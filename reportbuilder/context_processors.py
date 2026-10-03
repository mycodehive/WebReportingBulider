from django.db import OperationalError, ProgrammingError
from django.urls import reverse

from .models import CompanyBranding


def company_branding(request):
    # Allow the login page to render while migrations are being installed.
    try:
        branding = CompanyBranding.objects.filter(pk=1).first()
    except (OperationalError, ProgrammingError):
        branding = None
    return {'company_branding': branding,
            'company_logo_url': f'{reverse("company_logo")}?v={branding.updated_at.timestamp()}' if branding and branding.logo else ''}
