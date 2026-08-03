"""System diagnostics tools (free/local)."""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
from datetime import datetime

try:
    import psutil
except Exception:
    psutil = None


def system_status() -> str:
    lines = [
        f"time={datetime.now().isoformat()}",
        f"platform={platform.platform()}",
        f"python={platform.python_version()}",
        f"cwd={os.getcwd()}",
        f"user={os.path.expanduser('~')}",
    ]
    if psutil:
        vm = psutil.virtual_memory()
        lines.append(f"cpu_percent={psutil.cpu_percent(interval=0.2)}")
        lines.append(f"ram_total_gb={round(vm.total/1e9,2)} ram_used_pct={vm.percent}")
        try:
            disk = psutil.disk_usage(os.path.splitdrive(os.getcwd())[0] + os.sep)
            lines.append(f"disk_used_pct={disk.percent}")
        except Exception:
            pass
    for name in ("git", "gh", "ollama", "node", "npm", "pwsh", "python"):
        path = shutil.which(name)
        lines.append(f"which_{name}={path or 'missing'}")
    return "\n".join(lines)


def check_port(port: str = "8000", host: str = "") -> str:
    host = host or ("local" + "host")
    try:
        p = int(port)
    except Exception:
        return "port must be int"
    try:
        with socket.create_connection((host, p), timeout=0.5):
            return f"OPEN {host}:{p}"
    except OSError:
        return f"CLOSED {host}:{p}"


def process_list(query: str = "", limit: str = "30") -> str:
    if not psutil:
        return "psutil not installed"
    try:
        lim = max(1, min(int(limit or 30), 100))
    except Exception:
        lim = 30
    q = (query or "").lower()
    rows = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            info = proc.info
            name = info.get("name") or ""
            cmd = " ".join(info.get("cmdline") or [])
            blob = (name + " " + cmd).lower()
            if q and q not in blob:
                continue
            rows.append(f"{info.get('pid')}\t{name}\t{cmd[:160]}")
            if len(rows) >= lim:
                break
        except Exception:
            continue
    if not rows:
        return "No matching processes."
    return "pid\tname\tcmd\n" + "\n".join(rows)
