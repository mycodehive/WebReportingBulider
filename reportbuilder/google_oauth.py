"""Google Sheets read-only authorization; tokens stay on the server."""
import base64
import hashlib
import json
import re
import secrets
import time
from datetime import timedelta
from functools import wraps
from urllib.parse import urlencode, urlsplit, parse_qs

import httpx
from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST, require_GET

from .data import DataError
from .models import Connection, GoogleOAuthApp

SCOPE = 'https://www.googleapis.com/auth/spreadsheets.readonly'
TOKEN_URL = 'https://oauth2.googleapis.com/token'


def active_session(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_active or request.headers.get('Authorization'):
            raise PermissionDenied
        response = view(request, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        response['Referrer-Policy'] = 'no-referrer'
        return response
    return wrapped


def credentials(connection):
    if not connection.encrypted_secrets:
        return {}
    return json.loads(Fernet(settings.REPORT_SECRET_KEY.encode()).decrypt(connection.encrypted_secrets.encode()))


def token_request(data):
    try:
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            with client.stream('POST', TOKEN_URL, data=data) as response:
                if response.status_code != 200:
                    raise ValueError
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 65536:
                        raise ValueError
        result = json.loads(raw)
        if not isinstance(result.get('access_token'), str) or not result['access_token']:
            raise ValueError
        expiry = int(result.get('expires_in', 3600))
        if not 1 <= expiry <= 86400 or result.get('token_type', '').lower() != 'bearer':
            raise ValueError
        if 'scope' in result and SCOPE not in result['scope'].split():
            raise ValueError
        return result
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise DataError('GOOGLE_AUTH_REQUIRED', 'Google 인증이 만료되었거나 실패했습니다. Google 인증을 다시 진행하세요.') from None


@transaction.atomic
def access_token(connection):
    locked = Connection.objects.select_for_update().get(pk=connection.pk)
    secret = credentials(locked)
    app = GoogleOAuthApp.objects.filter(owner=locked.owner).first()
    if not app or secret.get('oauth_client_id') != app.client_id or not secret.get('refresh_token'):
        raise DataError('GOOGLE_AUTH_REQUIRED', '연결 목록에서 Google 인증을 진행하세요.')
    if secret.get('access_token') and secret.get('expires_at', 0) > time.time() + 60:
        return secret['access_token']
    result = token_request({'grant_type': 'refresh_token', 'refresh_token': secret['refresh_token'],
                            'client_id': app.client_id, 'client_secret': app.secret()})
    secret.update(access_token=result['access_token'], expires_at=time.time()+int(result.get('expires_in', 3600)))
    if result.get('refresh_token'):
        secret['refresh_token'] = result['refresh_token']
    locked.set_secrets(secret)
    locked.save(update_fields=['encrypted_secrets'])
    return secret['access_token']


def sheet_config(post):
    value = post.get('sheet_url', '').strip()
    gid = '0'
    if value.startswith('https://'):
        parsed = urlsplit(value)
        match = re.fullmatch(r'/spreadsheets/(?:u/\d+/)?d/([A-Za-z0-9_-]{8,200})(?:/.*)?', parsed.path)
        if parsed.netloc != 'docs.google.com' or not match:
            raise ValueError('Google Sheets 주소를 확인하세요.')
        value = match[1]
        gid = parse_qs(parsed.fragment).get('gid', parse_qs(parsed.query).get('gid', ['0']))[0]
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,200}', value) or not re.fullmatch(r'\d{1,20}', gid):
        raise ValueError('스프레드시트 ID 또는 gid가 올바르지 않습니다.')
    mode = post.get('sheet_auth_mode', 'public')
    if mode not in {'public', 'oauth'}:
        raise ValueError('연결 방식을 확인하세요.')
    header = int(post.get('sheet_header', '1'))
    if mode == 'public' and header != 1:
        raise ValueError('공개 시트의 헤더는 첫 행이어야 합니다.')
    if not 1 <= header <= 10000:
        raise ValueError('헤더 행을 확인하세요.')
    return {'spreadsheet_id': value, 'gid': gid, 'sheet': post.get('sheet_tab', '').strip()[:200],
            'auth_mode': mode, 'header_row': header}


@active_session
@require_http_methods(['GET', 'POST'])
def setup(request):
    app = GoogleOAuthApp.objects.filter(owner=request.user).first()
    if request.method == 'POST':
        client_id = request.POST.get('client_id', '').strip()
        secret = request.POST.get('client_secret', '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]+\.apps\.googleusercontent\.com', client_id) or (not secret and not app) or len(secret) > 4096:
            messages.error(request, 'Client ID와 Client Secret을 확인하세요.')
        elif app and app.client_id != client_id and not secret:
            messages.error(request, 'Client ID 변경 시 새 Client Secret도 입력하세요.')
        else:
            app = app or GoogleOAuthApp(owner=request.user)
            app.client_id = client_id
            if secret:
                app.set_secret(secret)
            app.save()
            messages.success(request, 'OAuth 설정을 저장했습니다. 연결 목록에서 Google 인증을 진행하세요.')
            return redirect('connections')
    return render(request, 'reportbuilder/google_oauth_setup.html', {
        'oauth_app': app, 'callback_url': request.build_absolute_uri(reverse('google_oauth_callback'))})


@active_session
@require_POST
def start(request, connection_id):
    connection = get_object_or_404(Connection, pk=connection_id, owner=request.user, kind__in=['sheets', 'google_sheets'])
    if connection.config.get('auth_mode') != 'oauth':
        raise PermissionDenied
    app = GoogleOAuthApp.objects.filter(owner=request.user).first()
    if not app:
        messages.info(request, '먼저 Google OAuth 설정을 등록하세요.')
        return redirect('google_oauth_setup')
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    connection.config['oauth_attempt'] = hashlib.sha256(state.encode()).hexdigest()
    connection.save(update_fields=['config'])
    callback = request.build_absolute_uri(reverse('google_oauth_callback'))
    request.session['google_oauth'] = {'state': state, 'verifier': verifier, 'connection': str(connection.pk),
        'user': str(request.user.pk), 'client_id': app.client_id, 'app_version': app.updated_at.isoformat(),
        'callback': callback, 'expires': time.time()+600}
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    return redirect('https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
        'client_id': app.client_id, 'redirect_uri': callback, 'response_type': 'code', 'scope': SCOPE,
        'access_type': 'offline', 'prompt': 'consent', 'state': state,
        'code_challenge': challenge, 'code_challenge_method': 'S256'}))


