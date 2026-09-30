import datetime as dt
import sqlite3
from decimal import Decimal
from unittest.mock import Mock

import pytest

from reportbuilder import data


def dataset(names, types=None, object_name="employees", conversions=None):
    types = types or ["string"] * len(names)
    conversions = conversions or {}
    fields = [{"field_id": f"f{i}", "object_id": "obj1", "alias": name,
               "label": name, "type": types[i], "required": True, "nullable": True}
              for i, name in enumerate(names)]
    contract = {"dataset_id": "ds1", "cardinality": "many", "objects": [{"object_id": "obj1"}],
                "fields": fields, "query": {"projection": [f["field_id"] for f in fields],
                                            "filters": {"op": "and", "items": []}, "sorts": [],
                                            "groups": [], "aggregates": []}}
    binding = {"dataset_id": "ds1", "object_mappings": {"obj1": {"object": object_name, "schema": None}},
               "field_mappings": {f["field_id"]: {"column": f["alias"], "conversion": conversions.get(f["alias"], "identity")}
                                  for f in fields}}
    return contract, binding


@pytest.fixture
def sqlite_file(tmp_path):
    path = tmp_path / "source.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE employees (name TEXT, department TEXT, amount DECIMAL, joined DATE)")
        conn.executemany("INSERT INTO employees VALUES (?,?,?,?)", [
            ("가", "A", 10.25, "2026-01-01"), ("나", "A", 20, "2026-02-01"),
            ("다", "B", 5, "2026-03-01"), ("라", "B", None, "2026-04-01")])
    return {"path": str(path)}


def test_catalog_explicit_uncertified_capabilities():
    kinds = {item["kind"] for item in data.connector_catalog()}
    assert {"excel", "csv", "sqlite", "postgresql", "mariadb", "oracle", "mssql", "google_sheets", "access", "rest"} <= kinds
    assert all(not item["verified"] and not item["capabilities"]["joins"] for item in data.connector_catalog())


def test_sqlite_introspection_and_readonly(sqlite_file):
    result = data.introspect("sqlite", sqlite_file)
    assert result["objects"][0]["object"] == "employees"
    columns = {c["column"]: c for c in result["objects"][0]["columns"]}
    assert columns["amount"]["type"] == "decimal"
    assert columns["joined"]["type"] == "date"
    with data._sqlite(sqlite_file) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM employees")
    assert data.test_connection("sqlite", sqlite_file)["object_count"] == 1


def test_unicode_identifier_and_sql_injection_are_literals(tmp_path):
    path = tmp_path / "injection.db"
    table, column = '연구원"; DROP TABLE kept;--', '이름"; DELETE FROM kept;--'
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE kept (value TEXT)")
        conn.execute(f"CREATE TABLE {data._identifier(table)} ({data._identifier(column)} TEXT)")
        conn.execute(f"INSERT INTO {data._identifier(table)} VALUES (?)", ("안전",))
    contract, binding = dataset([column], object_name=table)
    assert data.execute_dataset("sqlite", {"path": str(path)}, contract, binding)["rows"] == [{"f0": "안전"}]
    binding["object_mappings"]["obj1"]["object"] = "kept; DROP TABLE kept"
    with pytest.raises(data.DataError, match="매핑된") as caught:
        data.execute_dataset("sqlite", {"path": str(path)}, contract, binding)
    assert caught.value.code == "SCHEMA_CHANGED"
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM kept").fetchone()[0] == 0


def test_filter_parameter_projection_sort(sqlite_file):
    contract, binding = dataset(["name", "amount"], ["string", "decimal"], conversions={"amount": "to_decimal"})
    contract["query"].update({"filters": {"field_id": "f1", "operator": "gte", "parameter": "minimum"},
                              "sorts": [{"field_id": "f1", "direction": "desc", "nulls": "first"}], "projection": ["f0"]})
    result = data.execute_dataset("sqlite", sqlite_file, contract, binding, {"minimum": "10.25"})
    assert result["rows"] == [{"f0": "나"}, {"f0": "가"}]
    assert result["source_row_count"] == 4
    assert result["truncated"] is False


