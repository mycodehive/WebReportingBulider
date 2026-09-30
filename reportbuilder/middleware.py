import hashlib
from django.contrib.auth.models import AnonymousUser
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
