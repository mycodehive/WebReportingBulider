"""Exercise CSV string fields through the actual designer and chart API."""
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.management import call_command

from reportbuilder.models import Report


@pytest.mark.django_db(transaction=True)
def test_csv_numeric_strings_and_invalid_strings_in_designer(client, monkeypatch, settings, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setenv('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')
    settings.MEDIA_ROOT = tmp_path
    user = get_user_model().objects.create_user('csv-chart-member')
    call_command('seed_demo', user_id=str(user.pk), verbosity=0)
    report = Report.objects.get(owner=user, name='매출 현황 예제')
    for field in report.definition['datasets'][0]['fields']:
        field['type'] = 'string'
    report.bindings[0]['field_mappings']['amount']['conversion'] = 'identity'
    report.save(update_fields=['definition', 'bindings'])
    client.force_login(user)
    calls = []

    def serve(route):
        req = route.request
        path = urlparse(req.url).path
        if path.startswith('/static/'):
            asset = finders.find(path.removeprefix('/static/'))
            route.fulfill(body=Path(asset).read_bytes(), content_type=mimetypes.guess_type(path)[0])
            return
        method = req.method.lower()
        if method == 'get':
            response = client.get(path)
        else:
            response = getattr(client, method)(path, data=req.post_data_buffer or b'',
                                               content_type=req.headers.get('content-type', 'application/json'))
        if path.endswith('/infographic-data/'):
            calls.append((req.post_data, response.status_code))
        data = b''.join(response.streaming_content) if response.streaming else response.content
        route.fulfill(status=response.status_code, body=data,
                      content_type=response.get('Content-Type', 'text/html'))

    with playwright.sync_playwright() as api:
        browser = api.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_EXECUTABLE_PATH'))
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.route('http://testserver/**', serve)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        shots = Path('test-results/infographics')
        shots.mkdir(parents=True, exist_ok=True)
        page.goto(f'http://testserver/reports/{report.pk}/design/')
        page.wait_for_load_state('networkidle')
        page.get_by_role('tab', name='인포그래픽', exact=True).click()
        page.locator('#infographic-source').select_option('dataset')
        playwright.expect(page.locator('#infographic-value option[value="amount"]')).to_have_text('금액 (문자열 → 숫자변환)')
        page.locator('#infographic-label').select_option('department')
        page.locator('#infographic-value').select_option('amount')
        for theme in ('light', 'dark'):
            page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
            page.locator('#infographic-generate').click()
            playwright.expect(page.locator('#infographic-insert')).to_be_enabled()
            playwright.expect(page.locator('#infographic-preview')).to_be_visible()
            page.screenshot(path=str(shots / f'csv-{theme}.png'))
        page.locator('#infographic-insert').click()
        playwright.expect(page.locator('#infographic-status')).to_contain_text('캔버스에 추가했습니다')
        page.locator('#save').click()
        playwright.expect(page.locator('#save-state')).to_contain_text('저장됨 · 버전')
        report.refresh_from_db()
        assert any(e['type'] == 'image' for p in report.definition['pages'] for b in p['bands'] for e in b['elements'])
        page.locator('#infographic-value').select_option('customer')
        page.locator('#infographic-generate').click()
        playwright.expect(page.locator('#infographic-status')).to_contain_text('숫자가 아닌 값')
        assert calls[-1][1] == 400
        assert '"value_conversion":"to_decimal"' in calls[0][0]
        assert not errors
        browser.close()
