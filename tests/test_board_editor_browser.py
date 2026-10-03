"""Exercise locally served Summernote with real Django pages and submissions."""
import mimetypes
import os
import io
from pathlib import Path
from urllib.parse import urlparse

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.urls import reverse
from PIL import Image

from reportbuilder.models import Board, BoardPost, BoardReply


@pytest.mark.django_db(transaction=True)
def test_summernote_themes_mobile_save_edit_reply_and_fallback(client, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    # Route handlers run in Playwright's event loop, without a TCP server.
    monkeypatch.setenv('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')
    user = get_user_model().objects.create_user('summernote-user')
    client.force_login(user)
    board = Board.objects.create(name='에디터 테스트', kind='list')
    post = BoardPost.objects.create(board=board, author=user, title='기존 게시글',
                                    body='<p><strong>기존 내용</strong></p>')
    reply = BoardReply.objects.create(post=post, author=user, body='<p>기존 답변</p>')
    paths = [reverse('board_post_create', args=[board.pk]),
             reverse('board_post_edit', args=[board.pk, post.pk]),
             reverse('board_post', args=[board.pk, post.pk]),
             reverse('board_reply_edit', args=[board.pk, post.pk, reply.pk])]
    responses = {path: client.get(path) for path in paths}
    assert all(response.status_code == 200 for response in responses.values())
    posts = []

    def serve(route):
        request = route.request
        path = urlparse(request.url).path
        if path.startswith('/static/'):
            asset = finders.find(path.removeprefix('/static/'))
            assert asset, path
            route.fulfill(body=Path(asset).read_bytes(),
                          content_type=mimetypes.guess_type(path)[0] or 'application/octet-stream')
        elif request.method == 'POST':
            response = client.post(path, data=request.post_data,
                                   content_type='application/x-www-form-urlencoded')
            posts.append(response.status_code)
            if response.status_code == 302:
                # Resolve Django's redirect locally; no DNS/TCP server is used.
                response = client.get(response['Location'])
            route.fulfill(status=response.status_code, body=response.content, headers=dict(response.items()))
        else:
            response = responses.get(path) or client.get(path)
            route.fulfill(body=response.content, content_type='text/html')

    with playwright.sync_playwright() as api:
        try:
            browser = api.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_EXECUTABLE_PATH'))
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip('Chromium binary is unavailable')
            raise
        page = browser.new_page()
        page.route('http://testserver/**', serve)
        page.route('https://www.youtube.com/embed/**', lambda route: route.fulfill(body='<html></html>', content_type='text/html'))
        errors = []
        requests = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: requests.append(request.url))
        shots = Path('test-results/board-editor')
        shots.mkdir(parents=True, exist_ok=True)
        for width in (1280, 390):
            page.set_viewport_size({'width': width, 'height': 1000})
            for theme in ('light', 'dark'):
                page.goto('http://testserver' + paths[0])
                page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                editor = page.locator('.note-editable')
                playwright.expect(editor).to_be_visible()
                assert page.locator('#id_body').is_hidden()
                assert page.evaluate('jQuery.summernote.version') == '0.9.1'
                assert not page.evaluate('window.CKEDITOR')
                for name in ('Picture', 'Video', 'Code View'):
                    playwright.expect(page.get_by_role('button', name=name, exact=True)).to_be_visible()
                editor.fill('내용 테스트')
                playwright.expect(page.locator('#id_body')).to_have_value('<p>내용 테스트</p>')
                expected = 'rgb(15, 26, 44)' if theme == 'dark' else 'rgb(255, 255, 255)'
                assert editor.evaluate('e => getComputedStyle(e).backgroundColor') == expected
                page.get_by_role('button', name='링크', exact=True).click()
                dialog = page.get_by_role('dialog', name='링크 삽입')
                playwright.expect(dialog).to_be_visible()
                expected_surface = 'rgb(17, 28, 47)' if theme == 'dark' else 'rgb(255, 255, 255)'
                assert dialog.locator('.note-modal-content').evaluate(
                    'e => getComputedStyle(e).backgroundColor') == expected_surface
                bounds = dialog.locator('.note-modal-content').bounding_box()
                assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
                page.screenshot(path=str(shots / f'link-{theme}-{width}.png'), full_page=True)
                dialog.locator('.close').click()
                page.get_by_role('button', name='스타일', exact=True).click()
                playwright.expect(page.locator('.note-dropdown-menu:visible')).to_be_visible()
                page.screenshot(path=str(shots / f'editor-{theme}-{width}.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                # New dialogs and HTML source mode follow both workspace themes.
                page.get_by_role('button', name='스타일', exact=True).click()
                for button, title in [('Picture', '그림 삽입'), ('Video', '동영상 삽입')]:
                    page.get_by_role('button', name=button, exact=True).click()
                    media_dialog = page.get_by_role('dialog', name=title)
                    playwright.expect(media_dialog).to_be_visible()
                    assert media_dialog.locator('.note-modal-content').evaluate(
                        'e => getComputedStyle(e).backgroundColor') == expected_surface
                    page.screenshot(path=str(shots / f'{button}-{theme}-{width}.png'), full_page=True)
                    media_dialog.get_by_role('button', name='닫기', exact=True).click()
                page.get_by_role('button', name='Code View', exact=True).click()
                playwright.expect(page.locator('.note-codable')).to_be_visible()
                assert page.locator('.note-codable').evaluate('e => getComputedStyle(e).backgroundColor') == expected
                page.screenshot(path=str(shots / f'code-{theme}-{width}.png'), full_page=True)
                page.get_by_role('button', name='Code View', exact=True).click()
        for path in paths[1:]:
            page.goto('http://testserver' + path)
            playwright.expect(page.locator('.note-editable')).to_contain_text(
                '기존 답변' if path == paths[3] else '기존 내용' if path == paths[1] else '')
        page.goto('http://testserver' + paths[0])
        page.locator('#id_title').fill('Summernote 저장')
        page.evaluate("jQuery('#id_body').summernote('code', '<p><b>굵게</b> <i>기울임</i></p>')")
        assert page.locator('.rich-form').evaluate('f => f.checkValidity()'), page.locator(':invalid').evaluate_all(
            'es => es.map(e => [e.tagName, e.id, e.name, e.validationMessage])')
        page.get_by_role('button', name='저장', exact=True).click()
        playwright.expect(page.locator('.rich-content').first).to_contain_text('굵게')
        assert posts[-1] == 302
        page.locator('.note-editable').fill('Summernote 답변')
        # The routed response followed the redirect without changing browser URL.
        saved_id = BoardPost.objects.get(title='Summernote 저장').pk
        page.locator('.rich-form').evaluate('(f, url) => f.action = url',
                                          reverse('board_post', args=[board.pk, saved_id]))
        page.get_by_role('button', name='등록', exact=True).click()
        playwright.expect(page.locator('.rich-content').last).to_contain_text('Summernote 답변')
        assert posts[-1] == 302
        # Untrusted clipboard HTML is inserted only as text, before saving.
        page.goto('http://testserver' + paths[0])
        page.locator('.note-editable').evaluate('''e => {
            e.focus();
            const data = new DataTransfer();
            data.setData('text/plain', '안전한 붙여넣기');
            data.setData('text/html', '<img src=x onerror="window.pasteExecuted=true">');
            e.dispatchEvent(new ClipboardEvent('paste', {clipboardData: data, bubbles: true, cancelable: true}));
        }''')
        playwright.expect(page.locator('.note-editable')).to_contain_text('안전한 붙여넣기')
        assert page.locator('.note-editable img').count() == 0
        assert not page.evaluate('window.pasteExecuted')
        # Code View removes active HTML before the preview is reattached.
        page.get_by_role('button', name='Code View', exact=True).click()
        page.locator('.note-codable').fill('<p>코드 내용</p><img src=x onerror="window.codeExecuted=true">'
                                         '<script>window.codeExecuted=true</script>')
        page.get_by_role('button', name='Code View', exact=True).click()
        playwright.expect(page.locator('.note-editable')).to_contain_text('코드 내용')
        assert page.locator('.note-editable img').count() == 0
        assert not page.evaluate('window.codeExecuted')
        # Picture upload, video insertion, and submission while Code View is active.
        page.goto('http://testserver' + paths[0])
        page.locator('#id_title').fill('미디어 저장')
        page.get_by_role('button', name='Picture', exact=True).click()
        picture = page.get_by_role('dialog', name='그림 삽입')
        image = io.BytesIO()
        Image.new('RGB', (2, 2), '#265ed8').save(image, 'PNG')
        picture.locator('input[type=file]').set_input_files(
            {'name': 'pixel.png', 'mimeType': 'image/png', 'buffer': image.getvalue()})
        playwright.expect(page.locator('.note-editable img')).to_be_visible()
        page.get_by_role('button', name='Video', exact=True).click()
        video = page.get_by_role('dialog', name='동영상 삽입')
        video.locator('.note-video-url').fill('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        video.locator('.note-video-url').press('End')
        video.get_by_role('button', name='동영상 삽입', exact=True).click()
        playwright.expect(page.locator('.note-editable iframe')).to_be_visible()
        page.get_by_role('button', name='Code View', exact=True).click()
        source = page.locator('.note-codable')
        source.fill(source.input_value() + '<p>코드 모드 저장</p>')
        page.get_by_role('button', name='저장', exact=True).click()
        playwright.expect(page.locator('.rich-content').first).to_contain_text('코드 모드 저장')
        playwright.expect(page.locator('.rich-content img')).to_be_visible()
        playwright.expect(page.locator('.rich-content iframe')).to_be_visible()
        assert posts[-1] == 302
        assert not errors, errors
        # Missing dependency leaves an accessible, usable textarea.
        page.route('**/summernote-lite.min.js', lambda route: route.abort())
        page.goto('http://testserver' + paths[0])
        playwright.expect(page.locator('#id_body')).to_be_visible()
        playwright.expect(page.locator('.editor-fallback')).to_be_visible()
        assert all(url.startswith(('http://testserver/', 'https://www.youtube.com/embed/')) for url in requests), requests
        browser.close()
    saved = BoardPost.objects.get(title='Summernote 저장')
    assert '<b>굵게</b>' in saved.body and '<i>기울임</i>' in saved.body
    media = BoardPost.objects.get(title='미디어 저장')
    assert 'data:image/png;base64,' in media.body and 'sandbox=' in media.body
