import io

import pytest
from django.core.management import call_command

from reportbuilder.models import Connection, Project, Publication, Report, Revision

pytestmark = pytest.mark.django_db


def test_seed_demo_reset_recreates_example_without_deleting_shared_source(django_user_model, settings, tmp_path):
    admin = django_user_model.objects.create_user(username="demo-admin", is_staff=True, is_active=True)
    settings.MEDIA_ROOT = tmp_path
    output = io.StringIO()
    call_command("seed_demo", username=admin.username, stdout=output)
    first = Report.objects.get(owner=admin, name="매출 현황 예제")
    shared_connection_id = first.bindings[0]["connection_id"]
    source = Connection.objects.get(pk=shared_connection_id)

    unrelated_project = Project.objects.create(owner=admin, name="내 프로젝트")
    unrelated = Report.objects.create(owner=admin, project=unrelated_project, name="내 보고서",
                                      bindings=[{"connection_id": shared_connection_id}])
    call_command("seed_demo", username=admin.username, reset=True, stdout=output)

    replacement = Report.objects.get(owner=admin, name="매출 현황 예제")
    assert replacement.pk != first.pk
    assert Report.objects.filter(pk=unrelated.pk).exists()
    assert Connection.objects.filter(pk=source.pk).exists()
    assert replacement.bindings[0]["connection_id"] != shared_connection_id
    assert "예제 준비 완료" in output.getvalue()


def test_seed_demo_reset_deletes_existing_publication_before_report(django_user_model, settings, tmp_path):
    admin = django_user_model.objects.create_user(username="published-demo-admin", is_staff=True, is_active=True)
    settings.MEDIA_ROOT = tmp_path
    output = io.StringIO()
    call_command("seed_demo", username=admin.username, stdout=output)
    first = Report.objects.get(owner=admin, name="매출 현황 예제")
    revision = first.revisions.get(number=1)
    Publication.objects.create(report=first, revision=revision)

    call_command("seed_demo", username=admin.username, reset=True, stdout=output)

    replacement = Report.objects.get(owner=admin, name="매출 현황 예제")
    assert replacement.pk != first.pk
    assert not Publication.objects.filter(report=first).exists()
    assert "예제 준비 완료" in output.getvalue()


def test_seed_demo_reset_preserves_connection_used_by_published_revision(django_user_model, settings, tmp_path):
    admin = django_user_model.objects.create_user(username="published-source-admin", is_staff=True, is_active=True)
    settings.MEDIA_ROOT = tmp_path
    output = io.StringIO()
    call_command("seed_demo", username=admin.username, stdout=output)
    first = Report.objects.get(owner=admin, name="매출 현황 예제")
    shared_connection_id = first.bindings[0]["connection_id"]
    source = Connection.objects.get(pk=shared_connection_id)

    unrelated_project = Project.objects.create(owner=admin, name="내 프로젝트")
    unrelated = Report.objects.create(owner=admin, project=unrelated_project, name="내 보고서",
                                      definition=first.definition, bindings=[])
    old_revision = Revision.objects.create(report=unrelated, number=1, definition=first.definition,
                                           bindings=[{"connection_id": shared_connection_id}])
    Publication.objects.create(report=unrelated, revision=old_revision)

    call_command("seed_demo", username=admin.username, reset=True, stdout=output)

    assert Report.objects.filter(pk=unrelated.pk).exists()
    assert Connection.objects.filter(pk=source.pk).exists()
    assert "예제 준비 완료" in output.getvalue()
