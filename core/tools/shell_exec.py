"""Vaelor shell: broad access, never destroy core OS files."""
from __future__ import annotations
import json, os, re, subprocess
from datetime import datetime
from typing import List, Optional, Set

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "autonomy.json")
DEFAULT_TIMEOUT = 180
MAX_OUTPUT = 30000

# Always blocked: OS-wrecking / privilege bombs
OS_WRECK_BLOCKS = [
    r"\bformat\s+[A-Za-z]:",
    r"\bmkfs\b",
    r"\bdiskpart\b",
    r"\bcipher\s+/w",
    r"\brm\s+-rf\s+/($|\s)",
    r"\brm\s+-rf\s+/boot\b",
    r"\brm\s+-rf\s+/etc\b",
    r"\brm\s+-rf\s+/usr\b",
    r"\brm\s+-rf\s+/lib\b",
    r"\brm\s+-rf\s+/lib64\b",
    r"\brm\s+-rf\s+/bin\b",
    r"\brm\s+-rf\s+/sbin\b",
    r"\brm\s+-rf\s+/System\b",
    r"\bdel\s+/[sf].*C:\\Windows",
    r"Remove-Item\s+-Recurse\s+-Force\s+C:\\Windows",
    r"Remove-Item\s+-Recurse\s+-Force\s+['\"]?C:\\Windows",
    r"Remove-Item\s+-Recurse\s+-Force\s+['\"]?C:\\Program Files",
    r"Remove-Item\s+-Recurse\s+-Force\s+['\"]?C:\\ProgramData",
    r"Remove-Item\s+-Recurse\s+-Force\s+['\"]?C:\\Users(?:\\|$)",
    r"\bshutdown\b.*/[sr]",
    r"\bStop-Computer\b",
    r"\bRestart-Computer\b.*/Force",
    r"\bClear-Disk\b",
    r"\bInitialize-Disk\b",
    r"\bbcdedit\b",
    r"\bbootrec\b",
    r"\breg\s+delete\s+HKLM\\SYSTEM",
    r"\breg\s+delete\s+HKLM\\SOFTWARE\\Microsoft\\Windows",
    r":\s*\(\)\{",
]

# Destructive verbs that cannot target protected roots
DELETE_VERBS = [
    r"Remove-Item", r"\brm\b", r"\bdel\b", r"\berase\b", r"\brd\b", r"\brmdir\b",
    r"Clear-Content", r"\btruncate\b",
]

def load_autonomy() -> dict:
    defaults = {
        "mode": "supervised",
        "auto_confirm_mutations": False,
        "allow_installs": False,
        "sandbox_enforced": True,
        "require_sandbox_paths_in_commands": True,
        "protected_delete_roots": [r"C:\Windows", r"C:\Windows\System32", r"C:\Program Files", r"C:\ProgramData"],
        "allowed_user_profile": os.path.expanduser("~"),
        "audit_log": "memory/audit_log.jsonl",
        "max_timeout_seconds": 180,
        "default_cwd": PROJECT_ROOT,
    }
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            return defaults
        cfg = {**defaults, **loaded}
        if str(cfg.get("mode", "")).lower() not in ("supervised", "trusted", "admin"):
            cfg["mode"] = "supervised"
            cfg["auto_confirm_mutations"] = False
        return cfg
    except Exception:
        return defaults

def _norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expandvars(os.path.expanduser(p))))

