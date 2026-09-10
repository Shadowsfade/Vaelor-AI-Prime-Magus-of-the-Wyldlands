# Phase 4 governed execution integration

The canonical branch retains its durable task store, ReAct loop, exact action approval,
heartbeat, verification, and event transport. Governance is additive: typed evidence
provenance and bound action fingerprints describe why an action is proposed, while the
existing task approval boundary remains authoritative.

A mutating action must be evaluated by policy and, where required, approved for the exact
tool, arguments, target, scope, and current-state binding. `ToolRegistry.execute_guarded`
provides an explicit executor boundary for integrations; an authorization object cannot be
reused after any bound value changes. Unknown or missing authorization fails closed.

Historical memory and model text are evidence, never permission. Current observations outrank
stale history. Quarantined or unavailable evidence cannot support mutation. The ReAct loop
also stops after repeated identical actions and emits a bounded `stalled` event rather than
looping indefinitely. Existing task events and API/SSE transport remain the delivery boundary;
private reasoning is not emitted.

This checkpoint does not add a second supervisor, provider router, persistence backend, or
self-modification path. Full pending-approval revalidation, fresh-state adapters for every
canonical tool, and end-to-end verification linkage remain follow-up work where existing
canonical interfaces need deeper integration.

Product version remains `1.1.4-alpha`; this is an unreleased development checkpoint.
