import copy
import pytest
from reportbuilder.definition import DefinitionError, canonical_json, default_definition, validate_definition, validate_parameters
from reportbuilder.rendering import RenderError, pdf_bytes, render_report


def field(element_id="value", scope="row", field_id="f1"):
    return {"element_id": element_id, "type": "field", "geometry": {"x_mm": 0, "y_mm": 0, "width_mm": 60, "height_mm": 6}, "binding": {"dataset_id": "ds1", "field_id": field_id, "scope": scope}, "overflow": "fixed_clip"}


def flow_definition():
    d = default_definition("Flow")
    d["datasets"] = [{"dataset_id": "ds1", "alias": "data", "cardinality": "many", "objects": [{"object_id": "obj1", "alias": "rows"}], "fields": [{"field_id": "f1", "object_id": "obj1", "alias": "name", "type": "string"}, {"field_id": "grp", "object_id": "obj1", "alias": "group", "type": "string"}], "query": {"projection": ["f1", "grp"], "filters": {"op": "and", "items": []}, "sorts": [], "groups": [], "aggregates": []}}]
    p = d["pages"][0]
    p.update(kind="flow", dataset_id="ds1", height_mm=100, elements=[], bands=[{"band_id": "detail", "type": "Detail", "height_mm": 10, "elements": [field()]}])
    return d


def test_default_is_valid_and_canonical_copy():
    d = default_definition()
    validated = validate_definition(d)
    validated["pages"][0]["elements"][0]["text"] = "changed"
    assert d["pages"][0]["elements"][0]["text"] != "changed"
    assert canonical_json({"z": 1, "a": "한글"}) == '{"a":"한글","z":1}'


@pytest.mark.parametrize("mutate", [lambda d: d.update(sql="SELECT secret"), lambda d: d["pages"][0]["elements"][0].update(type="script"), lambda d: d["pages"][0]["elements"][0]["style"].update(color="url(http://evil)"), lambda d: d["pages"][0].update(width_mm=float("nan")), lambda d: d.update(schema_version="9.0"), lambda d: d["pages"][0]["elements"][0].update(url="http://evil"), lambda d: d["pages"][0]["elements"][0].update(type=[]), lambda d: d["pages"][0]["elements"][0]["geometry"].update(x_mm=True)])
def test_rejects_executable_unknown_and_malformed_values(mutate):
    d = default_definition()
    mutate(d)
    with pytest.raises(DefinitionError):
        validate_definition(d)


def test_fixed_text_is_escaped_and_multiple_templates_numbered():
    d = default_definition('<script>alert("x")</script>')
    p = copy.deepcopy(d["pages"][0])
    p["page_id"] = "p2"
    p["elements"][0].update(element_id="page_no", type="page_number")
    p["elements"][0].pop("text")
    d["pages"].append(p)
    r = render_report(d, {})
    assert r["page_count"] == 2
    assert "<script>" not in r["html"]
    assert "&lt;script&gt;" in r["html"]
    assert '>2</div>' in r["pages"][1]
    assert "width:210mm;height:297mm" in r["pages"][0]


def test_flow_repeats_data_and_page_headers_footers():
    d = flow_definition()
    p = d["pages"][0]
    page_no = {"element_id": "page_no", "type": "page_number", "geometry": {"x_mm": 0, "y_mm": 0, "width_mm": 30, "height_mm": 6}}
    total = {**page_no, "element_id": "total", "type": "total_pages"}
    p["bands"] += [{"band_id": "header", "type": "PageHeader", "height_mm": 10, "elements": [page_no]}, {"band_id": "footer", "type": "PageFooter", "height_mm": 10, "elements": [total]}]
    rows = [{"f1": f"row-{i}", "grp": "A"} for i in range(11)]
    r = render_report(d, {"ds1": {"rows": rows}})
    assert r["page_count"] == 3
    assert all(r["html"].count(f">row-{i}</div>") == 1 for i in range(11))
    assert r["pages"][0].count('data-element-id="page_no"') == 1
    assert r["pages"][2].count('>3</div>') == 2


def test_group_headers_footers_and_forced_breaks():
    d = flow_definition()
    d["pages"][0]["bands"] += [{"band_id": "gh", "type": "GroupHeader", "height_mm": 8, "group_field_id": "grp", "page_break_before": True, "elements": [field("group_name", "group", "grp")]}, {"band_id": "gf", "type": "GroupFooter", "height_mm": 8, "group_field_id": "grp", "elements": []}]
    r = render_report(d, {"ds1": {"rows": [{"f1": "a", "grp": "A"}, {"f1": "b", "grp": "A"}, {"f1": "c", "grp": "B"}]}})
    assert r["page_count"] == 2
    assert ">A</div>" in r["pages"][0] and ">B</div>" in r["pages"][1]
    with pytest.raises(RenderError, match="contiguous"):
        render_report(d, {"ds1": {"rows": [{"f1": "a", "grp": "A"}, {"f1": "b", "grp": "B"}, {"f1": "c", "grp": "A"}]}})


def test_grow_paginates_and_rejects_oversized_indivisible_row():
    d = flow_definition()
    d["pages"][0]["bands"][0]["elements"][0]["overflow"] = "grow"
    r = render_report(d, {"ds1": {"rows": [{"f1": "긴 한글 문장 " * 20} for _ in range(3)]}})
    assert r["page_count"] >= 2
    with pytest.raises(RenderError, match="taller"):
        render_report(d, {"ds1": {"rows": [{"f1": "긴 글 " * 1000}]}})


