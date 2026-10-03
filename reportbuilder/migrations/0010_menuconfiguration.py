from django.db import migrations, models
import reportbuilder.community_models


class Migration(migrations.Migration):
    dependencies = [
        ('reportbuilder', '0009_companybranding_board_boardcategory_boardpost_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='MenuConfiguration',
            fields=[
                ('id', models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ('items', models.JSONField(default=reportbuilder.community_models.default_menu_items)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
