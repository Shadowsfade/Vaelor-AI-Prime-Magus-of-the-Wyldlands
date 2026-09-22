"""Explicit, portable node identity configuration for R0 observation.

Observer and target identity must never be inferred from which machine the
probe happened to run on. This module makes that identity explicit and
loadable from a trusted local config file that is portable between
Legion Go (Linux) and the Windows host.

Nothing here executes commands, and nothing here reads model output.
"""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class NodeConfigError(ValueError):
    """Raised when node identity configuration is unusable."""


@dataclass(frozen=True)
class NodeIdentity:
    """Identity of a single node as configured by the operator."""

    name: str
    hostname: str = ""
    tailscale_ip: Optional[str] = None
    role: str = "generic"
    is_local: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "hostname": self.hostname or self.name,
            "tailscale_ip": self.tailscale_ip,
            "role": self.role,
            "is_local": self.is_local,
        }


@dataclass(frozen=True)
class NodeRegistry:
    """Resolved observer/target identity for an observation run."""

    observer: NodeIdentity
    nodes: dict = field(default_factory=dict)
    default_target: str = ""
    source: str = "builtin"

    def target(self, name: Optional[str] = None) -> NodeIdentity:
        wanted = name or self.default_target
        if not wanted:
            raise NodeConfigError("no target node configured and none requested")
        if wanted not in self.nodes:
            raise NodeConfigError(f"unknown target node: {wanted!r}")
        return self.nodes[wanted]

    def is_observer(self, name: str) -> bool:
        return name == self.observer.name

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "observer": self.observer.to_dict(),
            "default_target": self.default_target,
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
        }


def default_config_path(root: Optional[Path] = None) -> Path:
    base = Path(root) if root else Path(__file__).resolve().parent.parent.parent
    return Path(base) / "config" / "nodes.json"


def _builtin(host: Optional[str] = None) -> NodeRegistry:
    """Built-in registry derived only from the local hostname.

    Used when no config file exists. Never reaches out to the network.
    """
    hostname = (host or platform.node() or "localhost").split(".")[0]
    observer = NodeIdentity(
        name=hostname,
        hostname=hostname,
        tailscale_ip=None,
        role="local",
        is_local=True,
    )
    return NodeRegistry(
        observer=observer,
        nodes={hostname: observer},
        default_target=hostname,
        source="builtin",
    )


def load_node_registry(root: Optional[Path] = None,
                       explicit_path: Optional[Path] = None,
                       host: Optional[str] = None) -> NodeRegistry:
    """Load node identity from a trusted local config file.

    Falls back to a hostname-derived builtin registry when the file is
    absent. A present-but-invalid file raises NodeConfigError rather than
    silently degrading, because ambiguous node identity must fail closed.
    """
    path = Path(explicit_path) if explicit_path else default_config_path(root)
    if not path.exists():
        return _builtin(host)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NodeConfigError(f"node config unreadable: {exc}") from exc

    if not isinstance(raw, dict):
        raise NodeConfigError("node config must be a JSON object")

    observer_name = raw.get("observer")
    if not observer_name or not isinstance(observer_name, str):
        raise NodeConfigError("node config must declare a string 'observer'")

    entries = raw.get("nodes")
    if not isinstance(entries, dict) or not entries:
        raise NodeConfigError("node config must declare a non-empty 'nodes' object")

    nodes: dict = {}
    for name, spec in entries.items():
        if not isinstance(spec, dict):
            raise NodeConfigError(f"node {name!r} must be an object")
        nodes[name] = NodeIdentity(
            name=name,
            hostname=str(spec.get("hostname") or name),
            tailscale_ip=spec.get("tailscale_ip"),
            role=str(spec.get("role") or "generic"),
            is_local=(name == observer_name),
        )

    if observer_name not in nodes:
        raise NodeConfigError(
            f"observer {observer_name!r} is not present in 'nodes'"
        )

    default_target = raw.get("default_target") or observer_name
    if default_target not in nodes:
        raise NodeConfigError(
            f"default_target {default_target!r} is not present in 'nodes'"
        )

    return NodeRegistry(
        observer=nodes[observer_name],
        nodes=nodes,
        default_target=default_target,
        source=str(path),
    )
