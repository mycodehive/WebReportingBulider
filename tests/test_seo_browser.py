import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from PIL import Image

from reportbuilder.models import SEOConfiguration


@pytest.mark.django_db(transaction=True)
def test_seo_themes_preview_and_crud(client, monkeypatch, settings, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setenv('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')
    settings.DEBUG = True
    settings.MEDIA_ROOT = tmp_path
    sample = tmp_path / "share.jpg"
    Image.new("RGB", (120, 63), "#346b83").save(sample)
    settings.ALLOWED_HOSTS = ['testserver', 'wrb.writeaday.click']
    client.force_login(get_user_model().objects.create_user('seo-browser', is_staff=True))

    def serve(route):
        req = route.request
        path = urlparse(req.url).path
        if path.startswith('/static/'):
            asset = finders.find(path.removeprefix('/static/'))
            route.fulfill(body=Path(asset).read_bytes(), content_type=mimetypes.guess_type(path)[0])
            return
        content_type = req.headers.get('content-type', 'application/x-www-form-urlencoded')
        if req.method == 'POST' and content_type.startswith('multipart/form-data'):
            # Playwright's intercepted post_data omits file bytes; restore the selected fixture.
            parsed = RequestFactory().post(path, data=req.post_data_buffer, content_type=content_type)
            data = parsed.POST.dict()
            if parsed.FILES.get('og_upload') and parsed.FILES['og_upload'].name == sample.name:
                data['og_upload'] = SimpleUploadedFile(sample.name, sample.read_bytes(), content_type='image/jpeg')
            response = client.post(path, data=data)
        elif req.method == 'POST':
            response = client.post(path, data=req.post_data_buffer, content_type=content_type)
        else:
            response = client.get(path)
        if response.status_code == 302:
            response = client.get(response['Location'])
        body = b''.join(response.streaming_content) if response.streaming else response.content
        route.fulfill(status=response.status_code, body=body, content_type=response.get('Content-Type', 'text/html'))
        response.close()

    with playwright.sync_playwright() as api:
        browser = api.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_EXECUTABLE_PATH'))
        page = browser.new_page()
        page.route('http://testserver/**', serve)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        shots = Path('test-results/seo')
        shots.mkdir(parents=True, exist_ok=True)
        for width in (1440, 390):
            page.set_viewport_size({'width': width, 'height': 1100})
            for theme in ('light', 'dark'):
                page.goto('http://testserver/settings/seo/')
                page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                playwright.expect(page.locator('.settings-submenu [aria-current="page"]')).to_have_text('SEO')
                playwright.expect(page.get_by_role('button', name='SEO 설정 등록')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.screenshot(path=str(shots / f'{theme}-{width}.png'), full_page=True)
        page.get_by_label('사이트 제목', exact=True).fill('브라우저 SEO 제목')
        page.get_by_label('사이트 설명', exact=True).fill('<script>unsafe()</script> 안전한 미리보기')
        playwright.expect(page.locator('#seo-preview-description')).to_have_text('<script>unsafe()</script> 안전한 미리보기')
        assert page.locator('#seo-preview-description script').count() == 0
        page.get_by_label('대표 서비스 주소', exact=True).fill('https://wrb.writeaday.click/')
        playwright.expect(page.locator('#seo-preview-url')).to_have_text('https://wrb.writeaday.click/intro')
        page.get_by_label('공유 이미지 업로드', exact=True).set_input_files(str(sample))
        page.get_by_role('button', name='SEO 설정 등록').click()
        playwright.expect(page.get_by_role('button', name='변경사항 저장')).to_be_visible()
        assert SEOConfiguration.objects.get(pk=1).title == '브라우저 SEO 제목'
        assert SEOConfiguration.objects.get(pk=1).og_upload
        playwright.expect(page.get_by_alt_text('현재 링크 공유 이미지')).to_be_visible()
        assert page.get_by_alt_text('현재 링크 공유 이미지').evaluate('(image) => image.complete && image.naturalWidth > 0')
        assert '<title>브라우저 SEO 제목</title>' in client.get('/intro').content.decode()
        page.get_by_label('소개페이지 검색 허용', exact=True).uncheck()
        with page.expect_response(lambda response: response.url.endswith('/settings/seo/') and response.request.method == 'POST') as saved:
            page.get_by_role('button', name='변경사항 저장').click()
        assert saved.value.status == 200
        playwright.expect(page.get_by_text('SEO 설정을 저장했습니다. 소개페이지에 반영됩니다.', exact=True)).to_be_visible()
        assert not SEOConfiguration.objects.get(pk=1).allow_indexing
        page.get_by_label('저장된 SEO 설정을 삭제하는 데 동의합니다.', exact=True).check()
        page.get_by_role('button', name='SEO 설정 삭제', exact=True).click()
        playwright.expect(page.get_by_role('button', name='SEO 설정 등록')).to_be_visible()
        assert not SEOConfiguration.objects.exists()
        assert not errors
        browser.close()
