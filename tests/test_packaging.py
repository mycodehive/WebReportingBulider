import base64
import hashlib
import io
import json
import uuid
import zipfile
import pytest
from PIL import Image
from reportbuilder.definition import DefinitionError, default_definition
from reportbuilder.packaging import PackageError, export_project, import_project
from reportbuilder.rendering import RenderError, render_report


def raster():
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(stream, format="PNG")
    return stream.getvalue()


def image_definition(asset_id):
    d = default_definition()
    d["pages"][0]["elements"] = [{"element_id": "image", "type": "image", "asset_id": asset_id, "geometry": {"x_mm": 0, "y_mm": 0, "width_mm": 30, "height_mm": 30}}]
    return d


def rewrite(package, change, rehash=False):
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        entries = {i.filename: archive.read(i) for i in archive.infolist()}
    change(entries)
    if rehash:
        manifest = {"format_version": "1.0.0", "files": {p: {"sha256": hashlib.sha256(v).hexdigest(), "size": len(v)} for p, v in entries.items() if p != "manifest.json"}}
        entries["manifest.json"] = json.dumps(manifest).encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for path, value in entries.items():
            archive.writestr(path, value)
    return stream.getvalue()


def test_portable_roundtrip_includes_assets_but_no_local_bindings():
    asset_id = str(uuid.uuid4())
    assets = {asset_id: {"content": raster(), "filename": "sample.png", "mime": "image/png"}}
    d = image_definition(asset_id)
    package = export_project("Project", [{"name": "Report", "definition": d}], assets)
    result = import_project(package)
    assert result["reports"][0]["definition"] == d
    assert result["assets"] == assets
    assert result["name"] == "Project"
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        assert set(archive.namelist()) == {"manifest.json", "project.json", "reports/report_1.json", f"assets/{asset_id}.png"}
        assert b"connection_id" not in archive.read("reports/report_1.json")
    rendered = render_report(d, {}, asset_resolver=lambda aid: "data:image/png;base64," + base64.b64encode(result["assets"][aid]["content"]).decode())
    assert "data:image/png;base64," in rendered["html"]
    assert export_project("Project", [{"name": "Report", "definition": d}], assets) == package


def test_manifest_detects_tampering():
    package = export_project("Project", [{"name": "Report", "definition": default_definition()}])
    bad = rewrite(package, lambda files: files.update({"reports/report_1.json": files["reports/report_1.json"] + b" "}))
    with pytest.raises(PackageError, match="hash or size"):
        import_project(bad)


@pytest.mark.parametrize("path", ["../escape.txt", "/etc/passwd", "reports/../../evil.json", "C:\\evil.txt", "reports//evil.json"])
def test_rejects_unsafe_paths_even_with_recomputed_manifest(path):
    package = export_project("Project", [{"name": "Report", "definition": default_definition()}])
    bad = rewrite(package, lambda files: files.update({path: b"bad"}), rehash=True)
    with pytest.raises(PackageError):
        import_project(bad)


def test_rejects_undeclared_script_and_definition_credentials():
    package = export_project("Project", [{"name": "Report", "definition": default_definition()}])
    bad = rewrite(package, lambda files: files.update({"startup.py": b"import os"}), rehash=True)
    with pytest.raises(PackageError, match="Undeclared"):
        import_project(bad)
    def credentials(files):
        d = json.loads(files["reports/report_1.json"])
        d["connection_id"] = "production-password"
        files["reports/report_1.json"] = json.dumps(d).encode()
    with pytest.raises(DefinitionError):
        import_project(rewrite(package, credentials, rehash=True))


def test_rejects_duplicate_members_symlinks_and_zip_bombs():
    package = export_project("Project", [{"name": "Report", "definition": default_definition()}])
    stream = io.BytesIO(package)
    with zipfile.ZipFile(stream, "a") as archive:
        with pytest.warns(UserWarning):
            archive.writestr("manifest.json", b"{}")
    with pytest.raises(PackageError, match="Duplicate"):
        import_project(stream.getvalue())
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("manifest.json", b"{}")
        info = zipfile.ZipInfo("project.json")
        info.external_attr = 0o120777 << 16
        archive.writestr(info, b"/etc/passwd")
    with pytest.raises(PackageError, match="links"):
        import_project(stream.getvalue())
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", b"{}")
        archive.writestr("project.json", b"x" * 1_000_000)
    with pytest.raises(PackageError, match="expansion"):
        import_project(stream.getvalue())


def test_rejects_missing_assets_svg_and_external_image_urls():
    asset_id = str(uuid.uuid4())
    d = image_definition(asset_id)
    with pytest.raises(PackageError, match="referenced"):
        export_project("P", [{"name": "R", "definition": d}])
    with pytest.raises(PackageError):
        export_project("P", [{"name": "R", "definition": d}], {asset_id: {"content": b"<svg onload='alert(1)'/>", "filename": "bad.svg", "mime": "image/svg+xml"}})
    with pytest.raises(RenderError, match="embedded"):
        render_report(d, {}, asset_resolver=lambda _: "https://example.com/tracking.png")
    with pytest.raises(PackageError):
        render_report(d, {}, asset_resolver=lambda _: "data:image/png;base64," + base64.b64encode(b"fake").decode())


def test_rejects_json_duplicate_keys():
    package = export_project("Project", [{"name": "Report", "definition": default_definition()}])
    bad = rewrite(package, lambda files: files.update({"project.json": b'{"name":"a","name":"b"}'}), rehash=True)
    with pytest.raises(PackageError, match="Duplicate JSON"):
        import_project(bad)


@pytest.mark.django_db
def test_upload_rejects_reencoded_png_over_asset_limit_before_saving(client, settings, tmp_path, monkeypatch):
    import random
    from django.contrib.auth import get_user_model
    from django.core.files.base import ContentFile
    from reportbuilder import packaging
    from reportbuilder.models import Asset
    settings.MEDIA_ROOT = tmp_path
    user = get_user_model().objects.create_user(username="image_author")
    client.force_login(user)
    original = io.BytesIO()
    image = Image.frombytes("RGB", (64, 64), random.Random(1).randbytes(64 * 64 * 3))
    image.save(original, format="JPEG", quality=50)
    assert len(original.getvalue()) < 5000
    monkeypatch.setattr(packaging, "MAX_ASSET", 5000)
    response = client.post("/api/assets/", {"file": ContentFile(original.getvalue(), name="noise.jpg")})
    assert response.status_code == 400
    assert Asset.objects.count() == 0
    assert not list(tmp_path.rglob("*.png"))


@pytest.mark.django_db
def test_invalid_parameter_container_rejected_before_snapshot_creation(client):
    from django.contrib.auth import get_user_model
    from reportbuilder.models import Execution
    user = get_user_model().objects.create_user(username="param_author")
    client.force_login(user)
    report = client.post("/api/reports/", data=json.dumps({"name": "Parameter validation"}), content_type="application/json").json()
    for invalid in [[], False, "invalid"]:
        response = client.post(f"/api/reports/{report['id']}/preview/", data=json.dumps({"parameters": invalid}), content_type="application/json")
        assert response.status_code == 400
    assert Execution.objects.count() == 0
