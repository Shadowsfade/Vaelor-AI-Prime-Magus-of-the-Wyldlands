"""
Vaelor Voice Spells — free-tool stack

TTS: edge-tts (Microsoft Edge neural voices, free, no API key)
     Default wizard voice: en-GB-RyanNeural (deep, measured British male)
STT: Browser Web Speech API on the client (free, no server VRAM)
     Optional future: faster-whisper local if browser STT unavailable

No paid APIs. Designed for RTX 2060 6GB — TTS does not use GPU VRAM.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
SPELLBOOK_DIR = os.path.dirname(os.path.abspath(__file__))


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


def strip_for_speech(text: str) -> str:
    """Reduce markdown / code noise so the wizard voice sounds natural."""
    if not text:
        return ""

    # Remove fenced code blocks
    text = re.sub(r"```[\s\S]*?```", " (arcane sigils inscribed) ", text)
    # Inline code
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Markdown links
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Headings / emphasis markers
    text = re.sub(r"[#*_>~]+", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Soft length cap for call turns
    if len(text) > 1800:
        text = text[:1800].rsplit(" ", 1)[0] + "..."
    return text


async def _synthesize_async(text: str, voice: Optional[str] = None) -> bytes:
    import edge_tts

    settings = get_voice_settings()
    chosen = voice or settings["voice"]
    communicate = edge_tts.Communicate(
        text,
        voice=chosen,
        rate=settings["rate"],
        pitch=settings["pitch"],
    )

    buf = io.BytesIO()
    try:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
    except Exception:
        # Fallback voice if primary fails
        if chosen != settings["fallback"]:
            communicate = edge_tts.Communicate(
                text,
                voice=settings["fallback"],
                rate=settings["rate"],
                pitch=settings["pitch"],
            )
            buf = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
        else:
            raise

    return buf.getvalue()


def synthesize_speech(text: str, voice: Optional[str] = None) -> bytes:
    """Blocking helper for FastAPI endpoints. Returns MP3 bytes."""
    clean = strip_for_speech(text)
    if not clean:
        clean = "The archive is silent."

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Nested loop safety for already-running event loops
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _synthesize_async(clean, voice))
                return future.result(timeout=60)
        return loop.run_until_complete(_synthesize_async(clean, voice))
    except RuntimeError:
        return asyncio.run(_synthesize_async(clean, voice))


def list_wizard_voices() -> list:
    """Return preferred free wizard-like Edge voices."""
    return [
        {
            "id": "en-GB-RyanNeural",
            "label": "Ryan (British, deep — default wizard)",
            "locale": "en-GB",
        },
        {
            "id": "en-GB-ThomasNeural",
            "label": "Thomas (British, elder scholar)",
            "locale": "en-GB",
        },
        {
            "id": "en-GB-NoahNeural",
            "label": "Noah (British, calm mentor)",
            "locale": "en-GB",
        },
        {
            "id": "en-US-AndrewNeural",
            "label": "Andrew (American, warm guide)",
            "locale": "en-US",
        },
        {
            "id": "en-US-BrianNeural",
            "label": "Brian (American, measured)",
            "locale": "en-US",
        },
    ]


if __name__ == "__main__":
    audio = synthesize_speech(
        "Greetings, Apprentice. The Vaelor Archive awakens. The fires of knowledge burn brightly."
    )
    out = os.path.join(BASE_DIR, "web", "vaelor_greeting.mp3")
    with open(out, "wb") as f:
        f.write(audio)
    print(f"Wrote {len(audio)} bytes to {out}")
