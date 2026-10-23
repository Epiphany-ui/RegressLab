"""A development-only real CPU pilot, with a file freeze before target use."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pickle
import platform
import resource
import subprocess
import time
from uuid import uuid4
import warnings

import numpy as np
import scipy
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from .baselines import select_baselines
from .data import audit_massive, normalize_text
from .fetch import fetch

ROOT = Path(__file__).resolve().parents[2]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return file_hash(path)


def nested_train_indices(rows, fraction, seed):
    if not 0 < fraction <= 1:
        raise ValueError("INVALID_FRACTION")
    groups = defaultdict(list)
    for i, row in enumerate(rows):
        if row["role"] != "TRAIN":
            raise ValueError("TRAIN_ONLY_REQUIRED")
        groups[row["gold_label"]].append(i)
    chosen = []
    for label in sorted(groups):
        ordered = sorted(groups[label], key=lambda i: (hashlib.sha256(f"pilot-train-v1|{seed}|{rows[i]['sample_id']}".encode()).digest(), rows[i]["sample_id"].encode()))
        count = len(ordered) if fraction == 1 else max(1, int(fraction * len(ordered)))
        chosen.extend(ordered[:count])
    return sorted(chosen, key=lambda i: rows[i]["sample_id"].encode())


def probabilities(model, x, labels):
    result = model.predict_proba(x)
    if model.classes_.tolist() != labels or result.shape != (x.shape[0], len(labels)):
        raise ValueError("CLASS_CONTRACT_MISMATCH")
    if not np.isfinite(result).all() or np.any(result < 0) or not np.allclose(result.sum(axis=1), 1, rtol=0, atol=1e-8):
        raise ValueError("INVALID_PROBABILITIES")
    parsed = np.asarray(labels)[result.argmax(axis=1)]
    if not np.array_equal(parsed, model.predict(x)):
        raise ValueError("PREDICT_PROBA_MISMATCH")
    return result, parsed


def evaluate_cells(pool_gold, history, target, selections):
    """Only the post-freeze evaluator receives target predictions."""
    gold = np.asarray(pool_gold)
    history = np.asarray(history)
    if len(gold) == 0 and history.size == 0:
        history = np.empty((0, 3), dtype=str)
    target = np.asarray(target)
    if history.shape != (len(gold), 3) or target.shape != gold.shape or not np.all(history[:, 2] == gold):
        raise ValueError("INVALID_EVALUATION_SCOPE")
    flips = target != gold
    historical_flip = np.any((history[:, :2] == gold[:, None]) & (history[:, 1:] != gold[:, None]), axis=1)
    masks = {"historically_unseen": flips & ~historical_flip, "repaired_then_recurred": flips & historical_flip}
    total = int(flips.sum())
    output = []
    for selected in selections:
        indices = selected["indices"]
        if len(indices) != min(selected["budget"], len(gold)) or len(indices) != len(set(indices)) or any(i < 0 or i >= len(gold) for i in indices):
            raise ValueError("INVALID_SELECTION")
        found = int(flips[indices].sum())
        precision = found / len(indices) if indices else None
        output.append({
            **{k: selected[k] for k in ["method", "seed", "budget"]}, "actual_size": len(indices),
            "pool_count": len(gold), "future_flip_count": total, "detected": found,
            "recall": found / total if total else None, "precision": precision,
            "enrichment": precision / (total / len(gold)) if total and precision is not None else None,
            "na_reason": "NO_TARGET_FLIPS" if not total else None,
            **{name: {"denominator": int(mask.sum()), "detected": int(mask[indices].sum()), "recall": float(mask[indices].sum() / mask.sum()) if mask.any() else None} for name, mask in masks.items()},
        })
    return output


def verify_freeze(output):
    frozen = json.loads((output / "matrix-freeze.json").read_text())
    for relative, expected in frozen["files"].items():
        if file_hash(output / relative) != expected:
            raise ValueError("FROZEN_INPUT_CHANGED")
    return frozen


def vectorizer(config):
    kwargs = {k: v for k, v in config.items() if k != "fit_on"}
    kwargs["ngram_range"] = tuple(kwargs["ngram_range"])
    return TfidfVectorizer(**kwargs, dtype=np.float64)


def run(config_path, data_dir, output):
    if output.exists():
        raise ValueError("OUTPUT_ALREADY_EXISTS_USE_NEW_RUN_DIRECTORY")
    config = json.loads(config_path.read_text())
    if config["purpose"] != "DEVELOPMENT_SIGNAL_PILOT":
        raise ValueError("PILOT_ONLY")
    output.mkdir(parents=True)
    started = time.perf_counter()
    run_id = str(uuid4())
    events = []

    def event(kind, **details):
        value = {"event": kind, "time": utc(), "details": details, "previous_sha256": digest(events[-1]) if events else None}
        events.append(value)
        with (output / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(canonical(value).decode() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({"event": kind, **details}, ensure_ascii=False), flush=True)

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
    event("DATA_AUDITED", counts=prepared["manifest"]["counts_cleaned"], dev_counts=prepared["manifest"]["dev_counts"])
    train = prepared["train"]
    dev = prepared["dev_selector"]
    train_text = [normalize_text(row["text"]) for row in train]
    dev_text = [normalize_text(row["text"]) for row in dev]
    y_train = np.asarray([row["gold_label"] for row in train])
    y_dev = np.asarray([row["gold_label"] for row in dev])
    classes = prepared["manifest"]["label_vocab"]
    chain_summaries = []
    frozen_files = {name: file_hash(output / name) for name in ["preregistration.json", "data-audit.json"]}
    for family in config["families"]:
        for seed in config["training_seeds"]:
            chain_id = f"{family['id']}-seed{seed}"
            directory = output / "chains" / chain_id
            directory.mkdir(parents=True)
            base = nested_train_indices(train, 0.4, seed)
            representation = vectorizer(config["classifier_representation"])
            before = time.perf_counter()
            representation.fit([train_text[i] for i in base])
            x_train, x_dev = representation.transform(train_text), representation.transform(dev_text)
            representation_seconds = time.perf_counter() - before
            basis_hash = digest({"vocabulary": {key: int(value) for key, value in representation.vocabulary_.items()}, "idf": representation.idf_.tolist(), "train_ids": [train[i]["sample_id"] for i in base]})
            models, history, version_summaries = [], [], []
            for slot in range(4):
                indices = nested_train_indices(train, family["train_fractions"][slot], seed)
                model = LogisticRegression(C=family["C"][slot], **config["classifier"])
                begin = time.perf_counter()
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", ConvergenceWarning)
                    model.fit(x_train[indices], y_train[indices])
                train_seconds = time.perf_counter() - begin
                converged = not any(issubclass(w.category, ConvergenceWarning) for w in caught)
                if not converged or train_seconds > config["max_training_seconds_per_model"]:
                    raise ValueError("TRAINING_GATE_FAILED_NO_AUTOMATIC_RETUNING")
                model_path = directory / f"f{slot}.pkl"
                with model_path.open("xb") as stream:
                    pickle.dump({"vectorizer": representation, "classifier": model}, stream, protocol=5)
                with model_path.open("rb") as stream:
                    restored = pickle.load(stream)  # Only the file just produced internally.
                if not np.array_equal(model.predict(x_train[:32]), restored["classifier"].predict(x_train[:32])):
                    raise ValueError("RESTORE_PREDICTIONS_DIFFER")
                models.append(model)
                row = {"slot": f"f{slot}", "training_rows": len(indices), "C": family["C"][slot], "train_ids_sha256": digest([train[i]["sample_id"] for i in indices]), "basis_sha256": basis_hash, "model_file_sha256": file_hash(model_path), "train_seconds": train_seconds, "iterations": model.n_iter_.tolist(), "converged": converged, "restore_check": True}
                if slot < 3:
                    begin = time.perf_counter()
                    prob, prediction = probabilities(model, x_dev, classes)
                    row["history_inference_seconds"] = time.perf_counter() - begin
                    row["dev_selector_accuracy"] = float(np.mean(prediction == y_dev))
                    history.append(prediction)
                    with (directory / f"f{slot}-history.npz").open("xb") as stream:
                        np.savez_compressed(stream, probabilities=prob, predictions=prediction, sample_ids=np.asarray([r["sample_id"] for r in dev]))
                version_summaries.append(row)
                event("MODEL_TRAINED", chain_id=chain_id, slot=row["slot"], training_rows=len(indices), seconds=round(train_seconds, 3), predicted_target=False)
            history = np.asarray(history).T
            pool = np.flatnonzero(history[:, 2] == y_dev)
            pool_ids = [dev[i]["sample_id"] for i in pool]
            pool_gold = y_dev[pool].tolist()
            begin = time.perf_counter()
            selection_repr = vectorizer(config["selection_representation"])
            if len(pool):
                pool_vectors = selection_repr.fit_transform([dev_text[i] for i in pool])
            else:
                from scipy import sparse
                pool_vectors = sparse.csr_matrix((0, 0))
            representation_selection_seconds = time.perf_counter() - begin
            prob2 = np.load(directory / "f2-history.npz")["probabilities"][pool]
            begin = time.perf_counter()
            selections = select_baselines(pool_ids, pool_gold, history[pool], prob2, pool_vectors, classes, config["budgets"], config["selection_seeds"])
            selection_seconds = time.perf_counter() - begin
            if sorted(set(s["method"] for s in selections)) != sorted(config["methods"]):
                raise ValueError("BASELINE_MATRIX_INCOMPLETE")
            selection_path = directory / "selections.json"
            write_json(selection_path, {"scope": "DEV_SELECTOR_CURRENT_CORRECT", "pool_ids": pool_ids, "pool_indices_in_dev": pool.tolist(), "pool_gold": pool_gold, "history": history[pool].tolist(), "selections": selections})
            summary = {"chain_id": chain_id, "family": family["id"], "training_seed": seed, "dev_selector_count": len(dev), "pool_count": len(pool), "pool_label_count": len(set(pool_gold)), "versions": version_summaries, "representation_seconds": representation_seconds, "selection_representation_seconds": representation_selection_seconds, "all_baselines_selection_seconds": selection_seconds, "selection_cells": len(selections), "selection_file_sha256": file_hash(selection_path)}
            write_json(directory / "history-summary.json", summary)
            chain_summaries.append(summary)
            for path in directory.iterdir():
                frozen_files[str(path.relative_to(output))] = file_hash(path)
            event("CHAIN_SUITES_READY", chain_id=chain_id, pool_count=len(pool), cells=len(selections), selection_seconds=round(selection_seconds, 3))
            del models, x_train, x_dev
    write_json(output / "matrix-freeze.json", {"schema_version": "cpu-preflight-matrix-v1", "scope": "DEVELOPMENT_ONLY", "frozen_at": utc(), "config_sha256": digest(config), "chain_ids": [c["chain_id"] for c in chain_summaries], "cell_count": sum(c["selection_cells"] for c in chain_summaries), "files": frozen_files, "target_predictions_generated": False})
    event("ALL_SUITES_FROZEN", chains=len(chain_summaries), cell_count=sum(c["selection_cells"] for c in chain_summaries), freeze_sha256=file_hash(output / "matrix-freeze.json"))
    verify_freeze(output)
    result_cells = []
    for summary in chain_summaries:
        directory = output / "chains" / summary["chain_id"]
        selected = json.loads((directory / "selections.json").read_text())
        with (directory / "f3.pkl").open("rb") as stream:
            restored = pickle.load(stream)
        x_dev = restored["vectorizer"].transform(dev_text)
        begin = time.perf_counter()
        _, target = probabilities(restored["classifier"], x_dev, classes)
        elapsed = time.perf_counter() - begin
        pool = np.asarray(selected["pool_indices_in_dev"], dtype=int)
        with (directory / "f3-target.npz").open("xb") as stream:
            np.savez_compressed(stream, predictions=target, sample_ids=np.asarray([r["sample_id"] for r in dev]))
        cells = evaluate_cells(selected["pool_gold"], selected["history"], target[pool], selected["selections"])
        for cell in cells:
            cell.update(chain_id=summary["chain_id"], family=summary["family"])
        result_cells.extend(cells)
        summary.update(target_dev_selector_accuracy=float(np.mean(target == y_dev)), future_flip_count=int(np.sum(target[pool] != y_dev[pool])), target_full_dev_inference_seconds=elapsed)
        summary["historically_unseen_flips"] = cells[0]["historically_unseen"]["denominator"] if cells else 0
        summary["repaired_then_recurred_flips"] = cells[0]["repaired_then_recurred"]["denominator"] if cells else 0
        event("TARGET_EVALUATED", chain_id=summary["chain_id"], future_flips=summary["future_flip_count"], seconds=round(elapsed, 4))
    write_json(output / "evaluation-cells.json", result_cells)
    aggregated = []
    for chain in chain_summaries:
        for method in config["methods"]:
            for budget in config["budgets"]:
                cells = [c for c in result_cells if c["chain_id"] == chain["chain_id"] and c["method"] == method and c["budget"] == budget]
                recalls = [c["recall"] for c in cells if c["recall"] is not None]
                aggregated.append({"chain_id": chain["chain_id"], "family": chain["family"], "method": method, "budget": budget, "seed_count": len(cells), "mean_recall": float(np.mean(recalls)) if recalls else None, "std_recall": float(np.std(recalls)) if recalls else None, "mean_detected": float(np.mean([c["detected"] for c in cells])), "actual_size": cells[0]["actual_size"]})
    family_signals = {f["id"]: {"chains_with_flips": sum(c["future_flip_count"] >= config["signal_rule"]["min_future_flips_per_valid_chain"] for c in chain_summaries if c["family"] == f["id"]), "chain_count": sum(c["family"] == f["id"] for c in chain_summaries)} for f in config["families"]}
    report = {"schema_version": "cpu-preflight-report-v1", "purpose": config["purpose"], "run_id": run_id, "completed_at": utc(), "config_sha256": digest(config), "freeze_file_sha256": file_hash(output / "matrix-freeze.json"), "data_audit": prepared["manifest"], "families": family_signals, "signal_rule_met": all(x["chains_with_flips"] >= config["signal_rule"]["min_chains_with_future_flips_per_family"] for x in family_signals.values()), "chains": chain_summaries, "baseline_aggregates": aggregated, "wall_seconds": time.perf_counter() - started, "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, "environment": {"python": platform.python_version(), "platform": platform.platform(), "numpy": np.__version__, "scipy": scipy.__version__, "sklearn": sklearn.__version__, "cpu_threads": config["cpu_threads"]}, "formal_test_model_input_count": 0, "gpu_training_executed": False, "hgc_executed": False, "limitations": config["limitations"]}
    write_json(output / "report.json", report)
    event("PILOT_COMPLETE", signal_rule_met=report["signal_rule_met"], wall_seconds=round(report["wall_seconds"], 3))
    return report


def main():
    parser = argparse.ArgumentParser(description="真实CPU开发预实验；不使用正式TEST目标")
    parser.add_argument("--config", type=Path, default=ROOT / "experiments/configs/cpu-preflight-v1.json")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "datasets/massive-1.1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    with threadpool_limits(limits=config["cpu_threads"]):
        try:
            run(args.config, args.data_dir, args.output)
        except Exception as exc:
            print(json.dumps({"event": "PILOT_FAILED", "error_type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), flush=True)
            raise


if __name__ == "__main__":
    main()
