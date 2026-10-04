from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import include, path
from reportbuilder.signup_views import signup
from reportbuilder import email_verification_views as verification

urlpatterns = [path("admin/", admin.site.urls),
               path("accounts/login/", auth.LoginView.as_view(template_name="reportbuilder/login.html"), name="login"),
               path("accounts/logout/", auth.LogoutView.as_view(), name="logout"),
               path("accounts/email/", verification.notice, name="email_verification_notice"),
               path("accounts/email/resend/", verification.resend, name="email_verification_resend"),
               path("accounts/email/verify/<int:verification_id>/<str:token>/", verification.link, name="email_verification_link"),
               path("accounts/email/confirm/", verification.confirm, name="email_verification_confirm"),
               path("accounts/email/complete/", verification.complete, name="email_verification_complete"),
               path("accounts/signup/", signup, name="signup"),
               path("", include("reportbuilder.urls"))]