def test_page_break_element_and_malformed_intersection():
    d = flow_definition()
    band = d["pages"][0]["bands"][0]
    band["height_mm"] = 20
    band["elements"] += [{"element_id": "br", "type": "page_break", "geometry": {"x_mm": 0, "y_mm": 8, "width_mm": 1, "height_mm": 0}}, {"element_id": "tail", "type": "text", "text": "after-break", "geometry": {"x_mm": 0, "y_mm": 10, "width_mm": 50, "height_mm": 6}}]
    r = render_report(d, {"ds1": {"rows": [{"f1": "before-break"}]}})
    assert r["page_count"] == 2
    assert "before-break" in r["pages"][0] and "after-break" in r["pages"][1]
    band["elements"][1]["geometry"]["y_mm"] = 3
    with pytest.raises(RenderError, match="intersects"):
        render_report(d, {"ds1": {"rows": [{"f1": "before-break"}]}})


def test_single_scope_never_silently_selects_first_of_many():
    d = flow_definition()
    d["pages"][0]["bands"][0]["elements"][0]["binding"]["scope"] = "single"
    with pytest.raises(RenderError, match="multiple"):
        render_report(d, {"ds1": {"rows": [{"f1": "A"}, {"f1": "B"}]}})


def test_actual_pdf_uses_same_pages_and_escaped_visible_text():
    pytest.importorskip("playwright")
    pypdf = pytest.importorskip("pypdf")
    d = flow_definition()
    r = render_report(d, {"ds1": {"rows": [{"f1": f"record-{i}"} for i in range(12)]}})
    try:
        pdf = pdf_bytes(r["html"])
    except RenderError as exc:
        if "Executable doesn't exist" in str(exc.__cause__):
            pytest.skip("Chromium browser binary is unavailable")
        raise
    import io
    document = pypdf.PdfReader(io.BytesIO(pdf))
    assert len(document.pages) == r["page_count"]
    assert abs(float(document.pages[0].mediabox.width) - 210 / 25.4 * 72) < 1
    assert abs(float(document.pages[0].mediabox.height) - 100 / 25.4 * 72) < 1
    text = "".join(p.extract_text() for p in document.pages)
    for i in range(12):
        assert f"record-{i}" in text


def test_parameters_are_typed_and_validated_before_execution():
    d = default_definition()
    d["parameters"] = [{"name": "limit", "type": "integer", "required": True, "min": 1, "max": 100}, {"name": "enabled", "type": "boolean", "default": False}, {"name": "from_date", "type": "date", "default": "2026-10-01"}]
    assert validate_parameters(d, {"limit": "25", "enabled": "true"}) == {"limit": 25, "enabled": True, "from_date": "2026-10-01"}
    for params in [{}, {"limit": True}, {"limit": "200"}, {"limit": "25", "unknown": 1}, {"limit": "25", "from_date": "2026-02-30"}]:
        with pytest.raises(DefinitionError):
            validate_parameters(d, params)


def test_aggregate_output_contract_can_bind_generated_logical_id():
    d = flow_definition()
    ds = d["datasets"][0]
    ds["query"]["aggregates"] = [{"aggregate_id": "total", "function": "count"}]
    ds["query"]["projection"] = ["total"]
    d["pages"][0]["bands"][0]["elements"][0]["binding"]["field_id"] = "total"
    rendered = render_report(d, {"ds1": {"rows": [{"total": 7}]}})
    assert ">7</div>" in rendered["html"]


def test_fixed_grow_inside_printable_area_and_following_element_shift():
    d = default_definition()
    e = d["pages"][0]["elements"][0]
    e.update(text="Long text " * 40, overflow="grow")
    e["geometry"].update(width_mm=40, height_mm=5)
    e["style"] = {"font_size_pt": 10}
    d["pages"][0]["elements"].append({"element_id": "after", "type": "text", "text": "after", "geometry": {"x_mm": 0, "y_mm": 10, "width_mm": 50, "height_mm": 10}})
    r = render_report(d, {})
    assert r["page_count"] == 1
    import re
    y = float(re.search(r'data-element-id="after" style="position:absolute;left:0?[^;]*;top:([0-9.]+)mm', r["html"]).group(1))
    assert y > 25


def test_group_subtotals_use_only_current_group_rows():
    d = flow_definition()
    ds = d["datasets"][0]
    ds["fields"][0]["type"] = "integer"
    subtotal = field("subtotal", "aggregate")
    subtotal["binding"].update(aggregate="sum", aggregate_scope="group")
    d["pages"][0]["bands"].append({"band_id": "gf", "type": "GroupFooter", "group_field_id": "grp", "height_mm": 8, "elements": [subtotal]})
    r = render_report(d, {"ds1": {"rows": [{"f1": 2, "grp": "A"}, {"f1": 3, "grp": "A"}, {"f1": 7, "grp": "B"}]}})
    assert 'data-element-id="subtotal"' in r["html"]
    assert ">5</div>" in r["html"] and ">7</div>" in r["html"]
    assert ">12</div>" not in r["html"]


def test_decimal_parameters_preserve_financial_precision():
    d = default_definition()
    d["parameters"] = [{"name": "amount", "type": "decimal", "min": 0}]
    assert validate_parameters(d, {"amount": "12345678901234.56"})["amount"] == "12345678901234.56"
    with pytest.raises(DefinitionError):
        validate_parameters(d, {"amount": "nan"})
