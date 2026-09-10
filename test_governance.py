import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from core.governance import (ActionAuthorization, EvidenceProvenance,
                              EvidenceSource, bound_action_fingerprint,
                              mutation_supported, issue_authorization, GovernedInvocation)
from core.tools.registry import ToolRegistry


class GovernanceTests(unittest.TestCase):
    def test_evidence_sources_are_typed_and_quarantine_is_fail_closed(self):
        current = EvidenceProvenance("e1", EvidenceSource.CURRENT_TOOL, "read", "now",
                                     trust="validated", may_influence_mutation=True)
        historical = EvidenceProvenance("e2", EvidenceSource.HISTORICAL_TASK, "memory", "then")
        unavailable = EvidenceProvenance("e3", EvidenceSource.UNAVAILABLE, "tool", "now")
        self.assertTrue(mutation_supported((current,)))
        self.assertFalse(mutation_supported((historical,)))
        self.assertFalse(mutation_supported((unavailable,)))

    def test_bound_authorization_changes_with_arguments_target_state(self):
        base = bound_action_fingerprint("write", {"path": "a"}, target="a", state="s1")
        self.assertNotEqual(base, bound_action_fingerprint("write", {"path": "b"}, target="a", state="s1"))
        self.assertNotEqual(base, bound_action_fingerprint("write", {"path": "a"}, target="b", state="s1"))
        self.assertNotEqual(base, bound_action_fingerprint("write", {"path": "a"}, target="a", state="s2"))

    def test_guarded_registry_rejects_bypass_and_allows_bound_action(self):
        reg = ToolRegistry()
        calls = []
        reg.register("mutate", "mutation", False, lambda value="": calls.append(value) or "ok")
        self.assertIn("authorization", reg.execute_guarded("mutate", value="x"))
        invocation = GovernedInvocation("mutate", {"value": "x"}, task_id="t", step_id="s")
        fp = bound_action_fingerprint("mutate", {"value": "x"}, task_id="t", step_id="s")
        auth = issue_authorization(fp, "user", "now")
        self.assertEqual(reg.execute_guarded("mutate", authorization=auth, fingerprint=fp,
                                             invocation=invocation, value="x"), "ok")
        self.assertEqual(calls, ["x"])

    def test_repeated_actions_emit_stall_and_stop(self):
        from core.agent_loop import run_agent
        replies = iter([
            '{"actions":[{"tool":"shell_which","arguments":{"command":"python"}}],"final":null}',
            '{"actions":[{"tool":"shell_which","arguments":{"command":"python"}}],"final":null}',
            '{"actions":[{"tool":"shell_which","arguments":{"command":"python"}}],"final":null}',
        ])
        events = []
        with patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"), \
             patch("core.agent_loop.registry.execute", return_value="python"):
            result = run_agent("inspect", lambda _: next(replies), event_callback=lambda e, d: events.append(e))
        self.assertIn("repeated identical", result)
        self.assertIn("stalled", events)

    def test_durable_approval_binds_fresh_state(self):
        from core.task_store import TaskStore
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "tasks.json")
            task = store.create("edit", {})
            pending = store.request_approval(task["id"], {"fingerprint": "a" * 64,
                                                              "state_binding": "before"})
            store.approve_action(task["id"], "a" * 64)
            self.assertFalse(store.consume_action_approval(task["id"], "a" * 64, "changed"))
            self.assertTrue(store.consume_action_approval(task["id"], "a" * 64, "before"))

    def test_authorization_is_bound_to_task_and_step(self):
        a = bound_action_fingerprint("x", {}, task_id="t1", step_id="s1")
        self.assertNotEqual(a, bound_action_fingerprint("x", {}, task_id="t2", step_id="s1"))
        self.assertNotEqual(a, bound_action_fingerprint("x", {}, task_id="t1", step_id="s2"))

    def test_caller_cannot_downgrade_mutation(self):
        reg = ToolRegistry()
        called = []
        reg.register("mutate", "mutation", False, lambda: called.append(True))
        result = reg.execute_guarded("mutate", requires_authorization=False)
        self.assertIn("authorization", result)
        self.assertEqual(called, [])

    def test_model_governance_fields_are_rejected(self):
        from core.agent_loop import run_agent
        events = []
        with patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"):
            run_agent("inspect", lambda _: '{"actions":[{"tool":"list_dir","arguments":{"path":".","approval_id":"x"}}],"final":null}', event_callback=lambda e, d: events.append(e))
        self.assertIn("schema_error", events)
