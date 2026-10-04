"""Owner-isolated LLM configuration and authenticated model discovery."""
import json
from datetime import timedelta

from django import forms
from django.core import signing
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .data import DataError
from .llm_models import PROVIDER_BASE_URLS, MAX_MODELS, credential_context, list_models, validated_base_url
from .models import LLMConfiguration, LLMModelLookup
from .settings_navigation import settings_navigation, settings_page_allowed

CATALOG_SALT = 'llm-model-selection'


class LLMConfigurationForm(forms.ModelForm):
    base_url = forms.URLField(label='API 기본 주소', max_length=500, assume_scheme='https',
                              help_text='제공자의 HTTPS API 기본 주소를 입력하세요. 키는 주소에 넣지 마세요.')
    api_key = forms.CharField(label='API 키', required=False, max_length=4096,
                              widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
                              help_text='수정 시 비워 두면 저장된 키를 유지합니다.')
    model = forms.ChoiceField(label='모델명', choices=[])
    model_ticket = forms.CharField(required=False, max_length=1500000, widget=forms.HiddenInput)

    class Meta:
        model = LLMConfiguration
        fields = ['name', 'provider', 'base_url', 'api_key', 'model', 'active', 'model_ticket']
        help_texts = {
            'model': 'API 키로 모델 목록을 불러온 뒤 사용할 모델을 선택하세요.',
            'base_url': '제공자의 HTTPS API 기본 주소를 입력하세요. 키는 주소에 넣지 마세요.',
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        kwargs.setdefault('label_suffix', '')
        super().__init__(*args, **kwargs)
        self.original = {'provider': self.instance.provider, 'base_url': self.instance.base_url,
                         'model': self.instance.model, 'api_key': self.instance.api_key()}
        self.catalog = None
        choices = [('', '모델 불러오기 후 선택하세요')]
        if self.instance.pk and self.instance.model:
            choices.append((self.instance.model, self.instance.model))
        if self.is_bound:
            try:
                catalog = signing.loads(self.data.get('model_ticket', ''), salt=CATALOG_SALT, max_age=900)
                ids = catalog['models']
                if (catalog['context']['user'] != str(self.user.pk) or not isinstance(ids, list)
                        or not 0 < len(ids) <= MAX_MODELS or any(not isinstance(i, str) or len(i) > 200 for i in ids)):
                    raise ValueError
                self.catalog = catalog
                choices = [('', '모델을 선택하세요')] + [(i, i) for i in ids]
            except (signing.BadSignature, ValueError, TypeError, KeyError):
                pass
        self.fields['model'].choices = choices
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'input'
        self.fields['api_key'].help_text = ('비워 두면 저장된 키를 유지합니다. 새 키를 입력하면 교체합니다.'
                                            if self.instance.encrypted_api_key else '제공자에서 발급받은 API 키를 입력하세요.')

    def clean_base_url(self):
        try:
            return validated_base_url(self.cleaned_data.get('provider'), self.cleaned_data['base_url'])
        except DataError as exc:
            raise forms.ValidationError(str(exc)) from None

    def clean_name(self):
        name = self.cleaned_data['name']
        if LLMConfiguration.objects.filter(owner=self.user, name=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('같은 연결명이 이미 있습니다.')
        return name

    def clean(self):
        data = super().clean()
        if not data.get('api_key') and not self.instance.encrypted_api_key:
            self.add_error('api_key', '새 연결에는 API 키가 필요합니다.')
        if data.get('provider') and data.get('base_url') and data.get('model'):
            key = data.get('api_key') or self.original['api_key']
            context = credential_context(self.user, data['provider'], data['base_url'], key)
            unchanged = (self.instance.encrypted_api_key and data['model'] == self.original['model']
                         and context == credential_context(self.user, self.original['provider'], self.original['base_url'], self.original['api_key']))
            if not unchanged and (not self.catalog or self.catalog['context'] != context or data['model'] not in self.catalog['models']):
                self.add_error('model', '현재 API 키와 주소로 모델을 다시 불러온 뒤 선택하세요. 조회 결과는 15분간 유효합니다.')
        return data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.owner = self.user
        if self.cleaned_data['api_key']:
            instance.set_api_key(self.cleaned_data['api_key'])
        if commit:
            instance.save()
        return instance


@login_required
@require_GET
def internal(request):
    if not settings_page_allowed(request, 'internal-api'):
        return HttpResponseForbidden('이 내부API 메뉴에 접근할 권한이 없습니다.')
    return render(request, 'reportbuilder/api_internal.html', settings_navigation('api', 'internal-api', request))


@login_required
@require_http_methods(['GET', 'POST'])
def external(request, configuration_id=None):
    if not settings_page_allowed(request, 'external-api'):
        return HttpResponseForbidden('이 외부API 메뉴에 접근할 권한이 없습니다.')
    configuration = (get_object_or_404(LLMConfiguration, owner=request.user, pk=configuration_id)
                     if configuration_id else LLMConfiguration(owner=request.user))
    editing = configuration if configuration_id else None
    form = LLMConfigurationForm(request.POST if request.method == 'POST' else None, instance=configuration, user=request.user)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                form.save()
            messages.success(request, 'LLM 설정을 저장했습니다.')
            return redirect('external_api_settings')
        except IntegrityError:
            form.add_error('name', '같은 연결명이 이미 있습니다.')
    response = render(request, 'reportbuilder/api_external.html', {
        'form': form, 'configuration': editing, 'configurations': LLMConfiguration.objects.filter(owner=request.user),
        'provider_base_urls': PROVIDER_BASE_URLS,
        **settings_navigation('api', 'external-api', request),
    })
    response['Cache-Control'] = 'no-store'
    return response


@login_required
@require_POST
def delete(request, configuration_id):
    if not settings_page_allowed(request, 'external-api'):
        return HttpResponseForbidden('이 외부API 메뉴에 접근할 권한이 없습니다.')
    get_object_or_404(LLMConfiguration, owner=request.user, pk=configuration_id).delete()
    messages.success(request, 'LLM 설정을 삭제했습니다.')
    return redirect('external_api_settings')


@login_required
@require_POST
def models(request):
    if not settings_page_allowed(request, 'external-api'):
        return JsonResponse({'message': '이 외부API 메뉴에 접근할 권한이 없습니다.'}, status=403)
    if len(request.body) > 16384:
        return JsonResponse({'message': '모델 조회 입력값이 너무 큽니다.'}, status=400)
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
        provider, base_url, key = data.get('provider'), data.get('base_url'), data.get('api_key', '')
        if not isinstance(provider, str) or not isinstance(base_url, str) or not isinstance(key, str):
            raise ValueError
        base_url = validated_base_url(provider, base_url)
        if data.get('configuration_id'):
            configuration = get_object_or_404(LLMConfiguration, owner=request.user, pk=data['configuration_id'])
            if not key:
                if provider != configuration.provider or base_url != configuration.base_url:
                    raise DataError('AUTH_REQUIRED', '제공자나 주소를 변경하면 해당 제공자의 API 키를 입력하세요.')
                key = configuration.api_key()
        if not key or len(key) > 4096:
            raise DataError('AUTH_REQUIRED', 'API 키를 입력하세요.')
        lookup, _ = LLMModelLookup.objects.get_or_create(user=request.user)
        now = timezone.now()
        if not LLMModelLookup.objects.filter(pk=lookup.pk).filter(
                Q(requested_at__isnull=True) | Q(requested_at__lte=now - timedelta(seconds=5))).update(requested_at=now):
            return JsonResponse({'message': '모델 조회는 5초 간격으로 실행할 수 있습니다.'}, status=429)
        items = list_models(provider, base_url, key)
        ticket = signing.dumps({'context': credential_context(request.user, provider, base_url, key),
                                'models': [item['id'] for item in items]}, salt=CATALOG_SALT, compress=True)
        if len(ticket) > 1500000:
            raise DataError('DATA_LIMIT', '모델 선택 정보가 허용 크기를 초과했습니다.')
        return JsonResponse({'models': items, 'model_ticket': ticket})
    except DataError as exc:
        return JsonResponse({'message': str(exc), 'code': exc.code}, status=400)
    except (ValueError, TypeError, ValidationError):
        return JsonResponse({'message': '모델 조회 입력값이나 응답 형식이 올바르지 않습니다.'}, status=400)
    except Http404:
        raise
    except Exception:
        # Never echo transport/crypto errors or provider response bodies.
        return JsonResponse({'message': '모델 목록을 조회하지 못했습니다. 연결 상태와 API 키를 확인하세요.'}, status=400)
