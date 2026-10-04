import uuid
import io

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_safe

from .models import CompanyBranding
from .settings_navigation import settings_navigation
from .views import normalised_png


class BrandingForm(forms.Form):
    name = forms.CharField(label='회사명', max_length=120)
    logo = forms.FileField(label='로고 이미지', required=False)

    def clean_logo(self):
        upload = self.cleaned_data.get('logo')
        if not upload:
            return None
        if upload.size > 2 * 1024 * 1024:
            raise forms.ValidationError('로고 파일은 2MB 이하로 등록해 주세요.')
        try:
            return ContentFile(normalised_png(io.BytesIO(upload.read())), name=f'{uuid.uuid4().hex}.png')
        except (ValueError, OSError):
            raise forms.ValidationError('PNG, JPG, GIF, WebP 이미지 파일을 선택해 주세요.') from None


@require_safe
def logo(request):
    branding = CompanyBranding.objects.filter(pk=1).first()
    if not branding or not branding.logo:
        raise Http404
    try:
        response = FileResponse(branding.logo.open('rb'), content_type='image/png')
    except FileNotFoundError:
        raise Http404 from None
    response['Cache-Control'] = 'no-cache'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
@require_http_methods(['GET', 'POST'])
def settings(request):
    if not request.user.is_staff:
        return HttpResponseForbidden('회사 로고는 전체 관리자가 관리합니다.')
    branding = CompanyBranding.objects.filter(pk=1).first()
    form = BrandingForm(request.POST or None, request.FILES or None,
                        initial={'name': branding.name if branding else 'WebReportingBuilder'})
    if request.method == 'POST':
        if request.POST.get('action') == 'delete':
            if branding and branding.logo:
                branding.logo.delete(save=True)
            messages.success(request, '회사 로고를 삭제했습니다.')
            return redirect('company_settings')
        if form.is_valid():
            branding = branding or CompanyBranding(pk=1)
            previous = branding.logo.name
            branding.name = form.cleaned_data['name']
            if form.cleaned_data['logo']:
                branding.logo = form.cleaned_data['logo']
            branding.save()
            if previous and previous != branding.logo.name:
                branding.logo.storage.delete(previous)
            messages.success(request, '회사 정보를 저장했습니다.')
            return redirect('company_settings')
    return render(request, 'reportbuilder/company_settings.html', {'form': form, 'branding': branding, **settings_navigation('basic', 'company')})
