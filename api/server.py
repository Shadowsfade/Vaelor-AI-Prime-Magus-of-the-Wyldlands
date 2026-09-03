import sys
import os
import re
import io
import json
import asyncio

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Any, List, Optional

from core.runtime import VaelorRuntime
from core.setup_wizard import wizard_state, mark_complete, try_install_ollama_winget, try_pull_ollama_model, detect_backends
from core.tools.registry import registry as tool_registry
from spellbook.command_parser import parse_command, parse_tool_command
from spellbook.voice import synthesize_speech, list_wizard_voices, get_voice_settings

app = FastAPI(title="Vaelor API", version="1.1.1-alpha")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

runtime = VaelorRuntime()
brain = runtime.brain


class ChatRequest(BaseModel):
    message: str
    speak: bool = False
    voice: Optional[str] = None
    session_id: Optional[str] = None
    images: Optional[List[Any]] = None


class ChatResponse(BaseModel):
    mode: str
    response: str
    session_id: Optional[str] = None


class ProposalActionRequest(BaseModel):
    proposal_id: str


class SpeakRequest(BaseModel):
    text: str
    voice: Optional[str] = None


class CallRequest(BaseModel):
    """One turn of a continuous voice call (ChatGPT/Claude/Gemini style)."""
    transcript: str
    voice: Optional[str] = None
    mode: str = "call"  # call uses slightly shorter, spoken replies
    session_id: Optional[str] = None


class SessionCreateRequest(BaseModel):
    title: Optional[str] = None
    session_id: Optional[str] = None


class TaskResumeRequest(BaseModel):
    max_steps: int = Field(default=12, ge=3, le=25)


class TaskCreateRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    session_id: Optional[str] = None
    max_steps: int = Field(default=12, ge=3, le=25)
    workspace: Optional[str] = Field(default=None, max_length=4096)


class PreferenceCreateRequest(BaseModel):
    statement: str
    scope: str = "global"


class PreferenceStatusRequest(BaseModel):
    status: str


class TaskFeedbackRequest(BaseModel):
    rating: str
    comment: str = ""


class TaskCancelRequest(BaseModel):
    reason: str = Field(default="Cancelled by user.", max_length=1000)


class TaskClarifyRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=20000)
    max_steps: int = Field(default=12, ge=3, le=25)


@app.get("/preferences")
def list_preferences(status: Optional[str] = None):
    return {"preferences": brain.list_preferences(status)}


