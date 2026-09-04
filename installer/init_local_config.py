"""Generate machine-local Vaelor config at install/first-run.

Never ships another user's paths, ports, or memory.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def init_local_config(root: Path | None = None, force: bool = False) -> dict:
    root = Path(root or Path.cwd()).resolve()
    cfg_dir = root / "config"
    tpl_dir = cfg_dir / "templates"
    home = Path(os.path.expanduser("~")).resolve()
    docs = home / "Documents"
    desktop = home / "Desktop"
    downloads = home / "Downloads"

    # --- autonomy: rewrite for this user/machine ---
    autonomy_path = cfg_dir / "autonomy.json"
    if force or not autonomy_path.exists() or _is_foreign_autonomy(autonomy_path, home, root):
        base = _read_json(tpl_dir / "autonomy.portable.json") or {
            "mode": "admin",
            "profile": "full_access_os_safe",
            "auto_confirm_mutations": True,
            "allow_installs": True,
            "sandbox_enforced": False,
            "protected_delete_roots": [
                r"C:\Windows",
                r"C:\Windows\System32",
                r"C:\Program Files",
                r"C:\Program Files (x86)",
                r"C:\ProgramData",
            ],
            "audit_log": "memory/audit_log.jsonl",
            "max_timeout_seconds": 1800,
        }
        allowed = [
            str(root),
            str(root.parent),
            str(home),
            str(docs),
            str(desktop),
            str(downloads),
        ]
        # common extra drives if present
        for letter in "DEFG":
            drive = f"{letter}:\\"
            if Path(drive).exists():
                allowed.append(drive)
        base["default_cwd"] = str(root)
        base["allowed_roots"] = sorted(set(allowed))
        base["allowed_user_profile"] = str(home)
        base["comment"] = "Generated on this machine at install/first-run. Not shared."
        _write_json(autonomy_path, base)

    # --- vaelor identity/workspace ---
    vaelor_path = cfg_dir / "vaelor.json"
    if force or not vaelor_path.exists() or _is_foreign_vaelor(vaelor_path, root):
        base = _read_json(tpl_dir / "vaelor.portable.json") or {
            "name": "Vaelor",
            "version": "1.1.4-alpha",
            "ollama": {"endpoint": "http://localhost:11434"},
            "models": {
                "primary": "vaelor-prime:latest",
                "coding": "vaelor-prime:latest",
                "fast": "vaelor-prime:latest",
            },
            "identity": {
                "title": "The Arcane Archivist of the Wyldlands",
                "world": "Project Wyld",
            },
            "voice": {"enabled": True, "wizard_voice": "en-GB-RyanNeural"},
        }
        base["workspace"] = {"path": str(root.parent if (root.parent / "Workspace").exists() is False else root)}
        # Prefer install root as workspace root for strangers
        base["workspace"]["path"] = str(root)
        _write_json(vaelor_path, base)

    # --- models: ensure portable endpoints only ---
    models_path = cfg_dir / "models.json"
    if force or not models_path.exists():
        src = tpl_dir / "models.portable.json"
        if src.exists():
            shutil.copy2(src, models_path)
        else:
            _write_json(
                models_path,
                {
                    "provider": "ollama",
                    "voice": {
                        "tts_provider": "edge-tts",
                        "wizard_voice": "en-GB-RyanNeural",
                        "wizard_voice_fallback": "en-GB-ThomasNeural",
                        "rate": "-8%",
                        "pitch": "-5Hz",
                        "stt_provider": "browser_web_speech",
                    },
                    "backends": {
                        "ollama": {"endpoint": "http://localhost:11434"},
                        "lmstudio": {"endpoint": "http://localhost:1234"},
                    },
                },
            )

    # --- network: always local free port for THIS machine ---
    try:
        from core.netbind import resolve_bind

        host, port, url = resolve_bind(root, force_new=False)
    except Exception:
        host, port, url = "localhost", 8765, "http://localhost:8765/"
        _write_json(
            cfg_dir / "network.json",
            {
                "host": host,
                "port": port,
                "url": url,
                "bind": "loopback",
                "note": "Fallback bind; desktop app will re-resolve if needed.",
            },
        )

    # --- clean empty memory skeleton if missing ---
    mem = root / "memory"
    mem.mkdir(exist_ok=True)
    arch = mem / "archive.json"
    conv = mem / "conversations.json"
    if force or not arch.exists():
        arch.write_text("[]", encoding="utf-8")
    if force or not conv.exists():
        conv.write_text("{}", encoding="utf-8")
    # never copy foreign audit logs on init
    audit = mem / "audit_log.jsonl"
    if force and audit.exists():
        audit.write_text("", encoding="utf-8")
    elif not audit.exists():
        audit.write_text("", encoding="utf-8")

    # setup marker should not be forced complete for strangers
    setup = cfg_dir / "setup_complete.json"
    if force and setup.exists():
        try:
            setup.unlink()
        except Exception:
            pass

    return {
        "root": str(root),
        "user_home": str(home),
        "network": {"host": host, "port": port, "url": url},
        "autonomy": str(autonomy_path),
        "vaelor": str(vaelor_path),
    }


def _is_foreign_autonomy(path: Path, home: Path, root: Path) -> bool:
    data = _read_json(path)
    profile = str(data.get("allowed_user_profile") or "")
    # A profile owned by another account is definitive foreign-machine state.
    if profile and Path(profile).resolve() != home:
        return True
    return False


def _is_foreign_vaelor(path: Path, root: Path) -> bool:
    data = _read_json(path)
    ws = str(((data.get("workspace") or {}).get("path")) or "")
    if not ws:
        return True
    # Preserve an intentional existing workspace, but repair stale paths copied
    # from another machine.
    return not Path(ws).expanduser().exists()


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    force = "--force" in sys.argv
    info = init_local_config(target, force=force)
    print(json.dumps(info, indent=2))
