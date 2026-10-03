import io

from django.contrib import messages
from django.contrib.auth import login
from django.core.management import call_command
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .signup_forms import SignupForm


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            call_command("seed_demo", user_id=str(user.pk), stdout=io.StringIO())
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "가입이 완료되었습니다. 데모 보고서도 준비했습니다.")
        next_url = request.POST.get("next", "")
        if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect(reverse("dashboard"))
    return render(request, "reportbuilder/signup.html", {"form": form, "next": request.GET.get("next", "")})
