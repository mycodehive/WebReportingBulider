from pathlib import Path

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


DEFAULT_MENUS = [
    ("dashboard", "대시보드", "/", 10, False),
    ("reports", "보고서 라이브러리", "/reports/", 20, False),
    ("connections", "데이터 연결", "/connections/", 30, False),
    ("boards", "게시판", "/boards/", 40, False),
    ("company", "회사 로고", "/settings/company/", 50, True),
    ("manual", "사용 가이드", "/manual/", 60, False),
    ("admin", "관리 설정", "/admin/", 70, True),
    ("menu_management", "메뉴관리", "/menu-management/", 80, True),
]


def seed_workspace_content(apps, schema_editor):
    Menu = apps.get_model("reportbuilder", "WorkspaceMenu")
    Manual = apps.get_model("reportbuilder", "ManualVersion")
    Configuration = apps.get_model("reportbuilder", "MenuConfiguration")
    try:
        config = Configuration.objects.filter(pk=1).first()
        configured = {item.get("key"): item for item in (config.items if config and isinstance(config.items, list) else [])
                      if isinstance(item, dict)}
    except Exception:
        configured = {}
    for key, label, url, order, staff_only in DEFAULT_MENUS:
        item = configured.get(key, {})
        Menu.objects.get_or_create(
            key=key,
            defaults={"label": item.get("label", label), "url": url,
                      "order": item.get("order", order), "staff_only": staff_only, "active": True},
        )
    manual_path = Path(__file__).resolve().parent.parent / "manual.md"
    try:
        content = manual_path.read_text(encoding="utf-8")
    except OSError:
        content = "# 사용 가이드\n\n보고서 라이브러리에서 보고서를 만들고 데이터 연결을 등록해 사용하세요."
    for audience in ("user", "admin"):
        Manual.objects.get_or_create(
            audience=audience, version="1.0",
            defaults={"content": content, "is_published": True},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("reportbuilder", "0012_board_allow_replies"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ManualVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("audience", models.CharField(choices=[("user", "사용자용"), ("admin", "관리자용")], max_length=10, verbose_name="대상")),
                ("version", models.CharField(max_length=40, verbose_name="버전")),
                ("content", models.TextField(verbose_name="매뉴얼 내용")),
                ("is_published", models.BooleanField(default=False, verbose_name="홈페이지 공개")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["audience", "-created_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="manualversion",
            constraint=models.UniqueConstraint(fields=("audience", "version"), name="manual_audience_version_unique"),
        ),
        migrations.CreateModel(
            name="WorkspaceMenu",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.SlugField(max_length=50, unique=True, verbose_name="키")),
                ("label", models.CharField(max_length=40, verbose_name="메뉴명")),
                ("url", models.CharField(max_length=255, verbose_name="내부 주소")),
                ("order", models.IntegerField(default=0, verbose_name="순서")),
                ("staff_only", models.BooleanField(default=False, verbose_name="관리자 전용")),
                ("active", models.BooleanField(default=True, verbose_name="사용")),
            ],
            options={"ordering": ["order", "label", "key"], "verbose_name": "워크스페이스 메뉴", "verbose_name_plural": "워크스페이스 메뉴"},
        ),
        migrations.RunPython(seed_workspace_content, migrations.RunPython.noop),
    ]
