"""Staff-only LLM configuration; saving never contacts an external provider."""
from urllib.parse import urlsplit

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import LLMConfiguration
from .settings_navigation import settings_navigation


class LLMConfigurationForm(forms.ModelForm):
    base_url = forms.URLField(label='API 기본 주소', max_length=500, assume_scheme='https',
                              help_text='제공자의 HTTPS API 기본 주소를 입력하세요. 키는 주소에 넣지 마세요.')
    api_key = forms.CharField(label='API 키', required=False, max_length=4096,
                              widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
                              help_text='수정 시 비워 두면 저장된 키를 유지합니다.')

    class Meta:
        model = LLMConfiguration
        fields = ['name', 'provider', 'model', 'base_url', 'api_key', 'active']
        help_texts = {
            'model': '제공자에서 사용할 모델의 정확한 ID를 입력하세요.',
            'base_url': '제공자의 HTTPS API 기본 주소를 입력하세요. 키는 주소에 넣지 마세요.',
        }

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('label_suffix', '')
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'input'
        self.fields['api_key'].help_text = ('비워 두면 저장된 키를 유지합니다. 새 키를 입력하면 교체합니다.'
                                            if self.instance.encrypted_api_key else '제공자에서 발급받은 API 키를 입력하세요.')

    def clean_base_url(self):
        url = self.cleaned_data['base_url']
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise forms.ValidationError('인증 정보·쿼리·프래그먼트 없는 HTTPS 기본 주소를 입력하세요.')
        return url.rstrip('/')

    def clean(self):
        data = super().clean()
        if not data.get('api_key') and not self.instance.encrypted_api_key:
            self.add_error('api_key', '새 연결에는 API 키가 필요합니다.')
        return data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data['api_key']:
            instance.set_api_key(self.cleaned_data['api_key'])
        if commit:
            instance.save()
        return instance


@login_required
@require_GET
def internal(request):
    if not request.user.is_staff:
        return HttpResponseForbidden('API 설정은 전체 관리자만 이용할 수 있습니다.')
    return render(request, 'reportbuilder/api_internal.html', settings_navigation('api', 'internal-api', request))


@login_required
@require_http_methods(['GET', 'POST'])
def external(request, configuration_id=None):
    if not request.user.is_staff:
        return HttpResponseForbidden('API 설정은 전체 관리자만 이용할 수 있습니다.')
    configuration = get_object_or_404(LLMConfiguration, pk=configuration_id) if configuration_id else None
    form = LLMConfigurationForm(request.POST if request.method == 'POST' else None, instance=configuration)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'LLM 설정을 저장했습니다.')
        return redirect('external_api_settings')
    response = render(request, 'reportbuilder/api_external.html', {
        'form': form, 'configuration': configuration, 'configurations': LLMConfiguration.objects.all(),
        **settings_navigation('api', 'external-api', request),
    })
    response['Cache-Control'] = 'no-store'
    return response


@login_required
@require_POST
def delete(request, configuration_id):
    if not request.user.is_staff:
        return HttpResponseForbidden('API 설정은 전체 관리자만 이용할 수 있습니다.')
    get_object_or_404(LLMConfiguration, pk=configuration_id).delete()
    messages.success(request, 'LLM 설정을 삭제했습니다.')
    return redirect('external_api_settings')
