# Vaelor Coder Briefing — 1.1.0-alpha

**Product:** Vaelor (“Vay-lore”) — free, local AI companion  
**Tree:** `S:\VeilorServer\Workspace\Core`  
**Audience:** teammates catching up since last sync  
**Date:** 2026-08-02  

---

## 1. What Vaelor is

Vaelor is a **local-first** agent (not a paid cloud SaaS clone) with:

- Personality: **Arcane Archivist** of the Wyldlands; user is **Apprentice** (never “Master”)
- Stack: **FastAPI + Uvicorn + Ollama/LM Studio + edge-tts + browser Web Speech STT**
- UI: arcane **tome** WebUI at `http://localhost:8000`
- Goal: approach practical agent capability using **only free tools**, installable by non-technical users later

**Out of scope unless explicitly asked:** Project Ebonhold / WoW client work. OctoWoW was a one-off user install, not part of Vaelor core.

---

## 2. How to run (dev)

```powershell
cd S:\VeilorServer\Workspace\Core
.\Start-Vaelor.bat
# or
.\.venv\Scripts\python.exe -m uvicorn api.server:app --host localhost --port 8000
```

Open: http://localhost:8000  

Alpha install (copies to `%LOCALAPPDATA%\Vaelor`, venv, shortcuts):

```powershell
.\Install-Vaelor-Alpha.bat
# or
powershell -ExecutionPolicy Bypass -File .\installer\Install-Vaelor-Alpha.ps1
```

Portable zip for testers:

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\Build-AlphaPackage.ps1
# output: dist\Vaelor-Alpha-1.1.0-alpha.zip
```

---

## 3. Architecture map

| Path | Role |
|------|------|
| `api/server.py` | FastAPI routes: chat, call, voice, setup, tools, static WebUI |
| `core/runtime.py` | Bootstraps brain + config |
| `core/brain.py` | Reasoning, memory hooks, tool use, agent act |
| `core/task_intent.py` | Structured intent, goals, constraints, success criteria |
| `core/action_protocol.py` | Validated JSON decisions, actions, and final results |
| `core/agent_loop.py` | Multi-step tool agent loop (`agent:` / action language) |
| `core/tools/` | Tool implementations + `registry.py` |
| `core/setup_wizard.py` | Hardware scan, Ollama/LM Studio first-run |
| `core/hardware.py` | RAM/VRAM tiering |
| `spellbook/voice.py` | TTS (edge-tts), pronunciation (Vaelor → Vay-lore) |
| `spellbook/llm_client.py` | Ollama + LM Studio client scaffolding |
| `web/index.html` | Tome UI, call loop, setup |
| `config/autonomy.json` | Access policy |
| `config/SANDBOX_GOD_MODE.md` | Human-readable safety policy |
| `memory/` | Archive, conversations, audit log |
| `installer/` | Alpha installer + zip packager |

---

## 4. Systematic breakdown of work since last teammate sync

### 4.1 Core rebuild → working local agent
- Completed incomplete brain methods; FastAPI server as primary surface
- Chat routing: `code:`, `remember:`, `tool:`, `agent:`, `shell:`, `git:`, `search:`, stage/propose/approve workflow
- Personality + memory anchors preserved

### 4.2 Voice calling (free)
- **STT:** browser Web Speech API (Chrome/Edge)
- **TTS:** `edge-tts`, default wizard voice `en-GB-RyanNeural`
- Endpoints: `POST /call`, `POST /voice/speak`, `GET /voice/voices`, greeting audio
- Pronunciation rewrite so “Vaelor” is spoken **Vay-lore**
- **Deferred:** custom cloned voice from user recordings (patch later)

### 4.3 Web research (free, no paid APIs)
- `web_search` — Wikipedia + DuckDuckGo Instant Answer JSON
- `fetch_url` — public page text
- Chat: `search: <query>`

### 4.4 Tools & agent autonomy
Registered tools include (see `GET /tools`):
- Files: `project_scanner`, `file_reader`, `file_editor_propose`, `stage_file`, `scan_unused_files`, proposals approve/reject
- Web: `web_search`, `fetch_url`
- Shell: `shell_exec`, `shell_which`, `set_autonomy_mode`, `get_autonomy_status`, `describe_sandbox`
- Git: status/diff/log/branch/remote/add/commit/checkout/pull/push (force-push disabled)
- Unreal (optional): `unreal_status`, `unreal_open_epic_download`, `unreal_launch_epic` if module present

Agent loop can chain tools when user uses action language / `agent:`.

### 4.5 Access policy — **full_access_os_safe** (1.1.0-alpha)
User request: broad access for installs/dev; **never fully delete core OS files**.

| Setting | Value |
|---------|--------|
| `mode` | `admin` |
| `profile` | `full_access_os_safe` |
| `sandbox_enforced` | `false` (no tight workspace-only fence) |
| `allow_installs` | `true` |
| `auto_confirm_mutations` | `true` in admin/trusted |
| Audit | `memory/audit_log.jsonl` |

**Hard blocks remain:**
- format / diskpart / bcdedit / boot bombs / forced shutdown patterns
- `Remove-Item -Recurse -Force` (and delete verbs) targeting Windows, System32, Program Files, ProgramData, boot/EFI, other users
- cwd inside System32/SysWOW64/WinSxS

Implementation: `core/tools/shell_exec.py` + `config/autonomy.json`.

### 4.6 Setup wizard / hardware
- `/setup` API: backends detect, complete, optional winget Ollama install, model pull
- Tier guidance: RTX 2060 6GB → efficient 7B–9B Q4 class
- UI first-run path: setup → model → open tome

### 4.7 WebUI
- Leather cover / parchment tome aesthetic
- Open-tome click fix, call UI, setup entry
- Status/tools surfaces

### 4.8 Alpha installer (new in 1.1.0-alpha)
| Artifact | Purpose |
|----------|---------|
| `Install-Vaelor-Alpha.bat` | One-click entry from repo root |
| `installer/Install-Vaelor-Alpha.ps1` | Copy → venv → pip → Desktop/Start Menu shortcuts |
| `installer/Build-AlphaPackage.ps1` | Portable zip under `dist/` (no live memory, no .venv) |
| `Start-Vaelor.bat` | Dev/local launch |

Default install dir: `%LOCALAPPDATA%\Vaelor`  
Requires: Windows + Python 3.10+ on PATH. LLM backend (Ollama/LM Studio) still separate free install.

**Not yet:** single-file PyInstaller `.exe` with embedded Python (next packaging step if needed).

### 4.9 Side notes for coders
- GitHub private push was **blocked** earlier (no remote / `gh auth` issues) — commits may be local only
- Version stamp: `1.1.0-alpha` in `api/server.py` health + `config/vaelor.json`
- Do not commit secrets, large GGUF weights, or personal `memory/` dumps into shared zips (packager strips live memory)

---

## 5. API surface (high level)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/health` | online + voice meta + version |
| POST | `/chat` | text chat |
| POST | `/call` | voice call turn → text + audio_base64 |
| POST | `/voice/speak` | TTS only |
| GET | `/voice/voices` | edge-tts wizard list |
| GET | `/tools` | tool registry JSON |
| GET/POST | `/setup*` | first-run wizard |
| GET | `/greeting` | opening line + optional audio |
| static | `/` | tome WebUI |