@app.post("/preferences")
def create_preference(request: PreferenceCreateRequest):
    try:
        return brain.add_preference(request.statement, request.scope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/preferences/{preference_id}")
def update_preference(preference_id: str, request: PreferenceStatusRequest):
    try:
        return brain.set_preference_status(preference_id, request.status)
    except KeyError:
        raise HTTPException(status_code=404, detail="Preference not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/tasks")
def create_task(request: TaskCreateRequest, background_tasks: BackgroundTasks):
    try:
        task = brain.prepare_task(request.message, request.session_id, request.workspace)
    except (ValueError, PermissionError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if task.get("status") != "waiting":
        background_tasks.add_task(brain.run_prepared_task, task["id"], request.max_steps)
    return task


@app.get("/tasks")
def list_tasks(limit: int = 50):
    return {"tasks": brain.list_tasks(limit)}


@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    task = brain.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/tasks/{task_id}/events")
async def stream_task_events(task_id: str, after: int = 0):
    if brain.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")

    async def events():
        cursor = max(0, int(after or 0))
        last_status = None
        while True:
            task = brain.get_task(task_id)
            if task is None:
                yield "event: error\ndata: {\"detail\":\"Task not found\"}\n\n"
                return
            recorded = task.get("events") or []
            while cursor < len(recorded):
                payload = {"cursor": cursor + 1, "event": recorded[cursor]}
                yield "event: progress\ndata: " + json.dumps(payload) + "\n\n"
                cursor += 1
            status = task.get("status")
            if status != last_status:
                yield "event: status\ndata: " + json.dumps({
                    "task_id": task_id,
                    "status": status,
                    "attempts": task.get("attempts", 0),
                }) + "\n\n"
                last_status = status
            if status in {"completed", "failed", "cancelled", "waiting"}:
                yield "event: result\ndata: " + json.dumps({
                    "task_id": task_id,
                    "status": status,
                    "result": task.get("result"),
                    "cursor": cursor,
                }) + "\n\n"
                return
            yield ": keep-alive\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.post("/tasks/{task_id}/resume")
def resume_task(task_id: str, request: TaskResumeRequest):
    try:
        return {"task_id": task_id, "response": brain.resume_task(task_id, request.max_steps)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")


@app.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, request: TaskCancelRequest):
    try:
        return brain.cancel_task(task_id, request.reason)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/tasks/{task_id}/clarify")
def clarify_task(task_id: str, request: TaskClarifyRequest, background_tasks: BackgroundTasks):
    try:
        task = brain.clarify_task(task_id, request.answer)
        if task.get("status") == "pending":
            background_tasks.add_task(brain.run_prepared_task, task_id, request.max_steps)
        return task
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/tasks/{task_id}/feedback")
def task_feedback(task_id: str, request: TaskFeedbackRequest):
    try:
        return brain.record_task_feedback(task_id, request.rating, request.comment)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def route_message(message: str, session_id=None, images=None):
    """Shared command routing used by /chat and /call."""
    message = (message or "").strip()
    mode, prompt = parse_command(message)

    if mode == "code":
        response = brain.create(prompt)

    elif mode == "remember":
        brain.remember("fact", prompt)
        response = f"Understood. I will remember: {prompt}"

    elif mode == "roadmap":
        response = brain.reflect(prompt)

    elif mode == "fast":
        response = brain.fast(prompt)

    elif mode == "tools":
        response = brain.list_tools()

    elif mode == "tool":
        tool_name, kwargs = parse_tool_command(prompt)
        if not tool_name:
            response = "Usage: tool: <tool_name> key=value"
        else:
            response = brain.use_tool(tool_name, **kwargs)

    elif mode == "stage":
        if not prompt:
            response = "Usage: stage: <path>"
        else:
            response = brain.stage_edit(prompt)

    elif mode == "propose":
        if not prompt:
            response = "Usage: propose: <path>"
        else:
            response = brain.propose_edit(prompt)

    elif mode == "approve":
        if not prompt:
            response = "Usage: approve: <proposal id>"
        else:
            response = brain.approve_change(prompt)

    elif mode == "reject":
        if not prompt:
            response = "Usage: reject: <proposal id>"
        else:
            response = brain.reject_change(prompt)

    elif mode == "diffs":
        response = brain.list_proposals()

    
    
    elif mode == "agent":
        response = brain.act(prompt or message, session_id=session_id)

    elif mode == "shell":
        cmd = prompt or ""
        confirm = "no"
        if "confirm=yes" in cmd.lower():
            confirm = "yes"
            cmd = re.sub(r"\|?\s*confirm=yes", "", cmd, flags=re.I).strip()
        response = brain.use_tool("shell_exec", command=cmd, confirm=confirm)

    elif mode == "git":
        parts = (prompt or "").strip().split(None, 1)
        sub = (parts[0].lower() if parts else "status")
        rest = parts[1] if len(parts) > 1 else ""
        if sub == "status":
            response = brain.use_tool("git_status")
        elif sub == "diff":
            response = brain.use_tool("git_diff")
        elif sub == "log":
            response = brain.use_tool("git_log")
        elif sub == "branch":
            response = brain.use_tool("git_branch")
        elif sub == "remote":
            response = brain.use_tool("git_remote")
        elif sub == "add":
            response = brain.use_tool("git_add", path=rest or ".", confirm="yes" if "confirm=yes" in rest.lower() else "no")
        elif sub == "commit":
            conf = "yes" if "confirm=yes" in rest.lower() else "no"
            msg = re.sub(r"confirm=yes", "", rest, flags=re.I).strip()
            response = brain.use_tool("git_commit", message=msg, confirm=conf)
        elif sub == "push":
            response = brain.use_tool("git_push", confirm="yes" if "confirm=yes" in rest.lower() else "no")
        elif sub == "pull":
            response = brain.use_tool("git_pull", confirm="yes" if "confirm=yes" in rest.lower() else "no")
        else:
            response = "Usage: git: status|diff|log|branch|remote|add|commit|push|pull (mutating needs confirm=yes)"

    elif mode == "search":
        q = prompt or message
        research = brain.research(q)
        response = (
            "I consulted the wider aether (web search).\n\n"
            + research
            + "\n\n"
            + brain.think(
                "Summarize and answer using the research above.\nQuestion: " + q,
                session_id=session_id,
                use_web=False,
            )
        )

    elif mode == "cleanup":
        response = brain.cleanup_workspace()

    elif any(
        trigger in message.lower()
        for trigger in [
            "modify file",
            "update file",
            "create file",
            "add feature",
            "fix bug",
            "edit codebase",
            "write code for",
        ]
    ):
        mode = "code_forge"
        code_output = brain.create(message)
        response = (
            f"**Generated Code & Proposed Modification:**\n\n"
            f"```python\n{code_output}\n```\n\n"
            f"To stage and create a pending proposal for this change, run:\n"
            f"`stage: <target_file_path>` then `propose: <target_file_path>`\n\n"
            f"Or approve existing pending proposals with `approve: <proposal_id>`."
        )

    else:
        response = brain.think(prompt, session_id=session_id, images=images)

    return mode, response


@app.get("/health")
def health():
    settings = get_voice_settings()
    return {
        "status": "online",
        "name": runtime.name,
        "title": runtime.title,
        "version": "1.1.1-alpha",
        "voice": {
            "enabled": True,
            "provider": "edge-tts",
            "default_voice": settings.get("voice"),
            "stt": "browser_web_speech",
            "wizard_voice": settings.get("voice"),
            "theme": "arcane_tome",
        },
        "ui": {"theme": "arcane_tome", "desktop_capable": True},
    }


@app.get("/tools")
def list_tools():
    return {"tools": tool_registry.list_tools()}


@app.get("/proposals")
def list_proposals():
    return {"proposals": brain.list_proposals()}


@app.post("/proposals/approve")
def approve_proposal(request: ProposalActionRequest):
    result = brain.approve_change(request.proposal_id)
    return {"status": "success", "result": result}


@app.post("/proposals/reject")
def reject_proposal(request: ProposalActionRequest):
    result = brain.reject_change(request.proposal_id)
    return {"status": "success", "result": result}


@app.get("/spells")
def list_spells():
    """Expose spellbook entries for the tome UI."""
    import json

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "spellbook",
        "spells.json",
    )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        return {"spells": {}, "error": str(e)}


@app.get("/voice/voices")
def voice_list():
    return {"voices": list_wizard_voices(), "settings": get_voice_settings()}


@app.post("/voice/speak")
def voice_speak(request: SpeakRequest):
    try:
        audio = synthesize_speech(request.text, voice=request.voice)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice spell failed: {e}")

    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline; filename=vaelor.mp3"},
    )


