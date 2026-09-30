"""Portable report contract. No executable code or connection details are accepted."""
import copy
import datetime
import json
import math
import re
import uuid
from decimal import Decimal, InvalidOperation


class DefinitionError(ValueError):
    code = "invalid_definition"


ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
TYPES = {"string", "integer", "decimal", "number", "boolean", "date", "datetime", "binary"}
ELEMENTS = {"text", "field", "image", "line", "rectangle", "page_number", "total_pages", "parameter", "generated_at", "page_break"}
BANDS = {"ReportHeader", "PageHeader", "GroupHeader", "Detail", "GroupFooter", "PageFooter", "ReportFooter"}
STYLE = {"font_size_pt", "font_family", "font_weight", "font_style", "text_align", "color", "background_color", "border_color", "border_width_mm", "line_height", "vertical_align"}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _err(path, message):
    raise DefinitionError(f"{path}: {message}")


def _obj(value, keys, required, path):
    if not isinstance(value, dict):
        _err(path, "object required")
    if set(value) - set(keys):
        _err(path, "unsupported properties: " + ", ".join(sorted(set(value) - set(keys))))
    if set(required) - set(value):
        _err(path, "missing properties: " + ", ".join(sorted(set(required) - set(value))))


def _list(value, path, maximum=1000):
    if not isinstance(value, list) or len(value) > maximum:
        _err(path, f"array with at most {maximum} items required")


def _str(value, path, maximum=20000, empty=True):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        _err(path, "invalid string")


def _num(value, path, lo=0, hi=2000):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
        _err(path, f"finite number between {lo} and {hi} required")


def _id(value, path):
    if not isinstance(value, str) or not ID.fullmatch(value):
        _err(path, "invalid logical ID")


def _choice(value, choices, path):
    if value not in choices:
        _err(path, "unsupported value")


def _bool(value, path):
    if not isinstance(value, bool):
        _err(path, "boolean required")


def _unique(value, known, path):
    _id(value, path)
    if value in known:
        _err(path, "duplicate ID")
    known.add(value)


