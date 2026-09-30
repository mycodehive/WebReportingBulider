"""One escaped, paginated HTML representation for preview and PDF."""
import base64
import datetime
import html
import math
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from .definition import DefinitionError, validate_definition, validate_parameters


class RenderError(DefinitionError):
    code = "render_error"


def _rows(datasets, dataset_id):
    result = datasets.get(dataset_id)
    if not isinstance(result, dict) or not isinstance(result.get("rows"), list):
        raise RenderError(f"Dataset {dataset_id} has no supplied row data")
    rows = result["rows"]
    if len(rows) > 10000 or any(not isinstance(row, dict) for row in rows):
        raise RenderError("Dataset row limit exceeded or malformed rows")
    return rows


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, bytes)):
        raise RenderError("Scalar field value required")
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    text = str(value)
    if len(text) > 100000:
        raise RenderError("Field text exceeds rendering limit")
    return text


def _aggregate(rows, field_id, function):
    values = [r.get(field_id) for r in rows if r.get(field_id) is not None]
    if function == "count":
        return len(values)
    if not values:
        return None
    if function in {"min", "max"}:
        try:
            return (min if function == "min" else max)(values)
        except TypeError as exc:
            raise RenderError("Mixed values cannot be aggregated") from exc
    try:
        numbers = [Decimal(str(v)) for v in values]
        if any(not n.is_finite() for n in numbers):
            raise InvalidOperation
        total = sum(numbers)
        return total if function == "sum" else total / len(numbers)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RenderError("Numeric aggregate requires finite numeric values") from exc


def _value(e, datasets, params, row, group_rows, now, page_number=0, total_pages=0):
    kind = e["type"]
    if kind == "text":
        return e["text"]
    if kind == "parameter":
        return _text(params.get(e["parameter_name"]))
    if kind == "generated_at":
        return now
    if kind == "page_number":
        return str(page_number)
    if kind == "total_pages":
        return str(total_pages)
    if kind != "field":
        return ""
    b = e["binding"]
    rows = _rows(datasets, b["dataset_id"])
    scope, field = b["scope"], b["field_id"]
    if scope == "aggregate":
        members = (group_rows or []) if b.get("aggregate_scope") == "group" else rows
        return _text(_aggregate(members, field, b["aggregate"]))
    if scope == "single" and len(rows) > 1:
        raise RenderError("single field binding received multiple rows")
    source = row if scope == "row" else ((group_rows or [{}])[0] if scope == "group" else (rows or [{}])[0])
    return _text((source or {}).get(field))


def _estimated_text_height(text, e):
    """Conservative deterministic sizing; browser text remains clipped to allocated box."""
    style, g = e.get("style", {}), e["geometry"]
    em = style.get("font_size_pt", 10) * 25.4 / 72
    capacity = max(1, (g["width_mm"] - .8) / em)
    lines = 0
    for paragraph in text.split("\n"):
        width = sum(1.15 if unicodedata.east_asian_width(c) in {"W", "F"} else .75 for c in paragraph)
        lines += max(1, math.ceil(width / capacity))
    return max(g["height_mm"], lines * em * style.get("line_height", 1.25) + .8)


def _layout_band(band, datasets, params, row, group_rows, now):
    positioned = []
    shifts = []
    for e in sorted(band["elements"], key=lambda x: (x["geometry"]["y_mm"], x["element_id"])):
        g = e["geometry"]
        y = g["y_mm"] + max([delta for end, delta in shifts if end <= g["y_mm"] + .001] or [0])
        height = g["height_mm"]
        if e.get("overflow") == "grow":
            height = _estimated_text_height(_value(e, datasets, params, row, group_rows, now), e)
            if height > g["height_mm"]:
                shifts.append((g["y_mm"] + g["height_mm"], y - g["y_mm"] + height - g["height_mm"]))
        positioned.append({"element": e, "x": g["x_mm"], "y": y, "width": g["width_mm"], "height": height, "row": row, "group_rows": group_rows})
    end = max([p["y"] + p["height"] for p in positioned] or [0])
    height = max(band["height_mm"] + max([v for _, v in shifts] or [0]), end)
    breaks = sorted(set(p["y"] for p in positioned if p["element"]["type"] == "page_break"))
    if not breaks:
        return [{"height": height, "items": positioned, "break_before": band.get("page_break_before", False)}]
    for p in positioned:
        if p["element"]["type"] != "page_break" and any(p["y"] < b < p["y"] + p["height"] for b in breaks):
            raise RenderError("A page break intersects an element; move it between elements")
    cuts = sorted(set([0, *breaks, height]))
    pieces = []
    for i in range(len(cuts) - 1):
        start, end = cuts[i], cuts[i + 1]
        items = []
        for p in positioned:
            if p["element"]["type"] != "page_break" and start <= p["y"] < end:
                item = dict(p)
                item["y"] -= start
                items.append(item)
        pieces.append({"height": end - start, "items": items, "break_before": start in breaks or (i == 0 and band.get("page_break_before", False))})
    if height in breaks:
        pieces.append({"height": 0, "items": [], "break_before": True})
    return pieces


