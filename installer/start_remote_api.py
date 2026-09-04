"""Start Vaelor on an explicitly selected trusted-network interface."""
from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def validate_host(value: str) -> str:
    host = str(value or "").strip()
    if not host or len(host) > 253:
        raise ValueError("a bind host or IP is required")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", host):
            raise ValueError("invalid bind host")
        return host


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Tailscale/VPN IP or explicit interface")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        host = validate_host(args.host)
    except ValueError as exc:
        parser.error(str(exc))
    if not 1024 <= args.port <= 65535:
        parser.error("port must be 1024-65535")
    token_path = ROOT / "config" / "api_access.json"
    if not token_path.is_file():
        print("Remote authentication is not configured. Run installer/Configure-Remote-API.py first.")
        return 2
    print(f"Starting authenticated Vaelor at http://{host}:{args.port}/")
    print("Use only on Tailscale/a trusted VPN, or place Vaelor behind HTTPS.")
    return subprocess.call([
        sys.executable, "-m", "uvicorn", "api.server:app",
        "--host", host, "--port", str(args.port),
    ], cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
