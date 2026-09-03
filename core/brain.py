from spellbook.spell_router import cast_spell, cast_spell_stream

from .memory_manager import VaelorMemoryManager
from .conversation_memory import VaelorConversationMemory
from .task_intent import TaskIntent, classify_task
from .task_store import TaskStore
from .preference_store import PreferenceStore
from .project_context import build_project_context, resolve_workspace


class VaelorBrain:
    """Primary reasoning interface for Vaelor."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.memory = VaelorMemoryManager()
        self.conversations = VaelorConversationMemory()
        self.tasks = TaskStore()
        self.preferences = PreferenceStore()

    def _history_messages(self, session_id=None, limit=8):
        if session_id:
            return self.conversations.recall_session_messages(session_id, limit=limit)
        turns = self.conversations.recall_recent(limit)
        messages = []
        for t in turns:
            messages.append({"role": "user", "content": t.get("prompt", "")})
            messages.append({"role": "assistant", "content": t.get("response", "")})
        return messages

    def _history_text(self, session_id=None, limit=6):
        turns = (
            self.conversations.recall_recent(limit, session_id=session_id)
            if session_id
            else self.conversations.recall_recent(limit)
        )
        summary = self.conversations.get_summary(session_id) if session_id else ""
        if not turns and not summary:
            return ""
        out = ""
        if summary:
            out += "\nEarlier conversation summary:\n" + summary + "\n"
        out += "\nRecent conversation history:\n"
        for turn in turns:
            out += (
                "\nUser: "
                + turn.get("prompt", "")
                + "\nVaelor: "
                + turn.get("response", "")
                + "\n"
            )
        return out

    def _identity_block(self):
        ident = getattr(self.runtime, "identity", {}) or {}
        pers = getattr(self.runtime, "personality", {}) or {}
        return (
            "Identity anchor:\n"
            f"- Name: {ident.get('name', 'Vaelor')}\n"
            f"- Title: {ident.get('title', 'Prime Magus of the Wyldlands')}\n"
            "- Permanent persona: ancient, wise, powerful warlock, revered throughout the Wyldlands\n"
            f"- Address Architect as: Apprentice (never Master)\n"
            "- Knowledge posture: all-knowing mentor; seek and verify what is missing rather than guessing\n"
            "- Judgment: reason beyond the Apprentice's first proposal and recommend a better path when useful\n"
            f"- Tone: {(pers.get('personality') or {}).get('tone', 'wise, calm, patient')}\n"
        )

    def needs_web(self, prompt: str) -> bool:
        p = (prompt or "").lower()
        triggers = [
            "search the web", "look up", "latest", "current news", "today",
            "who is", "what is the current", "scrape", "browse", "according to the internet",
            "recent version", "as of 202", "weather", "price of", "news about",
        ]
        # also if user asks factual unknown + question mark
        if any(t in p for t in triggers):
            return True
        if p.strip().endswith("?") and any(
            w in p for w in ["who", "when", "where", "latest", "current", "news", "released"]
        ):
            # only if memory has weak coverage
            ctx = self.memory.build_context(prompt, limit=3)
            return len(ctx) < 40
        return False

    def research(self, query: str) -> str:
        from core.tools.web_research import web_search
        return web_search(query=query, limit=5)

    def _context_prefix(self, prompt, use_web=False):
        parts = [self._identity_block(), self._advisor_block()]
        preferences = self.preferences.context()
        if preferences:
            parts.append(preferences)
        mem = self.memory.build_context(prompt, limit=8)
        if mem:
            parts.append(mem)
        if use_web or self.needs_web(prompt):
            try:
                web = self.research(prompt)
                parts.append("External web research (free search):\n" + web)
            except Exception as e:
                parts.append(f"External web research unavailable: {e}")
        return "\n\n".join(parts) + "\n\n"

    @staticmethod
    def _advisor_block():
        return (
            "Advisory behavior:\n"
            "- Treat the user's requested outcome as the goal, not necessarily their proposed method.\n"
            "- Proactively recommend safer, simpler, faster, or more maintainable paths when useful.\n"
            "- Mention relevant tradeoffs, prerequisites, and system/hardware constraints plainly.\n"
            "- Do not manufacture objections: answer directly when the requested path is already sound.\n"
        )

    def think(self, prompt, session_id=None, images=None, use_web=None):
        # Only direct first-person preference declarations auto-activate.
        # Inferred lessons remain proposed until the user confirms them.
        preferences = getattr(self, "preferences", None)
        if preferences is not None:
            try:
                preferences.learn_explicit(prompt)
            except Exception:
                # Adaptation is supplementary; storage trouble must not block a turn.
                pass
        # Build an explicit task contract before deciding whether to use tools.
        task = None
        if not images:
            task = self.understand_task(prompt)
        if task and task.needs_clarification:
            response = task.clarification_question
            self.conversations.remember_turn(prompt, response, session_id=session_id)
            return response
        if task and task.should_act:
            try:
                return self.act(prompt, session_id=session_id, task_contract=task)
            except Exception as exc:
                response = (
                    "Vaelor could not complete the requested action because the agent loop "
                    f"failed: {exc}"
                )
                self.conversations.remember_turn(prompt, response, session_id=session_id)
                return response
        if use_web is None:
            use_web = self.needs_web(prompt)
        enhanced = (
            self._context_prefix(prompt, use_web=use_web)
            + self._history_text(session_id, limit=6)
            + "\nCurrent request:\n"
            + prompt
            + "\n\nAnswer as Vaelor using archive context first. "
              "If web research is present, use it for facts you lack and mention uncertainty when needed."
        )
        history = self._history_messages(session_id, limit=8)
        response = cast_spell(
            "vision" if images else "core_reasoning",
            enhanced,
            images=images,
            history=history,
        )
        self.conversations.remember_turn(prompt, response, session_id=session_id)
        return response

    def create(self, prompt, session_id=None):
        enhanced = self._context_prefix(prompt) + "Coding request:\n" + prompt
        response = cast_spell("code_forge", enhanced)
        self.conversations.remember_turn(prompt, response, session_id=session_id)
        return response

    def fast(self, prompt, session_id=None):
        enhanced = (
            self._context_prefix(prompt, use_web=False)
            + self._history_text(session_id, limit=3)
            + "\nAnswer briefly and clearly as Vaelor.\n\nRequest:\n"
            + prompt
        )
        history = self._history_messages(session_id, limit=4)
        response = cast_spell("fast_thought", enhanced, history=history)
        self.conversations.remember_turn(prompt, response, session_id=session_id)
        return response

    def see(self, prompt, images, session_id=None):
        enhanced = self._context_prefix(prompt) + "Vision request:\n" + prompt
        response = cast_spell("vision", enhanced, images=images)
        self.conversations.remember_turn(f"[vision] {prompt}", response, session_id=session_id)
        return response

    def think_stream(self, prompt, session_id=None, use_web=None):
        if use_web is None:
            use_web = self.needs_web(prompt)
        enhanced = (
            self._context_prefix(prompt, use_web=use_web)
            + self._history_text(session_id, limit=6)
            + "\nCurrent request:\n"
            + prompt
        )
        history = self._history_messages(session_id, limit=8)
        chunks = []
        for piece in cast_spell_stream("core_reasoning", enhanced, history=history):
            chunks.append(piece)
            yield piece
        self.conversations.remember_turn(prompt, "".join(chunks), session_id=session_id)

    def remember(self, category, content):
        return self.memory.remember(category, content)

    def recall(self, category=None, query=None, limit=10):
        if query:
            archive = self.memory.recall(category)
            ranked = sorted(
                archive,
                key=lambda m: self.memory.score_memory(m, query),
                reverse=True,
            )
            return ranked[:limit]
        data = self.memory.recall(category)
        return data[:limit] if isinstance(data, list) else data

    def reflect(self, prompt, session_id=None):
        roadmap = self.runtime.roadmap or {}
        roadmap_text = (
            "Current Vaelor version: "
            + str(roadmap.get("current_version", "unknown"))
            + "\n\nCompleted:\n"
            + "\n".join("- " + i for i in roadmap.get("completed", []))
            + "\n\nIn progress:\n"
            + "\n".join("- " + i for i in roadmap.get("in_progress", []))
            + "\n\nNext goals:\n"
            + "\n".join("- " + i for i in roadmap.get("next_goals", []))
        )
        enhanced = (
            "You are being asked about your own development status.\n\nRoadmap:\n"
            + roadmap_text
            + "\n\nQuestion:\n"
            + prompt
        )
        response = cast_spell("core_reasoning", enhanced)
        self.conversations.remember_turn(prompt, response, session_id=session_id)
        return response

    


    def build_system_prompt(self) -> str:
        """ReAct system prompt with full dynamic tool inventory."""
        from core.agent_loop import build_react_system_prompt
        from core.tools.registry import registry
        try:
            self._ensure_web_tools()
        except Exception:
            pass
        return build_react_system_prompt(registry.specs_for_prompt())

    def wants_action(self, prompt: str) -> bool:
        """Detect when the Apprentice wants Vaelor to DO work, not only talk."""
        p = (prompt or "").lower().strip()
        if not p:
            return False
        action_verbs = [
            "run ", "execute", "install", "commit", "push", "pull", "clone",
            "create file", "edit file", "modify", "fix", "debug", "search for",
            "look up", "find where", "list files", "show git", "check status",
            "delete", "rename", "build", "test ", "scan", "inspect",
            "implement", "refactor", "write a", "make a", "set up", "setup",
            "do everything", "take action", "use your tools", "agent:",
            "shell:", "git:", "tool:", "unreal", "game", "homebrew", "cfw", "modchip", "console",
        ]
        if any(v in p for v in action_verbs):
            return True
        if p.startswith(("please ", "can you ", "could you ", "i need you to ", "go ahead")) and any(
            w in p for w in ["run", "fix", "create", "update", "check", "git", "shell", "file", "code", "install"]
        ):
            return True
        return False

    def understand_task(self, prompt: str) -> TaskIntent:
        """Translate natural language into an explicit, validated task contract."""
        return classify_task(
            request=prompt,
            ask_classifier=lambda request: cast_spell("fast_thought", request),
            fallback_should_act=self.wants_action(prompt),
        )

    def act(self, goal, session_id=None, max_steps=12, task_contract=None, task_id=None,
            workspace=None, max_runtime_seconds=900):
        """Autonomous ReAct coding worker loop (tools + self-correct + verify)."""
        from core.agent_loop import run_agent
        from spellbook.spell_router import cast_spell

        if not isinstance(task_contract, TaskIntent):
            task_contract = TaskIntent(
                intent="act",
                goal=goal,
                success_criteria=["The requested outcome is complete and verified."],
                source="explicit",
            )
        task = self.tasks.get(task_id) if task_id else None
        if task is None:
            task = self.tasks.create(
                goal, task_contract.to_dict(), session_id, workspace, max_runtime_seconds
            )
        task_id = task["id"]
        workspace = task.get("workspace") or workspace
        max_runtime_seconds = task.get("max_runtime_seconds") or max_runtime_seconds
        self.tasks.update(task_id, status="running")
        self.tasks.add_event(task_id, "started", {"goal": task_contract.goal})

        react = self.build_system_prompt()
        ctx = (
            react
            + "\n\n"
            + build_project_context(workspace)
            + self._system_context()
            + self._context_prefix(goal, use_web=False)
            + self._history_text(session_id, limit=4)
        )

        def ask_llm(prompt: str) -> str:
            g = (goal or "").lower()
            spell = "code_forge" if any(
                k in g for k in ("implement", "refactor", "fix", "test", "code", "patch", "file")
            ) else "core_reasoning"
            return cast_spell(spell, prompt)

        agent_goal = task_contract.as_agent_goal(goal)
        try:
            result = run_agent(
                goal=agent_goal,
                ask_llm=ask_llm,
                max_steps=max_steps or 12,
                session_context=ctx,
                require_verification=True,
                event_callback=lambda event, data: self.tasks.add_event(task_id, event, data),
                should_cancel=lambda: self.tasks.is_cancelled(task_id),
                max_runtime_seconds=max_runtime_seconds,
                approval_required=lambda action: self.tasks.request_approval(task_id, action),
                consume_approval=lambda fingerprint: self.tasks.consume_action_approval(
                    task_id, fingerprint
                ),
            )
        except Exception as exc:
            self.tasks.add_event(task_id, "crashed", {"error": str(exc)})
            if not self.tasks.is_cancelled(task_id):
                self.tasks.update(task_id, status="failed", result=f"Agent error: {exc}")
            raise
        if result.upper().startswith("FINAL_SUMMARY: WAITING_APPROVAL"):
            status = "waiting"
        elif result.upper().startswith("FINAL_SUMMARY: CANCELLED") or self.tasks.is_cancelled(task_id):
            status = "cancelled"
        else:
            status = "completed" if result.upper().startswith("FINAL_SUMMARY: SUCCESS") else "failed"
        self.tasks.update(task_id, status=status, result=result)
        self.conversations.remember_turn(f"[agent] {goal}", result, session_id=session_id)
        return result

    @staticmethod
    def _system_context():
        try:
            from core.hardware import recommend_models, scan_hardware
            hardware = scan_hardware()
            advice = recommend_models(hardware)
            return (
                "## Current system constraints\n"
                f"OS: {hardware.get('os')}\n"
                f"RAM: {hardware.get('ram_gb')} GB total; "
                f"{hardware.get('ram_available_gb')} GB available\n"
                f"VRAM: {hardware.get('vram_gb')} GB\n"
                f"Execution advice: {advice.get('notes')}\n"
            )
        except Exception:
            return ""

    def list_tasks(self, limit=50):
        return self.tasks.list(limit)

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def cancel_task(self, task_id, reason="Cancelled by user."):
        return self.tasks.cancel(task_id, reason)

    def approve_task_action(self, task_id, fingerprint):
        return self.tasks.approve_action(task_id, fingerprint)

    def reject_task_action(self, task_id, fingerprint):
        return self.tasks.reject_action(task_id, fingerprint)

    def clarify_task(self, task_id, answer):
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(f"Unknown task: {task_id}")
        if task.get("status") != "waiting":
            raise ValueError("Task is not waiting for clarification.")
        if task.get("waiting_reason") == "approval":
            raise ValueError("Task is waiting for action approval, not clarification.")
        answer = str(answer or "").strip()
        if not answer:
            raise ValueError("Clarification answer cannot be empty.")
        original = task.get("request", "")
        question = (task.get("contract") or {}).get("clarification_question", "Clarification")
        revised_request = f"{original}\n\nClarification requested: {question}\nUser answer: {answer}"
        contract = self.understand_task(revised_request)
        if contract.intent != "act":
            contract.intent = "act"
        if contract.needs_clarification:
            return self.tasks.keep_waiting(
                task_id,
                revised_request,
                contract.to_dict(),
                contract.clarification_question,
            )
        return self.tasks.revise(task_id, revised_request, contract.to_dict())

    def list_preferences(self, status=None):
        return self.preferences.list(status)

    def add_preference(self, statement, scope="global"):
        return self.preferences.add(statement, scope=scope, source="user_explicit")

    def set_preference_status(self, preference_id, status):
        return self.preferences.set_status(preference_id, status)

    def record_task_feedback(self, task_id, rating, comment=""):
        if self.tasks.get(task_id) is None:
            raise KeyError(f"Unknown task: {task_id}")
        feedback = self.preferences.record_feedback(task_id, rating, comment)
        self.tasks.add_event(task_id, "user_feedback", {
            "rating": feedback["rating"],
            "comment": feedback["comment"],
        })
        return feedback

    def prepare_task(self, request, session_id=None, workspace=None, max_runtime_seconds=900):
        """Create a durable task before background execution begins."""
        contract = self.understand_task(request)
        if contract.intent != "act":
            contract = TaskIntent(
                intent="act",
                goal=contract.goal or request,
                success_criteria=contract.success_criteria,
                constraints=contract.constraints,
                needs_clarification=contract.needs_clarification,
                clarification_question=contract.clarification_question,
                source="task_api",
            )
        if workspace:
            resolve_workspace(workspace)
        task = self.tasks.create(
            request, contract.to_dict(), session_id, workspace, max_runtime_seconds
        )
        if contract.needs_clarification:
            self.tasks.update(
                task["id"],
                status="waiting",
                result=contract.clarification_question,
            )
            self.tasks.add_event(
                task["id"],
                "clarification_required",
                {"question": contract.clarification_question},
            )
        return self.tasks.get(task["id"])

    def run_prepared_task(self, task_id, max_steps=12):
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(f"Unknown task: {task_id}")
        if task.get("status") == "waiting":
            return task.get("result") or "Task is waiting for user input."
        return self.act(
            task.get("request", ""),
            session_id=task.get("session_id"),
            max_steps=max_steps,
            task_contract=TaskIntent.from_dict(task.get("contract") or {}),
            task_id=task_id,
            workspace=task.get("workspace"),
            max_runtime_seconds=task.get("max_runtime_seconds") or 900,
        )

    def resume_task(self, task_id, max_steps=12):
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(f"Unknown task: {task_id}")
        if task.get("status") == "completed":
            return task.get("result") or "FINAL_SUMMARY: SUCCESS Task was already complete."
        if task.get("status") == "cancelled":
            return task.get("result") or "FINAL_SUMMARY: CANCELLED Task was cancelled."
        return self.run_prepared_task(task_id, max_steps)

    def list_tools(self):
        from core.tools.registry import registry
        try:
            import core.tools.memory_checker  # noqa
            import core.tools.web_research  # noqa
        except Exception:
            pass
        # ensure web tools registered
        self._ensure_web_tools()
        tools = registry.list_tools()
        if not tools:
            return "No tools are currently registered in the archive."
        lines = ["Registered tools of the Grand Archive:\n"]
        for tool in tools:
            access = "read-only" if tool.get("read_only") else "needs approval"
            lines.append(f"- {tool['name']} ({access}): {tool['description']}")
        return "\n".join(lines)

    def _ensure_web_tools(self):
        from core.tools.registry import registry
        from core.tools.web_research import web_search, fetch_url
        if registry.get("web_search") is None:
            registry.register(
                "web_search",
                "Search the public internet (free DuckDuckGo). Args: query=..., optional limit=5",
                True,
                web_search,
            )
        if registry.get("fetch_url") is None:
            registry.register(
                "fetch_url",
                "Fetch and read a public http(s) page as text. Args: url=...",
                True,
                fetch_url,
            )

    def use_tool(self, tool_name, **kwargs):
        from core.tools.registry import registry
        self._ensure_web_tools()
        try:
            import core.tools.memory_checker  # noqa
        except Exception:
            pass
        result = registry.execute(tool_name, **kwargs)
        self.conversations.remember_turn(f"tool: {tool_name} {kwargs}", str(result))
        return str(result)

    def stage_edit(self, path):
        from core.tools.file_editor import stage_file
        return stage_file(path)

    def propose_edit(self, path):
        from core.tools.file_editor import propose_edit as _propose
        return _propose(path)

    def approve_change(self, proposal_id):
        from core.tools.approval import approve_change as _approve
        return _approve(proposal_id)

    def reject_change(self, proposal_id):
        from core.tools.approval import reject_change as _reject
        return _reject(proposal_id)

    def list_proposals(self):
        from core.tools.proposals import list_pending
        pending = list_pending()
        if not pending:
            return "No pending proposals."
        lines = ["Pending proposals:\n"]
        for p in pending:
            lines.append(f"- {p['id']}: {p['path']} (proposed {p.get('timestamp', 'unknown')})")
        return "\n".join(lines)

    def cleanup_workspace(self):
        from core.tools.cleaner import scan_unused_files
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates = scan_unused_files(root)
        if not candidates:
            return "The archive is tidy. No unused cleanup candidates found."
        lines = ["Cleanup candidates (review before deleting):\n"]
        for item in candidates:
            lines.append(f"- {item['file']}: {item['reason']}")
        return "\n".join(lines)



