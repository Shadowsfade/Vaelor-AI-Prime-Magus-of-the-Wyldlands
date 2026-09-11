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

## Phase 5 Slice 6: Lightweight Supervisor Health and Runtime Status

Runtime health is held in structured in-memory state by the singleton SupervisorRunner and SchedulerService. It records lifecycle state, ownership, start and cycle timestamps, successful-cycle timestamp, processed-task count, queue depth, and bounded error summaries. The server lifecycle starts and stops both services; client connectivity does not own their lifetime.

TaskStore.aggregate_counts() provides cheap current aggregates for pending, running, approval-waiting, blocked, retry-scheduled, interrupted, failed, succeeded, and cancelled tasks. The local GET /runtime/status endpoint combines these counts with the newest bounded task event, supervisor and scheduler snapshots, and the deterministic Auto Approve mode and last policy decision. It makes no model call, network request, log parse, or conversation reconstruction.

Status failures are isolated by section. An unreadable task store or unavailable runtime component produces a structured degraded section with a concise error while the status endpoint remains responsive. The endpoint is intentionally a small local diagnostic surface; it is not a metrics platform and does not expose private reasoning or secrets.

## Phase 5 Slice 7: Real-World Workflow Bring-Up

The first real workflow is a deterministic CachyOS/Arch application setup path entered through the ordinary durable task API: “Download jq, open it, and tell me how to use it on CachyOS.” Brain recognizes this narrow workflow without asking a model to classify routine orchestration, creates the normal durable task, and executes it only after the existing task lease is claimed.

The workflow detects the OS release, architecture, shell, user, home, and available pacman/paru/yay tools. It selects only the allowlisted official jq release source for this bring-up, places the binary under ~/.local/share/vaelor/tasks/<task-id>/jq, records the URL, destination, size, method, commands, and verification in the task record, and verifies both --version and --help before marking the task completed. Download, managed-workspace write, and launch decisions use the existing ApprovalPolicy; Auto Approve OFF pauses for approval, while the trusted-workspace policy can authorize the bounded setup.

The final result includes launch, usage, update, removal, and location guidance. Unsupported hosts or unsupported programs block rather than improvising. A failed download is persisted as recoverable retry work. User-input checkpoints use the existing waiting/recovery state and resume path; no separate workflow engine or client-owned lifetime is introduced.

Acceptance result: passed on the real CachyOS host. The exact request was 'Download jq, open it, and tell me how to use it on CachyOS.' Brain.prepare_task created durable task 2d879458-fd2, Brain.run_prepared_task detected CachyOS/x86_64/zsh with pacman, paru, and yay, selected the official pacman cache artifact jq-1.8.2-1.1-x86_64_v4.pkg.tar.zst, extracted it under the Vaelor-managed task directory, ran --version and --help, recorded artifact/command/verification data, and reached completed without manual terminal intervention.

## Real-World Workflow Bring-Up: Generic CachyOS/Arch Software

Slice 8 generalizes the prior jq bring-up. Natural-language requests use the existing durable task entry point, then deterministic code detects the CachyOS/Arch environment, extracts a safe program target, and resolves sources in this order: installed executable/package, official pacman/CachyOS repository, existing paru then yay AUR helper, and finally an allowlisted official upstream artifact. The resolver records the selected method and a concise source-selection reason; unsupported or ambiguous targets become durable BLOCKED work.

The workflow persists a compact installation plan, commands, artifacts, verification probes, and final result on the existing task record. Mutations remain behind ApprovalPolicy. Package installation uses non-interactive sudo checks: unavailable authentication produces WAITING_USER or WAITING_APPROVAL without hanging. TaskStore.resume_waiting returns the same task to the queue while preserving workflow/source/plan evidence; the normal claim/lease path then continues it. Verification checks executable existence and uses bounded non-interactive probes (--version, -V, version, --help, -h), stopping after the first successful probe; it never opens an interactive TUI.

Real Legion Go acceptance:
- Download btop, open it, and tell me how to use it on CachyOS. Created task 0dc93505-0ab; detected CachyOS x86_64 with pacman/paru/yay; selected already-installed btop; skipped installation; verified /usr/bin/btop --version successfully; completed.
- Install tree on CachyOS and tell me how to use it. Created task e7550584-e00; selected official pacman because the package exists in the official repository; persisted sudo -n pacman -S --needed --noconfirm tree; stopped cleanly for unavailable sudo authentication; resumed the same task ID and returned to waiting with its source and plan intact. No manual terminal driving or package mutation was performed.

