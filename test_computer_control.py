import unittest
from unittest.mock import Mock, patch
from core.computer_control import ComputerController, computer_input, invoking_task
from core.verification import build_requirement, verify_requirement

class ComputerTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.backend.stopped.return_value = False
        self.backend.capture.return_value = (b"pixels", 100, 80, 123)
        self.now = 1
        self.controller = ComputerController(self.backend, lambda: self.now)

    def observe(self):
        self.controller.enable("task", vision_model="test-vision")
        return self.controller.observe("task")[0]["snapshot_id"]

    def test_disabled_and_other_tasks_cannot_capture(self):
        with self.assertRaises(PermissionError): self.controller.observe("task")
        self.controller.enable("task")
        with self.assertRaises(PermissionError): self.controller.observe("other")
        self.backend.capture.assert_not_called()

    def test_action_is_single_use(self):
        snapshot = self.observe()
        result = self.controller.act("task", snapshot, "click", x=5, y=6)
        self.assertFalse(result["goal_verified"])
        with self.assertRaises(PermissionError): self.controller.act("task", snapshot, "click")
        self.backend.act.assert_called_once()

    def test_changed_screen_and_expired_snapshot_block_input(self):
        snapshot = self.observe()
        self.backend.capture.return_value = (b"changed", 100, 80, 123)
        with self.assertRaises(PermissionError): self.controller.act("task", snapshot, "click")
        snapshot = self.observe()
        self.now += 61
        with self.assertRaises(PermissionError): self.controller.act("task", snapshot, "click")
        self.backend.act.assert_not_called()

    def test_expiry_and_stop_revoke_access(self):
        self.observe()
        self.now += 301
        with self.assertRaises(PermissionError): self.controller.observe("task")
        self.observe()
        self.controller.stop()
        with self.assertRaises(PermissionError): self.controller.observe("task")

    def test_escape_revokes_session(self):
        snapshot = self.observe()
        self.backend.stopped.return_value = True
        with self.assertRaises(PermissionError): self.controller.act("task", snapshot, "click")
        self.assertFalse(self.controller.status()["enabled"])
        self.backend.act.assert_not_called()

    def test_invalid_coordinates_and_key_are_rejected(self):
        snapshot = self.observe()
        for args in ({"action":"click", "x":100}, {"action":"key", "key":"win+r"},
                     {"action":"type", "text":"bad\ncommand"}, {"action":"scroll", "amount":11}):
            with self.assertRaises(ValueError): self.controller.act("task", snapshot, **args)
        self.backend.act.assert_not_called()

    def test_direct_tool_call_has_no_task_authority(self):
        snapshot = self.observe()
        with patch('core.computer_control.controller', self.controller):
            with self.assertRaises(PermissionError): computer_input(snapshot, 'click')

    def test_capability_is_only_for_computer_input_on_selected_task(self):
        from core.approval_policy import ApprovalPolicy, AutoApproveMode, ActionClass, ActionContext
        policy = ApprovalPolicy(AutoApproveMode.OFF)
        policy.issue_capability(task_id="one", allowed_classes=[ActionClass.COMPUTER_INPUT], max_uses=1)
        self.assertEqual(policy.evaluate(ActionContext("computer_input", task_id="two")).decision.value, "REQUIRE_USER")
        self.assertEqual(policy.evaluate(ActionContext("shell_exec", {"command":"echo hi"}, task_id="one")).decision.value, "REQUIRE_USER")
        self.assertEqual(policy.evaluate(ActionContext("computer_input", task_id="one")).decision.value, "AUTO_APPROVE")
        self.assertEqual(policy.evaluate(ActionContext("computer_input", task_id="one")).decision.value, "REQUIRE_USER")

    def test_controller_action_budget_cannot_be_bypassed_by_capabilities(self):
        snapshot = self.observe()
        self.controller.remaining_actions = 0
        with self.assertRaises(PermissionError): self.controller.act("task", snapshot, "click")
        self.backend.act.assert_not_called()

    def test_computer_input_never_claims_verified_goal(self):
        req = build_requirement('computer_input', {}, 'fingerprint', 'task', 'step')
        record = verify_requirement(req, 'task', 'step', 'fingerprint')
        self.assertEqual(record.status.value, 'unavailable')

    def test_vision_failure_invalidates_snapshot(self):
        self.controller.enable('task', vision_model='test-vision')
        token = invoking_task.set('task')
        try:
            from core.computer_control import computer_observe
            with patch('core.computer_control.controller', self.controller), patch('spellbook.llm_client.chat', return_value='Vaelor archive connection error: offline'):
                with self.assertRaises(RuntimeError): computer_observe()
            self.assertIsNone(self.controller.snapshot)
        finally:
            invoking_task.reset(token)

class ComputerApiTests(unittest.TestCase):
    def setUp(self):
        import api.server as server
        from conftest import SynchronousASGIClient
        self.server = server
        self.client = SynchronousASGIClient(server.app)

    def tearDown(self):
        self.client.close()

    def test_enable_requires_explicit_ui_header_and_same_origin(self):
        body = {"task_id":"task", "vision_model":"test-vision"}
        self.assertEqual(self.client.post('/computer/enable', json=body).status_code, 403)
        self.assertEqual(self.client.post('/computer/enable', json=body,
            headers={"X-Vaelor-Computer":"1", "Origin":"https://evil.invalid"}).status_code, 403)

    def test_enable_binds_task_and_stop_revokes(self):
        backend = Mock()
        controller = ComputerController(backend)
        with patch('core.computer_control.controller', controller), patch.object(self.server.brain.tasks, 'get', return_value={"id":"task"}):
            response = self.client.post('/computer/enable', json={"task_id":"task", "vision_model":"test-vision"}, headers={"X-Vaelor-Computer":"1"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['task_id'], 'task')
            self.assertTrue(controller.status()['enabled'])
            response = self.client.post('/computer/stop', headers={"X-Vaelor-Computer":"1"})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(controller.status()['enabled'])

if __name__ == '__main__': unittest.main()
