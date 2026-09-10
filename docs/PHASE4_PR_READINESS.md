# Phase 4 Governance PR Readiness

Status: ready for human review, with one environment-only acceptance limitation noted below. No merge, rebase, tag, release, or automatic PR creation was performed.

## Integration baseline

- Branch: `work/integrate-phase4-governance`
- HEAD at audit start: `c15b86c1ee1116b4677313fd3561b68aa7288a87`
- Upstream: `canonical/work/integrate-phase4-governance` (synchronized at audit start)
- Merge base: `3bd8f1f2e66c9dc8232d9d52d09f364befe3eb7a`
- Canonical master advanced after branch creation; the branch is an unrebased descendant of the recorded merge base. Conflict assessment: no working-tree conflict exists; human review should still compare the 14 Phase 4 commits against current master before merge.
- Product version remains `1.1.4-alpha`.
- Branch delta at audit start: 14 commits, 15 changed files, 1,369 insertions, 49 deletions. The milestone adds the lifecycle harness, immutable contract handling, package-policy checks, and this document.

The protected memory files were snapshotted before editing and restored after mutation-prone test batches. Final SHA-256 values are recorded in the handoff report, and no pytest process remains.

## Architecture and trust boundaries

The model produces a structured action candidate. The action protocol rejects malformed or reserved governance fields before registry validation. The registry derives authoritative risk and mutation classification from trusted tool metadata; shell and terminal commands are classified by command effect, not by a caller-supplied downgrade flag. A mutating action is bound to task/step identity, target, scope, effects, state binding, and provenance in a canonical fingerprint.

The durable task store is the authority for waiting approvals and restart state. Approval resume requires the exact pending fingerprint, invocation fields, state binding, task and step, and persisted verification requirement. Runtime authorization is an ephemeral, nonce-backed capability with expiry, bounded capacity, and atomic claim-before-dispatch semantics. Executors receive only the exact registry dispatch. Verification is independent of model output and is recorded from fresh state after execution; execution success alone is never verification.

## Threat model

Assumed adversaries include a malformed or adversarial model response, a caller attempting to downgrade a mutation, stale approval replay, concurrent capability claim, changed filesystem/Git state between approval and execution, malformed persisted data, ambiguous normalized values, and a tool that returns a success-looking string without performing the intended transition. The design fails closed for unsupported contract values, malformed requirements, unavailable verification adapters, stale state, invalid capabilities, and ambiguous argument keys.

## Mutation entry-point matrix

| Entry point | Authoritative control | Verification |
| --- | --- | --- |
| Agent action parser | schema and reserved-field rejection | governed invocation fingerprint |
| `ToolRegistry.execute_guarded()` | registry risk/read-only metadata; no caller downgrade | exact invocation and one-time capability claim |
| `VaelorBrain.use_tool()` | same registry boundary | cannot bypass task-scoped authorization |
| Shell/terminal | command-effect classification | local file/Git adapters where supported |
| Durable approval/resume | exact persisted action and state | persisted requirement revalidated before consume |
| Git operations | repository identity, branch/ref and pre-state binding | `git.local` fresh-state adapter |
| Sandbox promotion | managed sandbox ID, exact validated head, source drift check | validation evidence and exact commit |
| Schedules/workflows | bounded inputs and registry metadata | ordinary task governance applies |
| Aider/self-extension paths | proposal/staging and existing governance boundary | no model-authored trust or verification authority |

## Immutable contracts and fingerprints

`GovernedInvocation`, `VerificationRequirement`, and `VerificationRecord` recursively freeze nested mappings and sequences at construction. Fingerprints use strict canonical JSON: sorted string keys, stable sequence representation, finite numeric values, and no `default=str` fallback. Unsupported objects, non-string mapping keys, and non-finite numbers fail closed. Persistence converts the immutable representation back to JSON-safe containers without changing the canonical fingerprint.

`ActionAuthorization` contains only immutable scalar identity and a private nonce. Runtime capabilities are stored separately, expire, are capacity-bounded, and are atomically consumed. Regression tests cover caller/nested mutation, JSON reload, argument-order invariance, unsupported values, duplicate/ambiguous key normalization, expiry, replay, and concurrency.

