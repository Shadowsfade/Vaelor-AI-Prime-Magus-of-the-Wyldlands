# Changelog

## [1.1.2-alpha] — 2026-08-03
### Added
- File CRUD tools (list/read/write/patch/delete/mkdir) under allowed roots; OS core protected
- Admin/trusted **auto-approve** for mutating tools in agent loop + shell_exec
- Console homebrew desk: game-consoles-only via verified public guides
### Changed
- Agent loop max_steps 10; proactive file/console action triggers
---

## [1.1.1-alpha] — 2026-08-03

### Fixed
- **Tome UI broken links:** added missing API routes the WebUI already called
  - GET/POST /sessions, GET/DELETE /sessions/{id}
  - POST /chat/stream (SSE)
- Chat request model now accepts session_id and images
- Conversation memory JSON loads use utf-8-sig (BOM-safe)
- Default think path passes session_id into brain

### Changed
- Version stamp **1.1.1-alpha**

---


All notable changes to **Vaelor** (Grand Archive / Project Wyld companion) are documented here.

## [1.1.0-alpha] — 2026-08-02

### Added
- **User docs:** INSTALL.md, README.md, beginner READ ME FIRST.txt / INSTALL.bat
- **Per-machine config init** (installer/init_local_config.py) so packages never ship another PC paths/ports/memory
- **Desktop app shell** (desktop/vaelor_app.py, Vaelor.exe builder) with arcane splash + wizard greeting hooks
- **Windows Alpha installer**
  - Install-Vaelor-Alpha.bat (repo root one-click)
  - installer/Install-Vaelor-Alpha.ps1 — copy Core to %LOCALAPPDATA%\\Vaelor, create .venv, install deps, Desktop + Start Menu shortcuts
  - installer/Build-AlphaPackage.ps1 — portable dist/Vaelor-Alpha-1.1.0-alpha.zip (+ .sha256); strips .venv and live memory/
  - VERSION.json stamp written on install
- **Coder handoff docs**
  - CODER_BRIEFING.md — full systematic breakdown for teammates
  - Updated config/SANDBOX_GOD_MODE.md for current policy
- **Autonomy profile ull_access_os_safe**
  - Broad install/dev shell access (mode=admin)
  - Explicit ban on full delete/destroy of core OS trees and disk/boot wreck commands
  - Audit trail: memory/audit_log.jsonl
  - Memory rules: proceed on consented free installs; never wipe OS core
- Optional **Unreal helper tools** registration hooks when module present

### Changed
- core/tools/shell_exec.py — policy engine for full-access / OS-safe
- config/autonomy.json — sandbox_enforced: false, protected_delete_roots, install flags
- Tool registry descriptions match OS-safe policy language
- Version bump to **1.1.0-alpha** (pi/server.py health, config/vaelor.json)
- Start-Vaelor.bat hardened for missing-venv guidance

### Deferred (next patch)
- **Custom / cloned AI voice** from user recordings; current TTS remains free dge-tts wizard voices
- Single-file PyInstaller .exe with embedded Python (Alpha uses zip + system Python + installer script)

### Security / safety
- Still blocked: format, diskpart, bcdedit, recursive wipe of Windows/System32/Program Files bulk delete, other user profiles, forced power bombs
- Force-push remains off by default in git tools

---

## [1.0.0] — 2026-08-01

### Added
- **Live voice calling** (ChatGPT/Claude-style loop)
  - Browser Web Speech API STT (Chrome/Edge)
  - Wizard TTS via free edge-tts (en-GB-RyanNeural default)
  - POST /call, POST /voice/speak, GET /voice/voices
  - Call UI: Summon Call, mic mute, listening meter, barge-in
- **Free web research tools** (no paid APIs)
  - web_search — Wikipedia + DuckDuckGo Instant Answer JSON
  - fetch_url — public http(s) pages as text
  - Chat shortcut: search: / web:
- **Stronger memory and context** (ranked archive, Apprentice identity anchors)
- **Arcane tome WebUI polish** (parchment, leather cover, open animation)
- **Hardware-aware setup helpers** (GPU/RAM tiering, Ollama vs LM Studio)
- Unified local LLM client scaffolding (spellbook/llm_client.py)
- Setup wizard API, shell + git tools, agent loop foundations

### Fixed
- Tome cover click did not open the archive
- Restored core UI handlers
- Tool registry web tools; FastAPI/Starlette venv import issues

### Setup
Dev: Start-Vaelor.bat then http://localhost:8000
Alpha: Install-Vaelor-Alpha.bat
Requires Python 3.10+, optional Ollama/LM Studio, Chrome/Edge for mic.

### Known limitations
- DDG HTML may bot-block; Instant Answer + Wikipedia used instead
- STT needs Chrome/Edge + mic on localhost
- Alpha needs system Python (not single offline EXE yet)
- Custom voice clone not in this alpha

---

## Earlier milestones
See ROADMAP.md, CODER_BRIEFING.md, and git history.
