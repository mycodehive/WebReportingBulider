import hashlib
from django.contrib.auth.models import AnonymousUser
from django.conf import settings
from django.utils import timezone
from django.middleware.csrf import CsrfViewMiddleware
from django.utils.cache import patch_cache_control
from .models import ApiToken


class ApiAuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        request.api_token = None
        header = request.headers.get("Authorization", "")
        if header and request.path.startswith("/api/"):
            request.user = AnonymousUser()
            if header.startswith("Bearer "):
                digest = hashlib.sha256(header[7:].encode()).hexdigest()
                token = ApiToken.objects.select_related("user").filter(digest=digest, enabled=True,
                            expires_at__gt=timezone.now(), user__is_active=True).first()
                if token:
                    request.user, request.api_token = token.user, token
        response = self.get_response(request)
        if request.user.is_authenticated or request.path.startswith("/api/"):
            patch_cache_control(response, private=True, no_store=True)
        return response


class ApiAwareCsrfMiddleware(CsrfViewMiddleware):
    def process_view(self, request, callback, callback_args, callback_kwargs):
        # Bearer credentials cannot be sent automatically by a cross-site form.
        if getattr(request, "api_token", None) is not None:
            return None
        return super().process_view(request, callback, callback_args, callback_kwargs)


class EmailVerificationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.http import JsonResponse
        from django.shortcuts import redirect
        from .email_verification import needs_verification

        permitted = (request.path.startswith('/accounts/email/') or
                     request.path in {'/accounts/login/', '/accounts/logout/', '/accounts/signup/'} or
                     request.path.startswith(settings.STATIC_URL))
        if (not permitted and request.user.is_authenticated and not request.user.is_staff
                and needs_verification(request.user)):
            if request.path.startswith('/api/'):
                return JsonResponse({'code': 'EMAIL_VERIFICATION_REQUIRED', 'message': '메일 주소 인증을 먼저 완료하세요.'}, status=403)
            return redirect('email_verification_notice')
        return self.get_response(request)