@app.get("/sessions")
def sessions_list():
    """List archive dialogues for the tome sidebar."""
    try:
        sessions = brain.conversations.list_sessions(limit=40)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"sessions list failed: {e}")
    return {"sessions": sessions}


@app.post("/sessions")
def sessions_create(request: SessionCreateRequest = None):
    """Create or ensure a dialogue session."""
    request = request or SessionCreateRequest()
    try:
        session = brain.conversations.ensure_session(
            session_id=request.session_id,
            title=request.title,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"session create failed: {e}")
    return session


@app.get("/sessions/{session_id}")
def sessions_get(session_id: str):
    """Load one dialogue and its turns for the UI."""
    try:
        sessions = brain.conversations.list_sessions(limit=200)
        session = next((s for s in sessions if s.get("id") == session_id), None)
        if not session:
            session = brain.conversations.ensure_session(session_id=session_id)
        turns = brain.conversations.recall_recent(limit=200, session_id=session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"session load failed: {e}")
    return {"session": session, "turns": turns}


@app.delete("/sessions/{session_id}")
def sessions_delete(session_id: str):
    try:
        brain.conversations.clear_session(session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"session delete failed: {e}")
    return {"status": "ok", "session_id": session_id}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    try:
        mode, response = route_message(
            request.message,
            session_id=request.session_id,
            images=request.images,
        )
        return ChatResponse(mode=mode, response=response, session_id=request.session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"chat failed: {e}")


