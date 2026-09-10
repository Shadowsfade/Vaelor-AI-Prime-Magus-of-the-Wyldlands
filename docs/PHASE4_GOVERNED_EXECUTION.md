# Phase 4 governed execution integration

## Milestone 3C: execution is not verification

An executor completing without raising an exception is only an execution outcome. It
does not prove that the requested state transition occurred. A governed mutation now
has two distinct outcomes: `action_completed` describes callable completion, while
`verification_passed` is emitted only after trusted code independently rereads fresh
state and a supported verifier returns `passed`. Contradictory state emits
`verification_failed`; an unsupported state adapter emits `verification_unavailable`.
The model's request to run a test or inspect a file is an ordinary model action, not
an independent verification result.

The bounded `VerificationRequirement` contract contains a requirement ID, exact
governed fingerprint, tool/category, trusted expected postcondition, pre-execution
state reference, and verifier adapter identity. The resulting bounded record contains
the task ID, step ID, governed fingerprint, fresh evidence ID, verifier identity,
status, evidence summary, and a bounded failure/unavailability reason. It excludes
prompts, hidden reasoning, file contents beyond bounded hashes, credentials, and
tokens. Requirements are stored inside pending/authorized invocations, so approval
pause, TaskStore reload, restart, and resume preserve the exact contract; trusted
code reconstructs and revalidates it rather than accepting model-authored fields.

Supported independent adapters are local file write/patch, deletion, directory
creation, and selected local Git mutations. File adapters preserve path identity,
reject symlink/type substitution, and compare exact content hashes when the intended
content is available. Git adapters bind repository identity, HEAD, branch/detached
state, and worktree/index status before execution, then inspect fresh Git state after
execution. Unsupported mutations remain separately executable where policy permits,
but are `verification_unavailable` and cannot satisfy a task requiring verified
mutation.

Runtime capabilities are UTC-expiry validated, pruned individually under the same
lock used for issuance/claim, bounded, and atomically claimed-and-consumed. Expired
entries do not clear live entries; exhausted capacity fails closed. A claimed token
cannot be replayed after callable success or exception. The private test reset is
not serialized or registered as a tool.

Known limitations: Git transition validation currently proves a fresh, repository-
bound state transition rather than interpreting every operation's semantic diff;
large file content is represented by a bounded cryptographic hash; remote services,
package managers, permissions, and other environmental mutations remain unavailable
until trustworthy adapters exist.

The canonical branch retains its durable task store, ReAct loop, exact action approval,
heartbeat, verification, and event transport. Governance is additive: typed evidence
provenance and bound action fingerprints describe why an action is proposed, while the
existing task approval boundary remains authoritative.

A mutating action must be evaluated by policy and, where required, approved for the exact
tool, arguments, target, scope, and current-state binding. Every model-driven action now
crosses `ToolRegistry.execute_guarded`; authorization is created only by the trusted loop,
never from model arguments. Mutation requirement comes from authoritative tool metadata and
shell command classification; caller flags can only increase protection. Durable approvals
carry a state binding and are rejected when it is missing or differs. Unknown tool metadata
fails closed.

The action fingerprint is independently reconstructed by the gateway from the registered
tool, invocation arguments, target/scope/effects/state, task and step identifiers, and
provenance identifiers. Runtime-issued capabilities are ephemeral, process-local,
single-use tokens layered on durable TaskStore approval; they do not survive restart and
cannot replace durable approval. A constructed authorization object is not accepted.

Historical memory and model text are evidence, never permission. Current observations outrank
stale history. Quarantined or unavailable evidence cannot support mutation. The ReAct loop
also stops after repeated identical actions and emits a bounded `stalled` event rather than
looping indefinitely. Existing task events and API/SSE transport remain the delivery boundary;
private reasoning is not emitted.

This checkpoint does not add a second supervisor, provider router, persistence backend, or
self-modification path. State binding is supported for local file targets (type, existence,
size, mtime, and bounded content hash). Command-plus-cwd hashing is action identity, not
environmental verification; Git, service, package, permission, and remote-state adapters
remain unsupported and require renewed policy work. Existing task events remain the
durable/API transport and receive proposal, authorization, and verification events from
the loop.

Product version remains `1.1.4-alpha`; this is an unreleased development checkpoint.

Runtime capabilities are ephemeral process-local single-use tokens layered on durable
TaskStore approval. Claim and consumption are atomic immediately before callable dispatch;
capacity exhaustion fails closed rather than clearing live capabilities. Durable approvals
survive restart, while ephemeral capabilities do not. Provenance events identify bounded
current-state evidence; historical or unavailable evidence cannot authorize mutation.

## Entry-point audit

| Entry point | Untrusted/model reachable | Mutation boundary |
|---|---:|---|
| `run_agent` ReAct loop | yes | `execute_guarded`, durable approval/state binding |
| `VaelorBrain.use_tool` | API/internal helper | `execute_guarded`; mutations denied without runtime capability |
| `ToolRegistry.execute` | internal primitive | not a model-facing dispatch API; callers must use guarded dispatch |
| shell/file/Git callables | indirect | reached only through registry dispatch |
| task approvals/resume | user/admin boundary | TaskStore exact fingerprint and state checks |

Runtime capabilities are ephemeral and process-local; durable approval is the restart-safe
record. File state adapters include type, existence, size, mtime, and bounded content hash.
Git command bindings include repository identity, HEAD, branch, and status digest when the
repository can be observed. Other environmental state remains unsupported and must not be
described as verified.
