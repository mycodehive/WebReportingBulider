from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from reportbuilder import mail_settings as mail
from reportbuilder.models import MailConfiguration, SettingsMenu, SettingsSection

pytestmark = pytest.mark.django_db


def payload(provider='smtp'):
    return dict(provider=provider, smtp_encryption='tls', smtp_host='smtp.example.com', smtp_port=587,
                smtp_username='sender', smtp_password='secret-smtp', mailgun_domain='mg.example.com',
                mailgun_key='secret-mailgun', mailgun_endpoint='api.mailgun.net',
                ses_access_key='secret-access', ses_secret_key='secret-ses', ses_region='ap-northeast-2',
                sender_email='sender@example.com', sender_name='회사 메일', action='save')


@pytest.fixture
def admin_client():
    client = Client()
    client.force_login(get_user_model().objects.create_user('mail-admin', is_staff=True))
    return client


def save_config(admin_client, provider='smtp'):
    assert admin_client.post('/settings/mail/', payload(provider)).status_code == 302
    return MailConfiguration.objects.get(pk=1)


def test_access_and_navigation(client, admin_client):
    anon = Client()
    assert anon.get('/settings/mail/').status_code == 302
    user = get_user_model().objects.create_user('mail-member')
    client.force_login(user)
    for method in (client.get, client.post):
        assert method('/settings/mail/').status_code == 403
    basic = SettingsSection.objects.get(key='basic')
    basic.staff_only = False
    basic.save()
    SettingsMenu.objects.filter(key='mail').update(staff_only=False)
    assert b'href="/settings/mail/"' not in client.get(f'/settings/sections/{basic.pk}/').content
    assert b'href="/settings/mail/"' in admin_client.get('/settings/mail/').content


def test_encryption_and_preservation(admin_client):
    config = save_config(admin_client)
    assert 'secret-' not in config.encrypted_credentials
    assert not any(k in config.options for k in mail.SECRET_FIELDS)
    assert mail.secrets(config)['smtp_password'] == 'secret-smtp'
    response = admin_client.get('/settings/mail/')
    assert 'no-store' in response['Cache-Control']
    assert b'secret-smtp' not in response.content
    data = payload()
    for key in mail.SECRET_FIELDS:
        data[key] = ''
    data['sender_name'] = '새 이름'
    assert admin_client.post('/settings/mail/', data).status_code == 302
    config.refresh_from_db()
    assert mail.secrets(config)['ses_secret_key'] == 'secret-ses'
    data['smtp_host'] = 'other.example.com'
    assert admin_client.post('/settings/mail/', data).status_code == 200
    config.refresh_from_db()
    assert config.options['smtp_host'] == 'smtp.example.com'


@pytest.mark.parametrize('provider,field,value', [('mailgun', 'mailgun_endpoint', 'evil.example.com'),
    ('mailgun', 'mailgun_domain', '../evil'), ('ses', 'ses_region', 'evil.example.com'),
    ('smtp', 'smtp_encryption', 'none'), ('smtp', 'smtp_host', 'https://smtp.example.com'),
    ('smtp', 'sender_name', 'name\r\nBcc: hidden@example.com')])
def test_validation(admin_client, provider, field, value):
    data = payload(provider)
    data[field] = value
    response = admin_client.post('/settings/mail/', data)
    assert response.status_code == 200
    assert response.context['form'].errors
    assert not MailConfiguration.objects.get().options


def test_test_delivery_saved_only_cooldown_and_safe_error(admin_client, monkeypatch):
    config = save_config(admin_client)
    sender = Mock(side_effect=RuntimeError('secret-smtp remote credential leak'))
    monkeypatch.setattr(mail, 'send_test', sender)
    response = admin_client.post('/settings/mail/', {'action': 'test', 'recipient': 'target@example.com', 'smtp_host': 'evil.example.com'})
    assert b'secret-smtp' not in response.content
    assert sender.call_args.args[0].options == config.options
    assert '발송에 실패' in response.content.decode()
    sender.reset_mock()
    response = admin_client.post('/settings/mail/', {'action': 'test', 'recipient': 'target@example.com'})
    assert '30초' in response.content.decode()
    sender.assert_not_called()
    MailConfiguration.objects.update(last_test_at=None)
    sender.side_effect = None
    assert admin_client.post('/settings/mail/', {'action': 'test', 'recipient': 'target@example.com'}).status_code == 302


def test_test_requires_saved_config_valid_recipient_and_csrf(admin_client, monkeypatch):
    sender = Mock()
    monkeypatch.setattr(mail, 'send_test', sender)
    admin_client.post('/settings/mail/', {'action': 'test', 'recipient': 'target@example.com'})
    save_config(admin_client)
    admin_client.post('/settings/mail/', {'action': 'test', 'recipient': 'target@example.com,other@example.com'})
    sender.assert_not_called()
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(get_user_model().objects.get(username='mail-admin'))
    assert csrf_client.post('/settings/mail/', {'action': 'test', 'recipient': 'target@example.com'}).status_code == 403


@pytest.mark.parametrize('provider', ['smtp', 'mailgun', 'ses'])
def test_transport_contract(admin_client, monkeypatch, provider):
    config = save_config(admin_client, provider)
    if provider == 'smtp':
        backend = Mock()
        monkeypatch.setattr(mail, 'EmailBackend', backend)
        email = Mock()
        email.return_value.send.return_value = 1
        monkeypatch.setattr(mail, 'EmailMessage', email)
        backend.return_value.__enter__ = Mock()
        backend.return_value.__exit__ = Mock()
    elif provider == 'mailgun':
        backend = Mock()
        client = Mock()
        backend.return_value.__enter__ = Mock(return_value=client)
        backend.return_value.__exit__ = Mock()
        monkeypatch.setattr(mail.httpx, 'Client', backend)
    else:
        backend = Mock()
        monkeypatch.setattr(mail.boto3, 'client', backend)
    mail.send_test(config, 'target@example.com')
    if provider == 'smtp':
        assert backend.call_args.kwargs['use_tls'] is True
        assert backend.call_args.kwargs['password'] == 'secret-smtp'
        assert email.call_args.args[3] == ['target@example.com']
    elif provider == 'mailgun':
        assert backend.call_args.kwargs['follow_redirects'] is False
        assert backend.call_args.kwargs['trust_env'] is False
        assert client.post.call_args.args[0] == 'https://api.mailgun.net/v3/mg.example.com/messages'
        assert client.post.call_args.kwargs['auth'] == ('api', 'secret-mailgun')
        assert client.post.call_args.kwargs['files']['to'] == (None, 'target@example.com')
    else:
        assert backend.call_args.kwargs['aws_access_key_id'] == 'secret-access'
        assert backend.call_args.kwargs['endpoint_url'] == 'https://email.ap-northeast-2.amazonaws.com'
        args = backend.return_value.send_email.call_args.kwargs
        assert args['Destination'] == {'ToAddresses': ['target@example.com']}
        assert args['Content']['Simple']['Subject']['Charset'] == 'UTF-8'
        backend.return_value.close.assert_called_once()
