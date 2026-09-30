"""Safe, versioned .wrpx interchange: definitions and raster assets, never credentials."""
import hashlib
import io
import json
import re
import uuid
import zipfile
from pathlib import PurePosixPath
from .definition import DefinitionError, canonical_json, validate_definition

MAX_PACKAGE = 30_000_000
MAX_EXPANDED = 60_000_000
MAX_ASSET = 10_000_000
MIME_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}


class PackageError(DefinitionError):
    code = "invalid_project"


def validate_asset(content, mime):
    if not isinstance(content, bytes) or not content or len(content) > MAX_ASSET or mime not in MIME_EXT:
        raise PackageError("Unsupported or oversized asset; PNG, JPEG, GIF and WebP are accepted")
    signatures = {
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/gif": content.startswith((b"GIF87a", b"GIF89a")),
        "image/webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
    }
    if not signatures[mime]:
        raise PackageError("Asset MIME type does not match raster file signature")
    try:
        from PIL import Image
        with Image.open(io.BytesIO(content)) as image:
            if image.width * image.height > 40_000_000:
                raise PackageError("Image pixel limit exceeded")
            image.verify()
    except ImportError as exc:
        raise PackageError("Raster verification requires Pillow") from exc
    except PackageError:
        raise
    except Exception as exc:
        raise PackageError("Invalid raster image") from exc
    return content


def _name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise PackageError("A nonempty project/report name of at most 200 characters is required")
    return value


def _asset_id(value):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise PackageError("Asset ID must be a canonical UUID") from exc
    return value


def _referenced_assets(reports):
    result = set()
    for report in reports:
        for page in report["definition"]["pages"]:
            elements = list(page["elements"])
            for band in page["bands"]:
                elements.extend(band["elements"])
            result.update(e["asset_id"] for e in elements if e["type"] == "image")
    return result