---

## 6. Config files teammates should know

- `config/vaelor.json` — identity, model names, voice flag  
- `config/models.json` — LLM backends + voice provider  
- `config/autonomy.json` — **safety / admin policy**  
- `config/personality.json` — tone / greeting  
- `requirements.txt` — FastAPI, uvicorn, edge-tts, psutil, …

---

## 7. Testing checklist (smoke)

1. `Start-Vaelor.bat` → health `online`  
2. Open tome → greeting  
3. Chat: `tools` lists shell/git/web  
4. `tool: describe_sandbox` shows FULL ACCESS / OS-SAFE  
5. Shell write in project OK; `Remove-Item -Recurse -Force C:\Windows` **refused**  
6. Optional: Summon Call in Chrome/Edge with mic  
7. Optional: `Build-AlphaPackage.ps1` produces zip + `.sha256`

---

## 8. Suggested next work (backlog)

1. Custom / cloned TTS voice (user-recorded) — **deferred patch**  
2. True single-file Windows `.exe` (PyInstaller/embedded Python) if zip+Python is too hard for testers  
3. Unreal Engine detect/install-offer polish for game-dev workflow  
4. Streaming chat SSE, sessions API, vision image chat  
5. Git remote + private GitHub auth for shared repo  
6. Android later (remote-to-PC first)

---

## 9. One-liner for stand-up

> Vaelor is a free local FastAPI+Ollama agent with tome UI, voice call, web tools, git/shell autonomy under an OS-safe admin policy, setup wizard, and a Windows Alpha installer/zip — custom voice clone still TODO.

See also: `CHANGELOG.md`, `ROADMAP.md`, `installer/README.md`.
