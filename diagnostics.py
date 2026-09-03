import os
import shutil
import subprocess
from pathlib import Path

import requests

from core.netbind import load_network_config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

WORKSPACE = BASE_DIR
MEMORY_FILE = os.path.join(BASE_DIR, "memory", "archive.json")


def check(title, success, detail=""):
    symbol = "✓" if success else "✗"
    print(f"{symbol} {title}")

    if detail:
        print(f"    {detail}")


print("=" * 42)
print("        VAELOR SYSTEM REPORT")
print("=" * 42)
print()

#
# Python
#

check(
    "Python",
    True,
    subprocess.check_output(["python", "--version"], text=True).strip()
)

#
# Virtual Environment
#

venv = os.environ.get("VIRTUAL_ENV")

check(
    "Virtual Environment",
    venv is not None,
    venv if venv else "Not Active"
)

#
# Ollama
#

try:

    response = requests.get(
        "http://localhost:11434/api/tags",
        timeout=3
    )

    check(
        "Ollama Server",
        response.status_code == 200
    )

except Exception:

    check(
        "Ollama Server",
        False
    )

#
# Vaelor Model
#

try:

    output = subprocess.check_output(
        ["ollama", "list"],
        text=True
    )

    exists = "vaelor-prime" in output.lower()

    check(
        "Vaelor Model",
        exists
    )

except Exception:

    check(
        "Vaelor Model",
        False
    )

#
# Git
#

check(
    "Git",
    shutil.which("git") is not None
)

#
# Aider
#

check(
    "Aider",
    shutil.which("aider") is not None
)

#
# Workspace
#

check(
    "Workspace",
    os.path.exists(WORKSPACE),
    WORKSPACE
)

#
# Memory
#

check(
    "Memory Archive",
    os.path.exists(MEMORY_FILE),
    MEMORY_FILE
)

#
# FastAPI
#

_net = load_network_config(Path(BASE_DIR))
_api_host = _net.get("host") or "localhost"
_api_port = _net.get("port") or 8765
_health_url = f"http://{_api_host}:{_api_port}/health"

try:

    response = requests.get(
        _health_url,
        timeout=2
    )

    check(
        "FastAPI",
        response.status_code == 200,
        _health_url,
    )

except Exception:

    check(
        "FastAPI",
        False,
        f"Not Running ({_health_url})",
    )

print()
print("=" * 42)
print("Diagnostics Complete")
print("=" * 42)
