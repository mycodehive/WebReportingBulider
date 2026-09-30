"""DOM test fixtures and a real Python contract/rendering check; no database required."""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.template.loader import render_to_string  # noqa: E402
from django.test import RequestFactory  # noqa: E402
from openpyxl import Workbook  # noqa: E402

from reportbuilder.data import execute_dataset, introspect  # noqa: E402
from reportbuilder.definition import default_definition, validate_definition  # noqa: E402
from reportbuilder.rendering import render_report  # noqa: E402

REPORT_ID = "00000000-0000-0000-0000-000000000001"
CONNECTION_ID = "00000000-0000-0000-0000-000000000002"


def workbook(path):
    book = Workbook()
    sheet = book.active
    sheet.title = "Staff"
    sheet.append(["name", "salary"])
    sheet.append(["Alice", 100.25])
    sheet.append(["Bob", 200.5])
    book.save(path)


def render_fixture():
    request = RequestFactory().get(f"/reports/{REPORT_ID}/design/")
    request.user = SimpleNamespace(
        is_authenticated=True, is_staff=True, get_username=lambda: "DOM test"
    )
    definition = default_definition("테스트 보고서")
    report = SimpleNamespace(id=REPORT_ID, name=definition["name"], revision=1, definition=definition)
    html = render_to_string("reportbuilder/designer.html", {"report": report}, request=request)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "staff.xlsx"
        workbook(path)
        schema = introspect("excel", {"path": str(path)})
    return {
        "html": html,
        "report": {"id": REPORT_ID, "name": report.name, "definition": definition,
                   "revision": 1, "bindings": []},
        "connections": {"connections": [{"id": CONNECTION_ID, "name": "Test workbook", "kind": "excel"}]},
        "schema": schema,
    }


def validate_results(payload):
    definitions = payload["definitions"]
    for definition in definitions:
        validate_definition(definition)
    definition = definitions[-1]
    bindings = {b["dataset_id"]: b for b in payload["bindings"]}
    parameters = {p["name"]: p.get("default") for p in definition["parameters"]}
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "staff.xlsx"
        workbook(path)
        datasets = {
            ds["dataset_id"]: execute_dataset("excel", {"path": str(path)}, ds,
                                              bindings[ds["dataset_id"]], parameters)
            for ds in definition["datasets"]
        }
        rendered = render_report(definition, datasets, parameters)
    assert rendered["page_count"] >= 2, "Flow and added fixed page should both render"
    assert "Alice" in rendered["html"], "Logical field should resolve through the local binding"
    assert "100" in rendered["html"], "Filtered number and footer sum should render"
    assert "Bob" not in rendered["html"], "Parameter filter should exclude the second row"
    return {"definition_count": len(definitions), "page_count": rendered["page_count"],
            "row_count": next(iter(datasets.values()))["row_count"]}


if __name__ == "__main__":
    if sys.argv[1] == "render":
        result = render_fixture()
    elif sys.argv[1] == "validate":
        result = validate_results(json.load(sys.stdin))
    else:
        raise SystemExit("Expected render or validate")
    print(json.dumps(result, ensure_ascii=False))
