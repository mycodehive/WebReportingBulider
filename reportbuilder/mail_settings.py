"""Administrator-only mail configuration and bounded test delivery."""
import json
import re
from datetime import timedelta
from email.utils import formataddr
from urllib.parse import urlsplit

import boto3
import httpx
from botocore.config import Config
from cryptography.fernet import Fernet
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import EmailMessage
from django.core.mail.backends.smtp import EmailBackend
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import MailConfiguration
from .settings_navigation import settings_navigation

REGIONS = [(r, label + ' · ' + r) for r, label in [
    ('ap-northeast-2', 'Asia Pacific (Seoul)'), ('ap-northeast-1', 'Asia Pacific (Tokyo)'),
    ('ap-southeast-1', 'Asia Pacific (Singapore)'), ('ap-southeast-2', 'Asia Pacific (Sydney)'),
    ('ap-south-1', 'Asia Pacific (Mumbai)'), ('us-east-1', 'US East (N. Virginia)'),
    ('us-east-2', 'US East (Ohio)'), ('us-west-2', 'US West (Oregon)'),
    ('eu-west-1', 'Europe (Ireland)'), ('eu-west-2', 'Europe (London)'),
    ('eu-central-1', 'Europe (Frankfurt)'), ('ca-central-1', 'Canada (Central)'),
    ('sa-east-1', 'South America (São Paulo)')]]
SECRET_FIELDS = ('smtp_password', 'mailgun_key', 'ses_access_key', 'ses_secret_key')
GROUPS = {'smtp': ('smtp_encryption', 'smtp_host', 'smtp_port', 'smtp_username', 'smtp_password'),
          'mailgun': ('mailgun_domain', 'mailgun_key', 'mailgun_endpoint'),
          'ses': ('ses_access_key', 'ses_secret_key', 'ses_region')}


def secrets(config):
    if not config.encrypted_credentials:
        return {}
    return json.loads(Fernet(settings.REPORT_SECRET_KEY.encode()).decrypt(config.encrypted_credentials.encode()))


