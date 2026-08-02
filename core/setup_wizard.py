
"""Beginner-friendly free setup wizard for Vaelor.

Detects hardware, recommends model size, compares free backends
(Ollama vs LM Studio), and writes local config.
No paid services.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
CONFIG.mkdir(exist_ok=True)

try:
    from core.hardware import scan_hardware, recommend_models
except Exception:
    def scan_hardware():
        return {"os": os.name, "cpu": "unknown", "ram_gb": None, "vram_gb": 0, "gpus": []}
    def recommend_models(hw=None):
        return {"tier": "efficient", "recommended_primary": "7B-9B Q4", "notes": "Default conservative recommendation", "suggested_ollama_pulls": ["llama3.2:3b", "qwen2.5:7b"]}


PROVIDERS = [
    {
        "id": "ollama",
        "name": "Ollama",
        "best_for": "Easiest free local AI for most people (recommended)",
        "pros": [
            "Very simple install and model downloads",
            "Great for always-on local servers",
            "Works well with Vaelor automatically",
            "One-command model pull",
        ],
        "cons": [
            "Less visual model browser than LM Studio",
            "GUI is minimal",
        ],
        "install_url": "https://ollama.com/download",
        "windows_winget": "Ollama.Ollama",
        "default_endpoint": "http://localhost:11434",
        "check": "ollama",
    },
    {
        "id": "lmstudio",
        "name": "LM Studio",
        "best_for": "People who want a friendly app UI to browse models",
        "pros": [
            "Pretty desktop app",
            "Easy model search/download UI",
            "OpenAI-compatible local server",
        ],
        "cons": [
            "Heavier application",
            "You must start the local server manually",
            "Slightly more clicks for always-on use",
        ],
        "install_url": "https://lmstudio.ai/",
        "windows_winget": None,
        "default_endpoint": "http://localhost:1234",
        "check": "lmstudio",
    },
]


def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def detect_backends() -> Dict[str, Any]:
    import urllib.request
    out = {
        "ollama": {"installed": _which("ollama") is not None, "running": False, "models": [], "endpoint": "http://localhost:11434"},
        "lmstudio": {"installed": False, "running": False, "models": [], "endpoint": "http://localhost:1234"},
    }
    # ollama running?
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1.5) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
            out["ollama"]["running"] = True
            out["ollama"]["models"] = [m.get("name") for m in data.get("models", []) if m.get("name")]
    except Exception:
        pass
    # lmstudio openai compat
    try:
        with urllib.request.urlopen("http://localhost:1234/v1/models", timeout=1.5) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
            out["lmstudio"]["running"] = True
            out["lmstudio"]["installed"] = True
            out["lmstudio"]["models"] = [m.get("id") for m in data.get("data", []) if m.get("id")]
    except Exception:
        # heuristic install presence
        candidates = [
            os.path.expandvars(r"%LOCALAPPDATA%\\LM Studio\\LM Studio.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\\Programs\\LM Studio\\LM Studio.exe"),
            r"C:\\Program Files\\LM Studio\\LM Studio.exe",
        ]
        out["lmstudio"]["installed"] = any(os.path.isfile(p) for p in candidates)
    return out


def wizard_state() -> Dict[str, Any]:
    hw = scan_hardware()
    rec = recommend_models(hw)
    backends = detect_backends()
    complete_path = CONFIG / "setup_complete.json"
    complete = complete_path.exists()
    meta = {}
    if complete:
        try:
            meta = json.loads(complete_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    # plain-language model advice
    tier = rec.get("tier", "efficient")
    advice = {
        "cpu": "Your PC may be slow for big AI. Start tiny (1B-3B).",
        "light": "Use small models (3B-7B Q4).",
        "efficient": "Best balance: 7B-9B Q4 models (great for RTX 2060 6GB class).",
        "solid": "You can run 9B-14B Q4 comfortably.",
        "strong": "14B models are comfortable.",
        "heavy": "You can try large 32B-class models.",
    }.get(tier, "Start with a 7B Q4 model.")

    steps = beginner_steps(backends, rec)
    return {
        "setup_complete": complete,
        "setup_meta": meta,
        "hardware": hw,
        "recommendation": {**rec, "plain_english": advice},
        "providers": PROVIDERS,
        "backends": backends,
        "steps": steps,
        "quick_start": {
            "after_install": [
                "1) Install your chosen backend (Ollama recommended)",
                "2) Download/pull the recommended model",
                "3) Start Vaelor with Start-Vaelor.bat or installer\\Start-Vaelor.ps1",
                "4) Open http://localhost:8000 and click the tome",
                "5) Allow microphone if you want voice calling",
            ]
        },
    }


def beginner_steps(backends: dict, rec: dict) -> List[dict]:
    pulls = rec.get("suggested_ollama_pulls") or ["llama3.2:3b"]
    model = pulls[0]
    return [
        {
            "id": "choose_backend",
            "title": "Choose your free AI engine",
            "body": "Pick Ollama (easiest) or LM Studio (pretty app). Both are free and run on your computer.",
        },
        {
            "id": "install_backend",
            "title": "Install the engine",
            "body": "If you don't have one yet, install it. Vaelor can open the download page or try winget for Ollama.",
        },
        {
            "id": "get_model",
            "title": "Download a model that fits your PC",
            "body": f"Recommended starting model family: {rec.get('recommended_primary')}. For Ollama try: ollama pull {model}",
        },
        {
            "id": "start_vaelor",
            "title": "Start Vaelor",
            "body": "Run Start-Vaelor.bat. Open the web page, click the magical tome, and talk to Vaelor (Vay-lore).",
        },
        {
            "id": "optional_voice",
            "title": "Optional: voice calling",
            "body": "Use Chrome or Edge. Click Summon Call and allow the microphone.",
        },
    ]


def mark_complete(provider: str = "ollama", model: str = "llama3.2:3b") -> dict:
    provider = (provider or "ollama").lower()
    model = model or "llama3.2:3b"
    meta = {
        "completed_at": datetime.now().isoformat(),
        "provider": provider,
        "model": model,
        "free_only": True,
    }
    (CONFIG / "setup_complete.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # update models.json if present
    models_path = CONFIG / "models.json"
    try:
        cfg = json.loads(models_path.read_text(encoding="utf-8")) if models_path.exists() else {}
        cfg["provider"] = provider
        cfg.setdefault("llm", {})
        endpoint = "http://localhost:11434" if provider == "ollama" else "http://localhost:1234"
        for key in ("primary", "coding", "fast"):
            cfg["llm"].setdefault(key, {})
            cfg["llm"][key]["provider"] = provider
            cfg["llm"][key]["model"] = model
            cfg["llm"][key]["endpoint"] = endpoint
        cfg.setdefault("backends", {})
        cfg["backends"].setdefault("ollama", {"endpoint": "http://localhost:11434"})
        cfg["backends"].setdefault("lmstudio", {"endpoint": "http://localhost:1234"})
        models_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        # mirror
        spell = ROOT / "spellbook" / "models.json"
        if spell.parent.exists():
            spell.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception as e:
        meta["config_error"] = str(e)
    return meta


def try_install_ollama_winget() -> str:
    winget = shutil.which("winget")
    if not winget:
        return "winget not found. Please install Ollama from https://ollama.com/download"
    try:
        proc = subprocess.run(
            [winget, "install", "-e", "--id", "Ollama.Ollama", "--accept-package-agreements", "--accept-source-agreements"],
            capture_output=True, text=True, timeout=1200,
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return f"exit={proc.returncode}\n{out[-4000:]}"
    except Exception as e:
        return f"Install failed: {e}"


def try_pull_ollama_model(model: str = "llama3.2:3b") -> str:
    if not shutil.which("ollama"):
        return "Ollama is not installed or not on PATH."
    try:
        proc = subprocess.run(["ollama", "pull", model], capture_output=True, text=True, timeout=3600)
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return f"exit={proc.returncode}\n{out[-4000:]}"
    except Exception as e:
        return f"Pull failed: {e}"
