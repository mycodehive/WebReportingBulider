"""Bounded model discovery. Keys never appear in URLs, responses or tickets."""
import time
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.utils.crypto import salted_hmac

from .data import DataError, _https_json

PROVIDER_BASE_URLS = {
    'openai': 'https://api.openai.com/v1',
    'anthropic': 'https://api.anthropic.com/v1',
    'gemini': 'https://generativelanguage.googleapis.com/v1beta',
    'openrouter': 'https://openrouter.ai/api/v1',
}
MAX_MODELS = 5000


def credential_context(user, provider, base_url, api_key):
    return {'user': str(user.pk), 'provider': provider, 'base_url': base_url.rstrip('/'),
            'credential': salted_hmac('llm-model-catalog', api_key, algorithm='sha256').hexdigest()}


def validated_base_url(provider, base_url):
    parsed = urlsplit(base_url)
    try:
        port = parsed.port
    except ValueError:
        raise DataError('INVALID_CONFIG', 'API 주소의 포트가 올바르지 않습니다.') from None
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or port not in {None, 443}
            or any(ord(c) < 32 for c in base_url) or '\\' in base_url):
        raise DataError('UNSAFE_ENDPOINT', '올바른 HTTPS API 기본 주소를 입력하세요.')
    base_url = base_url.rstrip('/')
    if provider in PROVIDER_BASE_URLS:
        if base_url != PROVIDER_BASE_URLS[provider]:
            raise DataError('UNSAFE_ENDPOINT', '공식 제공자의 기본 주소를 사용하세요. 별도 서버는 OpenAI 호환 API로 선택하세요.')
    elif provider == 'compatible':
        if parsed.hostname.lower() not in settings.REPORT_LLM_ALLOWED_HOSTS:
            raise DataError('UNSAFE_ENDPOINT', '서버 관리자가 허용한 호환 API 호스트만 사용할 수 있습니다.')
    else:
        raise DataError('INVALID_CONFIG', '지원하는 LLM 제공자를 선택하세요.')
    return base_url


def list_models(provider, base_url, api_key):
    base_url = validated_base_url(provider, base_url)
    if not isinstance(api_key, str) or not api_key or len(api_key) > 4096 or any(ord(c) < 32 for c in api_key):
        raise DataError('AUTH_REQUIRED', '올바른 API 키를 입력하세요.')
    if provider == 'anthropic':
        headers = {'x-api-key': api_key, 'anthropic-version': '2023-06-01'}
        query = {'limit': 1000}
    elif provider == 'gemini':
        headers = {'x-goog-api-key': api_key}
        query = {'pageSize': 1000}
    else:
        headers = {'Authorization': 'Bearer ' + api_key}
        query = {}
    models, cursors = {}, set()
    deadline = time.monotonic() + 30
    for _ in range(5):
        if time.monotonic() > deadline:
            raise DataError('DATA_LIMIT', '모델 목록 조회 시간이 초과되었습니다. 잠시 후 다시 시도하세요.')
        endpoint = base_url + '/models' + ('?' + urlencode(query) if query else '')
        try:
            payload = _https_json(endpoint, headers, [urlsplit(base_url).hostname], max_response_bytes=2 * 1024 * 1024)
        except DataError as exc:
            if exc.code == 'REMOTE_ERROR':
                raise DataError('REMOTE_ERROR', '모델 목록을 불러오지 못했습니다. API 키 권한과 모델 목록 API 지원 여부를 확인하세요.') from None
            raise
        if not isinstance(payload, dict):
            raise DataError('INVALID_RESPONSE', '모델 목록 응답 형식이 올바르지 않습니다.')
        entries = payload.get('models' if provider == 'gemini' else 'data')
        if not isinstance(entries, list) or len(entries) > MAX_MODELS:
            raise DataError('INVALID_RESPONSE', '모델 목록 응답 형식이 올바르지 않습니다.')
        for entry in entries:
            if not isinstance(entry, dict):
                raise DataError('INVALID_RESPONSE', '모델 목록 응답 형식이 올바르지 않습니다.')
            if provider == 'gemini' and 'generateContent' not in entry.get('supportedGenerationMethods', []):
                continue
            model_id = entry.get('name' if provider == 'gemini' else 'id')
            if provider == 'gemini' and isinstance(model_id, str):
                model_id = model_id.removeprefix('models/')
            if not isinstance(model_id, str) or not model_id or len(model_id) > 200 or any(ord(c) < 32 for c in model_id):
                raise DataError('INVALID_RESPONSE', '모델 식별자가 올바르지 않습니다.')
            # Some providers reflect credentials in metadata. Never forward them.
            if api_key in model_id:
                raise DataError('INVALID_RESPONSE', '모델 목록 응답을 안전하게 처리할 수 없습니다.')
            label = entry.get('displayName') or entry.get('display_name') or entry.get('name') or model_id
            if not isinstance(label, str) or api_key in label:
                label = model_id
            models[model_id] = {'id': model_id, 'label': label[:200]}
        if len(models) > MAX_MODELS:
            raise DataError('DATA_LIMIT', '모델 목록이 허용 개수를 초과했습니다.')
        cursor = (payload.get('nextPageToken') if provider == 'gemini' else
                  payload.get('last_id') if provider == 'anthropic' and payload.get('has_more') else None)
        if provider == 'anthropic' and payload.get('has_more') and not cursor:
            raise DataError('INVALID_RESPONSE', '모델 목록의 다음 페이지 정보가 없습니다.')
        if not cursor:
            if not models:
                raise DataError('NO_MODELS', '선택 가능한 모델이 없습니다. API 키의 모델 조회 권한을 확인하세요.')
            return sorted(models.values(), key=lambda item: item['id'])
        if not isinstance(cursor, str) or len(cursor) > 2000 or cursor in cursors or api_key in cursor:
            raise DataError('INVALID_RESPONSE', '모델 목록의 다음 페이지 정보가 올바르지 않습니다.')
        cursors.add(cursor)
        query['pageToken' if provider == 'gemini' else 'after_id'] = cursor
    raise DataError('DATA_LIMIT', '모델 목록이 조회 한도를 초과했습니다. 제공자의 모델 목록 범위를 확인하세요.')
