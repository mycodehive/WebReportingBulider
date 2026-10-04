import mimetypes
import os
import re
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import urlparse

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.utils import timezone

from reportbuilder import mail_settings
from reportbuilder.models import EmailVerification, MailConfiguration
from tests.test_mail_settings import payload


@pytest.mark.django_db(transaction=True)
def test_verification_and_admin_batch_themes(client, monkeypatch, settings):
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setenv('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')
    settings.DEBUG = True
    config = MailConfiguration.objects.create(pk=1)
    form = mail_settings.MailForm(payload(), configuration=config)
    assert form.is_valid()
    form.save()
    sender = Mock()
    monkeypatch.setattr(mail_settings, 'send_message', sender)
    User = get_user_model()
    long_email = 'longaddress' * 5 + '@' + 'longdomain' * 5 + '.example.com'
    user = User.objects.create_user('verification-browser', email=long_email)
    EmailVerification.objects.create(user=user, required=True)
    root = User.objects.create_superuser('email-browser-root', 'root@example.com', 'Root!Password2026')
    other = User.objects.create_user('admin-long-user-' * 6, email='other-' + long_email)
    invalid = User.objects.create_user('no-email-browser')
    client.force_login(user)
    batch_response = None

    def serve(route):
        req = route.request
        path = urlparse(req.url).path
        if path.startswith('/static/'):
            asset = finders.find(path.removeprefix('/static/'))
            route.fulfill(body=Path(asset).read_bytes(), content_type=mimetypes.guess_type(path)[0])
            return
        if path == '/admin-batch-fixture/':
            response = batch_response
        elif req.method == 'POST':
            response = client.post(path, data=req.post_data_buffer, content_type=req.headers.get('content-type', 'application/x-www-form-urlencoded'))
        else:
            response = client.get(path)
        for _ in range(3):
            if response.status_code != 302:
                break
            response = client.get(response['Location'])
        route.fulfill(status=response.status_code, body=response.content, content_type=response.get('Content-Type', 'text/html'))

    with playwright.sync_playwright() as api:
        browser = api.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_EXECUTABLE_PATH'))
        page = browser.new_page()
        page.route('http://testserver/**', serve)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        shots = Path('test-results/email-verification')
        shots.mkdir(parents=True, exist_ok=True)
        for width in (1440, 390):
            page.set_viewport_size({'width': width, 'height': 1000})
            for theme in ('light', 'dark'):
                page.goto('http://testserver/accounts/email/')
                page.wait_for_load_state('networkidle')
                page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                playwright.expect(page.get_by_role('heading', name='메일 주소를 인증해 주세요.')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(shots / f'{theme}-{width}-pending.png'), full_page=True)
        page.get_by_role('button', name='인증 메일 다시 보내기').click()
        playwright.expect(page.get_by_text('인증 메일을 발송했습니다. 받은 편지함과 스팸함을 확인하세요.', exact=True)).to_be_visible()
        path = re.search(r'http://testserver(/accounts/email/verify/\S+)', sender.call_args.args[3])[1]
        page.goto('http://testserver' + path)
        playwright.expect(page.get_by_role('button', name='메일 인증 완료')).to_be_visible()
        page.get_by_role('button', name='메일 인증 완료').click()
        playwright.expect(page.get_by_role('heading', name='메일 인증이 완료되었습니다.')).to_be_visible()
        assert EmailVerification.objects.get(user=user).verified_at
        client.force_login(root)
        endpoint = '/admin/auth/user/'
        for width in (1440, 390):
            page.set_viewport_size({'width': width, 'height': 1000})
            for theme in ('light', 'dark'):
                EmailVerification.objects.filter(user=other).update(last_sent_at=timezone.now() - timedelta(seconds=61))
                batch_response = client.post(endpoint, {'action': 'send_email_verifications', '_selected_action': [other.pk, invalid.pk]})
                page.goto('http://testserver/admin-batch-fixture/')
                page.wait_for_load_state('networkidle')
                page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                playwright.expect(page.locator('#email-batch-status')).to_contain_text('처리 완료')
                playwright.expect(page.locator('#email-batch-status')).to_contain_text('발송 1명')
                playwright.expect(page.locator('#email-batch-status')).to_contain_text('실패 1명')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.screenshot(path=str(shots / f'{theme}-{width}-admin.png'), full_page=True)
        assert not errors
        browser.close()
