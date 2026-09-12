import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from core.agent_loop import run_agent
from core.approval_policy import ApprovalPolicy, AutoApproveMode
from core.task_store import TaskStore

class ApprovalReplayTests(unittest.TestCase):
    def test_approved_second_step_replays_without_replanning(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_patch = patch("core.tools.fs_ops._load_autonomy", return_value={"allowed_roots":[str(root)]})
            config_patch.start()
            self.addCleanup(config_patch.stop)
            source, target = root/'source.txt', root/'target.txt'
            source.write_text('reference', encoding='utf-8')
            store = TaskStore(root/'tasks.json')
            task = store.create('write a file')
            task_id = task['id']
            store.claim(task_id, 'worker')
            def reply(tool, arguments):
                return json.dumps({'thought':'work', 'actions':[{'tool':tool,'arguments':arguments}], 'final':None})
            model = Mock(side_effect=[reply('file_reader', {'path':str(source)}),
                                      reply('write_text_file', {'path':str(target), 'content':'hello'})])
            common = dict(task_id=task_id, approval_policy=ApprovalPolicy(AutoApproveMode.OFF),
                approval_required=lambda action: store.request_approval(task_id, action),
                consume_approval=lambda fingerprint, state_binding=None, invocation=None:
                    store.consume_action_approval(task_id, fingerprint, state_binding, invocation))
            result = run_agent('write a file', model, **common)
            self.assertIn('WAITING_APPROVAL', result)
            pending = store.get(task_id)['pending_approval']
            self.assertEqual(pending['step_id'], '2')
            store.approve_action(task_id, pending['fingerprint'])
            saved = store.get(task_id)['authorized_invocation']
            resumed_model = Mock(return_value='FINAL_SUMMARY: SUCCESS File written')
            result = run_agent('write a file', resumed_model, resume_action=saved, **common)
            self.assertTrue(target.exists(), result)
            self.assertEqual(target.read_text(), 'hello')
            self.assertIn('SUCCESS', result)
            self.assertIsNone(store.get(task_id)['authorized_action'])
            self.assertEqual(resumed_model.call_count, 1)

    def test_replay_rejects_different_task(self):
        model = Mock()
        result = run_agent('goal', model, task_id='one', resume_action={
            'task_id':'two', 'step_id':'2', 'tool':'write_text_file', 'arguments':{}})
        self.assertIn('Invalid saved action', result)
        model.assert_not_called()

    def test_budget_summary_cannot_hide_tool_failure(self):
        model = Mock(side_effect=[json.dumps({"actions":[{"tool":"file_reader", "arguments":{"path":"does-not-exist-approval-replay.txt"}}], "final":None})] + ['FINAL_SUMMARY: SUCCESS done'] * 3)
        result = run_agent('read the missing file', model, max_steps=3)
        self.assertIn('FAILED', result)
