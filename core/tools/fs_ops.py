"""Filesystem tools for Vaelor — OS-safe, autonomy-aware."""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "autonomy.json")
MAX_READ = 250_000
MAX_GREP_HITS = 80
MAX_LIST = 400


def _load_autonomy() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {
            "default_cwd": PROJECT_ROOT,
            "allowed_roots": [PROJECT_ROOT, os.path.expanduser("~")],
            "protected_delete_roots": [r"C:\Windows", r"C:\Program Files", r"C:\ProgramData"],
            "allowed_user_profile": os.path.expanduser("~"),
            "mode": "admin",
        }


def _norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expandvars(os.path.expanduser(p))))


def _is_under(path: str, root: str) -> bool:
    path, root = _norm(path), _norm(root)
    return path == root or path.startswith(root.rstrip("\\/") + os.sep)


def _allowed_roots(cfg: dict) -> List[str]:
    roots = [_norm(r) for r in (cfg.get("allowed_roots") or []) if r]
    roots.append(_norm(PROJECT_ROOT))
    home = cfg.get("allowed_user_profile") or os.path.expanduser("~")
    roots.append(_norm(home))
    # unique preserve order
    out, seen = [], set()
    for r in roots:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _protected_roots(cfg: dict) -> List[str]:
    roots = [_norm(r) for r in (cfg.get("protected_delete_roots") or cfg.get("protected_roots") or [])]
    defaults = [
        r"C:\Windows", r"C:\Windows\System32", r"C:\Windows\SysWOW64", r"C:\Windows\WinSxS",
        r"C:\Program Files", r"C:\Program Files (x86)", r"C:\ProgramData",
        r"C:\Recovery", r"C:\Boot", r"C:\EFI",
    ]
    for d in defaults:
        nd = _norm(d)
        if nd not in roots:
            roots.append(nd)
    return roots


def _resolve_path(path: str, must_exist: bool = False) -> str:
    cfg = _load_autonomy()
    if not path:
        raise ValueError("path is required")
    path = os.path.expandvars(os.path.expanduser(path))
    if not os.path.isabs(path):
        base = cfg.get("default_cwd") or PROJECT_ROOT
        path = os.path.join(base, path)
    full = _norm(path)
    if must_exist and not os.path.exists(full):
        raise FileNotFoundError(full)
    # allow if under any allowed root
    allowed = _allowed_roots(cfg)
    if not any(_is_under(full, r) for r in allowed):
        # still allow pure reads of nothing outside; refuse writes later
        raise PermissionError(f"path outside allowed roots: {full}")
    return full


def _assert_not_protected_write(full: str) -> None:
    cfg = _load_autonomy()
    for root in _protected_roots(cfg):
        if _is_under(full, root):
            raise PermissionError(f"write/delete blocked on protected OS path: {full}")
    # other user profiles
    users = _norm(r"C:\Users")
    allowed_user = cfg.get("allowed_user_profile")
    if allowed_user and _is_under(full, users) and not _is_under(full, allowed_user) and full != users:
        raise PermissionError(f"other user profile blocked: {full}")


def list_dir(path: str = ".", recursive: str = "no", max_entries: str = "200") -> str:
    """List directory contents. path= . recursive=yes|no"""
    try:
        full = _resolve_path(path or ".")
    except Exception as e:
        return f"Refused: {e}"
    if not os.path.isdir(full):
        return f"Not a directory: {full}"
    try:
        limit = max(1, min(int(max_entries or 200), MAX_LIST))
    except Exception:
        limit = 200
    rec = str(recursive).lower() in ("yes", "true", "1", "y")
    lines = [f"Listing {full} (recursive={rec}, limit={limit})"]
    n = 0
    if rec:
        for root, dirs, files in os.walk(full):
            dirs.sort()
            files.sort()
            rel_root = os.path.relpath(root, full)
            for d in dirs:
                lines.append(f"[dir]  {os.path.join(rel_root, d) if rel_root != '.' else d}")
                n += 1
                if n >= limit:
                    lines.append("...truncated...")
                    return "\n".join(lines)
            for f in files:
                lines.append(f"[file] {os.path.join(rel_root, f) if rel_root != '.' else f}")
                n += 1
                if n >= limit:
                    lines.append("...truncated...")
                    return "\n".join(lines)
    else:
        try:
            entries = sorted(os.listdir(full), key=str.lower)
        except Exception as e:
            return f"List failed: {e}"
        for name in entries:
            p = os.path.join(full, name)
            kind = "dir " if os.path.isdir(p) else "file"
            lines.append(f"[{kind}] {name}")
            n += 1
            if n >= limit:
                lines.append("...truncated...")
                break
    lines.append(f"Total shown: {n}")
    return "\n".join(lines)


def glob_files(pattern: str = "**/*", path: str = ".", max_entries: str = "200") -> str:
    """Glob files under path. pattern=**/*.py path=."""
    try:
        base = _resolve_path(path or ".")
    except Exception as e:
        return f"Refused: {e}"
    if not pattern:
        pattern = "**/*"
    try:
        limit = max(1, min(int(max_entries or 200), MAX_LIST))
    except Exception:
        limit = 200
    root = Path(base)
    try:
        matches = list(root.glob(pattern))
    except Exception as e:
        return f"Glob failed: {e}"
    # files first
    files = [m for m in matches if m.is_file()]
    dirs = [m for m in matches if m.is_dir()]
    out = [f"Glob {pattern} under {base} ({len(files)} files, {len(dirs)} dirs)"]
    for i, m in enumerate(files[:limit]):
        out.append(str(m))
    if len(files) > limit:
        out.append(f"...truncated {len(files) - limit} files")
    return "\n".join(out)


