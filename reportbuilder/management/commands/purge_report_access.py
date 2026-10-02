from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from reportbuilder.models import ReportAccess


class Command(BaseCommand):
    help = "보존 기간이 지난 보고서 접속 통계만 삭제합니다. 기본 365일입니다."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=365)

    def handle(self, *args, **options):
        if options["days"] < 1:
            raise CommandError("--days는 1 이상의 정수여야 합니다.")
        count, _ = ReportAccess.objects.filter(
            created_at__lt=timezone.now() - timedelta(days=options["days"])
        ).delete()
        self.stdout.write(self.style.SUCCESS(f"접속 기록 {count}개 정리 완료"))
