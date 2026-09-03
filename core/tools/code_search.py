"""Bounded, dependency-free codebase search for agent context gathering."""
from __future__ import annotations

from pathlib import Path
import re

from .fs_ops import _resolve_path


EXCLUDED_DIRS = {".git", ".venv", "node_modules", "dist", "build", "__pycache__"}
TEXT_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".html",
    ".java", ".js", ".json", ".jsx", ".lua", ".md", ".php", ".ps1",
    ".py", ".rb", ".rs", ".sh", ".sql", ".toml", ".ts", ".tsx",
    ".txt", ".xml", ".yaml", ".yml",
}
MAX_FILES = 2000
MAX_FILE_BYTES = 500_000
MAX_TOTAL_BYTES = 20_000_000


def _tokens(query: str):
    return tuple(dict.fromkeys(re.findall(r"[A-Za-z_][A-Za-z0-9_.-]*", query.lower())))


def search_codebase(query: str, path: str = ".", limit: int = 12) -> str:
    """Rank matching text files and return small line-numbered context snippets."""
    terms = _tokens(str(query or ""))
    if not terms:
        raise ValueError("query must contain at least one searchable word")
    root = Path(_resolve_path(path, must_exist=True))
    if not root.is_dir():
        raise ValueError(f"path is not a directory: {root}")
    limit = max(1, min(int(limit or 12), 30))
    matches = []
    scanned = 0
    scanned_bytes = 0
    resolved_root = root.resolve()
    for candidate in sorted(root.rglob("*"), key=lambda item: str(item).casefold()):
        if scanned >= MAX_FILES or scanned_bytes >= MAX_TOTAL_BYTES:
            break
        if not candidate.is_file() or any(part in EXCLUDED_DIRS for part in candidate.parts):
            continue
        if candidate.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        scanned += 1
        try:
            resolved_candidate = candidate.resolve()
            resolved_candidate.relative_to(resolved_root)
            size = resolved_candidate.stat().st_size
            if size > MAX_FILE_BYTES or scanned_bytes + size > MAX_TOTAL_BYTES:
                continue
            scanned_bytes += size
            text = resolved_candidate.read_text(encoding="utf-8-sig", errors="replace")
            relative = candidate.relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        lower = text.lower()
        path_lower = relative.lower()
        score = sum(lower.count(term) for term in terms)
        score += 8 * sum(1 for term in terms if term in path_lower)
        if not score:
            continue
        lines = text.splitlines()
        hit_lines = [
            index for index, line in enumerate(lines)
            if any(term in line.lower() for term in terms)
        ][:3]
        snippets = []
        for index in hit_lines:
            start, end = max(0, index - 1), min(len(lines), index + 2)
            snippets.append("\n".join(f"{number + 1}: {lines[number]}" for number in range(start, end)))
        matches.append((score, relative, "\n...\n".join(snippets)))
    matches.sort(key=lambda item: (-item[0], item[1].casefold()))
    header = (
        f"Code search: {query!r} | root={root} | "
        f"scanned={scanned} files/{scanned_bytes} bytes"
    )
    if not matches:
        return header + "\nNo matching source text found."
    sections = [header]
    for score, relative, snippet in matches[:limit]:
        sections.append(f"\n--- {relative} (score {score}) ---\n{snippet}")
    return "\n".join(sections)
