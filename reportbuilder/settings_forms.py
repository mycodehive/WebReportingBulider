import uuid

from django import forms
from django.forms import BaseModelFormSet, modelformset_factory

from .models import SettingsMenu, SettingsSection


class SettingsSectionForm(forms.ModelForm):
    class Meta:
        model = SettingsSection
        fields = ['label', 'order', 'staff_only', 'active']
        widgets = {'label': forms.TextInput(attrs={'class': 'input'}),
                   'order': forms.NumberInput(attrs={'class': 'input'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs['aria-label'] = f"{self.instance.label or '새 탭'} {field.label}"

    def save(self, commit=True):
        if not self.instance.key:
            self.instance.key = f'section-{uuid.uuid4().hex}'
        return super().save(commit)


class SettingsMenuForm(forms.ModelForm):
    class Meta:
        model = SettingsMenu
        fields = ['section', 'label', 'url', 'order', 'staff_only', 'active']
        widgets = {'section': forms.Select(attrs={'class': 'input'}),
                   'label': forms.TextInput(attrs={'class': 'input'}),
                   'url': forms.TextInput(attrs={'class': 'input', 'placeholder': '/settings/company/'}),
                   'order': forms.NumberInput(attrs={'class': 'input'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs['aria-label'] = f"{self.instance.label or '새 하위 메뉴'} {field.label}"

    def save(self, commit=True):
        if not self.instance.key:
            self.instance.key = f'menu-{uuid.uuid4().hex}'
        return super().save(commit)


class AccessibleSettingsFormSet(BaseModelFormSet):
    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.fields['DELETE'].widget.attrs['aria-label'] = f"{form.instance.label or '새 메뉴'} 삭제"


SectionFormSet = modelformset_factory(SettingsSection, form=SettingsSectionForm, formset=AccessibleSettingsFormSet, extra=1, can_delete=True)
SettingsMenuFormSet = modelformset_factory(SettingsMenu, form=SettingsMenuForm, formset=AccessibleSettingsFormSet, extra=1, can_delete=True)
