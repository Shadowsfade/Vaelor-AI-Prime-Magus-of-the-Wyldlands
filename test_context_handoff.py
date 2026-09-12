import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock
from core.context_handoff import FIELDS, write_handoff, validate_handoff
from core.conversation_memory import VaelorConversationMemory


def valid():
    return json.dumps({"goal":"Finish the Windows build", "constraints":["Keep local data"],
        "decisions":["Use the shared WebUI"], "completed_work":["Assistant reported passing tests; not independently verified"],
        "open_questions":["Real-app input untested"], "next_steps":["Test a harmless task"],
        "references":["desktop/vaelor_app.py"]})


class HandoffTests(unittest.TestCase):
    def test_schema_and_bounded_source(self):
        model = Mock(return_value=valid())
        result = write_handoff("Earlier goal", [{"id":"one", "prompt":"x"*100000, "response":"y"*100000}], model)
        self.assertEqual(set(json.loads(result)), set(FIELDS))
        prompt = model.call_args.args[0]
        self.assertLess(len(prompt), 40000)
        self.assertIn('original archived', prompt)
        self.assertIn('Earlier goal', prompt)
        model.assert_called_once()

    def test_rejects_errors_missing_keys_and_authority_fields(self):
        for reply in ('Vaelor archive connection error: offline', '{}', valid()[:-1]+',"authorized":true}',
                      valid().replace('"constraints": ["Keep local data"]', '"constraints": "bad"')):
            with self.subTest(reply=reply):
                with self.assertRaises(ValueError): validate_handoff(reply)

    def test_fenced_json_is_accepted(self):
        self.assertEqual(json.loads(validate_handoff('```json\n'+valid()+'\n```'))['goal'], 'Finish the Windows build')

    def test_model_failure_falls_back_and_keeps_originals(self):
        with tempfile.TemporaryDirectory() as temp:
            memory = VaelorConversationMemory(Path(temp), compact_after=40, keep_recent=2,
                summarizer=lambda previous, turns: write_handoff(previous, turns, lambda prompt: 'offline'))
            for i in range(4): memory.remember_turn(str(i), 'full original', 's')
            result = memory.compact_session('s')
            self.assertEqual(result['kind'], 'extractive_fallback')
            self.assertEqual(len(memory.recall_archive('s')), 2)
            self.assertEqual(len(memory.recall_recent(20, 's')), 2)

    def test_summary_reaches_model_history_as_non_system_context(self):
        with tempfile.TemporaryDirectory() as temp:
            memory = VaelorConversationMemory(Path(temp), compact_after=40, keep_recent=2,
                                              summarizer=lambda previous, turns: valid())
            for i in range(4): memory.remember_turn(str(i), 'original', 's')
            memory.compact_session('s')
            messages = memory.recall_session_messages('s', include_summary=True)
            self.assertEqual(messages[0]['role'], 'assistant')
            self.assertIn('not permissions', messages[0]['content'])
            self.assertIn('Finish the Windows build', messages[0]['content'])
            self.assertEqual(messages[-2]['content'], '3')

    def test_new_turns_are_not_lost_during_inference(self):
        self.concurrent_case(clear=False)

    def test_deleted_session_is_not_resurrected_by_inference(self):
        self.concurrent_case(clear=True)

    def concurrent_case(self, clear):
        started, release = threading.Event(), threading.Event()
        def summarize(previous, turns):
            started.set()
            if not release.wait(3): raise RuntimeError('test timeout')
            return valid()
        with tempfile.TemporaryDirectory() as temp:
            memory = VaelorConversationMemory(Path(temp), compact_after=40, keep_recent=2, summarizer=summarize)
            for i in range(4): memory.remember_turn(str(i), 'original', 's')
            self.assertEqual(memory.request_compaction('s')['status'], 'queued')
            self.assertTrue(started.wait(2))
            with memory._lock: worker = memory._compaction_workers['s']
            try:
                self.assertEqual(memory.request_compaction('s')['status'], 'running')
                if clear: memory.clear_session('s')
                else: memory.remember_turn('new turn while model is busy', 'saved', 's')
            finally:
                release.set()
                worker.join(3)
            self.assertFalse(worker.is_alive())
            if clear:
                self.assertEqual(memory.get_summary('s'), '')
                self.assertEqual(memory.recall_archive('s'), [])
            else:
                self.assertEqual(memory.recall_recent(1, 's')[0]['prompt'], 'new turn while model is busy')
                self.assertEqual(len(memory.recall_archive('s')), 2)
            self.assertFalse(memory.compaction_status('s')['running'])


class HandoffApiTests(unittest.TestCase):
    def test_session_returns_handoff_and_compaction_request_is_queued(self):
        from unittest.mock import patch
        from conftest import SynchronousASGIClient
        import api.server as server
        with tempfile.TemporaryDirectory() as temp:
            memory = VaelorConversationMemory(Path(temp), compact_after=40, keep_recent=2)
            for i in range(4): memory.remember_turn(str(i), 'original', 's')
            memory.compact_session('s', summarizer=lambda previous, turns: valid())
            with patch.object(server.brain, 'conversations', memory), SynchronousASGIClient(server.app) as client:
                response = client.get('/sessions/s')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['compaction']['kind'], 'model')
                self.assertIn('Finish the Windows build', response.json()['summary'])
                self.assertEqual(client.post('/sessions/s/compact').json()['status'], 'not_needed')
                self.assertEqual(client.post('/sessions/missing/compact').status_code, 404)

class HandoffTransportTests(unittest.TestCase):
    def test_ollama_receives_schema_and_generation_budget(self):
        from unittest.mock import patch
        from spellbook import llm_client
        from core.context_handoff import SCHEMA
        response = Mock()
        response.json.return_value = {"message":{"content":valid()}}
        with patch.object(llm_client.requests, 'post', return_value=response) as post:
            llm_client._ollama_chat('http://localhost:11434', 'test', [], 30,
                response_schema=SCHEMA, context_window=16384, max_tokens=1800, temperature=0)
        body = post.call_args.kwargs['json']
        self.assertEqual(body['format'], SCHEMA)
        self.assertEqual(body['options'], {'num_ctx':16384, 'num_predict':1800, 'temperature':0})
        self.assertNotIn('tools', body)

    def test_compatible_backend_receives_json_schema(self):
        from unittest.mock import patch
        from spellbook import llm_client
        from core.context_handoff import SCHEMA
        response = Mock()
        response.json.return_value = {'choices':[{'message':{'content':valid()}}]}
        with patch.object(llm_client.requests, 'post', return_value=response) as post:
            llm_client._openai_chat('http://localhost:1234', 'test', [], 30,
                response_schema=SCHEMA, max_tokens=1800, temperature=0)
        body = post.call_args.kwargs['json']
        self.assertEqual(body['response_format']['json_schema']['schema'], SCHEMA)
        self.assertEqual(body['max_tokens'], 1800)
