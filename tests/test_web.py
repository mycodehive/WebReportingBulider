import copy
import hashlib
import io
import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.test import Client
from django.utils import timezone
from openpyxl import load_workbook
from PIL import Image

from reportbuilder.definition import default_definition
from reportbuilder.management.commands.seed_demo import demo_definition
from reportbuilder.models import ApiToken, Connection, Execution, Project, Publication, Report, Revision

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin():
    return get_user_model().objects.create_user(username="author", password="StrongTestPass123!", is_staff=True)


@pytest.fixture
def author_client(client, admin):
    client.force_login(admin)
    return client


@pytest.fixture
def data_report(admin, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    connection = Connection.objects.create(name="Data", owner=admin, kind="csv", config={},
                            upload=ContentFile(b"department,customer,amount\nA,Alice,100\nA,Bob,200\n", name="data.csv"))
    from reportbuilder.data import introspect
    name = introspect("csv", connection.runtime_config())["objects"][0]["object"]
    definition = demo_definition()
    binding = {"dataset_id": "sales", "connection_id": str(connection.pk),
               "object_mappings": {"sales_rows": {"schema": None, "object": name}},
               "field_mappings": {field: {"column": field, "conversion": "to_decimal" if field == "amount" else "identity"}
                                  for field in ["department", "customer", "amount"]}}
    project = Project.objects.create(owner=admin, name="Demo")
    report = Report.objects.create(owner=admin, name="Demo", project=project, definition=definition, bindings=[binding], revision=1)
    Revision.objects.create(report=report, number=1, definition=definition, bindings=[binding])
    return report, connection


def post(client, url, data=None, method="post"):
    return getattr(client, method)(url, data=json.dumps(data or {}), content_type="application/json")


def test_authentication_csrf_and_creation(admin):
    c = Client(enforce_csrf_checks=True)
    assert post(c, "/api/reports/", {"name": "A"}).status_code == 403
    c.force_login(admin)
    assert post(c, "/api/reports/", {"name": "A"}).status_code == 403
    assert c.get("/").status_code == 200
    response = c.post("/api/reports/", data=json.dumps({"name": "Test"}), content_type="application/json",
                      HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    assert response.status_code == 201
    assert response.json()["revision"] == 1


def test_snapshot_exports_and_revision_conflict(author_client, data_report):
    report, connection = data_report
    response = post(author_client, f"/api/reports/{report.pk}/preview/")
    assert response.status_code == 200, response.content
    snapshot = response.json()
    assert snapshot["row_count"] == 2 and snapshot["page_count"] == 1
    assert "Alice" in snapshot["html"] and "300" in snapshot["html"]
    # Changing the source must not change an already generated output.
    connection.upload.save("new.csv", ContentFile(b"department,customer,amount\nA,Changed,900\n"))
    url = f"/reports/{report.pk}/export/xlsx/?execution={snapshot['execution_id']}"
    xlsx = author_client.get(url)
    assert xlsx.status_code == 200
    workbook = load_workbook(io.BytesIO(xlsx.content))
    assert workbook.active["B2"].value == "Alice"
    bad = post(author_client, f"/api/reports/{report.pk}/", {"definition": report.definition, "expected_revision": 0}, "put")
    assert bad.status_code == 409


def test_cross_user_access_and_policy_revocation(author_client, data_report):
    report, connection = data_report
    other = get_user_model().objects.create_user(username="viewer")
    c = Client()
    c.force_login(other)
    assert c.get(f"/api/reports/{report.pk}/").status_code == 404
    group = Group.objects.create(name="Viewers")
    other.groups.add(group)
    report.viewer_groups.add(group)
    assert post(author_client, f"/api/reports/{report.pk}/publish/").status_code == 200
    assert post(c, f"/api/reports/{report.pk}/execute/").status_code == 403
    connection.groups.add(group)
    response = post(c, f"/api/reports/{report.pk}/execute/")
    assert response.status_code == 200
    execution_id = response.json()["execution_id"]
    assert post(c, f"/api/reports/{report.pk}/preview/").status_code == 403
    connection.allowed_columns = {report.bindings[0]["object_mappings"]["sales_rows"]["object"]: ["department", "customer"]}
    connection.save()
    assert c.get(f"/reports/{report.pk}/export/html/?execution={execution_id}").status_code == 403
    assert post(c, f"/api/reports/{report.pk}/execute/").status_code == 403


def test_published_revision_is_immutable(author_client, data_report):
    report, _ = data_report
    assert post(author_client, f"/api/reports/{report.pk}/publish/").status_code == 200
    definition = copy.deepcopy(report.definition)
    definition["pages"][0]["bands"][0]["elements"][0]["text"] = "New draft title"
    response = post(author_client, f"/api/reports/{report.pk}/", {"definition": definition, "expected_revision": 1}, "put")
    assert response.status_code == 200
    publication = Publication.objects.get(report=report)
    assert publication.revision.number == 1
    response = post(author_client, f"/api/reports/{report.pk}/execute/")
    assert "New draft title" not in response.json()["html"]
    response = post(author_client, f"/api/reports/{report.pk}/preview/")
    assert "New draft title" in response.json()["html"]


def test_publication_link_is_stable_and_available_without_republishing(author_client, data_report):
    report, _ = data_report
    endpoint = f"/api/reports/{report.pk}/"
    assert author_client.get(endpoint).json()["publication_url"] is None
    url = post(author_client, endpoint + "publish/").json()["publication_url"]
    assert author_client.get(endpoint).json()["publication_url"] == url
    page = author_client.get(f"/reports/{report.pk}/design/")
    assert page.context["publication_url"] == url
    assert f'href="{url}"'.encode() in page.content
    assert b'value="1" selected>100%' in page.content
    assert post(author_client, endpoint + "publish/").json()["publication_url"] == url
    post(author_client, endpoint + "publish/", {"enabled": False})
    assert author_client.get(endpoint).json()["publication_url"] is None
    assert author_client.get(f"/reports/{report.pk}/design/").context["publication_url"] is None
    assert post(author_client, endpoint + "publish/").json()["publication_url"] == url


def test_report_cover_upload_replacement_removal_and_permissions(author_client, data_report):
    report, _ = data_report
    endpoint = f'/reports/{report.pk}/cover/'
    def upload(color):
        stream = io.BytesIO()
        Image.new('RGB', (80, 40), color).save(stream, format='JPEG')
        return ContentFile(stream.getvalue(), name='cover.jpg')
    assert author_client.post(endpoint, {'cover':upload('blue')}).status_code == 302
    report.refresh_from_db()
    first = report.cover_id
    assert report.cover.mime == 'image/png'
    assert f'/assets/{first}/'.encode() in author_client.get('/reports/').content
    assert author_client.post(endpoint, {'cover':ContentFile(b'invalid', name='bad.png')}).status_code == 302
    report.refresh_from_db()
    assert report.cover_id == first
    author_client.post(endpoint, {'cover':upload('red')})
    report.refresh_from_db()
    assert report.cover_id != first
    other = Client()
    other.force_login(get_user_model().objects.create_user(username='cover-stranger'))
    assert other.post(endpoint, {'remove':'yes'}).status_code == 404
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(report.owner)
    assert strict.post(endpoint, {'remove':'yes'}).status_code == 403
    author_client.post(endpoint, {'remove':'yes'})
    report.refresh_from_db()
    assert report.cover_id is None


def test_infographic_data_uses_mapped_values_and_enforces_edit_access(author_client, data_report):
    report, _ = data_report
    endpoint = f'/api/reports/{report.pk}/infographic-data/'
    data = {'dataset_id':'sales','label_id':'department','value_id':'amount'}
    response = post(author_client, endpoint, data)
    assert response.status_code == 200, response.content
    assert response.json()['points'] == [{'label':'A','value':300}]
    assert 'no-store' in response['Cache-Control']
    assert post(author_client, endpoint, {**data,'aggregation':'avg'}).json()['points'] == [{'label':'A','value':150}]
    assert post(author_client, endpoint, {**data,'value_id':'customer'}).status_code == 400
    stranger = get_user_model().objects.create_user(username='chart-stranger')
    other = Client()
    other.force_login(stranger)
    assert post(other, endpoint, data).status_code == 404


def test_project_export_import_is_unbound_and_can_rebind(author_client, admin, data_report, settings, tmp_path):
    report, connection = data_report
    package = author_client.get(f"/reports/{report.pk}/export/project/")
    assert package.status_code == 200
    assert str(connection.pk).encode() not in package.content
    imported = author_client.post("/projects/import/", {"file": ContentFile(package.content, name="demo.wrpx")}, HTTP_ACCEPT="application/json")
    assert imported.status_code == 200, imported.content
    value = imported.json()["reports"][0]
    assert value["bindings"] == []
    new_id = value["id"]
    assert post(author_client, f"/api/reports/{new_id}/preview/").json()["code"] == "MAPPING_REQUIRED"
    assert post(author_client, f"/api/reports/{new_id}/bindings/", {"bindings": report.bindings}, "put").status_code == 200
    result = post(author_client, f"/api/reports/{new_id}/preview/")
    assert result.status_code == 200 and "Alice" in result.json()["html"]


def test_connections_are_admin_only_and_credentials_encrypted(author_client, admin):
    response = post(author_client, "/api/connections/", {"name": "DB", "kind": "postgresql",
                    "config": {"host": "localhost", "password": "super-private-test-password"}})
    assert response.status_code == 201
    connection = Connection.objects.get(pk=response.json()["id"])
    assert "super-private-test-password" not in json.dumps(connection.config)
    assert "super-private-test-password" not in connection.encrypted_secrets
    assert connection.runtime_config()["password"] == "super-private-test-password"
    assert "password" not in author_client.get("/api/connections/").content.decode()
    c = Client()
    c.force_login(get_user_model().objects.create_user(username="normal"))
    assert post(c, "/api/connections/", {"name": "DB", "kind": "rest", "config": {}}).status_code == 403
    assert post(author_client, "/api/connections/", {"name": "DB", "kind": "rest", "config": {"allowed_hosts": ["evil"]}}).status_code == 400


def test_assets_remap_safely(author_client, data_report):
    report, _ = data_report
    out = io.BytesIO()
    Image.new("RGB", (20, 20)).save(out, "PNG")
    uploaded = author_client.post("/api/assets/", {"file": ContentFile(out.getvalue(), name="image.png"), "report_id": str(report.pk)})
    assert uploaded.status_code == 201
    value = uploaded.json()
    definition = default_definition("Image report")
    definition["pages"][0]["elements"].append({"element_id": "img1", "type": "image", "asset_id": value["id"],
                                              "geometry": {"x_mm": 0, "y_mm": 20, "width_mm": 20, "height_mm": 20}})
    assert post(author_client, f"/api/reports/{report.pk}/", {"definition": definition, "expected_revision": 1}, "put").status_code == 200
    package = author_client.get(f"/reports/{report.pk}/export/project/")
    imported = author_client.post("/projects/import/", {"file": ContentFile(package.content, name="image.wrpx")}, HTTP_ACCEPT="application/json")
    assert imported.status_code == 200, imported.content
    new = imported.json()["reports"][0]
    assert new["definition"]["pages"][0]["elements"][1]["asset_id"] != value["id"]
    assert post(author_client, f"/api/reports/{new['id']}/preview/").status_code == 200


def test_embed_token_is_scoped_expiring_and_single_use(author_client, admin, data_report, settings):
    report, _ = data_report
    settings.EMBED_ALLOWED_ORIGINS = ["https://host.example"]
    post(author_client, f"/api/reports/{report.pk}/publish/")
    response = post(author_client, "/api/embed-sessions/", {"report_id": str(report.pk), "origin": "https://host.example"})
    assert response.status_code == 200
    token = response.json()["token"]
    browser = Client(enforce_csrf_checks=True)
    result = browser.post("/embed/", {"token": token}, HTTP_ORIGIN="https://host.example")
    assert result.status_code == 200 and "Alice" in result.content.decode()
    assert "frame-ancestors https://host.example" in result["Content-Security-Policy"]
    assert browser.post("/embed/", {"token": token}, HTTP_ORIGIN="https://host.example").status_code == 403
    assert browser.post("/embed/", {"token": "invalid"}, HTTP_ORIGIN="https://host.example").status_code == 403


def test_bearer_token_needs_report_and_scope_and_can_skip_session_csrf(admin, data_report):
    report, _ = data_report
    Revision.objects.get(report=report, number=1)
    Publication.objects.create(report=report, revision=report.revisions.get(number=1))
    token = "private-test-token"
    record = ApiToken.objects.create(user=admin, name="Test", digest=hashlib.sha256(token.encode()).hexdigest(),
                scopes=["run"], report_ids=[str(report.pk)], expires_at=timezone.now()+timedelta(hours=1))
    c = Client(enforce_csrf_checks=True)
    response = c.post(f"/api/reports/{report.pk}/execute/", data='{"parameters":{}}', content_type="application/json",
                      HTTP_AUTHORIZATION=f"Bearer {token}")
    assert response.status_code == 200
    assert c.get(f"/api/reports/{report.pk}/", HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 403
    record.enabled = False
    record.save()
    assert c.get(f"/api/reports/{report.pk}/", HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 401


def test_row_policy_cannot_be_overridden_and_masks_block_inference(author_client, data_report):
    report, connection = data_report
    connection.row_policy = [{"column": "customer", "operator": "eq", "value": "Alice"}]
    connection.save()
    response = post(author_client, f"/api/reports/{report.pk}/preview/")
    assert response.status_code == 200 and response.json()["row_count"] == 1
    assert "Bob" not in response.json()["html"]
    connection.masks = {"customer": "full"}
    connection.save()
    result = post(author_client, f"/api/reports/{report.pk}/preview/")
    assert "Alice" not in result.json()["html"]
    report.definition["datasets"][0]["query"]["filters"] = {"field_id": "customer", "operator": "eq", "value": "Alice"}
    report.save()
    assert post(author_client, f"/api/reports/{report.pk}/preview/").status_code == 403


def test_parameter_validation_precedes_data_lookup(author_client, data_report):
    report, _ = data_report
    report.definition["parameters"] = [{"name": "start", "type": "date", "required": True}]
    report.save()
    result = post(author_client, f"/api/reports/{report.pk}/preview/")
    assert result.status_code == 400
    assert Execution.objects.latest("created_at").status == "FAILED"


def test_html_screens_and_manual(author_client, data_report):
    report, _ = data_report
    for url in ["/", "/reports/", "/connections/", "/manual/", f"/reports/{report.pk}/design/", f"/reports/{report.pk}/"]:
        assert author_client.get(url).status_code == 200


def test_disabled_publication_blocks_previous_download(author_client, data_report):
    report, _ = data_report
    post(author_client, f"/api/reports/{report.pk}/publish/")
    result = post(author_client, f"/api/reports/{report.pk}/execute/").json()
    post(author_client, f"/api/reports/{report.pk}/publish/", {"enabled": False})
    response = author_client.get(f"/reports/{report.pk}/export/html/?execution={result['execution_id']}")
    assert response.status_code == 403


def test_viewer_metadata_does_not_expose_draft_or_local_bindings(author_client, data_report):
    report, _ = data_report
    viewer = get_user_model().objects.create_user(username="metadata-viewer")
    group = Group.objects.create(name="Metadata viewers")
    viewer.groups.add(group)
    report.viewer_groups.add(group)
    c = Client()
    c.force_login(viewer)
    result = c.get(f"/api/reports/{report.pk}/").json()
    assert result["definition"] is None and result["bindings"] == []
    assert c.get(f"/reports/{report.pk}/").status_code == 403
    assert post(author_client, f"/api/reports/{report.pk}/publish/").status_code == 200
    definition = copy.deepcopy(report.definition)
    definition["pages"][0]["bands"][0]["elements"][0]["text"] = "Confidential unfinished draft"
    assert post(author_client, f"/api/reports/{report.pk}/", {
        "definition": definition, "expected_revision": 1}, "put").status_code == 200
    detail = c.get(f"/api/reports/{report.pk}/").json()
    listed = c.get("/api/reports/").json()["reports"][0]
    for item in (detail, listed):
        assert "Confidential unfinished draft" not in json.dumps(item)
        assert item["revision"] == 1 and item["bindings"] == []
    publication = Publication.objects.get(report=report)
    for client, url in ((c, f"/reports/{report.pk}/"), (c, f"/published/{publication.pk}/"),
                        (author_client, f"/published/{publication.pk}/")):
        screen = client.get(url)
        assert screen.status_code == 200
        assert "Confidential unfinished draft" not in screen.content.decode()
        assert screen.context["viewer_definition"] == publication.revision.definition
    assert "Confidential unfinished draft" in author_client.get(f"/api/reports/{report.pk}/").content.decode()


def test_invalid_mask_mode_fails_closed(author_client, data_report):
    report, connection = data_report
    connection.masks = {"customer": "FULL"}
    connection.save()
    result = post(author_client, f"/api/reports/{report.pk}/preview/")
    assert result.status_code == 400 and result.json()["code"] == "POLICY_INVALID"
    assert "Alice" not in result.content.decode()


def test_username_row_policy_change_revokes_previous_snapshot(author_client, admin, data_report):
    report, connection = data_report
    admin.username = "Alice"
    admin.save()
    connection.row_policy = [{"column": "customer", "operator": "eq", "value": "$username"}]
    connection.save()
    generated = post(author_client, f"/api/reports/{report.pk}/preview/")
    assert generated.status_code == 200 and "Alice" in generated.json()["html"]
    admin.username = "Bob"
    admin.save()
    downloaded = author_client.get(f"/reports/{report.pk}/export/html/?execution={generated.json()['execution_id']}")
    assert downloaded.status_code == 403
    fresh = post(author_client, f"/api/reports/{report.pk}/preview/")
    assert fresh.status_code == 200 and "Bob" in fresh.json()["html"] and "Alice" not in fresh.json()["html"]


def test_server_policy_fields_are_not_exposed_and_ids_do_not_collide(author_client, data_report):
    report, connection = data_report
    connection.row_policy = [{"column": "customer", "operator": "eq", "value": "Alice"}]
    connection.save()
    dataset = report.definition["datasets"][0]
    # A legitimate authored field can have the same spelling as an internal policy ID.
    dataset["fields"].append({"field_id": "policy_0", "object_id": "sales_rows", "alias": "extra_customer",
                              "label": "extra_customer", "type": "string", "required": True, "nullable": True})
    dataset["query"]["projection"].append("policy_0")
    report.bindings[0]["field_mappings"]["policy_0"] = {"column": "customer", "conversion": "identity"}
    report.save()
    response = post(author_client, f"/api/reports/{report.pk}/preview/")
    assert response.status_code == 200, response.content
    snapshot = Execution.objects.get(pk=response.json()["execution_id"]).datasets_snapshot["sales"]
    assert [field["field_id"] for field in snapshot["fields"]] == ["department", "customer", "amount", "policy_0"]
    assert snapshot["rows"][0]["policy_0"] == "Alice"
    assert "policy_0_" not in snapshot["rows"][0]


def test_revoked_embed_user_returns_denial_instead_of_server_error(author_client, admin, data_report, settings):
    report, _ = data_report
    settings.EMBED_ALLOWED_ORIGINS = ["https://host.example"]
    assert post(author_client, f"/api/reports/{report.pk}/publish/").status_code == 200
    issued = post(author_client, "/api/embed-sessions/", {"report_id": str(report.pk), "origin": "https://host.example"})
    admin.is_active = False
    admin.save()
    result = Client().post("/embed/", {"token": issued.json()["token"]}, HTTP_ORIGIN="https://host.example")
    assert result.status_code == 403


def test_published_service_checks_report_access_even_with_connection_access(author_client, data_report):
    from django.core.exceptions import PermissionDenied
    from reportbuilder.services import execute_report
    report, connection = data_report
    assert post(author_client, f"/api/reports/{report.pk}/publish/").status_code == 200
    outsider = get_user_model().objects.create_user(username="source-only-viewer")
    group = Group.objects.create(name="Source access only")
    outsider.groups.add(group)
    connection.groups.add(group)
    with pytest.raises(PermissionDenied):
        execute_report(report, outsider, published=True)


def test_multiple_row_policies_remain_flat_and_sensitive_responses_are_not_cached(author_client, data_report):
    report, connection = data_report
    connection.row_policy = [{"column": "department", "operator": "eq", "value": "A"} for _ in range(12)]
    connection.save()
    response = post(author_client, f"/api/reports/{report.pk}/preview/")
    assert response.status_code == 200, response.content
    assert response.json()["row_count"] == 2
    assert "private" in response["Cache-Control"] and "no-store" in response["Cache-Control"]
    schema = author_client.get(f"/api/connections/{connection.pk}/schema/")
    assert schema.status_code == 200 and "no-store" in schema["Cache-Control"]


def test_staff_downgrade_revokes_draft_snapshot_even_with_remaining_viewer_access(author_client, admin, data_report):
    report, connection = data_report
    group = Group.objects.create(name="Downgraded administrator viewers")
    admin.groups.add(group)
    report.viewer_groups.add(group)
    connection.groups.add(group)
    assert post(author_client, f"/api/reports/{report.pk}/publish/").status_code == 200
    # Move ownership to a different user while the current staff author can still edit.
    owner = get_user_model().objects.create_user(username="new-report-owner")
    report.owner = owner
    report.save()
    draft = copy.deepcopy(report.definition)
    draft["pages"][0]["bands"][0]["elements"][0]["text"] = "Staff-only unfinished draft"
    assert post(author_client, f"/api/reports/{report.pk}/", {"definition": draft, "expected_revision": 1}, "put").status_code == 200
    preview = post(author_client, f"/api/reports/{report.pk}/preview/")
    assert preview.status_code == 200
    admin.is_staff = False
    admin.save()
    result = author_client.get(f"/reports/{report.pk}/export/html/?execution={preview.json()['execution_id']}")
    assert result.status_code == 403
    # Permissions now allow execution of the publication, but not the old privileged draft.
    published = post(author_client, f"/api/reports/{report.pk}/execute/")
    assert published.status_code == 200 and "Staff-only unfinished draft" not in published.json()["html"]
