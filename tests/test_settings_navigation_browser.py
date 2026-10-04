"""Check actual settings pages, tab navigation and responsive theme styling."""
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders

from reportbuilder.models import WorkspaceMenu, SettingsSection, SettingsMenu


@pytest.mark.django_db(transaction=True)
def test_settings_tabs_light_dark_desktop_mobile(client, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setenv('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')
    user = get_user_model().objects.create_user('settings-browser', is_staff=True)
    client.force_login(user)
    WorkspaceMenu.objects.get_or_create(key='settings', defaults={
        'label': '환경설정', 'url': '/settings/', 'order': 50, 'staff_only': True})

    def serve(route):
        path = urlparse(route.request.url).path
        if path.startswith('/static/'):
            asset = finders.find(path.removeprefix('/static/'))
            assert asset, path
            route.fulfill(body=Path(asset).read_bytes(), content_type=mimetypes.guess_type(path)[0])
        else:
            if route.request.method == 'POST':
                response = client.post(path, data=route.request.post_data,
                                       content_type='application/x-www-form-urlencoded')
                if response.status_code == 302:
                    response = client.get(response['Location'])
            else:
                response = client.get(path)
            route.fulfill(status=response.status_code, body=response.content,
                          content_type='text/html')

    with playwright.sync_playwright() as api:
        try:
            browser = api.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_EXECUTABLE_PATH'))
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip('Chromium binary unavailable')
            raise
        page = browser.new_page()
        page.route('http://testserver/**', serve)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        shots = Path('test-results/settings')
        shots.mkdir(parents=True, exist_ok=True)
        for width in (1280, 390):
            page.set_viewport_size({'width': width, 'height': 1000})
            for theme in ('light', 'dark'):
                page.goto('http://testserver/settings/')
                page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                tabs = page.get_by_role('navigation', name='환경설정 분류')
                children = page.get_by_role('navigation', name='선택한 설정의 하위 메뉴')
                assert tabs.evaluate('e => getComputedStyle(e).display') == 'flex'
                assert tabs.evaluate('e => [getComputedStyle(e).overflowX, getComputedStyle(e).overflowY]') == ['visible', 'visible']
                assert tabs.evaluate('e => e.scrollHeight <= e.clientHeight + 1 && e.scrollWidth <= e.clientWidth + 1')
                assert tabs.get_by_role('link', name='기본정보').evaluate(
                    'e => getComputedStyle(e).borderTopWidth') == '3px'
                assert children.bounding_box()['y'] >= tabs.bounding_box()['y'] + tabs.bounding_box()['height'] - 1
                playwright.expect(tabs.get_by_role('link', name='기본정보')).to_have_attribute('aria-current', 'page')
                playwright.expect(children.get_by_role('link', name='회사로고')).to_be_visible()
                playwright.expect(page.get_by_role('heading', name='로고 등록 / 수정')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.screenshot(path=str(shots / f'basic-{theme}-{width}.png'), full_page=True)
                tabs.get_by_role('link', name='사이트관리').click()
                page.wait_for_load_state('networkidle')
                page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                playwright.expect(tabs.get_by_role('link', name='사이트관리')).to_have_attribute('aria-current', 'page')
                playwright.expect(children.get_by_role('link', name='메뉴관리')).to_be_visible()
                playwright.expect(children.get_by_role('link', name='회사로고')).to_have_count(0)
                playwright.expect(page.locator('#global-sidebar a[aria-label="환경설정"]')).to_have_attribute('aria-current', 'page')
                playwright.expect(page.locator('.menu-management-form .table th').first).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                assert children.evaluate('e => getComputedStyle(e).backgroundColor') == (
                    'rgb(17, 28, 47)' if theme == 'dark' else 'rgb(255, 255, 255)')
                page.screenshot(path=str(shots / f'site-{theme}-{width}.png'), full_page=True)
                tabs.get_by_role('link', name='기본정보').click()
                playwright.expect(children.get_by_role('link', name='회사로고')).to_be_visible()
        page.goto('http://testserver/menu-management/')
        section_form = page.locator('.settings-section-form')
        section_form.locator('input[name$="-label"]').last.fill('운영관리')
        section_form.get_by_role('button', name='탭 설정 저장').click()
        playwright.expect(page.get_by_role('navigation', name='환경설정 분류').get_by_role('link', name='운영관리')).to_be_visible()
        section = SettingsSection.objects.get(label='운영관리')
        child_form = page.locator('.settings-children-form')
        child_form.locator('select[name$="-section"]').last.select_option(str(section.pk))
        child_form.locator('input[name$="-label"]').last.fill('운영 가이드')
        child_form.locator('input[name$="-url"]').last.fill('/manual/')
        child_form.get_by_role('button', name='하위 메뉴 설정 저장').click()
        page.get_by_role('navigation', name='환경설정 분류').get_by_role('link', name='운영관리').click()
        playwright.expect(page.get_by_role('navigation', name='선택한 설정의 하위 메뉴').get_by_role('link', name='운영 가이드')).to_be_visible()
        assert SettingsMenu.objects.filter(section=section, label='운영 가이드', url='/manual/').exists()
        # Many long tab names wrap without horizontal or vertical scrollbars.
        for index in range(10):
            SettingsSection.objects.create(key=f'wrap-{index}', label=f'긴 환경설정 탭 이름 {index}', order=100 + index)
        page.set_viewport_size({'width': 390, 'height': 1000})
        page.goto('http://testserver/menu-management/')
        page.wait_for_load_state('networkidle')
        for theme in ('light', 'dark'):
            page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
            tabs = page.get_by_role('navigation', name='환경설정 분류')
            assert tabs.evaluate('e => [getComputedStyle(e).overflowX, getComputedStyle(e).overflowY]') == ['visible', 'visible']
            assert tabs.evaluate('e => e.scrollHeight <= e.clientHeight + 1 && e.scrollWidth <= e.clientWidth + 1')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            for link in tabs.get_by_role('link').all():
                bounds = link.bounding_box()
                assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 390
            page.screenshot(path=str(shots / f'tabs-wrap-{theme}-390.png'), full_page=True)
        assert not errors
        browser.close()
