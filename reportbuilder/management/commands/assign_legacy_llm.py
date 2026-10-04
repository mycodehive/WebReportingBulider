from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from reportbuilder.models import LLMConfiguration


class Command(BaseCommand):
    help = 'Assign preserved legacy LLM settings without an owner to a specified administrator.'

    def add_arguments(self, parser):
        parser.add_argument('--user-id', type=int, required=True)

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(pk=options['user_id'], is_staff=True).first()
        if not user:
            raise CommandError('지정한 관리자 계정을 찾을 수 없습니다.')
        with transaction.atomic():
            rows = LLMConfiguration.objects.select_for_update().filter(owner__isnull=True)
            if LLMConfiguration.objects.filter(owner=user, name__in=rows.values('name')).exists():
                raise CommandError('같은 연결명이 있습니다. 사용자 연결명을 변경한 뒤 다시 실행하세요.')
            count = rows.update(owner=user)
        self.stdout.write(f'기존 LLM 설정 {count}개를 지정한 관리자에게 할당했습니다.')
