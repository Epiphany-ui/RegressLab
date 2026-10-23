import json

import numpy as np
import pytest

from preflight.runner import digest, evaluate_cells, nested_train_indices, verify_freeze, write_json


def test_train_sampling_is_nested_and_independent_of_input_order():
    rows = [{"sample_id": f"{label}:{i}", "gold_label": label, "role": "TRAIN"} for label in ["A", "B"] for i in range(20)]
    sets = [{rows[i]["sample_id"] for i in nested_train_indices(rows, fraction, 11)} for fraction in [0.4, 0.6, 0.8, 1]]
    assert [len(s) for s in sets] == [16, 24, 32, 40]
    assert all(a < b for a, b in zip(sets, sets[1:]))
    other = {rows[i]["sample_id"] for i in nested_train_indices(rows, 0.4, 23)}
    assert other != sets[0]
    reversed_rows = rows[::-1]
    assert {reversed_rows[i]["sample_id"] for i in nested_train_indices(reversed_rows, 0.4, 11)} == sets[0]


def test_non_train_rows_cannot_enter_sampler():
    with pytest.raises(ValueError, match="TRAIN_ONLY_REQUIRED"):
        nested_train_indices([{"sample_id": "dev", "role": "DEV_SELECTOR", "gold_label": "A"}], 1, 42)


def test_exact_repaired_and_novel_target_metrics():
    history = np.array([["A", "B", "A"], ["A", "A", "A"], ["A", "B", "A"], ["A", "A", "A"]])
    targets = np.array(["B", "B", "A", "A"])
    cells = [{"method": "example", "seed": None, "budget": 2, "indices": [0, 3]}]
    result = evaluate_cells(["A"] * 4, history, targets, cells)[0]
    assert result["future_flip_count"] == 2
    assert result["detected"] == 1
    assert result["recall"] == result["precision"] == 0.5
    assert result["enrichment"] == 1
    assert result["repaired_then_recurred"] == {"denominator": 1, "detected": 1, "recall": 1}
    assert result["historically_unseen"] == {"denominator": 1, "detected": 0, "recall": 0}


def test_zero_target_flips_are_retained_with_na():
    cell = {"method": "x", "seed": None, "budget": 20, "indices": [0]}
    result = evaluate_cells(["A"], [["A", "A", "A"]], ["A"], [cell])[0]
    assert result["recall"] is None
    assert result["enrichment"] is None
    assert result["precision"] == 0
    assert result["actual_size"] == 1
    assert result["na_reason"] == "NO_TARGET_FLIPS"


def test_invalid_suite_or_wrong_reference_pool_rejected():
    with pytest.raises(ValueError, match="INVALID_SELECTION"):
        evaluate_cells(["A"], [["A", "A", "A"]], ["B"], [{"budget": 20, "indices": [0, 0]}])
    with pytest.raises(ValueError, match="INVALID_EVALUATION_SCOPE"):
        evaluate_cells(["A"], [["A", "A", "B"]], ["B"], [])


def test_freeze_detects_actual_file_changes(tmp_path):
    hash_value = write_json(tmp_path / "selections.json", {"selected": ["a"]})
    write_json(tmp_path / "matrix-freeze.json", {"files": {"selections.json": hash_value}})
    verify_freeze(tmp_path)
    (tmp_path / "selections.json").write_text(json.dumps({"selected": ["b"]}))
    with pytest.raises(ValueError, match="FROZEN_INPUT_CHANGED"):
        verify_freeze(tmp_path)


def test_published_files_cannot_be_overwritten(tmp_path):
    write_json(tmp_path / "frozen.json", {"a": 1})
    with pytest.raises(FileExistsError):
        write_json(tmp_path / "frozen.json", {"a": 2})
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