def test_group_aggregate_decimal_precision_and_nulls(sqlite_file):
    contract, binding = dataset(["department", "amount"], ["string", "decimal"], conversions={"amount": "to_decimal"})
    contract["query"].update({"groups": ["f0"], "aggregates": [
        {"aggregate_id": "total", "function": "sum", "field_id": "f1"},
        {"aggregate_id": "number", "function": "count", "field_id": "f1"},
        {"aggregate_id": "all", "function": "count"}],
        "projection": ["f0", "total", "number", "all"], "sorts": [{"field_id": "total", "direction": "desc"}]})
    result = data.execute_dataset("sqlite", sqlite_file, contract, binding)
    assert result["rows"] == [{"f0": "A", "total": "30.25", "number": 2, "all": 2},
                              {"f0": "B", "total": "5", "number": 1, "all": 2}]


def test_cap_rejects_partial_aggregate_but_exact_cap_succeeds(sqlite_file):
    contract, binding = dataset(["amount"], ["decimal"], conversions={"amount": "to_decimal"})
    contract["query"].update({"projection": ["sum"], "aggregates": [{"aggregate_id": "sum", "function": "sum", "field_id": "f0"}]})
    with pytest.raises(data.DataError) as caught:
        data.execute_dataset("sqlite", sqlite_file, contract, binding, max_rows=3)
    assert caught.value.code == "DATA_LIMIT"
    assert data.execute_dataset("sqlite", sqlite_file, contract, binding, max_rows=4)["rows"] == [{"sum": "35.25"}]


def test_missing_parameter_null_filter_and_invalid_query(sqlite_file):
    contract, binding = dataset(["amount"], ["decimal"])
    contract["query"]["filters"] = {"field_id": "f0", "operator": "gte", "parameter": "p"}
    with pytest.raises(data.DataError) as caught:
        data.execute_dataset("sqlite", sqlite_file, contract, binding)
    assert caught.value.code == "MISSING_PARAMETER"
    contract["query"]["filters"] = {"field_id": "f0", "operator": "is_null"}
    assert data.execute_dataset("sqlite", sqlite_file, contract, binding)["rows"] == [{"f0": None}]
    contract["query"]["filters"] = {"field_id": "unknown", "operator": "eq", "value": 1}
    with pytest.raises(data.DataError) as caught:
        data.execute_dataset("sqlite", sqlite_file, contract, binding)
    assert caught.value.code == "INVALID_QUERY"


@pytest.mark.parametrize("change", ["object", "field", "conversion", "type", "dataset"])
def test_invalid_mapping_rejected(sqlite_file, change):
    contract, binding = dataset(["name"])
    if change == "object":
        binding["object_mappings"]["obj1"]["object"] = "missing"
    elif change == "field":
        binding["field_mappings"]["f0"]["column"] = "missing"
    elif change == "conversion":
        binding["field_mappings"]["f0"]["conversion"] = "eval"
    elif change == "type":
        contract["fields"][0]["type"] = "integer"
    else:
        binding["dataset_id"] = "other"
    with pytest.raises(data.DataError):
        data.execute_dataset("sqlite", sqlite_file, contract, binding)


def test_optional_mapping_default_and_single_cardinality(sqlite_file):
    contract, binding = dataset(["name", "optional"])
    contract["fields"][1]["required"] = False
    contract["fields"][1]["default"] = "기본값"
    binding["field_mappings"].pop("f1")
    result = data.execute_dataset("sqlite", sqlite_file, contract, binding)
    assert all(row["f1"] == "기본값" for row in result["rows"])
    contract["cardinality"] = "one"
    with pytest.raises(data.DataError) as caught:
        data.execute_dataset("sqlite", sqlite_file, contract, binding)
    assert caught.value.code == "CARDINALITY_MISMATCH"


def test_csv_headers_preserve_unicode_and_disambiguate(tmp_path):
    path = tmp_path / "test.csv"
    path.write_text("이름,,이름\n가,1,10.25\n나,2,20.00\n", encoding="utf-8-sig")
    config = {"path": str(path)}
    assert [c["column"] for c in data.introspect("csv", config)["objects"][0]["columns"]] == ["이름", "column_2", "이름_2"]
    contract, binding = dataset(["이름", "이름_2"], ["string", "decimal"], object_name="data", conversions={"이름_2": "to_decimal"})
    result = data.execute_dataset("csv", config, contract, binding)
    assert result["rows"] == [{"f0": "가", "f1": "10.25"}, {"f0": "나", "f1": "20.00"}]


