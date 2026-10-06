from django.contrib import messages
from django.contrib.auth import login
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .email_verification import VerificationError, reserve_public_request, send_verification
from .models import EmailVerification
from .demo import prepare_user_demo
from .signup_forms import SignupForm


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not reserve_public_request(request):
            form.add_error(None, "가입 요청이 너무 많습니다. 잠시 후 다시 시도하세요.")
            return render(request, "reportbuilder/signup.html", {"form": form})
        with transaction.atomic():
            user = form.save()
            EmailVerification.objects.create(user=user, required=True)
            demo_ready = prepare_user_demo(user)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "가입이 완료되었습니다.")
        if demo_ready:
            messages.info(request, "데모 보고서를 준비했습니다. 보고서 라이브러리에서 확인하세요.")
        else:
            messages.warning(request, "계정은 정상적으로 생성되었습니다. 데모 보고서는 메일 인증 완료 후 보고서 라이브러리에서 다시 준비할 수 있습니다.")
        try:
            send_verification(user, request)
            messages.info(request, "인증 메일을 발송했습니다. 메일 주소를 인증하면 서비스를 이용할 수 있습니다.")
        except VerificationError as exc:
            messages.error(request, str(exc))
        return redirect('email_verification_notice')
    return render(request, "reportbuilder/signup.html", {"form": form, "next": request.GET.get("next", "")})
