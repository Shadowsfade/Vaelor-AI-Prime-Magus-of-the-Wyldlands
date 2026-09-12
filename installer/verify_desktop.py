"""Exercise a relocated frozen package with Python removed from PATH."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request


def verify(package):
    with tempfile.TemporaryDirectory(prefix="vaelor-relocated-") as temp:
        relocated = Path(temp) / "Moved Vaelor"
        shutil.copytree(package, relocated)
        if any(relocated.rglob("pyvenv.cfg")):
            raise RuntimeError("Package contains a nonportable virtual environment.")
        if (relocated / "_internal/config/api_access.json").exists():
            raise RuntimeError("Package contains remote credentials.")
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env["PATH"] = str(Path(env.get("SystemRoot", "C:/Windows")) / "System32")
        process = subprocess.Popen([str(relocated / "Vaelor.exe"), "--server", "--port", str(port)],
            cwd=temp, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Frozen server exited with {process.returncode}")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                        health = json.load(response)
                    break
                except OSError:
                    time.sleep(.25)
            else:
                raise RuntimeError("Frozen server did not become healthy.")
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
                html = response.read().decode()
            assert 'id="researchBtn"' in html and "continue-software" in html
            result = {"relocated_runtime": "passed", "python_on_path": False,
                      "health": health["status"], "web_ui": "passed"}
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        report = Path(temp) / "native-ui.json"
        subprocess.run([str(relocated / "Vaelor.exe"), "--smoke-ui-output", str(report)],
            cwd=temp, env=env, timeout=100, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        result["native_webview"] = json.loads(report.read_text(encoding="utf-8"))
        if result["native_webview"]["status"] != "passed":
            raise RuntimeError("Native WebView did not render the task/chat controls.")
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.package.resolve()), indent=2))
