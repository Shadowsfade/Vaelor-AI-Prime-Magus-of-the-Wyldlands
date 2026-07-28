"""
project_scanner tool

Read-only. Lists the folder/file structure of the Vaelor project so
Vaelor can answer questions like "what does my project look like"
without needing manual copy/paste from the Architect.
"""

import os

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
)

EXCLUDE_DIRS = {".venv", "__pycache__", ".git", "node_modules"}


def scan_project(path=None, max_depth=4):
    """
    Returns a text tree of the project structure.
    path: optional subfolder relative to project root. Defaults to whole project.
    """
    start = PROJECT_ROOT

    if path:
        candidate = os.path.abspath(os.path.join(PROJECT_ROOT, path))
        if not candidate.startswith(PROJECT_ROOT):
            return "Refused: path escapes the project root."
        start = candidate

    if not os.path.exists(start):
        return f"Path not found: {path}"

    lines = []

    def walk(current_path, depth):
        if depth > max_depth:
            return

        try:
            entries = sorted(os.listdir(current_path))
        except PermissionError:
            return

        for entry in entries:
            if entry in EXCLUDE_DIRS:
                continue

            full_path = os.path.join(current_path, entry)
            indent = "  " * depth

            if os.path.isdir(full_path):
                lines.append(f"{indent}{entry}/")
                walk(full_path, depth + 1)
            else:
                lines.append(f"{indent}{entry}")

    lines.append(os.path.relpath(start, PROJECT_ROOT) or ".")
    walk(start, 1)

    return "\n".join(lines)


if __name__ == "__main__":
    print(scan_project())