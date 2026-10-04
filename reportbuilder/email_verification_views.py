import hashlib

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .email_verification import (SESSION_PROOF, VerificationError, is_verified, reserve_public_request,
                                 send_verification, valid_proof)
from .models import EmailVerification


def page(request, state, **context):
    response = render(request, 'reportbuilder/email_verification.html', {'state': state, **context})
    response['Referrer-Policy'] = 'no-referrer'
    response['Cache-Control'] = 'no-store'
    return response


@login_required
@never_cache
@require_GET
def notice(request):
    return page(request, 'complete' if is_verified(request.user) else 'pending', email=request.user.email)


@login_required
@never_cache
@require_POST
def resend(request):
    if not reserve_public_request(request):
        messages.error(request, '인증 메일 요청이 너무 많습니다. 잠시 후 다시 시도하세요.')
    else:
        try:
            result = send_verification(request.user, request)
            messages.success(request, '이미 인증된 메일 주소입니다.' if result == 'verified' else '인증 메일을 발송했습니다. 받은 편지함과 스팸함을 확인하세요.')
        except VerificationError as exc:
            messages.error(request, str(exc))
    return redirect('email_verification_notice')


@never_cache
@require_GET
def link(request, verification_id, token):
    request.session.pop(SESSION_PROOF, None)
    if len(token) > 128:
        return page(request, 'invalid')
    digest = hashlib.sha256(token.encode()).hexdigest()
    verification = EmailVerification.objects.select_related('user').filter(pk=verification_id).first()
    if not valid_proof(verification, digest):
        return page(request, 'invalid')
    if request.user.is_authenticated and request.user.pk != verification.user_id:
        return page(request, 'wrong-account')
    # Do not consume a proof on GET: email scanners may prefetch the link.
    # Remove the bearer secret from the URL before showing the confirmation form.
    request.session[SESSION_PROOF] = {'id': verification.pk, 'digest': digest}
    response = redirect('email_verification_confirm')
    response['Referrer-Policy'] = 'no-referrer'
    return response


@never_cache
@require_http_methods(['GET', 'POST'])
def confirm(request):
    proof = request.session.get(SESSION_PROOF, {})
    verification = EmailVerification.objects.select_related('user').filter(pk=proof.get('id')).first()
    if not valid_proof(verification, proof.get('digest', '')):
        request.session.pop(SESSION_PROOF, None)
        return page(request, 'invalid')
    if request.user.is_authenticated and request.user.pk != verification.user_id:
        return page(request, 'wrong-account')
    if request.method == 'GET':
        return page(request, 'confirm')
    # Conditional update makes concurrent confirmations single-use, including SQLite.
    updated = EmailVerification.objects.filter(pk=verification.pk, token_digest=proof['digest'],
                                               token_context=verification.token_context, expires_at__gt=timezone.now(),
                                               user__email=verification.user.email, user__password=verification.user.password, user__is_active=True).update(
        verified_at=timezone.now(), token_digest='', token_context='', expires_at=None)
    request.session.pop(SESSION_PROOF, None)
    if not updated:
        return page(request, 'invalid')
    request.session['email_verification_completed'] = True
    messages.success(request, '메일 주소 인증이 완료되었습니다.')
    # Possession of an email proof never signs the visitor into the user's account.
    return redirect('email_verification_complete')


@never_cache
@require_GET
def complete(request):
    done = is_verified(request.user) if request.user.is_authenticated else request.session.get('email_verification_completed', False)
    return page(request, 'complete' if done else 'invalid')
