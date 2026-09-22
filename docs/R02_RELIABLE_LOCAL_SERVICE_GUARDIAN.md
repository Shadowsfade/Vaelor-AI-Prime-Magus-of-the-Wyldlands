# R0.2 — Reliable Local Service Guardian

**Branch:** `work/r02-local-service-guardian-20260922`
**Baseline:** `d58978f` (`work/r0-infrastructure-reliability-20260917`)
**Status:** implemented and tested on Legion Go (Linux/CachyOS)

---

## 1. What R0.2 adds

Vaelor can now keep himself available locally: an **out-of-process guardian**
detects when the API/runtime process is absent or unhealthy and restarts it —
within strict, deterministic limits. When the host, network, configuration, or
recovery authority is uncertain, the guardian **fails closed** instead of
acting.

The guardian is deliberately *outside* the Vaelor application process. An
internal thread cannot restart the process that contains that thread.

---

## 2. Process ownership

| Component | Owns | Runs as |
|---|---|---|
| **Guardian** | supervision loop, restart policy, its own PID file | independent process |
| **Vaelor API child** | the API/runtime, its own PID file | spawned child of guardian |
| **systemd --user (planned)** | bringing the *guardian* up at login | optional, approval-gated |

Rules:

- The guardian **never restarts itself** — it supervises only the child.
- The guardian may hold **at most one** instance lock (`guardian.pid`).
- Vaelor may have **at most one** child instance (`vaelor.pid`).
- PID files are acted upon **only after staleness is proven** (see §6).

---

## 3. Liveness vs readiness

| Signal | Question | Endpoint |
|---|---|---|
| **Liveness** | is the process there at all? | PID file + `/health` |
| **Readiness** | can it serve work? | `/readiness` |

A process can be **live but not ready** (still initializing), or **ready but
degraded** (model backend down). The guardian treats these differently:

- **absent** → restart (automatic)
- **unhealthy** → restart, subject to backoff/budget (automatic, bounded)
- **unknown** (probe error, contradictory evidence) → **diagnose only**
- **healthy** → leave alone

### Health contract (`core/infra/health_contract.py`)

Eight independent, bounded sections — no model calls, no long waits, no
mutation, no secrets:

```
process_alive · api_responsive · runtime_initialized · taskstore_readable
supervisor_alive · scheduler_alive · model_backend · readiness
```

Each section is evaluated separately and one failure never hides the others.
**A downed model backend yields `DEGRADED`, never a loss of the ability to
inspect status, approve work, or diagnose recovery.**

Overall rollup: `HEALTHY` / `DEGRADED` / `UNHEALTHY` / `UNKNOWN`.

---

## 4. Observer / target identity

R0.1 could mix local and remote evidence. R0.2 makes identity explicit via
`core/infra/node_config.py` (`config/nodes.json`, optional) and enforces a
**scope guard** in `core/infra/observation.py`.

Every observation records:

```
observer node · target node · configured hostname · target Tailscale IP
probe type · observation timestamp · bounded timeout · evidence scope
```

**Invariant:** local process/model evidence is never written onto a remote
target. Requesting a remote target from a local observer **withholds** the
local probes and returns `UNKNOWN` with an explanation — it does not guess.

### Conditions (`core/infra/condition.py`)

| Condition | Meaning |
|---|---|
| `HEALTHY` | host + process + health endpoint all observed ok |
| `DEGRADED` | something required/optional is failing but host is up |
| `HOST_UNREACHABLE` | **local** observer reports its own host down |
| `NETWORK_PATH_UNAVAILABLE` | remote target unreachable; *host state cannot be distinguished from a broken path* |
| `VAELOR_PROCESS_DOWN` | configured local process absent |
| `VAELOR_UNHEALTHY` | process alive, health endpoint failing |
| `MODEL_BACKEND_DOWN` | model backend unavailable; everything else usable |
| `MISCONFIGURED` | missing/invalid config, ambiguous node identity |
| `UNKNOWN` | insufficient **or contradictory** evidence |
| `RECOVERING` | explicit recovery in progress |

**Contradictory evidence resolves to `UNKNOWN` with an explanation — never to
a confident DOWN diagnosis.** Examples: "host unreachable but health endpoint
answered", "health answered but no listener observed".

