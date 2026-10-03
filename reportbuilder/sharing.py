"""Revocable public links, scoped to one published revision and fixed parameters."""
import hashlib
import json
import secrets
from datetime import datetime, timedelta

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.db.models import F, Q

from .analytics import record_report_access
from .analytics_views import owner_session
from .definition import DefinitionError, validate_parameters
from .data import DataError
from .models import PublicShare
from .services import render_public_report
from django.core.exceptions import PermissionDenied

MAX_ACTIVE_SHARES = 100
PUBLIC_REQUESTS_PER_MINUTE = 30


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def secured(response):
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response


def parse_time(value):
    if not value:
        return None
    result = datetime.fromisoformat(value)
    if timezone.is_naive(result):
        raise ValueError('열람 기간에 시간대가 필요합니다.')
    return result


@require_http_methods(['GET', 'POST', 'DELETE'])
@owner_session
def shares(request, report):
    publication = getattr(report, 'publication', None)
    if request.method == 'DELETE':
        try:
            data = json.loads(request.body)
            share = get_object_or_404(PublicShare, report=report, pk=data['id'])
        except (ValueError, KeyError, TypeError):
            return JsonResponse({'message': '공유 링크를 확인하세요.'}, status=400)
        share.revoked = True
        share.save(update_fields=['revoked'])
        return JsonResponse({'revoked': True})
    if request.method == 'GET':
        now = timezone.now()
        rows = []
        active = report.public_shares.filter(revoked=False).order_by('-created_at')
        revoked = report.public_shares.filter(revoked=True).order_by('-created_at')[:100]
        for item in list(active) + list(revoked):
            status = '사용 가능'
            if item.revoked:
                status = '공유 해제'
            elif not publication or not publication.enabled or not report.enabled or item.revision_id != publication.revision_id:
                status = '게시 변경/중지'
            elif item.ends_at and now >= item.ends_at:
                status = '기간 만료'
            elif item.starts_at and now < item.starts_at:
                status = '시작 대기'
            rows.append({'id': str(item.pk), 'starts_at': item.starts_at, 'ends_at': item.ends_at, 'status': status, 'revoked': item.revoked, 'password_protected': bool(item.password_hash)})
        return JsonResponse({'shares': rows, 'parameters': publication.revision.definition.get('parameters', []) if publication else []})
    if not publication or not publication.enabled or not report.enabled or not report.owner.is_active:
        return JsonResponse({'message': '활성 보고서를 먼저 게시하세요.'}, status=400)
    if report.public_shares.filter(revoked=False).count() >= MAX_ACTIVE_SHARES:
        return JsonResponse({'message': '활성 공유 링크는 보고서당 최대 100개입니다. 기존 링크를 해제한 뒤 다시 시도하세요.'}, status=429)
    try:
        data = json.loads(request.body)
        starts_at, ends_at = parse_time(data.get('starts_at')), parse_time(data.get('ends_at'))
        if ends_at and (ends_at <= timezone.now() or starts_at and ends_at <= starts_at):
            raise ValueError('종료 시각은 현재와 시작 시각보다 뒤여야 합니다.')
        parameters = data.get('parameters', {})
        password = data.get('password', '')
        if not isinstance(password, str) or password and not 8 <= len(password) <= 128:
            raise ValueError('공유 비밀번호는 8~128자로 입력하세요.')
        if not isinstance(parameters, dict):
            raise ValueError('보고서 입력값을 확인하세요.')
        validate_parameters(publication.revision.definition, parameters)
    except (ValueError, TypeError, AttributeError, DefinitionError) as exc:
        return JsonResponse({'message': str(exc)}, status=400)
    token = secrets.token_urlsafe(32)
    PublicShare.objects.create(report=report, revision=publication.revision, token_hash=digest(token),
                               starts_at=starts_at, ends_at=ends_at, parameters=parameters,
                               password_hash=make_password(password) if password else '')
    return JsonResponse({'url': request.build_absolute_uri('/shared/' + token + '/')}, status=201)


@require_http_methods(['GET', 'POST'])
def public_report(request, token):
    share = PublicShare.objects.select_related('report__owner', 'report__publication').filter(token_hash=digest(token)).first()
    now = timezone.now()
    publication = getattr(share.report, 'publication', None) if share else None
    if (not share or share.revoked or not publication or not publication.enabled or not share.report.enabled
            or not share.report.owner.is_active or publication.revision_id != share.revision_id
            or share.starts_at and now < share.starts_at or share.ends_at and now >= share.ends_at):
        return secured(HttpResponse('<!doctype html><html lang="ko"><meta charset="utf-8"><title>공유 보고서</title><body><h1>이 공유 링크로 보고서를 열 수 없습니다.</h1><p>열람 기간이 아니거나 공유가 해제되었습니다. 공유한 사람에게 문의하세요.</p></body></html>', status=404))
    cutoff = now - timedelta(minutes=1)
    reset = PublicShare.objects.filter(pk=share.pk).filter(
        Q(public_window_started__isnull=True) | Q(public_window_started__lt=cutoff)
    ).update(public_window_started=now, public_window_count=1)
    if not reset:
        allowed = PublicShare.objects.filter(
            pk=share.pk, public_window_started__gte=cutoff,
            public_window_count__lt=PUBLIC_REQUESTS_PER_MINUTE,
        ).update(public_window_count=F('public_window_count') + 1)
        if not allowed:
            response = secured(HttpResponse('요청이 너무 많습니다. 잠시 후 다시 시도하세요.', status=429))
            response['Retry-After'] = '60'
            return response
    password_hash = share.password_hash
    if password_hash:
        key = 'public_share_' + str(share.pk)
        grant = digest(share.password_hash)
        if request.session.get(key) != grant:
            error = None
            if request.method == 'POST':
                password = request.POST.get('password', '')
                if len(password) <= 128 and check_password(password, share.password_hash):
                    request.session[key] = grant
                    return secured(redirect('public_report', token=token))
                error = '비밀번호가 맞지 않습니다. 다시 입력하세요.'
            response = secured(render(request, 'reportbuilder/share_password.html', {'error': error},
                                      status=403 if error else 200))
            # Native form POSTs need a same-origin Origin for Django's CSRF check.
            # Cross-origin requests still receive no referrer and cannot submit the form.
            response['Referrer-Policy'] = 'same-origin'
            response['Content-Security-Policy'] = "default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
            return response
    try:
        rendered = render_public_report(share.report, share.report.owner, share.revision.definition,
                                        share.revision.bindings, share.parameters)
    except (PermissionDenied, DefinitionError, DataError):
        return secured(HttpResponse('보고서를 표시할 수 없습니다. 공유한 사람에게 문의하세요.', status=503))
    # Rendering can take time: expiry/revocation/publication changes must still apply.
    share.refresh_from_db()
    now = timezone.now()
    from .models import Publication
    if share.password_hash != password_hash:
        return secured(HttpResponse('공유 설정이 변경되었습니다. 새로고침한 뒤 다시 열어 주세요.', status=403))
    if (share.revoked or share.ends_at and now >= share.ends_at
            or not Publication.objects.filter(report=share.report, enabled=True, report__enabled=True,
                                               revision_id=share.revision_id, report__owner__is_active=True).exists()):
        return secured(HttpResponse('공유가 만료되거나 중지되었습니다.', status=404))
    response = secured(HttpResponse(rendered['html']))
    response['Content-Security-Policy'] = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"
    record_report_access(request, share.report, 'view')
    return response
