import bleach
from bleach.css_sanitizer import CSSSanitizer
from django import forms
from django.contrib.auth import get_user_model
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils.html import strip_tags

from .models import Board, BoardCategory, BoardPost, BoardReply, BoardStatus


def clean_html(value):
    return bleach.clean(
        value, tags=['p', 'br', 'h2', 'h3', 'h4', 'strong', 'em', 'u', 's', 'blockquote',
                     'ul', 'ol', 'li', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
                     'span', 'div', 'a', 'code', 'pre', 'hr'],
        attributes={'*': ['style'], 'a': ['href', 'title'], 'td': ['colspan', 'rowspan'], 'th': ['colspan', 'rowspan']},
        protocols=['http', 'https', 'mailto'], strip=True, strip_comments=True,
        css_sanitizer=CSSSanitizer(allowed_css_properties=['color', 'background-color', 'font-weight',
                                                        'font-style', 'text-decoration', 'text-align', 'font-size']),
    )


class RichBodyMixin:
    def clean_body(self):
        value = clean_html(self.cleaned_data['body'])
        if not strip_tags(value).replace('\xa0', ' ').strip():
            raise forms.ValidationError('내용을 입력해 주세요.')
        return value


class BoardForm(forms.ModelForm):
    class Meta:
        model = Board
        fields = ['name', 'description', 'kind', 'active', 'allow_user_posts', 'managers', 'operators']
        widgets = {'description': forms.Textarea(attrs={'rows': 3}),
                   'managers': forms.SelectMultiple(attrs={'class': 'user-picker-select', 'data-user-select': 'true'}),
                   'operators': forms.SelectMultiple(attrs={'class': 'user-picker-select', 'data-user-select': 'true'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ['managers', 'operators']:
            selected_ids = self.data.getlist(field) if self.is_bound else (
                list(getattr(self.instance, field).values_list('pk', flat=True)) if self.instance.pk else []
            )
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