def test_csv_extra_columns_rejected(tmp_path):
    path = tmp_path / "test.csv"
    path.write_text("a,b\n1,2,3\n")
    with pytest.raises(data.DataError) as caught:
        data.introspect("csv", {"path": str(path)})
    assert caught.value.code == "INVALID_FILE"


def test_excel_sheets_and_datetime(tmp_path):
    import openpyxl
    path = tmp_path / "test.xlsx"
    book = openpyxl.Workbook()
    book.active.title = "직원"
    book.active.append(["이름", "일시"])
    book.active.append(["가", dt.datetime(2026, 10, 1, 9, 30)])
    book.create_sheet("빈 시트")
    book.save(path)
    config = {"path": str(path)}
    schema = data.introspect("excel", config)
    assert len(schema["objects"]) == 2
    contract, binding = dataset(["이름", "일시"], ["string", "datetime"], object_name="직원")
    assert data.execute_dataset("excel", config, contract, binding)["rows"] == [{"f0": "가", "f1": "2026-10-01T09:30:00"}]


def test_filter_tree_budget_and_depth():
    node = {"field_id": "f", "operator": "eq", "value": 1}
    for _ in range(11):
        node = {"op": "and", "items": [node]}
    with pytest.raises(data.DataError):
        data._filter(node, {"f": {}}, {})
    node = {"op": "and", "items": [{"op": "and", "items": [{"field_id": "f", "operator": "eq", "value": 1} for _ in range(100)]} for _ in range(20)]}
    with pytest.raises(data.DataError):
        data._filter(node, {"f": {}}, {})


def test_in_between_and_date_parameter():
    pred = data._filter({"op": "or", "items": [{"field_id": "f", "operator": "in", "value": [1, 2]},
                       {"field_id": "f", "operator": "between", "value": [5, 8]}]}, {"f": {}}, {})
    assert pred({"f": 2}) and pred({"f": 7}) and not pred({"f": 4})
    pred = data._filter({"field_id": "f", "operator": "gte", "parameter": "start"}, {"f": {}}, {"start": "2026-10-01"})
    assert pred({"f": dt.date(2026, 10, 1)}) and not pred({"f": dt.date(2026, 9, 30)})


def test_sort_null_position_independent_of_direction():
    for direction in ("asc", "desc"):
        rows = [{"f": None}, {"f": 1}, {"f": 2}]
        assert data._sort(rows, [{"field_id": "f", "direction": direction, "nulls": "first"}], {"f": {}})[0]["f"] is None
        assert data._sort(rows, [{"field_id": "f", "direction": direction, "nulls": "last"}], {"f": {}})[-1]["f"] is None


def test_explicit_numeric_conversion_does_not_truncate():
    assert data._convert("00012", "to_string", {}) == "00012"
    assert data._convert("12.00", "to_integer", {}) == 12
    with pytest.raises(data.DataError):
        data._convert("12.5", "to_integer", {})
    with pytest.raises(data.DataError):
        data._convert("NaN", "to_decimal", {})
    assert data._json_safe(Decimal("12345678901234567890.12")) == "12345678901234567890.12"


def test_number_contract_accepts_numeric_source(sqlite_file):
    contract, binding = dataset(["amount"], ["number"])
    assert data.execute_dataset("sqlite", sqlite_file, contract, binding)["rows"][0]["f0"] == 10.25


def test_declared_integer_cannot_receive_fractional_decimal(sqlite_file):
    contract, binding = dataset(["amount"], ["integer"])
    with pytest.raises(data.DataError) as caught:
        data.execute_dataset("sqlite", sqlite_file, contract, binding)
    assert caught.value.code == "TYPE_MISMATCH"


def test_sqlite_date_normalized_for_date_parameters(sqlite_file):
    contract, binding = dataset(["joined"], ["date"])
    contract["query"]["filters"] = {"field_id": "f0", "operator": "gte", "parameter": "start"}
    result = data.execute_dataset("sqlite", sqlite_file, contract, binding, {"start": "2026-03-01"})
    assert result["rows"] == [{"f0": "2026-03-01"}, {"f0": "2026-04-01"}]


