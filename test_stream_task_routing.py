import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from fastapi.testclient import TestClient
from api import server
from core.brain import VaelorBrain


@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('clarification', [False, True])
def test_chat_transports_share_task_routing(streaming, clarification):
    brain = object.__new__(VaelorBrain)
    contract = SimpleNamespace(needs_clarification=clarification, clarification_question='Which folder?', should_act=True)
    brain.understand_task = Mock(return_value=contract)
    brain.act = Mock(return_value='Task finished')
    brain.preferences = Mock()
    brain.conversations = Mock()
    with patch('core.brain.cast_spell_stream', side_effect=AssertionError('must execute, not converse')):
        result = ''.join(brain.think_stream('inspect folder', session_id='s')) if streaming else brain.think('inspect folder', session_id='s')
    assert result == ('Which folder?' if clarification else 'Task finished')
    brain.preferences.learn_explicit.assert_called_once_with('inspect folder')
    if clarification:
        brain.act.assert_not_called()
        brain.conversations.remember_turn.assert_called_once_with('inspect folder', 'Which folder?', session_id='s')
    else:
        brain.act.assert_called_once_with('inspect folder', session_id='s', task_contract=contract)


def test_explicit_agent_stream_failure_is_error_event_without_done():
    with patch.object(server, 'route_message', side_effect=RuntimeError('backend offline')):
        response = TestClient(server.app).post('/chat/stream', json={'message': 'agent: inspect folder', 'session_id': 's'})
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert events == [{'type': 'error', 'error': 'backend offline'}]


def test_explicit_agent_stream_preserves_session():
    with patch.object(server, 'route_message', return_value=('agent', 'Task finished')) as route:
        response = TestClient(server.app).post('/chat/stream', json={'message': 'agent: inspect folder', 'session_id': 's'})
    route.assert_called_once_with('agent: inspect folder', session_id='s', images=None)
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert [event['type'] for event in events] == ['token', 'done']
    assert events[-1]['session_id'] == 's'


@pytest.mark.parametrize('backend', ['ollama', 'openai'])
@pytest.mark.parametrize('complete', [False, True])
def test_stream_requires_completion_marker(backend, complete):
    from unittest.mock import MagicMock
    from spellbook import llm_client
    response = MagicMock()
    response.__enter__.return_value = response
    if backend == 'ollama':
        lines = [json.dumps({'message': {'content': 'hello'}})]
        if complete:
            lines.append('{"done":true}')
        stream = llm_client._ollama_stream
    else:
        lines = ['data:' + json.dumps({'choices': [{'delta': {'content': 'hello'}}]})]
        if complete:
            lines.append('data: [DONE]')
        stream = llm_client._openai_stream
    response.iter_lines.return_value = lines
    with patch.object(llm_client.requests, 'post', return_value=response):
        if complete:
            assert ''.join(stream('unused', 'model', [], 1)) == 'hello'
        else:
            with pytest.raises(llm_client.ModelConnectionError, match='before completion'):
                list(stream('unused', 'model', [], 1))


def test_failed_stream_does_not_save_partial_reply():
    from spellbook.llm_client import ModelConnectionError
    brain = object.__new__(VaelorBrain)
    brain._route_thought_task = Mock(return_value=None)
    brain._context_prefix = Mock(return_value='')
    brain._history_text = Mock(return_value='')
    brain._history_messages = Mock(return_value=[])
    brain.conversations = Mock()
    def interrupted(*args, **kwargs):
        yield 'partial reply'
        raise ModelConnectionError('stream interrupted')
    with patch('core.brain.cast_spell_stream', side_effect=interrupted):
        with pytest.raises(ModelConnectionError):
            list(brain.think_stream('hello', session_id='s', use_web=False))
    brain.conversations.remember_turn.assert_not_called()


def test_agent_model_requests_structured_protocol():
    from core.action_protocol import ACTION_RESPONSE_SCHEMA
    from spellbook import llm_client
    with patch.object(llm_client, 'chat', return_value='{}') as chat:
        VaelorBrain._agent_reply('task', 'core_reasoning')
    assert chat.call_args.kwargs['response_schema'] == ACTION_RESPONSE_SCHEMA
    assert chat.call_args.kwargs['schema_strict'] is False
    assert chat.call_args.kwargs['temperature'] == 0
