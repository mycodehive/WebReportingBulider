from django.contrib import messages
from django.contrib.auth import login
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .demo import prepare_user_demo
from .signup_forms import SignupForm


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            demo_ready = prepare_user_demo(user)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "가입이 완료되었습니다.")
        if demo_ready:
            messages.info(request, "데모 보고서를 준비했습니다. 보고서 라이브러리에서 확인하세요.")
        else:
            messages.warning(request, "데모 보고서 생성에 실패했습니다. 보고서 라이브러리에서 다시 시도할 수 있습니다.")
        next_url = request.POST.get("next", "")
        if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect(reverse("dashboard"))
    return render(request, "reportbuilder/signup.html", {"form": form, "next": request.GET.get("next", "")})