@app.post("/chat/stream")
def chat_stream(request: ChatRequest):
    """SSE stream for tome UI Stream: On mode."""
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Empty message")

    mode, prompt = parse_command(message)

    # Non-think modes: return one-shot SSE then done (keeps UI simple)
    if mode != "think":
        _mode, response = route_message(
            message,
            session_id=request.session_id,
            images=request.images,
        )

        def one_shot():
            payload = json.dumps({"type": "token", "text": response, "mode": _mode})
            yield f"data: {payload}\n\n"
            done = json.dumps({"type": "done", "mode": _mode, "session_id": request.session_id})
            yield f"data: {done}\n\n"

        return StreamingResponse(one_shot(), media_type="text/event-stream")

    def event_stream():
        import json as _json

        try:
            # Prefer true token stream from brain when available
            if hasattr(brain, "think_stream") and not request.images:
                chunks = []
                for piece in brain.think_stream(prompt, session_id=request.session_id):
                    chunks.append(piece)
                    yield f"data: {_json.dumps({'type': 'token', 'text': piece, 'mode': 'think'})}\n\n"
                full = "".join(chunks)
                yield f"data: {_json.dumps({'type': 'done', 'mode': 'think', 'text': full, 'session_id': request.session_id})}\n\n"
            else:
                _mode, response = route_message(
                    message,
                    session_id=request.session_id,
                    images=request.images,
                )
                yield f"data: {_json.dumps({'type': 'token', 'text': response, 'mode': _mode})}\n\n"
                yield f"data: {_json.dumps({'type': 'done', 'mode': _mode, 'session_id': request.session_id})}\n\n"
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/call")
def voice_call(request: CallRequest):
    """
    Continuous call turn:
    1) Accept spoken transcript from browser STT
    2) Reason with Vaelor (prefer concise spoken style)
    3) Return text + MP3 wizard voice
    """
    transcript = (request.transcript or "").strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="Empty transcript")

    # Encourage spoken, wizardly brevity during calls
    spoken_prompt = (
        "The Apprentice is speaking to you in a live voice call. "
        "Reply as Vaelor in a calm elder-wizard voice. "
        "Keep the answer conversational and under about 120 words unless they ask for detail. "
        "Avoid markdown code fences unless essential.\n\n"
        f"Apprentice said: {transcript}"
    )

    # Allow command prefixes still work mid-call
    if any(
        transcript.lower().startswith(p)
        for p in (
            "code:",
            "remember:",
            "roadmap:",
            "fast:",
            "tool:",
            "tools",
            "stage:",
            "propose:",
            "approve:",
            "reject:",
            "diffs",
            "cleanup",
        )
    ):
        mode, response = route_message(transcript)
    else:
        mode = "call"
        response = brain.fast(spoken_prompt)

    try:
        audio = synthesize_speech(response, voice=request.voice)
    except Exception as e:
        # Still return text if TTS fails
        return {
            "mode": mode,
            "transcript": transcript,
            "response": response,
            "audio_base64": None,
            "error": f"TTS failed: {e}",
        }

    import base64

    return {
        "mode": mode,
        "transcript": transcript,
        "response": response,
        "audio_base64": base64.b64encode(audio).decode("ascii"),
        "audio_mime": "audio/mpeg",
    }


