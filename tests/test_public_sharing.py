from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from reportbuilder.definition import default_definition
from reportbuilder.models import Project, Report, Revision, Publication, PublicShare

pytestmark = pytest.mark.django_db


@pytest.fixture
def published(client):
    user = get_user_model().objects.create_user(username='sharer', is_staff=True)
    project = Project.objects.create(owner=user, name='Share')
    report = Report.objects.create(owner=user, project=project, name='Share', definition=default_definition())
    revision = Revision.objects.create(report=report, number=1, definition=report.definition, bindings=[])
    Publication.objects.create(report=report, revision=revision)
    client.force_login(user)
    return report


def create(client, report, **data):
    response = client.post(f'/reports/{report.pk}/shares/', data, content_type='application/json')
    assert response.status_code == 201, response.content
    return urlsplit(response.json()['url']).path


def test_public_link_anonymous_and_revocable(client, published):
    url = create(client, published)
    assert url.split('/')[-2] not in PublicShare.objects.get().token_hash
    client.logout()
    response = client.get(url)
    assert response.status_code == 200
    assert 'no-store' in response['Cache-Control']
    assert response['Referrer-Policy'] == 'no-referrer'
    assert 'sandbox' in response['Content-Security-Policy']
    client.force_login(published.owner)
    response = client.delete(f'/reports/{published.pk}/shares/', {'id':str(PublicShare.objects.get().pk)}, content_type='application/json')
    assert response.status_code == 200
    client.logout()
    assert client.get(url).status_code == 404


def test_dates_and_publication_changes(client, published):
    now = timezone.now()
    url = create(client, published, starts_at=(now+timedelta(days=1)).isoformat(), ends_at=(now+timedelta(days=2)).isoformat())
    assert client.get(url).status_code == 404
    share = PublicShare.objects.get()
    share.starts_at = now-timedelta(days=2)
    share.ends_at = now-timedelta(days=1)
    share.save()
    assert client.get(url).status_code == 404
    share.ends_at = None
    share.save()
    assert client.get(url).status_code == 200
    revision = Revision.objects.create(report=published, number=2, definition=published.definition, bindings=[])
    Publication.objects.filter(report=published).update(revision=revision)
    assert client.get(url).status_code == 404


def test_permissions_and_invalid_inputs(client, published):
    endpoint = f'/reports/{published.pk}/shares/'
    assert client.post(endpoint, {'ends_at':'2020-01-01T00:00:00+09:00'}, content_type='application/json').status_code == 400
    assert client.post(endpoint, {'starts_at':'2026-01-01T00:00:00'}, content_type='application/json').status_code == 400
    assert client.post(endpoint, {}, content_type='application/json', HTTP_AUTHORIZATION='Bearer bad').status_code == 403
    stranger = get_user_model().objects.create_user(username='stranger')
    client.force_login(stranger)
    assert client.post(endpoint, {}, content_type='application/json').status_code == 404
    client.logout()
    assert client.get(endpoint).status_code == 401
    assert client.get('/shared/unknown/').status_code == 404
    client.force_login(published.owner)
    published.publication.enabled = False
    published.publication.save()
    assert client.post(endpoint, {}, content_type='application/json').status_code == 400
