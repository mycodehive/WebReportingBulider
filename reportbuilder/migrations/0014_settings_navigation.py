from django.db import migrations


def consolidate_settings(apps, schema_editor):
    Menu = apps.get_model("reportbuilder", "WorkspaceMenu")
    menus = Menu.objects.using(schema_editor.connection.alias)
    company = menus.filter(key="company").first()
    management = menus.filter(key="menu_management").first()
    existing = menus.filter(key="settings").first()
    order = company.order if company else existing.order if existing else management.order if management else 50
    menus.update_or_create(key="settings", defaults={
        "label": "환경설정", "url": "/settings/", "order": order,
        "staff_only": True, "active": True,
    })
    menus.filter(key__in=["company", "menu_management"]).delete()


class Migration(migrations.Migration):
    dependencies = [("reportbuilder", "0013_manual_versions_and_workspace_menus")]
    operations = [migrations.RunPython(consolidate_settings, migrations.RunPython.noop)]
