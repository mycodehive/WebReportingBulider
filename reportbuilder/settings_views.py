from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from . import branding, menu_views
from .models import SettingsSection
from .settings_navigation import settings_navigation


@login_required
@require_GET
def home(request, section_id=None):
    if not request.user.is_staff:
        return HttpResponseForbidden('환경설정은 전체 관리자만 이용할 수 있습니다.')
    sections = SettingsSection.objects.filter(active=True)
    section = get_object_or_404(sections, pk=section_id) if section_id else sections.first()
    child = section.menus.filter(active=True).first() if section else None
    request._settings_section_key = section.key if section else None
    request._settings_child_key = child.key if child else None
    # Existing screens retain their own permissions, forms and POST handling.
    if child and child.url == '/settings/company/':
        return branding.settings(request)
    if child and child.url == '/menu-management/':
        return menu_views.menu_management(request)
    context = settings_navigation(section.key if section else None, child.key if child else None)
    return render(request, 'reportbuilder/settings_home.html', context)
