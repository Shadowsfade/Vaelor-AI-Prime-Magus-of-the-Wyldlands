import sys
import os
import io

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from core.runtime import VaelorRuntime
from core.tools.registry import registry as tool_registry
from spellbook.command_parser import parse_command, parse_tool_command
from spellbook.voice import synthesize_speech, list_wizard_voices, get_voice_settings

app = FastAPI(title="Vaelor API", version="0.9.0")

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


class ChatResponse(BaseModel):
    mode: str
    response: str


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
        response = brain.think(prompt)

    return mode, response


@app.get("/health")
def health():
    settings = get_voice_settings()
    return {
        "status": "online",
        "name": runtime.name,
        "title": runtime.title,
        "version": "0.9.0",
        "voice": {
            "enabled": True,
            "provider": "edge-tts",
            "default_voice": settings.get("voice"),
            "stt": "browser_web_speech",
        },
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


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    mode, response = route_message(request.message, session_id=getattr(request, "session_id", None), images=getattr(request, "images", None))
    return ChatResponse(mode=mode, response=response)


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

app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