def test_sqlite_affinity_does_not_override_runtime_contract(tmp_path):
    path = tmp_path / "dynamic.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE employees (x INTEGER)")
        conn.execute("INSERT INTO employees VALUES ('invalid-number')")
    contract, binding = dataset(["x"], ["integer"])
    with pytest.raises(data.DataError) as caught:
        data.execute_dataset("sqlite", {"path": str(path)}, contract, binding)
    assert caught.value.code == "TYPE_MISMATCH"


def test_inferred_nullability_is_not_a_schema_guarantee():
    col = data._columns(["x"], [{"x": 1}])[0]
    assert col["nullable"] is True and col["sample_contains_null"] is False


def test_joins_and_raw_sql_explicitly_rejected(sqlite_file):
    contract, binding = dataset(["name"])
    contract["objects"].append({"object_id": "obj2"})
    with pytest.raises(data.DataError) as caught:
        data.execute_dataset("sqlite", sqlite_file, contract, binding)
    assert caught.value.code == "UNSUPPORTED_CAPABILITY"
    contract["objects"].pop()
    contract["query"]["raw_sql"] = "DELETE FROM employees"
    with pytest.raises(data.DataError) as caught:
        data.execute_dataset("sqlite", sqlite_file, contract, binding)
    assert caught.value.code == "UNSUPPORTED_CAPABILITY"


def test_safe_errors_do_not_expose_password(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("postgresql://admin:very-private-password@host/db")
    monkeypatch.setattr(data, "_sql_schema", fail)
    with pytest.raises(data.DataError) as caught:
        data.introspect("postgresql", {"host": "host", "password": "very-private-password"})
    assert caught.value.code == "CONNECTION_FAILED"
    assert "very-private-password" not in str(caught.value)


@pytest.mark.parametrize("endpoint,allowed", [
    ("http://api.example.test/data", ["api.example.test"]),
    ("https://api.example.test:8443/data", ["api.example.test"]),
    ("https://admin:secret@api.example.test/data", ["api.example.test"]),
    ("https://api.example.test/data", []),
    ("https://api.example.test/data#fragment", ["api.example.test"]),
])
def test_rest_rejects_unsafe_endpoints_before_network(endpoint, allowed, monkeypatch):
    lookup = Mock()
    monkeypatch.setattr(data.socket, "getaddrinfo", lookup)
    with pytest.raises(data.DataError) as caught:
        data._https_json(endpoint, allowed_hosts=allowed)
    assert caught.value.code == "UNSAFE_ENDPOINT"
    lookup.assert_not_called()


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "192.168.1.1"])
def test_rest_blocks_private_dns(address, monkeypatch):
    monkeypatch.setattr(data.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", (address, 443))])
    with pytest.raises(data.DataError) as caught:
        data._https_json("https://api.example.test/data", allowed_hosts=["api.example.test"])
    assert caught.value.code == "UNSAFE_ENDPOINT"


def test_rest_pins_validated_ip_and_never_follows_redirect(monkeypatch):
    monkeypatch.setattr(data.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("8.8.8.8", 443))])
    response = Mock(status=302)
    conn = Mock()
    conn.getresponse.return_value = response
    factory = Mock(return_value=conn)
    monkeypatch.setattr(data, "_PinnedHTTPS", factory)
    with pytest.raises(data.DataError) as caught:
        data._https_json("https://api.example.test/data", allowed_hosts=["api.example.test"])
    assert caught.value.code == "REMOTE_ERROR"
    factory.assert_called_once_with("api.example.test", "8.8.8.8", 443)
    conn.request.assert_called_once_with("GET", "/data", headers={"Accept": "application/json"})
    conn.close.assert_called_once()


def test_rest_response_path_and_full_snapshot_limit(monkeypatch):
    monkeypatch.setattr(data, "_https_json", lambda *args, **kwargs: {"result": {"rows": [{"x": 1}, {"x": 2}, {"x": 3}]}})
    config = {"endpoint": "https://api.example.test/data", "records_path": "result.rows"}
    contract, binding = dataset(["x"], ["integer"], object_name="data")
    assert data.execute_dataset("rest", config, contract, binding)["rows"] == [{"f0": 1}, {"f0": 2}, {"f0": 3}]
    with pytest.raises(data.DataError) as caught:
        data.execute_dataset("rest", config, contract, binding, max_rows=2)
    assert caught.value.code == "DATA_LIMIT"


