"""Local Demo HTTP and durable evidence-boundary integration tests."""

import json
from copy import deepcopy
from html import escape
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from regresslab import main
from regresslab.main import create_app


ROOT = Path(__file__).resolve().parents[2]
BASE = "/api/demo"


@pytest.fixture
def app(tmp_path):
    return create_app(database_path=tmp_path / "demo.sqlite3", frontend_dist=tmp_path / "no-ui")


@pytest.fixture
def client(app):
    with TestClient(app) as connection:
        yield connection


def fixture(client, kind="basic"):
    response = client.post(f"{BASE}/fixture", params={"kind": kind})
    assert response.status_code == 201, response.text
    return response.json()


def import_parts(prefix=""):
    filenames = {
        "dataset_file": f"{prefix}dataset.jsonl",
        "old_predictions_file": f"{prefix}old-predictions.jsonl",
        "new_predictions_file": f"{prefix}new-predictions.jsonl",
    }
    files = {field: (filename, (ROOT / "examples" / filename).read_bytes(), "application/x-ndjson") for field, filename in filenames.items()}
    form = {"name": "用户自行导入", "old_model_name": "用户声明旧版", "new_model_name": "用户声明新版", "source_url": "https://example.invalid/declared", "source_version": "test-v1", "license": "synthetic engineering test only", "parser_version": "label-json-v1"}
    return files, form


def post_import(client, files=None, form=None):
    default_files, default_form = import_parts()
    return client.post(f"{BASE}/analyses", files=files or default_files, data=form or default_form)


def error_code(response):
    return response.json()["error"]["code"]


