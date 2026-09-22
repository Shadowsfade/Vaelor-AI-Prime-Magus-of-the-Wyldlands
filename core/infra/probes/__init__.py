"""Windows and Linux infrastructure probes package."""

from __future__ import annotations

import platform
from typing import Any, Optional

# Export common types and functions
from core.infra.probes.windows import (
    run_all_local_probes as run_all_local_probes_windows,
    probe_host_uptime as probe_host_uptime_windows,
    probe_tailscale as probe_tailscale_windows,
    probe_ssh_service as probe_ssh_service_windows,
    probe_vaelor_endpoints as probe_vaelor_endpoints_windows,
    probe_listener_ownership as probe_listener_ownership_windows,
    probe_git_identity as probe_git_identity_windows,
    probe_model_backend as probe_model_backend_windows,
)

try:
    from core.infra.probes.linux import (
        run_all_local_probes as run_all_local_probes_linux,
        probe_host_uptime as probe_host_uptime_linux,
        probe_tailscale as probe_tailscale_linux,
        probe_ssh_service as probe_ssh_service_linux,
        probe_vaelor_endpoints as probe_vaelor_endpoints_linux,
        probe_listener_ownership as probe_listener_ownership_linux,
        probe_git_identity as probe_git_identity_linux,
        probe_model_backend as probe_model_backend_linux,
    )
    _LINUX_AVAILABLE = True
except ImportError:
    _LINUX_AVAILABLE = False
    run_all_local_probes_linux = None
    probe_host_uptime_linux = None
    probe_tailscale_linux = None
    probe_ssh_service_linux = None
    probe_vaelor_endpoints_linux = None
    probe_listener_ownership_linux = None
    probe_git_identity_linux = None
    probe_model_backend_linux = None


def _get_platform_probes():
    """Get the appropriate platform-specific probe functions."""
    system = platform.system().lower()
    if system == "windows":
        return {
            "run_all_local_probes": run_all_local_probes_windows,
            "probe_host_uptime": probe_host_uptime_windows,
            "probe_tailscale": probe_tailscale_windows,
            "probe_ssh_service": probe_ssh_service_windows,
            "probe_vaelor_endpoints": probe_vaelor_endpoints_windows,
            "probe_listener_ownership": probe_listener_ownership_windows,
            "probe_git_identity": probe_git_identity_windows,
            "probe_model_backend": probe_model_backend_windows,
        }
    elif system == "linux":
        if _LINUX_AVAILABLE:
            return {
                "run_all_local_probes": run_all_local_probes_linux,
                "probe_host_uptime": probe_host_uptime_linux,
                "probe_tailscale": probe_tailscale_linux,
                "probe_ssh_service": probe_ssh_service_linux,
                "probe_vaelor_endpoints": probe_vaelor_endpoints_linux,
                "probe_listener_ownership": probe_listener_ownership_linux,
                "probe_git_identity": probe_git_identity_linux,
                "probe_model_backend": probe_model_backend_linux,
            }
        else:
            raise RuntimeError("Linux probes not available")
    else:
        raise RuntimeError(f"Unsupported platform: {platform.system()}")


# Export platform-appropriate functions
_platform_probes = _get_platform_probes()
run_all_local_probes = _platform_probes["run_all_local_probes"]
probe_host_uptime = _platform_probes["probe_host_uptime"]
probe_tailscale = _platform_probes["probe_tailscale"]
probe_ssh_service = _platform_probes["probe_ssh_service"]
probe_vaelor_endpoints = _platform_probes["probe_vaelor_endpoints"]
probe_listener_ownership = _platform_probes["probe_listener_ownership"]
probe_git_identity = _platform_probes["probe_git_identity"]
probe_model_backend = _platform_probes["probe_model_backend"]

__all__ = [
    "run_all_local_probes",
    "probe_host_uptime",
    "probe_tailscale",
    "probe_ssh_service",
    "probe_vaelor_endpoints",
    "probe_listener_ownership",
    "probe_git_identity",
    "probe_model_backend",
]
