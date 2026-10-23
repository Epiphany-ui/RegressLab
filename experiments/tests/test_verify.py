"""Small completed runs catch false PASS without copying real model files."""

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from preflight.runner import digest, evaluate_cells
from preflight.verify import file_sha, verify


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False))


def get(path):
    return json.loads(path.read_text())


def save_events(root, events):
    for i, event in enumerate(events):
        event["previous_sha256"] = digest(events[i - 1]) if i else None
    (root / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))


@pytest.fixture
def completed(tmp_path):
    config = {
        "purpose": "DEVELOPMENT_SIGNAL_PILOT", "training_seeds": [11], "selection_seeds": [0, 1],
        "budgets": [1, 2], "methods": ["random", "facility"],
        "families": [{"id": name, "C": [1] * 4, "train_fractions": [1] * 4} for name in ["alpha", "beta"]],
        "signal_rule": {"min_future_flips_per_valid_chain": 1, "min_chains_with_future_flips_per_family": 1},
        "limitations": ["Synthetic verifier test only."],
    }
    audit = {"label_vocab": ["A", "B"], "dev_counts": {"DEV_SELECTOR": 4}, "train_label_counts": {"A": 5, "B": 5}, "counts_cleaned": {"train": 10, "dev": 4, "test": 0}}
    put(tmp_path / "preregistration.json", {"run_id": "test-run", "config": config, "config_sha256": digest(config)})
    put(tmp_path / "data-audit.json", audit)
    events = []

    def event(kind, **details):
        events.append({"event": kind, "time": "2026-10-23T00:00:00+00:00", "details": details})

    event("PREREGISTERED", config_sha256=digest(config))
    event("DATA_AUDITED", counts=audit["counts_cleaned"], dev_counts=audit["dev_counts"])
    summaries, cells = [], []
    ids = np.asarray(["source:0", "source:1", "source:2", "source:3"])
    gold = np.asarray(["A", "B", "A", "B"])
    for name in ["alpha", "beta"]:
        chain_id = name + "-seed11"
        directory = tmp_path / "chains" / chain_id
        directory.mkdir(parents=True)
        histories = [gold.copy(), np.asarray(["B", "B", "A", "B"]), gold.copy()] if name == "alpha" else [gold.copy(), gold.copy(), np.asarray(["B", "B", "A", "B"])]
        targets = np.asarray(["B", "B", "A", "B"]) if name == "alpha" else np.asarray(["B", "B", "B", "B"])
        versions = []
        for slot in range(4):
            model = directory / f"f{slot}.pkl"
            # Models are opaque to this verifier; never deserialize test payloads.
            identity = "shared-node" if (name, slot) in [("alpha", 3), ("beta", 2)] else f"{name}-{slot}"
            model.write_bytes(identity.encode())
            version = {"slot": f"f{slot}", "C": 1, "training_rows": 10, "model_file_sha256": file_sha(model), "train_seconds": 1.0, "converged": True, "restore_check": True}
            versions.append(version)
            if slot < 3:
                predictions = histories[slot]
                probabilities = np.asarray([[.9, .1] if p == "A" else [.1, .9] for p in predictions])
                np.savez_compressed(directory / f"f{slot}-history.npz", sample_ids=ids, predictions=predictions, probabilities=probabilities)
            event("MODEL_TRAINED", chain_id=chain_id, slot=f"f{slot}", training_rows=10, seconds=1.0, predicted_target=False)
        history = np.asarray(histories).T
        pool = np.flatnonzero(histories[2] == gold)
        selections = []
        for method, seed, order in [("random", 0, [0, 1]), ("random", 1, [1, 0]), ("facility", None, [0, 1])]:
            for budget in config["budgets"]:
                selections.append({"method": method, "seed": seed, "budget": budget, "indices": order[:budget]})
        selected = {"scope": "DEV_SELECTOR_CURRENT_CORRECT", "pool_ids": ids[pool].tolist(), "pool_indices_in_dev": pool.tolist(), "pool_gold": gold[pool].tolist(), "history": history[pool].tolist(), "selections": selections}
        put(directory / "selections.json", selected)
        summary = {"chain_id": chain_id, "family": name, "training_seed": 11, "dev_selector_count": 4, "pool_count": len(pool), "pool_label_count": len(set(gold[pool])), "versions": versions, "selection_cells": len(selections), "selection_file_sha256": file_sha(directory / "selections.json"), "all_baselines_selection_seconds": .1}
        put(directory / "history-summary.json", summary)
        summary = deepcopy(summary)
        result = evaluate_cells(selected["pool_gold"], selected["history"], targets[pool], selections)
        for cell in result:
            cell.update(chain_id=chain_id, family=name)
        cells.extend(result)
        summary.update(future_flip_count=result[0]["future_flip_count"], historically_unseen_flips=result[0]["historically_unseen"]["denominator"], repaired_then_recurred_flips=result[0]["repaired_then_recurred"]["denominator"], target_full_dev_inference_seconds=.02, target_dev_selector_accuracy=float(np.mean(targets == gold)))
        summaries.append(summary)
        event("CHAIN_SUITES_READY", chain_id=chain_id, pool_count=len(pool), cells=len(selections), selection_seconds=.1)
        np.savez_compressed(directory / "f3-target.npz", sample_ids=ids, predictions=targets)
    frozen_files = {str(p.relative_to(tmp_path)): file_sha(p) for p in tmp_path.rglob("*") if p.is_file() and p.name != "f3-target.npz"}
    frozen = {"schema_version": "cpu-preflight-matrix-v1", "scope": "DEVELOPMENT_ONLY", "target_predictions_generated": False, "config_sha256": digest(config), "chain_ids": [s["chain_id"] for s in summaries], "cell_count": len(cells), "files": frozen_files}
    put(tmp_path / "matrix-freeze.json", frozen)
    event("ALL_SUITES_FROZEN", chains=2, cell_count=len(cells), freeze_sha256=file_sha(tmp_path / "matrix-freeze.json"))
    for summary in summaries:
        event("TARGET_EVALUATED", chain_id=summary["chain_id"], future_flips=summary["future_flip_count"], seconds=.02)
    event("PILOT_COMPLETE", signal_rule_met=True, wall_seconds=5.0)
    save_events(tmp_path, events)
    aggregates = []
    for chain in summaries:
        for method in config["methods"]:
            for budget in config["budgets"]:
                subset = [c for c in cells if c["chain_id"] == chain["chain_id"] and c["method"] == method and c["budget"] == budget]
                valid = [c["recall"] for c in subset if c["recall"] is not None]
                aggregates.append({"chain_id": chain["chain_id"], "family": chain["family"], "method": method, "budget": budget, "seed_count": len(subset), "actual_size": subset[0]["actual_size"], "mean_detected": float(np.mean([c["detected"] for c in subset])), "mean_recall": float(np.mean(valid)) if valid else None, "std_recall": float(np.std(valid)) if valid else None})
    report = {"schema_version": "cpu-preflight-report-v1", "purpose": config["purpose"], "run_id": "test-run", "config_sha256": digest(config), "freeze_file_sha256": file_sha(tmp_path / "matrix-freeze.json"), "data_audit": audit, "limitations": config["limitations"], "formal_test_model_input_count": 0, "gpu_training_executed": False, "hgc_executed": False, "chains": summaries, "baseline_aggregates": aggregates, "families": {name: {"chains_with_flips": 1, "chain_count": 1} for name in ["alpha", "beta"]}, "signal_rule_met": True, "wall_seconds": 5.0}
    put(tmp_path / "report.json", report)
    put(tmp_path / "evaluation-cells.json", cells)
    return tmp_path