@active_session
@require_GET
def callback(request):
    pending = request.session.pop('google_oauth', None)
    if (not pending or pending['user'] != str(request.user.pk) or pending['expires'] <= time.time()
            or not isinstance(request.GET.get('state'), str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{40,64}', request.GET.get('state', ''))
            or not secrets.compare_digest(pending['state'], request.GET.get('state', ''))):
        messages.error(request, '인증 요청이 만료되었거나 일치하지 않습니다. 다시 시작하세요.')
        return redirect('connections')
    if request.GET.get('error') or not request.GET.get('code'):
        messages.info(request, 'Google 인증이 취소되었습니다.')
        return redirect('connections')
    connection = get_object_or_404(Connection, pk=pending['connection'], owner=request.user)
    app = GoogleOAuthApp.objects.filter(owner=request.user, client_id=pending['client_id']).first()
    if not app or app.updated_at.isoformat() != pending['app_version']:
        messages.error(request, 'OAuth 설정이 변경되었습니다. 인증을 다시 시작하세요.')
        return redirect('connections')
    if connection.config.get('auth_mode') != 'oauth' or connection.config.get('oauth_attempt') != hashlib.sha256(pending['state'].encode()).hexdigest():
        messages.error(request, '인증 요청이 해제되거나 갱신되었습니다. 다시 시작하세요.')
        return redirect('connections')
    try:
        result = token_request({'grant_type': 'authorization_code', 'code': request.GET['code'],
            'redirect_uri': pending['callback'], 'code_verifier': pending['verifier'],
            'client_id': app.client_id, 'client_secret': app.secret()})
        if not isinstance(result.get('refresh_token'), str) or not result['refresh_token']:
            raise DataError('GOOGLE_AUTH_REQUIRED', '오프라인 권한을 받지 못했습니다. Google 인증을 다시 진행하세요.')
        secret = {'access_token': result['access_token'], 'refresh_token': result['refresh_token'],
                  'expires_at': (timezone.now()+timedelta(seconds=int(result.get('expires_in', 3600)))).timestamp(),
                  'oauth_client_id': app.client_id}
        with transaction.atomic():
            current_app = GoogleOAuthApp.objects.select_for_update().filter(owner=request.user).first()
            connection = Connection.objects.select_for_update().get(pk=connection.pk)
            if (not current_app or current_app.client_id != pending['client_id']
                    or current_app.updated_at.isoformat() != pending['app_version']
                    or connection.config.get('oauth_attempt') != hashlib.sha256(pending['state'].encode()).hexdigest()):
                raise DataError('GOOGLE_AUTH_REQUIRED', '인증을 다시 시작하세요.')
            connection.config.pop('oauth_attempt', None)
            connection.set_secrets(secret)
            connection.status = 'AUTHORIZED'
            connection.save(update_fields=['encrypted_secrets', 'status', 'config'])
        messages.success(request, 'Google 인증을 완료했습니다. 연결 테스트로 시트 접근 권한을 확인하세요.')
    except DataError:
        messages.error(request, 'Google 인증에 실패했습니다. OAuth 설정과 승인 권한을 확인하고 다시 시도하세요.')
    return redirect('connections')


@active_session
@require_POST
@transaction.atomic
def disconnect(request, connection_id):
    connection = get_object_or_404(Connection.objects.select_for_update(), pk=connection_id, owner=request.user,
                                   kind__in=['sheets', 'google_sheets'])
    if connection.config.get('auth_mode') != 'oauth':
        raise PermissionDenied
    connection.config.pop('oauth_attempt', None)
    connection.set_secrets({})
    connection.status = 'UNTESTED'
    connection.save(update_fields=['encrypted_secrets', 'status', 'config'])
    request.session.pop('google_oauth', None)
    messages.success(request, '이 연결의 저장된 Google 인증을 삭제했습니다. Google 계정의 앱 권한은 계정 설정에서 해제할 수 있습니다.')
    return redirect('connections')
