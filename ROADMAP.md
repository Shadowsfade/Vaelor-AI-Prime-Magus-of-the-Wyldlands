# Vaelor Architecture & Oz-Like Intelligence Roadmap

## Primary Goal

Create Vaelor as an Oz-like Arcane Intelligence:
a persistent, context-aware assistant capable of helping build,
manage, and eventually create Project Wyld.

The priority is not simply making Vaelor answer questions.
The priority is creating a reliable intelligence layer with:

- Memory
- Context awareness
- Safe tools
- Project understanding
- Development assistance
- World-building capability

---

# PHASE 1 � Stabilize the Tower

Goal:
"I can start Vaelor anywhere and trust that he works."

## Completed

[x] One-command startup
[x] One-command shutdown
[x] Diagnostics system
[x] Virtual environment recovery
[x] Memory foundation
[x] SSH remote workflow
[x] Ollama integration
[x] FastAPI foundation
[x] Web interface foundation

## Remaining

[x] Better memory retrieval
[x] Persistent chat history
[ ] User/session identity
[ ] Service management dashboard
[ ] Reliable remote launcher

---

# PHASE 2 � True Memory Architecture

Current:

archive.json
|
+-- facts


Future:

Memory System

+-- Identity Memory
�   - Who is the Architect?
�   - Vaelor identity
�
+-- Project Memory
�   - Project Wyld decisions
�   - Architecture choices
�
+-- Technical Memory
�   - Code locations
�   - Systems
�   - Dependencies
�
+-- World Memory
�   - Wyldlands lore
�   - Locations
�   - Creatures
�
+-- Conversation Memory
�   - Previous discussions
�   - Design decisions
�
+-- Experience Memory
    - What was tried
    - What failed
    - Lessons learned


Required upgrades:

[x] Memory tagging
[x] Relevance search
[x] Memory ranking
[x] Duplicate consolidation
[x] Automatic bounded summaries and recent-turn retention
[x] Chat history storage

---

# PHASE 3 � Give Vaelor Hands

Goal:
Move from "code advisor" to "controlled development partner."

Architecture:

stage
 |
proposal
 |
approve
 |
execute


Required systems:

[x] Tool calling architecture
[x] Project scanner
[x] Multi-file reader
[x] Code proposal system
[x] Approval workflow
[x] Automated testing
[x] Error recovery
[x] Safe execution layer
[x] Evidence-bound exact-commit sandbox promotion
[x] Scoped hierarchical project instructions (`AGENTS.md` / `VAELOR.md`)
[x] Bounded automatic outcome learning from task feedback
[x] Canonical Prime Magus and emerging Wyldlands reality across inference paths
[x] Scoped reusable project workflows with ordinary action-policy enforcement
[x] Hardware-aware installed-model routing and provider-specific fallback
[x] Durable non-overlapping recurring task scheduler and controls
[x] Tome schedule observability, pause/resume, and last-run console access
[x] DNS-rebinding defense and opt-in authenticated non-loopback API boundary
[x] Authenticated remote Tome bootstrap and explicit trusted-interface launcher
[x] Isolated clean-package privacy, configuration, and runtime acceptance gate

---

# PHASE 4 � Project Wyld Integration

Goal:
Vaelor assists in creating the game world.

Unity:

[ ] C# script awareness
[ ] Prefab awareness
[ ] Scene awareness
[ ] ScriptableObject support
[ ] Build pipeline support


Unreal:

[ ] C++ awareness
[ ] Blueprint awareness
[ ] Data Asset support
[ ] Behavior Tree support
[ ] Level data awareness


---

# PHASE 5 � Living World Intelligence

Long-term vision:

NPCs become more than dialogue trees.

NPC:

+-- Personality Memory
+-- World Knowledge
+-- Goals
+-- Relationships
+-- Current State
+-- Vaelor reasoning layer


The world remembers.

The world reacts.

The world evolves.

---

# Current Development Priority

1. Add ConPTY full-screen terminal input and resize support
2. Extend bounded lexical code discovery with persistent semantic indexing
3. Add MCP tool extensibility
4. Validate the full interactive installer on additional physical clean machines
5. Strengthen user/session identity and profile separation
6. Add multi-agent orchestration
7. Create Unity/Unreal bridges

The foundation comes first.

The intelligence grows from the foundation.

---

# Post-stabilization capability direction

These are roadmap items only. They must reuse Vaelor's durable task runtime, governance, approval, observation, recovery, and verification boundaries. Do not implement them through larger prompts or parallel task engines.

## Capability adapters