@app.get("/greeting")
def greeting():
    """Opening line when the tome opens."""
    text = runtime.personality.get(
        "greeting",
        "Greetings, Apprentice. The Vaelor Archive awakens.",
    )
    try:
        audio = synthesize_speech(text)
        import base64

        return {
            "text": text,
            "audio_base64": base64.b64encode(audio).decode("ascii"),
            "audio_mime": "audio/mpeg",
        }
    except Exception:
        return {"text": text, "audio_base64": None}


WEB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "web",
)



@app.get("/setup")
def setup_get():
    return wizard_state()


@app.get("/setup/backends")
def setup_backends():
    return detect_backends()


@app.post("/setup/complete")
def setup_complete(payload: dict):
    provider = (payload or {}).get("provider", "ollama")
    model = (payload or {}).get("model", "llama3.2:3b")
    return mark_complete(provider, model)


@app.post("/setup/install_ollama")
def setup_install_ollama():
    return {"result": try_install_ollama_winget()}


@app.post("/setup/pull_model")
def setup_pull_model(payload: dict):
    model = (payload or {}).get("model", "llama3.2:3b")
    return {"result": try_pull_ollama_model(model)}




@app.get("/diagnostics")
def diagnostics():
    """Client/model/host diagnostics for the Debug Console."""
    import json as _json
    from pathlib import Path as _Path
    info = {
        "ok": True,
        "time": __import__("datetime").datetime.now().isoformat(),
        "version": "1.1.4-alpha",
        "health": None,
        "backends": None,
        "network": None,
        "system": None,
        "tools_count": 0,
        "errors": [],
    }
    try:
        settings = get_voice_settings()
        info["health"] = {
            "status": "online",
            "name": runtime.name,
            "title": runtime.title,
            "voice": settings.get("voice"),
            "provider": "edge-tts",
        }
    except Exception as e:
        info["errors"].append(f"health: {e}")
    try:
        info["backends"] = detect_backends()
    except Exception as e:
        info["errors"].append(f"backends: {e}")
    try:
        net_path = _Path(__file__).resolve().parents[1] / "config" / "network.json"
        if net_path.exists():
            info["network"] = _json.loads(net_path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        info["errors"].append(f"network: {e}")
    try:
        from core.tools.diagnostics_tools import system_status
        info["system"] = system_status()
    except Exception as e:
        info["errors"].append(f"system: {e}")
    try:
        info["tools_count"] = len(tool_registry.list_tools())
        info["tools"] = [t.get("name") for t in tool_registry.list_tools()]
    except Exception as e:
        info["errors"].append(f"tools: {e}")
    try:
        from core.hardware import scan_hardware, recommend_models
        hw = scan_hardware()
        info["hardware"] = hw
        info["recommendation"] = recommend_models(hw)
    except Exception as e:
        info["errors"].append(f"hardware: {e}")
    # Ollama/LM quick probe summary
    b = info.get("backends") or {}
    o = b.get("ollama") or {}
    l = b.get("lmstudio") or {}
    info["model_summary"] = {
        "ollama_running": bool(o.get("running") or o.get("ok")),
        "ollama_models": o.get("models") or [],
        "lmstudio_running": bool(l.get("running") or l.get("ok")),
        "lmstudio_models": l.get("models") or [],
        "any_model": bool((o.get("models") or l.get("models"))),
    }
    info["ok"] = len(info["errors"]) == 0 or info["model_summary"]["any_model"] or True
    return info


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")