def _audit(event: dict) -> None:
    cfg = load_autonomy()
    path = cfg.get("audit_log") or "memory/audit_log.jsonl"
    if not os.path.isabs(path):
        path = os.path.join(PROJECT_ROOT, path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    event = {"ts": datetime.now().isoformat(), **event}
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass

def _is_under(path: str, root: str) -> bool:
    path, root = _norm(path), _norm(root)
    return path == root or path.startswith(root.rstrip("\\/") + os.sep)

def _protected_delete_roots(cfg: dict) -> List[str]:
    roots = [_norm(r) for r in (cfg.get("protected_delete_roots") or cfg.get("protected_roots") or [])]
    defaults = [
        r"C:\Windows", r"C:\Windows\System32", r"C:\Windows\SysWOW64", r"C:\Windows\WinSxS",
        r"C:\Program Files", r"C:\Program Files (x86)", r"C:\ProgramData",
        r"C:\Recovery", r"C:\Boot", r"C:\EFI",
        r"C:\Users\Public", r"C:\Users\Default",
    ]
    for d in defaults:
        nd = _norm(d)
        if nd not in roots:
            roots.append(nd)
    return roots

def _extract_paths(command: str) -> List[str]:
    paths = []
    for m in re.finditer(r"['\"]([^'\"]+)['\"]", command):
        cand = m.group(1)
        if re.search(r"[\\/]|^[A-Za-z]:", cand):
            paths.append(cand)
    for m in re.finditer(r"(?<![\w])([A-Za-z]:\\[^\s|&><;]+)", command):
        paths.append(m.group(1).strip("\"'"))
    for m in re.finditer(r"(?<![\w])(\.{1,2}[\\/][^\s|&><;]+)", command):
        paths.append(m.group(1))
    out, seen = [], set()
    for p in paths:
        if p not in seen:
            seen.add(p); out.append(p)
    return out

def _is_os_wreck(cmd: str) -> Optional[str]:
    c = cmd.strip()
    for pat in OS_WRECK_BLOCKS:
        try:
            if re.search(pat, c, re.IGNORECASE):
                return f"Blocked: would endanger the operating system ({pat})"
        except re.error:
            continue
    # delete/remove targeting protected roots
    is_delete = any(re.search(v, c, re.I) for v in DELETE_VERBS)
    if is_delete:
        cfg = load_autonomy()
        cwd = cfg.get("default_cwd") or PROJECT_ROOT
        for raw in _extract_paths(c):
            cand = raw if os.path.isabs(raw) else os.path.abspath(os.path.join(cwd, raw))
            cand = os.path.abspath(os.path.expandvars(cand))
            for root in _protected_delete_roots(cfg):
                if _is_under(cand, root):
                    return f"Blocked: full delete/modify of core OS path not allowed: {cand}"
            # other users
            allowed_user = cfg.get("allowed_user_profile")
            if allowed_user:
                users = _norm(r"C:\Users")
                if _is_under(cand, users) and not _is_under(cand, allowed_user) and _norm(cand) != users:
                    return f"Blocked: other user profile path not allowed: {cand}"
    return None

def _is_mutating(cmd: str) -> bool:
    c = cmd.strip()
    if re.search(r"(?<![0-9])>(?!>)", c) or ">>" in c:
        return True
    mut = [
        r"\bRemove-Item\b", r"\bMove-Item\b", r"\bCopy-Item\b", r"\bNew-Item\b", r"\bSet-Content\b",
        r"\bAdd-Content\b", r"\bOut-File\b", r"\bmkdir\b", r"\btouch\b", r"\bpip\s+install\b",
        r"\bnpm\s+install\b", r"\bwinget\s+install\b", r"\bgit\s+(commit|push|reset|checkout|merge|rebase|clean)\b",
        r"\brm\b", r"\bdel\b", r"\biwr\b", r"\bInvoke-WebRequest\b", r"\bStart-Process\b",
    ]
    return any(re.search(p, c, re.I) for p in mut)

def _resolve_cwd(cwd: Optional[str]) -> str:
    cfg = load_autonomy()
    default = cfg.get("default_cwd") or PROJECT_ROOT
    base = default if os.path.isdir(default) else PROJECT_ROOT
    if not cwd:
        candidate = base
    else:
        candidate = cwd if os.path.isabs(cwd) else os.path.abspath(os.path.join(base, cwd))
    candidate = _norm(candidate)
    # allow almost anywhere except protected OS roots as cwd for deletes; reading from anywhere is ok
    # still refuse cwd inside System32 as working dir for safety of accidental relative deletes
    for root in [r"C:\Windows\System32", r"C:\Windows\SysWOW64", r"C:\Windows\WinSxS"]:
        if _is_under(candidate, root):
            raise ValueError(f"cwd in protected OS core not allowed: {candidate}")
    if not os.path.isdir(candidate):
        raise ValueError(f"cwd is not a directory: {candidate}")
    return candidate

def shell_exec(command: str = "", cwd: str = "", timeout: int = DEFAULT_TIMEOUT, confirm: str = "no") -> str:
    """Run almost any command. Blocks only OS-core destruction."""
    command = (command or "").strip()
    if not command:
        return "Refused: no command."

    wreck = _is_os_wreck(command)
    if wreck:
        _audit({"tool": "shell_exec", "command": command, "result": "os_protected", "reason": wreck})
        return f"Refused: {wreck}\nVaelor has broad access, but cannot fully delete/destroy core operating system files."

    cfg = load_autonomy()
    try:
        workdir = _resolve_cwd(cwd or None)
    except Exception as e:
        return f"Refused: {e}"

    # admin/trusted: auto confirm mutations
    mode = (cfg.get("mode") or "admin").lower()
    mutating = _is_mutating(command)
    if mutating and mode in ("trusted", "admin"):
        confirm = "yes"
    if mutating and mode == "supervised" and str(confirm).lower() not in ("yes", "true", "1", "y"):
        return f"Refused: supervised mode needs confirm=yes\nCommand: {command}"

    max_t = int(cfg.get("max_timeout_seconds") or 1800)
    timeout = max(5, min(int(timeout or DEFAULT_TIMEOUT), max_t))
    full_cmd = ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command] if os.name == "nt" else ["bash", "-lc", command]
    try:
        proc = subprocess.run(full_cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, "GIT_PAGER": "cat", "PAGER": "cat"})
    except subprocess.TimeoutExpired:
        _audit({"tool": "shell_exec", "command": command, "cwd": workdir, "result": "timeout"})
        return f"Timed out after {timeout}s: {command}"
    except Exception as e:
        _audit({"tool": "shell_exec", "command": command, "cwd": workdir, "result": "error", "error": str(e)})
        return f"Shell execution failed: {e}"

    out = ((proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")).strip()
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + f"\n...[truncated {len(out)-MAX_OUTPUT} chars]"
    status = "OK" if proc.returncode == 0 else f"EXIT {proc.returncode}"
    _audit({"tool": "shell_exec", "command": command, "cwd": workdir, "mutating": mutating,
            "returncode": proc.returncode, "mode": mode, "result": status})
    return f"[{status}] mode={mode} cwd={workdir}\n$ {command}\n" + (out if out else "(no output)")

def shell_which(command: str = "") -> str:
    command = (command or "").strip()
    if not command:
        return "Usage: tool: shell_which command=git"
    return shell_exec(command=f"Get-Command {command} | Format-List Name,Source,CommandType", timeout=15)

def set_autonomy_mode(mode: str = "admin") -> str:
    mode = (mode or "admin").lower().strip()
    if mode not in ("supervised", "trusted", "admin"):
        return "Refused: mode must be supervised|trusted|admin"
    cfg = load_autonomy()
    cfg["mode"] = mode
    cfg["auto_confirm_mutations"] = mode in ("trusted", "admin")
    cfg["allow_installs"] = True
    cfg["sandbox_enforced"] = False
    cfg["require_sandbox_paths_in_commands"] = False
    cfg["profile"] = "full_access_os_safe"
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    _audit({"tool": "set_autonomy_mode", "mode": mode, "result": "ok"})
    return f"Autonomy mode='{mode}'. Broad access enabled. Core OS delete/destroy still blocked."

def get_autonomy_status() -> str:
    return json.dumps(load_autonomy(), indent=2)

def describe_sandbox() -> str:
    cfg = load_autonomy()
    lines = [
        "Vaelor Access Policy: FULL ACCESS / OS-SAFE",
        f"mode={cfg.get('mode')} profile={cfg.get('profile')}",
        "Allowed: broad system use, installs, git, files, development.",
        "NOT allowed: full delete/destroy of core OS paths (Windows/System32, Program Files core, other users, boot).",
        "Protected delete roots:",
    ]
    for r in cfg.get("protected_delete_roots") or cfg.get("protected_roots") or []:
        lines.append(f"  x {r}")
    lines.append("Audit: " + str(cfg.get("audit_log")))
    return "\n".join(lines)