def _export_project(name, reports, assets=None):
    _name(name)
    if not isinstance(reports, list) or not 1 <= len(reports) <= 100:
        raise PackageError("A project must contain between 1 and 100 reports")
    assets = assets or {}
    if not isinstance(assets, dict) or len(assets) > 100:
        raise PackageError("Invalid asset collection")
    files, report_entries, safe_reports = {}, [], []
    for index, report in enumerate(reports, 1):
        if not isinstance(report, dict) or set(report) != {"name", "definition"}:
            raise PackageError("Reports contain only name and definition; bindings, credentials and data are excluded")
        definition = validate_definition(report["definition"])
        filename = f"reports/report_{index}.json"
        files[filename] = canonical_json(definition).encode("utf-8")
        report_entries.append({"name": _name(report["name"]), "path": filename})
        safe_reports.append({"name": report["name"], "definition": definition})
    referenced = _referenced_assets(safe_reports)
    if referenced != set(assets):
        raise PackageError("All referenced assets, and only referenced assets, must be included")
    asset_entries = []
    for asset_id, asset in sorted(assets.items()):
        _asset_id(asset_id)
        if not isinstance(asset, dict) or set(asset) != {"content", "filename", "mime"}:
            raise PackageError("Assets require content, filename and mime")
        filename = asset["filename"]
        if not isinstance(filename, str) or not filename or len(filename) > 200 or "/" in filename or "\\" in filename or any(ord(c) < 32 for c in filename):
            raise PackageError("Asset filename must be a safe basename")
        content = validate_asset(asset["content"], asset["mime"])
        path = f"assets/{asset_id}.{MIME_EXT[asset['mime']]}"
        files[path] = content
        asset_entries.append({"asset_id": asset_id, "path": path, "filename": filename, "mime": asset["mime"]})
    project = {"format": "wrpx", "format_version": "1.0.0", "name": name, "reports": report_entries, "assets": asset_entries}
    files["project.json"] = canonical_json(project).encode("utf-8")
    manifest = {"format_version": "1.0.0", "files": {path: {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)} for path, content in sorted(files.items())}}
    files["manifest.json"] = canonical_json(manifest).encode("utf-8")
    if sum(map(len, files.values())) > MAX_EXPANDED:
        raise PackageError("Expanded project exceeds size limit")
    output = io.BytesIO()
    # Stored members avoid compressed ZIP bombs and unnecessary recompression of images.
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for path, content in sorted(files.items()):
            info = zipfile.ZipInfo(path, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    package = output.getvalue()
    if len(package) > MAX_PACKAGE:
        raise PackageError("Project archive exceeds size limit")
    return package


def _json(content, name):
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PackageError(f"Duplicate JSON key in {name}")
            result[key] = value
        return result
    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=no_duplicates, parse_constant=lambda value: (_ for _ in ()).throw(PackageError("Nonfinite JSON numbers are forbidden")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PackageError(f"Invalid JSON in {name}") from exc


def _exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise PackageError(f"Invalid {label} properties")


def _import_project(package):
    if not isinstance(package, bytes) or not package or len(package) > MAX_PACKAGE:
        raise PackageError("Invalid or oversized project archive")
    try:
        archive = zipfile.ZipFile(io.BytesIO(package))
    except zipfile.BadZipFile as exc:
        raise PackageError("Invalid ZIP archive") from exc
    with archive:
        entries = archive.infolist()
        if not 2 <= len(entries) <= 202:
            raise PackageError("Invalid archive member count")
        names, expanded = set(), 0
        for entry in entries:
            path = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            if entry.filename in names or path.is_absolute() or ".." in path.parts or "\\" in entry.filename or any(ord(c) < 32 for c in entry.filename) or str(path) != entry.filename or entry.is_dir():
                raise PackageError("Duplicate or unsafe archive path")
            if (mode & 0o170000) not in {0, 0o100000}:
                raise PackageError("Archive links and nonregular members are forbidden")
            if entry.flag_bits & 1 or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise PackageError("Encrypted or unsupported archive compression")
            expanded += entry.file_size
            if entry.file_size > MAX_ASSET or expanded > MAX_EXPANDED or entry.file_size > max(1024, entry.compress_size) * 100:
                raise PackageError("Archive expansion limit exceeded")
            names.add(entry.filename)
        if not {"manifest.json", "project.json"} <= names:
            raise PackageError("Manifest and project metadata are required")
        try:
            files = {entry.filename: archive.read(entry) for entry in entries}
        except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
            raise PackageError("Archive checksum or content validation failed") from exc
    manifest = _json(files["manifest.json"], "manifest")
    _exact(manifest, {"format_version", "files"}, "manifest")
    if manifest["format_version"] != "1.0.0" or not isinstance(manifest["files"], dict) or set(manifest["files"]) != names - {"manifest.json"}:
        raise PackageError("Manifest version or member inventory mismatch")
    for path, declared in manifest["files"].items():
        _exact(declared, {"sha256", "size"}, "manifest member")
        if isinstance(declared["size"], bool) or not isinstance(declared["size"], int) or declared["size"] != len(files[path]) or not isinstance(declared["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", declared["sha256"]) or hashlib.sha256(files[path]).hexdigest() != declared["sha256"]:
            raise PackageError("Manifest hash or size mismatch")
    project = _json(files["project.json"], "project")
    _exact(project, {"format", "format_version", "name", "reports", "assets"}, "project")
    if project["format"] != "wrpx" or project["format_version"] != "1.0.0":
        raise PackageError("Unsupported project format/version")
    _name(project["name"])
    if not isinstance(project["reports"], list) or not 1 <= len(project["reports"]) <= 100 or not isinstance(project["assets"], list) or len(project["assets"]) > 100:
        raise PackageError("Invalid reports/assets inventory")
    reports, assets, expected = [], {}, {"manifest.json", "project.json"}
    for report in project["reports"]:
        _exact(report, {"name", "path"}, "report entry")
        _name(report["name"])
        path = report["path"]
        if not isinstance(path, str) or not re.fullmatch(r"reports/report_[1-9][0-9]*\.json", path) or path not in files or path in expected:
            raise PackageError("Invalid or duplicate report path")
        expected.add(path)
        reports.append({"name": report["name"], "definition": validate_definition(_json(files[path], path))})
    for asset in project["assets"]:
        _exact(asset, {"asset_id", "path", "filename", "mime"}, "asset entry")
        asset_id = _asset_id(asset["asset_id"])
        path, filename, mime = asset["path"], asset["filename"], asset["mime"]
        if mime not in MIME_EXT or path != f"assets/{asset_id}.{MIME_EXT[mime]}" or path not in files or asset_id in assets or path in expected:
            raise PackageError("Invalid or duplicate asset path")
        if not isinstance(filename, str) or not filename or len(filename) > 200 or "/" in filename or "\\" in filename or any(ord(c) < 32 for c in filename):
            raise PackageError("Unsafe original asset filename")
        validate_asset(files[path], mime)
        assets[asset_id] = {"content": files[path], "filename": filename, "mime": mime}
        expected.add(path)
    if expected != names:
        raise PackageError("Undeclared archive members are forbidden")
    if _referenced_assets(reports) != set(assets):
        raise PackageError("Missing or unused project assets")
    return {"name": project["name"], "reports": reports, "assets": assets}


def export_project(name, reports, assets=None):
    try:
        return _export_project(name, reports, assets)
    except DefinitionError:
        raise
    except (TypeError, KeyError, AttributeError, ValueError, OverflowError, RecursionError) as exc:
        raise PackageError("Malformed project metadata") from exc


def import_project(package):
    try:
        return _import_project(package)
    except DefinitionError:
        raise
    except (TypeError, KeyError, AttributeError, ValueError, OverflowError, RecursionError) as exc:
        raise PackageError("Malformed project metadata") from exc
