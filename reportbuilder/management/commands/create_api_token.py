import hashlib
import secrets
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from reportbuilder.models import ApiToken
from reportbuilder.services import reports_for


class Command(BaseCommand):
    help = "범위와 만료가 있는 호스트 서버용 API 토큰을 생성합니다. 원문은 한 번만 출력합니다."
    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--report", action="append", required=True)
        parser.add_argument("--scope", action="append", choices=["read", "run", "edit", "embed"])
        parser.add_argument("--hours", type=int, default=24)
        parser.add_argument("--name", default="Host integration")
    def handle(self, *args, **options):
        user = get_user_model().objects.filter(username=options["username"], is_active=True).first()
        if not user or not 1 <= options["hours"] <= 720:
            raise CommandError("사용자와 만료 시간(1~720시간)을 확인하세요.")
        reports = []
        for id in options["report"]:
            try:
                reports.append(str(reports_for(user).get(pk=id).pk))
            except Exception:
                raise CommandError("접근할 수 없는 보고서 ID입니다.") from None
        raw = "wrb_" + secrets.token_urlsafe(32)
        ApiToken.objects.create(user=user, name=options["name"][:100], digest=hashlib.sha256(raw.encode()).hexdigest(),
                                scopes=options["scope"] or ["read", "run", "embed"], report_ids=reports,
                                expires_at=timezone.now() + timedelta(hours=options["hours"]))
        self.stdout.write(raw)
