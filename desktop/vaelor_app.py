"""Vaelor desktop shell: arcane tome window + wizard voice + auto port."""
from __future__ import annotations

import atexit
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

WINDOW_TITLE = "Vaelor - Grand Archive"
BG = "#0a0603"


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def find_python(root: Path) -> Path:
    for c in (root / ".venv" / "Scripts" / "python.exe", root / "python" / "python.exe"):
        if c.exists():
            return c
    return Path(sys.executable)


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def wait_for_server(url: str, timeout: float = 70.0) -> bool:
    deadline = time.time() + timeout
    health = url.rstrip("/") + "/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health, timeout=1.5) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.3)
    return False


def start_server(root: Path, host: str, port: int):
    if port_open(host, port):
        try:
            with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=0.8) as r:
                if b"status" in r.read():
                    return None
        except Exception:
            pass

    py = find_python(root)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    env["VAELOR_HOST"] = host
    env["VAELOR_PORT"] = str(port)
    env["VAELOR_DESKTOP"] = "1"

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    log_dir = root / "memory"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_f = open(log_dir / "desktop_server.log", "a", encoding="utf-8", errors="replace")
    log_f.write(
        f"\n--- launch {time.strftime('%Y-%m-%d %H:%M:%S')} host={host} port={port} desktop=1 ---\n"
    )
    log_f.flush()

    cmd = [
        str(py),
        "-m",
        "uvicorn",
        "api.server:app",
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    return subprocess.Popen(
        cmd,
        cwd=str(root),
        env=env,
        stdout=log_f,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )


def splash_html(status: str = "Awakening the Grand Archive...") -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
  html,body{{height:100%;margin:0;background:{BG};color:#f0d78c;
    font-family:Georgia,'Times New Roman',serif;overflow:hidden}}
  body{{display:flex;align-items:center;justify-content:center;
    background:
      radial-gradient(ellipse 80% 60% at 50% 20%, rgba(90,50,15,.5), transparent 60%),
      radial-gradient(ellipse 70% 50% at 80% 100%, rgba(40,20,5,.75), transparent 55%),
      linear-gradient(165deg,#120a04 0%,#0a0603 50%,#160e08 100%);}}
  .seal{{width:110px;height:110px;border-radius:50%;margin:0 auto 18px;
    border:2px solid #d4af55;display:grid;place-items:center;font-size:2.4rem;
    color:#f0d78c;background:radial-gradient(circle at 35% 30%,#7a4e22,#2a160c 70%);
    box-shadow:0 0 28px rgba(212,175,85,.45), inset 0 0 24px rgba(212,175,85,.2);
    animation:pulse 2.2s ease-in-out infinite}}
  @keyframes pulse{{0%,100%{{transform:scale(1)}}50%{{transform:scale(1.05)}}}}
  h1{{font-size:2rem;letter-spacing:.18em;margin:0 0 8px;text-align:center;
    text-shadow:0 0 18px rgba(212,175,85,.45)}}
  p{{text-align:center;opacity:.9;margin:6px 0;font-style:italic}}
  .status{{margin-top:22px;font-size:.95rem;letter-spacing:.08em;opacity:.8}}
  .bar{{width:220px;height:4px;margin:18px auto 0;border-radius:3px;
    background:rgba(212,175,85,.15);overflow:hidden}}
  .bar>i{{display:block;height:100%;width:35%;background:linear-gradient(90deg,#8a6a2e,#f0d78c);
    animation:slide 1.4s ease-in-out infinite}}
  @keyframes slide{{0%{{transform:translateX(-120%)}}100%{{transform:translateX(320%)}}}}
</style></head>
<body>
  <div>
    <div class="seal">*</div>
    <h1>VAELOR</h1>
    <p>Arcane Archivist of the Wyldlands</p>
    <p class="status" id="st">{status}</p>
    <div class="bar"><i></i></div>
  </div>
</body></html>"""


def fetch_json(url: str, timeout: float = 8.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="ignore"))


def play_wizard_greeting(root: Path, base_url: str) -> None:
    """Play wizard TTS greeting without opening a browser window."""
    try:
        data = fetch_json(base_url.rstrip("/") + "/greeting", timeout=20)
        b64 = data.get("audio_base64")
        if b64:
            import base64

            audio = base64.b64decode(b64)
        else:
            text = data.get("text") or "Greetings, Apprentice. The Vaelor Archive awakens."
            req = urllib.request.Request(
                base_url.rstrip("/") + "/voice/speak",
                data=json.dumps({"text": text}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=45) as r:
                audio = r.read()
            if not audio:
                return
        tmp = Path(tempfile.gettempdir()) / "vaelor_desktop_greet.mp3"
        tmp.write_bytes(audio)

        if os.name == "nt":
            path = str(tmp).replace("'", "''")
            ps = (
                "$p = New-Object -ComObject WMPlayer.OCX; "
                f"$m = $p.newMedia('{path}'); "
                "$p.currentPlaylist.appendItem($m); $p.controls.play(); "
                "Start-Sleep -Milliseconds 400; "
                "while($p.playState -eq 3){ Start-Sleep -Milliseconds 300 }; "
                "$p.close()"
            )
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                creationflags=flags,
            )
        else:
            subprocess.Popen(["xdg-open", str(tmp)])
    except Exception as e:
        try:
            log = root / "memory" / "desktop_server.log"
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"greeting voice failed: {e}\n")
        except Exception:
            pass


def main() -> int:
    root = app_root()
    os.chdir(root)
    sys.path.insert(0, str(root))

    try:
        from installer.init_local_config import init_local_config
        init_local_config(root, force=False)
    except Exception:
        pass
    from core.netbind import resolve_bind

    host, port, url = resolve_bind(root)
    app_url = url.rstrip("/") + "/?desktop=1"

    server_proc = start_server(root, host, port)

    def _cleanup() -> None:
        if server_proc and server_proc.poll() is None:
            try:
                server_proc.terminate()
                try:
                    server_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server_proc.kill()
            except Exception:
                pass

    atexit.register(_cleanup)

    import webview

    window = webview.create_window(
        WINDOW_TITLE,
        html=splash_html("Binding the aether and opening the tome..."),
        width=1240,
        height=860,
        min_size=(960, 640),
        background_color=BG,
        text_select=True,
        confirm_close=False,
    )

    def boot() -> None:
        ready = wait_for_server(url, 70)
        if not ready:
            try:
                window.load_html(
                    splash_html(
                        f"The archive could not awaken at {url}. See memory/desktop_server.log"
                    )
                )
            except Exception:
                pass
            return
        try:
            window.load_url(app_url)
        except Exception:
            try:
                window.evaluate_js(f"window.location.replace({json.dumps(app_url)})")
            except Exception:
                pass
        time.sleep(1.2)
        play_wizard_greeting(root, url)

    threading.Thread(target=boot, daemon=True).start()
    webview.start()
    _cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