def test_sheet_blank_rows_cannot_hide_truncation(monkeypatch):
    responses = []
    def fake(endpoint, *args):
        responses.append(endpoint)
        if "?fields=" in endpoint:
            return {"sheets": [{"properties": {"title": "Staff's sheet"}}]}
        return {"values": [["x"], [1], [], [], [2], [3]]}
    monkeypatch.setattr(data, "_https_json", fake)
    config = {"spreadsheet_id": "abcd1234", "access_token": "test-token"}
    contract, binding = dataset(["x"], ["integer"], object_name="Staff's sheet")
    with pytest.raises(data.DataError) as caught:
        data.execute_dataset("sheets", config, contract, binding, max_rows=2)
    assert caught.value.code == "DATA_LIMIT"
    assert "%27Staff%27%27s%20sheet%27" in responses[-1]


def test_sheet_service_account_token_uri_cannot_redirect(monkeypatch):
    # Test before optional google-auth import by stubbing its modules.
    import sys
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", Mock(Credentials=Mock()))
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", Mock(Request=Mock()))
    with pytest.raises(data.DataError) as caught:
        data._sheet_headers({"service_account": {"token_uri": "https://169.254.169.254/token"}})
    assert caught.value.code == "INVALID_CONFIG"


def test_access_missing_dependency_is_explicit(tmp_path, monkeypatch):
    path = tmp_path / "sample.mdb"
    path.write_bytes(b"test")
    monkeypatch.setattr(data.shutil, "which", lambda command: None)
    with pytest.raises(data.DataError) as caught:
        data.introspect("access", {"path": str(path)})
    assert caught.value.code == "DRIVER_MISSING"


def test_access_subprocess_uses_arguments_not_shell(tmp_path, monkeypatch):
    path = tmp_path / "sample.mdb"
    path.write_bytes(b"test")
    monkeypatch.setattr(data.shutil, "which", lambda command: "/usr/bin/" + command)
    calls = []
    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        kwargs["stdout"].write(b"x\nhello\n")
        return Mock(returncode=0)
    monkeypatch.setattr(data.subprocess, "run", fake_run)
    names, rows = data._access_records({"path": str(path)}, "; echo secret", 10)
    assert names == ["x"] and rows == [{"x": "hello"}]
    assert calls[0][0][-1] == "; echo secret"
    assert "shell" not in calls[0][1]


def test_oracle_thick_mode_is_explicitly_unsupported():
    with pytest.raises(data.DataError) as caught:
        data._sql_engine("oracle", {"host": "db.example.test", "mode": "thick"})
    assert caught.value.code == "UNSUPPORTED_CAPABILITY"


def test_plugin_server_registration_and_bounded_execution(monkeypatch):
    class Plugin:
        def introspect(self, config):
            return {"objects": [data._object("items", [{"column": "x", "type": "integer"}])]}
        def read(self, config, mapping, columns, limit):
            return [{"x": 1}, {"x": 2}][:limit]
    monkeypatch.setattr(data, "_PLUGIN_CONNECTORS", {})
    data.register_connector("example_plugin", Plugin())
    contract, binding = dataset(["x"], ["integer"], object_name="items")
    assert data.execute_dataset("example_plugin", {}, contract, binding)["rows"] == [{"f0": 1}, {"f0": 2}]
    with pytest.raises(data.DataError):
        data.register_connector("sqlite", Plugin())


def test_empty_aggregate_count_is_zero(sqlite_file):
    contract, binding = dataset(["amount"], ["decimal"])
    contract["query"].update({"filters": {"field_id": "f0", "operator": "gt", "value": 999},
        "projection": ["count", "sum"], "aggregates": [{"aggregate_id": "count", "function": "count"},
        {"aggregate_id": "sum", "function": "sum", "field_id": "f0"}]})
    assert data.execute_dataset("sqlite", sqlite_file, contract, binding)["rows"] == [{"count": 0, "sum": None}]
