# Changelog

All notable changes to **Vaelor** (Grand Archive / Project Wyld companion) are documented here.

## [1.0.0] — 2026-08-01

### Added
- **Live voice calling** (ChatGPT/Claude-style loop)
  - Browser **Web Speech API** STT (Chrome/Edge)
  - Wizard **TTS** via free `edge-tts` (`en-GB-RyanNeural` default)
  - `POST /call`, `POST /voice/speak`, `GET /voice/voices`
  - Call UI: Summon Call, mic mute, listening meter, barge-in
- **Free web research tools** (no paid APIs)
  - `web_search` — Wikipedia OpenSearch/summary + DuckDuckGo Instant Answer JSON
  - `fetch_url` — read public http(s) pages as text
  - Chat shortcut: `search: <query>` / `web: <query>`
- **Stronger memory & context**
  - Ranked archive recall with rule priority
  - Identity anchors (Apprentice, never Master)
  - Session-oriented conversation memory modules
- **Arcane tome WebUI polish**
  - Parchment pages, leather cover, gold glow, floating aether particles
  - Tome open animation + cover click to enter archive
- **Hardware-aware setup helpers**
  - GPU/RAM scan without hanging on `nvidia-smi`
  - Model tier recommendations (efficient = 7B–9B Q4 for RTX 2060 6GB)
  - Ollama vs LM Studio comparison data for first-run guidance
- **Unified local LLM client scaffolding** (`spellbook/llm_client.py`)
  - Ollama + LM Studio provider detection hooks

### Fixed
- Tome cover **click did not open** the archive (missing `openTome` / click bindings after call-loop patch)
- Restored core UI handlers (send, mic, voice toggles, setup, new dialogue)
- Tool registry syntax/registration for web tools
- FastAPI/Starlette venv import issues on repair path

### Tools currently registered
- `project_scanner`, `file_reader`, `file_editor_propose`, `scan_unused_files`
- `web_search`, `fetch_url`

### Setup (local)

#### Requirements
- Windows host with Python 3.12+
- [Ollama](https://ollama.com) recommended (or LM Studio local server)
- Model: `vaelor-prime:latest` (or another local chat model)
- Chrome or Edge for microphone calling

#### Quick start
```powershell
cd S:\VeilorServer\Workspace\Core
.\.venv\Scripts\Activate.ps1
# if needed: pip install -r requirements.txt
# ensure Ollama is running and model exists: ollama list
python -m uvicorn api.server:app --host 127.0.0.1 --port 8000
```

Open: http://localhost:8000

Or use desktop launcher: `launcher.ps1` / `Vaelor.bat` (Web Dashboard option).

#### First-run tips
1. Click the closed tome cover to open the archive.
2. Optional Setup button / first-open wizard chooses Ollama vs LM Studio and model.
3. **Summon Call** → allow microphone (localhost).
4. Useful commands: `remember:`, `code:`, `tools`, `search: <query>`, `stage:` / `propose:` / `approve:`.

#### Voice stack
| Direction | Free component |
|-----------|----------------|
| You → text | Browser Web Speech API |
| Text → speech | `edge-tts` neural voices |
| Reasoning | Local Ollama/LM Studio model |

#### Privacy / publishing notes
- This repository is intended **private**.
- Do **not** commit model weights (`.gguf`), generated audio tests, or secrets.
- Runtime memory under `memory/` may contain personal project notes; review before sharing forks.

### Known limitations
- DuckDuckGo **HTML** search endpoints may bot-block; research uses Wikipedia + DDG Instant Answer JSON instead.
- Live STT requires Chrome/Edge and mic permission on localhost/HTTPS.
- Not a full cloud multi-agent clone of commercial assistants; focused on free local operation.

---

## Earlier milestones
See `ROADMAP.md` and git history for pre-1.0 foundation (CLI, FastAPI, memory, approval workflow, parchment UI baseline).
