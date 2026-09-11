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

The task store previously had durable task records but no exclusive supervisor ownership, no durable step identity, and no explicit distinction between safe retry and uncertain mutation. Those gaps could allow duplicate workers or unsafe restart behavior. The current slice closes those gaps for the existing Brain path without creating a second orchestrator.

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

## Supervisor lease and step semantics

Each claimed task persists a lease containing task id, owner identity, claim time, last heartbeat, expiry, and execution attempt. A valid lease blocks another owner. Expired leases can be reclaimed; waiting-for-approval and terminal tasks cannot be claimed. Brain execution claims before starting and releases the lease on completion or crash. TaskHeartbeat renews the same lease when an owner is supplied.

Each bounded step is persisted before execution with id, sequence, executor, action category, state, timestamps, attempt, retry limit, result summary, verification state, error category, and retry eligibility. Only operational facts are recorded; private model reasoning is excluded.

## Retry and recovery semantics

Failures are classified as TRANSIENT, RECOVERABLE, REQUIRES_ACTION, or TERMINAL. Retryability is derived from category, attempt budget, and mutation safety. Retry metadata records attempts, limit, summary, raw operational error, and next eligible time. Approval/governance failures wait for action and are never automatically retried. Deterministic or exhausted failures become terminal.

On startup, running tasks become interrupted and persist one of RESUME_SAFE or VERIFY_BEFORE_RETRY based on the last step. An uncertain mutating or verifying step requires independent verification before another execution claim. Recovery decisions deny claims for VERIFY_BEFORE_RETRY, WAIT_FOR_APPROVAL, BLOCKED, and TERMINAL_FAILURE. Lease recovery never bypasses Phase 4 capability, approval, provenance, or verification checks.

Existing agent completion still requires a structured final result and, for mutations, Phase 4 independent verification.

## Chosen first slice

This slice extends core/task_store.py and the existing core/task_heartbeat.py/core/brain.py path. It provides durable ownership, bounded step records, structured failure classification, bounded retry decisions, and startup recovery decisions while preserving the established governance and verification boundaries.

## Remaining migration work

1. Add an explicit supervisor queue/runner that consumes the persisted lease and step records for API background work.
2. Connect independent verification adapters to VERIFY_BEFORE_RETRY decisions.
3. Route CLI, voice, and remote clients through the same durable task API.
4. Add executor health/preflight and richer structured event streaming.
5. Add cancellation/pause semantics at step boundaries and idempotency evidence for mutating executors.
6. Expand the canonical event vocabulary while preserving the existing bounded event stream and Phase 4 provenance/verification records.


## Phase 5 Slice 3: Durable Supervisor Queue / Runner

The core.supervisor.SupervisorRunner is a lightweight durable coordinator over the existing TaskStore, Brain, heartbeat, governance, and verification boundaries. It does not create a second task model. Each cycle discovers deterministic eligible snapshots, performs preflight, claims an exclusive lease, checks cancellation, delegates one bounded Brain execution, records concise events, and releases the lease. A task-level exception is persisted as recoverable retry work and isolated from other tasks.

Queue eligibility is limited to pending or interrupted tasks whose lease is absent/expired, whose recovery decision is not approval/blocked/terminal, and whose retry.next_retry_at is due. Valid leases exclude other runners. Retry scheduling persists attempt, limit, category, reason, and an exponential bounded next_retry_at; exhaustion becomes terminal failure. The idle loop waits rather than busy-polling.

Startup recovery remains owned by TaskStore. RESUME_SAFE and due RETRY_SAFE work may continue. VERIFY_BEFORE_RETRY invokes the injected independent verifier before any rerun; failed or unavailable verification blocks the task. WAIT_FOR_APPROVAL, BLOCKED, and TERMINAL_FAILURE never execute.

Preflight emits preflight_started, validates an injected prerequisite check and an explicitly persisted workspace, and persists a structured block instead of crashing. Durable cancellation is checked immediately before execution, so disconnected clients do not affect server-side task lifetime and cancellation prevents new work. Existing Brain execution remains authoritative for governance, action approval, bounded steps, heartbeat renewal, and final verification.

Remaining gaps: the runner is currently a local process and must be started by the server lifecycle in a later slice; richer executor-specific preflight adapters and a persisted wake-up/index are intentionally deferred.


## Phase 5 Slice 5: Lightweight Smart Auto-Approve Governance

Auto Approve is implemented as a deterministic local-first policy at the existing governed agent dispatch boundary. The model proposes what to do; policy code decides whether the action may proceed. Normal actions do not trigger an LLM classification call. An optional future ambiguous-action adapter can consume only compact action metadata and must fail closed to user approval.

The policy classifies structured tool metadata and command effects into READ_ONLY, TRUSTED_WORKSPACE_WRITE, TEST_EXECUTION, SAFE_PROCESS_EXECUTION, NETWORK_READ, NETWORK_MUTATION, GIT_READ, GIT_FEATURE_BRANCH, GIT_COMMIT, GIT_PUSH_FEATURE_BRANCH, CANONICAL_BRANCH_CHANGE, DESTRUCTIVE_FILESYSTEM, CREDENTIAL_ACCESS, SYSTEM_CONFIGURATION, RELEASE_OPERATION, or UNKNOWN. Risk is LOW, MEDIUM, HIGH, or CRITICAL. Modes exposed to the product are OFF, SAFE, and TRUSTED_WORKSPACE. OFF requires manual approval for governed mutations; SAFE permits LOW-risk actions; TRUSTED_WORKSPACE also permits permitted MEDIUM actions only inside the explicitly supplied workspace scope.

Scoped capability bundles reduce approval spam without introducing a second execution authority. Each bundle carries an id, task/session binding, workspace scope, allowed and denied action classes, creation/expiry timestamps, optional use bounds, and provenance. A capability is accepted only when all bindings and scope checks match. Exact fingerprints, state-bound approvals, task leases, governance invocation validation, and independent verification remain authoritative. Hard stops include canonical/master changes, force pushes, releases/tags, credentials/secrets, and destructive or security-sensitive operations.

Every policy decision emits concise approval_policy_decided metadata, including decision, action class, risk tier, reason, scope, and capability id. The API exposes GET/POST /governance/auto-approve for the user-facing mode state; changing the mode changes policy behavior rather than skipping approval checks. The evaluation path is in-memory and bounded, with no filesystem scan, repo discovery, hardware probe, conversation history, or model call.
