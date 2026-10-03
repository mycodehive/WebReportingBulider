import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from reportbuilder.models import AuditEvent, Connection, Project, Report

pytestmark = pytest.mark.django_db


@pytest.fixture(params=[False, True], ids=["member", "staff"])
def managed_connection(client, request):
    owner = get_user_model().objects.create_user(username="connection-owner", is_staff=request.param)
    connection = Connection.objects.create(
        owner=owner,
        name="Warehouse",
        kind="postgresql",
        config={"host": "db.internal", "database": "reports"},
        status="CONNECTED",
        last_test_at=timezone.now(),
    )
    connection.set_secrets({"password": "old-secret"})
    connection.save(update_fields=["encrypted_secrets"])
    client.force_login(owner)
    return owner, connection


def test_connection_edit_hides_and_preserves_secrets(client, managed_connection):
    owner, connection = managed_connection
    page = client.get(reverse("connections"))
    assert b"old-secret" not in page.content
    assert b"password" in page.content

    response = client.post(reverse("connection_update", args=[connection.pk]), {
        "name": "Updated warehouse",
        "config": json.dumps({"host": "db-new.internal", "database": "reports"}),
        "secret_updates": json.dumps({"password": "new-secret"}),
    })

    assert response.status_code == 302
    connection.refresh_from_db()
    assert connection.name == "Updated warehouse"
    assert connection.config["host"] == "db-new.internal"
    assert connection.get_secrets() == {"password": "new-secret"}
    assert connection.status == "UNTESTED"
    assert connection.last_test_at is None
    assert AuditEvent.objects.filter(user=owner, action="connection_update", resource_id=str(connection.pk)).exists()


def test_connection_edit_keeps_existing_secret_when_secret_json_is_empty(client, managed_connection):
    _, connection = managed_connection

    response = client.post(reverse("connection_update", args=[connection.pk]), {
        "name": connection.name,
        "config": json.dumps(connection.config),
        "secret_updates": "",
    })

    assert response.status_code == 302
    connection.refresh_from_db()
    assert connection.get_secrets() == {"password": "old-secret"}


def test_edit_form_hides_and_invalidates_pending_oauth_attempt(client, managed_connection):
    _, connection = managed_connection
    connection.config["auth_mode"] = "oauth"
    connection.config["oauth_attempt"] = "pending-state-hash"
    connection.save(update_fields=["config"])

    page = client.get(reverse("connections"))
    assert b"pending-state-hash" not in page.content

    client.post(reverse("connection_update", args=[connection.pk]), {
        "name": connection.name,
        "config": json.dumps({"auth_mode": "oauth"}),
        "secret_updates": "{}",
    })
    connection.refresh_from_db()
    assert "oauth_attempt" not in connection.config


def test_connection_edit_rejects_secrets_in_public_config(client, managed_connection):
    _, connection = managed_connection

    client.post(reverse("connection_update", args=[connection.pk]), {
        "name": connection.name,
        "config": json.dumps({"host": "db.internal", "password": "plaintext"}),
        "secret_updates": "{}",
    })

    connection.refresh_from_db()
    assert "password" not in connection.config
    assert connection.get_secrets() == {"password": "old-secret"}


def test_only_connection_owner_can_edit_or_delete(client, managed_connection):
    _, connection = managed_connection
    other_staff = get_user_model().objects.create_user(username="other-staff", is_staff=True)
    client.force_login(other_staff)

    assert client.post(reverse("connection_update", args=[connection.pk]), {}).status_code == 404
    assert client.post(reverse("connection_delete", args=[connection.pk])).status_code == 404
    assert Connection.objects.filter(pk=connection.pk).exists()


def test_connection_delete_warns_and_removes_connection(client, managed_connection):
    owner, connection = managed_connection
    project = Project.objects.create(owner=owner, name="Finance")
    report = Report.objects.create(owner=owner, project=project, name="Summary", bindings=[
        {"connection_id": str(connection.pk), "dataset_id": "sales"},
    ])

    response = client.post(reverse("connection_delete", args=[connection.pk]))

    assert response.status_code == 302
    assert not Connection.objects.filter(pk=connection.pk).exists()
    assert Report.objects.filter(pk=report.pk).exists()
    assert AuditEvent.objects.filter(user=owner, action="connection_delete", resource_id=str(connection.pk)).exists()
    assert any("다시 매핑해야 합니다" in str(message) for message in response.wsgi_request._messages)


def test_non_owner_cannot_edit_or_delete_connections(client, managed_connection):
    _, connection = managed_connection
    member = get_user_model().objects.create_user(username="member")
    client.force_login(member)

    assert client.post(reverse("connection_update", args=[connection.pk]), {}).status_code == 404
    assert client.post(reverse("connection_delete", args=[connection.pk])).status_code == 404


