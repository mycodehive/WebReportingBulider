from html.parser import HTMLParser

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from reportbuilder.models import SEOConfiguration, SettingsMenu, SettingsSection
from reportbuilder.seo import SEOForm

pytestmark = pytest.mark.django_db


class Head(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.meta = {}
        self.canonical = ''
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            self.meta[attrs.get('name', attrs.get('property'))] = attrs.get('content')
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical = attrs['href']


def payload(**changes):
    return dict(action='save', title='새 보고서 서비스', description='보고서를 디자인해요', keywords='보고서,업무',
                site_url='https://wrb.writeaday.click', og_title='공유 제목', og_description='공유 설명',
                og_image='https://cdn.example.com/public/og.png', google_verification='google-code',
                naver_verification='naver-code', allow_indexing='on', **changes)


@pytest.fixture
def operator(client):
    client.force_login(get_user_model().objects.create_user('seo-operator', is_staff=True))
    return client


def test_crud_defaults_and_real_public_metadata(operator):
    assert operator.get('/settings/seo/').status_code == 200
    assert not SEOConfiguration.objects.exists()  # GET must not create configuration.
    assert operator.post('/settings/seo/', payload()).status_code == 302
    assert SEOConfiguration.objects.count() == 1
    config = SEOConfiguration.objects.get()
    assert config.title == '새 보고서 서비스'
    for path in ('/intro', '/intro/'):
        page = operator.get(path).content.decode()
        assert '<title>새 보고서 서비스</title>' in page
        head = Head(page)
        assert head.canonical == 'https://wrb.writeaday.click/intro'
        assert head.meta['description'] == config.description
        assert head.meta['og:title'] == config.og_title
        assert head.meta['og:image'] == config.og_image
        assert head.meta['google-site-verification'] == 'google-code'
        assert head.meta['naver-site-verification'] == 'naver-code'
        assert head.meta['robots'] == 'index, follow'
        assert head.meta['twitter:card'] == 'summary_large_image'
    data = payload()
    data['title'] = '수정된 제목'
    data.pop('allow_indexing')
    assert operator.post('/settings/seo/', data).status_code == 302
    assert Head(operator.get('/intro').content.decode()).meta['robots'] == 'noindex, nofollow'
    assert SEOConfiguration.objects.count() == 1
    assert operator.get('/settings/seo/', {'action': 'delete'}).status_code == 200
    assert operator.post('/settings/seo/', {'action': 'delete'}).status_code == 400
    assert SEOConfiguration.objects.exists()
    assert operator.post('/settings/seo/', {'action': 'delete', 'confirm_delete': 'yes'}).status_code == 302
    assert not SEOConfiguration.objects.exists()
    default = operator.get('/intro').content.decode()
    assert 'WebReportingBuilder — 웹에서 만드는 업무 보고서' in default
    assert 'google-code' not in default


def test_nonstaff_cannot_crud_or_reveal_settings_even_if_menu_is_public(client):
    assert client.get('/settings/seo/').status_code == 302
    section = SettingsSection.objects.get(key='basic')
    section.staff_only = False
    section.save()
    SettingsMenu.objects.filter(key='seo').update(staff_only=False)
    client.force_login(get_user_model().objects.create_user('seo-member'))
    for data in (None, payload(), {'action': 'delete', 'confirm_delete': 'yes'}):
        result = client.get('/settings/seo/') if data is None else client.post('/settings/seo/', data)
        assert result.status_code == 403
    assert not SEOConfiguration.objects.exists()
    assert 'href="/settings/seo/"' not in client.get(f'/settings/sections/{section.pk}/').content.decode()
    assert client.get('/intro').status_code == 200


def test_staff_csrf_is_required():
    client = Client(enforce_csrf_checks=True)
    client.force_login(get_user_model().objects.create_user('csrf-seo', is_staff=True))
    assert client.post('/settings/seo/', payload()).status_code == 403
    client.get('/settings/seo/')
    token = client.cookies['csrftoken'].value
    assert client.post('/settings/seo/', payload(), HTTP_X_CSRFTOKEN=token).status_code == 302
    assert client.post('/settings/seo/', {'action': 'delete', 'confirm_delete': 'yes'}).status_code == 403
    assert SEOConfiguration.objects.exists()


@pytest.mark.parametrize('field,value', [
    ('site_url', 'http://example.com'), ('site_url', 'https://example.com/path'),
    ('site_url', 'https://user:secret@example.com'), ('site_url', 'https://example.com/?token=abc'),
    ('og_image', 'javascript:alert(1)'), ('og_image', 'https://user:secret@example.com/image.png'),
    ('og_image', 'https://example.com/image.png?signature=secret'),
    ('google_verification', '<meta content="abc">'), ('naver_verification', 'code\nvalue'),
])
def test_invalid_metadata_urls_or_codes_are_rejected(field, value):
    data = payload()
    data[field] = value
    form = SEOForm(data)
    assert not form.is_valid()
    assert field in form.errors


def test_escaped_output_and_private_noindex(operator, settings):
    data = payload()
    data['title'] = '"><script>alert(1)</script>'
    data['description'] = '"><img src=x onerror=alert(1)>'
    assert operator.post('/settings/seo/', data).status_code == 302
    page = operator.get('/intro').content.decode()
    assert '<script>alert(1)</script>' not in page
    assert '&lt;script&gt;' in page
    assert Head(page).meta['description'] == data['description']
    settings.ALLOWED_HOSTS = ['*']
    SEOConfiguration.objects.all().delete()
    page = operator.get('/intro', HTTP_HOST='attacker.example').content.decode()
    assert not Head(page).canonical
    assert 'attacker.example' not in page
    for path in ('/accounts/login/', '/settings/seo/'):
        head = Head(operator.get(path).content.decode())
        assert head.meta['robots'] == 'noindex, nofollow'
        assert not head.canonical


def test_seeded_menu_and_staff_navigation(operator):
    menu = SettingsMenu.objects.get(key='seo')
    assert menu.staff_only and menu.section.key == 'basic'
    assert 'href="/settings/seo/"' in operator.get('/settings/mail/').content.decode()
