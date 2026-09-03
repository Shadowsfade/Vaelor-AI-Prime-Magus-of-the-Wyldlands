"""Canonical Vaelor release version loaded from config/vaelor.json."""
from __future__ import annotations

import json
from pathlib import Path


VERSION_FILE = Path(__file__).resolve().parent.parent / "config" / "vaelor.json"
FALLBACK_VERSION = "0.0.0-unknown"


def get_version() -> str:
    try:
        value = json.loads(VERSION_FILE.read_text(encoding="utf-8-sig"))
        version = str(value.get("version", "")).strip()
        return version or FALLBACK_VERSION
    except Exception:
        return FALLBACK_VERSION


VAELOR_VERSION = get_version()