def mutate_report(root, mutation):
    report = get(root / "report.json")
    mutation(report)
    put(root / "report.json", report)


def reseal_test_fixture(root):
    """Model a newly produced internally inconsistent run, not file tampering."""
    report = get(root / "report.json")
    for chain in report["chains"]:
        directory = root / "chains" / chain["chain_id"]
        summary = get(directory / "history-summary.json")
        summary["selection_file_sha256"] = file_sha(directory / "selections.json")
        put(directory / "history-summary.json", summary)
        chain.update(summary)
    frozen = get(root / "matrix-freeze.json")
    frozen["files"] = {name: file_sha(root / name) for name in frozen["files"]}
    put(root / "matrix-freeze.json", frozen)
    report["freeze_file_sha256"] = file_sha(root / "matrix-freeze.json")
    put(root / "report.json", report)
    events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
    next(e for e in events if e["event"] == "ALL_SUITES_FROZEN")["details"]["freeze_sha256"] = report["freeze_file_sha256"]
    save_events(root, events)


def test_complete_run_audits_actual_model_hashes_and_all_cells(completed):
    result = verify(completed)
    assert result["status"] == "PASS"
    assert result["purpose"] == "DEVELOPMENT_ONLY"
    assert result["formal_blind_evaluation_eligible"] is False
    assert result["cells_recomputed"] == 12
    assert result["aggregates_recomputed"] == 8
    assert result["frozen_files_verified"] == 20
    assert result["cross_chain_equivalent_target_history_nodes"] == [{"target_chain": "alpha-seed11", "historical_chain": "beta-seed11", "historical_slot": "f2", "identical_model_file_sha256": file_sha(completed / "chains/alpha-seed11/f3.pkl")}]


