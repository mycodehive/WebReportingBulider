"""Regressions for signup failures reported on the HTTPS deployment."""
import re
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.storage import FileSystemStorage
from django.test import Client, RequestFactory

from reportbuilder import email_verification, mail_settings
from reportbuilder.data import execute_dataset, introspect
from reportbuilder.demo import prepare_user_demo
from reportbuilder.models import Connection, EmailVerification, MailConfiguration, Report
from reportbuilder.site_origin import inferred_service_url
from tests.test_mail_settings import payload

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('hosts, expected', [
    (['localhost', '127.0.0.1', 'wrb.writeaday.click'], 'https://wrb.writeaday.click'),
    (['WRB.WRITEADAY.CLICK.', 'wrb.writeaday.click'], 'https://wrb.writeaday.click'),
    (['one.example.com', 'two.example.com'], ''),
    (['*', '.example.com', 'localhost', '127.0.0.1', '[::1]'], ''),
])
def test_canonical_origin_uses_only_explicit_unambiguous_configuration(settings, hosts, expected):
    settings.ALLOWED_HOSTS = hosts
    assert inferred_service_url() == expected


def test_production_mail_uses_canonical_host_and_explicit_override(settings, monkeypatch):
    settings.DEBUG = False
    settings.ALLOWED_HOSTS = ['wrb.writeaday.click', '127.0.0.1']
    config = MailConfiguration.objects.create(pk=1)
    form = mail_settings.MailForm(payload(), configuration=config)
    assert form.is_valid(), form.errors
    form.save()
    assert mail_settings.MailForm(configuration=config).initial['site_url'] == 'https://wrb.writeaday.click'
    sender = Mock()
    monkeypatch.setattr(mail_settings, 'send_message', sender)
    user = get_user_model().objects.create_user('origin-member', email='member@example.com')
    # The request host must never select the production email link domain.
    request = RequestFactory().get('/', HTTP_HOST='attacker.example')
    email_verification.send_verification(user, request)
    assert 'https://wrb.writeaday.click/accounts/email/verify/' in sender.call_args.args[3]
    assert 'attacker.example' not in sender.call_args.args[3]
    config.options['site_url'] = 'https://canonical.example.com'
    config.save()
    user2 = get_user_model().objects.create_user('origin-member2', email='member2@example.com')
    email_verification.send_verification(user2, request)
    assert 'https://canonical.example.com/accounts/email/verify/' in sender.call_args.args[3]


def test_ambiguous_origin_is_visible_to_admin(client, settings):
    settings.DEBUG = False
    settings.ALLOWED_HOSTS = ['testserver', 'one.example.com', 'two.example.com']
    client.force_login(get_user_model().objects.create_user('origin-admin', is_staff=True))
    assert client.post('/settings/mail/', payload(), secure=True).status_code == 302
    page = client.get('/settings/mail/', secure=True)
    assert page.context['verification_origin_missing']
    assert '인증 링크 주소는 별도로 필요합니다' in page.content.decode()


def test_https_forms_keep_referer_csrf_protection(settings, monkeypatch):
    settings.DEBUG = True  # Static discovery only; HTTPS CSRF checks still run.
    settings.ALLOWED_HOSTS = ['wrb.writeaday.click']
    config = MailConfiguration.objects.create(pk=1)
    data = payload()
    data['site_url'] = 'https://wrb.writeaday.click'
    form = mail_settings.MailForm(data, configuration=config)
    assert form.is_valid(), form.errors
    form.save()
    sender = Mock()
    monkeypatch.setattr(mail_settings, 'send_message', sender)
    user = get_user_model().objects.create_user('https-member', email='member@example.com')
    EmailVerification.objects.create(user=user, required=True)
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    host = {'secure': True, 'HTTP_HOST': 'wrb.writeaday.click'}
    page = client.get('/accounts/email/', **host)
    assert page['Referrer-Policy'] == 'same-origin'
    token = client.cookies['csrftoken'].value
    valid = dict(host, HTTP_X_CSRFTOKEN=token, HTTP_REFERER='https://wrb.writeaday.click/accounts/email/')
    assert client.post('/accounts/logout/', **host).status_code == 403
    assert client.post('/accounts/logout/', **dict(valid, HTTP_REFERER='https://attacker.example/')).status_code == 403
    assert client.post('/accounts/email/resend/', **valid).status_code == 302
    assert sender.call_count == 1
    link = re.search(r'https://wrb.writeaday.click(/accounts/email/verify/\S+)', sender.call_args.args[3])[1]
    redirect = client.get(link, **host)
    assert redirect['Referrer-Policy'] == 'no-referrer'
    page = client.get(redirect.url, **host)
    assert page['Referrer-Policy'] == 'same-origin'
    assert client.post('/accounts/email/confirm/', **dict(valid, HTTP_REFERER='https://wrb.writeaday.click/accounts/email/confirm/')).status_code == 302
    assert EmailVerification.objects.get(user=user).verified_at
    assert client.post('/accounts/logout/', **valid).status_code == 302
    assert '_auth_user_id' not in client.session


def test_demo_executes_without_media_file_writes_and_user_upload_wins(tmp_path):
    user = get_user_model().objects.create_user('no-media-demo')
    with patch.object(FileSystemStorage, 'save', side_effect=PermissionError('read-only media')):
        assert prepare_user_demo(user)
    report = Report.objects.get(owner=user)
    connection = Connection.objects.get(owner=user)
    assert not connection.upload
    result = execute_dataset('csv', connection.runtime_config(), report.definition['datasets'][0], report.bindings[0])
    assert result['row_count'] == 65
    assert result['rows'][0]['amount'] == '100000'
    uploaded = tmp_path / 'replacement.csv'
    uploaded.write_text('department,customer,amount\nReplacement,Customer,123\n')
    config = dict(connection.runtime_config(), path=str(uploaded))
    assert introspect('csv', config)['objects'][0]['columns'][0]['name'] == 'department'
    result = execute_dataset('csv', config, report.definition['datasets'][0], report.bindings[0])
    assert result['row_count'] == 1
    assert result['rows'][0]['amount'] == '123'


def test_reset_survives_legacy_file_cleanup_failure(django_capture_on_commit_callbacks):
    user = get_user_model().objects.create_user('legacy-demo')
    assert prepare_user_demo(user)
    connection = Connection.objects.get(owner=user)
    connection.upload.name = 'legacy-demo.csv'
    connection.save()
    with patch.object(FileSystemStorage, 'delete', side_effect=PermissionError('read-only media')):
        with django_capture_on_commit_callbacks(execute=True):
            assert prepare_user_demo(user, reset=True)
    assert Report.objects.filter(owner=user).count() == 1
    assert Connection.objects.filter(owner=user).count() == 1
    assert not Connection.objects.get(owner=user).upload
