import json
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from reportbuilder import data, llm_models


@pytest.mark.parametrize('provider,base,header,payload', [
    ('openai', 'https://api.openai.com/v1', 'Authorization', {'data': [{'id': 'chat-model'}]}),
    ('anthropic', 'https://api.anthropic.com/v1', 'x-api-key', {'data': [{'id': 'claude-test', 'display_name': 'Claude Test'}]}),
    ('gemini', 'https://generativelanguage.googleapis.com/v1beta', 'x-goog-api-key', {'models': [
        {'name': 'models/gemini-test', 'displayName': 'Gemini Test', 'supportedGenerationMethods': ['generateContent']},
        {'name': 'models/embed-test', 'supportedGenerationMethods': ['embedContent']}]}),
    ('openrouter', 'https://openrouter.ai/api/v1', 'Authorization', {'data': [{'id': 'vendor/chat-model'}]}),
    ('compatible', 'https://llm.example.com/v1', 'Authorization', {'data': [{'id': 'custom-model'}]}),
])
def test_model_discovery_real_http_validation(monkeypatch, settings, provider, base, header, payload):
    settings.REPORT_LLM_ALLOWED_HOSTS = ['llm.example.com']
    monkeypatch.setattr(data.socket, 'getaddrinfo', lambda *a, **kw: [(2, 1, 6, '', ('8.8.8.8', 443))])
    response = Mock(status=200)
    response.read.return_value = json.dumps(payload).encode()
    conn = Mock()
    conn.getresponse.return_value = response
    factory = Mock(return_value=conn)
    monkeypatch.setattr(data, '_PinnedHTTPS', factory)
    result = llm_models.list_models(provider, base, 'secret-test-key')
    assert len(result) == 1
    factory.assert_called_once_with(urlsplit(base).hostname, '8.8.8.8', 443)
    method, target = conn.request.call_args.args
    headers = conn.request.call_args.kwargs['headers']
    assert method == 'GET' and urlsplit(target).path.endswith('/models')
    assert 'secret-test-key' in headers[header]
    assert 'secret-test-key' not in target
    response.read.assert_called_once_with(2 * 1024 * 1024 + 1)
    conn.close.assert_called_once()


@pytest.mark.parametrize('provider,pages,expected_query', [
    ('anthropic', [{'data': [{'id': 'a'}], 'has_more': True, 'last_id': 'a'}, {'data': [{'id': 'b'}], 'has_more': False}], 'after_id'),
    ('gemini', [{'models': [{'name': 'models/a', 'supportedGenerationMethods': ['generateContent']}], 'nextPageToken': 'next'},
                {'models': [{'name': 'models/b', 'supportedGenerationMethods': ['generateContent']}]}], 'pageToken'),
])
def test_models_follow_only_bounded_cursors(monkeypatch, provider, pages, expected_query):
    fetch = Mock(side_effect=pages)
    monkeypatch.setattr(llm_models, '_https_json', fetch)
    result = llm_models.list_models(provider, llm_models.PROVIDER_BASE_URLS[provider], 'secret-test-key')
    assert [item['id'] for item in result] == ['a', 'b']
    assert expected_query in parse_qs(urlsplit(fetch.call_args.args[0]).query)


@pytest.mark.parametrize('provider,url', [
    ('openai', 'https://evil.example/v1'), ('openai', 'https://api.openai.com/v1/../private'),
    ('compatible', 'http://llm.example.com/v1'), ('compatible', 'https://user:key@llm.example.com/v1'),
    ('compatible', 'https://llm.example.com:8443/v1'), ('compatible', 'https://llm.example.com/v1?key=secret'),
    ('compatible', 'https://llm.example.com/v1#secret'), ('compatible', 'https://evil.example/v1'),
])
def test_untrusted_destination_rejected_before_network(monkeypatch, settings, provider, url):
    settings.REPORT_LLM_ALLOWED_HOSTS = ['llm.example.com']
    fetch = Mock()
    monkeypatch.setattr(llm_models, '_https_json', fetch)
    with pytest.raises(data.DataError):
        llm_models.list_models(provider, url, 'secret-test-key')
    fetch.assert_not_called()


@pytest.mark.parametrize('ip', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1'])
def test_even_allowed_host_cannot_resolve_to_private_network(monkeypatch, settings, ip):
    settings.REPORT_LLM_ALLOWED_HOSTS = ['llm.example.com']
    monkeypatch.setattr(data.socket, 'getaddrinfo', lambda *a, **kw: [(2, 1, 6, '', (ip, 443))])
    transport = Mock()
    monkeypatch.setattr(data, '_PinnedHTTPS', transport)
    with pytest.raises(data.DataError):
        llm_models.list_models('compatible', 'https://llm.example.com/v1', 'secret-test-key')
    transport.assert_not_called()


@pytest.mark.parametrize('status', [301, 302, 401, 403, 429, 500])
def test_model_discovery_no_redirects_or_provider_error_leaks(monkeypatch, status):
    monkeypatch.setattr(data.socket, 'getaddrinfo', lambda *a, **kw: [(2, 1, 6, '', ('8.8.8.8', 443))])
    conn = Mock()
    conn.getresponse.return_value = Mock(status=status)
    monkeypatch.setattr(data, '_PinnedHTTPS', Mock(return_value=conn))
    with pytest.raises(data.DataError) as caught:
        llm_models.list_models('openai', llm_models.PROVIDER_BASE_URLS['openai'], 'secret-test-key')
    assert 'secret-test-key' not in str(caught.value)
    conn.getresponse.return_value.read.assert_not_called()
    assert conn.request.call_count == 1


@pytest.mark.parametrize('payload', [None, {'data': 'wrong'}, {'data': []},
                                       {'data': [{'id': 'secret-test-key'}]}, {'data': [{'id': '\ninvalid'}]}])
def test_invalid_or_reflected_model_metadata_is_not_forwarded(monkeypatch, payload):
    monkeypatch.setattr(llm_models, '_https_json', Mock(return_value=payload))
    with pytest.raises(data.DataError):
        llm_models.list_models('openai', llm_models.PROVIDER_BASE_URLS['openai'], 'secret-test-key')
