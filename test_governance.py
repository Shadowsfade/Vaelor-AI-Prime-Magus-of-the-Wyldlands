import unittest
from unittest.mock import patch

from core.governance import (ActionAuthorization, EvidenceProvenance,
                              EvidenceSource, bound_action_fingerprint,
                              mutation_supported)
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
        fp = "f" * 64
        auth = ActionAuthorization(fp, "user", "now")
        self.assertEqual(reg.execute_guarded("mutate", authorization=auth, fingerprint=fp, value="x"), "ok")
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