def _validate_definition(definition):
    """Validate strictly; return a detached JSON-compatible definition."""
    try:
        raw = canonical_json(definition)
    except (TypeError, ValueError, RecursionError) as exc:
        raise DefinitionError("Definition must be finite, JSON-compatible data") from exc
    if len(raw.encode()) > 2_000_000:
        _err("definition", "too large")
    d = definition
    _obj(d, {"schema_version", "name", "parameters", "datasets", "pages"}, {"schema_version", "name", "parameters", "datasets", "pages"}, "definition")
    _choice(d["schema_version"], {"1.0.0"}, "schema_version")
    _str(d["name"], "name", 200, False)
    _list(d["parameters"], "parameters", 100)
    parameters = {}
    for p in d["parameters"]:
        _obj(p, {"name", "label", "type", "required", "default", "min", "max", "choices", "max_length"}, {"name", "type"}, "parameter")
        _id(p["name"], "parameter.name")
        if p["name"] in parameters:
            _err("parameters", "duplicate name")
        _choice(p["type"], TYPES - {"binary"}, "parameter.type")
        if "label" in p:
            _str(p["label"], "parameter.label", 200)
        if "required" in p:
            _bool(p["required"], "parameter.required")
        if "default" in p and isinstance(p["default"], (dict, list)):
            _err("parameter.default", "scalar required")
        for constraint in ("min", "max"):
            if constraint in p:
                if p["type"] not in {"integer", "decimal", "number"}:
                    _err("parameter." + constraint, "numeric constraints require numeric type")
                _num(p[constraint], "parameter." + constraint, -1e15, 1e15)
        if "min" in p and "max" in p and p["min"] > p["max"]:
            _err("parameter", "minimum exceeds maximum")
        if "max_length" in p:
            if p["type"] != "string" or isinstance(p["max_length"], bool) or not isinstance(p["max_length"], int) or not 1 <= p["max_length"] <= 20000:
                _err("parameter.max_length", "string length between 1 and 20000 required")
        if "choices" in p:
            _list(p["choices"], "parameter.choices", 100)
            if not p["choices"] or any(isinstance(v, (dict, list)) for v in p["choices"]):
                _err("parameter.choices", "nonempty scalar choices required")
        parameters[p["name"]] = p
    _list(d["datasets"], "datasets", 100)
    datasets, dataset_ids = {}, set()
    for ds in d["datasets"]:
        _obj(ds, {"dataset_id", "alias", "label", "cardinality", "objects", "fields", "query"}, {"dataset_id", "alias", "cardinality", "objects", "fields", "query"}, "dataset")
        _unique(ds["dataset_id"], dataset_ids, "dataset.dataset_id")
        _id(ds["alias"], "dataset.alias")
        if "label" in ds:
            _str(ds["label"], "dataset.label", 200)
        _choice(ds["cardinality"], {"one", "many"}, "dataset.cardinality")
        _list(ds["objects"], "objects", 20)
        objects = set()
        for o in ds["objects"]:
            _obj(o, {"object_id", "alias"}, {"object_id", "alias"}, "object")
            _unique(o["object_id"], objects, "object.object_id")
            _id(o["alias"], "object.alias")
        if len(objects) != 1:
            _err("objects", "this release supports exactly one object per dataset; joins are unsupported")
        _list(ds["fields"], "fields", 500)
        fields = {}
        for f in ds["fields"]:
            _obj(f, {"field_id", "object_id", "alias", "label", "type", "required", "nullable"}, {"field_id", "object_id", "alias", "type"}, "field")
            _id(f["field_id"], "field.field_id")
            if f["field_id"] in fields:
                _err("fields", "duplicate field ID")
            if f["object_id"] not in objects:
                _err("field.object_id", "unknown object")
            _id(f["alias"], "field.alias")
            _choice(f["type"], TYPES, "field.type")
            if "label" in f:
                _str(f["label"], "field.label", 200)
            for flag in ("required", "nullable"):
                if flag in f:
                    _bool(f[flag], "field." + flag)
            fields[f["field_id"]] = f
        q = ds["query"]
        _obj(q, {"projection", "filters", "sorts", "groups", "aggregates"}, {"projection", "filters", "sorts", "groups", "aggregates"}, "query")
        _list(q["aggregates"], "aggregates", 50)
        derived = {}
        for a in q["aggregates"]:
            _obj(a, {"aggregate_id", "field_id", "function", "label"}, {"aggregate_id", "function"}, "aggregate")
            _id(a["aggregate_id"], "aggregate.aggregate_id")
            if a["aggregate_id"] in fields or a["aggregate_id"] in derived:
                _err("aggregate.aggregate_id", "duplicate output ID")
            _choice(a["function"], {"count", "sum", "min", "max", "avg", "count_distinct"}, "aggregate.function")
            if a.get("field_id") not in fields and not (a["function"] == "count" and a.get("field_id") is None):
                _err("aggregate.field_id", "unknown field")
            if "label" in a:
                _str(a["label"], "aggregate.label", 200)
            derived[a["aggregate_id"]] = {"type": "number"}
        available = {**fields, **derived}
        _list(q["projection"], "query.projection", 500)
        for f in q["projection"]:
            if f not in available:
                _err("query.projection", "unknown field")
        if len(set(q["projection"])) != len(q["projection"]):
            _err("query.projection", "duplicate field")
        def filter_node(node, depth=0):
            if depth > 10:
                _err("filters", "nesting exceeds limit")
            if isinstance(node, dict) and "op" in node:
                _obj(node, {"op", "items"}, {"op", "items"}, "filters")
                _choice(node["op"], {"and", "or"}, "filters.op")
                _list(node["items"], "filters.items", 100)
                for n in node["items"]:
                    filter_node(n, depth + 1)
            else:
                _obj(node, {"field_id", "operator", "value", "parameter"}, {"field_id", "operator"}, "filter")
                if node["field_id"] not in fields:
                    _err("filter.field_id", "unknown field")
                _choice(node["operator"], {"eq", "ne", "gt", "gte", "lt", "lte", "contains", "starts_with", "ends_with", "in", "not_in", "between", "is_null", "is_not_null"}, "filter.operator")
                if "parameter" in node and node["parameter"] not in parameters:
                    _err("filter.parameter", "unknown parameter")
                if "parameter" in node and node["operator"] in {"in", "not_in", "between"}:
                    _err("filter.parameter", "list parameters are unsupported; use literal list filter values")
                if "parameter" in node and "value" in node:
                    _err("filter", "choose parameter or value")
                if node["operator"] not in {"is_null", "is_not_null"} and "parameter" not in node and "value" not in node:
                    _err("filter", "value or parameter required")
                if "value" in node and isinstance(node["value"], dict):
                    _err("filter.value", "object values unsupported")
                if "value" in node and isinstance(node["value"], list):
                    if node["operator"] not in {"in", "not_in", "between"} or len(node["value"]) > 1000 or any(isinstance(v, (dict, list)) for v in node["value"]) or (node["operator"] == "between" and len(node["value"]) != 2):
                        _err("filter.value", "invalid scalar list")
                elif "value" in node and node["operator"] in {"in", "not_in", "between"}:
                    _err("filter.value", "array required")
        filter_node(q["filters"])
        _list(q["sorts"], "sorts", 20)
        for s in q["sorts"]:
            _obj(s, {"field_id", "direction", "nulls"}, {"field_id", "direction"}, "sort")
            if s["field_id"] not in available:
                _err("sort.field_id", "unknown field")
            _choice(s["direction"], {"asc", "desc"}, "sort.direction")
            if "nulls" in s:
                _choice(s["nulls"], {"first", "last"}, "sort.nulls")
        _list(q["groups"], "groups", 1)
        for g in q["groups"]:
            if isinstance(g, str):
                field_id = g
            else:
                _obj(g, {"field_id"}, {"field_id"}, "group")
                field_id = g["field_id"]
            if field_id not in fields:
                _err("group", "unknown field")
        group_ids = [g if isinstance(g, str) else g["field_id"] for g in q["groups"]]
        outputs = ({f: fields[f] for f in group_ids} | derived) if group_ids or derived else fields
        if any(f not in outputs for f in q["projection"]) or any(s["field_id"] not in outputs for s in q["sorts"]):
            _err("query", "projection and sorts must reference aggregate/group output fields")
        datasets[ds["dataset_id"]] = {f: outputs[f] for f in q["projection"]} if q["projection"] else outputs
    _list(d["pages"], "pages", 100)
    if not d["pages"]:
        _err("pages", "at least one page required")
    page_ids, element_ids, band_ids = set(), set(), set()
    def elements(items, width, height, page_ds=None, band_type=None):
        _list(items, "elements", 500)
        for e in items:
            _obj(e, {"element_id", "type", "geometry", "binding", "style", "overflow", "text", "asset_id", "parameter_name", "fit", "page_break_before"}, {"element_id", "type", "geometry"}, "element")
            _unique(e["element_id"], element_ids, "element.element_id")
            _choice(e["type"], ELEMENTS, "element.type")
            g = e["geometry"]
            _obj(g, {"x_mm", "y_mm", "width_mm", "height_mm"}, {"x_mm", "y_mm", "width_mm", "height_mm"}, "geometry")
            for key in g:
                _num(g[key], "geometry." + key, 0, 2000)
            if g["width_mm"] <= 0 or (g["height_mm"] <= 0 and e["type"] != "page_break"):
                _err("geometry", "positive dimensions required")
            if g["x_mm"] + g["width_mm"] > width + .001 or g["y_mm"] + g["height_mm"] > height + .001:
                _err("geometry", "element exceeds parent bounds")
            overflow = e.get("overflow", "fixed_clip")
            _choice(overflow, {"fixed_clip", "grow"}, "element.overflow")
            if overflow == "grow" and e["type"] not in {"text", "field", "parameter"}:
                _err("element.overflow", "grow supported only for text, field and parameter")
            if "page_break_before" in e:
                _bool(e["page_break_before"], "element.page_break_before")
                _err("element.page_break_before", "use a page_break element or band page_break_before")
            style = e.get("style", {})
            _obj(style, STYLE, set(), "style")
            for key in ("color", "background_color", "border_color"):
                if key in style and (not isinstance(style[key], str) or not re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", style[key])):
                    _err("style." + key, "hex color required")
            for key, bounds in {"font_size_pt": (4, 144), "border_width_mm": (0, 10), "line_height": (1, 3)}.items():
                if key in style:
                    _num(style[key], "style." + key, *bounds)
            for key, choices in {"font_family": {"sans-serif", "serif", "monospace"}, "font_weight": {"normal", "bold"}, "font_style": {"normal", "italic"}, "text_align": {"left", "center", "right"}, "vertical_align": {"top", "middle", "bottom"}}.items():
                if key in style:
                    _choice(style[key], choices, "style." + key)
            if e["type"] == "text":
                _str(e.get("text"), "element.text")
            elif "text" in e:
                _err("element.text", "text property belongs to text elements")
            if e["type"] == "field":
                b = e.get("binding")
                _obj(b, {"dataset_id", "field_id", "scope", "aggregate", "aggregate_scope"}, {"dataset_id", "field_id", "scope"}, "binding")
                if b["dataset_id"] not in datasets or b["field_id"] not in datasets[b["dataset_id"]]:
                    _err("binding", "unknown dataset or field")
                _choice(b["scope"], {"row", "first", "single", "aggregate", "group"}, "binding.scope")
                if b["scope"] == "row" and (page_ds != b["dataset_id"] or band_type not in {"Detail", "GroupHeader", "GroupFooter"}):
                    _err("binding.scope", "row scope requires a matching flow data band")
                if b["scope"] == "group" and (page_ds != b["dataset_id"] or band_type not in {"GroupHeader", "GroupFooter"}):
                    _err("binding.scope", "group scope requires a matching group band")
                if b["scope"] == "aggregate":
                    _choice(b.get("aggregate"), {"count", "sum", "min", "max", "avg"}, "binding.aggregate")
                    _choice(b.get("aggregate_scope", "report"), {"report", "group"}, "binding.aggregate_scope")
                    if b.get("aggregate_scope") == "group" and (page_ds != b["dataset_id"] or band_type not in {"GroupHeader", "GroupFooter"}):
                        _err("binding.aggregate_scope", "group aggregate requires a matching group band")
                elif "aggregate" in b or "aggregate_scope" in b:
                    _err("binding.aggregate", "requires aggregate scope")
            elif "binding" in e:
                _err("binding", "only field elements may bind data")
            if e["type"] == "image":
                try:
                    if str(uuid.UUID(e.get("asset_id", ""))) != e["asset_id"]:
                        raise ValueError
                except (ValueError, TypeError, AttributeError):
                    _err("element.asset_id", "UUID asset ID required")
                _choice(e.get("fit", "contain"), {"contain", "cover", "fill"}, "image.fit")
            elif "asset_id" in e or "fit" in e:
                _err("element", "asset_id and fit belong to image elements")
            if e["type"] == "parameter":
                if e.get("parameter_name") not in parameters:
                    _err("element.parameter_name", "unknown parameter")
            elif "parameter_name" in e:
                _err("element.parameter_name", "only parameter elements accept this property")
            if e["type"] == "page_break" and band_type not in {"ReportHeader", "Detail", "ReportFooter", "GroupHeader", "GroupFooter"}:
                _err("element.page_break", "page breaks require a flow content band")
    for p in d["pages"]:
        _obj(p, {"page_id", "kind", "width_mm", "height_mm", "margins", "dataset_id", "elements", "bands"}, {"page_id", "kind", "width_mm", "height_mm", "margins", "elements", "bands"}, "page")
        _unique(p["page_id"], page_ids, "page.page_id")
        _choice(p["kind"], {"fixed", "flow"}, "page.kind")
        for key in ("width_mm", "height_mm"):
            _num(p[key], "page." + key, 50, 1200)
        m = p["margins"]
        _obj(m, {"top", "right", "bottom", "left"}, {"top", "right", "bottom", "left"}, "margins")
        for k in m:
            _num(m[k], "margins." + k, 0, 200)
        w, h = p["width_mm"] - m["left"] - m["right"], p["height_mm"] - m["top"] - m["bottom"]
        if min(w, h) <= 0:
            _err("margins", "printable area must be positive")
        if p["kind"] == "fixed":
            if p["bands"] or "dataset_id" in p:
                _err("page", "fixed pages do not accept bands or dataset_id")
            elements(p["elements"], w, h)
        else:
            if p.get("dataset_id") not in datasets:
                _err("page.dataset_id", "unknown dataset")
            if p["elements"]:
                _err("page.elements", "flow elements must belong to bands")
            _list(p["bands"], "bands", 20)
            counts = {}
            for band in p["bands"]:
                _obj(band, {"band_id", "type", "height_mm", "elements", "group_field_id", "page_break_before"}, {"band_id", "type", "height_mm", "elements"}, "band")
                _unique(band["band_id"], band_ids, "band.band_id")
                _choice(band["type"], BANDS, "band.type")
                counts[band["type"]] = counts.get(band["type"], 0) + 1
                if counts[band["type"]] > 1:
                    _err("bands", "at most one band of each type is supported")
                _num(band["height_mm"], "band.height_mm", .1, h)
                if "page_break_before" in band:
                    _bool(band["page_break_before"], "band.page_break_before")
                    if band["type"] in {"PageHeader", "PageFooter"}:
                        _err("band", "page headers/footers cannot force breaks")
                if band["type"] in {"GroupHeader", "GroupFooter"}:
                    if band.get("group_field_id") not in datasets[p["dataset_id"]]:
                        _err("band.group_field_id", "group band requires known field")
                elif "group_field_id" in band:
                    _err("band.group_field_id", "only group bands accept this property")
                elements(band["elements"], w, band["height_mm"], p["dataset_id"], band["type"])
            if "Detail" not in counts:
                _err("bands", "flow page requires Detail band")
            group_fields = {b["group_field_id"] for b in p["bands"] if b["type"] in {"GroupHeader", "GroupFooter"}}
            if len(group_fields) > 1:
                _err("bands", "nested groups unsupported")
    for p in d["parameters"]:
        if "default" in p:
            _parameter_value(p, p["default"])
        if "choices" in p:
            for choice in p["choices"]:
                _parameter_value({k: v for k, v in p.items() if k not in {"choices", "required"}}, choice)
    return copy.deepcopy(definition)


def validate_definition(definition):
    try:
        return _validate_definition(definition)
    except DefinitionError:
        raise
    except (TypeError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
        raise DefinitionError("Malformed definition value or reference") from exc


def _parameter_value(spec, value):
    path = "parameter." + spec["name"]
    if value is None or value == "" and spec["type"] != "string":
        if spec.get("required"):
            _err(path, "required parameter is missing")
        return None
    kind = spec["type"]
    try:
        if kind == "string":
            _str(value, path, spec.get("max_length", 20000))
            if spec.get("required") and not value.strip():
                _err(path, "nonempty value required")
            typed = value
        elif kind == "integer":
            if isinstance(value, bool) or not (isinstance(value, int) or isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value)):
                _err(path, "integer required")
            typed = int(value)
            if abs(typed) > 1e15:
                _err(path, "integer magnitude exceeds limit")
        elif kind in {"number", "decimal"}:
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                _err(path, "number required")
            numeric = Decimal(str(value))
            if not numeric.is_finite() or abs(numeric) > Decimal("1e15"):
                _err(path, "finite bounded number required")
            typed = str(numeric.normalize()) if kind == "decimal" else float(numeric)
        elif kind == "boolean":
            if isinstance(value, bool):
                typed = value
            elif value in ("true", "false"):
                typed = value == "true"
            else:
                _err(path, "boolean or true/false string required")
        elif kind == "date":
            _str(value, path, 10, False)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                _err(path, "ISO date required")
            typed = datetime.date.fromisoformat(value).isoformat()
        elif kind == "datetime":
            _str(value, path, 40, False)
            if "T" not in value:
                _err(path, "ISO datetime required")
            typed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        else:
            _err(path, "unsupported parameter type")
    except (ValueError, OverflowError, InvalidOperation) as exc:
        if isinstance(exc, DefinitionError):
            raise
        _err(path, "invalid typed value")
    comparable = Decimal(typed) if kind == "decimal" else typed
    minimum = Decimal(str(spec["min"])) if kind == "decimal" and "min" in spec else spec.get("min")
    maximum = Decimal(str(spec["max"])) if kind == "decimal" and "max" in spec else spec.get("max")
    if "min" in spec and comparable < minimum or "max" in spec and comparable > maximum:
        _err(path, "value outside allowed range")
    if "choices" in spec:
        choices = [_parameter_value({k: v for k, v in spec.items() if k not in {"choices", "required"}}, v) for v in spec["choices"]]
        if typed not in choices:
            _err(path, "value outside allowed choices")
    return typed


def validate_parameters(definition, parameters=None):
    d = validate_definition(definition)
    if parameters is None:
        parameters = {}
    if not isinstance(parameters, dict) or set(parameters) - {p["name"] for p in d["parameters"]}:
        raise DefinitionError("Unknown or malformed input parameters")
    return {p["name"]: _parameter_value(p, parameters.get(p["name"], p.get("default"))) for p in d["parameters"]}


def default_definition(name="새 보고서"):
    return {"schema_version": "1.0.0", "name": name, "parameters": [], "datasets": [], "pages": [{"page_id": "page1", "kind": "fixed", "width_mm": 210, "height_mm": 297, "margins": {"top": 15, "right": 15, "bottom": 15, "left": 15}, "elements": [{"element_id": "title", "type": "text", "geometry": {"x_mm": 0, "y_mm": 0, "width_mm": 180, "height_mm": 15}, "text": name, "style": {"font_size_pt": 20, "font_weight": "bold"}, "overflow": "fixed_clip"}], "bands": []}]}
