import os
import io
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from playwright.sync_api import expect, sync_playwright
from PIL import Image


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('offline_editor', [False, True])
def test_board_creation_editor_and_mobile(client, live_server, settings, tmp_path, offline_editor):
    settings.MEDIA_ROOT = tmp_path
    user = get_user_model().objects.create_user('board-browser', is_staff=True)
    client.force_login(user)
    root = Path(__file__).resolve().parents[1]
    shots = root / 'test-results' / 'community'
    shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as api:
        try:
            browser = api.chromium.launch(channel=os.environ.get('PLAYWRIGHT_CHANNEL') or None)
        except Exception as exc:
            if 'Executable doesn' in str(exc):
                pytest.skip('Chromium binary is unavailable')
            raise
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='ko-KR')
        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': live_server.url}])
        page = context.new_page()

        def static(route):
            path = root / 'reportbuilder' / 'static' / route.request.url.split('/static/')[1]
            route.fulfill(path=str(path), content_type='text/css' if path.suffix == '.css' else 'application/javascript')

        page.route('**/static/**', static)
        if offline_editor:
            page.route('https://cdn.ckeditor.com/**', lambda route: route.abort())
        image = io.BytesIO()
        Image.new('RGB', (480, 120), '#265ed8').save(image, 'PNG')
        page.goto(live_server.url + '/settings/company/')
        page.get_by_label('회사명').fill('Example Company')
        page.get_by_label('로고 이미지').set_input_files({'name': 'logo.png', 'mimeType': 'image/png', 'buffer': image.getvalue()})
        page.get_by_role('button', name='저장', exact=True).click()
        expect(page.locator('.company-brand-logo')).to_be_visible()
        visitor = browser.new_context()
        login = visitor.new_page()
        login.route('**/static/**', static)
        login.goto(live_server.url + '/accounts/login/')
        expect(login.locator('.login-company-brand img')).to_be_visible()
        expect(login.locator('body')).not_to_contain_text('createsuperuser')
        login.screenshot(path=str(shots / 'login-logo.png'), full_page=True)
        visitor.close()
        page.goto(live_server.url + '/boards/')
        page.get_by_role('link', name='게시판 만들기').click()
        page.get_by_label('게시판 이름').fill('고객 문의')
        page.get_by_label('게시판 유형').select_option('qa')
        page.get_by_role('button', name='게시판 저장').click()
        page.get_by_role('link', name='카테고리 / 상태 관리').click()
        page.locator('#id_categories-0-name').fill('사용 문의')
        page.get_by_role('button', name='카테고리 추가', exact=True).click()
        page.locator('#id_categories-1-name').fill('개선 제안')
        page.locator('#id_categories-1-order').fill('1')
        page.get_by_role('button', name='카테고리 / 상태 저장').click()
        expect(page.locator('.alert')).to_contain_text('카테고리와 상태를 저장했습니다.')
        page.screenshot(path=str(shots / 'taxonomy.png'), full_page=True)
        page.get_by_role('link', name='← 게시판 설정', exact=True).click()
        page.get_by_role('link', name='게시판 열기').click()
        page.get_by_role('link', name='글쓰기', exact=True).click()
        page.get_by_label('제목').fill('보고서 문의')
        page.get_by_label('카테고리').select_option(label='사용 문의')
        # The textarea remains usable if the pinned external editor is unavailable.
        if offline_editor:
            page.locator('#id_body').fill('문의 내용')
        else:
            page.wait_for_function('window.CKEDITOR && CKEDITOR.instances.id_body && CKEDITOR.instances.id_body.status === "ready"', timeout=45000)
            assert page.evaluate('CKEDITOR.version') == '4.22.1'
            page.evaluate('new Promise(resolve => CKEDITOR.instances.id_body.setData("<p><strong>문의 내용</strong></p>", {callback: resolve}))')
        page.screenshot(path=str(shots / 'editor.png'), full_page=True)
        page.get_by_role('button', name='저장', exact=True).click()
        expect(page.locator('.rich-content').first).to_contain_text('문의 내용')
        page.get_by_label('처리 상태').select_option(label='완료')
        page.get_by_role('button', name='상태 변경').click()
        expect(page.locator('.status-badge')).to_have_text('완료')
        if offline_editor:
            page.locator('#id_body').fill('답변 내용')
        else:
            page.wait_for_function('window.CKEDITOR && CKEDITOR.instances.id_body && CKEDITOR.instances.id_body.status === "ready"')
            page.evaluate('new Promise(resolve => CKEDITOR.instances.id_body.setData("<p>답변 내용</p>", {callback: resolve}))')
        page.get_by_role('button', name='등록', exact=True).click()
        expect(page.locator('.rich-content').nth(1)).to_contain_text('답변 내용')
        page.screenshot(path=str(shots / 'detail.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(shots / 'mobile.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), page.evaluate('Array.from(document.querySelectorAll("body *")).filter(e => e.getBoundingClientRect().right > innerWidth).map(e=>[e.tagName,e.className,e.getBoundingClientRect().right]).slice(0,15)')
        context.close()
        browser.close()
