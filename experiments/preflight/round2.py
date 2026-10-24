"""Second and bounded CPU development round; no formal TEST model inputs."""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
import platform
import resource
import subprocess
import time
from uuid import uuid4
import warnings

import numpy as np
from scipy import sparse
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from .baselines import select_baselines
from .data import audit_massive, normalize_text
from .fetch import fetch
from .hgc import select_hgc
from .identity import audit_identities, semantic_identity
from .runner import ROOT, canonical, digest, evaluate_cells, file_hash, nested_train_indices, probabilities, utc, vectorizer, verify_freeze, write_json


def benchmark_predict(bundle, texts, expected=None, repeats=5):
    """Warm-cache ordered wall times, including text transform; never used to select."""
    if type(repeats) is not int or repeats < 1:
        raise ValueError("POSITIVE_BENCHMARK_REPEATS_REQUIRED")
    times = []
    for _ in range(repeats):
        begin = time.perf_counter()
        predicted = bundle["classifier"].predict(bundle["vectorizer"].transform(texts)) if texts else np.asarray([], dtype=str)
        times.append(time.perf_counter() - begin)
        if expected is not None and not np.array_equal(predicted, expected):
            raise ValueError("BENCHMARK_PREDICTION_MISMATCH")
    return {"repetitions": repeats, "wall_seconds": times, "median_seconds": float(np.median(times)), "sample_count": len(texts), "scope": "TEXT_TRANSFORM_AND_PREDICT"}



def validate_selection_matrix(selections, config, pool_count):
    seeded = {"random", "stratified", "past-flip", "kcenter"}
    expected = {(method, seed, budget) for method in config["methods"] for seed in (config["selection_seeds"] if method in seeded else [None]) for budget in config["budgets"]}
    keys = [(s["method"], s["seed"], s["budget"]) for s in selections]
    if len(keys) != len(expected) or set(keys) != expected:
        raise ValueError("SELECTION_MATRIX_INCOMPLETE_OR_DUPLICATE")
    for selection in selections:
        indices = selection["indices"]
        if len(indices) != min(selection["budget"], pool_count) or len(set(indices)) != len(indices) or any(type(i) is not int or not 0 <= i < pool_count for i in indices):
            raise ValueError("INVALID_SELECTION_BEFORE_FREEZE")


def aggregate_cells(cells):
    keys = sorted({(c["chain_id"], c["method"], c["budget"]) for c in cells})
    output = []
    for chain, method, budget in keys:
        subset = [c for c in cells if (c["chain_id"], c["method"], c["budget"]) == (chain, method, budget)]
        valid = [c["recall"] for c in subset if c["recall"] is not None]
        output.append({"chain_id": chain, "family": subset[0]["family"], "method": method, "budget": budget, "seed_count": len(subset), "actual_size": subset[0]["actual_size"], "mean_recall": float(np.mean(valid)) if valid else None, "std_recall": float(np.std(valid)) if valid else None, "mean_detected": float(np.mean([c["detected"] for c in subset]))})
    return output


def screen_report(config, chains, aggregates, costs):
    families = {}
    for family in config["families"]:
        subset = [c for c in chains if c["family"] == family["id"]]
        differences = []
        for chain in subset:
            values = {a["method"]: a["mean_recall"] for a in aggregates if a["chain_id"] == chain["chain_id"] and a["budget"] == config["primary_budget"]}
            if values["hgc"] is not None:
                differences.append(values["hgc"] - values[config["primary_comparator"]])
        families[family["id"]] = {
            "chain_count": len(subset), "chains_with_minimum_events": sum(c["future_flip_count"] >= config["signal_rule"]["min_future_flips_per_valid_chain"] for c in subset),
            "hgc_minus_margin_mean_recall": float(np.mean(differences)) if differences else None,
            "descriptive_recall_screen_met": bool(differences) and len(differences) == len(subset) and float(np.mean(differences)) >= config["hgc_screen"]["minimum_family_mean_difference"],
        }
    ratios = [c["deployment_cost_ratio"] for c in costs if c["method"] == "hgc"]
    return {"families": families, "minimum_event_screen_met": all(f["chains_with_minimum_events"] >= config["signal_rule"]["min_chains_with_future_flips_per_family"] for f in families.values()), "descriptive_hgc_recall_screen_met": all(f["descriptive_recall_screen_met"] for f in families.values()), "cached_history_hgc_cost_screen_met": len(ratios) == len(chains) and all(r <= config["hgc_screen"]["max_hgc_deployment_cost_ratio"] for r in ratios), "formal_gate_approved": False, "automatic_third_tuning_round_authorized": False}


