"""Exercise CSV string fields through the actual designer and chart API."""
import mimetypes
import os
import json
from urllib.parse import parse_qs
from pathlib import Path
from urllib.parse import urlparse

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders


from reportbuilder.models import Report, Connection, Project
from reportbuilder.definition import default_definition


@pytest.mark.django_db(transaction=True)
def test_public_sheet_numeric_column_becomes_number_dataset(client, monkeypatch, settings, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setenv('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')
    settings.MEDIA_ROOT = tmp_path
    user = get_user_model().objects.create_user('public-chart-member')
    connection = Connection.objects.create(owner=user, name='자전거여행 공개 시트', kind='google_sheets',
                                           config={'spreadsheet_id': 'abcdefghijk', 'auth_mode': 'public', 'sheet': '훈련일지'})
    project = Project.objects.create(owner=user, name='자전거여행')
    report = Report.objects.create(owner=user, project=project, name='자전거여행', definition=default_definition())
    def sheet_response(url, *args, **kwargs):
        if parse_qs(urlparse(url).query).get('tqx') == ['out:json']:
            return 'google.visualization.Query.setResponse(' + json.dumps({'status': 'ok', 'table': {
                'cols': [{'label': '시행일', 'type': 'string'}, {'label': '거리(Km)', 'type': 'number'}], 'rows': []}}) + ');'
        return '시행일,거리(Km)\n1일,50.01\n2일,62.48\n'
    monkeypatch.setattr('reportbuilder.data._https_json', sheet_response)
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
        page.locator('#connection-select').select_option(str(connection.pk))
        playwright.expect(page.locator('#object-select option')).to_have_count(2)
        page.locator('#object-select').select_option('0')
        page.locator('#add-dataset').click()
        playwright.expect(page.locator('#field-list')).to_contain_text('number')
        page.locator('#save').click()
        playwright.expect(page.locator('#save-state')).to_contain_text('저장됨 · 버전')
        report.refresh_from_db()
        distance = next(f for f in report.definition['datasets'][0]['fields'] if f['label'] == '거리(Km)')
        label = next(f for f in report.definition['datasets'][0]['fields'] if f['label'] == '시행일')
        assert distance['type'] == 'number'
        assert report.bindings[0]['field_mappings'][distance['field_id']]['conversion'] == 'to_decimal'
        page.get_by_role('tab', name='인포그래픽', exact=True).click()
        page.locator('#infographic-source').select_option('dataset')
        page.locator('#infographic-label').select_option(label['field_id'])
        page.locator('#infographic-value').select_option(distance['field_id'])
        for theme in ('light', 'dark'):
            page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
            page.locator('#infographic-generate').click()
            playwright.expect(page.locator('#infographic-insert')).to_be_enabled()
            playwright.expect(page.locator('#infographic-preview')).to_be_visible()
            page.screenshot(path=str(shots / f'public-{theme}.png'))
        assert calls[-1][1] == 200
        assert '"value_conversion":"identity"' in calls[0][0]
        assert not errors
        browser.close()
