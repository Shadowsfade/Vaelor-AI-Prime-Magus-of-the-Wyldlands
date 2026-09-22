"""Linux-specific infrastructure probes for Vaelor R0 observability.

All probes are read-only. No process termination, service restart,
or configuration changes.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.infra.status import ProbeEvidence, NodeState


# Known Vaelor ports from netbind.py (for reference)
VAELOR_PORTS = [8765, 8766, 8767, 8770, 8780, 8788, 8790, 8800, 8810, 8820]
# Common dev ports to scan but NOT assume Vaelor identity
EXTRA_PORTS = [7000, 8000, 11434]
ALL_PORTS = VAELOR_PORTS + EXTRA_PORTS


def _run_cmd(cmd: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def _run_cmd_shell(cmd: str, timeout: float = 5.0) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=True,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def probe_host_uptime(observer: str, target: str) -> ProbeEvidence:
    """Get Linux boot time / uptime using ISO-8601 UTC timestamp."""
    start = time.perf_counter()
    # Use /proc/uptime for reliable uptime
    rc, stdout, stderr = _run_cmd(["cat", "/proc/uptime"])
    latency = (time.perf_counter() - start) * 1000

    if rc == 0 and stdout:
        try:
            uptime_seconds = float(stdout.split()[0])
            boot_time = datetime.now(timezone.utc) - __import__('datetime').timedelta(seconds=uptime_seconds)
            return ProbeEvidence(
                probe="host_uptime",
                observer_node=observer,
                target_node=target,
                status="ok",
                latency_ms=latency,
                detail=f"uptime_seconds={uptime_seconds:.0f}",
                raw={"uptime_seconds": uptime_seconds, "boot_time_utc": boot_time.isoformat()},
            )
        except Exception as e:
            return ProbeEvidence(
                probe="host_uptime",
                observer_node=observer,
                target_node=target,
                status="failed",
                latency_ms=latency,
                detail=f"parse error: {e}",
                raw={"stdout": stdout, "stderr": stderr},
            )

    return ProbeEvidence(
        probe="host_uptime",
        observer_node=observer,
        target_node=target,
        status="failed",
        latency_ms=latency,
        detail=f"cmd failed: {stderr or stdout}",
        raw={"returncode": rc, "stdout": stdout, "stderr": stderr},
    )


def probe_tailscale(observer: str, target: str) -> list[ProbeEvidence]:
    """Probe Tailscale service, backend state, and peer reachability."""
    evidence = []

    # Service state
    start = time.perf_counter()
    rc, stdout, stderr = _run_cmd(["systemctl", "is-active", "tailscaled"])
    latency = (time.perf_counter() - start) * 1000

    if rc == 0:
        status = stdout.strip()
        evidence.append(ProbeEvidence(
            probe="tailscale_service",
            observer_node=observer,
            target_node=target,
            status="ok" if status == "active" else "degraded",
            latency_ms=latency,
            detail=f"status={status}",
            raw={"status": status},
        ))
    else:
        evidence.append(ProbeEvidence(
            probe="tailscale_service",
            observer_node=observer,
            target_node=target,
            status="failed",
            latency_ms=latency,
            detail=f"systemctl failed: {stderr}",
            raw={"returncode": rc, "stdout": stdout, "stderr": stderr},
        ))

    # Backend state and local IP via tailscale status --json
    start = time.perf_counter()
    rc, stdout, stderr = _run_cmd(["tailscale", "status", "--json"])
    latency = (time.perf_counter() - start) * 1000

    if rc == 0 and stdout:
        try:
            data = json.loads(stdout)
            backend_state = data.get("BackendState")
            self_ips = data.get("TailscaleIPs", [])
            peer = data.get("Peer", {})

            # Check peer reachability (any peer online) - SEPARATE from local health
            peer_reachable = any(p.get("Online") for p in peer.values())

            evidence.append(ProbeEvidence(
                probe="tailscale_backend",
                observer_node=observer,
                target_node=target,
                status="ok" if backend_state == "Running" else "degraded",
                latency_ms=latency,
                detail=f"backend={backend_state}, ips={self_ips}",
                raw={
                    "backend_state": backend_state,
                    "self_ips": self_ips,
                    "peer_count": len(peer),
                    "peers_online": sum(1 for p in peer.values() if p.get("Online")),
                },
            ))

            # Peer reachability is INFORMATIONAL, not a health signal
            evidence.append(ProbeEvidence(
                probe="tailscale_peer_reachable",
                observer_node=observer,
                target_node=target,
                status="ok" if peer_reachable else "degraded",
                latency_ms=latency,
                detail=f"peers_online={sum(1 for p in peer.values() if p.get('Online'))}/{len(peer)}",
                raw={"peer_reachable": peer_reachable, "peer_details": {
                    k: {"online": v.get("Online"), "hostname": v.get("HostName")}
                    for k, v in peer.items()
                }},
            ))
        except Exception as e:
            evidence.append(ProbeEvidence(
                probe="tailscale_backend",
                observer_node=observer,
                target_node=target,
                status="failed",
                latency_ms=latency,
                detail=f"parse error: {e}",
                raw={"stdout": stdout[:500]},
            ))
    else:
        evidence.append(ProbeEvidence(
            probe="tailscale_backend",
            observer_node=observer,
            target_node=target,
            status="failed",
            latency_ms=latency,
            detail=f"cmd failed: {stderr}",
            raw={"returncode": rc, "stderr": stderr},
        ))

    return evidence


def probe_ssh_service(observer: str, target: str) -> ProbeEvidence:
    """Check local SSH service (sshd) state."""
    start = time.perf_counter()
    rc, stdout, stderr = _run_cmd(["systemctl", "is-active", "sshd"])
    latency = (time.perf_counter() - start) * 1000

    if rc == 0:
        status = stdout.strip()
        return ProbeEvidence(
            probe="ssh_service",
            observer_node=observer,
            target_node=target,
            status="ok" if status == "active" else "degraded",
            latency_ms=latency,
            detail=f"status={status}",
            raw={"status": status},
        )
    else:
        # Try ssh service name
        rc2, stdout2, stderr2 = _run_cmd(["systemctl", "is-active", "ssh"])
        if rc2 == 0:
            status = stdout2.strip()
            return ProbeEvidence(
                probe="ssh_service",
                observer_node=observer,
                target_node=target,
                status="ok" if status == "active" else "degraded",
                latency_ms=latency,
                detail=f"status={status}",
                raw={"status": status},
            )

    return ProbeEvidence(
        probe="ssh_service",
        observer_node=observer,
        target_node=target,
        status="failed",
        latency_ms=latency,
        detail=f"sshd not found or not active: {stderr}",
        raw={"returncode": rc, "stdout": stdout, "stderr": stderr},
    )


def _discover_configured_vaelor_port(worktree_path: Optional[str] = None) -> Optional[int]:
    """Discover the configured Vaelor port from netbind.py network.json."""
    try:
        from core.netbind import load_network_config, default_config_path
        cfg = load_network_config(Path(worktree_path) if worktree_path else None)
        port = cfg.get("port")
        if port:
            return int(port)
    except Exception:
        pass
    return None


def _verify_vaelor_identity(url: str, port: int) -> tuple[bool, str, dict]:
    """Verify an endpoint is actually Vaelor by checking identity in response.

    Returns (is_vaelor, confidence, raw) where confidence is "VERIFIED", "INFERRED", or "UNKNOWN".
    VERIFIED requires strong identity signal (explicit product/name field == Vaelor, known config, known runtime).
    INFERRED is weak textual detection.
    """
    try:
        import urllib.request
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            status_code = resp.getcode()
        if status_code == 200:
            try:
                data = json.loads(body)
                # VERIFIED: Strong identity signals
                if data.get("name") == "Vaelor" or data.get("product") == "Vaelor":
                    return True, "VERIFIED", {"url": url, "status_code": status_code, "body": body[:500], "identity": data}
                # INFERRED: Weak textual detection
                if "vaelor" in str(data).lower() or "Vaelor" in body:
                    return True, "INFERRED", {"url": url, "status_code": status_code, "body": body[:500], "identity": data}
            except Exception:
                # JSON parse failed but HTTP 200 - weak textual detection
                if "vaelor" in body.lower() or "Vaelor" in body:
                    return True, "INFERRED", {"url": url, "status_code": status_code, "body": body[:500]}
    except Exception:
        pass
    return False, "UNKNOWN", {"url": url, "error": "request_failed"}


def probe_vaelor_endpoints(observer: str, target: str, worktree_path: Optional[str] = None) -> list[ProbeEvidence]:
    """Probe Vaelor endpoints with identity verification.

    Priority:
    1. Configured port from netbind.py
    2. VAELOR_PORTS range
    3. Returns per-port evidence with identity_confidence
    """
    evidence = []

    # Discover configured port first
    configured_port = _discover_configured_vaelor_port(worktree_path)
    candidate_ports = []
    if configured_port:
        candidate_ports.append(("configured", configured_port))
    for p in VAELOR_PORTS:
        if p != configured_port:
            candidate_ports.append(("vaelor_range", p))

    for source, port in candidate_ports:
        for path in ["/health", "/readiness", "/runtime/status"]:
            probe_name = f"vaelor_{path.strip('/').replace('/', '_')}_{port}"
            start = time.perf_counter()
            url = f"http://127.0.0.1:{port}{path}"
            try:
                import urllib.request
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    body = resp.read().decode("utf-8", errors="ignore")
                    status_code = resp.getcode()
                latency = (time.perf_counter() - start) * 1000

                # Verify Vaelor identity with confidence
                is_vaelor, confidence, raw = _verify_vaelor_identity(url, port)

                if is_vaelor:
                    status = "ok" if status_code == 200 else "degraded"
                    evidence.append(ProbeEvidence(
                        probe=probe_name,
                        observer_node=observer,
                        target_node=target,
                        status=status,
                        latency_ms=latency,
                        detail=f"HTTP {status_code} on {url} [{source}, {confidence}]",
                        raw={**raw, "source": source, "identity_confidence": confidence, "verified_vaelor": True},
                    ))
                else:
                    # Non-Vaelor endpoint - record as degraded with confidence
                    evidence.append(ProbeEvidence(
                        probe=probe_name,
                        observer_node=observer,
                        target_node=target,
                        status="degraded",
                        latency_ms=latency,
                        detail=f"HTTP {status_code} on {url} [{source}, {confidence}, not Vaelor]",
                        raw={**raw, "source": source, "identity_confidence": confidence, "verified_vaelor": False},
                    ))
            except Exception as e:
                latency = (time.perf_counter() - start) * 1000
                evidence.append(ProbeEvidence(
                    probe=probe_name,
                    observer_node=observer,
                    target_node=target,
                    status="failed",
                    latency_ms=latency,
                    detail=f"request failed: {e}",
                    raw={"url": url, "error": str(e), "source": source, "identity_confidence": "UNKNOWN"},
                ))

    return evidence


def probe_listener_ownership(observer: str, target: str, ports: Optional[list[int]] = None) -> ProbeEvidence:
    """Get listener ownership for configured ports.

    Filters by known/candidate ports, not by loopback address.
    Records identity_confidence: VERIFIED/INFERRED/UNKNOWN
    """
    ports = ports or ALL_PORTS
    start = time.perf_counter()

    # Query all listeners regardless of bind address
    rc, stdout, stderr = _run_cmd_shell("ss -ltnp")
    latency = (time.perf_counter() - start) * 1000

    ownership = {}
    if rc == 0 and stdout:
        try:
            for line in stdout.strip().split("\n"):
                if "LISTEN" in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        local_addr = parts[3]
                        pid_info = parts[5] if len(parts) > 5 else ""
                        # Parse port from local_addr (e.g., 0.0.0.0:8765 or :::8765 or 127.0.0.1:8765)
                        if ":" in local_addr:
                            port_str = local_addr.split(":")[-1]
                            try:
                                port = int(port_str)
                                if port in ports:
                                    # Extract PID from pid_info (format: pid=1234,comm=...)
                                    pid = None
                                    if "pid=" in pid_info:
                                        try:
                                            pid = int(pid_info.split("pid=")[1].split(",")[0])
                                        except (ValueError, IndexError):
                                            pass

                                    if pid:
                                        # Get process details
                                        rc2, stdout2, stderr2 = _run_cmd(["ps", "-p", str(pid), "-o", "pid,comm,args"])
                                        if rc2 == 0 and stdout2:
                                            lines = stdout2.strip().split("\n")
                                            if len(lines) > 1:
                                                proc_parts = lines[1].split(None, 2)
                                                if len(proc_parts) >= 3:
                                                    exe = proc_parts[1]
                                                    cmdline = proc_parts[2] if len(proc_parts) > 2 else ""

                                                    # Determine identity confidence
                                                    identity_confidence = "UNKNOWN"
                                                    product = "unknown"
                                                    if "vaelor" in exe.lower() or "vaelor" in cmdline.lower():
                                                        identity_confidence = "VERIFIED"
                                                        product = "Vaelor"
                                                    elif "odysseus" in exe.lower() or "odysseus" in cmdline.lower():
                                                        identity_confidence = "VERIFIED"
                                                        product = "Odysseus"
                                                    elif "VaelorServer" in exe or "VaelorServer" in cmdline:
                                                        identity_confidence = "INFERRED"
                                                        product = "Vaelor"

                                                    ownership[str(port)] = {
                                        "pid": pid,
                                        "local_address": local_addr,
                                        "exe": exe,
                                        "cmdline": cmdline,
                                        "product": product,
                                        "identity_confidence": identity_confidence,
                                    }
                                        continue
                            except ValueError:
                                pass
        except Exception:
            pass

    return ProbeEvidence(
        probe="listener_ownership",
        observer_node=observer,
        target_node=target,
        status="ok" if ownership else "degraded",
        latency_ms=latency,
        detail=f"ports_scanned={len(ports)}, listeners_found={len(ownership)}",
        raw={"ownership": ownership, "ports_scanned": ports},
    )


def probe_git_identity(observer: str, target: str, worktree_path: Optional[str] = None) -> ProbeEvidence:
    """Get Git branch, HEAD, and dirty status using porcelain format."""
    start = time.perf_counter()
    path = worktree_path or str(Path(__file__).resolve().parent.parent.parent)

    # Use porcelain format for reliable parsing
    cmd = f'cd "{path}"; git rev-parse --abbrev-ref HEAD; git rev-parse HEAD; git status --porcelain'
    rc, stdout, stderr = _run_cmd_shell(cmd, timeout=10.0)
    latency = (time.perf_counter() - start) * 1000

    if rc == 0 and stdout:
        lines = stdout.strip().split("\n")
        branch = lines[0].strip() if lines else "unknown"
        head = lines[1].strip() if len(lines) > 1 else "unknown"
        dirty_files = [l for l in lines[2:] if l.strip()] if len(lines) > 2 else []
        dirty = len(dirty_files) > 0

        return ProbeEvidence(
            probe="git_identity",
            observer_node=observer,
            target_node=target,
            status="ok",
            latency_ms=latency,
            detail=f"branch={branch}, head={head[:8]}, dirty={dirty}",
            raw={"branch": branch, "head": head, "dirty": dirty, "dirty_files": dirty_files, "path": path},
        )

    return ProbeEvidence(
        probe="git_identity",
        observer_node=observer,
        target_node=target,
        status="failed",
        latency_ms=latency,
        detail=f"cmd failed: {stderr}",
        raw={"returncode": rc, "stdout": stdout, "stderr": stderr, "path": path},
    )


def probe_model_backend(observer: str, target: str) -> ProbeEvidence:
    """Probe Ollama or other model backend availability."""
    start = time.perf_counter()
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3.0) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            status_code = resp.getcode()
        latency = (time.perf_counter() - start) * 1000

        if status_code == 200:
            try:
                data = json.loads(body)
                models = [m.get("name") for m in data.get("models", [])]
                return ProbeEvidence(
                    probe="model_backend",
                    observer_node=observer,
                    target_node=target,
                    status="ok",
                    latency_ms=latency,
                    detail=f"models={len(models)}",
                    raw={"models": models[:20]},
                )
            except Exception:
                return ProbeEvidence(
                    probe="model_backend",
                    observer_node=observer,
                    target_node=target,
                    status="ok",
                    latency_ms=latency,
                    detail="ollama responding but parse failed",
                    raw={"body": body[:500]},
                )
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        return ProbeEvidence(
            probe="model_backend",
            observer_node=observer,
            target_node=target,
            status="failed",
            latency_ms=latency,
            detail=f"ollama not reachable: {e}",
            raw={"error": str(e)},
        )


def run_all_local_probes(observer: str = "legiongo", target: str = "legiongo",
                          worktree_path: Optional[str] = None) -> list[ProbeEvidence]:
    """Run all local probes for the current Linux node."""
    all_evidence = []

    all_evidence.append(probe_host_uptime(observer, target))
    all_evidence.extend(probe_tailscale(observer, target))
    all_evidence.append(probe_ssh_service(observer, target))
    all_evidence.extend(probe_vaelor_endpoints(observer, target, worktree_path))
    all_evidence.append(probe_listener_ownership(observer, target))
    all_evidence.append(probe_git_identity(observer, target, worktree_path))
    all_evidence.append(probe_model_backend(observer, target))

    return all_evidence