@pytest.mark.parametrize("mutation,code", [
    (lambda r: r.update(baseline_aggregates=[]), "AGGREGATE_SET"),
    (lambda r: r["baseline_aggregates"].pop(), "AGGREGATE_SET"),
    (lambda r: r["baseline_aggregates"].append(r["baseline_aggregates"][0]), "DUPLICATE_AGGREGATE"),
    (lambda r: r["chains"][0]["versions"][3].update(model_file_sha256="0" * 64), "REPORT_CHAIN_SUMMARY"),
    (lambda r: r["chains"][0].update(pool_count=999), "REPORT_CHAIN_SUMMARY"),
    (lambda r: r["chains"][0].update(historically_unseen_flips=999), "REPORT_FLIP_SUMMARY"),
    (lambda r: r["chains"][0].update(repaired_then_recurred_flips=999), "REPORT_FLIP_SUMMARY"),
    (lambda r: r.update(signal_rule_met=False), "REPORT_SIGNAL"),
    (lambda r: r["families"]["alpha"].update(chains_with_flips=0), "REPORT_SIGNAL"),
    (lambda r: r["chains"].pop(), "REPORT_CHAIN_SET"),
])
def test_report_omissions_and_fabricated_derived_claims_cannot_pass(completed, mutation, code):
    mutate_report(completed, mutation)
    with pytest.raises(ValueError, match=code):
        verify(completed)


@pytest.mark.parametrize("mutation,code", [
    (lambda rows: rows.pop(), "SELECTION_CELL_SET"),
    (lambda rows: rows[0].update(seed=99), "SELECTION_CELL_SET"),
    (lambda rows: rows[0].update(budget=99), "SELECTION_CELL_SET"),
    (lambda rows: rows.append(rows[0]), "DUPLICATE_SELECTION_CELL"),
    (lambda rows: rows[1].update(indices=[1, 0]), "SHARED_PREFIX"),
])
def test_frozen_matrix_coverage_and_prefixes_are_not_inferred_from_existing_rows(completed, mutation, code):
    path = completed / "chains/alpha-seed11/selections.json"
    selected = get(path)
    mutation(selected["selections"])
    put(path, selected)
    reseal_test_fixture(completed)
    with pytest.raises(ValueError, match=code):
        verify(completed)


def test_model_hash_is_checked_against_bytes_not_only_report(completed):
    directory = completed / "chains/alpha-seed11"
    summary = get(directory / "history-summary.json")
    summary["versions"][3]["model_file_sha256"] = "0" * 64
    put(directory / "history-summary.json", summary)
    reseal_test_fixture(completed)
    with pytest.raises(ValueError, match="MODEL_FILE_IDENTITY"):
        verify(completed)


@pytest.mark.parametrize("event_name", ["TARGET_EVALUATED", "CHAIN_SUITES_READY"])
def test_missing_event_sets_fail_even_when_hash_chain_is_rebuilt(completed, event_name):
    events = [json.loads(line) for line in (completed / "events.jsonl").read_text().splitlines()]
    save_events(completed, [e for e in events if e["event"] != event_name])
    with pytest.raises(ValueError, match="EVENT_SET_MISMATCH"):
        verify(completed)


def test_frozen_event_must_identify_the_actual_freeze_file(completed):
    events = [json.loads(line) for line in (completed / "events.jsonl").read_text().splitlines()]
    next(e for e in events if e["event"] == "ALL_SUITES_FROZEN")["details"]["freeze_sha256"] = "0" * 64
    save_events(completed, events)
    with pytest.raises(ValueError, match="FREEZE_EVENT_MISMATCH"):
        verify(completed)


def test_target_prediction_ids_must_align_with_history(completed):
    path = completed / "chains/alpha-seed11/f3-target.npz"
    with np.load(path) as data:
        predictions, ids = data["predictions"], data["sample_ids"]
    np.savez_compressed(path, predictions=predictions, sample_ids=np.asarray(["other:0", "other:1", "other:2", "other:3"]))
    with pytest.raises(ValueError, match="TARGET_ID_ORDER"):
        verify(completed)


def test_frozen_history_probabilities_are_validated(completed):
    path = completed / "chains/alpha-seed11/f2-history.npz"
    with np.load(path) as data:
        predictions, ids, probabilities = data["predictions"], data["sample_ids"], data["probabilities"]
    probabilities[0] = [.7, .7]
    np.savez_compressed(path, predictions=predictions, sample_ids=ids, probabilities=probabilities)
    reseal_test_fixture(completed)
    with pytest.raises(ValueError, match="PROBABILITY_NORMALIZATION"):
        verify(completed)


def test_report_freeze_hash_cannot_refer_to_another_run(completed):
    mutate_report(completed, lambda r: r.update(freeze_file_sha256="0" * 64))
    with pytest.raises(ValueError, match="REPORT_FREEZE_MISMATCH"):
        verify(completed)
