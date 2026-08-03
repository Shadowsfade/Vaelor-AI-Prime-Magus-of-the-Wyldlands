"""Console homebrew guidance - game consoles ONLY, verified public guides."""
from __future__ import annotations

GUIDES = {
    "switch": {
        "scope": "Nintendo Switch (unpatched / modchip / RCM depending on unit)",
        "public_methods": [
            "Primary verified guide: https://switch.hacks.guide/",
            "Hardware: some units need a modchip; some early units allow RCM payload inject",
            "Typical stack after guide: hekate, Atmosphere CFW - follow guide version pins exactly",
        ],
        "rules": [
            "Only the console; never phone/PC/router/IoT/bank accounts",
            "Follow switch.hacks.guide for THAT hardware revision",
            "Backup NAND before any CFW write",
            "No piracy coaching; user-owned media only where law allows",
        ],
    },
    "3ds": {
        "scope": "Nintendo 3DS family",
        "public_methods": [
            "Primary verified guide: https://3ds.hacks.guide/",
            "Finalizing setup + Luma3DS as documented there",
        ],
        "rules": ["Console-only", "Methods only as the live guide specifies", "NAND backup first"],
    },
    "wiiu": {
        "scope": "Wii U",
        "public_methods": ["https://wiiu.hacks.guide/"],
        "rules": ["Console-only", "Follow current Tiramisu/Aroma guide"],
    },
    "wii": {
        "scope": "Wii",
        "public_methods": ["https://wii.hacks.guide/"],
        "rules": ["Console-only"],
    },
    "vita": {
        "scope": "PlayStation Vita",
        "public_methods": ["https://vita.hacks.guide/"],
        "rules": ["Console-only", "HENkaku/enso only via current guide"],
    },
    "psp": {
        "scope": "PlayStation Portable",
        "public_methods": ["Known-good community CFW guides (PRO-C / LME era)"],
        "rules": ["Console-only"],
    },
}


def console_homebrew_help(console: str = "", goal: str = "") -> str:
    """Verified-public console homebrew guidance. console=switch|3ds|wiiu|wii|vita|psp"""
    key = (console or "").strip().lower().replace(" ", "")
    aliases = {
        "nintendoswitch": "switch",
        "nx": "switch",
        "n3ds": "3ds",
        "2ds": "3ds",
        "new3ds": "3ds",
        "psvita": "vita",
        "psv": "vita",
    }
    key = aliases.get(key, key)
    lines = [
        "Vaelor Console Homebrew Desk - GAME CONSOLES ONLY",
        "Scope lock: game consoles only. Not PCs, phones, networks, or non-console systems.",
        "Method lock: only widely published, community-verified guides (linked).",
        "Help unlock/mod the Apprentice console via known guides; no piracy coaching.",
        "",
    ]
    if not key or key not in GUIDES:
        lines.append("Supported keys: " + ", ".join(sorted(GUIDES)))
        lines.append('Usage: tool: console_homebrew_help console=switch goal="install CFW safely"')
        return "\n".join(lines)
    g = GUIDES[key]
    lines.append("Console: " + g["scope"])
    if goal:
        lines.append("Apprentice goal: " + goal)
    lines.append("Verified-public methods:")
    for m in g["public_methods"]:
        lines.append("  - " + m)
    lines.append("Hard rules:")
    for r in g["rules"]:
        lines.append("  - " + r)
    lines.append("Next: open primary guide, identify hardware revision, backup, then step-by-step.")
    lines.append("Vaelor may use shell/web tools to open guides and organize files under allowed roots.")
    return "\n".join(lines)


def console_scope_guard(target: str = "") -> str:
    """Refuse non-console hack targets."""
    t = (target or "").lower()
    blocked = [
        "windows",
        "linux",
        "android phone",
        "iphone",
        "router",
        "bank",
        "website login",
        "discord token",
        "wifi neighbor",
    ]
    if any(b in t for b in blocked):
        return "Refused: outside game-console scope. Console homebrew via verified public guides only."
    return "In scope if this is a game console homebrew task using public verified guides."
