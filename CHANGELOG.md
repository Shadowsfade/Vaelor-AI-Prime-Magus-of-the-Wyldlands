# Changelog

## [Unreleased] — 2026-09-02

### Native Git review milestone 32
- Added `review_git_changes`, a read-only agent tool that assembles changed-file status,
  added/deleted line statistics, `git diff --check`, and a bounded unified diff.
- Review packets flag newly added merge-conflict markers and redact likely credential or
  private-key lines before returning diffs to the model or durable task history.
- Repository paths pass through allowed-root policy, staged and unstaged review are both
  supported, and review never modifies the worktree or index.
- Autonomous guidance now requires this review before claiming repository changes are
  complete; real temporary-repository tests cover non-mutation, review content, redaction,
  conflict warnings, and read-only tool registration.

### Bounded codebase discovery milestone 31
- Added `search_codebase`, a read-only agent tool that ranks relevant source files and
  returns compact line-numbered snippets before Vaelor edits an unfamiliar project.
- Search combines filename and content relevance, uses deterministic ordering, ignores
  dependency/build/binary content, and requires no embedding service or paid API.
- Enforced allowed-root resolution, symlink containment, per-file size limits, a 2,000-file
  ceiling, a 20 MB total scan budget, and a maximum of 30 returned matches.
- Updated autonomous guidance to search for implementations and symbols instead of
  guessing file locations, with regression coverage for ranking, exclusions, bounds,
  invalid queries, and tool registration.

This is immediate bounded lexical discovery; a persistent semantic index remains future work.

### Incremental terminal visibility milestone 30
- Persistent terminal commands now emit bounded incremental output chunks while they run,
  rather than withholding all console text until command completion.
- Agent-run terminal chunks are stored as durable `terminal_output` events and delivered
  through the existing resumable task SSE stream, preserving visibility across reconnects.
- The Task Center live console renders streamed chunks as safe text and continues to show
  lifecycle status, completion metadata, and final results.
- Output callbacks are isolated from the public tool schema, callback failures cannot
  break command execution, and chunk/event retention remains bounded.
- Added real-shell regression coverage for incremental output and frontend coverage for
  rendering terminal chunks.

Full-screen ConPTY input and resize support remain in progress for interactive terminal UIs.

### Prime Magus identity invariant milestone 29
- Made **Vaelor, Prime Magus of the Wyldlands** the canonical permanent title across
  runtime identity, personality, and portable configuration.
- Anchored Vaelor as an ancient, wise, powerful warlock revered throughout the realm,
  with the Architect consistently addressed as his gifted Apprentice.
- Defined “all-knowing” as an active knowledge posture: independently seek and verify
  missing context, reason beyond the Apprentice's initial proposal, and never fabricate
  certainty when evidence is unavailable.
- Applied the invariant to both conversational and autonomous-agent prompts and added
  regression coverage to prevent later persona drift.

### Context-aware butler milestone 28
- Registered guarded persistent terminal sessions as agent tools, allowing Vaelor to
  retain working-directory and environment state when a task genuinely requires it.
- Added proactive but non-obstructive advisory guidance: Vaelor gathers available
  context first and recommends safer, simpler, faster, or more maintainable approaches
  with relevant system constraints and tradeoffs.
- Added current OS, RAM, VRAM, and model-execution advice to autonomous task context.
- Changed durable task runtime defaults to 15 minutes and enforced a 20-minute hard cap
  at both the API boundary and agent loop so work cannot silently run indefinitely.
- Added a live Task Center console backed by resumable Server-Sent Events, with safe text
  rendering for progress, status, and final results.
- Added regression coverage for terminal-tool registration and safety classification,
  runtime enforcement, advisory behavior, and live console contracts.

Task events are now visible live; per-command stdout chunk streaming and ConPTY
full-screen input/resize remain explicitly in progress.

### Persistent terminal foundation milestone 27
- Added managed long-lived PowerShell/bash sessions with retained working directory and
  environment, bounded output, command deadlines, interruption, listing, and cleanup.
- Persistent commands reuse the existing OS-wreck protection, mutation classification,
  autonomy policy, and audit trail instead of introducing an unguarded shell path.
- Replaced the broken legacy `vaelor.py` router with a canonical native CLI supporting
  one-shot prompts, JSON output, version reporting, persistent `!command` execution,
  terminal restart/close commands, and reliable shutdown cleanup.
