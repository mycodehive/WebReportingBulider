"""Bounded individual requests keep selected-user mail delivery out of long admin POSTs."""
from django.contrib import admin, messages
from django.core import signing
from django.db.models import Exists, OuterRef, Subquery
from django.db.models.functions import Lower, Trim
from django.http import HttpResponseForbidden, JsonResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse

from .email_verification import VerificationError, send_verification
from .models import EmailVerification

SALT = 'admin-email-verification-batch'


class EmailStatusFilter(admin.SimpleListFilter):
    title = '메일 인증'
    parameter_name = 'email_verified'

    def lookups(self, request, modeladmin):
        return [('yes', '인증 완료'), ('no', '미인증')]

    def queryset(self, request, queryset):
        if self.value() in {'yes', 'no'}:
            return queryset.filter(_email_verified=self.value() == 'yes')
        return queryset


@admin.action(description='메일 인증 메일 전송', permissions=['change'])
def send_email_verifications(modeladmin, request, queryset):
    if queryset.count() > 100:
        modeladmin.message_user(request, '한 번에 최대 100명을 선택하세요.', level=messages.ERROR)
        return None
    users = list(queryset.order_by('pk'))
    payload = [{'id': str(user.pk), 'username': user.get_username(), 'email': user.email} for user in users]
    ticket = signing.dumps({'actor': str(request.user.pk), 'users': [item['id'] for item in payload]}, salt=SALT, compress=True)
    return TemplateResponse(request, 'admin/reportbuilder/email_verification_send.html', {
        **modeladmin.admin_site.each_context(request), 'opts': modeladmin.model._meta,
        'title': '메일 인증 메일 전송', 'recipients': payload, 'ticket': ticket,
        'send_url': reverse('admin:auth_user_email_verification_send'),
        'list_url': reverse('admin:auth_user_changelist'),
    })


class EmailVerificationAdminMixin:
    @admin.display(boolean=True, description='메일 인증', ordering='_email_verified')
    def email_verified(self, obj):
        return getattr(obj, '_email_verified', False)

    @admin.display(description='메일 인증 일시')
    def email_verified_on(self, obj):
        return getattr(obj, '_email_verified_at', None)

    def get_queryset(self, request):
        verification = EmailVerification.objects.filter(user_id=OuterRef('pk'), email=Lower(Trim(OuterRef('email'))), verified_at__isnull=False)
        return super().get_queryset(request).annotate(_email_verified=Exists(verification),
                                                      _email_verified_at=Subquery(verification.values('verified_at')[:1]))

    def get_urls(self):
        return [path('email-verification-send/', self.admin_site.admin_view(self.email_verification_send_view),
                     name='auth_user_email_verification_send')] + super().get_urls()

    def email_verification_send_view(self, request):
        if request.method != 'POST':
            return JsonResponse({'message': 'POST 요청만 허용합니다.'}, status=405)
        if not self.has_change_permission(request):
            return HttpResponseForbidden('사용자 변경 권한이 필요합니다.')
        try:
            payload = signing.loads(request.POST.get('ticket', ''), salt=SALT, max_age=3600)
            user_id = request.POST.get('user_id', '')
            if payload['actor'] != str(request.user.pk) or user_id not in payload['users']:
                raise ValueError
        except (signing.BadSignature, ValueError, TypeError, KeyError):
            return JsonResponse({'status': 'error', 'message': '발송 대상 정보가 만료되었거나 올바르지 않습니다. 사용자를 다시 선택하세요.'}, status=400)
        user = self.get_queryset(request).filter(pk=user_id).first()
        if not user or not self.has_change_permission(request, user):
            return JsonResponse({'status': 'error', 'message': '발송 대상에 접근할 수 없습니다.'}, status=403)
        if not user.is_active:
            return JsonResponse({'status': 'skipped', 'message': '비활성 사용자 · 제외'})
        try:
            result = send_verification(user, request)
            if result == 'sent':
                self.log_change(request, user, '메일 인증 메일 전송')
            return JsonResponse({'status': result, 'message': '발송 접수 완료' if result == 'sent' else '이미 인증 완료 · 제외'})
        except VerificationError as exc:
            return JsonResponse({'status': 'error', 'message': str(exc)})
