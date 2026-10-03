from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.test import Client
from django.utils import timezone

from reportbuilder.definition import default_definition
from reportbuilder.models import AuditEvent, Execution, Project, Report, Revision, Publication, PublicShare

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


def test_password_share_challenges_before_rendering_and_scopes_unlock(client, published, monkeypatch):
    url = create(client, published, password='Correct-pass-123')
    share = PublicShare.objects.get()
    assert share.password_hash != 'Correct-pass-123'
    assert check_password('Correct-pass-123', share.password_hash)
    listing = client.get(f'/reports/{published.pk}/shares/').json()['shares'][0]
    assert listing['password_protected'] is True
    assert 'password_hash' not in listing
    rendered = []
    monkeypatch.setattr('reportbuilder.sharing.render_public_report', lambda *args: rendered.append(True) or {'html': '<p>Protected contents</p>'})
    client.logout()
    assert b'password' in client.get(url).content
    assert client.post(url, {'password': 'wrong'}).status_code == 403
    assert not rendered
    assert client.post(url, {'password': 'Correct-pass-123'}).status_code == 302
    assert b'Protected contents' in client.get(url).content
    another = Client()
    assert b'Protected contents' not in another.get(url).content
    share.password_hash = make_password('Changed-pass-123')
    share.save(update_fields=['password_hash'])
    assert b'Protected contents' not in client.get(url).content
    share.revoked = True
    share.save(update_fields=['revoked'])
    assert client.post(url, {'password': 'Changed-pass-123'}).status_code == 404


def test_password_validation_and_csrf(client, published):
    endpoint = f'/reports/{published.pk}/shares/'
    for password in ['short', 'x' * 129, 123, None]:
        assert client.post(endpoint, {'password':password}, content_type='application/json').status_code == 400
    url = create(client, published, password='Correct-pass-123')
    visitor = Client(enforce_csrf_checks=True)
    assert visitor.get(url).status_code == 200
    assert visitor.post(url, {'password':'Correct-pass-123'}).status_code == 403
    assert visitor.post(url, {'password':'Correct-pass-123'},
                        HTTP_X_CSRFTOKEN=visitor.cookies['csrftoken'].value).status_code == 302


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


def test_public_view_does_not_create_owner_execution_or_audit(client, published):
    url = create(client, published)
    client.logout()

    assert client.get(url).status_code == 200
    assert Execution.objects.filter(report=published).count() == 0
    assert not AuditEvent.objects.filter(resource_id=str(published.pk), action='execute').exists()


def test_public_view_is_rate_limited_before_rendering(client, published, monkeypatch):
    from reportbuilder import sharing

    url = create(client, published)
    share = PublicShare.objects.get()
    share.public_window_started = timezone.now()
    share.public_window_count = sharing.PUBLIC_REQUESTS_PER_MINUTE
    share.save(update_fields=['public_window_started', 'public_window_count'])
    client.logout()
    monkeypatch.setattr(sharing, 'render_public_report', lambda *args, **kwargs: pytest.fail('render should not run'))

    response = client.get(url)
    assert response.status_code == 429
    assert response['Retry-After'] == '60'


def test_all_unrevoked_shares_remain_listed_for_revocation(client, published):
    revision = published.publication.revision
    for index in range(105):
        PublicShare.objects.create(report=published, revision=revision,
                                   token_hash=f'{index:064x}')

    response = client.get(f'/reports/{published.pk}/shares/')
    assert response.status_code == 200
    assert len(response.json()['shares']) == 105


def test_active_share_creation_has_a_bounded_limit(client, published):
    revision = published.publication.revision
    for index in range(100):
        PublicShare.objects.create(report=published, revision=revision,
                                   token_hash=f'{index:064x}')

    response = client.post(f'/reports/{published.pk}/shares/', {}, content_type='application/json')
    assert response.status_code == 429
