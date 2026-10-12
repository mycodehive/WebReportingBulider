import io
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from reportbuilder.models import EmailVerification, SEOConfiguration
from reportbuilder.seo import image_path
from tests.test_seo import payload, Head

pytestmark = pytest.mark.django_db


def upload():
    stream = io.BytesIO()
    Image.new('RGB', (120, 63), '#346b83').save(stream, format='JPEG')
    return SimpleUploadedFile('photo.jpg', stream.getvalue(), content_type='image/jpeg')


def test_image_upload_public_metadata_preserve_replace_remove(client, settings, tmp_path, django_capture_on_commit_callbacks):
    settings.MEDIA_ROOT = tmp_path
    user = get_user_model().objects.create_user('seo-upload', is_staff=True)
    client.force_login(user)
    data = payload()
    data['og_upload'] = upload()
    assert client.post('/settings/seo/', data).status_code == 302
    config = SEOConfiguration.objects.get(pk=1)
    first_path = image_path(config)
    first_file = Path(config.og_upload.path)
    with Image.open(first_file) as im:
        assert im.format == 'PNG' and im.size == (120, 63)
    page = client.get('/intro').content.decode()
    head = Head(page)
    assert head.meta['og:image'] == 'https://wrb.writeaday.click' + first_path
    assert head.meta['twitter:image'] == head.meta['og:image']
    assert 'enctype="multipart/form-data"' in client.get('/settings/seo/').content.decode()
    assert '현재 업로드 이미지' in client.get('/settings/seo/').content.decode()
    assert client.post('/settings/seo/', payload()).status_code == 302
    config.refresh_from_db()
    assert image_path(config) == first_path  # Saving text must retain the existing image.
    client.logout()
    response = client.get(first_path)
    assert response.status_code == 200 and response['Content-Type'] == 'image/png'
    assert b''.join(response.streaming_content).startswith(b'\x89PNG')
    assert client.post(first_path).status_code == 405
    assert client.get('/seo/image/unrelated.png/').status_code == 404
    pending = get_user_model().objects.create_user('seo-pending')
    EmailVerification.objects.create(user=pending, required=True)
    client.force_login(pending)
    response = client.get(first_path)
    assert response.status_code == 200
    response.close()
    assert client.get('/reports/').status_code == 302
    client.force_login(user)
    with django_capture_on_commit_callbacks(execute=True):
        data = payload()
        data['og_upload'] = upload()
        assert client.post('/settings/seo/', data).status_code == 302
    config.refresh_from_db()
    second_path = image_path(config)
    assert second_path != first_path and not first_file.exists()
    assert client.get(first_path).status_code == 404
    second_file = Path(config.og_upload.path)
    with django_capture_on_commit_callbacks(execute=True):
        data = payload()
        data['remove_image'] = 'on'
        assert client.post('/settings/seo/', data).status_code == 302
    config.refresh_from_db()
    assert not config.og_upload and not second_file.exists()
    assert Head(client.get('/intro').content.decode()).meta['og:image'] == data['og_image']


def test_invalid_image_cannot_replace_valid_image(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    client.force_login(get_user_model().objects.create_user('seo-validation', is_staff=True))
    for name, content in [('fake.png', b'<svg onload="alert(1)"></svg>'), ('huge.png', b'x' * (5 * 1024 * 1024 + 1))]:
        data = payload()
        data['og_upload'] = SimpleUploadedFile(name, content)
        response = client.post('/settings/seo/', data)
        assert response.status_code == 200
        assert 'og_upload' in response.context['form'].errors
    assert not SEOConfiguration.objects.exists()
    assert not list(tmp_path.rglob('*.png'))
    data = payload()
    data.update(og_upload=upload(), remove_image='on')
    assert client.post('/settings/seo/', data).status_code == 200
    assert not SEOConfiguration.objects.exists()
    settings.ALLOWED_HOSTS = ['testserver']
    data = payload()
    data.update(og_upload=upload(), site_url='')
    response = client.post('/settings/seo/', data)
    assert response.status_code == 200 and 'site_url' in response.context['form'].errors


def test_image_requires_staff_to_upload_and_delete_configuration_cleans_file(client, settings, tmp_path, django_capture_on_commit_callbacks):
    settings.MEDIA_ROOT = tmp_path
    client.force_login(get_user_model().objects.create_user('seo-regular'))
    data = payload()
    data['og_upload'] = upload()
    assert client.post('/settings/seo/', data).status_code == 403
    assert not SEOConfiguration.objects.exists()
    client.force_login(get_user_model().objects.create_user('seo-admin-image', is_staff=True))
    data['og_upload'] = upload()
    assert client.post('/settings/seo/', data).status_code == 302
    config = SEOConfiguration.objects.get(pk=1)
    path, file = image_path(config), Path(config.og_upload.path)
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post('/settings/seo/', {'action': 'delete', 'confirm_delete': 'yes'}).status_code == 302
    assert not file.exists()
    assert client.get(path).status_code == 404
