import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from reportbuilder.models import DemoSeed, Report

pytestmark = pytest.mark.django_db


def test_auto_demo_once(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    user = get_user_model().objects.create_user(username='demo-admin', is_staff=True)
    client.force_login(user)
    page = client.get('/reports/')
    assert 'Demo 보고서 생성중' in page.content.decode()
    assert 'uv run python manage.py seed_demo 명령' not in page.content.decode()
    assert client.get('/reports/demo/').status_code == 405
    assert client.post('/reports/demo/').status_code == 200
    report = Report.objects.get(owner=user)
    assert DemoSeed.objects.get(owner=user).completed
    report.name = 'Renamed demo'
    report.save()
    assert client.post('/reports/demo/').status_code == 200
    assert Report.objects.filter(owner=user).count() == 1
    assert 'id="demo-bootstrap"' not in client.get('/reports/').content.decode()


def test_existing_seed_and_permissions(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    user = get_user_model().objects.create_user(username='existing-admin', is_staff=True)
    call_command('seed_demo', username=user.username)
    client.force_login(user)
    assert client.post('/reports/demo/').status_code == 200
    assert Report.objects.filter(owner=user).count() == 1
    user.is_staff = False
    user.save()
    assert client.post('/reports/demo/').status_code == 403
    assert 'id="demo-bootstrap"' not in client.get('/reports/').content.decode()
