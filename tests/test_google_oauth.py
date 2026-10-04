import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from reportbuilder.data import introspect, _sheet_records, DataError
from reportbuilder.google_oauth import sheet_config
from reportbuilder.models import GoogleOAuthApp, Connection

pytestmark = pytest.mark.django_db


@pytest.fixture(params=[False, True], ids=["member", "staff"])
def setup(client, request):
    owner = get_user_model().objects.create_user(username='google-owner', is_staff=request.param)
    app = GoogleOAuthApp(owner=owner, client_id='123-test.apps.googleusercontent.com')
    app.set_secret('test-secret')
    app.save()
    connection = Connection.objects.create(owner=owner, kind='sheets', name='Private', config={'spreadsheet_id':'abcdefghijk', 'auth_mode':'oauth'})
    client.force_login(owner)
    return owner, app, connection


def begin(client, connection):
    response = client.post(f'/connections/{connection.pk}/google/start/')
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.url).query)
    assert query['code_challenge_method'] == ['S256']
    assert query['access_type'] == ['offline']
    return query['state'][0]


def test_authorize_refresh_and_disconnect(client, setup):
    owner, app, conn = setup
    state = begin(client, conn)
    with patch('reportbuilder.google_oauth.token_request', return_value={'access_token':'secret-access', 'refresh_token':'secret-refresh', 'expires_in':3600}):
        assert client.get('/connections/google/callback/', {'state':state, 'code':'test-code'}).status_code == 302
    conn.refresh_from_db()
    assert 'secret-refresh' not in conn.encrypted_secrets
    assert conn.runtime_config()['access_token'] == 'secret-access'
    with patch('reportbuilder.google_oauth.token_request') as exchange:
        client.get('/connections/google/callback/', {'state':state, 'code':'replay'})
        exchange.assert_not_called()
    from reportbuilder.google_oauth import credentials
    secret = credentials(conn)
    secret['expires_at'] = 0
    conn.set_secrets(secret)
    conn.save()
    with patch('reportbuilder.google_oauth.token_request', return_value={'access_token':'new-access','expires_in':3600}) as exchange:
        assert conn.runtime_config()['access_token'] == 'new-access'
        assert exchange.call_args.args[0]['grant_type'] == 'refresh_token'
    assert client.post(f'/connections/{conn.pk}/google/disconnect/').status_code == 302
    with pytest.raises(DataError):
        conn.runtime_config()


def test_state_expiry_permission_and_csrf(client, setup):
    owner, app, conn = setup
    begin(client, conn)
    with patch('reportbuilder.google_oauth.token_request') as exchange:
        client.get('/connections/google/callback/', {'state':'bad','code':'code'})
        client.get('/connections/google/callback/', {'state':'한글','code':'code'})
        exchange.assert_not_called()
    state = begin(client, conn)
    session = client.session
    pending = session['google_oauth']
    pending['expires'] = time.time()-1
    session['google_oauth'] = pending
    session.save()
    with patch('reportbuilder.google_oauth.token_request') as exchange:
        client.get('/connections/google/callback/', {'state':state,'code':'code'})
        exchange.assert_not_called()
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(owner)
    assert strict.post(f'/connections/{conn.pk}/google/start/').status_code == 403
    other = get_user_model().objects.create_user(username='other', is_staff=True)
    client.force_login(other)
    assert client.post(f'/connections/{conn.pk}/google/start/').status_code == 404
    other.is_staff = False
    other.save()
    assert client.get('/connections/google/oauth/').status_code == 200
    assert app.client_id not in client.get('/connections/google/oauth/').content.decode()
    assert client.post(f'/connections/{conn.pk}/google/start/').status_code == 404
    assert client.post(f'/connections/{conn.pk}/google/disconnect/').status_code == 404


def test_setup_hides_secret_and_parses_url(client, setup):
    owner, app, conn = setup
    response = client.get('/connections/google/oauth/')
    assert 'test-secret' not in response.content.decode()
    config = sheet_config({'sheet_url':'https://docs.google.com/spreadsheets/d/abcdefghijk/edit#gid=42', 'sheet_auth_mode':'public'})
    assert config['gid'] == '42'
    with pytest.raises(ValueError):
        sheet_config({'sheet_url':'https://evil.test/spreadsheets/d/abcdefghijk/edit'})


