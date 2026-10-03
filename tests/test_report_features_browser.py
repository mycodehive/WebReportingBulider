import io
import os
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from PIL import Image
from playwright.sync_api import sync_playwright, expect
from reportbuilder.models import Report

@pytest.mark.django_db(transaction=True)
def test_report_features_in_browser(client, live_server, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    user = get_user_model().objects.create_user(username='feature-browser', is_staff=True)
    call_command('seed_demo', username=user.username, verbosity=0)
    report = Report.objects.get(owner=user, name='매출 현황 예제')
    client.force_login(user)
    assert client.post(f'/api/reports/{report.pk}/publish/', {}, content_type='application/json').status_code == 200
    root = Path(__file__).resolve().parents[1]
    shots = root / 'test-results' / 'report-features'
    shots.mkdir(parents=True, exist_ok=True)
    image = io.BytesIO()
    Image.new('RGB', (640, 360), '#0891b2').save(image, 'PNG')
    with sync_playwright() as api:
        try:
            browser = api.chromium.launch(channel=os.environ.get('PLAYWRIGHT_CHANNEL') or None)
        except Exception as exc:
            if 'Executable doesn''t exist' in str(exc):
                pytest.skip('Chromium binary is unavailable')
            raise
        context = browser.new_context(viewport={'width':1600,'height':1100}, locale='ko-KR')
        context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':client.cookies[settings.SESSION_COOKIE_NAME].value,'url':live_server.url}])
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def static(route):
            path=root/'reportbuilder'/'static'/route.request.url.split('/static/')[1]
            route.fulfill(path=str(path),content_type='text/css' if path.suffix=='.css' else 'application/javascript')
        page.route('**/static/**',static)
        page.goto(live_server.url+'/reports/')
        page.locator(f'[data-report-cover="{report.pk}"]').click()
        expect(page.locator('#cover-dialog')).to_be_visible()
        page.locator('#cover-file').set_input_files({'name':'cover.png','mimeType':'image/png','buffer':image.getvalue()})
        expect(page.locator('#cover-preview')).to_be_visible()
        page.get_by_role('button',name='이미지 저장',exact=True).click()
        expect(page.locator('.alert')).to_contain_text('대표 이미지를 등록했습니다.')
        card=page.locator('.report-card').filter(has=page.locator(f'[data-report-cover="{report.pk}"]'))
        expect(card.locator('.report-thumbnail img')).to_be_visible()
        page.screenshot(path=str(shots/'library-cover.png'),full_page=True)
        page.locator(f'[data-share-report="{report.pk}"]').click()
        expect(page.locator('#share-create')).to_be_enabled()
        page.locator('#share-password').fill('Browser-pass-123')
        page.locator('#share-create').click()
        expect(page.locator('#share-url')).not_to_have_value('')
        url=page.locator('#share-url').input_value()
        expect(page.locator('#share-list')).to_contain_text('비밀번호 보호')
        page.screenshot(path=str(shots/'password-share.png'))
        guest=browser.new_context()
        visitor=guest.new_page()
        visitor.route('**/static/**',static)
        visitor.goto(url)
        expect(visitor.get_by_role('heading',name='비밀번호로 보고서 열기')).to_be_visible()
        visitor.locator('[name=password]').fill('Wrong-pass-123')
        visitor.get_by_role('button',name='보고서 열기').click()
        expect(visitor.locator('[role=alert]')).to_contain_text('비밀번호가 맞지 않습니다.')
        visitor.screenshot(path=str(shots/'password-challenge.png'))
        visitor.locator('[name=password]').fill('Browser-pass-123')
        visitor.get_by_role('button',name='보고서 열기').click()
        expect(visitor.locator('body')).to_contain_text('매출 현황 보고서')
        guest.close()
        page.locator('#share-close').click()
        page.goto(live_server.url+f'/reports/{report.pk}/design/')
        page.get_by_role('tab',name='인포그래픽',exact=True).click()
        expect(page.locator('#infographic-panel')).to_be_visible()
        expect(page.locator('#elements-panel')).not_to_be_visible()
        for chart in ['bar','line','donut','kpi']:
            page.locator('#infographic-type').select_option(chart)
            page.locator('#infographic-generate').click()
            expect(page.locator('#infographic-insert')).to_be_enabled()
            expect(page.locator('#infographic-preview')).to_be_visible()
        page.locator('#infographic-type').select_option('bar')
        page.locator('#infographic-source').select_option('dataset')
        page.locator('#infographic-label').select_option('department')
        page.locator('#infographic-value').select_option('amount')
        page.locator('#infographic-generate').click()
        expect(page.locator('#infographic-insert')).to_be_enabled(timeout=15000)
        page.screenshot(path=str(shots/'infographic-panel.png'))
        page.locator('#infographic-insert').click()
        expect(page.locator('#infographic-status')).to_contain_text('캔버스에 추가했습니다.')
        expect(page.locator('.canvas-element.element-image img')).to_be_visible()
        page.locator('#save').click()
        expect(page.locator('#save-state')).to_contain_text('저장됨')
        page.reload()
        expect(page.locator('.canvas-element.element-image img')).to_be_visible()
        assert not errors, errors
        context.close()
        browser.close()
    report.refresh_from_db()
    elements=[e for p in report.definition['pages'] for b in p['bands'] for e in b['elements']]
    assert any(e['type']=='image' for e in elements)
    response=client.get(f'/reports/{report.pk}/export/project/')
    assert response.status_code==200
    from reportbuilder.packaging import import_project
    assert import_project(response.content)['assets']
