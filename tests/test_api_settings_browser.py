"""Real settings forms and API hierarchy in both themes and screen sizes."""
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders

from reportbuilder.models import LLMConfiguration, SettingsSection


@pytest.mark.django_db(transaction=True)
def test_api_navigation_and_llm_forms(client, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setenv('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')
    client.force_login(get_user_model().objects.create_user('api-browser-admin', is_staff=True))
    section = SettingsSection.objects.get(key='api')

    def serve(route):
        req = route.request
        path = urlparse(req.url).path
        if path.startswith('/static/'):
            asset = finders.find(path.removeprefix('/static/'))
            route.fulfill(body=Path(asset).read_bytes(), content_type=mimetypes.guess_type(path)[0])
            return
        if req.method == 'POST':
            response = client.post(path, data=req.post_data, content_type='application/x-www-form-urlencoded')
        else:
            response = client.get(path)
        # Redirect requests bypass Playwright routes; follow via the real
        # Django client rather than sending the browser to a nonexistent host.
        if response.status_code == 302:
            response = client.get(response['Location'])
        route.fulfill(status=response.status_code, body=response.content, content_type='text/html')

    with playwright.sync_playwright() as api:
        browser = api.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_EXECUTABLE_PATH'))
        page = browser.new_page()
        page.route('http://testserver/**', serve)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        shots = Path('test-results/api-settings')
        shots.mkdir(parents=True, exist_ok=True)
        for width in (1440, 390):
            page.set_viewport_size({'width': width, 'height': 1000})
            for theme in ('light', 'dark'):
                page.goto(f'http://testserver/settings/sections/{section.pk}/')
                page.wait_for_load_state('networkidle')
                page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                playwright.expect(page.get_by_text('실험실에 열심히 개발중이에요')).to_be_visible()
                playwright.expect(page.locator('.settings-tabs [aria-current="page"]')).to_have_text('API')
                page.get_by_role('navigation', name='선택한 설정의 하위 메뉴').get_by_role('link', name='외부API').click()
                page.wait_for_load_state('networkidle')
                page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                playwright.expect(page.get_by_label('API 키', exact=True)).to_have_attribute('type', 'password')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(shots / f'{theme}-{width}.png'), full_page=True)
        page.get_by_label('연결명', exact=True).fill('브라우저 LLM')
        page.get_by_label('제공자', exact=True).select_option('compatible')
        page.get_by_label('모델명', exact=True).fill('test-model')
        page.get_by_label('API 기본 주소', exact=True).fill('https://llm.example.com/v1')
        page.get_by_label('API 키', exact=True).fill('browser-secret')
        page.get_by_role('button', name='LLM 설정 등록', exact=True).click()
        playwright.expect(page.get_by_role('heading', name='브라우저 LLM', exact=True)).to_be_visible()
        config = LLMConfiguration.objects.get(name='브라우저 LLM')
        assert config.api_key() == 'browser-secret'
        page.get_by_role('link', name='브라우저 LLM 수정').click()
        playwright.expect(page.get_by_label('API 키', exact=True)).to_have_value('')
        page.get_by_label('모델명', exact=True).fill('updated-model')
        page.get_by_role('button', name='변경사항 저장').click()
        playwright.expect(page.get_by_text('updated-model', exact=True)).to_be_visible()
        config.refresh_from_db()
        assert config.model == 'updated-model' and config.api_key() == 'browser-secret'
        page.on('dialog', lambda dialog: dialog.accept())
        page.get_by_role('button', name='브라우저 LLM 삭제').click()
        playwright.expect(page.get_by_text('등록된 LLM이 없습니다.', exact=False)).to_be_visible()
        assert not LLMConfiguration.objects.exists()
        assert not errors
        browser.close()
