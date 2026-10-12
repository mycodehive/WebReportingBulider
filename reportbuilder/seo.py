"""Staff-only SEO settings and escaped public introduction metadata."""
import io
import logging
import uuid
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import OperationalError, ProgrammingError, transaction
from django.http import HttpResponseBadRequest, HttpResponseForbidden, FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_safe

from .models import SEOConfiguration
from .settings_navigation import settings_navigation
from .site_origin import inferred_service_url
from .views import normalised_png

logger = logging.getLogger(__name__)

DEFAULT_TITLE = 'WebReportingBuilder — 웹에서 만드는 업무 보고서'
DEFAULT_DESCRIPTION = 'Excel·CSV·데이터베이스를 연결해 웹에서 보고서를 디자인하세요. 반복 출력과 합계, 미리보기, 게시·공유, 데이터 내보내기와 시스템 연동을 지원합니다.'


class SEOForm(forms.ModelForm):
    site_url = forms.URLField(label='대표 서비스 주소', required=False, max_length=500, assume_scheme='https')
    og_image = forms.URLField(label='공유 이미지 URL', required=False, max_length=2000, assume_scheme='https')

    og_upload = forms.FileField(label='공유 이미지 업로드', required=False,
                                widget=forms.FileInput(attrs={'accept': 'image/png,image/jpeg,image/gif,image/webp'}),
                                help_text='PNG·JPG·GIF·WebP, 최대 5MB. 업로드 이미지를 URL보다 우선 사용합니다. 링크 방문자에게 공개됩니다. 권장 비율 1200×630.')
    remove_image = forms.BooleanField(label='업로드 이미지 삭제', required=False,
                                     help_text='새 파일을 선택하지 않고 체크 후 저장하세요. 이미지 URL이 있으면 URL 이미지로 돌아갑니다.')

    class Meta:
        model = SEOConfiguration
        fields = ['title', 'description', 'keywords', 'site_url', 'og_title', 'og_description',
                  'og_image', 'google_verification', 'naver_verification', 'allow_indexing']
        widgets = {name: forms.Textarea(attrs={'rows': 3}) for name in ['description', 'og_description']}
        help_texts = {
            'title': '비우면 기본 소개페이지 제목을 사용합니다. 검색 결과의 표시 길이는 검색엔진이 결정합니다.',
            'description': '소개페이지의 검색 결과 설명 후보입니다. 비우면 기본 설명을 사용합니다.',
            'keywords': '쉼표로 구분하세요. 키워드 입력이 검색 순위를 보장하지는 않습니다.',
            'site_url': '예: https://wrb.writeaday.click — 경로 없이 HTTPS 주소를 입력하세요.',
            'og_title': '비우면 사이트 제목을 사용합니다.',
            'og_description': '비우면 사이트 설명을 사용합니다.',
            'og_image': '외부 방문자가 열 수 있는 HTTPS 이미지 주소. 서명·토큰·쿼리 없이 입력하세요. 서버에서 다운로드하지 않습니다.',
            'google_verification': 'google-site-verification 메타 태그의 content 값만 입력하세요.',
            'naver_verification': 'naver-site-verification 메타 태그의 content 값만 입력하세요.',
            'allow_indexing': '소개페이지에만 적용합니다. 로그인·업무 화면의 검색 제외는 유지됩니다.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.help_text = self.Meta.help_texts.get(name, field.help_text)
            if name not in ('allow_indexing', 'remove_image'):
                field.widget.attrs['class'] = 'input'
            if name in ('google_verification', 'naver_verification'):
                field.widget.attrs['autocomplete'] = 'off'

    def clean_og_upload(self):
        upload = self.cleaned_data.get('og_upload')
        if not upload:
            return None
        if upload.size > 5 * 1024 * 1024:
            raise forms.ValidationError('이미지는 5MB 이하로 업로드하세요.')
        try:
            content = normalised_png(io.BytesIO(upload.read()))
        except (ValueError, OSError):
            raise forms.ValidationError('올바른 PNG·JPG·GIF·WebP 이미지를 선택하세요.') from None
        return ContentFile(content, name=uuid.uuid4().hex + '.png')

    def clean(self):
        data = super().clean()
        for name in ('site_url', 'og_image'):
            value = data.get(name)
            if not value:
                continue
            parts = urlsplit(value)
            if parts.scheme != 'https' or not parts.hostname or parts.username is not None or parts.password is not None:
                self.add_error(name, '인증 정보가 없는 HTTPS 주소를 입력하세요.')
            elif name == 'og_image' and (parts.query or parts.fragment):
                self.add_error(name, '토큰·서명 등이 없는 공개 이미지 URL을 입력하세요. 쿼리·프래그먼트는 사용할 수 없습니다.')
            elif name == 'site_url':
                if parts.path not in ('', '/') or parts.query or parts.fragment:
                    self.add_error(name, '서비스 주소에는 경로·쿼리·프래그먼트를 넣을 수 없습니다.')
                else:
                    data[name] = value.rstrip('/')
        if data.get('og_upload') and data.get('remove_image'):
            self.add_error('remove_image', '업로드와 삭제 중 하나만 선택하세요.')
        has_upload = data.get('og_upload') or (self.instance.og_upload and not data.get('remove_image'))
        if has_upload and not (data.get('site_url') or inferred_service_url()):
            self.add_error('site_url', '공유 이미지의 공개 주소를 만들 대표 서비스 주소를 입력하세요.')
        for name in ('google_verification', 'naver_verification'):
            value = data.get(name, '')
            if any(char in value for char in '<>\r\n'):
                self.add_error(name, 'HTML 태그 없이 인증 코드 값만 입력하세요.')
        return data


@login_required
@require_http_methods(['GET', 'POST'])
def settings(request):
    if not request.user.is_staff:
        return HttpResponseForbidden('SEO 설정은 운영자만 관리할 수 있습니다.')
    config = SEOConfiguration.objects.filter(pk=1).first()
    if request.method == 'POST' and request.POST.get('action') == 'delete':
        if request.POST.get('confirm_delete') != 'yes':
            return HttpResponseBadRequest('삭제 확인이 필요합니다.')
        with transaction.atomic():
            SEOConfiguration.objects.filter(pk=1).delete()
            if config and config.og_upload:
                transaction.on_commit(lambda: cleanup_image(config.og_upload.storage, config.og_upload.name))
        messages.success(request, 'SEO 설정을 삭제했습니다. 기본 소개 정보로 돌아갑니다.')
        return redirect('seo_settings')
    if request.method == 'POST' and request.POST.get('action') != 'save':
        return HttpResponseBadRequest('올바르지 않은 작업입니다.')
    form = SEOForm(request.POST if request.method == 'POST' else None, request.FILES if request.method == 'POST' else None, instance=config)
    if request.method == 'POST' and form.is_valid():
        previous = config.og_upload.name if config and config.og_upload else ''
        config = form.save(commit=False)
        config.pk = 1
        upload = form.cleaned_data.get('og_upload')
        if upload:
            config.og_upload = upload
        elif form.cleaned_data.get('remove_image'):
            config.og_upload = ''
        with transaction.atomic():
            config.save()
            if previous and previous != config.og_upload.name:
                transaction.on_commit(lambda: cleanup_image(config.og_upload.storage, previous))
        messages.success(request, 'SEO 설정을 저장했습니다. 소개페이지에 반영됩니다.')
        return redirect('seo_settings')
    response = render(request, 'reportbuilder/seo_settings.html', {
        'form': form, 'saved': config is not None,
        'uploaded_image_url': image_path(config) if config and config.og_upload else '',
        'preview_title': DEFAULT_TITLE, 'preview_description': DEFAULT_DESCRIPTION,
        'preview_url': inferred_service_url() + '/intro' if inferred_service_url() else '대표 서비스 주소를 설정하세요.',
        **settings_navigation('basic', 'seo', request)})
    response['Cache-Control'] = 'no-store'
    return response


def metadata(request):
    """Never infer canonical URLs from an untrusted request Host."""
    try:
        config = SEOConfiguration.objects.filter(pk=1).first()
    except (OperationalError, ProgrammingError):
        config = None
    title = (config.title if config else '') or DEFAULT_TITLE
    description = (config.description if config else '') or DEFAULT_DESCRIPTION
    public = request.path in ('/intro', '/intro/')
    origin = (config.site_url if config else '') or inferred_service_url()
    return {'seo': {
        'title': title, 'description': description, 'keywords': config.keywords if config else '',
        'og_title': (config.og_title if config else '') or title,
        'og_description': (config.og_description if config else '') or description,
        'og_image': (origin + image_path(config) if config and config.og_upload and origin
                     else config.og_image if config else ''),
        'canonical': origin + '/intro' if public and origin else '',
        'robots': 'index, follow' if public and (not config or config.allow_indexing) else 'noindex, nofollow',
        'google_verification': config.google_verification if config and public else '',
        'naver_verification': config.naver_verification if config and public else '',
    }}


def cleanup_image(storage, name):
    try:
        storage.delete(name)
    except Exception:
        logger.warning('SEO image cleanup failed', exc_info=True)


def image_path(config):
    return reverse('seo_image', args=[PurePosixPath(config.og_upload.name).name])


@require_safe
def image(request, image_name):
    config = SEOConfiguration.objects.filter(pk=1).first()
    if not config or not config.og_upload or PurePosixPath(config.og_upload.name).name != image_name:
        raise Http404
    try:
        response = FileResponse(config.og_upload.open('rb'), content_type='image/png')
    except (FileNotFoundError, OSError):
        raise Http404 from None
    response['Cache-Control'] = 'no-cache'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
