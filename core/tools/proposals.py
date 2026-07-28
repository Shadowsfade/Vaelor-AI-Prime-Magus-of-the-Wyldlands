"""
Vaelor Proposal System

This is the safety layer for any change that would modify a real file.
Nothing in this file writes to a project file. It only stores proposed
changes so a human can review a diff and explicitly approve or reject
before anything is touched.

Proposals are persisted to memory/proposals.json so they survive a
restart of Vaelor.
"""

import json
import os
import uuid
import difflib
from datetime import datetime

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
)

MEMORY_DIR = os.path.join(BASE_DIR, "memory")
PROPOSALS_FILE = os.path.join(MEMORY_DIR, "proposals.json")


def _load():
    if not os.path.exists(PROPOSALS_FILE):
        return []

    with open(PROPOSALS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data):
    os.makedirs(MEMORY_DIR, exist_ok=True)
    with open(PROPOSALS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def create_proposal(path, old_content, new_content):
    diff_lines = list(difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"{path} (current)",
        tofile=f"{path} (proposed)"
    ))

    proposal = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().isoformat(),
        "path": path,
        "old_content": old_content,
        "new_content": new_content,
        "diff": "".join(diff_lines) if diff_lines else "(no changes detected)",
        "status": "pending"
    }

    proposals = _load()
    proposals.append(proposal)
    _save(proposals)

    return proposal


def get_proposal(proposal_id):
    proposals = _load()
    for p in proposals:
        if p["id"] == proposal_id:
            return p
    return None


def list_pending():
    proposals = _load()
    return [p for p in proposals if p["status"] == "pending"]


def update_status(proposal_id, status):
    proposals = _load()
    for p in proposals:
        if p["id"] == proposal_id:
            p["status"] = status
    _save(proposals)