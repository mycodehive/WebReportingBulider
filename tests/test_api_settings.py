import importlib

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client
from django.urls import reverse

from reportbuilder.models import LLMConfiguration, SettingsMenu, SettingsSection

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(client):
    client.force_login(get_user_model().objects.create_user('api-settings-admin', is_staff=True))
    return client


def payload(**updates):
    return {'name': '보고서 도우미', 'provider': 'openai', 'model': 'test-model',
            'base_url': 'https://llm.example.com/v1', 'api_key': 'secret-key-not-for-display',
            'active': 'on', **updates}


def test_api_tab_default_page_and_managed_children(staff_client):
    section = SettingsSection.objects.get(key='api')
    response = staff_client.get(reverse('settings_section', args=[section.pk]))
    assert response.status_code == 200
    assert '실험실에 열심히 개발중이에요' in response.content.decode()
    assert [child['label'] for child in response.context['settings_children']] == ['내부API', '외부API']
    assert next(s for s in response.context['settings_sections'] if s['active'])['key'] == 'api'
    assert next(s for s in response.context['sidebar_items'] if s['key'] == 'settings')['active']
    # Reordering is respected when API tab content is selected.
    SettingsMenu.objects.filter(key='external-api').update(order=0)
    response = staff_client.get(reverse('settings_section', args=[section.pk]))
    assert 'LLM 설정 등록' in response.content.decode()
    assert response.context['form'].is_bound is False


def test_llm_create_update_keep_key_replace_and_delete(staff_client):
    url = reverse('external_api_settings')
    assert staff_client.post(url, payload()).status_code == 302
    config = LLMConfiguration.objects.get()
    assert config.api_key() == 'secret-key-not-for-display'
    assert 'secret-key-not-for-display' not in config.encrypted_api_key
    edit = reverse('llm_configuration_edit', args=[config.pk])
    response = staff_client.get(edit)
    assert 'no-store' in response['Cache-Control']
    assert 'secret-key-not-for-display' not in response.content.decode()
    assert 'value="secret-key' not in response.content.decode()
    assert staff_client.post(edit, payload(model='changed-model', api_key='', active='')).status_code == 302
    config.refresh_from_db()
    assert config.model == 'changed-model' and config.active is False
    assert config.api_key() == 'secret-key-not-for-display'
    assert staff_client.post(edit, payload(api_key='replacement-secret')).status_code == 302
    config.refresh_from_db()
    assert config.api_key() == 'replacement-secret'
    invalid = staff_client.post(edit, payload(api_key='must-not-leak', model=''))
    assert invalid.status_code == 200 and invalid.context['form'].errors
    assert 'must-not-leak' not in invalid.content.decode()
    config.refresh_from_db()
    assert config.api_key() == 'replacement-secret'
    delete = reverse('llm_configuration_delete', args=[config.pk])
    assert staff_client.get(delete).status_code == 405
    assert staff_client.post(delete).status_code == 302
    assert not LLMConfiguration.objects.exists()


@pytest.mark.parametrize('updates', [
    {'api_key': ''}, {'provider': 'unsupported'}, {'model': ''},
    {'base_url': 'http://llm.example.com'}, {'base_url': 'https://user:key@llm.example.com'},
    {'base_url': 'https://llm.example.com?key=secret'}, {'base_url': 'https://llm.example.com#secret'},
])
def test_invalid_settings_never_saved(staff_client, updates):
    response = staff_client.post(reverse('external_api_settings'), payload(**updates))
    assert response.status_code == 200 and response.context['form'].errors
    assert not LLMConfiguration.objects.exists()


def test_llm_staff_permissions_and_csrf(staff_client):
    staff_client.post(reverse('external_api_settings'), payload())
    config = LLMConfiguration.objects.get()
    urls = [reverse('internal_api_settings'), reverse('external_api_settings'),
            reverse('llm_configuration_edit', args=[config.pk]), reverse('llm_configuration_delete', args=[config.pk])]
    client = Client(enforce_csrf_checks=True)
    client.force_login(get_user_model().objects.get(username='api-settings-admin'))
    for url in urls[1:]:
        assert client.post(url, payload()).status_code == 403
    member = get_user_model().objects.create_user('api-settings-member')
    staff_client.force_login(member)
    for url in urls:
        assert staff_client.post(url, payload()).status_code in {403, 405}
        if url != urls[-1]:
            assert staff_client.get(url).status_code == 403
    assert LLMConfiguration.objects.count() == 1
    staff_client.logout()
    assert staff_client.get(urls[1]).status_code == 302


@pytest.mark.django_db(transaction=True)
def test_api_menu_seed_is_idempotent_and_preserves_customization():
    section = SettingsSection.objects.get(key='api')
    section.label = 'API 관리'
    section.save()
    SettingsMenu.objects.filter(key='internal-api').update(label='실험실', active=False)
    migration = importlib.import_module('reportbuilder.migrations.0017_llmconfiguration')
    with connection.schema_editor() as editor:
        migration.seed_api_settings(apps, editor)
        migration.seed_api_settings(apps, editor)
    assert SettingsSection.objects.get(key='api').label == 'API 관리'
    assert SettingsMenu.objects.get(key='internal-api').active is False
    assert SettingsMenu.objects.filter(section=section).count() == 2
