"""Evidence for the Demo's meaningful data and statistical boundaries."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from regresslab.domain import (
    DEFAULT_CONFIG, DomainError, analyze, hash_json, parse_jsonl,
    surface_features, validate_dataset, validate_predictions,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE = {"name": "Engineering fixture", "version": "1", "source_url": "https://example.invalid/fixture", "license": "fixture-only", "fixture_only": True}


def group_for(role, serial):
    for attempt in range(1000):
        group = f"test:{serial}:{attempt}"
        value = int(hashlib.sha256(f"split-v1|42|{group}".encode()).hexdigest()[:16], 16)
        actual = "DISCOVERY" if value < 2**63 else "CONFIRM" if value < 3 * 2**62 else "AUDIT"
        if actual == role:
            return group
    raise AssertionError("could not construct deterministic test group")


def sample(sample_id, text, label="A", partition="test", group=None):
    return {"sample_id": sample_id, "group_id": group or sample_id, "source_partition": partition, "text": text, "gold_label": label, "locale": "zh-CN"}


def input_rows(n=12, with_hidden=True):
    rows = [sample("train:a", "训练甲类文本", "A", "train"), sample("train:b", "训练乙类文本", "B", "train")]
    rows.extend(sample(f"fixture:{i:02}", f"请设置第{i}个闹钟", group=group_for("DISCOVERY", i)) for i in range(1, n + 1))
    if with_hidden:
        rows.extend([sample("secret:c", "CONFIRM_SECRET", group=group_for("CONFIRM", "c")), sample("secret:a", "AUDIT_SECRET", group=group_for("AUDIT", "a"))])
    return rows


def prediction_rows(dataset, predictions=None, parser="label-json-v1", run_id=None):
    run_id = run_id or str(uuid4())
    result = []
    for row in dataset["samples"]:
        if row["role"] not in ("DISCOVERY", "CONFIRM"):
            continue
        label = predictions.get(row["sample_id"], "A") if predictions else "A"
        result.append({"sample_id": row["sample_id"], "prediction_label": label, "run_id": run_id, "raw_response": json.dumps({"label": label}) if parser == "label-json-v1" else label})
    return result


def fixture_analysis():
    dataset = validate_dataset(input_rows(), SOURCE)
    fixture = parse_jsonl((ROOT / "contracts/fixtures/paired-cases.jsonl").read_text())
    old_labels = {row["sample_id"]: row["old_prediction_label"] for row in fixture}
    new_labels = {row["sample_id"]: row["new_prediction_label"] for row in fixture}
    old = validate_predictions(prediction_rows(dataset, old_labels), dataset)
    new = validate_predictions(prediction_rows(dataset, new_labels), dataset)
    return dataset, old, new, analyze(dataset, old, new)


def test_fixture_metrics_match_hand_calculation_and_do_not_claim_confirmation():
    _, _, _, result = fixture_analysis()
    expected = json.loads((ROOT / "contracts/fixtures/paired-expected.json").read_text())
    actual = result["metrics"]["discovery"]
    for key in ("n", "a", "b", "c", "d", "old_accuracy", "new_accuracy", "accuracy_drop", "negative_flip_rate", "positive_flip_rate", "old_correct_regression_rate"):
        assert actual[key] == pytest.approx(expected[key])
    assert actual["old_macro_f1"] == pytest.approx(3 / 7)
    assert actual["new_macro_f1"] == pytest.approx(7 / 19)
    assert actual["per_label_support"] == {"A": 12, "B": 0}
    assert result["slices"] == []  # production threshold is 30, never reduced for Demo.
    assert result["metrics"]["confirmation"] is None
    assert result["evidence_mode"] == "DESCRIPTIVE_ONLY"
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["summary_reason"] == "EVIDENCE_NOT_CONFIRMABLE"
    assert result["confusion_changes"]["cells"] == [
        {"gold_label": "A", "prediction_label": "A", "old_count": 9, "new_count": 7, "delta": -2},
        {"gold_label": "A", "prediction_label": "B", "old_count": 3, "new_count": 5, "delta": 2},
    ]


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":{"y":1,"y":2}}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}', '{"x":1}\n\n{"x":2}'])
def test_jsonl_rejects_ambiguous_or_nonfinite_content(text):
    with pytest.raises(DomainError):
        parse_jsonl(text)


def test_jsonl_accepts_crlf_and_keeps_unicode_line_separator_inside_text():
    assert parse_jsonl('{"text":"a\u2028b"}\r\n') == [{"text": "a\u2028b"}]


def test_dataset_transitive_components_reject_cross_partition_leakage():
    rows = input_rows(with_hidden=False)
    # train:a -> another same group -> another same normalized text -> TEST.
    rows.append(sample("bridge", "Ａ　Ｂ", "A", "train", "train:a"))
    rows.append(sample("leak", "A B", "A", "test", "other-group"))
    with pytest.raises(DomainError, match="连通组件") as error:
        validate_dataset(rows, SOURCE)
    assert error.value.code == "SPLIT_LEAKAGE"


def test_conflicting_gold_and_unknown_labels_are_rejected():
    rows = input_rows()
    rows.append(sample("conflict", rows[2]["text"], "B", group=rows[2]["group_id"]))
    with pytest.raises(DomainError) as error:
        validate_dataset(rows, SOURCE)
    assert error.value.code == "CONFLICTING_GOLD"
    rows = input_rows()
    rows[2]["gold_label"] = "UNSEEN"
    with pytest.raises(DomainError) as error:
        validate_dataset(rows, SOURCE)
    assert error.value.code == "UNSEEN_LABEL"


@pytest.mark.parametrize("extra", [{"role": "DISCOVERY"}, {"metadata": {"worker_id": "private"}}, {"gold_label": ""}])
def test_input_contract_cannot_bypass_roles_or_import_private_metadata(extra):
    rows = input_rows()
    rows[2].update(extra)
    with pytest.raises(DomainError):
        validate_dataset(rows, SOURCE)


def test_hashes_are_order_stable_and_confirmation_identity_ignores_source_names():
    rows = input_rows()
    first = validate_dataset(rows, SOURCE)
    second = validate_dataset(list(reversed(rows)), {**SOURCE, "name": "re-uploaded name"})
    assert first["manifest"]["evaluation_data_sha256"] == second["manifest"]["evaluation_data_sha256"]
    assert first["manifest"]["content_sha256"] != second["manifest"]["content_sha256"]
    assert hash_json({"b": 2, "a": 1}) == hash_json({"a": 1, "b": 2})
    assert first["manifest"]["counts"] == {"TRAIN": 2, "DEV": 0, "DISCOVERY": 12, "CONFIRM": 1, "AUDIT": 1}


def test_normalized_duplicates_stay_in_one_component_and_keep_original_text():
    rows = input_rows()
    rows.extend([sample("same:1", "Ａ　Ｂ", "A", "train", "group:z"), sample("same:2", "A B", "A", "train", "group:a")])
    dataset = validate_dataset(rows, SOURCE)
    twins = [row for row in dataset["samples"] if row["sample_id"].startswith("same:")]
    assert [row["component_key"] for row in twins] == ["group:a", "group:a"]
    assert twins[0]["text"] == "Ａ　Ｂ"
    assert twins[0]["text_sha256"] == twins[1]["text_sha256"]


@pytest.mark.parametrize("failure", ["missing", "duplicate", "extra", "gold", "unknown", "raw_mismatch", "raw_empty", "mixed_run"])
def test_prediction_validation_rejects_bad_execution_instead_of_changing_metric_denominator(failure):
    dataset = validate_dataset(input_rows(), SOURCE)
    rows = prediction_rows(dataset)
    if failure == "missing":
        rows.pop()
    elif failure == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif failure == "extra":
        rows.append({**rows[0], "sample_id": "secret:a"})
    elif failure == "gold":
        rows[0]["gold_label"] = "A"
    elif failure == "unknown":
        rows[0]["prediction_label"] = "UNKNOWN"
    elif failure == "raw_mismatch":
        rows[0]["raw_response"] = '{"label":"B"}'
    elif failure == "raw_empty":
        rows[0]["raw_response"] = ""
    elif failure == "mixed_run":
        rows[0]["run_id"] = str(uuid4())
    with pytest.raises(DomainError) as error:
        validate_predictions(rows, dataset)
    assert "coverage" in error.value.details
    if failure == "raw_mismatch":
        assert error.value.code == "RAW_LABEL_MISMATCH"


def test_literal_parser_is_exact_and_json_raw_rejects_duplicate_or_extra_keys():
    dataset = validate_dataset(input_rows(), SOURCE)
    rows = prediction_rows(dataset, parser="label-literal-v1")
    assert validate_predictions(rows, dataset, "label-literal-v1")["coverage"]["ratio"] == 1
    rows[0]["raw_response"] = " A "
    with pytest.raises(DomainError):
        validate_predictions(rows, dataset, "label-literal-v1")
    for raw in ('{"label":"A","label":"A"}', '{"label":"A","reason":"extra"}'):
        rows = prediction_rows(dataset)
        rows[0]["raw_response"] = raw
        with pytest.raises(DomainError):
            validate_predictions(rows, dataset)


def test_discovery_does_not_use_hidden_gold_or_prediction_outcomes():
    dataset = validate_dataset(input_rows(n=40), SOURCE)
    old = validate_predictions(prediction_rows(dataset), dataset)
    new_labels = {row["sample_id"]: "B" for row in dataset["samples"] if row["role"] == "DISCOVERY"}
    new = validate_predictions(prediction_rows(dataset, new_labels), dataset)
    before = analyze(dataset, old, new)
    hidden = next(row for row in dataset["samples"] if row["role"] == "CONFIRM")
    # Role isolation is checked without changing the already-frozen dataset identity.
    hidden["gold_label"] = "B"
    hidden["text"] = "DIFFERENT_CONFIRM_SECRET"
    hidden["features"] = {"arbitrary_hidden_feature": "must not enumerate"}
    changed_rows = deepcopy(new["rows"])
    for row in changed_rows:
        if row["sample_id"] == hidden["sample_id"]:
            row["prediction_label"] = "B"
            row["raw_response"] = '{"label":"B"}'
    after = analyze(dataset, old, validate_predictions(changed_rows, dataset))
    for field in ("candidate_set_hash", "metrics", "slices", "confusion_changes", "discovery_cases"):
        assert before[field] == after[field]
    assert before["slices"]  # ≥30 D rows legitimately exercise discovery.
    assert all(item["status"] == "PROPOSED" and item["confirmation"] is None for item in before["slices"])
    exported = json.dumps(after)
    assert "CONFIRM_SECRET" not in exported
    assert "AUDIT_SECRET" not in exported
    assert "secret:c" not in exported and "secret:a" not in exported


def test_analysis_rejects_prediction_set_for_another_dataset_even_when_ids_match():
    dataset, old, new, _ = fixture_analysis()
    changed_rows = input_rows()
    changed_rows[2]["text"] = "修改后数据版本"
    another = validate_dataset(changed_rows, SOURCE)
    with pytest.raises(DomainError) as error:
        analyze(another, old, new)
    assert error.value.code == "SCOPE_MISMATCH"


def test_no_discovery_scope_and_zero_old_correct_denominator():
    rows = input_rows(n=0)
    dataset = validate_dataset(rows, SOURCE)
    with pytest.raises(DomainError) as error:
        validate_predictions([], dataset)
    assert error.value.code == "INVALID_SCOPE"
    dataset = validate_dataset(input_rows(), SOURCE)
    wrong = {row["sample_id"]: "B" for row in dataset["samples"] if row["role"] == "DISCOVERY"}
    old = validate_predictions(prediction_rows(dataset, wrong), dataset)
    new = validate_predictions(prediction_rows(dataset, wrong), dataset)
    assert analyze(dataset, old, new)["metrics"]["discovery"]["old_correct_regression_rate"] is None


def test_production_defaults_and_input_feature_contract_match_design():
    assert DEFAULT_CONFIG == json.loads((ROOT / "contracts/default-analysis-config.json").read_text())
    features = surface_features("  不要　Ａ１２？  ", "zh-CN")
    assert features == {"locale": "zh-CN", "length_bin": "1-8", "has_negation": True, "has_digit": True, "has_question_mark": True}
    assert surface_features("cannot play", "en-US")["has_negation"] is True
    assert surface_features("notebook", "en-US")["has_negation"] is False


@pytest.mark.parametrize("partition", [[], {}, True, 1, None])
def test_partition_edge_types_are_domain_errors_not_unhandled_type_errors(partition):
    rows = input_rows()
    rows[2]["source_partition"] = partition
    with pytest.raises(DomainError) as error:
        validate_dataset(rows, SOURCE)
    assert error.value.code == "INVALID_SAMPLE"


def test_invalid_prediction_identifier_does_not_echo_nested_input_values():
    dataset = validate_dataset(input_rows(), SOURCE)
    rows = prediction_rows(dataset)
    rows[0]["sample_id"] = {"private": "MUST_NOT_APPEAR_IN_DETAILS"}
    with pytest.raises(DomainError) as error:
        validate_predictions(rows, dataset)
    assert "MUST_NOT_APPEAR_IN_DETAILS" not in json.dumps(error.value.details)


def test_pair_cannot_reuse_one_execution_as_both_versions():
    dataset, old, _, _ = fixture_analysis()
    with pytest.raises(DomainError) as error:
        analyze(dataset, old, old)
    assert error.value.code == "PREDICTION_RUN_REUSED"
