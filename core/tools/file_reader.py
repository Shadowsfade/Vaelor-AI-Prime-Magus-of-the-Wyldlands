"""
file_reader tool

Read-only. Lets Vaelor read the contents of a single file inside his
own project, so he can answer questions about his own code without the
Architect needing to paste it manually.

Safety: refuses any path that resolves outside the project root, and
refuses files above a size limit to avoid flooding the model context.
"""

import os

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
)

MAX_FILE_SIZE = 200_000  # bytes, ~200KB safety cap


def read_file(path):
    if not path:
        return "Refused: no path provided."

    full_path = os.path.abspath(os.path.join(PROJECT_ROOT, path))

    if not full_path.startswith(PROJECT_ROOT):
        return "Refused: path escapes the project root."

    if not os.path.exists(full_path):
        return f"File not found: {path}"

    if not os.path.isfile(full_path):
        return f"Not a file: {path}"

    size = os.path.getsize(full_path)
    if size > MAX_FILE_SIZE:
        return f"Refused: file too large ({size} bytes, limit {MAX_FILE_SIZE})."

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        return f"Refused: file is not readable text ({path})."

    return f"----- {path} -----\n{content}"


if __name__ == "__main__":
    print(read_file("vaelor.py"))