def test_oauth_setup_post_requires_csrf_and_saves_credentials(setup):
    owner, _, _ = setup
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(owner)
    strict.get('/connections/google/oauth/')
    csrf = strict.cookies['csrftoken'].value

    response = strict.post('/connections/google/oauth/', {
        'client_id': '123-test.apps.googleusercontent.com',
        'client_secret': 'new-secret',
    }, HTTP_X_CSRFTOKEN=csrf)

    assert response.status_code == 302
    configured = GoogleOAuthApp.objects.get(owner=owner)
    assert configured.client_id == '123-test.apps.googleusercontent.com'
    assert 'new-secret' not in configured.encrypted_secret
    assert configured.secret() == 'new-secret'


def test_public_sheet_without_authentication():
    config = {'spreadsheet_id':'abcdefghijk','auth_mode':'public','gid':'42'}
    with patch('reportbuilder.data._https_json', return_value='name,amount\nAlice,100\nBob,200\n') as request:
        schema = introspect('sheets', config)
        assert schema['objects'][0]['object'] == '공개 시트'
        assert request.call_args.args[1] == {}
        assert 'gid=42' in request.call_args.args[0]
        assert _sheet_records(config, '공개 시트', 1)[1] == [{'name':'Alice','amount':'100'}]


def test_disconnect_invalidates_pending_callback(client, setup):
    owner, app, conn = setup
    state = begin(client, conn)
    # Simulate a second logged-in browser keeping an old OAuth session.
    other = Client()
    other.force_login(owner)
    session = other.session
    session['google_oauth'] = client.session['google_oauth']
    session.save()
    client.post(f'/connections/{conn.pk}/google/disconnect/')
    with patch('reportbuilder.google_oauth.token_request') as exchange:
        other.get('/connections/google/callback/', {'state':state,'code':'code'})
        exchange.assert_not_called()


def test_token_endpoint_validates_response_and_redacts_errors():
    import httpx
    from reportbuilder.google_oauth import token_request, SCOPE
    original = httpx.Client
    def response(request):
        assert request.url == 'https://oauth2.googleapis.com/token'
        assert request.method == 'POST'
        return httpx.Response(200, json={'access_token':'sample', 'expires_in':3600, 'token_type':'Bearer', 'scope':SCOPE})
    with patch('reportbuilder.google_oauth.httpx.Client', side_effect=lambda **kw: original(transport=httpx.MockTransport(response), **kw)):
        assert token_request({'client_secret':'hidden'})['access_token'] == 'sample'
    def denied(request):
        return httpx.Response(400, json={'error':'invalid_grant', 'error_description':'hidden'})
    with patch('reportbuilder.google_oauth.httpx.Client', side_effect=lambda **kw: original(transport=httpx.MockTransport(denied), **kw)):
        with pytest.raises(DataError) as exc:
            token_request({'client_secret':'hidden'})
        assert 'hidden' not in str(exc.value)


def test_register_public_and_oauth_through_connection_form(client, setup):
    owner, app, conn = setup
    for mode in ('public', 'oauth'):
        response = client.post('/connections/', {'name':mode, 'kind':'sheets', 'sheet_url':'https://docs.google.com/spreadsheets/d/abcdefghijk/edit#gid=42', 'sheet_auth_mode':mode, 'sheet_header':'1', 'config':'not JSON'})
        assert response.status_code == 302
        assert Connection.objects.get(name=mode).config['auth_mode'] == mode


def test_public_sheet_declared_numeric_hint_preserves_existing_csv_values():
    import json
    from urllib.parse import parse_qs, urlsplit
    config = {'spreadsheet_id': 'abcdefghijk', 'auth_mode': 'public', 'sheet': '훈련일지'}
    response = {'status': 'ok', 'table': {'cols': [
        {'label': '코드', 'type': 'string'}, {'label': '거리(Km)', 'type': 'number'}], 'rows': []}}

    def fetch(url, *args, **kwargs):
        if parse_qs(urlsplit(url).query)['tqx'] == ['out:json']:
            return '/*O_o*/\ngoogle.visualization.Query.setResponse(' + json.dumps(response) + ');'
        return '코드,거리(Km)\n001,50.01\n002,62.48\n'

    with patch('reportbuilder.data._https_json', side_effect=fetch):
        schema = introspect('google_sheets', config)
        code, distance = schema['objects'][0]['columns']
        assert code['type'] == 'string' and 'suggested_type' not in code
        assert distance['type'] == 'string'  # Existing identity/string contracts remain valid.
        assert distance['source_type'] == 'number'
        assert distance['suggested_conversion'] == 'to_decimal'
        assert _sheet_records(config, '훈련일지', 1)[1][0] == {'코드': '001', '거리(Km)': '50.01'}
