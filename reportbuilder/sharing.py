"""Revocable public links, scoped to one published revision and fixed parameters."""
import hashlib
import json
import secrets
from datetime import datetime

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_GET

from .analytics import record_report_access
from .analytics_views import owner_session
from .definition import DefinitionError, validate_parameters
from .data import DataError
from .models import PublicShare
from .services import execute_report
from django.core.exceptions import PermissionDenied


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
        for item in report.public_shares.order_by('-created_at')[:100]:
            status = '사용 가능'
            if item.revoked:
                status = '공유 해제'
            elif not publication or not publication.enabled or not report.enabled or item.revision_id != publication.revision_id:
                status = '게시 변경/중지'
            elif item.ends_at and now >= item.ends_at:
                status = '기간 만료'
            elif item.starts_at and now < item.starts_at:
                status = '시작 대기'
            rows.append({'id': str(item.pk), 'starts_at': item.starts_at, 'ends_at': item.ends_at, 'status': status, 'revoked': item.revoked})
        return JsonResponse({'shares': rows, 'parameters': publication.revision.definition.get('parameters', []) if publication else []})
    if not publication or not publication.enabled or not report.enabled or not report.owner.is_active:
        return JsonResponse({'message': '활성 보고서를 먼저 게시하세요.'}, status=400)
    try:
        data = json.loads(request.body)
        starts_at, ends_at = parse_time(data.get('starts_at')), parse_time(data.get('ends_at'))
        if ends_at and (ends_at <= timezone.now() or starts_at and ends_at <= starts_at):
            raise ValueError('종료 시각은 현재와 시작 시각보다 뒤여야 합니다.')
        parameters = data.get('parameters', {})
        if not isinstance(parameters, dict):
            raise ValueError('보고서 입력값을 확인하세요.')
        validate_parameters(publication.revision.definition, parameters)
    except (ValueError, TypeError, AttributeError, DefinitionError) as exc:
        return JsonResponse({'message': str(exc)}, status=400)
    token = secrets.token_urlsafe(32)
    PublicShare.objects.create(report=report, revision=publication.revision, token_hash=digest(token),
                               starts_at=starts_at, ends_at=ends_at, parameters=parameters)
    return JsonResponse({'url': request.build_absolute_uri('/shared/' + token + '/')}, status=201)


@require_GET
def public_report(request, token):
    share = PublicShare.objects.select_related('report__owner', 'report__publication').filter(token_hash=digest(token)).first()
    now = timezone.now()
    publication = getattr(share.report, 'publication', None) if share else None
    if (not share or share.revoked or not publication or not publication.enabled or not share.report.enabled
            or not share.report.owner.is_active or publication.revision_id != share.revision_id
            or share.starts_at and now < share.starts_at or share.ends_at and now >= share.ends_at):
        return secured(HttpResponse('<!doctype html><html lang="ko"><meta charset="utf-8"><title>공유 보고서</title><body><h1>이 공유 링크로 보고서를 열 수 없습니다.</h1><p>열람 기간이 아니거나 공유가 해제되었습니다. 공유한 사람에게 문의하세요.</p></body></html>', status=404))
    try:
        _, rendered = execute_report(share.report, share.report.owner, share.parameters, published=True)
    except (PermissionDenied, DefinitionError, DataError):
        return secured(HttpResponse('보고서를 표시할 수 없습니다. 공유한 사람에게 문의하세요.', status=503))
    # Rendering can take time: expiry/revocation/publication changes must still apply.
    share.refresh_from_db()
    now = timezone.now()
    from .models import Publication
    if (share.revoked or share.ends_at and now >= share.ends_at
            or not Publication.objects.filter(report=share.report, enabled=True, report__enabled=True,
                                               revision_id=share.revision_id, report__owner__is_active=True).exists()):
        return secured(HttpResponse('공유가 만료되거나 중지되었습니다.', status=404))
    response = secured(HttpResponse(rendered['html']))
    response['Content-Security-Policy'] = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"
    record_report_access(request, share.report, 'view')
    return response
