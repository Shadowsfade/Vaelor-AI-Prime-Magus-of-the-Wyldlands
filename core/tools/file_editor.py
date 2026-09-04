"""
file_editor tool

Two-step, staging-based edit workflow. Windows PowerShell does not
reliably deliver multi-line pasted text into a Python input() loop,
so instead of pasting into the terminal, edits are made in Notepad
against a staging copy of the file.

Step 1: 'stage: <path>' - creates a staging copy of the file (or a
blank one if it doesn't exist yet) inside .staging/, and tells the
Architect where to edit it.

Step 2: 'propose: <path>' - reads the edited staging copy, generates a
diff against the real file, and creates a pending proposal. The
staging copy is then cleared so the next edit starts fresh.

Nothing in this file writes to a real project file. Only approval.py
does that, and only when explicitly triggered by 'approve: <id>'.
"""

import os
import shutil

from .proposals import create_proposal

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
)

STAGING_DIR = os.path.join(PROJECT_ROOT, ".staging")


def _resolve(path):
    full_path = os.path.abspath(os.path.join(PROJECT_ROOT, path))
    if not full_path.startswith(PROJECT_ROOT):
        return None
    return full_path


def _staging_path(path):
    return os.path.join(STAGING_DIR, path)


def stage_file(path):
    if not path:
        return "Refused: no path provided."

    full_path = _resolve(path)
    if full_path is None:
        return "Refused: path escapes the project root."

    staging_path = _staging_path(path)
    os.makedirs(os.path.dirname(staging_path), exist_ok=True)

    if os.path.exists(full_path):
        shutil.copy2(full_path, staging_path)
        note = "seeded with the file's current content"
    else:
        open(staging_path, "w", encoding="utf-8").close()
        note = "this is a new file, staging copy starts empty"

    return (
        f"Staging copy ready ({note}):\n"
        f"{staging_path}\n\n"
        f"Open it in Notepad, edit it, save, then run:\n"
        f"propose: {path}"
    )


def propose_edit(path):
    if not path:
        return "Refused: no path provided."

    full_path = _resolve(path)
    if full_path is None:
        return "Refused: path escapes the project root."

    staging_path = _staging_path(path)

    if not os.path.exists(staging_path):
        return (
            f"No staged content found for {path}.\n"
            f"Run 'stage: {path}' first, edit the file it creates, then propose again."
        )

    with open(staging_path, "r", encoding="utf-8") as f:
        new_content = f.read()

    old_content = ""
    if os.path.exists(full_path):
        with open(full_path, "r", encoding="utf-8") as f:
            old_content = f.read()

    proposal = create_proposal(path, old_content, new_content)

    try:
        os.remove(staging_path)
    except OSError:
        pass

    return (
        f"Proposal {proposal['id']} created for {path}.\n\n"
        f"{proposal['diff']}\n\n"
        f"To apply: approve: {proposal['id']}\n"
        f"To discard: reject: {proposal['id']}"
    )