def _image_data(asset_id, resolver):
    if resolver is None:
        raise RenderError(f"Asset {asset_id} has no resolver")
    src = resolver(asset_id)
    if not isinstance(src, str) or len(src) > 14_000_000:
        raise RenderError("Invalid image asset")
    match = re.fullmatch(r"data:(image/(?:png|jpeg|gif|webp));base64,([A-Za-z0-9+/=]+)", src)
    if not match:
        raise RenderError("Only approved embedded raster images are accepted")
    try:
        data = base64.b64decode(match[2], validate=True)
    except ValueError as exc:
        raise RenderError("Invalid image encoding") from exc
    from .packaging import validate_asset
    validate_asset(data, match[1])
    return src


def _element_html(p, datasets, params, now, number, total, resolver, offset_x=0, offset_y=0):
    e, style = p["element"], p["element"].get("style", {})
    kind = e["type"]
    if kind == "page_break":
        return ""
    css = ["position:absolute", f"left:{p['x'] + offset_x:.4f}mm", f"top:{p['y'] + offset_y:.4f}mm", f"width:{p['width']:.4f}mm", f"height:{p['height']:.4f}mm", "box-sizing:border-box", "overflow:hidden"]
    css += [f"font-size:{style.get('font_size_pt', 10)}pt", f"font-family:{style.get('font_family', 'sans-serif')}", f"font-weight:{style.get('font_weight', 'normal')}", f"font-style:{style.get('font_style', 'normal')}", f"text-align:{style.get('text_align', 'left')}", f"line-height:{style.get('line_height', 1.25)}", f"color:{style.get('color', '#111111')}", "white-space:pre-wrap", "overflow-wrap:anywhere"]
    if style.get("background_color"):
        css.append(f"background-color:{style['background_color']}")
    if style.get("border_width_mm", 0) > 0 or kind == "rectangle":
        css.append(f"border:{style.get('border_width_mm', .2)}mm solid {style.get('border_color', '#111111')}")
    if kind == "line":
        css.append(f"border-top:{style.get('border_width_mm', .2)}mm solid {style.get('border_color', '#111111')}")
    alignment = style.get("vertical_align", "top")
    if alignment != "top":
        css.extend(["display:flex", "flex-direction:column", f"justify-content:{'center' if alignment == 'middle' else 'flex-end'}"])
    value = html.escape(_value(e, datasets, params, p.get("row"), p.get("group_rows"), now, number, total))
    if kind == "image":
        src = html.escape(_image_data(e["asset_id"], resolver), quote=True)
        value = f'<img alt="" src="{src}" style="width:100%;height:100%;object-fit:{e.get("fit", "contain")}">'
    return f'<div data-element-id="{e["element_id"]}" style="{";".join(css)}">{value}</div>'