@pytest.mark.parametrize("staff", [False, True], ids=["member", "staff"])
def test_users_create_private_connections_from_form_and_api(client, settings, tmp_path, staff):
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.MEDIA_ROOT = tmp_path
    user = get_user_model().objects.create_user(username="own-connections", is_staff=staff)
    other = get_user_model().objects.create_user(username="another-owner")
    client.force_login(user)
    page = client.get(reverse("connections")).content.decode()
    assert "새 연결 등록" in page
    assert "관리자에게 데이터 연결 등록을 요청하세요" not in page
    response = client.post(reverse("connections"), {
        "name": "My uploaded CSV", "kind": "csv", "config": "{}", "owner": other.pk,
        "file": SimpleUploadedFile("data.csv", b"name,amount\nexample,42\n", content_type="text/csv"),
    })
    assert response.status_code == 302
    uploaded = Connection.objects.get(name="My uploaded CSV")
    assert uploaded.owner == user
    assert client.post(f"/api/connections/{uploaded.pk}/test/").status_code == 200
    assert client.get(f"/api/connections/{uploaded.pk}/schema/").status_code == 200

    response = client.post("/api/connections/", {
        "name": "My database", "kind": "postgresql", "owner": other.pk,
        "config": {"host": "example.test", "password": "private-password"},
    }, content_type="application/json")
    assert response.status_code == 201
    connection = Connection.objects.get(pk=response.json()["id"])
    assert connection.owner == user
    assert connection.get_secrets()["password"] == "private-password"
    assert "password" not in connection.config
    page = client.get(reverse("connections")).content.decode()
    assert f'data-edit-connection="{connection.pk}"' in page
    assert "private-password" not in page
    assert "private-password" not in client.get("/api/connections/").content.decode()
    assert AuditEvent.objects.filter(user=user, action="connection_create", resource_id=str(connection.pk)).exists()


@pytest.mark.parametrize("staff", [False, True], ids=["member", "staff"])
def test_connection_settings_are_isolated_even_with_shared_group(client, managed_connection, staff):
    from unittest.mock import patch
    from django.contrib.auth.models import Group

    owner, connection = managed_connection
    viewer = get_user_model().objects.create_user(username="private-viewer", is_staff=staff)
    own = Connection.objects.create(owner=viewer, name="Visible own connection", kind="postgresql")
    group = Group.objects.create(name="Same department")
    owner.groups.add(group)
    viewer.groups.add(group)
    connection.groups.add(group)
    client.force_login(viewer)

    page = client.get(reverse("connections")).content.decode()
    assert connection.name not in page
    assert str(connection.pk) not in page
    assert own.name in page
    assert client.get("/api/connections/").json()["connections"] == [
        {"id": str(own.pk), "name": own.name, "kind": own.kind, "status": own.status},
    ]
    with patch("reportbuilder.views.test_connection") as test_connection, patch("reportbuilder.views.introspect") as schema:
        assert client.post(f"/api/connections/{connection.pk}/test/").status_code == 404
        assert client.get(f"/api/connections/{connection.pk}/schema/").status_code == 404
        test_connection.assert_not_called()
        schema.assert_not_called()
    assert client.post(reverse("connection_update", args=[connection.pk]), {
        "name": "Hijacked", "config": "{}", "owner": viewer.pk,
    }).status_code == 404
    assert client.post(reverse("connection_delete", args=[connection.pk])).status_code == 404
    connection.refresh_from_db()
    assert connection.owner == owner
    assert connection.name == "Warehouse"


def test_member_mutations_require_login_and_csrf(settings, tmp_path):
    from django.test import Client

    settings.MEDIA_ROOT = tmp_path
    strict = Client(enforce_csrf_checks=True)
    assert strict.get(reverse("connections")).status_code == 302
    assert strict.get("/api/connections/").status_code == 401
    user = get_user_model().objects.create_user(username="csrf-member")
    strict.force_login(user)
    strict.get(reverse("connections"))
    payload = {"name": "Protected", "kind": "postgresql", "config": "{}"}
    assert strict.post(reverse("connections"), payload).status_code == 403
    assert not Connection.objects.filter(owner=user).exists()
    assert strict.post(reverse("connections"), payload,
                       HTTP_X_CSRFTOKEN=strict.cookies["csrftoken"].value).status_code == 302
    connection = Connection.objects.get(owner=user)
    assert strict.post(reverse("connection_update", args=[connection.pk]), payload).status_code == 403
    assert strict.post(reverse("connection_delete", args=[connection.pk])).status_code == 403