The outer workflow remains suitable for future Windows, macOS, and other Linux backends; only the platform resolver/executor boundary is CachyOS/Arch-specific. Remaining gaps are authenticated privileged installation UX, broader upstream artifact metadata/checksums, and the future platform-neutral software workflow core.
# Phase 5 Slice 9: Portable software workflow core

Slice 9 extracts a compact, serializable software workflow contract from the
Slice 8 CachyOS implementation. `core/software_workflow.py` owns
`SoftwareRequest`, `SoftwareEnvironment`, `SoftwareSource`, `SoftwarePlan`,
`SoftwareArtifact`, `SoftwareVerification`, bounded safe verification, and
durable orchestration. `core/software_platforms/cachyos.py` is the first
`SoftwarePlatformAdapter`; it owns Arch-family detection, pacman/AUR/upstream
source details, command construction, and usage/update/removal instructions.

The flow is now detect -> canonicalize -> resolve -> plan -> persist plan ->
governance -> execute -> verify -> durable result/recovery. Platform adapters
never bypass ApprovalPolicy, Auto Approve, scoped capabilities, or waiting.
TaskStore remains the only task engine. A waiting task resumes with the same
task ID and persisted request, source, plan, artifacts, commands, events,
approval history, and recovery reason; completed mutation steps are not
repeated. Verification belongs to the portable core and requires a discoverable
executable plus one successful bounded non-interactive probe.

The current deterministic source order is already installed, official
repository, trusted community repository, allowlisted official upstream
artifact, then blocked/clarification. Unsupported platforms are durably
blocked; there is no LLM fallback for package installation.

Future adapters use the same core: Windows (`winget` -> Chocolatey -> official
upstream), macOS (Homebrew -> official upstream), Debian/Ubuntu (apt -> official
upstream), and Fedora (dnf -> official upstream). They are not implemented in
Slice 9.

## September 11 desktop continuation

The Slice 9 production entry now uses the portable core with the existing
TaskStore and heartbeat. Persisted step fields are `action_category` and `state`;
resume recognizes successful mutations using those fields. Existing Slice 8
records are converted without another source lookup, retaining the original plan
under `legacy_plan`. Changed adapter commands are rejected rather than silently
substituted for an approved plan. Uncertain/failed mutations wait for explicit
reconciliation and are not automatically repeated.

The Research button sends the current topic through the existing authenticated
chat endpoint's search mode. `VaelorBrain.research_answer` fetches bounded page
excerpts and invokes the configured reasoning model directly, with evidence and
untrusted-content instructions. It keeps sources and session history. The CLI
supports `--research topic` and interactive `/research topic`. No second task
engine, model configuration, or runtime service was introduced.

Validation on the Windows desktop includes the whole Python suite, inline UI
JavaScript syntax, and the isolated clean-package build/import/API smoke gate.
This is not a new on-device LEGO1 acceptance run. Real sudo installation and the
Research button with a live model still need acceptance on the target host.

Remaining release work: authenticated privilege/approval UX for package tasks,
reviewed upstream checksums and broader sources, Windows/macOS package adapters,
and a standalone installer that bundles its Python runtime. The portable ZIP
still requires Python. The WebUI remains the shared desktop presentation layer.

Verified result: 349 tests passed, one Windows symlink privilege skip, seven
subtests passed. Python compilation and inline JavaScript syntax passed.
The clean-package gate built and verified a 120-file archive and passed runtime smoke.

## Software approvals and host authentication

The portable software workflow now submits its exact operation to TaskStore's
existing pending-approval API. The card includes the full source and plan; its
SHA-256 fingerprint covers the task/session and all execution inputs. Approve
Once is consumed only after sudo preflight succeeds. Source/plan changes cause
another approval request, and a current policy DENY/AMBIGUOUS decision cannot
be overridden by an earlier approval.

A privilege wait has a separate Task Center Recheck Host Authentication button,
backed by POST /tasks/{id}/continue-software. It only requeues a software task
waiting for privilege, preserving its identity and plan. It does not collect
credentials, widen policy, or interpret a new natural-language task.
Authentication must be available to Vaelor's process on the host; sudo timestamp
sharing depends on host configuration. A successful click alone does not prove
credentials are available: preflight checks again and remains waiting if needed.

This completes the application approval/recheck wiring. Real privileged install
acceptance on LEGO1, additional OS adapters, upstream checksum verification,
and Python-bundled packaging remain release work.

Validation: full suite 354 passed and one Windows symlink-privilege skip; final focused approval suite seven passed (including two additional cases). Python compilation, JavaScript syntax, mocked UI recheck routing, and isolated clean-package acceptance passed. No live privileged installation was performed.