def test_health_exposes_bounded_demo_capabilities_and_security_headers(client):
    response = client.get(f"{BASE}/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["mode"] == "demo"
    assert body["limits"]["max_rows"] == 5000
    assert "paired_discovery_metrics" in body["capabilities"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-request-id"]


def test_basic_fixture_serves_hand_calculated_metrics_without_confirmation(client):
    created = fixture(client)
    response = client.get(f"{BASE}/analyses/{created['id']}")
    assert response.status_code == 200
    actual = response.json()
    assert actual == created
    metric = actual["metrics"]["discovery"]
    assert [metric[key] for key in ("n", "a", "b", "c", "d")] == [12, 6, 3, 1, 2]
    assert metric["old_accuracy"] == .75
    assert metric["new_accuracy"] == pytest.approx(7 / 12)
    assert metric["accuracy_drop"] == pytest.approx(1 / 6)
    assert actual["slices"] == []
    assert actual["metrics"]["confirmation"] is None
    assert actual["evidence_mode"] == "DESCRIPTIVE_ONLY"
    assert actual["summary"] == "INCONCLUSIVE"
    assert actual["fixture_only"] is True
    assert actual["coverage"]["old"]["ratio"] == actual["coverage"]["new"]["ratio"] == 1


def test_discovery_fixture_has_real_calculated_candidates_but_no_c_statistics(client):
    created = fixture(client, "discovery")
    assert created["slices"]
    assert created["metrics"]["discovery"]["n"] >= 30
    assert created["metrics"]["confirmation"] is None
    for item in created["slices"]:
        assert item["status"] == "PROPOSED"
        assert item["confirmation"] is None
        assert 1 <= len(item["predicate"]["all"]) <= 2
    assert created["summary_reason"] == "EVIDENCE_NOT_CONFIRMABLE"


def test_own_multipart_import_stays_declared_and_unverified(client):
    response = post_import(client)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["fixture_only"] is False
    assert result["name"] == "用户自行导入"
    for key in ("old_model", "new_model"):
        assert result[key]["provenance_status"] == "DECLARED"
        assert result[key]["identity_verified"] is False
        assert result[key]["weights_sha256"] is None
        assert result[key]["inference_config_sha256"] is None
    assert result["metrics"]["discovery"]["b"] == 3


def test_literal_prediction_import_uses_frozen_exact_parser(client):
    files, form = import_parts()
    form["parser_version"] = "label-literal-v1"
    for field in ("old_predictions_file", "new_predictions_file"):
        filename, payload, content_type = files[field]
        rows = [json.loads(line) for line in payload.decode().splitlines()]
        for row in rows:
            row["raw_response"] = row["prediction_label"]
        files[field] = (filename, "\n".join(json.dumps(row) for row in rows).encode(), content_type)
    response = post_import(client, files, form)
    assert response.status_code == 201, response.text
    assert response.json()["old_model"]["parser_version"] == "label-literal-v1"
    assert response.json()["metrics"]["discovery"]["b"] == 3


def test_missing_prediction_rejects_entire_analysis_and_preserves_failure_record(client, app):
    files, form = import_parts()
    filename, payload, content_type = files["new_predictions_file"]
    lines = payload.decode().splitlines()
    files["new_predictions_file"] = (filename, "\n".join(lines[:-1]).encode(), content_type)
    response = post_import(client, files, form)
    assert response.status_code == 422
    assert error_code(response) == "PREDICTION_COVERAGE"
    assert response.json()["error"]["details"]["coverage"]["missing_count"] == 1
    assert client.get(f"{BASE}/analyses").json()["total"] == 0
    with app.state.store.connection() as db:
        failed = db.execute("SELECT request_id, code, input_hashes FROM demo_import_failures").fetchall()
    assert len(failed) == 1
    assert failed[0][0] == response.json()["error"]["request_id"]
    assert failed[0][1] == "PREDICTION_COVERAGE"
    assert set(json.loads(failed[0][2])) == {"dataset", "old", "new"}
    assert all(len(value) == 64 for value in json.loads(failed[0][2]).values())
    assert "raw_response" not in failed[0][2]


def test_repeated_fixture_posts_create_immutable_records_with_distinct_ids(client):
    first, second = fixture(client), fixture(client)
    assert first["id"] != second["id"]
    assert first["dataset"]["content_sha256"] == second["dataset"]["content_sha256"]
    assert first["old_model"]["prediction_content_sha256"] == second["old_model"]["prediction_content_sha256"]
    assert client.get(f"{BASE}/analyses/{first['id']}").json() == first
    listed = client.get(f"{BASE}/analyses", params={"page": 1, "page_size": 1}).json()
    assert listed["total"] == 2 and len(listed["items"]) == 1
    assert client.get(f"{BASE}/analyses/{first['id']}").json()["content_sha256"] == first["content_sha256"]


def test_cases_paginate_negative_flips_without_hidden_role_rows(client):
    created = fixture(client)
    route = f"{BASE}/analyses/{created['id']}/cases"
    first = client.get(route, params={"outcome": "negative_flip", "page": 1, "page_size": 2}).json()
    second = client.get(route, params={"outcome": "negative_flip", "page": 2, "page_size": 2}).json()
    assert first["total"] == second["total"] == 3
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    ids = [case["sample_id"] for case in first["items"] + second["items"]]
    assert len(set(ids)) == 3
    assert all(case["outcome"] == "negative_flip" for case in first["items"] + second["items"])
    all_cases = client.get(route, params={"page_size": 100}).json()
    assert all_cases["total"] == 12
    assert all("raw_response" not in row for row in all_cases["items"])


@pytest.mark.parametrize("query", ["role=CONFIRM", "role=AUDIT", "role=DISCOVERY&role=CONFIRM", "role=DISCOVERY&role=AUDIT", "role=CONFIRM&role=DISCOVERY", "role=AUDIT&role=DISCOVERY"])
def test_c_and_a_cases_are_forbidden_even_with_repeated_role_query(client, query):
    created = fixture(client)
    response = client.get(f"{BASE}/analyses/{created['id']}/cases?{query}")
    assert response.status_code == 403
    assert "items" not in response.json()


@pytest.mark.parametrize("format", ["json", "html"])
def test_exports_exclude_private_inputs_hidden_samples_and_all_raw_responses(client, app, format):
    created = fixture(client)
    stored = app.state.store.load(created["id"])
    hidden = [sample for sample in stored["private"]["dataset"]["samples"] if sample["role"] in ("CONFIRM", "AUDIT")]
    assert hidden, "fixture must actually contain hidden rows for this boundary test"
    response = client.get(f"{BASE}/analyses/{created['id']}/export", params={"format": format})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert f".{format}" in response.headers["content-disposition"]
    body = response.text
    for sample in hidden:
        assert sample["text"] not in body
        assert sample["sample_id"] not in body
    for key in ("private", "input_texts", "raw_response"):
        assert f'"{key}"' not in body
    for predictions in (stored["private"]["old_predictions"], stored["private"]["new_predictions"]):
        for row in predictions["rows"]:
            assert row["raw_response"] not in body
    if format == "json":
        report = response.json()
        assert report["report_schema"] == "regresslab-demo-report-v1"
        assert len(report["discovery_cases"]) == 12
    else:
        assert "default-src 'none'" in response.headers["content-security-policy"]


def test_hostile_d_text_is_escaped_in_exported_html(client, app):
    created = fixture(client)
    stored = app.state.store.load(created["id"])
    target = next(sample for sample in stored["private"]["dataset"]["samples"] if sample["role"] == "DISCOVERY")
    files, form = import_parts()
    rows = [json.loads(line) for line in files["dataset_file"][1].decode().splitlines()]
    hostile = '<script>alert("D-XSS")</script><img src=x onerror="alert(1)">'
    for row in rows:
        if row["sample_id"] == target["sample_id"]:
            row["text"] = hostile
    files["dataset_file"] = ("dataset.jsonl", "\n".join(json.dumps(row, ensure_ascii=False) for row in rows).encode(), "application/x-ndjson")
    imported = post_import(client, files, form)
    assert imported.status_code == 201, imported.text
    html = client.get(f"{BASE}/analyses/{imported.json()['id']}/export?format=html")
    assert hostile not in html.text
    assert escape(hostile, quote=True) in html.text
    assert "<script>" not in html.text
    assert 'default-src \'none\'' in html.headers["content-security-policy"]


def test_database_reopen_preserves_content_and_source_hashes(tmp_path):
    path = tmp_path / "durable.sqlite3"
    with TestClient(create_app(database_path=path, frontend_dist=tmp_path / "absent")) as first:
        created = fixture(first)
    with TestClient(create_app(database_path=path, frontend_dist=tmp_path / "absent")) as reopened:
        result = reopened.get(f"{BASE}/analyses/{created['id']}")
        assert result.status_code == 200
        assert result.json() == created
        assert reopened.get(f"{BASE}/analyses").json()["total"] == 1


def test_tampered_stored_payload_stops_reads_with_storage_error(client, app):
    created = fixture(client)
    record = deepcopy(app.state.store.load(created["id"]))
    record["public"]["metrics"]["discovery"]["b"] = 999
    with app.state.store.connection() as db:
        db.execute("UPDATE demo_analyses SET payload = ? WHERE id = ?", (json.dumps(record), created["id"]))
    response = client.get(f"{BASE}/analyses/{created['id']}")
    assert response.status_code == 500
    assert error_code(response) == "STORAGE_ERROR"
    assert "999" not in response.text


@pytest.mark.parametrize("payload", ['{"n":NaN}', '{"n":', '{"text":"\\ud800"}'])
def test_corrupted_or_noncanonical_storage_is_a_storage_error(client, app, payload):
    created = fixture(client)
    with app.state.store.connection() as db:
        db.execute("UPDATE demo_analyses SET payload = ? WHERE id = ?", (payload, created["id"]))
    response = client.get(f"{BASE}/analyses/{created['id']}")
    assert response.status_code == 500
    assert error_code(response) == "STORAGE_ERROR"


def test_confirmation_refusal_and_unknown_id_are_explicit(client):
    created = fixture(client)
    response = client.post(f"{BASE}/analyses/{created['id']}/confirm")
    assert response.status_code == 409
    assert error_code(response) == "EVIDENCE_NOT_CONFIRMABLE"
    unknown = client.get(f"{BASE}/analyses/{uuid4()}")
    assert unknown.status_code == 404
    assert error_code(unknown) == "NOT_FOUND"
    assert client.get(f"{BASE}/analyses/{created['id']}").json()["metrics"]["confirmation"] is None


def test_invalid_form_validation_does_not_echo_submitted_secret_values(client):
    files, form = import_parts()
    secret = "PRIVATE_FORM_VALUE_SHOULD_NOT_BE_ECHOED"
    form["parser_version"] = secret
    response = post_import(client, files, form)
    assert response.status_code == 422
    assert error_code(response) == "INVALID_REQUEST"
    assert secret not in response.text
    assert "dataset_file" not in response.text  # no uploaded content or file-body dump


@pytest.mark.parametrize("field", ["raw_response", "gold_label"])
def test_failed_hidden_row_validation_never_echoes_hidden_text_gold_or_raw(client, app, field):
    created = fixture(client)
    hidden = next(sample for sample in app.state.store.load(created["id"])["private"]["dataset"]["samples"] if sample["role"] == "CONFIRM")
    marker = "PRIVATE_CONFIRM_VALUE_MUST_NOT_BE_RETURNED"
    files, form = import_parts()
    part = "new_predictions_file" if field == "raw_response" else "dataset_file"
    filename, payload, content_type = files[part]
    rows = [json.loads(line) for line in payload.decode().splitlines()]
    for row in rows:
        if row["sample_id"] == hidden["sample_id"]:
            row[field] = json.dumps({"label": row["prediction_label"], "secret": marker}) if field == "raw_response" else marker
    files[part] = (filename, "\n".join(json.dumps(row, ensure_ascii=False) for row in rows).encode(), content_type)
    response = post_import(client, files, form)
    assert response.status_code == 422
    assert marker not in response.text
    assert hidden["text"] not in response.text
    assert "traceback" not in response.text.lower()
    assert client.get(f"{BASE}/analyses").json()["total"] == 1  # only the setup fixture survived


def test_per_file_limit_is_enforced_without_large_test_payload(client, app, monkeypatch):
    monkeypatch.setattr(main, "MAX_FILE_BYTES", 128)
    files, form = import_parts()
    files["dataset_file"] = ("oversize.jsonl", b"x" * 129, "application/x-ndjson")
    response = post_import(client, files, form)
    assert response.status_code in (413, 422)
    assert error_code(response) == "FILE_TOO_LARGE"
    assert response.json()["error"]["details"]["limit"] == 128
    assert client.get(f"{BASE}/analyses").json()["total"] == 0
    with app.state.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM demo_import_failures").fetchone()[0] == 1


def test_total_request_limit_checks_declared_and_actual_streamed_bytes(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_BODY_BYTES", 128)
    declared = client.post(f"{BASE}/fixture", content=b"x", headers={"Content-Length": "129"})
    assert declared.status_code == 413
    assert error_code(declared) == "UPLOAD_TOO_LARGE"
    # Generator request has chunked transfer; its actual bytes exceed the limit.
    streamed = client.post(f"{BASE}/fixture", content=iter([b"x" * 64, b"y" * 65]))
    assert streamed.status_code == 413
    assert error_code(streamed) == "UPLOAD_TOO_LARGE"
    assert client.get(f"{BASE}/analyses").json()["total"] == 0


@pytest.mark.parametrize("headers", [{"Origin": "https://untrusted.example"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}])
def test_cross_site_writes_are_rejected(client, headers):
    response = client.post(f"{BASE}/fixture", headers=headers)
    assert response.status_code == 403
    assert error_code(response) == "ORIGIN_REJECTED"
    assert client.get(f"{BASE}/analyses").json()["total"] == 0


def test_same_origin_write_is_allowed_and_untrusted_host_is_rejected(client):
    response = client.post(f"{BASE}/fixture", headers={"Origin": "http://testserver"})
    assert response.status_code == 201
    hostile = client.get(f"{BASE}/health", headers={"Host": "untrusted.example"})
    assert hostile.status_code == 400
