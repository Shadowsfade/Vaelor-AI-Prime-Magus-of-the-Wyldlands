import subprocess
import os


WORKSPACE = r"S:\VeilorServer\Workspace"


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
            cwd=WORKSPACE,
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