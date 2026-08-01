"""Hardware probe + free local model recommendations for Vaelor setup wizard."""
from __future__ import annotations
import json, os, platform, shutil
from typing import List

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

def _gpu_nvidia() -> List[dict]:
    """Best-effort GPU probe without hanging on nvidia-smi."""
    gpus = []
    # Prefer Windows CIM - usually instant; skip nvidia-smi (can hang headless)
    if os.name == "nt":
        try:
            import subprocess
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            ps = (
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name,AdapterRAM | ConvertTo-Json -Compress"
            )
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", ps],
                stderr=subprocess.DEVNULL, text=True, timeout=3, creationflags=flags,
            )
            data = json.loads(out) if out.strip() else []
            if isinstance(data, dict):
                data = [data]
            for item in data or []:
                name = item.get("Name") or "GPU"
                ram = item.get("AdapterRAM") or 0
                # AdapterRAM is unreliable for >4GB; detect 2060 by name
                vram_mb = 0
                lname = name.lower()
                if "2060" in lname:
                    vram_mb = 6144
                elif "3060" in lname:
                    vram_mb = 12288
                elif "3070" in lname:
                    vram_mb = 8192
                elif "3080" in lname:
                    vram_mb = 10240
                elif "4070" in lname:
                    vram_mb = 12288
                elif ram and ram > 0:
                    vram_mb = round(ram / (1024 * 1024))
                    if vram_mb < 0:  # overflow
                        vram_mb = 6144
                if "microsoft" in lname or "basic" in lname:
                    continue
                gpus.append({"name": name, "vram_mb": vram_mb, "vendor": "unknown", "assumed": vram_mb in (6144, 12288, 8192, 10240)})
        except Exception:
            pass
    return gpus

def scan_hardware() -> dict:
    ram_total = ram_available = None
    if HAS_PSUTIL:
        try:
            vm = psutil.virtual_memory()
            ram_total = round(vm.total / (1024**3), 2)
            ram_available = round(vm.available / (1024**3), 2)
        except Exception:
            pass
    gpus = _gpu_nvidia()
    if not gpus:
        gpus = [{"name": "NVIDIA GeForce RTX 2060 (fallback profile)", "vram_mb": 6144, "vendor": "nvidia", "assumed": True}]
    vram = max([(g.get("vram_mb") or 0) for g in gpus], default=0)
    return {
        "os": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "ram_gb": ram_total,
        "ram_available_gb": ram_available,
        "gpus": gpus,
        "vram_mb": vram,
        "vram_gb": round(vram / 1024, 2) if vram else 0,
    }

def recommend_models(hw=None) -> dict:
    hw = hw or scan_hardware()
    vram = hw.get("vram_mb") or 0
    ram = hw.get("ram_gb") or 0
    if vram >= 22000:
        tier, primary, sizes = "heavy", "32B Q4_K_M", ["32B-Q4", "14B-Q5", "9B-Q8"]
        note = "High VRAM — large models comfortable."
    elif vram >= 12000:
        tier, primary, sizes = "strong", "14B Q4_K_M / Q5", ["14B-Q4", "14B-Q5", "9B-Q5"]
        note = "Good headroom for 14B chat + light tools."
    elif vram >= 8000:
        tier, primary, sizes = "solid", "9B–14B Q4_K_M", ["14B-Q4", "9B-Q4", "7B-Q5"]
        note = "14B Q4 possible; prefer 9B with vision+voice."
    elif vram >= 6000:
        tier, primary, sizes = "efficient", "7B–9B Q4_K_M (recommended)", ["9B-Q4", "7B-Q4", "3B-Q4"]
        note = "RTX 2060 6GB class — Vaelor Prime 9B Q4 is ideal."
    elif vram >= 4000:
        tier, primary, sizes = "light", "3B–7B Q4", ["7B-Q4", "3B-Q4"]
        note = "Stay on small quants; lower context."
    else:
        tier, primary, sizes = "cpu", "1B–3B Q4 CPU", ["3B-Q4", "1B-Q4"]
        note = "No usable GPU VRAM — CPU mode will be slow."
    if ram and ram < 16 and tier in ("heavy", "strong"):
        note += " System RAM is modest; keep context shorter."
    pulls = {
        "heavy": ["qwen2.5:32b-instruct-q4_K_M", "qwen2.5-coder:14b"],
        "strong": ["qwen2.5:14b", "qwen2.5-coder:14b", "qwen2.5:7b"],
        "solid": ["qwen2.5:14b", "qwen2.5:7b", "qwen2.5-coder:7b"],
        "efficient": ["vaelor-prime:latest", "qwen2.5:7b", "qwen2.5:3b"],
        "light": ["qwen2.5:3b", "qwen2.5:7b"],
        "cpu": ["qwen2.5:3b", "tinyllama"],
    }.get(tier, ["qwen2.5:7b"])
    return {
        "tier": tier,
        "recommended_primary": primary,
        "candidate_sizes": sizes,
        "notes": note,
        "suggested_ollama_pulls": pulls,
        "hardware": {"vram_mb": vram, "ram_gb": ram, "gpu_names": [g.get("name") for g in hw.get("gpus") or []]},
    }

def provider_comparison() -> List[dict]:
    return [
        {"id": "ollama", "name": "Ollama",
         "pros": ["Simple CLI and always-on local API", "Great for servers / headless Vaelor", "Easy model pull", "Native vision on many models"],
         "cons": ["Less visual model browser", "GUI is minimal"],
         "best_for": "Vaelor server, automation, Tailscale remote access",
         "default_endpoint": "http://localhost:11434"},
        {"id": "lmstudio", "name": "LM Studio",
         "pros": ["Polished desktop UI", "OpenAI-compatible local server", "Easy GGUF browsing"],
         "cons": ["Heavier app", "Server must be started manually", "Less ideal always-on"],
         "best_for": "Desktop tinkering and visual model management",
         "default_endpoint": "http://localhost:1234"},
    ]

def setup_status() -> dict:
    from spellbook.llm_client import backend_status
    hw = scan_hardware()
    rec = recommend_models(hw)
    try:
        backends = backend_status()
    except Exception as e:
        backends = {"error": str(e)}
    setup_flag = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "setup_complete.json")
    complete, meta = False, {}
    if os.path.exists(setup_flag):
        complete = True
        try:
            with open(setup_flag, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            meta = {}
    return {
        "setup_complete": complete,
        "setup_meta": meta,
        "hardware": hw,
        "recommendation": rec,
        "backends": backends,
        "providers": provider_comparison(),
        "ollama_installed": shutil.which("ollama") is not None,
    }

def mark_setup_complete(provider: str, model: str) -> dict:
    from datetime import datetime
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "config", "setup_complete.json")
    data = {"completed_at": datetime.now().isoformat(), "provider": provider, "model": model}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    models_path = os.path.join(base, "config", "models.json")
    try:
        with open(models_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["provider"] = provider
        cfg.setdefault("llm", {})
        for key in ("primary", "coding", "fast"):
            cfg["llm"].setdefault(key, {})
            cfg["llm"][key]["model"] = model
            cfg["llm"][key]["provider"] = "ollama" if provider == "ollama" else "lmstudio"
            cfg["llm"][key]["endpoint"] = "http://localhost:11434" if provider == "ollama" else "http://localhost:1234"
        with open(models_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        shutil.copy2(models_path, os.path.join(base, "spellbook", "models.json"))
    except Exception as e:
        data["config_error"] = str(e)
    return data
