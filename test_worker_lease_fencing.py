from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.brain import VaelorBrain
from core.task_store import TaskStore, LeaseLostError


def test_expired_worker_cannot_check_or_publish_result(tmp_path):
    store = TaskStore(tmp_path / "tasks.json")
    task = store.create("inspect")
    store.claim(task["id"], "old", now=datetime.now(timezone.utc) - timedelta(hours=1))
    with pytest.raises(LeaseLostError):
        store.worker_cancelled(task["id"], "old")
    with pytest.raises(LeaseLostError):
        store.update(task["id"], status="completed", result="stale", owner="old")
    assert store.get(task["id"])["result"] is None


def test_replacement_result_cannot_be_overwritten(tmp_path):
    store = TaskStore(tmp_path / "tasks.json")
    task = store.create("inspect")
    store.claim(task["id"], "new")
    store.update(task["id"], status="completed", result="replacement", owner="new")
    with pytest.raises(LeaseLostError):
        store.update(task["id"], status="failed", result="old crashed", owner="old")
    assert store.get(task["id"])["result"] == "replacement"


def make_brain(tmp_path):
    brain = VaelorBrain.__new__(VaelorBrain)
    brain.tasks = TaskStore(tmp_path / "tasks.json")
    brain.conversations = MagicMock()
    for name in ("build_system_prompt", "_system_context", "_context_prefix", "_history_text"):
        setattr(brain, name, MagicMock(return_value=""))
    return brain


@pytest.mark.parametrize("after_model", [True, False])
def test_stale_brain_cannot_execute_or_overwrite_replacement(tmp_path, after_model):
    brain = make_brain(tmp_path)
    task = brain.tasks.create("inspect repository")
    def replace(*args, **kwargs):
        brain.tasks.release(task["id"], "old")
        brain.tasks.claim(task["id"], "new")
        brain.tasks.update(task["id"], status="completed", result="replacement", owner="new")
        if after_model:
            return '{"actions":[{"tool":"shell_exec","arguments":{"command":"git status"}}],"final":null}'
        return "FINAL_SUMMARY: SUCCESS stale"
    target = "core.brain.VaelorBrain._agent_reply" if after_model else "core.agent_loop.run_agent"
    with patch(target, side_effect=replace), patch("core.brain.build_project_context", return_value=""), patch("core.agent_loop.registry.execute") as execute:
        with pytest.raises(RuntimeError):
            brain.act("inspect repository", task_id=task["id"], owner="old")
    execute.assert_not_called()
    assert brain.tasks.get(task["id"])["result"] == "replacement"
    brain.conversations.remember_turn.assert_not_called()


def test_user_cancellation_result_survives_worker_completion(tmp_path):
    store = TaskStore(tmp_path / "tasks.json")
    task = store.create("inspect")
    store.claim(task["id"], "worker")
    store.cancel(task["id"], "User stopped this task")
    assert store.worker_cancelled(task["id"], "worker")
    store.update(task["id"], status="failed", result="late error", owner="worker")
    assert store.get(task["id"])["result"] == "User stopped this task"


def test_workflow_error_does_not_overwrite_replacement(tmp_path):
    brain = make_brain(tmp_path)
    task = brain.tasks.create("install example")
    def replaced(*args):
        brain.tasks.release(task["id"], "old")
        brain.tasks.claim(task["id"], "new")
        brain.tasks.update(task["id"], status="completed", result="replacement", owner="new")
        raise RuntimeError("old workflow error")
    with patch("core.cachyos_workflow.is_software_request", return_value=True), patch("core.cachyos_workflow.run_platform_workflow", side_effect=replaced):
        with pytest.raises(RuntimeError, match="old workflow error"):
            brain.act("install example", task_id=task["id"], owner="old")
    assert brain.tasks.get(task["id"])["result"] == "replacement"
