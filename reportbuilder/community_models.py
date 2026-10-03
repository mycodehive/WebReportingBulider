import uuid

from django.utils.text import slugify

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models


class CompanyBranding(models.Model):
    name = models.CharField('회사명', max_length=120, default='WebReportingBuilder')
    logo = models.FileField(upload_to='branding/', blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class Board(models.Model):
    TYPES = [('list', '리스트형'), ('card', '카드형'), ('qa', '질문답변형 (1:1)')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField('게시판 이름', max_length=120)
    slug = models.SlugField('URL slug', max_length=150, unique=True, blank=True)
    description = models.TextField('설명', blank=True, max_length=1000)
    kind = models.CharField('게시판 유형', max_length=8, choices=TYPES, default='list')
    active = models.BooleanField('사용', default=True)
    allow_user_posts = models.BooleanField('사용자 글쓰기 허용', default=True)
    managers = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='managed_boards', verbose_name='게시판 관리자')
    operators = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='operated_boards', verbose_name='게시판 운영자')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name', 'id']

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or f'board-{self.pk.hex[:8]}'
            candidate = base[:150]
            suffix = 2
            while Board.objects.exclude(pk=self.pk).filter(slug=candidate).exists():
                ending = f'-{suffix}'
                candidate = f'{base[:150 - len(ending)]}{ending}'
                suffix += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class BoardCategory(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField('카테고리 이름', max_length=80)
    order = models.PositiveIntegerField('순서', default=0)

    class Meta:
        ordering = ['order', 'id']
        constraints = [models.UniqueConstraint(fields=['board', 'name'], name='board_category_name')]

    def __str__(self):
        return self.name


class BoardStatus(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='statuses')
    name = models.CharField('상태 이름', max_length=40)
    color = models.CharField('색상', max_length=7, default='#2563eb', validators=[RegexValidator(r'^#[0-9a-fA-F]{6}$', '색상은 #RRGGBB 형식이어야 합니다.')])
    order = models.PositiveIntegerField('순서', default=0)

    class Meta:
        ordering = ['order', 'id']
        constraints = [models.UniqueConstraint(fields=['board', 'name'], name='board_status_name')]

    def __str__(self):
        return self.name


class BoardPost(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='posts')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='board_posts')
    title = models.CharField('제목', max_length=200)
    body = models.TextField('내용', max_length=100000)
    category = models.ForeignKey(BoardCategory, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.ForeignKey(BoardStatus, null=True, blank=True, on_delete=models.SET_NULL)
    pinned = models.BooleanField('상단 고정', default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-pinned', '-updated_at', '-id']


class BoardReply(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(BoardPost, on_delete=models.CASCADE, related_name='replies')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField('답변 / 댓글', max_length=100000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at', 'id']


def default_menu_items():
    return [
        {'key': 'dashboard', 'label': '대시보드', 'order': 10},
        {'key': 'reports', 'label': '보고서 라이브러리', 'order': 20},
        {'key': 'connections', 'label': '데이터 연결', 'order': 30},
        {'key': 'boards', 'label': '게시판', 'order': 40},
        {'key': 'company', 'label': '회사 로고', 'order': 50},
        {'key': 'manual', 'label': '사용 가이드', 'order': 60},
        {'key': 'admin', 'label': '관리 설정', 'order': 70},
        {'key': 'menu_management', 'label': '메뉴관리', 'order': 80},
    ]


class MenuConfiguration(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    items = models.JSONField(default=default_menu_items)
    updated_at = models.DateTimeField(auto_now=True)

