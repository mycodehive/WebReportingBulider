"""Database-managed settings tabs and their child navigation."""
from django.urls import reverse

from .models import SettingsSection


def settings_navigation(section_key=None, child_key=None, request=None):
    section_key = getattr(request, '_settings_section_key', section_key)
    child_key = getattr(request, '_settings_child_key', child_key)
    sections = []
    selected_key = section_key
    for section in SettingsSection.objects.filter(active=True).prefetch_related('menus'):
        children = [{'key': child.key, 'label': child.label, 'url': child.url,
                     'active': child.key == child_key}
                    for child in section.menus.all() if child.active]
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
