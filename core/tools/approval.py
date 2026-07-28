"""
Approval flow for Vaelor's write-capable tools.

approve_change() is the ONLY code path in the entire project that
writes to a project file on Vaelor's behalf. It is only ever triggered
by the Architect explicitly typing 'approve: <id>' - never automatically.

Before writing, it always backs up the current file content to
S:\VeilorServer\Backups\ with a timestamped name, so any bad change
can be manually restored even without git.
"""

import os
import shutil
from datetime import datetime

from .proposals import get_proposal, update_status

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
)

BACKUPS_DIR = r"S:\VeilorServer\Backups"


def approve_change(proposal_id):
    proposal = get_proposal(proposal_id)

    if proposal is None:
        return f"No proposal found with id {proposal_id}."

    if proposal["status"] != "pending":
        return f"Proposal {proposal_id} is already '{proposal['status']}', not pending."

    full_path = os.path.abspath(
        os.path.join(PROJECT_ROOT, proposal["path"])
    )

    if not full_path.startswith(PROJECT_ROOT):
        return "Refused: proposal path escapes the project root."

    if os.path.exists(full_path):
        os.makedirs(BACKUPS_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = proposal["path"].replace("\\", "_").replace("/", "_")
        backup_path = os.path.join(
            BACKUPS_DIR,
            f"{safe_name}.{timestamp}.bak"
        )
        shutil.copy2(full_path, backup_path)
    else:
        backup_path = None

    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, "w", encoding="utf-8") as f:
        f.write(proposal["new_content"])

    update_status(proposal_id, "approved")

    result = f"Applied proposal {proposal_id} to {proposal['path']}."
    if backup_path:
        result += f"\nBackup saved: {backup_path}"

    return result


def reject_change(proposal_id):
    proposal = get_proposal(proposal_id)

    if proposal is None:
        return f"No proposal found with id {proposal_id}."

    if proposal["status"] != "pending":
        return f"Proposal {proposal_id} is already '{proposal['status']}', not pending."

    update_status(proposal_id, "rejected")

    return f"Discarded proposal {proposal_id} for {proposal['path']}. No files were changed."