from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from . import branding, menu_views, api_settings
from .settings_navigation import settings_navigation, visible_settings_sections, visible_settings_children


@login_required
@require_GET
def home(request, section_id=None):
    sections = visible_settings_sections(request)
    section = get_object_or_404(sections, pk=section_id) if section_id else sections.first()
    if not section and not request.user.is_staff:
        return HttpResponseForbidden('이용 가능한 환경설정 메뉴가 없습니다.')
    children = visible_settings_children(section, request) if section else []
    child = children[0] if children else None
    request._settings_section_key = section.key if section else None
    request._settings_child_key = child.key if child else None
    # Existing screens retain their own permissions, forms and POST handling.
    if child and child.url == '/settings/company/':
        return branding.settings(request)
    if child and child.url == '/menu-management/':
        return menu_views.menu_management(request)
    if child and child.url == '/settings/api/internal/':
        return api_settings.internal(request)
    if child and child.url == '/settings/api/external/':
        return api_settings.external(request)
    context = settings_navigation(section.key if section else None, child.key if child else None, request)
    return render(request, 'reportbuilder/settings_home.html', context)
