"""Audit frozen development-pilot artifacts; never select or infer again.

Scoring is rerun through the pilot's scorer, not an independent implementation
of its formulas. This checks artifact consistency, not formal blind eligibility.
"""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np

from .runner import digest, evaluate_cells, verify_freeze

SEEDED_METHODS = {"random", "stratified", "past-flip", "kcenter"}
DETERMINISTIC_METHODS = {"ref-maxprob", "ref-margin", "ref-entropy", "ref-deepgini", "facility"}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("NONFINITE_JSON_NUMBER")

    return json.loads(path.read_text(), object_pairs_hook=unique, parse_constant=invalid)


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def indexed(items, fields, code):
    result = {}
    for item in items:
        key = tuple(item[field] for field in fields)
        require(key not in result, code)
        result[key] = item
    return result


def integer_values(values, minimum, code):
    require(isinstance(values, list) and bool(values), code)
    require(all(type(value) is int and value >= minimum for value in values), code)
    require(len(set(values)) == len(values), code)


def load_predictions(path, labels, expected_count, *, probabilities_required):
    with np.load(path, allow_pickle=False) as stored:
        require(set(stored.files) == ({"predictions", "sample_ids", "probabilities"} if probabilities_required else {"predictions", "sample_ids"}), "PREDICTION_ARRAY_FIELDS")
        predictions = stored["predictions"]
        ids = stored["sample_ids"]
        require(predictions.shape == ids.shape == (expected_count,), "PREDICTION_ARRAY_SHAPE")
        require(ids.dtype.kind == predictions.dtype.kind == "U", "PREDICTION_ARRAY_TYPE")
        id_list = ids.tolist()
        require(all(id_list) and id_list == sorted(set(id_list), key=lambda value: value.encode("utf-8")), "PREDICTION_IDS_INVALID")
        require(set(predictions.tolist()) <= set(labels), "PREDICTION_LABEL_INVALID")
        if probabilities_required:
            probabilities = stored["probabilities"]
            require(probabilities.shape == (expected_count, len(labels)), "PROBABILITY_SHAPE")
            require(np.isfinite(probabilities).all() and np.all((probabilities >= 0) & (probabilities <= 1)), "PROBABILITY_INVALID")
            require(np.allclose(probabilities.sum(axis=1), 1, rtol=0, atol=1e-8), "PROBABILITY_NORMALIZATION")
            require(np.array_equal(np.asarray(labels)[probabilities.argmax(axis=1)], predictions), "PROBABILITY_LABEL_MISMATCH")
        return ids, predictions