class MailForm(forms.Form):
    provider = forms.ChoiceField(label='메일러', choices=[('smtp', 'SMTP'), ('mailgun', 'Mailgun'), ('ses', 'SES (Amazon)')])
    smtp_encryption = forms.ChoiceField(label='암호화', choices=[('tls', 'TLS (STARTTLS)'), ('ssl', 'SSL/TLS'), ('none', '없음')], initial='tls')
    smtp_host = forms.CharField(label='SMTP 호스트', max_length=253, required=False)
    smtp_port = forms.IntegerField(label='포트', min_value=1, max_value=65535, initial=587, required=False)
    smtp_username = forms.CharField(label='사용자명', max_length=254, required=False)
    smtp_password = forms.CharField(label='비밀번호', max_length=4096, required=False, widget=forms.PasswordInput)
    mailgun_domain = forms.CharField(label='Mailgun 도메인', max_length=253, required=False)
    mailgun_key = forms.CharField(label='Mailgun API 키', max_length=4096, required=False, widget=forms.PasswordInput)
    mailgun_endpoint = forms.ChoiceField(label='Mailgun 엔드포인트', choices=[('api.mailgun.net', 'api.mailgun.net (미국)'), ('api.eu.mailgun.net', 'api.eu.mailgun.net (유럽)')])
    ses_access_key = forms.CharField(label='AWS 액세스 키', max_length=256, required=False, widget=forms.PasswordInput)
    ses_secret_key = forms.CharField(label='AWS 시크릿 키', max_length=4096, required=False, widget=forms.PasswordInput)
    ses_region = forms.ChoiceField(label='AWS 리전', choices=REGIONS, initial='ap-northeast-2')
    sender_email = forms.EmailField(label='발신자 이메일', max_length=254)
    sender_name = forms.CharField(label='발신자 이름', max_length=120)
    site_url = forms.URLField(label='서비스 주소 (인증 메일 링크)', required=False, max_length=500, assume_scheme='https',
                              help_text='운영 시 https://reports.example.com처럼 외부에서 접속 가능한 주소를 지정하세요.')

    def __init__(self, *args, configuration, **kwargs):
        self.configuration = configuration
        self.stored_secrets = secrets(configuration)
        super().__init__(*args, label_suffix='', initial=configuration.options, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs['class'] = 'input'
            if name in SECRET_FIELDS:
                field.widget.attrs['autocomplete'] = 'new-password'
                field.help_text = '등록됨 · 비워 두면 기존 값을 유지합니다.' if self.stored_secrets.get(name) else '저장 시 암호화됩니다.'
        self.fields['smtp_host'].widget.attrs['placeholder'] = 'smtp.example.com'
        self.fields['mailgun_domain'].widget.attrs['placeholder'] = 'mg.example.com'

    def clean_site_url(self):
        value = self.cleaned_data['site_url'].rstrip('/')
        if value:
            parts = urlsplit(value)
            if (parts.scheme not in ({'http', 'https'} if settings.DEBUG else {'https'})
                    or not parts.hostname or parts.username or parts.password or parts.path
                    or parts.query or parts.fragment or any(c in value for c in '\r\n\x00')):
                raise forms.ValidationError('경로·계정·쿼리 없는 서비스 주소를 입력하세요. 운영 시 HTTPS가 필수입니다.')
        return value

    def clean(self):
        data = super().clean()
        provider = data.get('provider')
        required = {'smtp': ['smtp_host', 'smtp_port'], 'mailgun': ['mailgun_domain', 'mailgun_key'],
                    'ses': ['ses_access_key', 'ses_secret_key']}.get(provider, [])
        for name in required:
            if not data.get(name) and not self.stored_secrets.get(name):
                self.add_error(name, '이 메일러에 필요한 항목입니다.')
        for name in ('smtp_host', 'mailgun_domain'):
            value = data.get(name, '')
            if value and not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?', value):
                self.add_error(name, '주소나 경로 대신 호스트 이름만 입력하세요.')
        for name in ('sender_name', 'smtp_username', *SECRET_FIELDS):
            if any(c in data.get(name, '') for c in '\r\n\x00'):
                self.add_error(name, '줄바꿈이나 제어 문자는 사용할 수 없습니다.')
        if provider == 'smtp':
            password = data.get('smtp_password') or self.stored_secrets.get('smtp_password')
            if data.get('smtp_username') and not password:
                self.add_error('smtp_password', 'SMTP 인증 비밀번호를 입력하세요.')
            if data.get('smtp_encryption') == 'none' and data.get('smtp_username'):
                self.add_error('smtp_encryption', '인증 정보를 보호하려면 TLS 또는 SSL/TLS를 사용하세요.')
            changed = any(data.get(n) != self.configuration.options.get(n) for n in ('smtp_host', 'smtp_port', 'smtp_encryption'))
            if changed and self.stored_secrets.get('smtp_password') and data.get('smtp_username') and not data.get('smtp_password'):
                self.add_error('smtp_password', '서버 또는 암호화를 변경하면 비밀번호를 다시 입력하세요.')
        return data

    def save(self):
        credentials = dict(self.stored_secrets)
        for name in SECRET_FIELDS:
            if self.cleaned_data.get(name):
                credentials[name] = self.cleaned_data[name]
        self.configuration.options = {k: v for k, v in self.cleaned_data.items() if k not in SECRET_FIELDS}
        self.configuration.encrypted_credentials = Fernet(settings.REPORT_SECRET_KEY.encode()).encrypt(json.dumps(credentials).encode()).decode()
        self.configuration.save(update_fields=['options', 'encrypted_credentials', 'updated_at'])


class TestMailForm(forms.Form):
    recipient = forms.EmailField(label='테스트 메일을 받을 이메일 주소', max_length=254, widget=forms.EmailInput(attrs={'class': 'input', 'placeholder': 'recipient@example.com'}))


def send_message(config, recipient, subject, body):
    options, credentials = config.options, secrets(config)
    sender = formataddr((options['sender_name'], options['sender_email']))
    if options['provider'] == 'smtp':
        backend = EmailBackend(host=options['smtp_host'], port=options['smtp_port'],
                               username=options['smtp_username'], password=credentials.get('smtp_password', ''),
                               use_tls=options['smtp_encryption'] == 'tls', use_ssl=options['smtp_encryption'] == 'ssl', timeout=10)
        with backend:
            if EmailMessage(subject, body, sender, [recipient], connection=backend).send() != 1:
                raise RuntimeError('delivery rejected')
    elif options['provider'] == 'mailgun':
        # Only fixed Mailgun hosts; no redirects, proxies, or arbitrary credential destinations.
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            response = client.post(f"https://{options['mailgun_endpoint']}/v3/{options['mailgun_domain']}/messages",
                                   auth=('api', credentials['mailgun_key']),
                                   files={k: (None, v) for k, v in {'from': sender, 'to': recipient, 'subject': subject, 'text': body}.items()})
            response.raise_for_status()
    else:
        client = boto3.client('sesv2', region_name=options['ses_region'],
                              aws_access_key_id=credentials['ses_access_key'], aws_secret_access_key=credentials['ses_secret_key'],
                              endpoint_url=f"https://email.{options['ses_region']}.amazonaws.com",
                              config=Config(connect_timeout=10, read_timeout=10, retries={'total_max_attempts': 1}, proxies={}))
        try:
            client.send_email(FromEmailAddress=sender, Destination={'ToAddresses': [recipient]},
                              Content={'Simple': {'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                                                  'Body': {'Text': {'Data': body, 'Charset': 'UTF-8'}}}})
        finally:
            client.close()


def send_test(config, recipient):
    send_message(config, recipient, '[WebReportingBuilder] 메일 설정 테스트',
                 '테스트 메일입니다. 이 메일을 수신했다면 메일 설정이 정상적으로 작동합니다.')


@login_required
@require_http_methods(['GET', 'POST'])
def mail(request):
    if not request.user.is_staff:
        return HttpResponseForbidden('메일 설정은 관리자만 이용할 수 있습니다.')
    config, _ = MailConfiguration.objects.get_or_create(pk=1)
    testing = request.method == 'POST' and request.POST.get('action') == 'test'
    form = MailForm(request.POST if request.method == 'POST' and not testing else None, configuration=config)
    test_form = TestMailForm(request.POST if testing else None)
    if request.method == 'POST':
        if testing and test_form.is_valid():
            # Revalidate stored configuration; never accept credentials from the test request.
            saved_form = MailForm(config.options, configuration=config)
            if not saved_form.is_valid():
                test_form.add_error(None, '먼저 올바른 메일 설정을 저장하세요.')
            else:
                now = timezone.now()
                reserved = MailConfiguration.objects.filter(pk=1).filter(Q(last_test_at__isnull=True) | Q(last_test_at__lte=now - timedelta(seconds=30))).update(last_test_at=now)
                if not reserved:
                    test_form.add_error(None, '테스트 발송은 30초 간격으로 실행할 수 있습니다.')
                else:
                    try:
                        send_test(config, test_form.cleaned_data['recipient'])
                        messages.success(request, '메일 서버가 테스트 메일을 접수했습니다. 받은 편지함과 스팸함을 확인하세요.')
                        return redirect('mail_settings')
                    except Exception:
                        test_form.add_error(None, '발송에 실패했습니다. 서버 주소·인증 정보·발신자 인증·수신자 제한·네트워크를 확인하세요.')
        elif not testing and form.is_valid():
            form.save()
            messages.success(request, '메일 설정을 저장했습니다.')
            return redirect('mail_settings')
    groups = [(provider, label, [form[name] for name in GROUPS[provider]]) for provider, label in [('smtp', 'SMTP 설정'), ('mailgun', 'Mailgun 설정'), ('ses', 'SES (Amazon) 설정')]]
    response = render(request, 'reportbuilder/mail_settings.html', {'form': form, 'test_form': test_form, 'groups': groups,
                      'saved': bool(config.options), **settings_navigation('basic', 'mail', request)})
    response['Cache-Control'] = 'no-store'
    return response
