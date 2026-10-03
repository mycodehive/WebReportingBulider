from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import include, path
from reportbuilder.signup_views import signup

urlpatterns = [path("admin/", admin.site.urls),
               path("accounts/login/", auth.LoginView.as_view(template_name="reportbuilder/login.html"), name="login"),
               path("accounts/logout/", auth.LogoutView.as_view(), name="logout"),
               path("accounts/signup/", signup, name="signup"),
               path("", include("reportbuilder.urls"))]
