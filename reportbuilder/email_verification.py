"""Expiring single-use email proofs shared by signup and the user admin action."""
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from . import mail_settings
from .analytics import client_address
from .models import EmailVerification, EmailVerificationLimit, MailConfiguration

TOKEN_LIFETIME = timedelta(hours=24)
RESEND_DELAY = timedelta(seconds=60)
SESSION_PROOF = 'email_verification_proof'


class VerificationError(Exception):
    """Safe UI message: never include provider or credential details."""


def normalized_email(user):
    return user.email.strip().lower()


def is_verified(user, verification=None):
    if verification is None:
        verification = EmailVerification.objects.filter(user=user).first()
    return bool(verification and verification.verified_at and verification.email == normalized_email(user))


def needs_verification(user):
    verification = EmailVerification.objects.filter(user=user).first()
    return bool(verification and verification.required and not is_verified(user, verification))


def context_digest(user):
    # Changing the password or email invalidates all previously issued proofs.
    return salted_hmac('email-verification-context', f'{user.pk}:{normalized_email(user)}:{user.password}').hexdigest()


def reserve_public_request(request):
    now = timezone.now()
    key = salted_hmac('email-verification-ip', str(client_address(request) or 'unknown')).hexdigest()
    EmailVerificationLimit.objects.filter(window_started_at__lt=now - timedelta(days=1)).delete()
    EmailVerificationLimit.objects.get_or_create(key=key, defaults={'window_started_at': now})
    EmailVerificationLimit.objects.filter(key=key, window_started_at__lte=now - timedelta(hours=1)).update(window_started_at=now, count=0)
    return bool(EmailVerificationLimit.objects.filter(key=key, count__lt=20).update(count=F('count') + 1))


def delivery_configuration(request):
    config = MailConfiguration.objects.filter(pk=1).first()
    if not config or not mail_settings.MailForm(config.options, configuration=config).is_valid():
        raise VerificationError('메일 발송 설정이 준비되지 않았습니다. 관리자에게 문의하세요.')
    origin = config.options.get('site_url', '')
    if not origin and settings.DEBUG:
        origin = request.build_absolute_uri('/').rstrip('/')
    parts = urlsplit(origin)
    if (parts.scheme not in ({'http', 'https'} if settings.DEBUG else {'https'}) or not parts.hostname
            or parts.username or parts.password or parts.path.strip('/') or parts.query or parts.fragment):
        raise VerificationError('관리자가 메일 설정의 서비스 주소를 지정해야 인증 메일을 보낼 수 있습니다.')
    return config, origin.rstrip('/')


def send_verification(user, request):
    if not user.is_active:
        raise VerificationError('비활성 사용자는 발송 대상에서 제외합니다.')
    email = normalized_email(user)
    try:
        validate_email(email)
    except ValidationError:
        raise VerificationError('사용자의 유효한 메일 주소를 먼저 등록하세요.') from None
    if is_verified(user):
        return 'verified'
    try:
        config, origin = delivery_configuration(request)
    except VerificationError:
        raise
    except Exception:
        raise VerificationError('메일 설정을 읽지 못했습니다. 관리자에게 문의하세요.') from None
    verification, _ = EmailVerification.objects.get_or_create(user=user)
    now = timezone.now()
    EmailVerification.objects.filter(pk=verification.pk).filter(
        Q(window_started_at__isnull=True) | Q(window_started_at__lte=now - timedelta(hours=1))
    ).update(window_started_at=now, send_count=0)
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    claimed = EmailVerification.objects.filter(pk=verification.pk, send_count__lt=5).filter(
        Q(verified_at__isnull=True) | ~Q(email=email)
    ).filter(
        Q(last_sent_at__isnull=True) | Q(last_sent_at__lte=now - RESEND_DELAY)
    ).update(email=email, verified_at=None, token_digest=digest, token_context=context_digest(user),
             expires_at=now + TOKEN_LIFETIME, last_sent_at=now, send_count=F('send_count') + 1)
    if not claimed:
        raise VerificationError('인증 메일은 60초 간격, 사용자별 시간당 5회까지 요청할 수 있습니다.')
    url = origin + reverse('email_verification_link', args=[verification.pk, token])
    body = ('WebReportingBuilder 메일 주소 인증을 요청했습니다.\n\n'
            f'다음 링크를 열고 「메일 인증 완료」 버튼을 눌러 주세요.\n{url}\n\n'
            '링크는 24시간 동안 유효하며 한 번만 사용할 수 있습니다. 다시 발송하면 이전 링크는 무효화됩니다.\n'
            '본인이 요청하지 않았다면 이 메일을 무시하세요. 계정의 비밀번호는 변경되지 않습니다.')
    try:
        mail_settings.send_message(config, email, '[WebReportingBuilder] 메일 주소 인증', body)
    except Exception:
        EmailVerification.objects.filter(pk=verification.pk, token_digest=digest).update(token_digest='', token_context='', expires_at=None)
        raise VerificationError('인증 메일을 보내지 못했습니다. 잠시 후 재발송하거나 관리자에게 문의하세요.') from None
    return 'sent'


def valid_proof(verification, digest):
    return bool(verification and verification.user.is_active and verification.token_digest
                and constant_time_compare(verification.token_digest, digest)
                and verification.expires_at and verification.expires_at > timezone.now()
                and verification.email == normalized_email(verification.user)
                and constant_time_compare(verification.token_context, context_digest(verification.user)))
