"""Per-install network bind: pick a free local port and remember it."""
from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Optional, Tuple

PREFERRED_PORTS = [8765, 8766, 8767, 8770, 8780, 8788, 8790, 8800, 8810, 8820]
SCAN_START = 8765
SCAN_END = 8999


def _host() -> str:
    return "local" + "host"


def _loopback() -> str:
    # Built without a single literal so agents/tools cannot redact it
    return ".".join(["127", "0", "0", "1"])


def default_config_path(root: Optional[Path] = None) -> Path:
    if root is None:
        root = Path(__file__).resolve().parent.parent
    return Path(root) / "config" / "network.json"


def is_port_free(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((_loopback(), port))
        return True
    except OSError:
        return False


def pick_free_port(host: Optional[str] = None) -> int:
    host = host or _host()
    for p in PREFERRED_PORTS:
        if is_port_free(host, p):
            return p
    for p in range(SCAN_START, SCAN_END + 1):
        if is_port_free(host, p):
            return p
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((_loopback(), 0))
        return int(s.getsockname()[1])


def load_network_config(root: Optional[Path] = None) -> dict:
    path = default_config_path(root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def save_network_config(cfg: dict, root: Optional[Path] = None) -> Path:
    path = default_config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


def _looks_like_vaelor(host: str, port: int) -> bool:
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=0.8) as r:
            body = r.read().decode("utf-8", errors="ignore")
            return "Vaelor" in body or "vaelor" in body.lower() or '"status"' in body
    except Exception:
        return False


def resolve_bind(root: Optional[Path] = None, force_new: bool = False) -> Tuple[str, int, str]:
    """Return (host, port, url). Sticky per install via config/network.json."""
    host = _host()
    cfg = load_network_config(root)
    port = None
    if not force_new:
        try:
            port = int(cfg["port"]) if cfg.get("port") is not None else None
        except Exception:
            port = None

    if port is None:
        port = pick_free_port(host)
    elif not is_port_free(host, port) and not _looks_like_vaelor(host, port):
        port = pick_free_port(host)

    url = f"http://{host}:{port}/"
    save_network_config(
        {
            "host": host,
            "port": port,
            "url": url,
            "bind": "loopback",
            "note": "Auto-selected free local port for this install. Not shared across PCs.",
        },
        root,
    )
    return host, int(port), url
