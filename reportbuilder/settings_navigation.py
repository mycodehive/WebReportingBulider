"""Database-managed settings tabs and their child navigation."""
from django.urls import reverse

from .models import SettingsSection, SettingsMenu


def visible_settings_sections(request):
    sections = SettingsSection.objects.filter(active=True)
    if not request or not getattr(request.user, 'is_staff', False):
        sections = sections.filter(staff_only=False)
    return sections.prefetch_related('menus')


def visible_settings_children(section, request):
    staff = bool(request and request.user.is_staff)
    return [child for child in section.menus.all() if child.active and
            (staff or (not child.staff_only and child.key != 'mail' and child.url != '/settings/mail/'))]


def settings_page_allowed(request, child_key):
    if request.user.is_staff:
        return True
    # Check persisted policy even for direct URLs, edits, deletes and AJAX.
    return SettingsMenu.objects.filter(key=child_key, active=True, staff_only=False,
                                       section__active=True, section__staff_only=False).exists()


def settings_navigation(section_key=None, child_key=None, request=None):
    section_key = getattr(request, '_settings_section_key', section_key)
    child_key = getattr(request, '_settings_child_key', child_key)
    sections = []
    selected_key = section_key
    for section in visible_settings_sections(request):
        children = [{'key': child.key, 'label': child.label, 'url': child.url,
                     'active': child.key == child_key}
                    for child in visible_settings_children(section, request)]
        if any(child['active'] for child in children):
            selected_key = section.key
        sections.append({'key': section.key, 'label': section.label, 'children': children,
                         'url': reverse('settings_section', args=[section.pk])})
    if selected_key is None and sections:
        selected_key = sections[0]['key']
    selected = next((section for section in sections if section['key'] == selected_key), None)
    for section in sections:
        section['active'] = section is selected
    return {'settings_sections': sections, 'settings_children': selected['children'] if selected else []}
