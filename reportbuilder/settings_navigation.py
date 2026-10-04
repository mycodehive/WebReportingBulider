"""Content navigation: settings categories contain their own child menus."""
from django.urls import reverse


SETTINGS_SECTIONS = (
    {"key": "basic", "label": "기본정보", "children": (
        {"key": "company", "label": "회사로고", "route": "company_settings"},
    )},
    {"key": "site", "label": "사이트관리", "children": (
        {"key": "menus", "label": "메뉴관리", "route": "menu_management"},
    )},
)


def settings_navigation(section_key, child_key):
    sections = []
    for section in SETTINGS_SECTIONS:
        children = [{**child, "url": reverse(child["route"]), "active": child["key"] == child_key}
                    for child in section["children"]]
        sections.append({**section, "children": children, "url": children[0]["url"],
                         "active": section["key"] == section_key})
    return {"settings_sections": sections,
            "settings_children": next(section["children"] for section in sections if section["active"])}
