# Vaelor Coder Briefing — 1.1.4-alpha

**Product:** Vaelor (“Vay-lore”) — free, local AI companion  
**Tree:** `S:\VeilorServer\Workspace\Core`  
**Audience:** teammates catching up since last sync  
**Date:** 2026-09-03

---

## 1. What Vaelor is

Vaelor is a **local-first** agent (not a paid cloud SaaS clone) with:

- Permanent identity: **Vaelor, Prime Magus of the Wyldlands**—an ancient, wise,
  powerful warlock; user is **Apprentice** (never “Master”)
- The Wyldlands is Vaelor's home and lived reality: an emerging virtual world being built
  through this software workshop. He does not pretend unfinished game systems already exist.
- “All-knowing” is implemented as active context gathering and verification, never
  fabricated certainty; Vaelor should apply deeper judgment and suggest better paths.
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
# output: dist\Vaelor-Alpha-1.1.4-alpha.zip
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
| `core/task_store.py` | Atomic task state, progress events, interruption recovery |
| `core/preference_store.py` | User-confirmed preferences and outcome feedback |
| `core/project_context.py` | Bounded, allowed-root repository context for tasks |
| `core/readiness.py` | Operational checks for tools, task storage, and local models |
| `core/memory.py` | Atomic, provenance-aware long-term memory archive |
| `core/memory_manager.py` | Bounded relevance ranking and context selection |
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
- Files: `project_scanner`, `search_codebase`, `file_reader`, `read_many_text_files`,
  `file_editor_propose`, `stage_file`, `scan_unused_files`, proposals approve/reject
- Web: `web_search`, `fetch_url`
- Shell: `shell_exec`, `shell_which`, `terminal_start`, `terminal_list`, `terminal_run`,
  `terminal_interrupt`, `terminal_close`, `set_autonomy_mode`, `get_autonomy_status`,
  `describe_sandbox`
- Git: status/diff/log/branch/remote/add/commit/checkout/pull/push plus bounded
  `review_git_changes` (force-push disabled)
- Unreal (optional): `unreal_status`, `unreal_open_epic_download`, `unreal_launch_epic` if module present

Agent loop can chain tools when user uses action language / `agent:`.
For unfamiliar repositories, it is instructed to call `search_codebase` before assuming
file locations. Search is lexical, allowed-root constrained, and globally scan-bounded;
a persistent semantic/embedding index is not yet implemented.
Project context discovers `AGENTS.md` and `VAELOR.md` from repository root through the
active workspace. Instructions apply broad-to-specific within their directory scope and
remain subordinate to the Apprentice's request, permanent identity, safety, and approvals.
Before reporting repository work complete, `review_git_changes` provides name/line scope,
whitespace checks, a bounded unified diff, conflict-marker warnings, and likely-secret
redaction without changing the index or worktree.
For risky implementation work, Vaelor can create and review a managed detached worktree,
commit the tested result there, bind validation evidence to that exact commit, and promote
it only through an authorized fast-forward. Any failed evidence, later sandbox commit,
dirty worktree, or source-branch drift blocks promotion and requires fresh validation.
For substantial creation work, the agent defines applicable acceptance checks and calls
`evaluate_validation` with concrete evidence. Unknown/skipped/failed checks receive no
confidence credit; required failures or unknowns block promotion even above the threshold.
Task contracts include `reusable_capability` and `capability_reason`. When set, Vaelor
audits his existing tools first and may extend his own modular source when the request
authorizes that outcome. Examples are not integrations by default, and all self-extension
still requires normal safety, tests, documentation, evidence, diff review, and restart notes.
Git-backed projects can use `create_validation_sandbox` to obtain a detached temporary
worktree from committed state. The returned path is used by normal tools; manifests are
listed with `list_validation_sandboxes`, and destructive cleanup requires the exact managed
ID through `discard_validation_sandbox`. `review_validation_sandbox` feeds one managed ID
through the bounded secret-redacting Git review path. Uncommitted source work is never copied.
Transient local-model exceptions are retried twice by default. Retry attempts are written
to the durable task event stream and remain cancellable between attempts.
Tool observations are bounded per result and across the rolling history so long-running
tasks do not overwhelm smaller local-model context windows.
Tasks also persist a wall-clock runtime budget (default 15 minutes) and cooperatively
stop between model/tool operations when that deadline is exceeded. Both the API and agent
enforce a 20-minute maximum. Autonomous task context includes current OS/RAM/VRAM advice,
and directs the model to inspect available context and suggest materially better paths.
The Task Center View action consumes the resumable SSE stream in a live, text-safe console.
Agent calls to `terminal_run` additionally emit bounded `terminal_output` chunks into that
stream while the command is running. Full-screen ConPTY input/resize is still pending.
All durable runs also use a lifecycle-bound 30-second heartbeat. It is visible through the
same resumable stream and terminates when the task leaves `running` or execution unwinds.

