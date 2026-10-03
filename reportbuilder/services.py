import base64
import copy
import hashlib
import json

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.models import Q

from .data import DataError, execute_dataset
from .definition import DefinitionError, validate_definition, validate_parameters
from .models import Asset, AuditEvent, Connection, Execution, Report
from .rendering import render_report


def audit(user, action, resource, **details):
    AuditEvent.objects.create(user=user, action=action, resource_id=str(resource), details=details)


def reports_for(user):
    if user.is_staff:
        return Report.objects.all()
    return Report.objects.filter(Q(owner=user) | Q(viewer_groups__in=user.groups.all())).distinct()


def connections_for(user):
    if user.is_staff:
        return Connection.objects.all()
    return Connection.objects.filter(owner=user)


def accessible_connections(user, allow_shared=False):
    if user.is_staff:
        return Connection.objects.all()
    if allow_shared:
        return Connection.objects.filter(Q(owner=user) | Q(groups__in=user.groups.all())).distinct()
    return Connection.objects.filter(owner=user)


def editable(report, user):
    if not (user.is_staff or report.owner_id == user.pk):
        raise PermissionDenied("수정 권한이 없습니다.")


def resolve_connections(user, bindings, allow_shared=False):
    found = {}
    for binding in bindings:
        try:
            connection_id = binding["connection_id"]
            conn = accessible_connections(user, allow_shared=allow_shared).get(pk=connection_id)
        except KeyError:
            raise DataError("MAPPING_REQUIRED", "데이터셋의 데이터 연결 매핑이 없습니다. 보고서의 데이터 연결을 다시 선택하세요.") from None
        except (Connection.DoesNotExist, ValueError):
            raise PermissionDenied(
                "데이터 연결에 접근할 수 없습니다. 연결 소유자 또는 공유 그룹 권한과 보고서의 데이터셋 연결 매핑을 확인하세요."
            ) from None
        found[str(conn.pk)] = conn
    return found


def policy_fingerprint(user, report, bindings, allow_shared=False):
    conns = resolve_connections(user, bindings, allow_shared=allow_shared)
    policy = [{"id": str(c.pk), "objects": c.allowed_objects, "columns": c.allowed_columns,
               "masks": c.masks, "rows": c.row_policy, "groups": list(c.groups.values_list("pk", flat=True))}
              for c in sorted(conns.values(), key=lambda c: str(c.pk))]
    publication = getattr(report, "publication", None)
    policy.append({"report_enabled": report.enabled, "report_owner_id": str(report.owner_id),
                   "published_enabled": publication.enabled if publication else None,
                   "groups": list(report.viewer_groups.values_list("pk", flat=True))})
    # Dynamic row-policy variables must invalidate results when identity changes.
    policy.append({"principal_id": str(user.pk), "principal_username": user.get_username(),
                   "principal_staff": user.is_staff, "principal_superuser": user.is_superuser,
                   "principal_groups": list(user.groups.order_by("pk").values_list("pk", flat=True))})
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def safe_asset(report, user, asset_id):
    try:
        asset = Asset.objects.get(pk=asset_id)
    except (Asset.DoesNotExist, ValueError):
        raise DataError("ASSET_MISSING", "보고서 이미지가 없습니다.") from None
    if asset.owner_id != report.owner_id and asset.project_id != report.project_id:
        raise PermissionDenied("프로젝트 이미지 접근 권한이 없습니다.")
    with asset.file.open("rb") as stream:
        content = stream.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise DataError("ASSET_LIMIT", "이미지 크기 한도를 초과했습니다.")
    return f"data:{asset.mime};base64,{base64.b64encode(content).decode()}"


