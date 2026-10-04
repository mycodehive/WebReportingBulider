import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders


@pytest.mark.django_db(transaction=True)
def test_mail_forms_themes_and_provider_switch(client, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setenv('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')
    client.force_login(get_user_model().objects.create_user('mail-browser', is_staff=True))

    def serve(route):
        req = route.request
        path = urlparse(req.url).path
        if path.startswith('/static/'):
            asset = finders.find(path.removeprefix('/static/'))
            route.fulfill(body=Path(asset).read_bytes(), content_type=mimetypes.guess_type(path)[0])
            return
        response = (client.post(path, data=req.post_data_buffer, content_type=req.headers.get('content-type', 'application/x-www-form-urlencoded'))
                    if req.method == 'POST' else client.get(path))
        if response.status_code == 302:
            response = client.get(response['Location'])
        route.fulfill(status=response.status_code, body=response.content, content_type=response.get('Content-Type', 'text/html'))

    with playwright.sync_playwright() as api:
        browser = api.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_EXECUTABLE_PATH'))
        page = browser.new_page()
        page.route('http://testserver/**', serve)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        shots = Path('test-results/mail-settings')
        shots.mkdir(parents=True, exist_ok=True)
        for width in (1440, 390):
            page.set_viewport_size({'width': width, 'height': 1100})
            for theme in ('light', 'dark'):
                page.goto('http://testserver/settings/mail/')
                page.wait_for_load_state('networkidle')
                page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                playwright.expect(page.locator('.settings-submenu [aria-current="page"]')).to_have_text('메일')
                playwright.expect(page.get_by_role('button', name='테스트 발송')).to_be_disabled()
                for provider in ('smtp', 'mailgun', 'ses'):
                    page.get_by_label('메일러', exact=True).select_option(provider)
                    playwright.expect(page.locator(f'[data-mail-provider="{provider}"]')).to_be_visible()
                    assert page.locator('[data-mail-provider]:visible').count() == 1
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(shots / f'{theme}-{width}-{provider}.png'), full_page=True)
        page.get_by_label('메일러', exact=True).select_option('smtp')
        page.get_by_label('SMTP 호스트', exact=True).fill('smtp.example.com')
        page.get_by_label('사용자명', exact=True).fill('sender')
        page.get_by_label('비밀번호', exact=True).fill('browser-secret')
        page.get_by_label('발신자 이메일', exact=True).fill('sender@example.com')
        page.get_by_label('발신자 이름', exact=True).fill('회사 메일')
        page.get_by_role('button', name='메일 설정 저장').click()
        playwright.expect(page.get_by_text('메일 설정을 저장했습니다.', exact=True)).to_be_visible()
        playwright.expect(page.get_by_label('비밀번호', exact=True)).to_have_value('')
        playwright.expect(page.get_by_role('button', name='테스트 발송')).to_be_enabled()
        assert not errors
        browser.close()
