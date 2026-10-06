import hashlib
import re
from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import signing
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from reportbuilder import email_verification as verification
from reportbuilder import mail_settings
from reportbuilder.admin_email_verification import SALT
from reportbuilder.models import ApiToken, EmailVerification, EmailVerificationLimit, MailConfiguration, Report
from tests.test_mail_settings import payload

pytestmark = pytest.mark.django_db


@pytest.fixture
def transport(monkeypatch, settings):
    settings.DEBUG = True
    config = MailConfiguration.objects.create(pk=1)
    form = mail_settings.MailForm(payload(), configuration=config)
    assert form.is_valid(), form.errors
    form.save()
    sender = Mock()
    monkeypatch.setattr(mail_settings, 'send_message', sender)
    return sender


@pytest.fixture
def member():
    return get_user_model().objects.create_user('verify-member', email='member@example.com', password='Verify!Password2026')


def issue(member, transport):
    verification.send_verification(member, RequestFactory().get('/', HTTP_HOST='testserver'))
    body = transport.call_args.args[3]
    path = re.search(r'http://testserver(/accounts/email/verify/\S+)', body)[1]
    return path


def confirm(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert response.url == reverse('email_verification_confirm')
    return client.post(response.url)


def batch_ticket(client, users):
    response = client.post(reverse('admin:auth_user_changelist'), {
        'action': 'send_email_verifications', '_selected_action': [str(user.pk) for user in users],
    })
    assert response.status_code == 200
    return response.context_data['ticket']


def test_signup_mail_and_required_gate(client, transport, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    response = client.post('/accounts/signup/', {'username': 'verified-new', 'email': 'new@example.com',
                           'password1': 'Distinctive!BlueRiver2026', 'password2': 'Distinctive!BlueRiver2026', 'next': '/reports/'})
    assert response.url == '/accounts/email/'
    user = get_user_model().objects.get(username='verified-new')
    record = EmailVerification.objects.get(user=user)
    assert record.required and not record.verified_at
    assert Report.objects.filter(owner=user, name='매출 현황 예제').exists()
    assert transport.call_args.args[1] == 'new@example.com'
    assert '_auth_user_id' in client.session
    assert client.get('/reports/').url == '/accounts/email/'
    assert client.post('/api/reports/', {}).status_code == 403
    assert client.post('/accounts/logout/').status_code == 302
    assert client.login(username=user.username, password='Distinctive!BlueRiver2026')
    assert client.get('/reports/').url == '/accounts/email/'
    path = re.search(r'http://testserver(/accounts/email/verify/\S+)', transport.call_args.args[3])[1]
    assert confirm(client, path).status_code == 302
    assert client.get('/reports/').status_code == 200


def test_get_does_not_consume_single_use_proof_and_no_automatic_login(client, member, transport):
    path = issue(member, transport)
    record = EmailVerification.objects.get(user=member)
    token = path.rstrip('/').split('/')[-1]
    assert record.token_digest == hashlib.sha256(token.encode()).hexdigest()
    assert token not in record.token_digest
    assert client.get(path).status_code == 302
    record.refresh_from_db()
    assert record.verified_at is None
    page = client.get('/accounts/email/confirm/')
    assert page['Referrer-Policy'] == 'same-origin'
    assert token.encode() not in page.content
    assert '메일 인증 완료' in page.content.decode()
    assert client.post('/accounts/email/confirm/').status_code == 302
    record.refresh_from_db()
    assert record.verified_at and record.token_digest == '' and record.expires_at is None
    assert '_auth_user_id' not in client.session
    assert client.post('/accounts/email/confirm/').status_code == 200
    assert '인증 링크를 사용할 수 없습니다' in client.get(path).content.decode()
    assert '메일 인증이 완료' in client.get('/accounts/email/complete/').content.decode()


@pytest.mark.parametrize('change', ['tamper', 'expired', 'email', 'password', 'inactive'])
def test_invalid_proofs(client, member, transport, change):
    path = issue(member, transport)
    if change == 'tamper':
        path = path[:-2] + ('a' if path[-2] != 'a' else 'b') + '/'
    elif change == 'expired':
        EmailVerification.objects.filter(user=member).update(expires_at=timezone.now() - timedelta(seconds=1))
    elif change == 'email':
        member.email = 'changed@example.com'
        member.save()
    elif change == 'password':
        member.set_password('Changed!Password2026')
        member.save()
    else:
        member.is_active = False
        member.save()
    assert client.get(path).status_code == 200
    assert client.post('/accounts/email/confirm/').status_code == 200
    assert not EmailVerification.objects.get(user=member).verified_at


def test_resend_replaces_proof_and_limits_by_user(client, member, transport):
    path = issue(member, transport)
    client.force_login(member)
    response = client.get('/accounts/email/resend/')
    assert response.status_code == 405
    assert client.post('/accounts/email/resend/').status_code == 302
    assert transport.call_count == 1
    for _ in range(4):
        EmailVerification.objects.filter(user=member).update(last_sent_at=timezone.now() - timedelta(seconds=61))
        client.post('/accounts/email/resend/')
    assert transport.call_count == 5
    assert '인증 링크를 사용할 수 없습니다' in client.get(path).content.decode()
    EmailVerification.objects.filter(user=member).update(last_sent_at=timezone.now() - timedelta(seconds=61))
    client.post('/accounts/email/resend/')
    assert transport.call_count == 5
    EmailVerification.objects.filter(user=member).update(window_started_at=timezone.now() - timedelta(hours=2))
    client.post('/accounts/email/resend/')
    assert transport.call_count == 6


def test_confirmation_wrong_account_and_csrf(client, member, transport):
    path = issue(member, transport)
    wrong = get_user_model().objects.create_user('wrong-account')
    client.force_login(wrong)
    assert '다른 계정' in client.get(path).content.decode()
    assert not EmailVerification.objects.get(user=member).verified_at
    csrf = Client(enforce_csrf_checks=True)
    assert csrf.get(path).status_code == 302
    assert csrf.post('/accounts/email/confirm/').status_code == 403
    csrf.force_login(member)
    assert csrf.post('/accounts/email/resend/').status_code == 403


def test_delivery_failure_keeps_account_pending_and_clears_proof(client, transport, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    transport.side_effect = RuntimeError('credential-secret or provider response')
    response = client.post('/accounts/signup/', {'username': 'failed-mail', 'email': 'failed@example.com',
                           'password1': 'Distinctive!BlueRiver2026', 'password2': 'Distinctive!BlueRiver2026'})
    assert response.status_code == 302
    user = get_user_model().objects.get(username='failed-mail')
    record = EmailVerification.objects.get(user=user)
    assert record.required and not record.token_digest
    page = client.get('/accounts/email/').content.decode()
    assert 'credential-secret' not in page and '인증 메일을 보내지 못했습니다' in page
    assert client.get('/reports/').status_code == 302


def test_admin_batch_ticket_permissions_results_and_legacy_access(client, member, transport):
    root = get_user_model().objects.create_superuser('verify-root', 'root@example.com', 'Root!Password2026')
    missing = get_user_model().objects.create_user('no-email')
    inactive = get_user_model().objects.create_user('inactive', email='inactive@example.com', is_active=False)
    done = get_user_model().objects.create_user('done', email='done@example.com')
    EmailVerification.objects.create(user=done, email=done.email, verified_at=timezone.now())
    outsider = get_user_model().objects.create_user('unselected', email='unselected@example.com')
    client.force_login(root)
    ticket = batch_ticket(client, [member, missing, inactive, done])
    endpoint = reverse('admin:auth_user_email_verification_send')
    for user, expected in [(missing, 'error'), (inactive, 'skipped'), (done, 'verified'), (member, 'sent')]:
        response = client.post(endpoint, {'ticket': ticket, 'user_id': str(user.pk)})
        assert response.json()['status'] == expected
    assert transport.call_count == 1
    assert client.post(endpoint, {'ticket': ticket, 'user_id': str(outsider.pk)}).status_code == 400
    assert client.post(endpoint, {'ticket': ticket + 'x', 'user_id': str(member.pk)}).status_code == 400
    other_admin = get_user_model().objects.create_superuser('other-verify-root', 'other@example.com', 'Root!Password2026')
    client.force_login(other_admin)
    assert client.post(endpoint, {'ticket': ticket, 'user_id': str(member.pk)}).status_code == 400
    client.force_login(member)
    assert client.get('/reports/').status_code == 200
    assert client.post(endpoint, {'ticket': ticket, 'user_id': str(member.pk)}).status_code != 200


def test_admin_status_filter_and_continuation_after_failed_delivery(client, member, transport):
    admin = get_user_model().objects.create_superuser('verify-admin', 'root@example.com', 'Root!Password2026')
    other = get_user_model().objects.create_user('next-member', email='next@example.com')
    client.force_login(admin)
    ticket = batch_ticket(client, [member, other])
    endpoint = reverse('admin:auth_user_email_verification_send')
    transport.side_effect = [RuntimeError('secret'), None]
    response = client.post(endpoint, {'ticket': ticket, 'user_id': str(member.pk)})
    assert response.json()['status'] == 'error' and b'secret' not in response.content
    assert client.post(endpoint, {'ticket': ticket, 'user_id': str(other.pk)}).json()['status'] == 'sent'
    EmailVerification.objects.filter(user=other).update(verified_at=timezone.now())
    response = client.get(reverse('admin:auth_user_changelist') + '?email_verified=yes')
    assert list(response.context['cl'].queryset) == [other]
    page = client.get(reverse('admin:auth_user_change', args=[other.pk]))
    assert '메일 인증 일시' in page.content.decode()
    limited = get_user_model().objects.create_user('limited-staff', is_staff=True)
    limited.user_permissions.add(Permission.objects.get(codename='view_user'))
    client.force_login(limited)
    limited_ticket = signing.dumps({'actor': str(limited.pk), 'users': [str(member.pk)]}, salt=SALT)
    assert client.post(endpoint, {'ticket': limited_ticket, 'user_id': str(member.pk)}).status_code == 403


def test_canonical_origin_production_and_host_header(client, member, transport, settings):
    config = MailConfiguration.objects.get(pk=1)
    config.options['site_url'] = 'https://reports.example.com'
    config.save()
    request = RequestFactory().get('/', HTTP_HOST='attacker.example.com')
    settings.DEBUG = False
    verification.send_verification(member, request)
    assert 'https://reports.example.com/accounts/email/verify/' in transport.call_args.args[3]
    assert 'attacker.example.com' not in transport.call_args.args[3]
    config.options['site_url'] = ''
    config.save()
    other = get_user_model().objects.create_user('origin-required', email='origin@example.com')
    with pytest.raises(verification.VerificationError, match='서비스 주소'):
        verification.send_verification(other, request)
    config.options['site_url'] = 'http://reports.example.com'
    config.save()
    with pytest.raises(verification.VerificationError):
        verification.send_verification(other, request)


def test_public_limit_private_ip_digest_and_bearer_gate(client, member, transport):
    request = RequestFactory().get('/', REMOTE_ADDR='192.0.2.123')
    assert all(verification.reserve_public_request(request) for _ in range(20))
    assert verification.reserve_public_request(request) is False
    assert '192.0.2.123' not in EmailVerificationLimit.objects.get().key
    EmailVerification.objects.create(user=member, required=True)
    token = 'pending-api-token'
    ApiToken.objects.create(user=member, name='pending', digest=hashlib.sha256(token.encode()).hexdigest(),
                            expires_at=timezone.now() + timedelta(hours=1), scopes=['read'])
    response = client.get('/api/reports/', HTTP_AUTHORIZATION='Bearer ' + token)
    assert response.status_code == 403
    assert response.json()['code'] == 'EMAIL_VERIFICATION_REQUIRED'


def test_legacy_whitespace_email_and_proxy_limit(client, member, transport, settings):
    member.email = ' Member@Example.com '
    member.save()
    path = issue(member, transport)
    assert transport.call_args.args[1] == 'member@example.com'
    assert confirm(client, path).status_code == 302
    assert verification.is_verified(member)
    settings.REPORT_TRUSTED_PROXIES = ['127.0.0.1/32']
    factory = RequestFactory()
    first = factory.get('/', REMOTE_ADDR='127.0.0.1', HTTP_X_FORWARDED_FOR='192.0.2.1')
    second = factory.get('/', REMOTE_ADDR='127.0.0.1', HTTP_X_FORWARDED_FOR='192.0.2.2')
    assert all(verification.reserve_public_request(first) for _ in range(20))
    assert not verification.reserve_public_request(first)
    assert verification.reserve_public_request(second)
    settings.REPORT_TRUSTED_PROXIES = []
    first = factory.get('/', REMOTE_ADDR='192.0.2.3', HTTP_X_FORWARDED_FOR='192.0.2.4')
    second = factory.get('/', REMOTE_ADDR='192.0.2.3', HTTP_X_FORWARDED_FOR='192.0.2.5')
    assert all(verification.reserve_public_request(first) for _ in range(20))
    assert not verification.reserve_public_request(second)
