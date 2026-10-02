import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reportbuilder", "0002_embednonce_apitoken")]

    operations = [
        migrations.CreateModel(
            name="ReportAccess",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("event", models.CharField(choices=[("view", "View"), ("execute", "Execute"), ("embed", "Embed")], max_length=10)),
                ("country", models.CharField(default="Unknown", max_length=7)),
                ("device", models.CharField(choices=[(x, x) for x in ("desktop", "mobile", "tablet", "bot", "unknown")], default="unknown", max_length=10)),
                ("browser", models.CharField(choices=[(x, x) for x in ("chrome", "edge", "firefox", "safari", "opera", "other", "unknown")], default="unknown", max_length=10)),
                ("os", models.CharField(choices=[(x, x) for x in ("windows", "macos", "linux", "android", "ios", "chromeos", "other", "unknown")], default="unknown", max_length=10)),
                ("report", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="access_events", to="reportbuilder.report")),
            ],
            options={
                "ordering": ["-created_at", "-pk"],
                "indexes": [
                    models.Index(fields=["report", "created_at"], name="access_report_time_idx"),
                    models.Index(fields=["report", "event", "created_at"], name="access_report_event_idx"),
                    models.Index(fields=["created_at"], name="access_retention_idx"),
                ],
            },
        ),
    ]
