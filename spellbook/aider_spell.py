import subprocess
import os
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def configured_workspace() -> str:
    try:
        config = json.loads((ROOT / "config" / "vaelor.json").read_text(encoding="utf-8-sig"))
        candidate = Path(str((config.get("workspace") or {}).get("path") or "")).expanduser()
        if candidate.is_dir():
            return str(candidate.resolve())
    except (OSError, ValueError, TypeError):
        pass
    return str(ROOT)


def cast_aider_spell(task):

    command = [
        "aider",
        "--no-show-model-warnings",
        "--model",
        "ollama/qwen2.5-coder:7b",
        "--git",
        "--auto-commits",
        "--show-diffs",
        "--yes-always",
        "--message",
        task
    ]

    try:
        result = subprocess.run(
            command,
            cwd=configured_workspace(),
            capture_output=True,
            text=True
        )

        return result.stdout + "\n" + result.stderr

    except Exception as e:
        return f"Aider spell failed: {e}"


if __name__ == "__main__":

    print("AiderSpell initialized.")

    response = cast_aider_spell(
        "Create a file called hello_vaelor.py containing a simple hello world function."
    )

    print(response)
