"""Vaelor Voice Spells — free-tool stack.

TTS: edge-tts (free). Default wizard voice: en-GB-RyanNeural.
Pronunciation: Vaelor is VAY-lore (not VEE-lore).
"""
from __future__ import annotations
import asyncio, concurrent.futures, io, json, os, re
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")

def _load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def get_voice_settings() -> dict:
    models = _load_json(os.path.join(CONFIG_DIR, "models.json"))
    voice = models.get("voice", {})
    return {
        "voice": voice.get("wizard_voice", "en-GB-RyanNeural"),
        "fallback": voice.get("wizard_voice_fallback", "en-GB-ThomasNeural"),
        "rate": voice.get("rate", "-8%"),
        "pitch": voice.get("pitch", "-5Hz"),
    }

def pronounce_for_speech(text: str) -> str:
    if not text:
        return text
    reps = [
        (r"\bVaelor's\b", "Vay-lore's"),
        (r"\bVAELOR'S\b", "VAY-LORE'S"),
        (r"\bVaelor\b", "Vay-lore"),
        (r"\bVAELOR\b", "VAY-LORE"),
        (r"\bvaelor\b", "vay-lore"),
        (r"\bWyldlands\b", "Wild-lands"),
        (r"\bWyld\b", "Wild"),
    ]
    for pat, rep in reps:
        text = re.sub(pat, rep, text)
    return text

def strip_for_speech(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"```[\s\S]*?```", " (arcane sigils inscribed) ", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[#*_>~]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 1800:
        text = text[:1800].rsplit(" ", 1)[0] + "..."
    return pronounce_for_speech(text)

async def _synthesize_async(text: str, voice: Optional[str] = None) -> bytes:
    import edge_tts
    settings = get_voice_settings()
    chosen = voice or settings["voice"]
    buf = io.BytesIO()
    try:
        communicate = edge_tts.Communicate(text, voice=chosen, rate=settings["rate"], pitch=settings["pitch"])
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
    except Exception:
        if chosen != settings["fallback"]:
            communicate = edge_tts.Communicate(text, voice=settings["fallback"], rate=settings["rate"], pitch=settings["pitch"])
            buf = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
        else:
            raise
    return buf.getvalue()

def synthesize_speech(text: str, voice: Optional[str] = None) -> bytes:
    clean = strip_for_speech(text)
    if not clean:
        clean = "The archive is silent."
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _synthesize_async(clean, voice)).result(timeout=60)
        return loop.run_until_complete(_synthesize_async(clean, voice))
    except RuntimeError:
        return asyncio.run(_synthesize_async(clean, voice))

def list_wizard_voices() -> list:
    return [
        {"id": "en-GB-RyanNeural", "label": "Ryan (British, deep — default wizard)", "locale": "en-GB"},
        {"id": "en-GB-ThomasNeural", "label": "Thomas (British, elder scholar)", "locale": "en-GB"},
        {"id": "en-GB-NoahNeural", "label": "Noah (British, calm mentor)", "locale": "en-GB"},
        {"id": "en-US-AndrewNeural", "label": "Andrew (American, warm guide)", "locale": "en-US"},
        {"id": "en-US-BrianNeural", "label": "Brian (American, measured)", "locale": "en-US"},
    ]
