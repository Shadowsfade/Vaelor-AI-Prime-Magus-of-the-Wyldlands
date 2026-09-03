"""Bounded, read-only multi-file context gathering for agent tasks."""
from __future__ import annotations

from pathlib import Path
from typing import List

from .fs_ops import _resolve_path


MAX_FILES = 20
MAX_TOTAL_CHARS = 50000
MAX_FILE_CHARS = 12000


def read_many_text_files(paths: List[str], max_total_chars: int = MAX_TOTAL_CHARS) -> str:
    """Read several allowed-root text files under a shared, deterministic budget."""
    if not isinstance(paths, list) or not paths:
        return "Refused: paths must be a non-empty JSON array."
    if len(paths) > MAX_FILES:
        return f"Refused: at most {MAX_FILES} files may be read at once."
    try:
        budget = max(1000, min(int(max_total_chars), MAX_TOTAL_CHARS))
    except (TypeError, ValueError):
        return "Refused: max_total_chars must be an integer."

    sections = []
    used = 0
    for raw_path in paths:
        if not isinstance(raw_path, str) or not raw_path.strip():
            sections.append("----- INVALID PATH -----\nRefused: every path must be a non-empty string.")
            continue
        try:
            full = Path(_resolve_path(raw_path, must_exist=True))
            if not full.is_file():
                raise ValueError("not a file")
            remaining = budget - used
            if remaining <= 0:
                break
            per_file = min(MAX_FILE_CHARS, remaining)
            with full.open(encoding="utf-8-sig", errors="replace") as handle:
                content = handle.read(per_file + 1)
            truncated = len(content) > per_file
            content = content[:per_file]
            header = f"----- {full} -----"
            body = content + ("\n...[file truncated]" if truncated else "")
            sections.append(header + "\n" + body)
            used += len(content)
        except Exception as exc:
            sections.append(f"----- {raw_path} -----\nRead failed: {exc}")

    if len(paths) > len(sections):
        sections.append(
            f"...[total budget reached; {len(paths) - len(sections)} file(s) not read]"
        )
    return "\n\n".join(sections) if sections else "No files were read."
