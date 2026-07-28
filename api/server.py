import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.runtime import VaelorRuntime
from core.tools.registry import registry as tool_registry
from spellbook.command_parser import parse_command, parse_tool_command

app = FastAPI(title="Vaelor API", version="0.3.0")

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


class ChatResponse(BaseModel):
    mode: str
    response: str


@app.get("/health")
def health():
    return {
        "status": "online",
        "name": runtime.name,
        "title": runtime.title
    }


@app.get("/tools")
def list_tools():
    """
    Returns structured tool data for the dashboard.
    NOTE: this is a JSON array of objects, not the formatted text string
    that brain.list_tools() returns for chat/CLI use. If you add code
    elsewhere that calls this endpoint, it expects:
    { "tools": [ { "name": str, "description": str, "read_only": bool }, ... ] }
    """
    return {"tools": tool_registry.list_tools()}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    mode, prompt = parse_command(request.message)

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

    else:
        response = brain.think(prompt)

    return ChatResponse(mode=mode, response=response)


WEB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "web"
)

app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")