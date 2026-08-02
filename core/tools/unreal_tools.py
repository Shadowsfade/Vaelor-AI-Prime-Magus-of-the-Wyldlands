"""Unreal Engine detection + guided install helpers (free/local)."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def _exists(p: str) -> bool:
    try:
        return os.path.exists(p)
    except Exception:
        return False


def _find_unreal_editors(max_hits: int = 8) -> List[str]:
    hits: List[str] = []
    roots = [
        r"C:\Program Files\Epic Games",
        r"C:\Program Files\Unreal Engine",
        r"C:\Program Files (x86)\Epic Games",
        os.path.expandvars(r"%LOCALAPPDATA%\EpicGamesLauncher"),
        r"D:\",
        r"E:\",
        r"S:\UE",
        r"S:\Unreal",
        r"S:\Epic Games",
    ]
    for root in roots:
        if not _exists(root):
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                # prune deep junk
                depth = dirpath[len(root):].count(os.sep)
                if depth > 6:
                    dirnames[:] = []
                    continue
                if "UnrealEditor.exe" in filenames:
                    hits.append(os.path.join(dirpath, "UnrealEditor.exe"))
                    if len(hits) >= max_hits:
                        return hits
                # also UE4
                if "UE4Editor.exe" in filenames:
                    hits.append(os.path.join(dirpath, "UE4Editor.exe"))
                    if len(hits) >= max_hits:
                        return hits
        except Exception:
            continue
    return hits


def _find_uprojects(max_hits: int = 20) -> List[str]:
    hits: List[str] = []
    roots = [
        os.path.expanduser(r"~\Documents"),
        os.path.expanduser(r"~\Desktop"),
        r"S:\VeilorServer",
        r"S:\Games",
        os.path.expanduser(r"~\Documents\Unreal Projects"),
    ]
    for root in roots:
        if not _exists(root):
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                depth = dirpath[len(root):].count(os.sep) if root in dirpath else 0
                if depth > 5:
                    dirnames[:] = []
                    continue
                skip = {"Binaries", "Intermediate", "Saved", "DerivedDataCache", ".git", "node_modules"}
                dirnames[:] = [d for d in dirnames if d not in skip]
                for fn in filenames:
                    if fn.lower().endswith(".uproject"):
                        hits.append(os.path.join(dirpath, fn))
                        if len(hits) >= max_hits:
                            return hits
        except Exception:
            continue
    return hits


def _epic_launcher_path() -> Optional[str]:
    candidates = [
        r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
        r"C:\Program Files\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe"),
    ]
    for c in candidates:
        if _exists(c):
            return c
    return None


def unreal_status() -> str:
    """Report whether Unreal Engine / Epic Launcher / .uprojects exist."""
    editors = _find_unreal_editors()
    projects = _find_uprojects()
    epic = _epic_launcher_path()
    vs = shutil_which_vs()

    installed = len(editors) > 0
    lines = ["Unreal Engine status for the Apprentice:", ""]
    if installed:
        lines.append("UE EDITOR: FOUND")
        for e in editors:
            lines.append(f"  - {e}")
    else:
        lines.append("UE EDITOR: NOT INSTALLED (or not on common paths)")
        lines.append("  Vaelor cannot open Blueprints/maps until Unreal Engine is installed.")

    lines.append("")
    if epic:
        lines.append(f"EPIC LAUNCHER: FOUND at {epic}")
    else:
        lines.append("EPIC LAUNCHER: NOT FOUND")
        lines.append("  Install from https://store.epicgames.com/download (free).")

    lines.append("")
    if projects:
        lines.append("UPROJECT FILES:")
        for p in projects:
            lines.append(f"  - {p}")
    else:
        lines.append("UPROJECT FILES: none found yet under Documents/Desktop/VeilorServer/Games")

    lines.append("")
    lines.append(f"VISUAL STUDIO C++ TOOLS: {'likely present' if vs else 'not detected (recommended for C++ UE work)'}")

    lines.append("")
    if not installed:
        lines.append("NEXT STEPS:")
        lines.append("1) Install Epic Games Launcher (free)")
        lines.append("2) In Launcher → Unreal Engine → Install Engine (UE5 recommended)")
        lines.append("3) Optional: Visual Studio 2022 with Game Development with C++")
        lines.append("4) Create a Blank or Third Person project")
        lines.append("5) Tell Vaelor the .uproject path so he can help with code/content workflow")
        lines.append("")
        lines.append("OFFER: Ask Vaelor to open the Epic installer/download page or launch Epic if installed.")
        lines.append("Commands:")
        lines.append("  tool: unreal_open_epic_download")
        lines.append("  tool: unreal_launch_epic")
    else:
        lines.append("Vaelor can help with project structure, C++/Blueprint guidance, build scripts, git, and file edits.")
    return "\n".join(lines)


def shutil_which_vs() -> bool:
    candidates = [
        r"C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\devenv.exe",
        r"C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\IDE\devenv.exe",
        r"C:\Program Files\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe",
        r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\Common7\IDE\devenv.exe",
    ]
    return any(_exists(c) for c in candidates)


def unreal_open_epic_download() -> str:
    """Open Epic Games free download page in the default browser."""
    url = "https://store.epicgames.com/en-US/download"
    try:
        os.startfile(url)  # Windows
        return f"Opened Epic Games download page: {url}\nAfter install, open Launcher → Unreal Engine → Install Engine."
    except Exception as e:
        return f"Could not open browser automatically: {e}\nPlease visit {url}"


def unreal_launch_epic() -> str:
    """Launch Epic Games Launcher if installed."""
    epic = _epic_launcher_path()
    if not epic:
        return (
            "Epic Games Launcher is not installed.\n"
            "I can open the free download page with: tool: unreal_open_epic_download"
        )
    try:
        subprocess.Popen([epic], shell=False)
        return f"Launched Epic Games Launcher:\n{epic}\nNext: Unreal Engine tab → Install Engine (UE5)."
    except Exception as e:
        return f"Failed to launch Epic Launcher: {e}"


def unreal_json() -> Dict[str, Any]:
    return {
        "editors": _find_unreal_editors(),
        "projects": _find_uprojects(),
        "epic_launcher": _epic_launcher_path(),
        "visual_studio": shutil_which_vs(),
        "ue_installed": len(_find_unreal_editors()) > 0,
    }
