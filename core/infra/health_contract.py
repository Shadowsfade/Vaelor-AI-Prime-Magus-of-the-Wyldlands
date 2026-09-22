"""Vaelor health contract for the guardian (R0.2 Phase 5).

Distinguishes process-alive from API-responsive from ready. Every section
is evaluated independently, bounded, and never raises: one broken
subsection must not hide the rest.

Rules:
- no model calls
- no long network waits (bounded timeouts)
- no state mutation
- no secrets in output
- model backend down yields DEGRADED, not a loss of inspectability
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from core.infra.condition import bounded_error, redact


SECTION_ORDER = (
    "process_alive",
    "api_responsive",
    "runtime_initialized",
    "taskstore_readable",
    "supervisor_alive",
    "scheduler_alive",
    "model_backend",
    "readiness",
)

# Sections that reflect local process/API liveness rather than backend luck.
CORE_SECTIONS = (
    "process_alive",
    "api_responsive",
    "runtime_initialized",
    "taskstore_readable",
    "supervisor_alive",
    "scheduler_alive",
)


@dataclass
class HealthSection:
    """One bounded, independent health subsection."""

    name: str
    ok: Optional[bool]          # None == unknown, never silently False
    detail: str = ""
    error: Optional[str] = None
    data: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.ok is None:
            return "UNKNOWN"
        return "OK" if self.ok else "FAIL"

    def to_dict(self) -> dict:
        return redact({
            "name": self.name,
            "ok": self.ok,
            "status": self.status,
            "detail": self.detail[:300],
            "error": self.error,
            "data": self.data,
        })


@dataclass
class HealthReport:
    """Full health report with a coarse state and fine condition."""

    sections: dict = field(default_factory=dict)
    observed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def add(self, section: HealthSection) -> None:
        self.sections[section.name] = section

    @property
    def overall(self) -> str:
        """HEALTHY | DEGRADED | UNHEALTHY | UNKNOWN."""
        core = [self.sections.get(n) for n in CORE_SECTIONS]
        known = [s for s in core if s is not None and s.ok is not None]
        if not known:
            # No core evidence: everything else being fine still helps.
            any_ok = any(s.ok for s in self.sections.values())
            return "HEALTHY" if (any_ok and len(self.sections) > 1) else "UNKNOWN"
        failed = [s for s in known if s.ok is False]
        if len(failed) == len(known):
            return "UNHEALTHY"
        if failed:
            return "DEGRADED"

        backend = self.sections.get("model_backend")
        if backend is not None and backend.ok is False:
            # Model backend down must not erase inspectability.
            return "DEGRADED"

        unknown_core = [s for s in core if s is None or s.ok is None]
        if unknown_core:
            return "DEGRADED"
        return "HEALTHY"

    @property
    def ready(self) -> bool:
        return self.overall == "HEALTHY"

    @property
    def degraded_reasons(self) -> list:
        out = []
        for name in SECTION_ORDER:
            sec = self.sections.get(name)
            if sec is None:
                continue
            if sec.ok is False:
                out.append(f"{name}: {sec.detail or sec.error or 'failed'}")
            elif sec.ok is None:
                out.append(f"{name}: unknown")
        return out

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "ready": self.ready,
            "observed_at": self.observed_at,
            "sections": {
                name: sec.to_dict() for name, sec in self.sections.items()
            },
            "degraded_reasons": self.degraded_reasons,
        }


def _section(name: str, fn: Callable[[], HealthSection]) -> HealthSection:
    """Run one health check; never let it raise into the caller."""
    try:
        return fn()
    except Exception as exc:   # noqa: BLE001 - bounded by design
        return HealthSection(name=name, ok=False,
                             detail="health check raised",
                             error=bounded_error(exc))


def _http_section(name: str, url: str, timeout: float,
                  expect_status: int = 200) -> HealthSection:
    """GET a local endpoint with a bounded timeout. No model calls."""
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(8192).decode("utf-8", errors="replace")
            code = resp.getcode()
    except urllib.error.HTTPError as exc:
        # An HTTP error still proves the API is responsive.
        return HealthSection(
            name=name, ok=(exc.code == expect_status),
            detail=f"HTTP {exc.code} from {url}",
            data={"status_code": exc.code},
        )
    except Exception as exc:   # noqa: BLE001
        return HealthSection(
            name=name, ok=False,
            detail=f"request failed for {url}",
            error=bounded_error(exc),
        )

    payload = {}
    if body.strip():
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                payload = parsed
        except ValueError:
            payload = {}

    return HealthSection(
        name=name, ok=(code == expect_status),
        detail=f"HTTP {code} from {url}",
        data={"status_code": code, "payload_keys": sorted(payload)[:20],
              "payload": payload if len(body) < 2000 else {}},
    )


def assess_health(*,
                  process_alive: Optional[bool],
                  health_url: str,
                  readiness_url: str,
                  timeout: float = 2.0,
                  runtime_status: Optional[dict] = None,
                  backend_probe: Optional[Callable[[], dict]] = None) -> HealthReport:
    """Assemble a full HealthReport without any model involvement.

    ``process_alive`` and ``runtime_status`` are supplied by the caller so
    this function performs no process signalling of its own.
    ``backend_probe`` is optional; omitting it yields UNKNOWN for the
    model backend rather than a false FAIL.
    """
    report = HealthReport()

    report.add(_section(
        "process_alive",
        lambda: HealthSection(
            name="process_alive",
            ok=process_alive,
            detail=("process observed alive" if process_alive
                    else "process not observed alive" if process_alive is False
                    else "process liveness not observed"),
        ),
    ))

    report.add(_section(
        "api_responsive",
        lambda: _http_section("api_responsive", health_url, timeout),
    ))

    # Runtime-derived sections all come from one bounded status call.
    status = runtime_status
    if status is None:
        try:
            import urllib.request
            url = health_url.rsplit("/health", 1)[0] + "/runtime/status"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = json.loads(resp.read(65536).decode("utf-8",
                                                            errors="replace"))
        except Exception:      # noqa: BLE001
            status = None

    def _from_status(label: str, extractor) -> HealthSection:
        if not isinstance(status, dict):
            return HealthSection(name=label, ok=None,
                                 detail="runtime status unavailable")
        try:
            return extractor(status)
        except Exception as exc:  # noqa: BLE001
            return HealthSection(name=label, ok=False,
                                 detail="runtime status unreadable",
                                 error=bounded_error(exc))

    report.add(_section(
        "runtime_initialized",
        lambda: _from_status("runtime_initialized", lambda s: HealthSection(
            name="runtime_initialized",
            ok=bool(s.get("server")),
            detail="server section present" if s.get("server")
                   else "server section missing",
        )),
    ))

    report.add(_section(
        "taskstore_readable",
        lambda: _from_status("taskstore_readable", lambda s: _taskstore(s)),
    ))

    report.add(_section(
        "supervisor_alive",
        lambda: _from_status("supervisor_alive", lambda s: _flag(
            "supervisor_alive", s.get("supervisor"),
            "supervisor thread running")),
    ))

    report.add(_section(
        "scheduler_alive",
        lambda: _from_status("scheduler_alive", lambda s: _flag(
            "scheduler_alive", s.get("scheduler"),
            "scheduler thread running")),
    ))

    # Model backend: optional probe; absence -> UNKNOWN, not FAIL.
    def _backend() -> HealthSection:
        if backend_probe is None:
            return HealthSection(
                name="model_backend", ok=None,
                detail="no backend probe supplied",
            )
        try:
            result = backend_probe() or {}
        except Exception as exc:  # noqa: BLE001
            return HealthSection(
                name="model_backend", ok=False,
                detail="backend probe raised",
                error=bounded_error(exc),
            )
        if not isinstance(result, dict):
            return HealthSection(name="model_backend", ok=None,
                                 detail="backend probe returned non-object")
        ok = result.get("ok")
        return HealthSection(
            name="model_backend",
            ok=bool(ok) if ok is not None else None,
            detail=str(result.get("detail") or "backend probe result"),
            data={"models": list(result.get("models") or [])[:10]},
        )

    report.add(_section("model_backend", _backend))

    # Readiness: derived from the readiness endpoint, bounded.
    report.add(_section(
        "readiness",
        lambda: _readiness(readiness_url, timeout),
    ))

    return report


def _taskstore(status: dict) -> HealthSection:
    tasks = status.get("tasks")
    if not isinstance(tasks, dict):
        return HealthSection(name="taskstore_readable", ok=None,
                             detail="task section missing from runtime status")
    if tasks.get("status") == "degraded" or tasks.get("error"):
        return HealthSection(
            name="taskstore_readable", ok=False,
            detail="task store reported degraded",
            error=str(tasks.get("error") or "")[:300],
        )
    return HealthSection(name="taskstore_readable", ok=True,
                         detail="task aggregates readable",
                         data={k: v for k, v in tasks.items()
                               if isinstance(v, (int, str, bool))})


def _flag(name: str, value, positive_detail: str) -> HealthSection:
    if not isinstance(value, dict):
        return HealthSection(name=name, ok=None, detail=f"{name} not reported")
    if value.get("status") == "degraded" or value.get("error"):
        return HealthSection(
            name=name, ok=False,
            detail=f"{name} degraded",
            error=str(value.get("error") or "")[:300],
        )
    running = value.get("running")
    if running is None:
        return HealthSection(name=name, ok=None, detail=f"{name} state unknown")
    return HealthSection(name=name, ok=bool(running),
                         detail=positive_detail if running
                         else f"{name} not running")


def _readiness(url: str, timeout: float) -> HealthSection:
    import urllib.error
    import urllib.request
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            body = resp.read(8192).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        # 503 is a legitimate "not ready" answer, and still responsive.
        return HealthSection(
            name="readiness", ok=(exc.code == 200),
            detail=f"readiness HTTP {exc.code}",
            data={"status_code": exc.code},
        )
    except Exception as exc:   # noqa: BLE001
        return HealthSection(name="readiness", ok=False,
                             detail=f"readiness request failed for {url}",
                             error=bounded_error(exc))

    payload = {}
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            payload = parsed
    except ValueError:
        pass
    return HealthSection(
        name="readiness", ok=(code == 200),
        detail=f"readiness HTTP {code}",
        data={"status_code": code,
              "issues": [str(i)[:120] for i in (payload.get("issues") or [])][:10]},
    )
