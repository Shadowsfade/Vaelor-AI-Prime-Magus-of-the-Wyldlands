"""Persistent shell sessions for Vaelor's native CLI and future terminal UI."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time
import uuid

from core.tools.shell_exec import _audit, _is_mutating, _is_os_wreck, _resolve_cwd, load_autonomy


MAX_SESSION_OUTPUT = 30000
MAX_STREAM_CHUNK = 4000
_OUTPUT_CALLBACK = ContextVar("vaelor_terminal_output_callback", default=None)


@contextmanager
def terminal_output_events(callback):
    """Temporarily expose terminal output without adding callbacks to the tool schema."""
    token = _OUTPUT_CALLBACK.set(callback)
    try:
        yield
    finally:
        _OUTPUT_CALLBACK.reset(token)


@dataclass
class TerminalSession:
    id: str
    cwd: str
    process: subprocess.Popen
    output: queue.Queue = field(default_factory=queue.Queue)
    lock: threading.RLock = field(default_factory=threading.RLock)


class TerminalSessionManager:
    """Manage long-lived shells while applying the same safety policy as shell_exec."""

    def __init__(self):
        self._sessions = {}
        self._lock = threading.RLock()

    @staticmethod
    def _command():
        if os.name == "nt":
            return ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "-"]
        return ["bash", "--noprofile", "--norc"]

    @staticmethod
    def _pump(stream, output):
        try:
            for line in iter(stream.readline, ""):
                output.put(line)
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def create(self, cwd=None):
        workdir = _resolve_cwd(cwd)
        process = subprocess.Popen(
            self._command(), cwd=workdir, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
            env={**os.environ, "GIT_PAGER": "cat", "PAGER": "cat"},
        )
        session = TerminalSession(str(uuid.uuid4())[:12], workdir, process)
        threading.Thread(
            target=self._pump, args=(process.stdout, session.output), daemon=True
        ).start()
        with self._lock:
            self._sessions[session.id] = session
        return {"id": session.id, "cwd": session.cwd, "running": True}

    def list(self):
        with self._lock:
            return [
                {"id": item.id, "cwd": item.cwd, "running": item.process.poll() is None}
                for item in self._sessions.values()
            ]

    def execute(self, session_id, command, timeout=180, confirm="no"):
        command = str(command or "").strip()
        if not command:
            raise ValueError("Command cannot be empty.")
        wreck = _is_os_wreck(command)
        if wreck:
            raise PermissionError(wreck)
        cfg = load_autonomy()
        mode = str(cfg.get("mode", "supervised")).lower()
        mutating = _is_mutating(command)
        approved = str(confirm).lower() in ("yes", "true", "1", "y")
        if mutating and mode == "supervised" and not approved:
            raise PermissionError("Supervised mode requires explicit confirmation.")
        timeout = max(1, min(int(timeout), int(cfg.get("max_timeout_seconds") or 180)))
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Unknown terminal session: {session_id}")
        with session.lock:
            if session.process.poll() is not None:
                raise RuntimeError("Terminal session is no longer running.")
            marker = "__VAELOR_DONE_" + uuid.uuid4().hex
            if os.name == "nt":
                payload = (
                    f"{command}\n"
                    "$vaelorExitCode = if ($?) { 0 } else { 1 }\n"
                    f"Write-Output ('{marker}:' + $vaelorExitCode)\n"
                )
            else:
                payload = f"{command}\nprintf '{marker}:%s\\n' $?\n"
            session.process.stdin.write(payload)
            session.process.stdin.flush()
            chunks = []
            stream_chunks = []
            stream_size = 0
            last_stream = time.monotonic()
            returncode = None
            deadline = time.monotonic() + timeout

            def flush_stream():
                nonlocal stream_chunks, stream_size, last_stream
                if not stream_chunks:
                    return
                callback = _OUTPUT_CALLBACK.get()
                payload = "".join(stream_chunks)[-MAX_STREAM_CHUNK:]
                stream_chunks = []
                stream_size = 0
                last_stream = time.monotonic()
                if callback:
                    try:
                        callback(payload)
                    except Exception:
                        pass

            while time.monotonic() < deadline:
                try:
                    line = session.output.get(timeout=min(0.1, deadline - time.monotonic()))
                except queue.Empty:
                    if session.process.poll() is not None:
                        break
                    continue
                if line.startswith(marker + ":"):
                    try:
                        returncode = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        returncode = 1
                    break
                chunks.append(line)
                stream_chunks.append(line)
                stream_size += len(line)
                if stream_size >= 2048 or time.monotonic() - last_stream >= 0.25:
                    flush_stream()
            flush_stream()
            if returncode is None:
                raise TimeoutError(f"Command exceeded {timeout}s; session remains available.")
            output = "".join(chunks).strip()
            if len(output) > MAX_SESSION_OUTPUT:
                output = output[-MAX_SESSION_OUTPUT:]
            _audit({"tool": "terminal_session", "session_id": session_id, "command": command,
                    "mode": mode, "mutating": mutating, "returncode": returncode})
            return {"session_id": session_id, "returncode": returncode, "output": output}

    def interrupt(self, session_id):
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Unknown terminal session: {session_id}")
        if session.process.poll() is None:
            session.process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        return {"id": session_id, "running": session.process.poll() is None}

    def close(self, session_id):
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if not session:
            raise KeyError(f"Unknown terminal session: {session_id}")
        if session.process.poll() is None:
            try:
                session.process.stdin.close()
            except Exception:
                pass
            session.process.terminate()
            try:
                session.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                session.process.kill()
        return {"id": session_id, "running": False}

    def close_all(self):
        for session_id in [item["id"] for item in self.list()]:
            self.close(session_id)


manager = TerminalSessionManager()


def terminal_start(cwd: str = "") -> dict:
    return manager.create(cwd or None)


def terminal_list() -> list:
    return manager.list()


def terminal_run(session_id: str, command: str, timeout: int = 180,
                 confirm: str = "no") -> dict:
    return manager.execute(session_id, command, timeout=timeout, confirm=confirm)


def terminal_interrupt(session_id: str) -> dict:
    return manager.interrupt(session_id)


def terminal_close(session_id: str) -> dict:
    return manager.close(session_id)
