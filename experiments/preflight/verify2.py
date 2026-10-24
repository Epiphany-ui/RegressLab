"""Audit completed round-two development runs, not formal blind eligibility.

ONLY use on trusted, locally generated pilot directories: after checking frozen
bytes this audit deserializes their sklearn pickles to recompute inference-state
identity. It never downloads models or runs target inference. Metrics/selectors
are replayed with the production pure functions, not independent implementations.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
import pickle
import re

import numpy as np
from scipy import sparse

from .baselines import select_baselines
from .data import normalize_text
from .hgc import DEFAULT_HGC_CONFIG, select_hgc
from .identity import audit_identities, semantic_identity
from .round2 import aggregate_cells, screen_report
from .runner import ROOT, digest, evaluate_cells, vectorizer
from .verify import DETERMINISTIC_METHODS, SEEDED_METHODS, file_sha, indexed, integer_values, read_json, require


HGC_TIMES = {"risk_build_seconds", "similarity_build_seconds", "greedy_seconds", "total_seconds"}


def nonnegative(value, code="INVALID_COST_TIME"):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, code)
    return value


def local_file(root, relative):
    path = Path(relative)
    require(not path.is_absolute() and ".." not in path.parts, "UNSAFE_ARTIFACT_PATH")
    candidate = root / path
    require(candidate.is_file() and not candidate.is_symlink(), "MISSING_OR_LINKED_ARTIFACT")
    require(candidate.resolve().is_relative_to(root.resolve()), "ARTIFACT_PATH_ESCAPE")
    return candidate


def expected_matrix(config):
    require(config["schema_version"] == "regresslab-cpu-preflight-v2" and config["purpose"] == "DEVELOPMENT_SIGNAL_PILOT", "CONFIG_SCOPE_MISMATCH")
    require(config["development_round"] == config["max_development_rounds"] == 2, "DEVELOPMENT_ROUND_MISMATCH")
    require(config["hgc"] == DEFAULT_HGC_CONFIG, "HGC_REGISTRATION_MISMATCH")
    for name, minimum in [("training_seeds", 0), ("selection_seeds", 0), ("budgets", 1)]:
        integer_values(config[name], minimum, "INVALID_" + name.upper())
    require(type(config["primary_budget"]) is int and config["primary_budget"] in config["budgets"], "PRIMARY_BUDGET_NOT_REGISTERED")
    require(config["cost_policy"]["primary_budget"] == config["primary_budget"], "COST_PRIMARY_BUDGET_MISMATCH")
    methods = config["methods"]
    require(len(methods) == len(set(methods)) and set(methods) == SEEDED_METHODS | DETERMINISTIC_METHODS | {"hgc"}, "REGISTERED_METHOD_SET_MISMATCH")
    require(config["primary_comparator"] in methods and config["primary_comparator"] != "hgc", "INVALID_PRIMARY_COMPARATOR")
    require(len(config["families"]) == len({f["id"] for f in config["families"]}) > 0, "INVALID_FAMILY_SET")
    chains = [(f"{family['id']}-seed{seed}", family, seed) for family in config["families"] for seed in config["training_seeds"]]
    require(all(re.fullmatch(r"[A-Za-z0-9_-]+", name) for name, _, _ in chains), "UNSAFE_CHAIN_ID")
    for _, family, _ in chains:
        require(len(family["C"]) == len(family["train_fractions"]) == 4, "FOUR_VERSION_RECIPE_REQUIRED")
        require(all(type(c) in (int, float) and math.isfinite(c) and c > 0 for c in family["C"]), "INVALID_C_RECIPE")
        require(all(type(f) in (int, float) and 0 < f <= 1 for f in family["train_fractions"]), "INVALID_TRAIN_FRACTIONS")
    keys = {(method, seed, budget) for method in methods for seed in (config["selection_seeds"] if method in SEEDED_METHODS else [None]) for budget in config["budgets"]}
    files = {"preregistration.json", "data-audit.json", "excluded-component-ids.json", "dev-data.json", "identity-audit.json"}
    names = ["training-summary.json", "history-summary.json", "selections.json", "pool-vectors.npz", "hgc-diagnostics.json", "pretarget-costs.json", *[f"f{i}.pkl" for i in range(4)], *[f"f{i}-history.npz" for i in range(3)]]
    for chain, _, _ in chains:
        files.update(f"chains/{chain}/{name}" for name in names)
    return chains, keys, files


def predictions(path, labels, expected_ids, *, with_scores):
    with np.load(path, allow_pickle=False) as stored:
        require(set(stored.files) == ({"sample_ids", "predictions", "probabilities"} if with_scores else {"sample_ids", "predictions"}), "PREDICTION_ARRAY_FIELDS")
        ids, predicted = stored["sample_ids"], stored["predictions"]
        require(ids.shape == predicted.shape == (len(expected_ids),) and ids.dtype.kind == predicted.dtype.kind == "U", "PREDICTION_ARRAY_SHAPE_OR_TYPE")
        require(ids.tolist() == expected_ids and set(predicted.tolist()) <= set(labels), "PREDICTION_IDS_OR_LABELS_MISMATCH")
        scores = stored["probabilities"] if with_scores else None
        if with_scores:
            require(scores.shape == (len(expected_ids), len(labels)), "PROBABILITY_SHAPE")
            require(np.isfinite(scores).all() and np.all((scores >= 0) & (scores <= 1)), "INVALID_PROBABILITIES")
            require(np.allclose(scores.sum(axis=1), 1, rtol=0, atol=1e-8), "PROBABILITY_NORMALIZATION")
            require(np.array_equal(np.asarray(labels)[scores.argmax(axis=1)], predicted), "PROBABILITY_LABEL_MISMATCH")
        return predicted, scores


def check_hgc(stored, computed):
    require(set(stored) == set(computed), "HGC_DIAGNOSTIC_FIELDS_MISMATCH")
    for name in HGC_TIMES:
        nonnegative(stored[name], "INVALID_HGC_TIME")
    require({k: v for k, v in stored.items() if k not in HGC_TIMES} == {k: v for k, v in computed.items() if k not in HGC_TIMES}, "HGC_RISK_OR_SELECTION_DIAGNOSTICS_MISMATCH")


def timing_index(rows, config, max_budget):
    expected = {(method, seed) for method in config["methods"] if method != "hgc" for seed in (config["selection_seeds"] if method in SEEDED_METHODS else [None])}
    expected.add(("__shared_validation__", None))
    result = indexed(rows, ["method", "seed"], "DUPLICATE_SELECTION_TIMING")
    require(set(result) == expected, "SELECTION_TIMING_SET_MISMATCH")
    for row in rows:
        require(set(row) == {"method", "seed", "selection_seconds", "max_budget", "includes_shared_representation"}, "SELECTION_TIMING_FIELDS_MISMATCH")
        require(type(row["max_budget"]) is int and row["max_budget"] == max_budget and row["includes_shared_representation"] is False, "TIMING_BUDGET_OR_REPRESENTATION_MISMATCH")
        nonnegative(row["selection_seconds"])
    return result


def benchmark_block(block, sample_count):
    require(set(block) == {"repetitions", "wall_seconds", "median_seconds", "sample_count", "scope"}, "BENCHMARK_FIELDS_MISMATCH")
    require(block["repetitions"] == 5 and len(block["wall_seconds"]) == 5 and block["sample_count"] == sample_count and block["scope"] == "TEXT_TRANSFORM_AND_PREDICT", "BENCHMARK_SCOPE_MISMATCH")
    for elapsed in block["wall_seconds"]:
        nonnegative(elapsed)
    require(block["median_seconds"] == float(np.median(block["wall_seconds"])), "BENCHMARK_MEDIAN_MISMATCH")
    return nonnegative(block["median_seconds"])


def deployment_costs(config, chain, selections, pretarget, target_costs):
    primary = config["primary_budget"]
    timing_index(pretarget["all_budget_baselines"], config, max(config["budgets"]))
    timings = timing_index(pretarget["primary_budget_baselines"], config, primary)
    require(pretarget["history_cache_assumed"] is True, "COST_SCENARIO_MISMATCH")
    nonnegative(pretarget["selection_representation_seconds"])
    nonnegative(pretarget["full_pool_reference_score_rebuild_seconds"])
    suites = [s for s in selections if s["budget"] == primary]
    measured = indexed(target_costs["suites"], ["method", "seed", "budget"], "DUPLICATE_TARGET_COST")
    require(set(measured) == {(s["method"], s["seed"], primary) for s in suites}, "TARGET_COST_METHOD_SET_MISMATCH")
    full = benchmark_block(target_costs["full_pool"], chain["pool_count"])
    require(full > 0, "ZERO_FULL_POOL_BENCHMARK_TIME")
    output = []
    for suite in suites:
        block = measured[(suite["method"], suite["seed"], primary)]
        selected = benchmark_block({k: v for k, v in block.items() if k not in {"method", "seed", "budget"}}, len(suite["indices"]))
        shared = 0.0 if suite["method"] == "hgc" else timings[("__shared_validation__", None)]["selection_seconds"]
        method = pretarget["primary_budget_hgc"]["total_seconds"] if suite["method"] == "hgc" else timings[(suite["method"], suite["seed"])]["selection_seconds"]
        selection = nonnegative(method) + shared
        representation = pretarget["selection_representation_seconds"] if suite["method"] in config["cost_policy"]["representation_charged_to"] else 0.0
        total = selection + representation + selected
        output.append({
            "chain_id": chain["chain_id"], "family": chain["family"], "method": suite["method"], "seed": suite["seed"], "budget": primary,
            "selection_seconds": selection, "method_selection_seconds": method, "shared_validation_seconds": shared,
            "representation_seconds": representation, "selected_inference_median_seconds": selected,
            "full_pool_inference_median_seconds": full, "deployment_seconds_cached_history": total,
            "deployment_cost_ratio": total / full,
            "reference_score_rebuild_seconds_if_uncached": pretarget["full_pool_reference_score_rebuild_seconds"] if suite["method"].startswith("ref-") else 0.0,
            "scope": "CACHED_HISTORY_AND_F2_SCORES_NO_TRAINING_AMORTIZATION",
        })
    return output


def trusted_identity(path, expected_sha):
    require(file_sha(path) == expected_sha, "MODEL_FILE_HASH_MISMATCH")
    with path.open("rb") as stream:
        bundle = pickle.load(stream)  # TRUSTED LOCAL RUN ONLY; never an HTTP/upload API.
    require(type(bundle) is dict and set(bundle) == {"vectorizer", "classifier"}, "MODEL_BUNDLE_FIELDS_MISMATCH")
    return semantic_identity(bundle["vectorizer"], bundle["classifier"]), bundle


def check_identity_audit(output, config, nodes):
    stored = read_json(output / "identity-audit.json")
    actual = audit_identities(nodes)
    require(all(stored.get(k) == value for k, value in actual.items()), "GLOBAL_IDENTITY_AUDIT_MISMATCH")
    require(stored["prior_exposure_run_id"] == config["parent_run_id"], "PRIOR_RUN_ID_MISMATCH")
    prior_nodes = stored["prior_nodes"]
    prior_keys = indexed(prior_nodes, ["chain_id", "slot"], "DUPLICATE_PRIOR_IDENTITY")
    # The identity parser verifies the full canonical components/hash even if a
    # previously generated run is no longer available on this trusted host.
    audit_identities([{k: v for k, v in node.items() if k != "model_file_sha256"} for node in prior_nodes])
    require(stored["prior_node_count"] == len(prior_nodes) == 24, "PRIOR_NODE_COUNT_MISMATCH")
    require(stored["prior_freeze_sha256"] == config["prior_freeze_sha256"], "REGISTERED_PRIOR_FREEZE_MISMATCH")
    relative = Path(config["prior_exposure_run"])
    require(not relative.is_absolute() and ".." not in relative.parts, "UNSAFE_PRIOR_RUN_PATH")
    prior = ROOT / relative
    verified_prior = 0
    require(prior.is_dir(), "PRIOR_LOCAL_RUN_REQUIRED_FOR_EXPOSURE_AUDIT")
    if prior.exists():
        old_freeze = read_json(prior / "matrix-freeze.json")
        for name, expected in old_freeze["files"].items():
            require(file_sha(local_file(prior, name)) == expected, "PRIOR_FROZEN_INPUT_CHANGED")
        require(file_sha(prior / "matrix-freeze.json") == stored["prior_freeze_sha256"], "PRIOR_FREEZE_HASH_MISMATCH")
        old_prereg = read_json(prior / "preregistration.json")
        require(old_prereg["run_id"] == config["parent_run_id"], "PRIOR_PREREGISTRATION_IDENTITY_MISMATCH")
        prior_chain_ids = [f"{family['id']}-seed{seed}" for family in old_prereg["config"]["families"] for seed in old_prereg["config"]["training_seeds"]]
        require(prior_chain_ids == old_freeze["chain_ids"] and len(prior_chain_ids) == 6, "PRIOR_FROZEN_CHAIN_SET_MISMATCH")
        expected_prior = {(chain_id, f"f{slot}") for chain_id in prior_chain_ids for slot in range(4)}
        require(set(prior_keys) == expected_prior, "PRIOR_NODE_SET_MISMATCH")
        for (chain, slot), node in prior_keys.items():
            name = f"chains/{chain}/{slot}.pkl"
            require(old_freeze["files"].get(name) == node["model_file_sha256"], "PRIOR_MODEL_HASH_MISMATCH")
            identity, _ = trusted_identity(local_file(prior, name), node["model_file_sha256"])
            require(identity == node["identity"], "PRIOR_MODEL_IDENTITY_MISMATCH")
            verified_prior += 1
    collisions = [{"target": {"chain_id": node["chain_id"], "slot": node["slot"]}, "previously_seen": {"chain_id": old["chain_id"], "slot": old["slot"]}, "inference_sha256": node["identity"]["inference_sha256"]} for node in nodes if node["slot"] == "f3" for old in prior_nodes if node["identity"]["inference_sha256"] == old["identity"]["inference_sha256"]]
    require(stored["previous_exposure_collisions"] == collisions and actual["passed"] and not collisions and stored["passed"] is True, "SEMANTIC_MODEL_COLLISION")
    return len(prior_nodes), verified_prior


def check_events(output, config, chains, cells, report, identities):
    events = []
    for line in (output / "events.jsonl").read_text().splitlines():
        def unique(pairs):
            require(len(dict(pairs)) == len(pairs), "DUPLICATE_EVENT_JSON_KEY")
            return dict(pairs)
        events.append(json.loads(line, object_pairs_hook=unique, parse_constant=lambda _: require(False, "NONFINITE_EVENT")))
    chain_ids = [chain["chain_id"] for chain in chains]
    counts = {"PREREGISTERED": 1, "DATA_AUDITED": 1, "MODEL_TRAINED": 4 * len(chains), "GLOBAL_IDENTITY_GATE": 1, "HISTORY_PREDICTED": 3 * len(chains), "CHAIN_SUITES_READY": len(chains), "ALL_SUITES_FROZEN": 1, "TARGET_EVALUATED": len(chains), "TARGET_COST_MEASURED": len(chains), "PILOT_COMPLETE": 1}
    require(Counter(e["event"] for e in events) == counts, "EVENT_SET_MISMATCH")
    require(events[0]["event"] == "PREREGISTERED" and events[-1]["event"] == "PILOT_COMPLETE", "EVENT_BOUNDARIES_MISMATCH")
    for i, event in enumerate(events):
        require(set(event) == {"event", "time", "details", "previous_sha256"}, "EVENT_FIELDS_MISMATCH")
        require(event["previous_sha256"] == (digest(events[i - 1]) if i else None), "EVENT_HASH_CHAIN_MISMATCH")
        now = datetime.fromisoformat(event["time"])
        require(now.tzinfo is not None and (not i or now >= datetime.fromisoformat(events[i - 1]["time"])), "EVENT_TIME_ORDER_MISMATCH")
    gate = next(i for i, e in enumerate(events) if e["event"] == "GLOBAL_IDENTITY_GATE")
    freeze = next(i for i, e in enumerate(events) if e["event"] == "ALL_SUITES_FROZEN")
    require(gate < freeze, "IDENTITY_GATE_AFTER_FREEZE")
    require(events[gate]["details"] == {"passed": True, "current_nodes": 4 * len(chains), "prior_nodes": identities, "current_dev_predicted": False}, "IDENTITY_GATE_EVENT_MISMATCH")
    require(events[freeze]["details"] == {"chains": len(chains), "cell_count": len(cells), "freeze_sha256": file_sha(output / "matrix-freeze.json")}, "FREEZE_EVENT_MISMATCH")
    require(events[0]["details"] == {"config_sha256": digest(config)}, "PREREGISTRATION_EVENT_MISMATCH")
    audit = report["data_audit"]
    data_event = next(i for i, e in enumerate(events) if e["event"] == "DATA_AUDITED")
    require(events[data_event]["details"] == {"counts": audit["counts_cleaned"], "dev_counts": audit["dev_counts"]} and data_event < gate, "DATA_AUDIT_EVENT_MISMATCH")
    by_chain = {c["chain_id"]: c for c in chains}
    seen = {kind: set() for kind in ("MODEL_TRAINED", "HISTORY_PREDICTED", "CHAIN_SUITES_READY", "TARGET_EVALUATED", "TARGET_COST_MEASURED")}
    for i, event in enumerate(events):
        kind, detail = event["event"], event["details"]
        if kind not in seen:
            continue
        require(detail["chain_id"] in by_chain, "EVENT_UNKNOWN_CHAIN")
        chain = by_chain[detail["chain_id"]]
        key = (detail["chain_id"], detail["slot"]) if kind in {"MODEL_TRAINED", "HISTORY_PREDICTED"} else detail["chain_id"]
        require(key not in seen[kind], "DUPLICATE_STAGE_EVENT")
        seen[kind].add(key)
        if kind == "MODEL_TRAINED":
            require(data_event < i < gate, "MODEL_TRAINING_AFTER_IDENTITY_GATE")
            versions = {v["slot"]: v for v in chain["versions"]}
            require(detail["slot"] in versions, "UNKNOWN_MODEL_SLOT_EVENT")
            v = versions[detail["slot"]]
            require(detail == {"chain_id": chain["chain_id"], "slot": detail["slot"], "training_rows": v["training_rows"], "seconds": round(v["train_seconds"], 3), "current_dev_predicted": False}, "MODEL_TRAIN_EVENT_MISMATCH")
        elif kind == "HISTORY_PREDICTED":
            require(gate < i < freeze and detail["slot"] in {"f0", "f1", "f2"} and detail["current_target_predicted"] is False, "HISTORY_BEFORE_IDENTITY_GATE_OR_AFTER_FREEZE")
        elif kind == "CHAIN_SUITES_READY":
            require(gate < i < freeze and all((chain["chain_id"], f"f{s}") in seen["HISTORY_PREDICTED"] for s in range(3)), "READY_BEFORE_HISTORY_OR_AFTER_FREEZE")
            require(detail == {"chain_id": chain["chain_id"], "pool_count": chain["pool_count"], "cells": chain["selection_cells"], "hgc_groups": chain["hgc_group_count"]}, "SUITES_READY_EVENT_MISMATCH")
        elif kind == "TARGET_EVALUATED":
            require(i > freeze and detail == {"chain_id": chain["chain_id"], "future_flips": chain["future_flip_count"]}, "TARGET_BEFORE_FREEZE_OR_EVENT_MISMATCH")
        else:
            primary_count = len(config["selection_seeds"]) * len(SEEDED_METHODS) + len(DETERMINISTIC_METHODS) + 1
            require(i > freeze and chain["chain_id"] in seen["TARGET_EVALUATED"] and detail == {"chain_id": chain["chain_id"], "suites": primary_count, "repetitions_per_suite": 5}, "TARGET_COST_EVENT_MISMATCH")
    require(seen["MODEL_TRAINED"] == {(c, f"f{s}") for c in chain_ids for s in range(4)} and seen["HISTORY_PREDICTED"] == {(c, f"f{s}") for c in chain_ids for s in range(3)}, "MODEL_OR_HISTORY_EVENT_MATRIX_MISMATCH")
    require(all(seen[kind] == set(chain_ids) for kind in ("CHAIN_SUITES_READY", "TARGET_EVALUATED", "TARGET_COST_MEASURED")), "CHAIN_EVENT_MATRIX_MISMATCH")
    nonnegative(report["wall_seconds"], "INVALID_RUN_WALL_TIME")
    require(events[-1]["details"] == {"screens": report["screens"], "wall_seconds": round(report["wall_seconds"], 3)}, "COMPLETE_EVENT_MISMATCH")
    require(datetime.fromisoformat(events[freeze - 1]["time"]) <= datetime.fromisoformat(read_json(output / "matrix-freeze.json")["frozen_at"]) <= datetime.fromisoformat(events[freeze]["time"]), "FREEZE_TIMESTAMP_MISMATCH")
    return len(events)


def verify(output: Path) -> dict:
    output = Path(output).resolve()
    frozen = read_json(local_file(output, "matrix-freeze.json"))
    require(frozen["schema_version"] == "cpu-preflight-matrix-v2" and frozen["scope"] == "DEVELOPMENT_ONLY" and frozen["target_predictions_generated"] is False and frozen["global_identity_gate_passed"] is True, "FREEZE_SCOPE_MISMATCH")
    # Check bytes before using cached data or deserializing trusted local models.
    for name, expected in frozen["files"].items():
        require(re.fullmatch(r"[0-9a-f]{64}", expected) is not None and file_sha(local_file(output, name)) == expected, "FROZEN_INPUT_CHANGED")
    prereg = read_json(local_file(output, "preregistration.json"))
    config = prereg["config"]
    expected_chains, expected_keys, expected_files = expected_matrix(config)
    require(set(frozen["files"]) == expected_files, "FROZEN_FILE_SET_MISMATCH")
    require(digest(config) == prereg["config_sha256"] == frozen["config_sha256"], "CONFIG_HASH_MISMATCH")
    chain_ids = [name for name, _, _ in expected_chains]
    require(frozen["chain_ids"] == chain_ids and frozen["cell_count"] == len(expected_keys) * len(chain_ids), "FROZEN_MATRIX_MISMATCH")
    report = read_json(local_file(output, "report.json"))
    require(report["schema_version"] == "cpu-preflight-report-v2" and report["purpose"] == config["purpose"] and report["development_round"] == 2 and report["run_id"] == prereg["run_id"], "REPORT_IDENTITY_MISMATCH")
    require(report["config_sha256"] == digest(config) and report["freeze_file_sha256"] == file_sha(output / "matrix-freeze.json"), "REPORT_FREEZE_MISMATCH")
    require(report["identity_gate_passed"] is True and report["formal_blind_evaluation_eligible"] is False and report["formal_test_model_input_count"] == 0 and report["gpu_training_executed"] is False and report["hgc_executed"] is True and report["limitations"] == config["limitations"], "REPORT_SCOPE_MISMATCH")
    audit = read_json(output / "data-audit.json")
    require(report["data_audit"] == audit and audit["source"]["archive_sha256"] == config["archive_sha256"] and audit["cleaning_policy"] == config["cleaning_policy"] and audit["test_use"] == config["test_policy"] and audit["test_samples_returned"] == 0, "DATA_AUDIT_MISMATCH")
    excluded = read_json(output / "excluded-component-ids.json")
    require(digest(excluded) == audit["excluded_sha256"] and Counter(x["source_partition"] for x in excluded) == Counter({k: v for k, v in audit["excluded_counts"].items() if v}), "EXCLUSION_MANIFEST_MISMATCH")
    dev = read_json(output / "dev-data.json")
    ids = [row["sample_id"] for row in dev]
    require(all(set(row) == {"sample_id", "text", "gold_label"} and all(type(v) is str and bool(v) for v in row.values()) for row in dev), "DEV_DATA_FIELDS_MISMATCH")
    require(ids == sorted(set(ids), key=lambda value: value.encode("utf-8")) and len(dev) == audit["dev_counts"]["DEV_SELECTOR"], "DEV_DATA_ID_OR_COUNT_MISMATCH")
    labels = audit["label_vocab"]
    require(set(row["gold_label"] for row in dev) <= set(labels) and all(normalize_text(row["text"]) for row in dev), "DEV_GOLD_OR_TEXT_INVALID")
    require({label: sum(row["gold_label"] == label for row in dev) for label in labels} == audit["dev_label_counts"]["DEV_SELECTOR"], "FULL_DEV_GOLD_COUNTS_MISMATCH")
    gold = np.asarray([row["gold_label"] for row in dev])
    report_chains = indexed(report["chains"], ["chain_id"], "DUPLICATE_REPORT_CHAIN")
    require(set(report_chains) == {(name,) for name in chain_ids}, "REPORT_CHAIN_SET_MISMATCH")
    require(report["environment"]["cpu_threads"] == config["cpu_threads"], "CPU_THREAD_CONFIG_MISMATCH")
    all_cells, all_costs, nodes, summaries = [], [], [], []
    for chain_id, family, seed in expected_chains:
        directory = output / "chains" / chain_id
        summary = read_json(directory / "history-summary.json")
        training = read_json(directory / "training-summary.json")
        chain = report_chains[(chain_id,)]
        require(all(chain.get(k) == v for k, v in summary.items()), "REPORT_CHAIN_SUMMARY_MISMATCH")
        require(summary["chain_id"] == chain_id and summary["family"] == family["id"] and summary["training_seed"] == seed and summary["dev_selector_count"] == len(dev), "CHAIN_REGISTRATION_MISMATCH")
        require([v["slot"] for v in summary["versions"]] == [f"f{s}" for s in range(4)], "MODEL_SLOT_SET_MISMATCH")
        require(all(training[k] == summary[k] for k in ("chain_id", "family", "training_seed", "training_representation_seconds")), "TRAINING_SUMMARY_MISMATCH")
        history, reference = [], None
        for slot, version in enumerate(summary["versions"]):
            require(all(version.get(k) == v for k, v in training["versions"][slot].items()), "TRAINING_VERSION_MISMATCH")
            identity, bundle = trusted_identity(local_file(output, f"chains/{chain_id}/f{slot}.pkl"), version["model_file_sha256"])
            require(identity == version["identity"], "SEMANTIC_MODEL_IDENTITY_MISMATCH")
            nodes.append({"chain_id": chain_id, "slot": f"f{slot}", "identity": identity})
            model = bundle["classifier"]
            require(model.classes_.tolist() == labels and model.C == version["C"] == family["C"][slot] and all(model.get_params()[k] == v for k, v in config["classifier"].items()), "FITTED_MODEL_CONFIG_MISMATCH")
            require(all(bundle["vectorizer"].get_params()[k] == (tuple(v) if k == "ngram_range" else v) for k, v in config["classifier_representation"].items() if k != "fit_on"), "FITTED_REPRESENTATION_CONFIG_MISMATCH")
            require(version["converged"] is True and version["restore_check"] is True and model.n_iter_.tolist() == version["iterations"], "MODEL_GATE_OR_ITERATION_MISMATCH")
            count = sum(c if family["train_fractions"][slot] == 1 else max(1, int(family["train_fractions"][slot] * c)) for c in audit["train_label_counts"].values())
            require(version["training_rows"] == count, "TRAINING_ROW_COUNT_MISMATCH")
            nonnegative(version["train_seconds"])
            require(version["train_seconds"] <= config["max_training_seconds_per_model"], "TRAINING_TIME_GATE_FAILED")
            if slot < 3:
                predicted, probs = predictions(directory / f"f{slot}-history.npz", labels, ids, with_scores=True)
                require(version["dev_selector_accuracy"] == float(np.mean(predicted == gold)), "HISTORY_ACCURACY_MISMATCH")
                nonnegative(version["history_inference_seconds"])
                history.append(predicted)
                if slot == 2:
                    reference = probs
        require(len({v["basis_train_ids_sha256"] for v in summary["versions"]}) == 1, "CHAIN_BASIS_TRAIN_IDENTITY_MISMATCH")
        history = np.asarray(history).T
        pool = np.flatnonzero(history[:, 2] == gold)
        selected = read_json(directory / "selections.json")
        require(selected["scope"] == "DEV_SELECTOR_CURRENT_CORRECT", "SELECTION_SCOPE_MISMATCH")
        require(selected["pool_indices_in_dev"] == pool.tolist() and selected["pool_ids"] == [ids[i] for i in pool] and selected["pool_gold"] == gold[pool].tolist() and selected["history"] == history[pool].tolist(), "FULL_CURRENT_CORRECT_POOL_MISMATCH")
        require(summary["pool_count"] == len(pool) and summary["pool_label_count"] == len(set(gold[pool])), "POOL_SUMMARY_MISMATCH")
        selections = selected["selections"]
        require(set(indexed(selections, ["method", "seed", "budget"], "DUPLICATE_SELECTION_CELL")) == expected_keys and summary["selection_cells"] == len(expected_keys), "SELECTION_CELL_SET_MISMATCH")
        texts = [normalize_text(dev[i]["text"]) for i in pool]
        rebuilt = vectorizer(config["selection_representation"]).fit_transform(texts) if len(pool) else sparse.csr_matrix((0, 0))
        vectors = sparse.load_npz(directory / "pool-vectors.npz").tocsr()
        require(vectors.shape == rebuilt.shape and np.array_equal(vectors.indptr, rebuilt.indptr) and np.array_equal(vectors.indices, rebuilt.indices) and np.array_equal(vectors.data, rebuilt.data), "POOL_REPRESENTATION_MISMATCH")
        baseline = select_baselines(selected["pool_ids"], selected["pool_gold"], history[pool], reference[pool], vectors, labels, config["budgets"], config["selection_seeds"])
        hgc, diagnostic = select_hgc(dev, history, pool.tolist(), vectors, config["budgets"], config["hgc"])
        require(selections == baseline + hgc, "SELECTION_REPLAY_MISMATCH")
        check_hgc(read_json(directory / "hgc-diagnostics.json"), diagnostic)
        require(summary["hgc_group_count"] == len(diagnostic["groups"]) and summary["hgc_fallback"] == diagnostic["fallback"], "HGC_SUMMARY_MISMATCH")
        pretarget = read_json(directory / "pretarget-costs.json")
        _, primary_diagnostic = select_hgc(dev, history, pool.tolist(), vectors, [config["primary_budget"]], config["hgc"])
        check_hgc(pretarget["primary_budget_hgc"], primary_diagnostic)
        require(pretarget["selection_representation_seconds"] == summary["selection_representation_seconds"], "REPRESENTATION_COST_MISMATCH")
        target, _ = predictions(local_file(output, f"chains/{chain_id}/f3-target.npz"), labels, ids, with_scores=False)
        require(chain["target_dev_selector_accuracy"] == float(np.mean(target == gold)), "TARGET_ACCURACY_MISMATCH")
        computed = evaluate_cells(selected["pool_gold"], selected["history"], target[pool], selections)
        for cell in computed:
            cell.update(chain_id=chain_id, family=family["id"])
        first = computed[0]
        require(chain["future_flip_count"] == first["future_flip_count"] and chain["historically_unseen_flips"] == first["historically_unseen"]["denominator"] and chain["repaired_then_recurred_flips"] == first["repaired_then_recurred"]["denominator"], "FUTURE_EVENT_SUMMARY_MISMATCH")
        nonnegative(chain["target_full_dev_seconds"])
        all_cells.extend(computed)
        all_costs.extend(deployment_costs(config, chain, selections, pretarget, read_json(local_file(output, f"chains/{chain_id}/target-costs.json"))))
        summaries.append(chain)
    prior_count, prior_verified = check_identity_audit(output, config, nodes)
    require(all_cells == read_json(local_file(output, "evaluation-cells.json")) and len(all_cells) == frozen["cell_count"], "EVALUATION_CELLS_MISMATCH")
    require(all_costs == read_json(local_file(output, "deployment-costs.json")), "DEPLOYMENT_COSTS_MISMATCH")
    aggregates = aggregate_cells(all_cells)
    require(report["baseline_aggregates"] == aggregates and len(aggregates) == len(chain_ids) * len(config["methods"]) * len(config["budgets"]), "AGGREGATE_SET_OR_VALUE_MISMATCH")
    require(report["screens"] == screen_report(config, summaries, aggregates, all_costs), "REPORT_SCREENS_MISMATCH")
    event_count = check_events(output, config, summaries, all_cells, report, prior_count)
    return {
        "status": "PASS", "purpose": "DEVELOPMENT_ROUND_2_ONLY", "frozen_files_verified": len(expected_files),
        "chains_verified": len(chain_ids), "cells_recomputed": len(all_cells), "aggregates_recomputed": len(aggregates),
        "primary_deployment_cost_rows_recomputed": len(all_costs), "events_verified": event_count,
        "full_current_correct_pools_reconstructed": True, "history_only_selection_replayed": True,
        "hgc_risk_diagnostics_recomputed": True, "model_semantic_identities_recomputed": len(nodes),
        "previously_exposed_nodes_verified_from_local_models": prior_verified, "previously_exposed_nodes_registered": prior_count,
        "global_identity_gate_before_history_events": True, "target_events_after_global_freeze": True,
        "formal_blind_evaluation_eligible": False,
        "limitations": [
            "Trusted local sklearn pickle files only; never apply this CLI to untrusted uploads.",
            "Selectors, HGC, metrics and screen formulas are replayed with existing implementations, not independent algorithms.",
            "Cached target labels are validated and aligned but target inference is not executed again by this audit.",
            "Event hashes establish internal consistency, not external proof of timing or previously unseen outcomes.",
            "Second development round reuses DEV data; related LR chains are not independent updates or formal blind evidence.",
            "Fixed-order warm-cache cost medians do not establish neural deployment savings or a hard resource timeout.",
            "Previous-round trusted local model files are required to verify all registered prior exposures.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="仅审计可信本地第二轮CPU预实验目录；会加载模型pickle")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.output), ensure_ascii=False, indent=2))