- ComputerUse: observable screenshots, window enumeration, application focus/launch, bounded click/type/keyboard/scroll/clipboard, before/after evidence, and risk-gated confirmation. Prefer APIs, terminals, filesystem operations, and native automation.
- Capability/model routing: model-independent routing across general, reasoning, coding, vision, image generation, speech-to-text, and text-to-speech; smallest capable local model by default, health checks, safe fallback, and explicit override.
- Coding-agent supervision: Vaelor remains the durable supervisor for its own tools, OpenCode, Codex, and future backends: inspect, plan, edit, test, observe, recover, independently verify, and apply Git gates.
- Voice client: wake word or push-to-talk, STT, normal durable tasks, streamed events, concise status, and TTS. CLI, Web, Android, and future Android Auto clients share the same runtime.
- Vision/screen: structured screenshot, shared-screen, window, and explicitly enabled camera observations. Continuous monitoring must be visibly user-controlled.
- ImageGeneration: provider/model selection, generation, artifact tracking, preview/verification, and saved output through an adapter.
- 3D application adapters: begin with Blender's Python API for scene/model creation, materials, lighting, camera, rendering, import/export, preview verification, and saved artifacts; later consider Unity, O3DE, and other creative applications.
- Discoverable tool/plugin architecture: capability metadata, schemas, permissions, health, platform support, risk classification, and verification strategy without hardcoding every application into core agent logic.

## Context-scoped instructions

Use a small core Vaelor policy plus dynamically loaded capability instructions, relevant project context, and current durable task state. Load ComputerUse, Blender, coding, voice, or other instructions only for the active capability.

## Software direction

Explicit imperative software requests are ACTION regardless of whether the name is known. The current Windows adapter resolves only reviewed git, jq, and ripgrep metadata; unknown software must remain ACTION and produce deterministic trusted-source investigation or BLOCKED evidence rather than CHAT. Future discovery should search native package managers, configured trusted providers, and verifiable official upstream distributions, never model-invented URLs or commands.

## Target experience

Users state outcomes; Vaelor selects capabilities, models, tools, machines, plan, approvals, execution, and verification.

---

# R0 RELIABILITY TRACK

Goal:
"Vaelor stays available locally, and fails safely when anything is uncertain."

## R0.0 — Host stability (skyai)

[x] MEMORY.DMP + minidump analysis (BugCheck 0xA at `nt!KiInsertTimerTable`)
[x] WHEA analysis (15× Event 18, APIC 7 / Bank 5 Cache Hierarchy signature)
[x] Physical Visit Pack (R0.0B-F) prepared
[ ] Physical inspection, BIOS capture, HWiNFO64 + Coreinfo telemetry
[ ] TEST 0 passive idle observation (15–30 min, stop on WHEA / BSOD / 85 °C)

Status: **BLOCKED** — requires physical access. No hardware-failure conclusion
is asserted; recorded WHEA/BugCheck events are historical observations.

## R0.1 — Infrastructure observability

[x] `core/infra/*` status, classifier, observer, recovery, relay contract
[x] Platform probes for Windows **and** Linux
[x] Required probe `None` → `UNKNOWN` (never silently `DEGRADED`)
[x] Hardcoded ComputerUse-Foundation path removed
[x] `vaelor.py infra status` / `infra diagnose`

Status: **COMPLETE** — 30/30 focused tests passing.

## R0.2 — Reliable local service guardian

[x] Explicit, portable observer/target node identity (`config/nodes.json`)
[x] Scope guard: local evidence never attributed to a remote target
[x] Precise conditions: `HOST_UNREACHABLE` vs `NETWORK_PATH_UNAVAILABLE` vs
    `VAELOR_PROCESS_DOWN` vs `VAELOR_UNHEALTHY` vs `MODEL_BACKEND_DOWN`
    vs `MISCONFIGURED` vs `UNKNOWN`
[x] Contradictory evidence → `UNKNOWN` with explanation, never confident DOWN
[x] Out-of-process guardian: probe → decide → act, argv arrays only
[x] Exponential backoff + jitter, restart budget, circuit breaker,
    healthy-interval budget reset
[x] Duplicate guardian / duplicate Vaelor prevention, proven-stale PID files
[x] Bounded, credential-redacted structured recovery events
[x] Recovery authority matrix (automatic vs approval-required vs diagnose-only)
[x] Service-manager adapters: systemd-user (plan/validate) + Windows contract
[x] Health contract: 8 independent sections; model backend down → `DEGRADED`
[x] Crash/soak tests (temp dirs, fake clocks, injected adapters)
[x] Documentation: `docs/R02_RELIABLE_LOCAL_SERVICE_GUARDIAN.md`

Status: **COMPLETE on Legion Go** — 660 passed / 1 skipped full suite;
177 focused tests. No OS service installed.

Remaining (needs approval or physical access):
[ ] Install systemd --user unit (explicit approval required)
[ ] Windows adapter live validation
[ ] Guardian tuning against observed crash signatures

See `docs/R02_RELIABLE_LOCAL_SERVICE_GUARDIAN.md` for the recovery boundary,
deployment/rollback steps, and known limitations.