def run(config_path: Path, data_dir: Path, output: Path):
    if output.exists():
        raise ValueError("OUTPUT_ALREADY_EXISTS_USE_NEW_RUN_DIRECTORY")
    config = json.loads(config_path.read_text())
    if config["purpose"] != "DEVELOPMENT_SIGNAL_PILOT" or config["development_round"] != 2 or config["max_development_rounds"] != 2:
        raise ValueError("SECOND_DEVELOPMENT_ROUND_ONLY")
    if config["hgc"] != {"lambda": .5, "m": 30, "k": 3, "min_support": 10, "max_groups": 30, "jaccard": .9, "length_boundaries": [10, 20, 40], "negation_terms": ["不", "没", "无", "别", "未", "不要", "不能", "not", "no", "never", "without"], "question_marks": ["?", "？"]}:
        raise ValueError("FIXED_SINGLE_HGC_CONFIGURATION_REQUIRED")
    output.mkdir(parents=True)
    started = time.perf_counter()
    events = []

    def event(kind, **details):
        value = {"event": kind, "time": utc(), "details": details, "previous_sha256": digest(events[-1]) if events else None}
        events.append(value)
        with (output / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(canonical(value).decode() + "\n")
            stream.flush()
        print(json.dumps({"event": kind, **details}, ensure_ascii=False), flush=True)

    run_id = str(uuid4())
    write_json(output / "preregistration.json", {"run_id": run_id, "registered_at": utc(), "config": config, "config_sha256": digest(config), "code_files": {str(p.relative_to(ROOT)): file_hash(p) for p in sorted((ROOT / "experiments/preflight").glob("*.py"))}, "dependency_lock_sha256": file_hash(ROOT / "experiments/uv.lock"), "git_base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())})
    event("PREREGISTERED", config_sha256=digest(config))
    source = fetch(data_dir)
    if source["archive_sha256"] != config["archive_sha256"]:
        raise ValueError("PREREGISTERED_SOURCE_MISMATCH")
    rows = [json.loads(line) for line in (data_dir / "zh-CN.jsonl").read_text().splitlines()]
    prepared = audit_massive(rows, source=source)
    del rows
    write_json(output / "data-audit.json", prepared["manifest"])
    write_json(output / "excluded-component-ids.json", prepared["excluded"])
    train = prepared["train"]
    dev = [{key: row[key] for key in ("sample_id", "text", "gold_label")} for row in prepared["dev_selector"]]
    write_json(output / "dev-data.json", dev)  # Local-only complete gold enables later pool verification.
    event("DATA_AUDITED", counts=prepared["manifest"]["counts_cleaned"], dev_counts=prepared["manifest"]["dev_counts"])
    train_text = [normalize_text(row["text"]) for row in train]
    dev_text = [normalize_text(row["text"]) for row in dev]
    y_train = np.asarray([row["gold_label"] for row in train])
    y_dev = np.asarray([row["gold_label"] for row in dev])
    ids = np.asarray([row["sample_id"] for row in dev])
    labels = prepared["manifest"]["label_vocab"]
    chains, nodes = [], []
    # Train the entire registered matrix before any current DEV prediction.
    for family in config["families"]:
        for seed in config["training_seeds"]:
            chain_id = f"{family['id']}-seed{seed}"
            directory = output / "chains" / chain_id
            directory.mkdir(parents=True)
            base = nested_train_indices(train, .4, seed)
            representation = vectorizer(config["classifier_representation"])
            begin = time.perf_counter()
            x_train = representation.fit([train_text[i] for i in base]).transform(train_text)
            basis_seconds = time.perf_counter() - begin
            versions = []
            for slot in range(4):
                selected = nested_train_indices(train, family["train_fractions"][slot], seed)
                model = LogisticRegression(C=family["C"][slot], **config["classifier"])
                begin = time.perf_counter()
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", ConvergenceWarning)
                    model.fit(x_train[selected], y_train[selected])
                elapsed = time.perf_counter() - begin
                if any(issubclass(w.category, ConvergenceWarning) for w in caught) or elapsed > config["max_training_seconds_per_model"]:
                    raise ValueError("TRAINING_GATE_FAILED_NO_AUTOMATIC_RETUNING")
                bundle = {"vectorizer": representation, "classifier": model}
                with (directory / f"f{slot}.pkl").open("xb") as stream:
                    pickle.dump(bundle, stream, protocol=5)
                with (directory / f"f{slot}.pkl").open("rb") as stream:
                    restored = pickle.load(stream)  # Only the trusted local file just written.
                if not np.array_equal(model.predict(x_train[:32]), restored["classifier"].predict(x_train[:32])):
                    raise ValueError("RESTORE_PREDICTIONS_DIFFER")
                identity = semantic_identity(representation, model)
                nodes.append({"chain_id": chain_id, "slot": f"f{slot}", "identity": identity})
                versions.append({"slot": f"f{slot}", "C": family["C"][slot], "training_rows": len(selected), "train_ids_sha256": digest([train[i]["sample_id"] for i in selected]), "basis_train_ids_sha256": digest([train[i]["sample_id"] for i in base]), "model_file_sha256": file_hash(directory / f"f{slot}.pkl"), "identity": identity, "train_seconds": elapsed, "iterations": model.n_iter_.tolist(), "converged": True, "restore_check": True})
                event("MODEL_TRAINED", chain_id=chain_id, slot=f"f{slot}", training_rows=len(selected), seconds=round(elapsed, 3), current_dev_predicted=False)
            chain = {"chain_id": chain_id, "family": family["id"], "training_seed": seed, "training_representation_seconds": basis_seconds, "versions": versions}
            write_json(directory / "training-summary.json", chain)
            chains.append(chain)
            del x_train, model, bundle, restored
    identities = audit_identities(nodes)
    # Every model in round one has already been visible, including its former f3.
    prior = ROOT / config["prior_exposure_run"]
    if file_hash(prior / "matrix-freeze.json") != config["prior_freeze_sha256"]:
        raise ValueError("PRIOR_EXPOSURE_FREEZE_MISMATCH")
    prior_freeze = verify_freeze(prior)
    prior_prereg = json.loads((prior / "preregistration.json").read_text())
    expected_prior_chains = [f"{family['id']}-seed{seed}" for family in prior_prereg["config"]["families"] for seed in prior_prereg["config"]["training_seeds"]]
    if prior_prereg["run_id"] != config["parent_run_id"] or prior_freeze["chain_ids"] != expected_prior_chains or len(expected_prior_chains) != 6:
        raise ValueError("PRIOR_EXPOSURE_ID_OR_CHAIN_SET_MISMATCH")
    prior_nodes = []
    for prior_chain_id in expected_prior_chains:
        for slot in range(4):
            relative_model_path = f"chains/{prior_chain_id}/f{slot}.pkl"
            if relative_model_path not in prior_freeze["files"]:
                raise ValueError("PRIOR_EXPOSURE_MODEL_MISSING_FROM_FREEZE")
            model_path = prior / relative_model_path
            with model_path.open("rb") as stream:
                bundle = pickle.load(stream)  # Previously produced and freeze-hash-checked trusted model.
            prior_nodes.append({"chain_id": prior_chain_id, "slot": f"f{slot}", "model_file_sha256": file_hash(model_path), "identity": semantic_identity(bundle["vectorizer"], bundle["classifier"])})
    prior_collisions = [{"target": {"chain_id": node["chain_id"], "slot": node["slot"]}, "previously_seen": {"chain_id": old["chain_id"], "slot": old["slot"]}, "inference_sha256": node["identity"]["inference_sha256"]} for node in nodes if node["slot"] == "f3" for old in prior_nodes if node["identity"]["inference_sha256"] == old["identity"]["inference_sha256"]]
    identities.update(prior_exposure_run_id=prior_prereg["run_id"], prior_freeze_sha256=file_hash(prior / "matrix-freeze.json"), prior_node_count=len(prior_nodes), prior_nodes=prior_nodes, previous_exposure_collisions=prior_collisions)
    identities["passed"] = identities["passed"] and not prior_collisions
    write_json(output / "identity-audit.json", identities)
    event("GLOBAL_IDENTITY_GATE", passed=identities["passed"], current_nodes=len(nodes), prior_nodes=len(prior_nodes), current_dev_predicted=False)
    if not identities["passed"]:
        raise ValueError("SEMANTIC_MODEL_COLLISION_STOP_NO_RETUNING")
    for chain in chains:
        directory = output / "chains" / chain["chain_id"]
        history, prob2 = [], None
        for slot in range(3):
            with (directory / f"f{slot}.pkl").open("rb") as stream:
                bundle = pickle.load(stream)
            begin = time.perf_counter()
            x_dev = bundle["vectorizer"].transform(dev_text)
            probs, predicted = probabilities(bundle["classifier"], x_dev, labels)
            elapsed = time.perf_counter() - begin
            history.append(predicted)
            chain["versions"][slot].update(history_inference_seconds=elapsed, dev_selector_accuracy=float(np.mean(predicted == y_dev)))
            with (directory / f"f{slot}-history.npz").open("xb") as stream:
                np.savez_compressed(stream, probabilities=probs, predictions=predicted, sample_ids=ids)
            if slot == 2:
                prob2 = probs
            event("HISTORY_PREDICTED", chain_id=chain["chain_id"], slot=f"f{slot}", current_target_predicted=False)
        history = np.asarray(history).T
        pool = np.flatnonzero(history[:, 2] == y_dev)
        pool_ids, pool_gold = ids[pool].tolist(), y_dev[pool].tolist()
        begin = time.perf_counter()
        selection_repr = vectorizer(config["selection_representation"])
        vectors = selection_repr.fit_transform([dev_text[i] for i in pool]) if len(pool) else sparse.csr_matrix((0, 0))
        repr_seconds = time.perf_counter() - begin
        sparse.save_npz(directory / "pool-vectors.npz", vectors)
        timings = []
        selected = select_baselines(pool_ids, pool_gold, history[pool], prob2[pool], vectors, labels, config["budgets"], config["selection_seeds"], timings=timings)
        hgc, diagnostic = select_hgc(dev, history, pool.tolist(), vectors, config["budgets"], config["hgc"])
        selected += hgc
        validate_selection_matrix(selected, config, len(pool))
        primary_timings = []
        probe = select_baselines(pool_ids, pool_gold, history[pool], prob2[pool], vectors, labels, [config["primary_budget"]], config["selection_seeds"], timings=primary_timings)
        hgc_probe, primary_diagnostic = select_hgc(dev, history, pool.tolist(), vectors, [config["primary_budget"]], config["hgc"])
        probe += hgc_probe
        if probe != [s for s in selected if s["budget"] == config["primary_budget"]]:
            raise ValueError("PRIMARY_COST_PROBE_CHANGED_SELECTION")
        if set(s["method"] for s in selected) != set(config["methods"]):
            raise ValueError("METHOD_MATRIX_INCOMPLETE")
        begin = time.perf_counter()
        _ = bundle["classifier"].predict_proba(bundle["vectorizer"].transform([dev_text[i] for i in pool])) if len(pool) else []
        reference_score_rebuild_seconds = time.perf_counter() - begin
        write_json(directory / "hgc-diagnostics.json", diagnostic)
        write_json(directory / "pretarget-costs.json", {"selection_representation_seconds": repr_seconds, "all_budget_baselines": timings, "primary_budget_baselines": primary_timings, "primary_budget_hgc": primary_diagnostic, "full_pool_reference_score_rebuild_seconds": reference_score_rebuild_seconds, "history_cache_assumed": True})
        write_json(directory / "selections.json", {"scope": "DEV_SELECTOR_CURRENT_CORRECT", "pool_ids": pool_ids, "pool_indices_in_dev": pool.tolist(), "pool_gold": pool_gold, "history": history[pool].tolist(), "selections": selected})
        chain.update(dev_selector_count=len(dev), pool_count=len(pool), pool_label_count=len(set(pool_gold)), selection_cells=len(selected), selection_representation_seconds=repr_seconds, hgc_group_count=len(diagnostic["groups"]), hgc_fallback=diagnostic["fallback"])
        write_json(directory / "history-summary.json", chain)
        event("CHAIN_SUITES_READY", chain_id=chain["chain_id"], pool_count=len(pool), cells=len(selected), hgc_groups=len(diagnostic["groups"]))
    frozen_files = {str(p.relative_to(output)): file_hash(p) for p in sorted(output.rglob("*")) if p.is_file() and p.name != "events.jsonl"}
    write_json(output / "matrix-freeze.json", {"schema_version": "cpu-preflight-matrix-v2", "scope": "DEVELOPMENT_ONLY", "frozen_at": utc(), "config_sha256": digest(config), "chain_ids": [c["chain_id"] for c in chains], "cell_count": sum(c["selection_cells"] for c in chains), "files": frozen_files, "target_predictions_generated": False, "global_identity_gate_passed": True})
    event("ALL_SUITES_FROZEN", chains=len(chains), cell_count=sum(c["selection_cells"] for c in chains), freeze_sha256=file_hash(output / "matrix-freeze.json"))
    verify_freeze(output)
    cells, costs = [], []
    for chain in chains:
        directory = output / "chains" / chain["chain_id"]
        selection = json.loads((directory / "selections.json").read_text())
        with (directory / "f3.pkl").open("rb") as stream:
            bundle = pickle.load(stream)
        begin = time.perf_counter()
        _, target = probabilities(bundle["classifier"], bundle["vectorizer"].transform(dev_text), labels)
        target_seconds = time.perf_counter() - begin
        with (directory / "f3-target.npz").open("xb") as stream:
            np.savez_compressed(stream, predictions=target, sample_ids=ids)
        pool = np.asarray(selection["pool_indices_in_dev"], dtype=int)
        computed = evaluate_cells(selection["pool_gold"], selection["history"], target[pool], selection["selections"])
        for cell in computed:
            cell.update(chain_id=chain["chain_id"], family=chain["family"])
        cells.extend(computed)
        chain.update(target_dev_selector_accuracy=float(np.mean(target == y_dev)), target_full_dev_seconds=target_seconds, future_flip_count=int(np.sum(target[pool] != y_dev[pool])), historically_unseen_flips=computed[0]["historically_unseen"]["denominator"], repaired_then_recurred_flips=computed[0]["repaired_then_recurred"]["denominator"])
        event("TARGET_EVALUATED", chain_id=chain["chain_id"], future_flips=chain["future_flip_count"])
        cost_inputs = json.loads((directory / "pretarget-costs.json").read_text())
        full = benchmark_predict(bundle, [dev_text[i] for i in pool], target[pool])
        target_costs = {"full_pool": full, "suites": []}
        for suite in selection["selections"]:
            if suite["budget"] != config["primary_budget"]:
                continue
            indices = pool[np.asarray(suite["indices"], dtype=int)]
            inference = benchmark_predict(bundle, [dev_text[i] for i in indices], target[indices])
            if suite["method"] == "hgc":
                method_selection_seconds = cost_inputs["primary_budget_hgc"]["total_seconds"]
                shared_validation_seconds = 0.0
            else:
                method_selection_seconds = next(t["selection_seconds"] for t in cost_inputs["primary_budget_baselines"] if t["method"] == suite["method"] and t["seed"] == suite["seed"])
                shared_validation_seconds = next(t["selection_seconds"] for t in cost_inputs["primary_budget_baselines"] if t["method"] == "__shared_validation__")
            selection_seconds = method_selection_seconds + shared_validation_seconds
            representation_seconds = cost_inputs["selection_representation_seconds"] if suite["method"] in config["cost_policy"]["representation_charged_to"] else 0.0
            total = selection_seconds + representation_seconds + inference["median_seconds"]
            entry = {"chain_id": chain["chain_id"], "family": chain["family"], "method": suite["method"], "seed": suite["seed"], "budget": suite["budget"], "selection_seconds": selection_seconds, "method_selection_seconds": method_selection_seconds, "shared_validation_seconds": shared_validation_seconds, "representation_seconds": representation_seconds, "selected_inference_median_seconds": inference["median_seconds"], "full_pool_inference_median_seconds": full["median_seconds"], "deployment_seconds_cached_history": total, "deployment_cost_ratio": total / full["median_seconds"], "reference_score_rebuild_seconds_if_uncached": cost_inputs["full_pool_reference_score_rebuild_seconds"] if suite["method"].startswith("ref-") else 0.0, "scope": "CACHED_HISTORY_AND_F2_SCORES_NO_TRAINING_AMORTIZATION"}
            costs.append(entry)
            target_costs["suites"].append({"method": suite["method"], "seed": suite["seed"], "budget": suite["budget"], **inference})
        write_json(directory / "target-costs.json", target_costs)
        event("TARGET_COST_MEASURED", chain_id=chain["chain_id"], suites=len(target_costs["suites"]), repetitions_per_suite=5)
    write_json(output / "evaluation-cells.json", cells)
    write_json(output / "deployment-costs.json", costs)
    aggregates = aggregate_cells(cells)
    report = {"schema_version": "cpu-preflight-report-v2", "purpose": "DEVELOPMENT_SIGNAL_PILOT", "development_round": 2, "run_id": run_id, "completed_at": utc(), "config_sha256": digest(config), "freeze_file_sha256": file_hash(output / "matrix-freeze.json"), "data_audit": prepared["manifest"], "chains": chains, "baseline_aggregates": aggregates, "screens": screen_report(config, chains, aggregates, costs), "wall_seconds": time.perf_counter() - started, "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, "environment": {"python": platform.python_version(), "platform": platform.platform(), "cpu_threads": config["cpu_threads"]}, "identity_gate_passed": True, "formal_blind_evaluation_eligible": False, "formal_test_model_input_count": 0, "gpu_training_executed": False, "hgc_executed": True, "limitations": config["limitations"]}
    write_json(output / "report.json", report)
    event("PILOT_COMPLETE", screens=report["screens"], wall_seconds=round(report["wall_seconds"], 3))
    return report


def main():
    parser = argparse.ArgumentParser(description="第二轮CPU开发预实验，固定HGC配置与正式TEST保留")
    parser.add_argument("--config", type=Path, default=ROOT / "experiments/configs/cpu-preflight-v2.json")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "datasets/massive-1.1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    with threadpool_limits(limits=config["cpu_threads"]):
        run(args.config, args.data_dir, args.output)


if __name__ == "__main__":
    main()