def read_text_file(path: str = "", start_line: str = "", end_line: str = "") -> str:
    """Read a text file (allowed roots). Optional start_line/end_line (1-based)."""
    try:
        full = _resolve_path(path, must_exist=True)
    except Exception as e:
        return f"Refused: {e}"
    if not os.path.isfile(full):
        return f"Not a file: {full}"
    size = os.path.getsize(full)
    if size > MAX_READ:
        return f"Refused: file too large ({size} bytes, limit {MAX_READ})."
    try:
        with open(full, "r", encoding="utf-8-sig", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return f"Read failed: {e}"
    s = int(start_line) if str(start_line).isdigit() else 1
    e = int(end_line) if str(end_line).isdigit() else len(lines)
    s = max(1, s)
    e = min(len(lines), e)
    chunk = lines[s - 1 : e]
    body = "".join(f"{i}|{line}" for i, line in enumerate(chunk, start=s))
    return f"----- {full} lines {s}-{e} of {len(lines)} -----\n{body}"


def write_text_file(path: str = "", content: str = "", mode: str = "overwrite", confirm: str = "yes") -> str:
    """Write text file under allowed roots. mode=overwrite|append. Blocks OS-protected paths."""
    if str(confirm).lower() not in ("yes", "true", "1", "y"):
        return "Refused: write_text_file needs confirm=yes"
    if content is None:
        content = ""
    # support \\n escapes from tool kwargs
    content = content.replace("\\n", "\n").replace("\\t", "\t")
    try:
        full = _resolve_path(path)
        _assert_not_protected_write(full)
    except Exception as e:
        return f"Refused: {e}"
    parent = os.path.dirname(full)
    os.makedirs(parent, exist_ok=True)
    m = (mode or "overwrite").lower()
    try:
        if m == "append":
            with open(full, "a", encoding="utf-8") as f:
                f.write(content)
        else:
            with open(full, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
    except Exception as e:
        return f"Write failed: {e}"
    return f"Wrote {len(content)} chars to {full} (mode={m})"


def apply_patch(path: str = "", old: str = "", new: str = "", confirm: str = "yes") -> str:
    """Replace exact old text with new text in a file (one occurrence)."""
    if str(confirm).lower() not in ("yes", "true", "1", "y"):
        return "Refused: apply_patch needs confirm=yes"
    if not old:
        return "Refused: old= text required"
    old = old.replace("\\n", "\n").replace("\\t", "\t")
    new = (new or "").replace("\\n", "\n").replace("\\t", "\t")
    try:
        full = _resolve_path(path, must_exist=True)
        _assert_not_protected_write(full)
    except Exception as e:
        return f"Refused: {e}"
    try:
        text = Path(full).read_text(encoding="utf-8-sig")
    except Exception as e:
        return f"Read failed: {e}"
    if old not in text:
        return "Refused: old text not found (must match exactly)."
    count = text.count(old)
    text2 = text.replace(old, new, 1)
    try:
        Path(full).write_text(text2, encoding="utf-8", newline="\n")
    except Exception as e:
        return f"Write failed: {e}"
    return f"Patched {full} (replaced 1 of {count} occurrence(s))."


def grep_files(query: str = "", path: str = ".", glob: str = "*.py", max_hits: str = "60") -> str:
    """Search file contents under path. query=pattern glob=*.py"""
    if not query:
        return "Usage: grep_files query=TODO path=. glob=*.py"
    try:
        base = _resolve_path(path or ".")
    except Exception as e:
        return f"Refused: {e}"
    try:
        limit = max(1, min(int(max_hits or 60), MAX_GREP_HITS))
    except Exception:
        limit = 60
    pattern = glob or "*.*"
    try:
        rx = re.compile(query)
    except re.error:
        rx = re.compile(re.escape(query))
    hits = []
    root = Path(base)
    try:
        candidates = list(root.rglob(pattern)) if "**" not in pattern else list(root.glob(pattern))
        if not candidates:
            candidates = list(root.rglob(pattern))
    except Exception as e:
        return f"Search failed: {e}"
    for fp in candidates:
        if not fp.is_file():
            continue
        if fp.stat().st_size > MAX_READ:
            continue
        try:
            text = fp.read_text(encoding="utf-8-sig", errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append(f"{fp}:{i}: {line.strip()[:240]}")
                if len(hits) >= limit:
                    return "Grep results (truncated):\n" + "\n".join(hits)
    if not hits:
        return f"No matches for /{query}/ under {base} ({pattern})"
    return f"Grep results ({len(hits)}):\n" + "\n".join(hits)


def make_dir(path: str = "", confirm: str = "yes") -> str:
    if str(confirm).lower() not in ("yes", "true", "1", "y"):
        return "Refused: make_dir needs confirm=yes"
    try:
        full = _resolve_path(path)
        _assert_not_protected_write(full)
        os.makedirs(full, exist_ok=True)
        return f"Directory ready: {full}"
    except Exception as e:
        return f"Refused: {e}"


def delete_path(path: str = "", recursive: str = "no", confirm: str = "yes") -> str:
    """Delete file or directory under allowed roots. Blocks core OS trees. confirm=yes."""
    if str(confirm).lower() not in ("yes", "true", "1", "y"):
        return "Refused: delete_path needs confirm=yes"
    try:
        full = _resolve_path(path, must_exist=True)
        _assert_not_protected_write(full)
    except Exception as e:
        return f"Refused: {e}"
    try:
        if os.path.isdir(full):
            if str(recursive).lower() in ("yes", "true", "1", "y"):
                shutil.rmtree(full)
            else:
                if os.listdir(full):
                    return f"Refused: directory not empty (use recursive=yes): {full}"
                os.rmdir(full)
        else:
            os.remove(full)
        return f"Deleted: {full}"
    except Exception as e:
        return f"Delete failed: {e}"
