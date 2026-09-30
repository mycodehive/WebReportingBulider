from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from reportbuilder.models import EmbedNonce, Execution


class Command(BaseCommand):
    help = "보존 기간이 지난 실행 스냅샷의 데이터와 HTML을 제거합니다. 감사 정보는 유지합니다."
    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24)
    def handle(self, *args, **options):
        if options["hours"] < 1:
            raise ValueError("hours must be positive")
        count = Execution.objects.filter(created_at__lt=timezone.now()-timedelta(hours=options["hours"])).update(
            rendered_html="", datasets_snapshot={}, definition_snapshot={}, bindings_snapshot={}, status="EXPIRED")
        EmbedNonce.objects.filter(expires_at__lt=timezone.now()).delete()
        self.stdout.write(f"{count}개 실행의 데이터 스냅샷을 제거했습니다.")