`NodeState` remains the coarse R0.1 rollup (`HEALTHY`/`DEGRADED`/
`UNREACHABLE`/`UNKNOWN`/`RECOVERING`); `NodeCondition` is the precise
diagnosis. `condition_to_state()` maps between them.

---

## 5. Automatic recovery boundary

`core/infra/recovery_authority.py` is a deterministic, trusted-code policy
matrix. It only *decides*; it never executes.

### Automatically recoverable

- local Vaelor process is absent
- the configured local service exited
- health endpoint failed while host and service manager remain observable
- a stale PID file is **proven** stale
- a previously healthy local instance needs a bounded restart

### Approval-required (never automatic)

Tailscale install/config/service changes · firewall changes · system package
installation · credential repair · Wake-on-LAN · remote host power actions ·
reboot/shutdown · Windows service installation · systemd service
installation · canonical Git changes · unknown commands · ambiguous node
identity · contradictory evidence · repeated crash loops · recovery that
could affect unrelated services

### Fail-closed defaults

- Any action **not enumerated** as automatic → approval-required.
- Any `source` other than `"guardian"` (model response, task record, memory
  record, web response, conversation) → approval-required, reason
  `unknown_command_source`.
- Any blocker present (`repeated_crash_loop`, `contradictory_evidence`,
  `ambiguous_node_identity`, `host_unreachable`, `missing_configuration`,
  `stale_state_uncertain`, `unknown_command_source`) → **diagnose only**.

**Host-down recovery is never represented as successful merely because a
command was attempted** — such decisions carry no command at all, so nothing
can be "attempted".

---

## 6. Restart / backoff / circuit-breaker behaviour

`core/infra/guardian_backoff.py` — pure logic, injectable clock, no I/O.

- **Backoff:** exponential `base × factor^(n-1)`, capped at `max_seconds`,
  ±25% jitter (seedable for tests).
- **Restart budget:** bounded restart allowance (default 5, range 1–100).
- **Circuit breaker:** opens after N consecutive failures (default 3), half-opens
  after cooldown (default 30 s); a failed probe re-opens immediately.
- **Healthy interval:** the budget resets **only after** the child stays healthy
  for `healthy_interval_seconds` (default 60 s). A brief survival followed by a
  failure clears the health streak — **crash loops cannot be laundered into an
  infinite restart loop by waiting.**

### Safety properties

| Property | Mechanism |
|---|---|
| one guardian | `InstanceGuard` + `guardian.pid`, refused if live owner |
| one Vaelor | `PidFile` check + responsive-API check before spawn |
| stale PID | proven stale only if dead **or** identity mismatch |
| corrupt state | fails closed to a clean, flagged state |
| shell injection | config rejects any string command — **argv arrays only** |
| untrusted commands | authority matrix `source != "guardian"` → blocked |
| clean shutdown | SIGTERM/SIGINT → stop child → persist state → release lock |

Recovery events (`core/infra/guardian_events.py`) are structured, bounded
(500 on disk, 400 chars/field), and **redacted of credentials before
persisting**. Persistence failure degrades to in-memory only rather than
raising during recovery.

---

## 7. Linux deployment plan (CachyOS)

**Nothing below is installed or enabled by R0.2 without explicit approval.**

1. Verify the plan is valid (read-only):
   ```
   python vaelor.py infra guardian status
   ```
2. Render and inspect the user unit (writes nothing):
   ```
   python -c "from core.infra.service_adapters import SystemdUserAdapter;
   from pathlib import Path; a=SystemdUserAdapter(worktree=Path.cwd());
   print(a.render()); print('problems:', a.validate())"
   ```
3. **Only with explicit approval:**
   - write the unit to `~/.config/systemd/user/vaelor.service`
   - `systemctl --user daemon-reload`
   - `systemctl --user enable --now vaelor.service`
4. Confirm: `systemctl --user status vaelor`

The unit sets `Restart=no` because **the guardian owns restart policy**;
systemd must not race it.

### Running the guardian

```
python vaelor.py infra guardian status      # observe + decide (no action)
python vaelor.py infra guardian run-once    # exactly one cycle
python vaelor.py infra guardian run         # supervision loop (SIGTERM to stop)
```

