# Phase 4 governed execution integration

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
