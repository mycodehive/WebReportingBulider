import bleach
import re
from bleach.css_sanitizer import CSSSanitizer
from django import forms
from django.contrib.auth import get_user_model
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils.html import strip_tags
from urllib.parse import urlsplit
from html import unescape

from .board_media import normalize_board_media

from .models import Board, BoardCategory, BoardPost, BoardReply, BoardStatus


def board_attribute(tag, name, value):
    if name == 'style':
        return True
    allowed = {'a': ['href', 'title'], 'td': ['colspan', 'rowspan'], 'th': ['colspan', 'rowspan'],
               'img': ['src', 'alt', 'width', 'height'], 'iframe': ['src', 'title', 'width', 'height']}
    if name not in allowed.get(tag, []):
        return False
    if tag == 'a' and name == 'href':
        try:
            normalized = re.sub(r'[\x00-\x20\x7f-\xa0\ufffd]+', '', unescape(value))
            return urlsplit(normalized).scheme.lower() in {'', 'http', 'https', 'mailto'}
        except ValueError:
            return False
    return True


def clean_html(value):
    value = bleach.clean(
        value, tags=['p', 'br', 'h2', 'h3', 'h4', 'strong', 'em', 'b', 'i', 'u', 's', 'blockquote',
                     'ul', 'ol', 'li', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
                     'span', 'div', 'a', 'code', 'pre', 'hr', 'img', 'iframe'],
        attributes=board_attribute,
        protocols=['http', 'https', 'mailto', 'data'], strip=True, strip_comments=True,
        css_sanitizer=CSSSanitizer(allowed_css_properties=['color', 'background-color', 'font-weight',
                                                        'font-style', 'text-decoration', 'text-align', 'font-size']),
    )
    return normalize_board_media(value)


class RichBodyMixin:
    def clean_body(self):
        value = clean_html(self.cleaned_data['body'])
        if not strip_tags(value).replace('\xa0', ' ').strip() and '<img ' not in value and '<iframe ' not in value:
            raise forms.ValidationError('내용을 입력해 주세요.')
        return value


class BoardForm(forms.ModelForm):
    class Meta:
        model = Board
        fields = ['name', 'slug', 'description', 'kind', 'active', 'allow_user_posts', 'allow_replies', 'managers', 'operators']
        widgets = {'description': forms.Textarea(attrs={'rows': 3}),
                   'managers': forms.SelectMultiple(attrs={'class': 'user-picker-select', 'data-user-select': 'true'}),
                   'operators': forms.SelectMultiple(attrs={'class': 'user-picker-select', 'data-user-select': 'true'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['slug'].help_text = '게시판 주소: /boards/{slug}. 비워 두면 게시판 이름으로 자동 생성됩니다.'
        self.fields['allow_replies'].help_text = '끄면 새 답변과 댓글을 작성할 수 없습니다. 기존 답변과 댓글은 보존됩니다.'
        for field in ['managers', 'operators']:
            if self.is_bound:
                selected_ids = self.data.getlist(field) if hasattr(self.data, 'getlist') else self.data.get(field, [])
                if not isinstance(selected_ids, (list, tuple)):
                    selected_ids = [selected_ids] if selected_ids else []
            else:
                selected_ids = list(getattr(self.instance, field).values_list('pk', flat=True)) if self.instance.pk else []
            self.fields[field].queryset = get_user_model().objects.filter(
                is_active=True, pk__in=selected_ids
            ).order_by('username')

    def clean_kind(self):
        value = self.cleaned_data['kind']
        if self.instance.pk and self.instance.kind == 'qa' and value != 'qa' and self.instance.posts.exists():
            raise forms.ValidationError('질문이 있는 1:1 게시판은 공개 유형으로 변경할 수 없습니다. 새 게시판을 만들어 주세요.')
        return value


class StatusFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        if not any(f.cleaned_data.get('name') and not f.cleaned_data.get('DELETE') for f in self.forms):
            raise forms.ValidationError('상태를 한 개 이상 등록해 주세요. 첫 번째 상태가 새 질문의 기본 상태입니다.')


CategoryFormSet = inlineformset_factory(Board, BoardCategory, fields=['name', 'order'], extra=1, can_delete=True)
StatusFormSet = inlineformset_factory(Board, BoardStatus, formset=StatusFormSet, fields=['name', 'color', 'order'],
                                   widgets={'color': forms.TextInput(attrs={'type': 'color'})}, extra=1, can_delete=True)


class PostForm(RichBodyMixin, forms.ModelForm):
    class Meta:
        model = BoardPost
        fields = ['title', 'category', 'body', 'pinned', 'status']
        widgets = {'body': forms.Textarea(attrs={'class': 'rich-editor', 'rows': 12})}
        labels = {'category': '카테고리', 'status': '처리 상태'}

    def __init__(self, *args, board, moderator=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = board.categories.all()
        self.fields['body'].widget.attrs.pop('required', None)
        self.fields['body'].widget.is_required = False
        if not moderator:
            self.fields.pop('pinned')
        if moderator and board.kind == 'qa':
            self.fields['status'].queryset = board.statuses.all()
            self.fields['status'].required = True
            if not self.instance.status_id:
                first_status = board.statuses.first()
                self.initial['status'] = first_status.pk if first_status else None
        else:
            self.fields.pop('status')


class ReplyForm(RichBodyMixin, forms.ModelForm):
    class Meta:
        model = BoardReply
        fields = ['body']
        widgets = {'body': forms.Textarea(attrs={'class': 'rich-editor', 'rows': 6})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['body'].widget.is_required = False


class StatusChangeForm(forms.Form):
    status = forms.ModelChoiceField(label='처리 상태', queryset=BoardStatus.objects.none())

    def __init__(self, *args, board, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].queryset = board.statuses.all()
