import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from reportbuilder.models import AuditEvent, Connection, Project, Report

pytestmark = pytest.mark.django_db


@pytest.fixture
def managed_connection(client):
    owner = get_user_model().objects.create_user(username="connection-owner", is_staff=True)
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


def test_non_staff_cannot_edit_or_delete_connections(client, managed_connection):
    _, connection = managed_connection
    member = get_user_model().objects.create_user(username="member")
    client.force_login(member)

    assert client.post(reverse("connection_update", args=[connection.pk]), {}).status_code == 403
    assert client.post(reverse("connection_delete", args=[connection.pk])).status_code == 403
