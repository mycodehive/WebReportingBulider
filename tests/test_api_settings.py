import importlib
from unittest.mock import Mock

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client
from django.urls import reverse

from reportbuilder.models import LLMConfiguration, LLMModelLookup, SettingsMenu, SettingsSection

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(client):
    client.force_login(get_user_model().objects.create_user('api-settings-admin', is_staff=True))
    return client


def payload(**updates):
    return {'name': '보고서 도우미', 'provider': 'openai', 'model': 'test-model',
            'base_url': 'https://api.openai.com/v1', 'api_key': 'secret-key-not-for-display',
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


def catalog_payload(client, monkeypatch, **updates):
    data = payload(**updates)
    monkeypatch.setattr('reportbuilder.api_settings.list_models', lambda *a: [{'id': data['model'], 'label': data['model']}])
    LLMModelLookup.objects.all().update(requested_at=None)
    response = client.post(reverse('llm_models'), {'provider': data['provider'], 'base_url': data['base_url'],
                           'api_key': data['api_key']}, content_type='application/json')
    assert response.status_code == 200, response.content
    data['model_ticket'] = response.json()['model_ticket']
    return data


def test_llm_create_update_keep_key_replace_and_delete(staff_client, monkeypatch):
    url = reverse('external_api_settings')
    assert staff_client.post(url, catalog_payload(staff_client, monkeypatch)).status_code == 302
    config = LLMConfiguration.objects.get()
    assert config.api_key() == 'secret-key-not-for-display'
    assert 'secret-key-not-for-display' not in config.encrypted_api_key
    edit = reverse('llm_configuration_edit', args=[config.pk])
    response = staff_client.get(edit)
    assert 'no-store' in response['Cache-Control']
    assert 'secret-key-not-for-display' not in response.content.decode()
    assert 'value="secret-key' not in response.content.decode()
    assert staff_client.post(edit, payload(api_key='', active='')).status_code == 302
    config.refresh_from_db()
    assert config.model == 'test-model' and config.active is False
    assert config.api_key() == 'secret-key-not-for-display'
    assert staff_client.post(edit, catalog_payload(staff_client, monkeypatch, model='changed-model', api_key='replacement-secret')).status_code == 302
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


def test_llm_permissions_and_csrf(staff_client, monkeypatch):
    staff_client.post(reverse('external_api_settings'), catalog_payload(staff_client, monkeypatch))
    config = LLMConfiguration.objects.get()
    urls = [reverse('internal_api_settings'), reverse('external_api_settings'),
            reverse('llm_configuration_edit', args=[config.pk]), reverse('llm_configuration_delete', args=[config.pk])]
    client = Client(enforce_csrf_checks=True)
    client.force_login(get_user_model().objects.get(username='api-settings-admin'))
    for url in [*urls[1:], reverse('llm_models')]:
        assert client.post(url, payload()).status_code == 403
    member = get_user_model().objects.create_user('api-settings-member')
    staff_client.force_login(member)
    assert staff_client.get(urls[0]).status_code == 403
    assert staff_client.get(urls[1]).status_code == 200
    assert payload()['name'] not in staff_client.get(urls[1]).content.decode()
    for url in urls[2:]:
        assert staff_client.post(url, payload()).status_code == 404
        assert staff_client.get(url).status_code in {404, 405}
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


def test_member_private_crud_same_names_and_staff_cannot_access_other_keys(client, monkeypatch):
    users = [get_user_model().objects.create_user('llm-first'), get_user_model().objects.create_user('llm-second', is_staff=True)]
    clients = []
    configs = []
    for user in users:
        own = Client()
        own.force_login(user)
        clients.append(own)
        data = catalog_payload(own, monkeypatch, api_key=f'private-secret-{user.pk}')
        data['owner'] = str(users[0].pk)  # Incoming ownership is ignored.
        assert own.post(reverse('external_api_settings'), data).status_code == 302
        config = LLMConfiguration.objects.get(owner=user)
        configs.append(config)
        assert config.owner == user
        assert own.get(reverse('workspace_settings')).status_code == 200
    assert configs[0].name == configs[1].name
    for index, own in enumerate(clients):
        other = configs[1-index]
        response = own.get(reverse('external_api_settings'))
        assert list(response.context['configurations']) == [configs[index]]
        for route in ('llm_configuration_edit', 'llm_configuration_delete'):
            assert own.post(reverse(route, args=[other.pk]), payload()).status_code == 404
        assert own.get(reverse('llm_configuration_edit', args=[other.pk])).status_code == 404
        fetch = Mock()
        monkeypatch.setattr('reportbuilder.api_settings.list_models', fetch)
        result = own.post(reverse('llm_models'), {
            'configuration_id': str(other.pk), 'provider': other.provider, 'base_url': other.base_url,
        }, content_type='application/json')
        assert result.status_code == 404
        fetch.assert_not_called()


def test_model_lookup_uses_only_owners_saved_key_and_redacts_errors(staff_client, monkeypatch):
    data = catalog_payload(staff_client, monkeypatch)
    assert staff_client.post(reverse('external_api_settings'), data).status_code == 302
    config = LLMConfiguration.objects.get()
    LLMModelLookup.objects.all().update(requested_at=None)
    fetch = Mock(return_value=[{'id': 'available-model', 'label': 'Available'}])
    monkeypatch.setattr('reportbuilder.api_settings.list_models', fetch)
    inputs = {'configuration_id': str(config.pk), 'provider': config.provider, 'base_url': config.base_url}
    response = staff_client.post(reverse('llm_models'), inputs, content_type='application/json')
    assert response.status_code == 200
    fetch.assert_called_once_with(config.provider, config.base_url, config.api_key())
    assert config.api_key() not in response.content.decode()
    assert staff_client.post(reverse('llm_models'), inputs, content_type='application/json').status_code == 429
    assert fetch.call_count == 1
    LLMModelLookup.objects.all().update(requested_at=None)
    fetch.side_effect = RuntimeError('provider-error-including-' + config.api_key())
    response = staff_client.post(reverse('llm_models'), inputs, content_type='application/json')
    assert response.status_code == 400
    assert config.api_key() not in response.content.decode()


def test_menu_policy_filters_members_and_blocks_all_external_endpoints(client, monkeypatch):
    user = get_user_model().objects.create_user('policy-member')
    client.force_login(user)
    assert client.get(reverse('workspace_settings')).status_code == 200
    context = client.get(reverse('external_api_settings')).context
    assert [section['key'] for section in context['settings_sections']] == ['api']
    assert [child['key'] for child in context['settings_children']] == ['external-api']
    config = LLMConfiguration.objects.create(owner=user, name='Own', provider='openai',
                                             model='saved', base_url='https://api.openai.com/v1')
    config.set_api_key('stored-secret')
    config.save()
    for model, key in [(SettingsMenu, 'external-api'), (SettingsSection, 'api')]:
        model.objects.filter(key=key).update(staff_only=True)
        for route, args in [('external_api_settings', []), ('llm_configuration_edit', [config.pk])]:
            assert client.get(reverse(route, args=args)).status_code == 403
            assert client.post(reverse(route, args=args), payload()).status_code == 403
        assert client.post(reverse('llm_configuration_delete', args=[config.pk])).status_code == 403
        assert client.post(reverse('llm_models'), {}, content_type='application/json').status_code == 403
        model.objects.filter(key=key).update(staff_only=False)
    SettingsSection.objects.filter(key='api').update(staff_only=True)
    assert client.get(reverse('workspace_settings')).status_code == 403
    assert client.get(reverse('settings_section', args=[SettingsSection.objects.get(key='api').pk])).status_code == 404
    assert not any(item['key'] == 'settings' for item in client.get('/').context['sidebar_items'])
    assert LLMConfiguration.objects.filter(pk=config.pk).exists()


def test_forged_expired_and_cross_user_catalog_cannot_create_settings(staff_client, client, monkeypatch):
    import time
    from django.core import signing
    data = catalog_payload(staff_client, monkeypatch)
    wrong = {**data, 'model': 'injected-model'}
    assert staff_client.post(reverse('external_api_settings'), wrong).status_code == 200
    wrong = {**data, 'api_key': 'changed-secret'}
    assert staff_client.post(reverse('external_api_settings'), wrong).status_code == 200
    wrong = {**data, 'model_ticket': data['model_ticket'] + 'tampered'}
    assert staff_client.post(reverse('external_api_settings'), wrong).status_code == 200
    original_time = time.time()
    with monkeypatch.context() as patch:
        patch.setattr(signing.time, 'time', lambda: original_time + 1000)
        assert staff_client.post(reverse('external_api_settings'), data).status_code == 200
    client.force_login(get_user_model().objects.create_user('ticket-thief'))
    assert client.post(reverse('external_api_settings'), data).status_code == 200
    assert not LLMConfiguration.objects.exists()


def test_legacy_owner_migration_and_explicit_recovery(staff_client):
    import io
    from django.core.management import call_command, CommandError
    migration = importlib.import_module('reportbuilder.migrations.0018_llmconfiguration_owner_settingsmenu_staff_only_and_more')
    first = get_user_model().objects.get(username='api-settings-admin')
    old = LLMConfiguration.objects.create(name='Legacy', provider='openai', model='old', base_url='https://api.openai.com/v1')
    old.set_api_key('legacy-secret')
    old.save()
    second = get_user_model().objects.create_user('second-admin', is_staff=True)
    migration.migrate_user_llm_settings(apps, type('Editor', (), {'connection': connection})())
    old.refresh_from_db()
    assert old.owner is None  # Ambiguous ownership is preserved without disclosure.
    assert 'Legacy' not in staff_client.get(reverse('external_api_settings')).content.decode()
    member = get_user_model().objects.create_user('cannot-claim')
    with pytest.raises(CommandError):
        call_command('assign_legacy_llm', user_id=member.pk)
    output = io.StringIO()
    call_command('assign_legacy_llm', user_id=first.pk, stdout=output)
    old.refresh_from_db()
    assert old.owner == first and old.api_key() == 'legacy-secret'
    assert 'legacy-secret' not in output.getvalue()
    second.delete()
