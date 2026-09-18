"""Relay guardian contract for vaelor-relay.

Defines expected guardian capabilities and validation schema.
Validation state is PENDING_PHYSICAL_RECOVERY until relay is restored.

The relay contract is DECLARATIVE - it defines what the guardian SHOULD do,
not executable commands against guessed ports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ValidationState(Enum):
    VALIDATED = "VALIDATED"
    PENDING_PHYSICAL_RECOVERY = "PENDING_PHYSICAL_RECOVERY"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass
class RelayCapability:
    """Single guardian capability requirement."""
    name: str
    required: bool
    check_command: Optional[str] = None
    description: str = ""
    validation_state: ValidationState = ValidationState.UNKNOWN
    last_validated: Optional[str] = None  # ISO timestamp


@dataclass
class NodeConfig:
    """Configuration for a node the guardian monitors."""
    node: str
    tailscale_ip: Optional[str] = None
    lan_ip: Optional[str] = None
    vaelor_endpoint: Optional[str] = None  # e.g., "http://skyai:8765" - resolved from netbind
    expected_product_identity: str = "Vaelor"
    health_check_interval_seconds: int = 60
    health_check_timeout_seconds: int = 180


RELAY_RESPONSIBILITIES = {
    "tailscaled": RelayCapability(
        name="tailscaled",
        required=True,
        check_command="systemctl is-active tailscaled",
        description="Tailscale daemon running and connected",
    ),
    "ssh": RelayCapability(
        name="ssh",
        required=True,
        check_command="systemctl is-active ssh",
        description="SSH server accepting connections",
    ),
    "vaelor_guardian": RelayCapability(
        name="vaelor_guardian",
        required=True,
        check_command="systemctl is-active vaelor-guardian",
        description="Vaelor guardian daemon (health monitor + recovery)",
        validation_state=ValidationState.PENDING_PHYSICAL_RECOVERY,
    ),
    "skyai_heartbeat": RelayCapability(
        name="skyai_heartbeat",
        required=True,
        check_command=None,  # Resolved at runtime from NodeConfig.vaelor_endpoint
        description="Periodic skyai health check via configured Vaelor endpoint (60s interval, 180s timeout)",
        validation_state=ValidationState.PENDING_PHYSICAL_RECOVERY,
    ),
    "continuity_mirror": RelayCapability(
        name="continuity_mirror",
        required=False,
        check_command=None,
        description="Git HEAD + runtime state snapshot mirror",
        validation_state=ValidationState.PENDING_PHYSICAL_RECOVERY,
    ),
    "lan_recovery": RelayCapability(
        name="lan_recovery",
        required=False,
        check_command=None,
        description="Wake-on-LAN proxy for skyai",
        validation_state=ValidationState.PENDING_PHYSICAL_RECOVERY,
    ),
    "subnet_router": RelayCapability(
        name="subnet_router",
        required=False,
        check_command="tailscale status --json | jq '.Self.SubnetRouter'",
        description="Advertise LAN routes via Tailscale",
        validation_state=ValidationState.PENDING_PHYSICAL_RECOVERY,
    ),
}


DEFAULT_NODE_CONFIGS = {
    "skyai": NodeConfig(
        node="skyai",
        tailscale_ip="100.119.249.96",
        lan_ip=None,  # Not independently verified; populated by guardian discovery later
        vaelor_endpoint=None,  # Resolved from skyai's netbind config at runtime
        expected_product_identity="Vaelor",
    ),
    "legiongo": NodeConfig(
        node="legiongo",
        tailscale_ip="100.92.120.48",
        lan_ip=None,
        vaelor_endpoint=None,
        expected_product_identity="Vaelor",
    ),
}


@dataclass
class RelayContract:
    """Complete relay guardian contract."""
    node: str = "vaelor-relay"
    capabilities: dict = field(default_factory=lambda: RELAY_RESPONSIBILITIES)
    node_configs: dict = field(default_factory=lambda: DEFAULT_NODE_CONFIGS)
    validation_state: ValidationState = ValidationState.PENDING_PHYSICAL_RECOVERY
    notes: str = "Relay offline since 2026-08-31. Physical recovery required before validation."

    def required_capabilities(self) -> list[RelayCapability]:
        return [c for c in self.capabilities.values() if c.required]

    def optional_capabilities(self) -> list[RelayCapability]:
        return [c for c in self.capabilities.values() if not c.required]

    def get_node_config(self, node: str) -> Optional[NodeConfig]:
        return self.node_configs.get(node)

    def all_validated(self) -> bool:
        return all(c.validation_state == ValidationState.VALIDATED for c in self.required_capabilities())

    def to_dict(self) -> dict:
        return {
            "node": self.node,
            "validation_state": self.validation_state.value,
            "notes": self.notes,
            "capabilities": {
                name: {
                    "required": cap.required,
                    "description": cap.description,
                    "validation_state": cap.validation_state.value,
                    "last_validated": cap.last_validated,
                }
                for name, cap in self.capabilities.items()
            },
            "node_configs": {
                name: {
                    "tailscale_ip": cfg.tailscale_ip,
                    "lan_ip": cfg.lan_ip,
                    "vaelor_endpoint": cfg.vaelor_endpoint,
                    "expected_product_identity": cfg.expected_product_identity,
                    "health_check_interval_seconds": cfg.health_check_interval_seconds,
                    "health_check_timeout_seconds": cfg.health_check_timeout_seconds,
                }
                for name, cfg in self.node_configs.items()
            },
        }


def get_relay_contract() -> RelayContract:
    """Get the current relay contract."""
    return RelayContract()