def verify(output: Path) -> dict:
    output = Path(output)
    frozen = read_json(output / "matrix-freeze.json")
    require(frozen["schema_version"] == "cpu-preflight-matrix-v1" and frozen["scope"] == "DEVELOPMENT_ONLY" and frozen["target_predictions_generated"] is False, "FREEZE_SCOPE_MISMATCH")
    require(all(not Path(name).is_absolute() and ".." not in Path(name).parts for name in frozen["files"]), "UNSAFE_FROZEN_PATH")
    # Verify before trusting the preregistration or any chain summaries.
    verify_freeze(output)
    prereg = read_json(output / "preregistration.json")
    config = prereg["config"]
    audit = read_json(output / "data-audit.json")
    require(config["purpose"] == "DEVELOPMENT_SIGNAL_PILOT", "PURPOSE_MISMATCH")
    require(digest(config) == prereg["config_sha256"] == frozen["config_sha256"], "CONFIG_HASH_MISMATCH")
    integer_values(config["training_seeds"], 0, "INVALID_TRAINING_SEEDS")
    integer_values(config["selection_seeds"], 0, "INVALID_SELECTION_SEEDS")
    integer_values(config["budgets"], 1, "INVALID_BUDGETS")
    methods = config["methods"]
    require(bool(methods) and len(methods) == len(set(methods)) and set(methods) <= SEEDED_METHODS | DETERMINISTIC_METHODS, "INVALID_METHODS")
    families = {family["id"]: family for family in config["families"]}
    require(bool(families) and len(families) == len(config["families"]), "INVALID_FAMILIES")
    expected_chains = [(f"{family['id']}-seed{seed}", family, seed) for family in config["families"] for seed in config["training_seeds"]]
    chain_ids = [chain_id for chain_id, _, _ in expected_chains]
    require(all(re.fullmatch(r"[A-Za-z0-9_-]+", chain_id) for chain_id in chain_ids) and len(set(chain_ids)) == len(chain_ids), "INVALID_CHAIN_IDS")
    require(frozen["chain_ids"] == chain_ids, "FROZEN_CHAIN_SET_MISMATCH")
    expected_files = {"preregistration.json", "data-audit.json"}
    for chain_id in chain_ids:
        expected_files.update(f"chains/{chain_id}/{name}" for name in ["history-summary.json", "selections.json", *[f"f{i}.pkl" for i in range(4)], *[f"f{i}-history.npz" for i in range(3)]])
    require(set(frozen["files"]) == expected_files, "FROZEN_FILE_SET_MISMATCH")
    expected_keys = {(method, seed, budget) for method in methods for seed in (config["selection_seeds"] if method in SEEDED_METHODS else [None]) for budget in config["budgets"]}
    require(type(frozen["cell_count"]) is int and frozen["cell_count"] == len(chain_ids) * len(expected_keys), "FROZEN_CELL_COUNT_MISMATCH")
    report = read_json(output / "report.json")
    require(report["schema_version"] == "cpu-preflight-report-v1" and report["purpose"] == config["purpose"] and report["run_id"] == prereg["run_id"], "REPORT_IDENTITY_MISMATCH")
    require(report["config_sha256"] == digest(config) and report["freeze_file_sha256"] == file_sha(output / "matrix-freeze.json"), "REPORT_FREEZE_MISMATCH")
    require(report["data_audit"] == audit and report["limitations"] == config["limitations"], "REPORT_AUDIT_MISMATCH")
    require(report["formal_test_model_input_count"] == 0 and report["gpu_training_executed"] is False and report["hgc_executed"] is False, "REPORT_SCOPE_MISMATCH")
    chains = indexed(report["chains"], ["chain_id"], "DUPLICATE_REPORT_CHAIN")
    require(set(chains) == {(chain_id,) for chain_id in chain_ids}, "REPORT_CHAIN_SET_MISMATCH")
    cells, versions, summaries = [], [], {}
    labels = audit["label_vocab"]
    dev_count = audit["dev_counts"]["DEV_SELECTOR"]
    for chain_id, family, seed in expected_chains:
        directory = output / "chains" / chain_id
        summary = read_json(directory / "history-summary.json")
        chain = chains[(chain_id,)]
        require(all(chain.get(key) == value for key, value in summary.items()), "REPORT_CHAIN_SUMMARY_MISMATCH")
        require(summary["chain_id"] == chain_id and summary["family"] == family["id"] and summary["training_seed"] == seed and summary["dev_selector_count"] == dev_count, "CHAIN_IDENTITY_MISMATCH")
        require([v["slot"] for v in summary["versions"]] == ["f0", "f1", "f2", "f3"], "VERSION_SET_MISMATCH")
        history_ids, history_labels = None, []
        for slot, version in enumerate(summary["versions"]):
            model_hash = file_sha(directory / f"f{slot}.pkl")
            require(version["model_file_sha256"] == model_hash, "MODEL_FILE_IDENTITY_MISMATCH")
            require(version["C"] == family["C"][slot], "MODEL_CONFIG_MISMATCH")
            require(version["converged"] is True and version["restore_check"] is True, "MODEL_GATE_FAILED")
            expected_rows = sum(count if family["train_fractions"][slot] == 1 else max(1, int(family["train_fractions"][slot] * count)) for count in audit["train_label_counts"].values())
            require(version["training_rows"] == expected_rows, "TRAINING_ROW_COUNT_MISMATCH")
            versions.append({"chain_id": chain_id, "slot": f"f{slot}", "model_file_sha256": model_hash})
            if slot < 3:
                ids, prediction = load_predictions(directory / f"f{slot}-history.npz", labels, dev_count, probabilities_required=True)
                require(history_ids is None or np.array_equal(ids, history_ids), "HISTORY_ID_ORDER_MISMATCH")
                history_ids = ids
                history_labels.append(prediction)
        selected = read_json(directory / "selections.json")
        require(selected["scope"] == "DEV_SELECTOR_CURRENT_CORRECT", "SELECTION_SCOPE_MISMATCH")
        require(file_sha(directory / "selections.json") == summary["selection_file_sha256"], "SELECTION_HASH_MISMATCH")
        selection_index = indexed(selected["selections"], ["method", "seed", "budget"], "DUPLICATE_SELECTION_CELL")
        require(set(selection_index) == expected_keys and summary["selection_cells"] == len(expected_keys), "SELECTION_CELL_SET_MISMATCH")
        pool = selected["pool_indices_in_dev"]
        require(all(type(i) is int and 0 <= i < dev_count for i in pool) and pool == sorted(set(pool)), "POOL_INDICES_INVALID")
        pool_index = np.asarray(pool, dtype=int)
        require(selected["pool_ids"] == history_ids[pool_index].tolist(), "POOL_ID_MAPPING_MISMATCH")
        require(summary["pool_count"] == len(pool) == len(selected["pool_gold"]) and summary["pool_label_count"] == len(set(selected["pool_gold"])), "POOL_COUNT_MISMATCH")
        require(set(selected["pool_gold"]) <= set(labels), "POOL_GOLD_LABEL_INVALID")
        cached_history = np.asarray(history_labels).T[pool_index]
        require(selected["history"] == cached_history.tolist(), "POOL_HISTORY_MISMATCH")
        for selection in selected["selections"]:
            require(type(selection["budget"]) is int and (selection["seed"] is None or type(selection["seed"]) is int) and all(type(i) is int for i in selection["indices"]), "SELECTION_TYPES_INVALID")
        for method in methods:
            if method == "stratified":
                continue  # Proportional quotas are intentionally recomputed per budget.
            for selection_seed in config["selection_seeds"] if method in SEEDED_METHODS else [None]:
                largest = selection_index[(method, selection_seed, max(config["budgets"]))]["indices"]
                require(all(selection_index[(method, selection_seed, budget)]["indices"] == largest[:min(budget, len(pool))] for budget in config["budgets"]), "SHARED_PREFIX_MISMATCH")
        target_ids, full_target = load_predictions(directory / "f3-target.npz", labels, dev_count, probabilities_required=False)
        require(np.array_equal(target_ids, history_ids), "TARGET_ID_ORDER_MISMATCH")
        computed = evaluate_cells(selected["pool_gold"], selected["history"], full_target[pool_index], selected["selections"])
        for cell in computed:
            cell.update(chain_id=chain_id, family=family["id"])
        require(len(computed) == len(expected_keys), "COMPUTED_CELL_COUNT_MISMATCH")
        sample_cell = computed[0]
        require(chain["future_flip_count"] == sample_cell["future_flip_count"] and chain["historically_unseen_flips"] == sample_cell["historically_unseen"]["denominator"] and chain["repaired_then_recurred_flips"] == sample_cell["repaired_then_recurred"]["denominator"], "REPORT_FLIP_SUMMARY_MISMATCH")
        cells.extend(computed)
        summaries[chain_id] = summary
    require(cells == read_json(output / "evaluation-cells.json") and len(cells) == frozen["cell_count"], "EVALUATION_CELLS_MISMATCH")
    expected_aggregates = {}
    for chain_id, family, _ in expected_chains:
        for method in methods:
            for budget in config["budgets"]:
                subset = [cell for cell in cells if cell["chain_id"] == chain_id and cell["method"] == method and cell["budget"] == budget]
                valid = [cell["recall"] for cell in subset if cell["recall"] is not None]
                expected_aggregates[(chain_id, method, budget)] = {"chain_id": chain_id, "family": family["id"], "method": method, "budget": budget, "seed_count": len(subset), "actual_size": subset[0]["actual_size"], "mean_detected": float(np.mean([c["detected"] for c in subset])), "mean_recall": float(np.mean(valid)) if valid else None, "std_recall": float(np.std(valid)) if valid else None}
    aggregates = indexed(report["baseline_aggregates"], ["chain_id", "method", "budget"], "DUPLICATE_AGGREGATE")
    require(aggregates == expected_aggregates, "AGGREGATE_SET_OR_VALUE_MISMATCH")
    expected_families = {family: {"chains_with_flips": sum(chains[(chain_id,)]["future_flip_count"] >= config["signal_rule"]["min_future_flips_per_valid_chain"] for chain_id, f, _ in expected_chains if f["id"] == family), "chain_count": sum(f["id"] == family for _, f, _ in expected_chains)} for family in families}
    signal = all(f["chains_with_flips"] >= config["signal_rule"]["min_chains_with_future_flips_per_family"] for f in expected_families.values())
    require(report["families"] == expected_families and report["signal_rule_met"] is signal, "REPORT_SIGNAL_MISMATCH")
    events = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
    for index, event in enumerate(events):
        require(event["previous_sha256"] == (digest(events[index - 1]) if index else None), "EVENT_HASH_CHAIN_MISMATCH")
        current_time = datetime.fromisoformat(event["time"])
        require(current_time.tzinfo is not None and (not index or current_time >= datetime.fromisoformat(events[index - 1]["time"])), "EVENT_TIME_ORDER_MISMATCH")
    event_counts = Counter(e["event"] for e in events)
    require(event_counts == {"PREREGISTERED": 1, "DATA_AUDITED": 1, "MODEL_TRAINED": 4 * len(chain_ids), "CHAIN_SUITES_READY": len(chain_ids), "ALL_SUITES_FROZEN": 1, "TARGET_EVALUATED": len(chain_ids), "PILOT_COMPLETE": 1}, "EVENT_SET_MISMATCH")
    require(events[0]["event"] == "PREREGISTERED" and events[-1]["event"] == "PILOT_COMPLETE", "EVENT_BOUNDARIES_MISMATCH")
    freeze_index = next(i for i, e in enumerate(events) if e["event"] == "ALL_SUITES_FROZEN")
    freeze_event = events[freeze_index]
    require(freeze_event["details"] == {"chains": len(chain_ids), "cell_count": len(cells), "freeze_sha256": file_sha(output / "matrix-freeze.json")}, "FREEZE_EVENT_MISMATCH")
    require(events[0]["details"]["config_sha256"] == digest(config), "PREREGISTRATION_EVENT_MISMATCH")
    audit_event = next(e for e in events if e["event"] == "DATA_AUDITED")
    require(audit_event["details"] == {"counts": audit["counts_cleaned"], "dev_counts": audit["dev_counts"]}, "AUDIT_EVENT_MISMATCH")
    trained = indexed([e["details"] for e in events if e["event"] == "MODEL_TRAINED"], ["chain_id", "slot"], "DUPLICATE_MODEL_EVENT")
    require(set(trained) == {(c, f"f{s}") for c in chain_ids for s in range(4)}, "MODEL_EVENT_SET_MISMATCH")
    ready = indexed([e["details"] for e in events if e["event"] == "CHAIN_SUITES_READY"], ["chain_id"], "DUPLICATE_READY_EVENT")
    targets = indexed([e["details"] for e in events if e["event"] == "TARGET_EVALUATED"], ["chain_id"], "DUPLICATE_TARGET_EVENT")
    require(set(ready) == set(targets) == {(chain_id,) for chain_id in chain_ids}, "TARGET_OR_READY_EVENT_SET_MISMATCH")
    for index, event in enumerate(events):
        kind, detail = event["event"], event["details"]
        if kind in {"MODEL_TRAINED", "CHAIN_SUITES_READY"}:
            require(index < freeze_index, "PREPARATION_EVENT_AFTER_FREEZE")
        if kind == "TARGET_EVALUATED":
            require(index > freeze_index, "TARGET_EVALUATION_EVENT_BEFORE_FREEZE")
            chain = chains[(detail["chain_id"],)]
            require(detail["future_flips"] == chain["future_flip_count"] and detail["seconds"] == round(chain["target_full_dev_inference_seconds"], 4), "TARGET_EVENT_MISMATCH")
        if kind == "MODEL_TRAINED":
            version = next(v for v in summaries[detail["chain_id"]]["versions"] if v["slot"] == detail["slot"])
            require(detail["predicted_target"] is False and detail["training_rows"] == version["training_rows"] and detail["seconds"] == round(version["train_seconds"], 3), "MODEL_EVENT_MISMATCH")
        if kind == "CHAIN_SUITES_READY":
            summary = summaries[detail["chain_id"]]
            require(detail["pool_count"] == summary["pool_count"] and detail["cells"] == summary["selection_cells"] and detail["selection_seconds"] == round(summary["all_baselines_selection_seconds"], 3), "READY_EVENT_MISMATCH")
    require(math.isfinite(report["wall_seconds"]) and report["wall_seconds"] >= 0 and events[-1]["details"] == {"signal_rule_met": signal, "wall_seconds": round(report["wall_seconds"], 3)}, "COMPLETE_EVENT_MISMATCH")
    equivalents = [{"target_chain": target["chain_id"], "historical_chain": history["chain_id"], "historical_slot": history["slot"], "identical_model_file_sha256": target["model_file_sha256"]} for target in versions if target["slot"] == "f3" for history in versions if history["slot"] != "f3" and history["chain_id"] != target["chain_id"] and history["model_file_sha256"] == target["model_file_sha256"]]
    return {"status": "PASS", "purpose": "DEVELOPMENT_ONLY", "frozen_files_verified": len(frozen["files"]), "event_hash_chain_verified": True, "explicit_target_events_after_matrix_freeze": True, "cells_recomputed": len(cells), "aggregates_recomputed": len(aggregates), "cross_chain_equivalent_target_history_nodes": equivalents, "formal_blind_evaluation_eligible": False, "limitations": ["Development artifact consistency audit, rerunning the same scorer rather than independently implementing metric formulas.", "Exact model file hashes are verified, but file inequality does not prove semantic model independence or global temporal isolation.", "Full DEV gold is not persisted: audit trusts frozen pool gold/membership and cannot independently reconstruct the complete correct pool or full-DEV accuracy.", "Event hashes verify internal consistency, not externally anchored completeness or actual execution honesty.", "Target caches are checked for ID alignment and legal labels, not regenerated through model inference.", "Timing fields are measured stage wall times, not deployment cost savings or a hard training timeout."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.output), ensure_ascii=False, indent=2))
