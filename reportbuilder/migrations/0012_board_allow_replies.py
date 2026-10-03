from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reportbuilder", "0011_board_slug")]

    operations = [
        migrations.AddField(
            model_name="board",
            name="allow_replies",
            field=models.BooleanField(default=True, verbose_name="답변 / 댓글 허용"),
        ),
    ]
