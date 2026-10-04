import importlib

import pytest
from django.contrib.auth import get_user_model
from django.apps import apps
from django.db import connection
from django.urls import reverse

from reportbuilder.models import WorkspaceMenu


@pytest.mark.django_db
def test_settings_categories_permissions_and_sidebar(client):
    admin = get_user_model().objects.create_user('settings-admin', is_staff=True)
    client.force_login(admin)
    for route, selected, child, absent in (
        ('workspace_settings', '기본정보', '회사로고', '메뉴관리'),
        ('company_settings', '기본정보', '회사로고', '메뉴관리'),
        ('menu_management', '사이트관리', '메뉴관리', '회사로고'),
    ):
        response = client.get(reverse(route))
        assert response.status_code == 200
        assert next(item for item in response.context['settings_sections'] if item['active'])['label'] == selected
        assert [item['label'] for item in response.context['settings_children']] == ([child, '메일'] if selected == '기본정보' else [child])
        sidebar = response.context['sidebar_items']
        assert len([item for item in sidebar if item['key'] == 'settings' and item['active']]) == 1
        assert not any(item['key'] in {'company', 'menu_management'} for item in sidebar)
        submenu = response.content.decode().split('aria-label="선택한 설정의 하위 메뉴"')[1].split('</nav>')[0]
        assert child in submenu and absent not in submenu
    member = get_user_model().objects.create_user('settings-member')
    client.force_login(member)
    assert client.get(reverse('workspace_settings')).status_code == 200
    for route in ('company_settings', 'menu_management'):
        assert client.get(reverse(route)).status_code == 403
    assert any(item['key'] == 'settings' for item in client.get('/').context['sidebar_items'])
    client.logout()
    assert client.get(reverse('workspace_settings')).status_code == 302


@pytest.mark.django_db(transaction=True)
def test_settings_migration_preserves_other_menus_and_custom_order():
    WorkspaceMenu.objects.all().delete()
    WorkspaceMenu.objects.create(key='company', label='브랜드', url='/settings/company/', order=23)
    WorkspaceMenu.objects.create(key='menu_management', label='메뉴관리', url='/menu-management/', order=80)
    custom = WorkspaceMenu.objects.create(key='custom', label='커스텀', url='/boards/', order=13)
    migration = importlib.import_module('reportbuilder.migrations.0014_settings_navigation')
    with connection.schema_editor() as editor:
        migration.consolidate_settings(apps, editor)
        migration.consolidate_settings(apps, editor)
    settings = WorkspaceMenu.objects.get(key='settings')
    assert (settings.label, settings.url, settings.order, settings.staff_only, settings.active) == (
        '환경설정', '/settings/', 23, True, True)
    # Second invocation has no old company row; retain the consolidated position.
    assert WorkspaceMenu.objects.filter(pk=custom.pk, label='커스텀', order=13).exists()
    assert not WorkspaceMenu.objects.filter(key__in=['company', 'menu_management']).exists()
