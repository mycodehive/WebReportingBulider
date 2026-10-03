from django.db import migrations, models
from django.utils.text import slugify


def populate_board_slugs(apps, schema_editor):
    Board = apps.get_model("reportbuilder", "Board")
    used = set()
    for board in Board.objects.order_by("created_at", "id"):
        base = slugify(board.name) or f"board-{str(board.pk).replace('-', '')[:8]}"
        candidate = base[:150]
        suffix = 2
        while candidate in used:
            ending = f"-{suffix}"
            candidate = f"{base[:150 - len(ending)]}{ending}"
            suffix += 1
        board.slug = candidate
        board.save(update_fields=["slug"])
        used.add(candidate)


class Migration(migrations.Migration):
    dependencies = [("reportbuilder", "0010_menuconfiguration")]

    operations = [
        migrations.AddField(
            model_name="board",
            name="slug",
            field=models.SlugField(blank=True, max_length=150, verbose_name="URL slug"),
        ),
        migrations.RunPython(populate_board_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="board",
            name="slug",
            field=models.SlugField(blank=True, max_length=150, unique=True, verbose_name="URL slug"),
        ),
    ]