- Added real PowerShell integration tests for retained environment/cwd, safety rejection,
  supervised confirmation, unknown sessions, cleanup, and CLI argument/version contracts.

This is the persistent terminal foundation; ConPTY full-screen input, resize, and live
streaming remain explicitly in progress.

### Conversation compaction milestone 26
- Added automatic per-session compaction after bounded history thresholds, preserving
  recent turns verbatim while rolling older context into a reusable summary.
- Summary and conversation files now use lock-protected atomic replacement; summaries
  are size-bounded, isolated by session, exposed through the session API, and removed
  with their session.
- Vaelor injects the earlier summary before recent turns so long-running relationships
  retain decisions and context without overwhelming smaller local models.
- Added isolated regression coverage for automatic compaction, bounds, session isolation,
  deletion, and valid persisted JSON; runtime summary files are excluded from Git.

### Durable Task Center milestone 25
- Added a tome Task Center that submits requests through the durable task API rather than
  requiring chat-command knowledge.
- Recent tasks expose status and waiting reason plus safe View, Cancel, Resume, and
  Clarify controls appropriate to each lifecycle state.
- Task and approval panels refresh together after actions and every five seconds while
  the tome is open, keeping background execution visible and actionable.
- Added frontend contract tests for submission, lifecycle controls, polling, and safe
  result rendering.

### GitHub documentation and roadmap-truth milestone 24
- Rebuilt the GitHub README as a complete newcomer path covering installation, first use,
  task approvals, source startup, capabilities, verification, documentation, and privacy.
- Synchronized stale release references in the install guide and coder briefing with the
  canonical `1.1.4-alpha` version and added regression coverage for those public docs.
- Marked exact approval complete and expanded the canonical roadmap to cover the Task
  Center, PTY/CLI runtime, indexing/review, extensibility, model routing, and orchestration.

### Web approval-controls milestone 23
- Added an Action Approvals panel to the tome that discovers durable tasks waiting on
  policy and shows each exact tool, argument set, task ID, and risk level.
- Users can approve one action or reject it directly from the UI; controls submit only
  the server-issued fingerprint and disable during requests to prevent duplicate clicks.
- The panel refreshes when the tome opens, after chat and manual refreshes, and every five
  seconds while open so background tasks become actionable without API tooling.
- Added static frontend contract coverage while retaining streamed-copy regressions.

### Live-copy milestone 21
- Fixed streamed-message copy buttons retaining and copying the original thinking
  placeholder instead of the visible completed response.
- Message copy now reads live per-message state that is updated with every streamed token
  and final response.
- Completed streams are rendered through the normal Markdown path, restoring fenced-code
  copy buttons after streaming.
- Clipboard fallback now detects browser copy rejection and always removes its temporary
  textarea.
- Added focused streamed-copy and final-render regression tests.

### Exact action-approval milestone 22
- Supervised and trusted tasks now pause durably instead of failing when one specific
  mutating action needs user approval.
- Pending approvals expose the exact tool, bounded arguments, risk, autonomy mode, and a
  canonical fingerprint; client-supplied replacement actions are never accepted.
- Added approve/reject task endpoints. Approval resumes the same task ID and grants a
  matching authorization exactly once, while stale or mismatched fingerprints fail closed.
- Added regression coverage for blocked execution, stable fingerprints, durable approval,
  one-time consumption, rejection, stale conflicts, and background task resumption.

### Release-truth milestone 20
- API health, diagnostics, FastAPI metadata, capabilities, roadmap, portable defaults,
  installer scripts, and package names now agree on canonical version `1.1.4-alpha`.
- Runtime version reporting loads from `config/vaelor.json` with an explicit unknown
  fallback instead of duplicating literals.
- Updated stale roadmap checkboxes to distinguish completed foundations from genuine
  remaining work, and normalized the roadmap to UTF-8.
- Added deterministic API, JSON, installer, template, and package version-drift tests.

### Multi-file understanding milestone 19
- Added `read_many_text_files`, a read-only typed tool that gathers up to 20 related
  source files in one agent action.
- Per-file and total character budgets prevent repository exploration from overwhelming
  local-model context windows.
- Every path is resolved through existing allowed-root policy; one unreadable or blocked
  file is reported without discarding successfully gathered context.
