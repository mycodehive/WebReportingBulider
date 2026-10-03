import base64
import hashlib
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(os.environ.get("WEBREPORT_BASE_DIR", Path(__file__).resolve().parent.parent))
load_dotenv(BASE_DIR / ".env")
# Local development works without a copied .env; deployments must explicitly disable DEBUG.
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "development-only-change-before-deploying-webreport")
if not DEBUG and (SECRET_KEY.startswith("development-only") or not os.environ.get("REPORT_SECRET_KEY")):
    raise ImproperlyConfigured("Production requires DJANGO_SECRET_KEY and REPORT_SECRET_KEY.")
REPORT_SECRET_KEY = os.environ.get(
    "REPORT_SECRET_KEY", base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest()).decode()
)
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles", "reportbuilder",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware", "reportbuilder.middleware.ApiAuthenticationMiddleware",
    "reportbuilder.middleware.ApiAwareCsrfMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True,
              "OPTIONS": {"context_processors": [
                  "django.template.context_processors.request", "django.contrib.auth.context_processors.auth",
                  "django.contrib.messages.context_processors.messages", "reportbuilder.context_processors.company_branding", "reportbuilder.context_processors.workspace_navigation"]}}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
if os.environ.get("DATABASE_URL"):
    url = urlparse(os.environ["DATABASE_URL"])
    if url.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured("Metadata DATABASE_URL must be PostgreSQL.")
    DATABASES["default"] = {"ENGINE": "django.db.backends.postgresql", "NAME": url.path.lstrip("/"),
                           "USER": unquote(url.username or ""), "PASSWORD": unquote(url.password or ""),
                           "HOST": url.hostname, "PORT": url.port or 5432, "CONN_MAX_AGE": 60}
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG else
                            "whitenoise.storage.CompressedManifestStaticFilesStorage"}}
MEDIA_ROOT = BASE_DIR / "media"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 55 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
REPORT_MAX_ROWS = int(os.environ.get("REPORT_MAX_ROWS", 10000))
REPORT_REST_ALLOWED_HOSTS = [h.strip() for h in os.environ.get("REPORT_REST_ALLOWED_HOSTS", "").split(",") if h.strip()]
EMBED_ALLOWED_ORIGINS = [h.strip() for h in os.environ.get("EMBED_ALLOWED_ORIGINS", "").split(",") if h.strip()]
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True

# Enable only behind a trusted proxy that strips the client-supplied header.
if os.environ.get("DJANGO_TRUST_PROXY_HEADERS", "false").lower() == "true":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Access analytics uses a local GeoIP country database; raw IP/UA are not stored.
REPORT_ANALYTICS_ENABLED = os.environ.get("REPORT_ANALYTICS_ENABLED", "true").lower() == "true"
REPORT_GEOIP_DATABASE = os.environ.get("REPORT_GEOIP_DATABASE", "")
REPORT_TRUSTED_PROXIES = [value.strip() for value in os.environ.get("REPORT_TRUSTED_PROXIES", "").split(",") if value.strip()]
