
import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.templatetags.static import static

from reportbuilder.models import EmailVerification

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('path', ['/intro', '/intro/'])
def test_public_intro_and_images(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert 'WebReportingBuilder — 웹에서 만드는 업무 보고서' in response.content.decode()
    for name in ('01-hero.webp', '02-designer.webp', '03-reuse.webp'):
        asset = f'reportbuilder/intro/images/{name}'
        assert static(asset).encode() in response.content
        assert finders.find(asset)
    assert b'src="images/' not in response.content
    assert client.head(path).status_code == 200
    assert client.post(path).status_code == 405


def test_pending_user_can_read_intro_but_workspace_stays_protected(client):
    user = get_user_model().objects.create_user('pending-intro', email='pending@example.com')
    EmailVerification.objects.create(user=user, required=True)
    client.force_login(user)
    assert client.get('/intro').status_code == 200
    assert client.get('/intro/').status_code == 200
    assert client.get('/reports/').url == '/accounts/email/'
    assert client.get('/intro/private').url == '/accounts/email/'