- Added deterministic ordering, typed-input, file-count, total-budget, and partial-failure tests.

### Task-deadline milestone 18
- Durable tasks now carry a bounded wall-clock runtime budget in addition to their step
  budget, configurable through `POST /tasks` from 10 seconds to two hours.
- The agent checks its deadline before model calls, between retry attempts, before every
  tool, and before final summarization.
- Deadline expiry returns an honest failed result and emits a durable `task_timed_out`
  event with the phase, step, and configured limit.
- Added deterministic deadline, persistence, and HTTP-boundary tests.

### Command-aware shell milestone 17
- Shell actions are now classified from the command itself instead of treating every
  `shell_exec` call as a mutation.
- Supervised mode can run read-only diagnostics and verification commands while still
  blocking writes, installs, deletes, history changes, and publishing.
- Classification failures remain fail-closed as mutations.
- Added deterministic read-only shell classification and supervised execution tests.

### Risk-aware autonomy milestone 16
- Tool metadata now exposes `read`, `low`, `medium`, or `high` execution risk to the
  model and API clients.
- Supervised mode blocks all autonomous mutations and ignores model-authored confirmation;
  trusted mode allows routine mutations but blocks destructive, install, policy-changing,
  and remote-publishing actions; admin mode permits deliberate full autonomy.
- Shell commands receive dynamic risk classification, including delete, install, Git
  history-changing, and push operations.
- Blocked actions never execute and emit durable `action_blocked` events with mode, risk,
  tool, and reason.
- Added registry, risk detection, policy matrix, spoofed-confirmation, and execution tests.

### Context-budget milestone 15
- Individual tool results are bounded before entering agent observations while retaining
  both the beginning and end for commands whose decisive error appears last.
- Prior observations now use an exact rolling character budget that favors the newest
  evidence instead of growing with every agent step.
- Max-budget finalization uses the same bounded context, reducing local-model overload
  and preserving coherence on longer jobs.
- Added deterministic exact-bound, truncation, and recency tests.

### Operational-readiness milestone 14
- Added `GET /readiness` to distinguish a live HTTP process from a Vaelor instance that
  can actually execute dependable tasks.
- Readiness verifies registered tools, durable task storage, a running local model
  backend, and at least one available model.
- Unready instances return HTTP 503 with structured checks and actionable issues; probe
  failures are reported without crashing the API.
- Added deterministic readiness and route status-code tests.

### Task-API contract milestone 13
- Added FastAPI integration coverage for task creation, workspace forwarding, background
  execution, clarification gating, cancellation conflicts, missing tasks, and terminal SSE.
- Task creation and clarification now reject empty or oversized text and unreasonable
  agent step budgets at the HTTP boundary.
- Cancellation reasons and workspace paths are bounded before entering durable state.
- Added seven deterministic route-level tests using FastAPI's test client.

### Project-grounding milestone 12
- Background tasks can now carry an optional validated workspace path through durable
  storage and `POST /tasks`.
- Agent prompts receive a bounded snapshot of the Git root, top-level structure, and
  relevant `AGENTS.md`, README, `pyproject.toml`, or package metadata.
- Workspace, discovered Git roots, and symlinked guidance remain constrained by the
  configured allowed roots; unapproved roots safely fall back to the workspace.
- Added deterministic structure, package filtering, path-boundary, persistence, and
  agent-context integration tests.

### Model-resilience milestone 11
- Local model decision and final-summary calls now retry transient exceptions up to two
  times by default, with a bounded configurable maximum.
- Every retry emits a durable `model_retry` progress event with phase, attempt, remaining
  retries, and the error for diagnosis.
- Cancellation is checked between retry attempts, and exhausted retries raise a concise
  error that the durable task lifecycle records as a failure.
- Added deterministic recovery, exhaustion, event, and cancellation tests.

### Fail-closed safety milestone 10
- Missing, malformed, or invalid machine-local autonomy policy now defaults to supervised
  mode with mutation auto-confirmation and silent installs disabled.
- Shell and filesystem mutation functions now default to `confirm=no`; callers must
  deliberately authorize writes, patches, directories, deletions, and mutating commands.
- Proposal approval now enforces its documented explicit-confirmation requirement.
- Added deterministic missing-policy, invalid-mode, shell, filesystem, and proposal tests.

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