### Disabling the guardian

- Set `"enabled": false` in `config/guardian.json`, **or**
- simply do not run `guardian run` (it is opt-in; nothing auto-starts in R0.2).

### Rollback

```
git checkout work/r0-infrastructure-reliability-20260917
# or, to abandon R0.2 entirely:
git branch -D work/r02-local-service-guardian-20260922
rm -rf memory/guardian/          # local guardian runtime state
```
No OS service was installed, so no unit file needs removal. If a unit was
installed under approval: `systemctl --user disable --now vaelor.service` and
delete the unit file.

---

## 8. Windows deployment plan

**Not validated — no Windows host was contacted or modified by R0.2.**

- `WindowsServiceAdapter` is a **contract**: it plans deterministic argv and
  reports `platform_supported=False` when not on Windows, and
  `validated=False` always. It does **not** pretend to validate Windows
  service behavior on Linux.
- The existing persistent launcher arrangement is *described*, not installed.
- Planned steps for a real Windows deployment (each requires approval):
  1. `sc.exe` plan review via the adapter (dry-run only)
  2. verify the guardian's argv against the actual Python path
  3. install/configure the service **with explicit approval**
  4. run `python vaelor.py infra guardian run-once` and confirm one clean cycle

---

## 9. Context handoff / untrusted summaries

Preserved from the R0.1 boundary and **not weakened**:

- Handoffs and compaction summaries are **untrusted narrative data**.
- Authorization, capabilities, task state, approvals, and verification always
  reload from authoritative runtime records.
- **A summary cannot authorize recovery or alter guardian configuration.**
  Configuration is read only from trusted local `config/guardian.json`, and
  any unknown key fails closed.
- Uploading/publishing files is **not** implied by shell or network access;
  no automatic publication behavior was added.

---

## 10. Remaining physical-server validation (skyai)

Not achievable from Legion Go; requires physical/remote access to the Windows
host:

- [ ] Verify guardian behavior against the real Windows launcher
- [ ] Confirm health contract sections against a live Windows Vaelor
- [ ] Validate PID/staleness semantics on Windows (msvcrt locking path)
- [ ] Capture fresh event baseline (WHEA / BugCheck / Kernel-Power)
- [ ] TEST 0 passive idle observation (15–30 min) with stop conditions
      (WHEA, BSOD, 85 °C)
- [ ] HWiNFO64 + Coreinfo telemetry installation

> **No claim is made that the Windows server is suffering a hardware failure.**
> Prior evidence recorded WHEA Cache Hierarchy errors (APIC 7, Bank 5) and
> BugCheck 0xA as *historical* observations; current live status was not
> re-verified in this milestone.

---

## 11. Exact manual validation commands

```bash
cd ~/Vaelor-R0.1

# Baseline
.venv/bin/python -m pytest --collect-only -q
.venv/bin/python -m pytest -q

# Focused R0.2
.venv/bin/python -m pytest test_infra.py test_guardian.py test_node_identity.py -q

# CLI behavior (read-only)
.venv/bin/python vaelor.py infra status
.venv/bin/python vaelor.py infra guardian status
.venv/bin/python vaelor.py infra guardian run-once

# Governance / hygiene
git diff --check
git status --short
sha256sum memory/archive.json memory/conversations.json memory/tasks.json \
          memory/preferences.json memory/proposals.json memory/sessions.json
```

Expected: collection clean, full suite passing, `infra status` reporting
observer/target/scope/condition explicitly, guardian status deciding **without
acting**, `git diff --check` silent, and all six hashes unchanged.

---

## 12. Known limitations

1. **Windows adapter is contract-only** — no real Windows behavior validated.
2. **No systemd unit is installed** — deployment requires explicit approval.
3. **Remote observation is withheld, not implemented** — a remote target
   returns `UNKNOWN` rather than a real remote probe (correct, but means
   skyai cannot be observed from Legion Go yet).
4. **Guardian does not survive its own machine's sleep/hibernate** without a
   service manager bringing it back.
5. **Backoff/budget numbers are defaults**, not yet tuned against observed
   crash signatures.
6. **`observe_remote()` remains a placeholder** (documented in code).