def run_datasets(report, user, definition, bindings, parameters, allow_shared=False):
    validate_definition(definition)
    parameters = validate_parameters(definition, parameters)
    connection_map = resolve_connections(user, bindings, allow_shared=allow_shared)
    by_dataset = {b["dataset_id"]: b for b in bindings}
    results = {}
    for original_contract in definition.get("datasets", []):
        contract = copy.deepcopy(original_contract)
        ds_id = contract["dataset_id"]
        if ds_id not in by_dataset:
            raise DataError("MAPPING_REQUIRED", "데이터셋을 연결하고 컬럼을 매핑해 주세요.")
        binding = copy.deepcopy(by_dataset[ds_id])
        conn = connection_map[str(binding["connection_id"])]
        if not isinstance(conn.masks, dict) or any(not isinstance(mode, str) or mode not in {"full", "last4"} for mode in conn.masks.values()):
            raise DataError("POLICY_INVALID", "마스킹 정책은 full 또는 last4만 사용할 수 있습니다.")
        if not isinstance(conn.row_policy, list) or len(conn.row_policy) > 100:
            raise DataError("POLICY_INVALID", "행 정책은 최대 100개의 조건 목록이어야 합니다.")
        objects = binding.get("object_mappings", {})
        fields = binding.get("field_mappings", {})
        for obj in contract.get("objects", []):
            mapping = objects.get(obj["object_id"], {})
            object_name = mapping.get("object", "")
            if not object_name or (conn.allowed_objects and object_name not in conn.allowed_objects):
                raise PermissionDenied("허용되지 않은 테이블/범위입니다.")
        for field in contract.get("fields", []):
            mapping = fields.get(field["field_id"], {})
            object_name = objects.get(field.get("object_id"), {}).get("object")
            permitted = conn.allowed_columns.get(object_name)
            if not mapping.get("column") or (permitted is not None and mapping["column"] not in permitted):
                raise PermissionDenied("허용되지 않았거나 매핑하지 않은 컬럼입니다.")
        masked_ids = {key for key, mapping in fields.items() if conn.masks.get(mapping.get("column"))}
        def references_masked(node):
            if isinstance(node, dict):
                return node.get("field_id") in masked_ids or any(references_masked(v) for v in node.values())
            if isinstance(node, list):
                return any(references_masked(v) for v in node)
            return isinstance(node, str) and node in masked_ids
        if masked_ids and references_masked({k: v for k, v in contract.get("query", {}).items() if k != "projection"}):
            raise PermissionDenied("마스킹 필드는 조회조건·정렬·그룹·집계에 사용할 수 없습니다.")
        # Policies are configured only by source administrators and always AND with report filters.
        original_field_ids = {f["field_id"] for f in contract.get("fields", [])}
        reserved_ids = original_field_ids | {a.get("aggregate_id") for a in contract.get("query", {}).get("aggregates", [])}
        policy_field_ids = set()
        policy_filters = []
        for index, rule in enumerate(conn.row_policy):
            if not isinstance(rule, dict) or not isinstance(rule.get("column"), str) or not rule["column"]:
                raise DataError("POLICY_INVALID", "행 정책에는 실제 컬럼 이름이 필요합니다.")
            if not contract.get("objects"):
                raise DataError("POLICY_INVALID", "행 정책 대상 객체가 없습니다.")
            field_id = f"policy_{index}"
            while field_id in reserved_ids:
                field_id += "_"
            reserved_ids.add(field_id)
            policy_field_ids.add(field_id)
            contract["fields"].append({"field_id": field_id, "object_id": contract["objects"][0]["object_id"],
                                      "alias": field_id, "label": field_id, "type": rule.get("type", "string"),
                                      "required": True, "nullable": True})
            binding["field_mappings"][field_id] = {"column": rule["column"], "conversion": "identity"}
            value = rule.get("value")
            if value == "$user_id":
                value = user.pk
            elif value == "$username":
                value = user.get_username()
            policy_filters.append({"field_id": field_id, "operator": rule.get("operator", "eq"), "value": value})
        if policy_filters:
            query = contract.setdefault("query", {})
            original_filter = query.get("filters", {"op": "and", "items": []})
            # Flatten an existing AND instead of increasing depth once per rule.
            original_items = original_filter.get("items", []) if original_filter.get("op") == "and" else [original_filter]
            query["filters"] = {"op": "and", "items": [*original_items, *policy_filters]}
        result = execute_dataset(conn.kind, conn.runtime_config(), contract, binding, parameters,
                                 max_rows=settings.REPORT_MAX_ROWS)
        mask_map = {field_id: conn.masks.get(mapping.get("column")) for field_id, mapping in fields.items()}
        result["fields"] = [field for field in result.get("fields", []) if field["field_id"] not in policy_field_ids]
        for row in result["rows"]:
            for field_id in list(row):
                if field_id in policy_field_ids:
                    row.pop(field_id)
                elif mask_map.get(field_id) and row[field_id] is not None:
                    text = str(row[field_id])
                    row[field_id] = "*" * len(text) if mask_map[field_id] == "full" else "*" * max(0, len(text) - 4) + text[-4:]
        results[ds_id] = result
    return results


def execute_report(report, user, parameters=None, published=False):
    if not user.is_authenticated or not reports_for(user).filter(pk=report.pk).exists():
        raise PermissionDenied("보고서 조회 권한이 없습니다.")
    if not report.enabled:
        raise PermissionDenied("중지된 보고서입니다.")
    parameters = {} if parameters is None else parameters
    if published:
        if not hasattr(report, "publication"):
            raise PermissionDenied("게시하지 않은 보고서입니다.")
        publication = report.publication
        if not publication.enabled:
            raise PermissionDenied("게시가 중지되었습니다.")
        revision = publication.revision
        definition, bindings, number = revision.definition, revision.bindings, revision.number
    else:
        editable(report, user)
        definition, bindings, number = report.definition, report.bindings, report.revision
    if not isinstance(parameters, dict):
        raise DefinitionError("Input parameters must be an object")
    execution = Execution.objects.create(report=report, user=user, revision=number,
                                         parameters={k: "[redacted]" for k in parameters})
    try:
        parameters = validate_parameters(definition, parameters)
        fingerprint = policy_fingerprint(user, report, bindings, allow_shared=published)
        datasets = run_datasets(report, user, definition, bindings, parameters, allow_shared=published)
        rendered = render_report(definition, datasets, parameters,
                                 asset_resolver=lambda asset_id: safe_asset(report, user, asset_id))
        execution.status = "SUCCEEDED"
        execution.definition_snapshot = definition
        execution.bindings_snapshot = bindings
        execution.datasets_snapshot = datasets
        execution.rendered_html = rendered["html"]
        execution.policy_fingerprint = fingerprint
        execution.page_count = rendered["page_count"]
        execution.row_count = sum(len(d["rows"]) for d in datasets.values())
        execution.save()
        audit(user, "execute", report.pk, execution_id=str(execution.pk), rows=execution.row_count)
        return execution, rendered
    except Exception as exc:
        execution.status = "FAILED"
        execution.error_code = getattr(exc, "code", "EXECUTION_FAILED")
        execution.save(update_fields=["status", "error_code"])
        raise
def render_public_report(report, user, definition, bindings, parameters=None):
    """Render a share without creating execution snapshots or owner audit events."""
    if not user.is_authenticated or report.owner_id != user.pk or not user.is_active:
        raise PermissionDenied("공유 보고서 소유자 연결이 유효하지 않습니다.")
    if not isinstance(parameters, dict):
        raise DefinitionError("Input parameters must be an object")
    parameters = validate_parameters(definition, parameters)
    datasets = run_datasets(report, user, definition, bindings, parameters)
    return render_report(definition, datasets, parameters,
                         asset_resolver=lambda asset_id: safe_asset(report, user, asset_id))