### 4.5 Access policy — **full_access_os_safe** (1.1.4-alpha)
User request: broad access for installs/dev; **never fully delete core OS files**.

| Setting | Value |
|---------|--------|
| `mode` | `admin` |
| `profile` | `full_access_os_safe` |
| `sandbox_enforced` | `false` (no tight workspace-only fence) |
| `allow_installs` | `true` |
| `auto_confirm_mutations` | policy flag; agent additionally enforces per-tool risk |
| Audit | `memory/audit_log.jsonl` |

**Hard blocks remain:**
- format / diskpart / bcdedit / boot bombs / forced shutdown patterns
- `Remove-Item -Recurse -Force` (and delete verbs) targeting Windows, System32, Program Files, ProgramData, boot/EFI, other users
- cwd inside System32/SysWOW64/WinSxS

Implementation: `core/tools/shell_exec.py` + `config/autonomy.json`.

Agent-loop policy is risk-aware: supervised blocks autonomous mutations, trusted permits
routine reversible changes but blocks high-risk delete/install/push/policy actions, and
admin permits high-risk work while the hard OS protections remain active. Confirmation
written by the model itself is never treated as user authorization.
Shell policy is command-aware, so supervised mode still permits read-only inspection and
test commands needed to understand and verify work.

If the machine-local `config/autonomy.json` is absent, malformed, or names an unknown
mode, Vaelor fails closed to supervised mode. Mutating tools default to `confirm=no`;
trusted/admin behavior is available only from a valid local policy or an explicit mode
change.

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
- Canonical version: `config/vaelor.json`; API and packaging metadata consume or are
  regression-checked against it.
- Do not commit secrets, large GGUF weights, or personal `memory/` dumps into shared zips (packager strips live memory)

### 4.10 Dependable memory retrieval
- Archive writes are lock-protected and atomic; malformed archives fail closed to an
  empty result rather than breaking a task.
- Memories carry source, confidence, and tags, and normalized duplicate content is
  suppressed.
- Prompt context is relevance-ranked and bounded. Only high-confidence, high-importance
  rules may be treated as global; unrelated low-confidence memories stay out of context.
- Regression coverage lives in `test_memory_retrieval.py`.

### 4.11 Safe outcome adaptation
- Positive and negative task-feedback comments automatically enter a bounded recent
  experience block for later reasoning, allowing Vaelor to retain what worked and improve
  recurring weak spots.
- Feedback experience is deduplicated and explicitly advisory. It cannot grant tool
  permission or override the current request, permanent identity, safety, or approvals.
- Inferred negative lessons remain proposed preferences until the user activates them;
  only direct user preference declarations become durable active rules automatically.

---

## 5. API surface (high level)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/health` | online + voice meta + version |
| GET | `/readiness` | 200 when task-capable; structured 503 when dependencies are unavailable |
| POST | `/chat` | text chat |
| POST | `/call` | voice call turn → text + audio_base64 |
| POST | `/voice/speak` | TTS only |
| GET | `/voice/voices` | edge-tts wizard list |
| GET | `/tools` | tool registry JSON |
| GET/POST | `/tasks*` | workspace-aware durable tasks, clarify/cancel/resume, exact action approve/reject, and SSE progress |
| GET/POST/PATCH | `/preferences*` | user-controlled adaptation and preference state |
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

Task-control regression check:

```powershell
python -m unittest -v test_task_lifecycle.py test_agent_loop.py
```

When policy blocks one mutating task action, inspect `pending_approval` on the task and
send its unchanged 64-character `fingerprint` to `POST /tasks/{task_id}/approve-action`.
Vaelor resumes that task with a one-time authorization. Use the matching
`/reject-action` endpoint to cancel it instead; stale fingerprints return HTTP 409.
The tome's **Action Approvals** sidebar panel provides the same flow for normal users and
polls for newly blocked background tasks while the tome is open.

API contract regression check:

```powershell
python -m unittest -v test_api_tasks.py
```

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
