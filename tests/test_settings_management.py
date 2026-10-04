import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from reportbuilder.models import SettingsMenu, SettingsSection


pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client):
    client.force_login(get_user_model().objects.create_user('settings-manager', is_staff=True))
    return client


def payload(formset):
    prefix = formset.prefix
    result = {f'{prefix}-TOTAL_FORMS': str(len(formset.forms)),
              f'{prefix}-INITIAL_FORMS': str(formset.initial_form_count())}
    for form in formset:
        for field in form:
            value = field.value()
            if value is True:
                result[field.html_name] = 'on'
            elif value is not False and value is not None:
                result[field.html_name] = str(value)
    return result


def test_create_rename_order_move_hide_and_delete_settings(admin_client):
    response = admin_client.get(reverse('menu_management'))
    forms = response.context['section_forms']
    data = payload(forms)
    data['action'] = 'save_settings_sections'
    basic_index = next(i for i, form in enumerate(forms) if form.instance.key == 'basic')
    data[f'sections-{basic_index}-label'] = '브랜드정보'
    data[f'sections-{basic_index}-order'] = '30'
    extra = forms.initial_form_count()
    data.update({f'sections-{extra}-label': '운영관리', f'sections-{extra}-order': '5',
                 f'sections-{extra}-active': 'on'})
    assert admin_client.post(reverse('menu_management'), data).status_code == 302
    new = SettingsSection.objects.get(label='운영관리')
    assert SettingsSection.objects.get(key='basic').label == '브랜드정보'
    assert SettingsSection.objects.filter(active=True).first() == new

    forms = admin_client.get(reverse('menu_management')).context['settings_menu_forms']
    data = payload(forms)
    data['action'] = 'save_settings_children'
    company_index = next(i for i, form in enumerate(forms) if form.instance.key == 'company')
    data.update({f'children-{company_index}-section': str(new.pk),
                 f'children-{company_index}-label': '브랜드 로고'})
    extra = forms.initial_form_count()
    data.update({f'children-{extra}-section': str(new.pk), f'children-{extra}-label': '사용 가이드',
                 f'children-{extra}-url': '/manual/', f'children-{extra}-order': '20',
                 f'children-{extra}-active': 'on'})
    assert admin_client.post(reverse('menu_management'), data).status_code == 302
    company = SettingsMenu.objects.get(key='company')
    assert company.section == new and company.label == '브랜드 로고'
    response = admin_client.get(reverse('company_settings'))
    assert next(section for section in response.context['settings_sections'] if section['active'])['key'] == new.key
    assert [child['label'] for child in response.context['settings_children']] == ['브랜드 로고', '사용 가이드']
    root = admin_client.get(reverse('workspace_settings'))
    assert '로고 등록 / 수정' in root.content.decode()

    forms = admin_client.get(reverse('menu_management')).context['section_forms']
    data = payload(forms)
    data['action'] = 'save_settings_sections'
    index = next(i for i, form in enumerate(forms) if form.instance.pk == new.pk)
    data.pop(f'sections-{index}-active')
    assert admin_client.post(reverse('menu_management'), data).status_code == 302
    assert new.key not in [section['key'] for section in admin_client.get(reverse('company_settings')).context['settings_sections']]
    data[f'sections-{index}-DELETE'] = 'on'
    assert admin_client.post(reverse('menu_management'), data).status_code == 302
    assert not SettingsMenu.objects.filter(section_id=new.pk).exists()
    assert admin_client.get(reverse('menu_management')).status_code == 200


@pytest.mark.parametrize('url', ['https://evil.example/', '//evil.example/', '/\\evil', 'javascript:alert(1)', '/settings/', '/settings/sections/1/'])
def test_invalid_child_url_rolls_back_all_changes(admin_client, url):
    forms = admin_client.get(reverse('menu_management')).context['settings_menu_forms']
    data = payload(forms)
    data['action'] = 'save_settings_children'
    data['children-0-label'] = '저장되면 안 되는 이름'
    data['children-1-url'] = url
    response = admin_client.post(reverse('menu_management'), data)
    assert response.status_code == 200
    assert response.context['settings_menu_forms'].errors
    assert not SettingsMenu.objects.filter(label='저장되면 안 되는 이름').exists()


def test_empty_settings_and_staff_only_mutations(admin_client, client):
    SettingsSection.objects.all().delete()
    response = admin_client.get(reverse('workspace_settings'))
    assert response.status_code == 200
    assert response.context['settings_sections'] == []
    assert '메뉴관리 열기' in response.content.decode()
    member = get_user_model().objects.create_user('settings-no-access')
    client.force_login(member)
    assert client.post(reverse('menu_management'), {'action': 'save_settings_sections'}).status_code == 403
    assert not SettingsSection.objects.exists()
