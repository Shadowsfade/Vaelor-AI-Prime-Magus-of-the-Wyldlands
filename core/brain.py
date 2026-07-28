from spellbook.spell_router import cast_spell

from .memory_manager import VaelorMemoryManager
from .tools.registry import registry as tool_registry


class VaelorBrain:
    """
    Primary reasoning interface for Vaelor.

    Handles:
    - reasoning requests (core_reasoning, 14B)
    - fast/lightweight requests (fast_thought, 3B)
    - coding requests (code_forge)
    - archive recall
    - roadmap / self-awareness of project status
    - tool use (observe -> act, read-only for now)
    - proposal-based write tools (stage -> propose -> approve/reject)
    """

    def __init__(self, runtime):
        self.runtime = runtime
        self.memory = VaelorMemoryManager()

    def think(self, prompt):
        memory_context = self.memory.build_context(prompt)

        enhanced_prompt = (
            memory_context
            + "\n\nCurrent request:\n"
            + prompt
        )

        response = cast_spell(
            "core_reasoning",
            enhanced_prompt
        )

        return response

    def fast(self, prompt):
        return cast_spell(
            "fast_thought",
            prompt
        )

    def create(self, prompt):
        return cast_spell(
            "code_forge",
            prompt
        )

    def remember(self, category, content):
        return self.memory.remember(
            category,
            content
        )

    def reflect(self, prompt):
        roadmap = self.runtime.roadmap

        roadmap_text = (
            "Current Vaelor version: " + roadmap.get("current_version", "unknown")
            + "\n\nCompleted:\n"
            + "\n".join("- " + item for item in roadmap.get("completed", []))
            + "\n\nIn progress:\n"
            + "\n".join("- " + item for item in roadmap.get("in_progress", []))
            + "\n\nNext goals:\n"
            + "\n".join("- " + item for item in roadmap.get("next_goals", []))
            + "\n\nHardware constraints:\n"
            + roadmap.get("hardware_constraints", "")
        )

        enhanced_prompt = (
            "You are being asked about your own development status. "
            "Here is your current roadmap:\n\n"
            + roadmap_text
            + "\n\nQuestion:\n"
            + prompt
        )

        return cast_spell(
            "core_reasoning",
            enhanced_prompt
        )

    def list_tools(self):
        tools = tool_registry.list_tools()

        if not tools:
            return "No tools are registered yet."

        lines = []
        for tool in tools:
            access = "read-only" if tool["read_only"] else "requires approval"
            lines.append(f"- {tool['name']} ({access}): {tool['description']}")

        return "Available tools:\n" + "\n".join(lines)

    def use_tool(self, tool_name, **kwargs):
        return tool_registry.execute(tool_name, **kwargs)

    def stage_edit(self, path):
        """
        Step 1 of the edit workflow. Creates a staging copy of a file
        for the Architect to edit in Notepad. Writes only inside
        .staging\\ - never touches the real project file.
        """
        from .tools.file_editor import stage_file
        return stage_file(path)

    def propose_edit(self, path):
        """
        Step 2 of the edit workflow. Reads the edited staging copy and
        creates a pending proposal with a diff. Writes nothing to the
        real project file.
        """
        from .tools.file_editor import propose_edit as _propose
        return _propose(path)

    def approve_change(self, proposal_id):
        """
        Apply a pending proposal. This is the only path that writes
        a real project file, and it only runs when explicitly called.
        """
        from .tools.approval import approve_change as _approve
        return _approve(proposal_id)

    def reject_change(self, proposal_id):
        from .tools.approval import reject_change as _reject
        return _reject(proposal_id)

    def list_proposals(self):
        from .tools.proposals import list_pending
        pending = list_pending()

        if not pending:
            return "No pending proposals."

        lines = []
        for p in pending:
            lines.append(f"- {p['id']}: {p['path']} (proposed {p['timestamp']})")

        return "Pending proposals:\n" + "\n".join(lines)