def render_report(definition, datasets, parameters=None, asset_resolver=None):
    d = validate_definition(definition)
    if not isinstance(datasets, dict):
        raise RenderError("datasets must be an object")
    params = validate_parameters(d, parameters)
    for ds in d["datasets"]:
        rows = _rows(datasets, ds["dataset_id"])
        if ds["cardinality"] == "one" and len(rows) > 1:
            raise RenderError("Single-row dataset received multiple rows")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    output = []
    for template in d["pages"]:
        m = template["margins"]
        printable_height = template["height_mm"] - m["top"] - m["bottom"]
        if template["kind"] == "fixed":
            fake = {"elements": template["elements"], "height_mm": 0}
            segments = _layout_band(fake, datasets, params, None, None, now)
            if len(segments) != 1 or segments[0]["height"] > printable_height + .001:
                raise RenderError("Growing fixed-page content exceeds the printable area")
            output.append({"template": template, "items": segments[0]["items"]})
            continue
        bands = {b["type"]: b for b in template["bands"]}
        header = _layout_band(bands["PageHeader"], datasets, params, None, None, now)[0] if "PageHeader" in bands else {"height": 0, "items": []}
        footer = _layout_band(bands["PageFooter"], datasets, params, None, None, now)[0] if "PageFooter" in bands else {"height": 0, "items": []}
        usable = printable_height - header["height"] - footer["height"]
        if usable <= 0:
            raise RenderError("Page header and footer leave no body area")
        current = None
        cursor = 0
        body_count = 0
        def new_page():
            nonlocal current, cursor, body_count
            if len(output) >= 1000:
                raise RenderError("Rendered page limit exceeded")
            items = [dict(p) for p in header["items"]]
            for p in footer["items"]:
                item = dict(p)
                item["y"] += printable_height - footer["height"]
                items.append(item)
            current = {"template": template, "items": items}
            output.append(current)
            cursor, body_count = header["height"], 0
        def place_band(kind, row=None, group_rows=None, keep_with=0):
            nonlocal cursor, body_count
            if kind not in bands:
                return
            segments = _layout_band(bands[kind], datasets, params, row, group_rows, now)
            for segment in segments:
                size = segment["height"]
                if size > usable + .001:
                    raise RenderError(f"{kind} band is taller than a page body; reduce text or split the template")
                remaining = printable_height - footer["height"] - cursor
                if (segment["break_before"] and body_count) or size > remaining + .001 or (body_count and size + keep_with > remaining + .001 and size + keep_with <= usable):
                    new_page()
                for p in segment["items"]:
                    item = dict(p)
                    item["y"] += cursor
                    current["items"].append(item)
                cursor += size
                if size or segment["items"]:
                    body_count += 1
        new_page()
        place_band("ReportHeader")
        rows = _rows(datasets, template["dataset_id"])
        group_band = bands.get("GroupHeader") or bands.get("GroupFooter")
        groups = []
        if group_band:
            fid = group_band["group_field_id"]
            seen = set()
            for row in rows:
                marker = (type(row.get(fid)).__name__, _text(row.get(fid)))
                if not groups or groups[-1][0] != marker:
                    if marker in seen:
                        raise RenderError("Grouping requires contiguous sorted group values; sort by the group field")
                    seen.add(marker)
                    groups.append((marker, [row]))
                else:
                    groups[-1][1].append(row)
        else:
            groups = [(None, rows)]
        for _, group_rows in groups:
            if group_band and group_rows:
                first_height = sum(s["height"] for s in _layout_band(bands["Detail"], datasets, params, group_rows[0], group_rows, now))
                place_band("GroupHeader", group_rows[0], group_rows, first_height)
            for row in group_rows:
                place_band("Detail", row, group_rows)
            if group_band and group_rows:
                place_band("GroupFooter", group_rows[-1], group_rows)
        place_band("ReportFooter")
    total, pages, rules = len(output), [], []
    if total > 1000:
        raise RenderError("Rendered page limit exceeded")
    for index, page in enumerate(output, 1):
        t, m = page["template"], page["template"]["margins"]
        page_name = "sheet_" + t["page_id"]
        rule = f"@page {page_name}{{size:{t['width_mm']}mm {t['height_mm']}mm;margin:0}}"
        if rule not in rules:
            rules.append(rule)
        body = "".join(_element_html(p, datasets, params, now, index, total, asset_resolver, m["left"], m["top"]) for p in page["items"])
        pages.append(f'<section class="report-page" data-page="{index}" style="page:{page_name};width:{t["width_mm"]}mm;height:{t["height_mm"]}mm">{body}</section>')
    css = """html,body{margin:0;padding:0}body{background:#e5e7eb}.report-page{position:relative;box-sizing:border-box;background:white;margin:12px auto;overflow:hidden;break-after:page;break-inside:avoid}.report-page:last-child{break-after:auto}@media print{body{background:white}.report-page{margin:0;box-shadow:none;-webkit-print-color-adjust:exact;print-color-adjust:exact}}"""
    rendered = '<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; font-src \'none\'"><title>' + html.escape(d["name"]) + "</title><style>" + css + "".join(rules) + "</style></head><body>" + "".join(pages) + "</body></html>"
    if len(rendered.encode()) > 50_000_000:
        raise RenderError("Rendered document exceeds size limit")
    return {"html": rendered, "page_count": total, "pages": pages, "generated_at": now, "warnings": ["Text growth uses conservative line measurement; oversized indivisible bands are rejected."]}


def pdf_bytes(html_document):
    """PDF from exactly the preview HTML. Optional browser installation is required."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RenderError("PDF requires the optional Playwright dependency and Chromium installation") from exc
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.route("**/*", lambda route: route.abort())
                page.set_content(html_document, wait_until="load", timeout=30000)
                page.emulate_media(media="print")
                page.evaluate("document.fonts.ready")
                return page.pdf(print_background=True, prefer_css_page_size=True, margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
            finally:
                browser.close()
    except Exception as exc:
        raise RenderError("PDF renderer unavailable; install Chromium or inspect server logs") from exc
