# Changelog

## [Unreleased] — 2026-09-02

### Clarification-loop milestone 9
- Added `POST /tasks/{task_id}/clarify` so an answer can revise and continue the same
  durable task instead of creating a disconnected replacement.
- Clarification answers are reclassified into an updated task contract before execution.
- Still-ambiguous answers remain waiting with the refined question and context persisted;
  resolved answers return to pending and run in the background.
- Added deterministic same-task, insufficient-answer, and invalid-state tests.

### Task-control milestone 8
- Added durable, idempotent task cancellation with an audit event and optional reason.
- The agent checks for cancellation before model calls, after model calls, between tool
  calls, and before max-budget summarization.
- Cancellation state cannot be overwritten by a late model result or backend exception,
  and cancelled tasks are not accidentally resumed.
- Added `POST /tasks/{task_id}/cancel`; existing task event streams report the cancelled
  terminal state and result.
- Added deterministic cancellation timing, persistence, race, and resume tests.

### Relevant-memory milestone 7
- Memory archive updates are now lock-protected and atomically replaced, preventing
  concurrent writers or interrupted saves from leaving a partial archive.
- Corrupt archives fail safely as an empty archive instead of interrupting Vaelor.
- Stored memories include source, confidence, and tags, and normalized duplicate
  content is rejected.
- Context retrieval uses bounded relevance scoring; unrelated or low-confidence rules
  are no longer injected globally into every prompt.
- Added deterministic corruption, provenance, deduplication, relevance, and ranking tests.

### User-adaptation milestone 6
- Added local, user-controlled preferences with source, confidence, scope, status, and
  repeated-evidence tracking.
- Direct first-person preference declarations can become active automatically and enter
  Vaelor's reasoning context; inferred lessons never auto-activate.
- Negative task feedback creates a proposed preference for user review rather than
  silently rewriting behavior.
- Added preference list/create/enable/disable APIs and task-linked positive/negative
  feedback with durable task events.
- Preference learning is non-blocking: storage failures cannot interrupt chat or action.
- Personal preference and feedback files are excluded from Git.
- Added deterministic preference, provenance, feedback, context, and control tests.

### Live-progress milestone 5
- Added background task submission with `POST /tasks`; the durable task record is
  returned before execution begins.
- Added `GET /tasks/{task_id}/events` Server-Sent Events for progress, lifecycle status,
  keep-alives, and final results with resumable event cursors.
- Prepared tasks retain their structured contract and execute under the same durable ID.
- Tasks needing clarification enter a visible waiting state without executing tools.
- Added lifecycle tests for task preparation, clarification waits, background execution,
  and preservation of task identity.

### Durable-task milestone 4
- Added an atomic local task ledger with task contracts, lifecycle status, attempts,
  bounded progress events, and final results.
- Agent decisions, schema errors, tool starts, tool results, crashes, and completion are
  recorded without allowing logging failures to interrupt execution.
- Tasks left running during shutdown are marked interrupted on startup and can resume
  under the same task ID and contract.
- Added `GET /tasks`, `GET /tasks/{task_id}`, and `POST /tasks/{task_id}/resume` APIs.
- Personal task state and temporary atomic-write files are excluded from Git.
- Added deterministic persistence, restart recovery, lifecycle, crash, and resume tests.

### Structured-tool milestone 3
- Added a validated JSON protocol for agent thoughts, typed tool arguments, batched
  actions, and structured final status.
- Tool schemas are derived from registered callable signatures and exposed in the tool
  inventory, including required and optional argument names.
- Every action batch is fully validated before any tool executes, preventing partial
  execution of malformed batches.
- Invalid JSON and invalid tool arguments are returned to the model for correction.
- Existing `ACTION:` and `TOOL` formats remain supported for backward compatibility.
- Fixed implicit confirmation injection for mutating tools that do not accept a
  `confirm` argument.
- Added deterministic protocol, schema, typed-argument, correction, and integration tests.

### Task-understanding milestone 2
- Added a structured task contract with intent, normalized goal, observable success
  criteria, explicit constraints, and clarification state.
- Natural-language requests are classified before execution instead of relying only on
  keyword routing.
- Action contracts are carried into the agent loop so planning and completion are tied
  to the user's requested outcome.
- Material ambiguity pauses for one focused clarification rather than guessing and acting.
- Malformed or unavailable classifier output falls back to the existing conservative
  detector, preserving offline behavior.
- Added deterministic tests for JSON extraction, fallback behavior, clarification,
  action routing, and task-contract construction.

### Reliability milestone 1
- Agent mutations now require a passing verification before success can be reported.
- Any mutation after verification invalidates the earlier verification result.
- Mutation classification now follows registered tool metadata.
- Missing or malformed autonomy policy fails closed instead of enabling auto-confirm.
- Unknown tools are classified as failures, allowing the agent to recover honestly.
- Agent-loop exceptions are surfaced and recorded instead of silently falling back to chat.
- Added deterministic unit tests for verification enforcement, mutation invalidation,
  policy fallback, unknown tools, read-only completion, and visible agent failures.
- Diagnostics now checks the configured per-machine API host and port.

### Project workflow
- Major completed milestones must be documented, verified, committed, and pushed with
  their implementation so GitHub remains the cross-session source of truth.

---

## [1.1.4-alpha] — 2026-08-03
### Added
- **Debug Console** (header Debug): /diagnostics for models/backends/host/client log
- **Copyable code blocks** in Vaelor replies (fenced ` + Copy), plus Copy message
### Fixed
- Tome cover Continue/open no longer freezes waiting on TTS/API
---

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