## Supported verification adapters

- `local.file`: exact file content/size where available, deletion, real directory type, and symlink rejection.
- `git.local`: repository identity, branch, index/tree, parent transition, exact checkout target, and observable remote/ref transitions.

Unsupported verification cases return `unavailable` or fail closed: unknown adapters, incomplete requirements, unverifiable remote state, unsupported initial-commit transitions, and mutations without a concrete adapter. A successful executor return string is not verification.

## Durable versus ephemeral state

Durable state includes task lifecycle, pending approvals, authorized invocation/verification requirements, activity events, schedule records, and validation-sandbox records. Ephemeral state includes runtime authorization nonces, scheduler worker threads, ASGI client runner state, and fresh observation evidence. Durable event data is bounded and records identifiers/status rather than private payloads or credentials.

## API lifespan behavior

`api.server` uses an explicit FastAPI lifespan context. Scheduler startup occurs once on lifespan entry and shutdown occurs once in `finally`; import alone does not start a worker. Startup failure clears partial scheduler state, and shutdown is safe when startup was incomplete. The test-only `SynchronousASGIClient` uses one persistent `asyncio.Runner` and one ASGI lifespan task, an in-process ASGI message exchange, the `testclient` identity, persistent cookies, supported request methods, exception propagation, and deterministic shutdown. It does not patch Starlette's `TestClient` globally and production code never imports `conftest.py`.

## Warning classification and disposition

The pre-milestone baseline reported 47 warnings: 46 from pinned FastAPI's Python 3.14 use of deprecated `asyncio.iscoroutinefunction`, and one from pinned Starlette's deprecated AnyIO `BlockingPortal` alias. Vaelor-owned `@app.on_event` lifecycle handlers were migrated to the explicit lifespan context. The remaining filters are exact third-party module/message filters in test configuration only; Vaelor-owned `api` and `core` deprecations are treated as errors in the focused gate. No production warning suppression was added.

## Regression matrix

The final complete dependency-enabled run passed normally: **286 passed, 4 subtests passed, exit 0, 3.21 seconds**. Collection passed with **286 tests collected**. The focused governance/API/lifecycle/package batch passed **138 tests**, including warnings-as-errors for Vaelor-owned `api` and `core` deprecations. The source-level release metadata and clean-package policy tests passed.

The full matrix covered governance/verification, approval/restart/concurrency, brain/runtime, API/authentication/scheduler, terminal/sandbox, release metadata, and package-policy tests. No test contacts LM Studio, Ollama, OpenAI, GitHub, or another external model/backend.

## Packaging result

Runtime import validation passed without pytest/test-only imports, and the package policy excludes `.venv`, caches, `conftest.py`, `requirements-test.txt`, test modules, memory state, credentials, and builder-specific paths. The repository's full clean-package acceptance command could not execute in this Linux environment because the existing Windows package builder requires PowerShell 5.1+; no `powershell` or `pwsh` executable is installed. This is the remaining environment-only gate for a Windows acceptance rerun.

## Known limitations and rollback

The verification adapters intentionally do not claim unsupported external-provider or opaque custom-tool mutations. The API test harness contains a narrow Python 3.14 compatibility path and should be removed when the pinned dependency/runtime combination supplies a working lifespan-aware client. Rollback is a normal revert of the milestone commits on the branch; do not restore old startup handlers or weaken the governance boundary independently.

## Post-merge monitoring

Review scheduler start/stop counts and worker liveness, approval stale/conflict rates, verification `unavailable`/`failed` events, event-store growth, schedule overlap/claim behavior, and API authentication/cookie behavior. Re-run the complete dependency-enabled suite and Windows clean-package acceptance after dependency or Python-version changes.

## Deferred milestones

Deferred work includes broader independent adapters for external systems, richer bounded event retention/rotation, and replacing the test-only compatibility path once upstream Starlette/AnyIO support is stable on Python 3.14. These are not prerequisites for the current local governance boundary.
