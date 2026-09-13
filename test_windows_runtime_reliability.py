import json
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from desktop import vaelor_app
from spellbook import llm_client


def test_desktop_does_not_reuse_occupied_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert vaelor_app.select_desktop_port(port) != port
        with patch.object(vaelor_app.subprocess, 'Popen') as spawn:
            with pytest.raises(RuntimeError):
                vaelor_app.start_server(Path('.'), '127.0.0.1', port)
            spawn.assert_not_called()


def test_desktop_health_requires_own_instance():
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = json.dumps({'status': 'online', 'desktop_instance': 'other'}).encode()
    with patch.object(vaelor_app.urllib.request, 'urlopen', return_value=response), patch.object(vaelor_app.time, 'sleep'):
        assert not vaelor_app.wait_for_server('http://localhost', .01, 'mine')
        response.read.return_value = b'{"desktop_instance":"mine"}'
        assert vaelor_app.wait_for_server('http://localhost', .1, 'mine')


def test_model_outage_raises_instead_of_becoming_assistant_text():
    with patch.object(llm_client, 'get_backend_settings', return_value={'timeout': 1, 'ollama_url': 'unused'}), patch.object(llm_client, 'resolve_route', return_value={'provider': 'ollama', 'model': 'test'}), patch.object(llm_client, '_ollama_chat', side_effect=ConnectionError('offline')):
        with pytest.raises(llm_client.ModelConnectionError):
            llm_client.chat('hello')


@pytest.mark.parametrize('stream', [llm_client._ollama_stream, llm_client._openai_stream])
def test_stream_reports_backend_error(stream):
    response = MagicMock()
    response.__enter__.return_value = response
    response.iter_lines.return_value = [json.dumps({'error': 'model unavailable'})]
    with patch.object(llm_client.requests, 'post', return_value=response):
        with pytest.raises(llm_client.ModelConnectionError, match='model unavailable'):
            list(stream('http://unused', 'test', [], 1))


def test_chat_api_reports_outage_as_service_unavailable():
    from api import server
    from fastapi import HTTPException
    with patch.object(server, 'route_message', side_effect=llm_client.ModelConnectionError('offline')):
        with pytest.raises(HTTPException) as error:
            server.chat(server.ChatRequest(message='hello'))
    assert error.value.status_code == 503
