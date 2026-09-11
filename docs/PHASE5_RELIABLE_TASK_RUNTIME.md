# Phase 5 reliable unified task runtime

Status: first implementation slice complete on work/phase5-reliable-task-runtime.
Product version remains 1.1.4-alpha.

## Existing execution architecture

- api/server.py exposes durable task creation, listing, detail, event streaming, approval, clarification, resume, cancellation, and feedback endpoints.
- core/brain.py owns task preparation and invokes core.agent_loop.run_agent.
- core/task_store.py persists task records and bounded operational events in JSON using a temporary file and atomic replace.
- core/scheduler.py launches ordinary Brain tasks for recurring schedules.
- core/task_heartbeat.py records liveness while a task is running.
- core/terminal_session.py provides persistent bounded shell sessions; the registry and execute_guarded path remain the governance boundary.
- core/governance.py, core/verification.py, and the guarded registry provide immutable fingerprints, state-bound approvals, one-time capabilities, provenance, and independent verification.
- web/index.html is already a task client: it creates tasks, observes SSE progress, displays approvals, and requests cancel/resume/clarification.
- vaelor.py is still a separate interactive terminal/CLI surface. It does not yet submit every terminal command through the durable task API.

## Reliability gaps found

The task store was durable, but status changes were not a single validated state machine. update() accepted any known status transition, while approval, clarification, cancellation, and restart recovery each changed status directly. That allowed impossible histories to be persisted and made safe resume policy implicit. The API also uses FastAPI background tasks, so a worker restart can leave an active task interrupted without a supervisor recovery decision.

## Canonical lifecycle

The existing names are retained for compatibility:

    pending -> running -> completed
                        -> failed -> pending/running
                        -> interrupted -> pending/running
                        -> waiting -> pending/running
    pending -> waiting -> pending
    pending/running/waiting/interrupted/failed -> cancelled
    completed/cancelled -> terminal

core.task_store.STATE_TRANSITIONS is now authoritative for all durable status changes. Invalid transitions fail closed with ValueError. Re-entry into the same state remains idempotent where existing callers need it. Approval, clarification, cancellation, and restart recovery use the same transition validation as ordinary task updates.

## Recovery and completion semantics

On startup, running tasks become interrupted; the system does not blindly rerun the last action. Resume is an explicit operation and reuses the durable task contract. Existing agent completion still requires a structured final result and, for mutations, Phase 4 independent verification. Waiting approval remains an exact fingerprint/state-binding boundary.

## Chosen first slice

This slice formalizes the durable lifecycle before adding new workers or executors. It prevents invalid state histories and establishes a safe seam for the next slice: an explicit supervisor/runner that claims pending or recoverable tasks, performs preflight, invokes one bounded worker action, classifies the result, and records retry metadata before resuming work.

## Remaining migration work

1. Add a durable supervisor claim/lease so API background tasks do not own orchestration implicitly.
2. Add structured step records and retry classification with bounded backoff.
3. Add startup recovery decisions that verify before retrying mutating steps.
4. Route CLI, voice, and remote clients through the task API.
5. Add executor health/preflight and structured error records.
6. Expand the canonical event vocabulary while preserving the existing bounded event stream and Phase 4 provenance/verification records.
