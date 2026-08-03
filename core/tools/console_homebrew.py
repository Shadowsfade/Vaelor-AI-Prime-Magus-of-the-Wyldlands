"""Console homebrew guidance — game consoles ONLY, from well-known public methods."""
from __future__ import annotations

GUIDES = {
    "switch": {
        "scope": "Nintendo Switch (unpatched / modchip / RCM depending on unit)",
        "public_methods": [
            "Official-community docs: https://switch.hacks.guide/ (primary verified walkthrough)",
            "Hardware: some units need a modchip; some early units allow RCM payload inject",
            "Typical stack after guide: hekate, Atmosphere CFW — follow guide version pins exactly",
        ],
        "rules": [
            "Only the console; never phone/PC/router/IoT/bank accounts",
            "Follow the current switch.hacks.guide steps for THAT serial/hardware revision",
            "Backup NAND before any CFW write",
            "Do not pirate games; homebrew homebrew-legal dumps only where user owns media and law allows",
        ],
    },
    "3ds": {
        "scope": "Nintendo 3DS family",
        "public_methods": [
            "Primary verified guide: https://3ds.hacks.guide/",
            "Finalizing setup + Luma3DS as documented there",
        ],
        "rules": ["Console-only", "Seedminer/other methods only as the live guide specifies", "NAND backup first"],
    },
    "wiiu": {
        "scope": "Wii U",
        "public_methods": ["https://wiiu.hacks.guide/"],
        "rules": ["Console-only", "Follow guide for Tiramisu/Aroma era as currently published"],
    },
    "wii": {
        "scope": "Wii",
        "public_methods": ["https://wii.hacks.guide/"],
        "rules": ["Console-only"],
    },
    "vita": {
        "scope": "PlayStation Vita",
        "public_methods": ["https://vita.hacks.guide/"],
        "rules": ["Console-only", "HENkaku/ensō only via current guide"],
    },
    "psp": {
        "scope": "PlayStation Portable",
        "public_methods": ["Community CFW guides (PRO-C / LME) — prefer well-mirrored known-good guides"],
        "rules": ["Console-only"],
    },
}


def console_homebrew_help(console: str = "", goal: str = "") -> str:
    """Return verified-public console homebrew guidance. console=switch|3ds|wiiu|wii|vita|psp"""
    key = (console or "").strip().lower().replace(" ", "")
    aliases = {
        "nintendoswitch": "switch", "nx": "switch",
        "n3ds": "3ds", "2ds": "3ds", "new3ds": "3ds",
        "psvita": "vita", "psv": "vita",
    }
    key = aliases.get(key, key)
    lines = [
        "Vaelor Console Homebrew Desk — GAME CONSOLES ONLY",
        "Scope lock: physical/game consoles. Not PCs, phones, networks, or non-console systems.",
        "Method lock: only widely published, community-verified guides (linked).",
        "Ethics: help the Apprentice unlock/mod THEIR console via known guides; no piracy coaching.",
        "",
    ]
    if not key or key not in GUIDES:
        lines.append("Supported keys: " + ", ".join(sorted(GUIDES)))
        lines.append("Usage: tool: console_homebrew_help console=switch goal="install CFW safely"")
        return "\n".join(lines)
    g = GUIDES[key]
    lines.append(f"Console: {g['scope']}")
    if goal:
        lines.append(f"Apprentice goal: {goal}")
    lines.append("Verified-public methods:")
    for m in g["public_methods"]:
        lines.append(f"  - {m}")
    lines.append("Hard rules:")
    for r in g["rules"]:
        lines.append(f"  - {r}")
    lines.append("Next: open the primary guide URL, identify hardware revision, backup, then proceed step-by-step.")
    lines.append("Vaelor may use shell/web tools to open guides, download official payloads the guide names, and organize files under the Apprentice home/project folders.")
    return "\n".join(lines)


def console_scope_guard(target: str = "") -> str:
    """Refuse non-console hack targets."""
    t = (target or "").lower()
    blocked = ["windows", "linux", "android phone", "iphone", "router", "bank", "website login", "discord token", "wifi neighbor"]
    if any(b in t for b in blocked):
        return "Refused: outside game-console scope. Vaelor only assists console homebrew via verified public guides."
    return "In scope if this is a game console homebrew task using public verified guides."
