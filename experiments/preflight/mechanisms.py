"""Fixed synthetic mechanism checks; never evidence of natural-model benefit.

All suites in the registered grid are sealed before generating any target.
Synthetic difficulty supplies a genuinely informative margin comparator in both
regimes. Generator latent values are kept outside every selector interface.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from scipy import sparse
from threadpoolctl import threadpool_limits

from .baselines import _anchors, _facility_order
from .hgc import DEFAULT_HGC_CONFIG, select_hgc
from .runner import ROOT, canonical, digest, evaluate_cells, file_hash, utc, write_json

SCENARIOS = ["risk_persists", "risk_reversed", "new_risk", "overlap", "no_group_signal"]
DEFAULT_MECHANISM_CONFIG = {
    "schema_version": "regresslab-fixed-mechanisms-v1",
    "purpose": "SYNTHETIC_MECHANISM_CHECK_ONLY",
    "n_rows": 800,
    "environment_seeds": list(range(1000, 1020)),
    "selection_seeds": list(range(20)),
    "scenarios": SCENARIOS,
    "margin_regimes": {
        "complementary": {"intercept": .01, "difficulty_coefficient": .12, "group_coefficient": .28},
        "strong_margin": {"intercept": .01, "difficulty_coefficient": .45, "group_coefficient": .06},
    },
    "budgets": [20, 50, 100], "primary_budget": 100,
    "methods": ["hgc", "facility", "risk-top", "random", "ref-margin"],
    "hgc": deepcopy(DEFAULT_HGC_CONFIG),
    "representation": {"analyzer": "char", "ngram_range": [2, 4], "min_df": 1, "max_features": 5000, "sublinear_tf": True, "lowercase": False, "norm": "l2"},
    "features": {"negation_probability": .25, "digit_probability": .25, "question_probability": .5, "gold": "balanced A/B, independently shuffled", "difficulty": "independent Uniform[0,1]"},
    "history": {"f0_correct_probability": .9, "negative_flip_base": .015, "single_group_coefficient": .18, "overlap_each_group_coefficient": .13, "repair_probabilities": [.5, .75]},
    "reference_probability": {"predicted_class_intercept": .95, "difficulty_coefficient": -.4},
    "target_wrong_to_correct_probability": .75,
    "rng": {"algorithm": "NumPy default_rng(SeedSequence([environment_seed, stream]))", "feature_stream": 11, "history_stream": 23, "difficulty_stream": 37, "target_stream": 97, "paired_scenarios_and_regimes": True},
    "target_group": {"risk_persists": "negation", "risk_reversed": "not negation", "new_risk": "digit", "overlap": "(negation + digit)/2", "no_group_signal": "zero; target depends only on difficulty"},
    "history_group": "negation, except overlap uses additive negation/digit coefficients",
    "freeze_policy": "ALL_200_ENVIRONMENT_SUITES_BEFORE_ANY_SYNTHETIC_TARGET",
    "cpu_threads": 2,
    "numerical_tie_tolerance": 1e-12,
    "limitations": ["Synthetic DGP, labels, confidence and histories are not trained model outputs.", "Every scenario includes a genuinely informative margin comparator; no-group-signal control retains difficulty signal.", "Same-seed scenarios/regimes are paired, not independent model families; selection seeds are aggregated within environment.", "A positive synthetic result cannot establish natural-data superiority, net deployment savings, novelty or thesis acceptability.", "Failure or reversal scenarios are retained; no parameter search or post-result mechanism changes."],
}


def _rng(seed, stream):
    if type(seed) is not int or seed < 0:
        raise ValueError("NONNEGATIVE_ENVIRONMENT_SEED_REQUIRED")
    return np.random.default_rng(np.random.SeedSequence([seed, stream]))


def validate_config(config):
    if config != DEFAULT_MECHANISM_CONFIG:
        raise ValueError("FIXED_MECHANISM_REGISTRATION_REQUIRED_NO_RETUNING")


def build_environment(seed, scenario, n_rows=800, config=None):
    """Prepare f0/f1/f2, texts and latent DGP state; no future draw occurs."""
    config = DEFAULT_MECHANISM_CONFIG if config is None else config
    if scenario not in SCENARIOS or type(n_rows) is not int or n_rows < 2:
        raise ValueError("INVALID_SYNTHETIC_ENVIRONMENT")
    feature_rng = _rng(seed, config["rng"]["feature_stream"])
    negation = feature_rng.random(n_rows) < config["features"]["negation_probability"]
    digit = feature_rng.random(n_rows) < config["features"]["digit_probability"]
    question = feature_rng.random(n_rows) < config["features"]["question_probability"]
    gold = np.asarray(["A" if i % 2 == 0 else "B" for i in range(n_rows)])
    feature_rng.shuffle(gold)
    actions = ["open", "close", "set", "move", "find", "play", "send", "read"]
    objects = ["window", "lamp", "music", "message", "calendar", "weather", "ticket", "timer"]
    endings = ["", " today", " in the room", " before the meeting starts"]
    rows = []
    for i in range(n_rows):
        text = "please " + ("do not " if negation[i] else "")
        text += actions[int(feature_rng.integers(len(actions)))] + " the " + objects[int(feature_rng.integers(len(objects)))]
        text += " 2" if digit[i] else ""
        text += endings[int(feature_rng.integers(len(endings)))]
        text += "?" if question[i] else "."
        rows.append({"sample_id": f"synthetic:{i:04d}", "text": text, "gold_label": str(gold[i])})
    difficulty = _rng(seed, config["rng"]["difficulty_stream"]).random(n_rows)
    history_rng = _rng(seed, config["rng"]["history_stream"])
    correct = history_rng.random(n_rows) < config["history"]["f0_correct_probability"]
    correctness = [correct.copy()]
    negative_probability = np.full(n_rows, config["history"]["negative_flip_base"])
    if scenario == "overlap":
        negative_probability += config["history"]["overlap_each_group_coefficient"] * (negation.astype(int) + digit.astype(int))
    else:
        negative_probability += config["history"]["single_group_coefficient"] * negation
    for repair_probability in config["history"]["repair_probabilities"]:
        flip_draw = history_rng.random(n_rows)
        repair_draw = history_rng.random(n_rows)
        correct = np.where(correct, flip_draw >= negative_probability, repair_draw < repair_probability)
        correctness.append(correct.copy())
    wrong = np.where(gold == "A", "B", "A")
    history = np.column_stack([np.where(mask, gold, wrong) for mask in correctness])
    pool = np.flatnonzero(correctness[-1])
    confidence = config["reference_probability"]["predicted_class_intercept"] + config["reference_probability"]["difficulty_coefficient"] * difficulty[pool]
    probability_a = np.where(gold[pool] == "A", confidence, 1 - confidence)
    probabilities = np.column_stack([probability_a, 1 - probability_a])
    return {"rows": rows, "history": history, "pool_indices": pool.tolist(), "reference_probabilities": probabilities,
            "latent": {"negation": negation.tolist(), "digit": digit.tolist(), "question": question.tolist(), "difficulty": difficulty.tolist()}, "seed": seed, "scenario": scenario}


def select_suites(rows, history, pool, reference_probabilities, config=None):
    """Freeze candidates using only history inputs; never inspect latent state."""
    config = DEFAULT_MECHANISM_CONFIG if config is None else config
    texts = [rows[i]["text"] for i in pool]
    representation = dict(config["representation"])
    representation["ngram_range"] = tuple(representation["ngram_range"])
    vectors = TfidfVectorizer(**representation, dtype=np.float64).fit_transform(texts) if texts else sparse.csr_matrix((0, 0))
    hgc, diagnostics = select_hgc(rows, history, pool, vectors, config["budgets"], config["hgc"])
    ids = [rows[i]["sample_id"] for i in pool]
    labels = [rows[i]["gold_label"] for i in pool]
    ordered = np.asarray(sorted(range(len(pool)), key=lambda i: ids[i].encode()), dtype=int)
    anchors = _anchors(ids, labels, ordered)
    # Match HGC/baseline input normalization exactly, including rounding ties.
    norms = np.sqrt(np.asarray(vectors.multiply(vectors).sum(axis=1)).ravel())
    inverse = np.divide(1.0, norms, out=np.zeros_like(norms), where=norms > 0)
    facility_vectors = (sparse.diags(inverse) @ vectors).tocsr()
    facility = _facility_order(facility_vectors, anchors, ordered, min(max(config["budgets"]), len(pool)))
    risk = np.zeros(len(pool))
    for group in diagnostics["groups"]:
        risk[group["p_member_indices"]] += group["normalized_weight"]
    risk_order = sorted(ordered.tolist(), key=lambda i: (-risk[i], ids[i].encode()))
    reference_probabilities = np.asarray(reference_probabilities, dtype=float)
    if reference_probabilities.shape != (len(pool), 2) or not np.isfinite(reference_probabilities).all() or np.any((reference_probabilities < 0) | (reference_probabilities > 1)) or not np.allclose(reference_probabilities.sum(axis=1), 1, rtol=0, atol=1e-8) or not np.array_equal(np.asarray(["A", "B"])[reference_probabilities.argmax(axis=1)], np.asarray(labels)):
        raise ValueError("INVALID_SYNTHETIC_REFERENCE_PROBABILITIES")
    sorted_scores = np.sort(reference_probabilities, axis=1)
    margin = sorted_scores[:, -1] - sorted_scores[:, -2]
    margin_order = sorted(ordered.tolist(), key=lambda i: (margin[i], ids[i].encode()))
    selections = hgc.copy()
    for method, sequence in [("facility", facility), ("risk-top", risk_order), ("ref-margin", margin_order)]:
        selections.extend({"method": method, "seed": None, "budget": budget, "indices": sequence[:min(budget, len(pool))]} for budget in config["budgets"])
    for seed in config["selection_seeds"]:
        sequence = np.random.default_rng(seed).permutation(ordered).tolist()
        selections.extend({"method": "random", "seed": seed, "budget": budget, "indices": sequence[:min(budget, len(pool))]} for budget in config["budgets"])
    expected = {(m, s, b) for m in config["methods"] for s in (config["selection_seeds"] if m == "random" else [None]) for b in config["budgets"]}
    keys = [(s["method"], s["seed"], s["budget"]) for s in selections]
    if len(keys) != len(expected) or set(keys) != expected:
        raise ValueError("INCOMPLETE_SYNTHETIC_SUITES")
    compact = {k: diagnostics[k] for k in ["candidate_counts", "global_transitions", "fallback", "proxy_values", "risk_build_seconds", "similarity_build_seconds", "greedy_seconds", "total_seconds"]}
    compact["groups"] = [{k: g[k] for k in ["predicate", "predicate_sha256", "d_support", "p_support", "e", "b", "p0", "u", "q", "w", "normalized_weight"]} for g in diagnostics["groups"]]
    return selections, compact


def freeze_record(environment, regime, selections, diagnostics, config=None):
    config = DEFAULT_MECHANISM_CONFIG if config is None else config
    if regime not in config["margin_regimes"]:
        raise ValueError("UNKNOWN_MARGIN_REGIME")
    return {"environment_id": f"{environment['scenario']}--{regime}--seed{environment['seed']}", "seed": environment["seed"], "scenario": environment["scenario"], "margin_regime": regime,
            "rows": deepcopy(environment["rows"]), "history": environment["history"].tolist(), "pool_indices": environment["pool_indices"].copy(), "reference_probabilities": environment["reference_probabilities"].tolist(),
            "latent": deepcopy(environment["latent"]), "selections": deepcopy(selections), "hgc_diagnostics": deepcopy(diagnostics), "config_sha256": digest(config)}


def target_probability(record, config=None):
    config = DEFAULT_MECHANISM_CONFIG if config is None else config
    negation = np.asarray(record["latent"]["negation"], dtype=float)
    digit = np.asarray(record["latent"]["digit"], dtype=float)
    difficulty = np.asarray(record["latent"]["difficulty"], dtype=float)
    group = {"risk_persists": negation, "risk_reversed": 1 - negation, "new_risk": digit,
             "overlap": (negation + digit) / 2, "no_group_signal": np.zeros_like(negation)}[record["scenario"]]
    regime = config["margin_regimes"][record["margin_regime"]]
    probability = regime["intercept"] + regime["difficulty_coefficient"] * difficulty + regime["group_coefficient"] * group
    if not np.isfinite(probability).all() or np.any((probability < 0) | (probability > 1)):
        raise ValueError("INVALID_SYNTHETIC_TARGET_PROBABILITY")
    return probability


def generate_target(record, frozen_sha256, config=None):
    """Draw future labels only from an already sealed complete record."""
    config = DEFAULT_MECHANISM_CONFIG if config is None else config
    if digest(record) != frozen_sha256 or record["config_sha256"] != digest(config):
        raise ValueError("SYNTHETIC_PRETARGET_FREEZE_CHANGED")
    gold = np.asarray([r["gold_label"] for r in record["rows"]])
    current = np.asarray(record["history"])[:, 2] == gold
    rng = _rng(record["seed"], config["rng"]["target_stream"])
    flip_draw, repair_draw = rng.random(len(gold)), rng.random(len(gold))
    correct = np.where(current, flip_draw >= target_probability(record, config), repair_draw < config["target_wrong_to_correct_probability"])
    return np.where(correct, gold, np.where(gold == "A", "B", "A"))


def summarize(cells, config):
    """Average selection seeds inside an environment before averaging environments."""
    environment_rows = []
    for environment in sorted({cell["environment_id"] for cell in cells}):
        unit = [c for c in cells if c["environment_id"] == environment]
        for method in config["methods"]:
            for budget in config["budgets"]:
                subset = [c for c in unit if c["method"] == method and c["budget"] == budget]
                valid = [c["recall"] for c in subset if c["recall"] is not None]
                environment_rows.append({"environment_id": environment, "scenario": subset[0]["scenario"], "margin_regime": subset[0]["margin_regime"], "environment_seed": subset[0]["environment_seed"], "method": method, "budget": budget, "selection_seed_count": len(subset), "mean_detected": float(np.mean([c["detected"] for c in subset])), "recall": float(np.mean(valid)) if valid else None, "future_flip_count": subset[0]["future_flip_count"]})
    aggregate = []
    for scenario in config["scenarios"]:
        for regime in config["margin_regimes"]:
            for method in config["methods"]:
                for budget in config["budgets"]:
                    subset = [c for c in environment_rows if c["scenario"] == scenario and c["margin_regime"] == regime and c["method"] == method and c["budget"] == budget]
                    values = [c["recall"] for c in subset if c["recall"] is not None]
                    aggregate.append({"scenario": scenario, "margin_regime": regime, "method": method, "budget": budget, "environment_count": len(subset), "valid_environment_count": len(values), "mean_recall": float(np.mean(values)) if values else None, "std_recall": float(np.std(values)) if values else None, "min_recall": min(values) if values else None, "max_recall": max(values) if values else None})
    differences = []
    for scenario in config["scenarios"]:
        for regime in config["margin_regimes"]:
            for comparator in [m for m in config["methods"] if m != "hgc"]:
                paired = []
                for seed in config["environment_seeds"]:
                    subset = {r["method"]: r["recall"] for r in environment_rows if r["scenario"] == scenario and r["margin_regime"] == regime and r["environment_seed"] == seed and r["budget"] == config["primary_budget"]}
                    if subset["hgc"] is not None and subset[comparator] is not None:
                        paired.append(subset["hgc"] - subset[comparator])
                differences.append({"scenario": scenario, "margin_regime": regime, "budget": config["primary_budget"], "comparator": comparator, "paired_environment_count": len(paired), "mean_hgc_recall_difference": float(np.mean(paired)) if paired else None, "std_difference": float(np.std(paired)) if paired else None, "win_count": sum(v > config["numerical_tie_tolerance"] for v in paired), "tie_count": sum(abs(v) <= config["numerical_tie_tolerance"] for v in paired), "loss_count": sum(v < -config["numerical_tie_tolerance"] for v in paired)})
    return environment_rows, aggregate, differences


def run(config, output, registration_path=None):
    validate_config(config)
    output = Path(output)
    if output.exists():
        raise ValueError("OUTPUT_ALREADY_EXISTS_USE_NEW_DIRECTORY")
    output.mkdir(parents=True)
    begin = time.perf_counter()
    events = []

    def event(kind, **details):
        value = {"event": kind, "time": utc(), "details": details, "previous_sha256": digest(events[-1]) if events else None}
        events.append(value)
        with (output / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(canonical(value).decode() + "\n")
            stream.flush()

    prereg = {"purpose": config["purpose"], "registered_at": utc(), "config": config, "config_sha256": digest(config), "code_files": {str(p.relative_to(ROOT)): file_hash(p) for p in sorted((ROOT / "experiments/preflight").glob("*.py"))}, "dependency_lock_sha256": file_hash(ROOT / "experiments/uv.lock"), "git_base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()), "global_registration_sha256": file_hash(registration_path) if registration_path else None}
    write_json(output / "preregistration.json", prereg)
    event("REGISTERED", config_sha256=digest(config))
    records = []
    frozen_files = {"preregistration.json": file_hash(output / "preregistration.json")}
    # Same-seed regimes share history and selectors; this is intentional paired
    # DGP comparison, not extra independent evidence or parameter tuning.
    for scenario in config["scenarios"]:
        for seed in config["environment_seeds"]:
            environment = build_environment(seed, scenario, config["n_rows"], config)
            selections, diagnostics = select_suites(environment["rows"], environment["history"], environment["pool_indices"], environment["reference_probabilities"], config)
            for regime in config["margin_regimes"]:
                record = freeze_record(environment, regime, selections, diagnostics, config)
                name = f"environments/{record['environment_id']}.json"
                frozen_files[name] = write_json(output / name, record)
                records.append((name, digest(record)))
                event("ENVIRONMENT_SUITES_READY", environment_id=record["environment_id"], suite_count=len(selections), semantic_record_sha256=digest(record), file_sha256=frozen_files[name])
            if len(records) % 40 == 0:
                print(json.dumps({"stage": "PRETARGET_GRID", "prepared_environments": len(records)}), flush=True)
    expected_environments = len(config["scenarios"]) * len(config["margin_regimes"]) * len(config["environment_seeds"])
    if len(records) != expected_environments:
        raise ValueError("INCOMPLETE_SYNTHETIC_ENVIRONMENT_MATRIX")
    write_json(output / "matrix-freeze.json", {"schema_version": "mechanism-grid-freeze-v1", "purpose": config["purpose"], "frozen_at": utc(), "config_sha256": digest(config), "environment_count": len(records), "files": frozen_files, "semantic_record_hashes": dict(records), "targets_generated": False})
    event("ALL_ENVIRONMENT_SUITES_FROZEN", environment_count=len(records), freeze_file_sha256=file_hash(output / "matrix-freeze.json"))
    for name, expected in frozen_files.items():
        if file_hash(output / name) != expected:
            raise ValueError("FROZEN_SYNTHETIC_INPUT_CHANGED")
    cells, summaries = [], []
    for index, (name, frozen_sha) in enumerate(records):
        record = json.loads((output / name).read_text())
        target = generate_target(record, frozen_sha, config)
        pool = np.asarray(record["pool_indices"], dtype=int)
        gold = [r["gold_label"] for r in record["rows"]]
        history = np.asarray(record["history"])
        computed = evaluate_cells(np.asarray(gold)[pool].tolist(), history[pool], target[pool], record["selections"])
        for cell in computed:
            cell.update(environment_id=record["environment_id"], scenario=record["scenario"], margin_regime=record["margin_regime"], environment_seed=record["seed"])
        cells.extend(computed)
        diag = record["hgc_diagnostics"]
        summary = {"environment_id": record["environment_id"], "scenario": record["scenario"], "margin_regime": record["margin_regime"], "environment_seed": record["seed"], "d_count": len(gold), "pool_count": len(pool), "future_flip_count": computed[0]["future_flip_count"], "historically_unseen_flips": computed[0]["historically_unseen"]["denominator"], "repaired_then_recurred_flips": computed[0]["repaired_then_recurred"]["denominator"], "hgc_group_count": len(diag["groups"]), "hgc_fallback": diag["fallback"], "hgc_proxy_values": diag["proxy_values"], "target_generated_after_global_grid_freeze": True}
        summaries.append(summary)
        with _target_stream(output, Path(name).stem) as stream:
            np.savez_compressed(stream, predictions=target, sample_ids=np.asarray([r["sample_id"] for r in record["rows"]]))
        event("ENVIRONMENT_EVALUATED", environment_id=record["environment_id"], future_flips=summary["future_flip_count"])
        if (index + 1) % 40 == 0:
            print(json.dumps({"stage": "TARGET_EVALUATION", "evaluated_environments": index + 1}), flush=True)
    environment_rows, aggregate, differences = summarize(cells, config)
    write_json(output / "evaluation-cells.json", cells)
    write_json(output / "environment-aggregates.json", environment_rows)
    report = {"schema_version": "mechanism-check-report-v1", "purpose": config["purpose"], "completed_at": utc(), "config_sha256": digest(config), "global_freeze_sha256": file_hash(output / "matrix-freeze.json"), "environment_count": len(records), "cell_count": len(cells), "environment_summaries": summaries, "aggregates": aggregate, "primary_paired_differences": differences, "wall_seconds": time.perf_counter() - begin, "formal_gate_approved": False, "natural_model_effect_proven": False, "limitations": config["limitations"]}
    write_json(output / "report.json", report)
    event("MECHANISM_CHECK_COMPLETE", environment_count=len(records), cell_count=len(cells), report_sha256=file_hash(output / "report.json"))
    return report



def verify(output):
    """Replay this fixed synthetic DGP/scorer; no natural-model inference."""
    output = Path(output)
    prereg = json.loads((output / "preregistration.json").read_text())
    config = prereg["config"]
    validate_config(config)
    frozen = json.loads((output / "matrix-freeze.json").read_text())
    expected = [f"environments/{scenario}--{regime}--seed{seed}.json" for scenario in config["scenarios"] for seed in config["environment_seeds"] for regime in config["margin_regimes"]]
    if frozen["schema_version"] != "mechanism-grid-freeze-v1" or frozen["purpose"] != config["purpose"] or frozen["targets_generated"] is not False or frozen["environment_count"] != len(expected):
        raise ValueError("MECHANISM_FREEZE_IDENTITY_MISMATCH")
    if set(frozen["files"]) != {"preregistration.json", *expected} or set(frozen["semantic_record_hashes"]) != set(expected):
        raise ValueError("MECHANISM_FREEZE_FILE_SET_MISMATCH")
    if digest(config) != prereg["config_sha256"] or frozen["config_sha256"] != digest(config):
        raise ValueError("MECHANISM_CONFIG_HASH_MISMATCH")
    for name, expected_sha in frozen["files"].items():
        if file_hash(output / name) != expected_sha:
            raise ValueError("FROZEN_SYNTHETIC_INPUT_CHANGED")
    cells, cache, environment_ids = [], {}, []
    ignored_times = {"risk_build_seconds", "similarity_build_seconds", "greedy_seconds", "total_seconds"}
    for name in expected:
        record = json.loads((output / name).read_text())
        environment_id = Path(name).stem
        if record["environment_id"] != environment_id or digest(record) != frozen["semantic_record_hashes"][name]:
            raise ValueError("MECHANISM_RECORD_IDENTITY_MISMATCH")
        key = (record["scenario"], record["seed"])
        if key not in cache:
            environment = build_environment(record["seed"], record["scenario"], config["n_rows"], config)
            suites, diagnostics = select_suites(environment["rows"], environment["history"], environment["pool_indices"], environment["reference_probabilities"], config)
            cache[key] = (environment, suites, diagnostics)
        environment, suites, diagnostics = cache[key]
        rebuilt = freeze_record(environment, record["margin_regime"], suites, diagnostics, config)
        left = {k: v for k, v in record.items() if k != "hgc_diagnostics"}
        right = {k: v for k, v in rebuilt.items() if k != "hgc_diagnostics"}
        if left != right or {k: v for k, v in record["hgc_diagnostics"].items() if k not in ignored_times} != {k: v for k, v in diagnostics.items() if k not in ignored_times}:
            raise ValueError("MECHANISM_PRETARGET_REPLAY_MISMATCH")
        target = generate_target(record, frozen["semantic_record_hashes"][name], config)
        with np.load(output / "targets" / (environment_id + ".npz"), allow_pickle=False) as stored:
            if set(stored.files) != {"predictions", "sample_ids"} or stored["sample_ids"].tolist() != [r["sample_id"] for r in record["rows"]] or not np.array_equal(stored["predictions"], target):
                raise ValueError("SYNTHETIC_TARGET_REPLAY_MISMATCH")
        pool = np.asarray(record["pool_indices"], dtype=int)
        gold = np.asarray([row["gold_label"] for row in record["rows"]])
        computed = evaluate_cells(gold[pool].tolist(), np.asarray(record["history"])[pool], target[pool], record["selections"])
        for cell in computed:
            cell.update(environment_id=environment_id, scenario=record["scenario"], margin_regime=record["margin_regime"], environment_seed=record["seed"])
        cells.extend(computed)
        environment_ids.append(environment_id)
    if cells != json.loads((output / "evaluation-cells.json").read_text()):
        raise ValueError("MECHANISM_CELL_REPLAY_MISMATCH")
    environment_rows, aggregate, differences = summarize(cells, config)
    if environment_rows != json.loads((output / "environment-aggregates.json").read_text()):
        raise ValueError("MECHANISM_ENVIRONMENT_AGGREGATE_MISMATCH")
    report = json.loads((output / "report.json").read_text())
    if report["aggregates"] != aggregate or report["primary_paired_differences"] != differences or report["environment_count"] != len(expected) or report["cell_count"] != len(cells) or report["config_sha256"] != digest(config) or report["global_freeze_sha256"] != file_hash(output / "matrix-freeze.json"):
        raise ValueError("MECHANISM_REPORT_REPLAY_MISMATCH")
    if report["formal_gate_approved"] is not False or report["natural_model_effect_proven"] is not False:
        raise ValueError("SYNTHETIC_CLAIM_SCOPE_MISMATCH")
    events = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
    expected_event_names = ["REGISTERED", *(["ENVIRONMENT_SUITES_READY"] * len(expected)), "ALL_ENVIRONMENT_SUITES_FROZEN", *(["ENVIRONMENT_EVALUATED"] * len(expected)), "MECHANISM_CHECK_COMPLETE"]
    if [e["event"] for e in events] != expected_event_names:
        raise ValueError("MECHANISM_EVENT_STAGE_OR_COUNT_MISMATCH")
    for i, event in enumerate(events):
        if event["previous_sha256"] != (digest(events[i - 1]) if i else None):
            raise ValueError("MECHANISM_EVENT_HASH_CHAIN_MISMATCH")
    if [e["details"]["environment_id"] for e in events if e["event"] == "ENVIRONMENT_SUITES_READY"] != environment_ids or [e["details"]["environment_id"] for e in events if e["event"] == "ENVIRONMENT_EVALUATED"] != environment_ids:
        raise ValueError("MECHANISM_EVENT_ENVIRONMENT_SET_MISMATCH")
    freeze_event = events[1 + len(expected)]
    if freeze_event["details"] != {"environment_count": len(expected), "freeze_file_sha256": file_hash(output / "matrix-freeze.json")} or events[-1]["details"] != {"environment_count": len(expected), "cell_count": len(cells), "report_sha256": file_hash(output / "report.json")}:
        raise ValueError("MECHANISM_EVENT_FREEZE_OR_REPORT_HASH_MISMATCH")
    return {"status": "PASS", "purpose": config["purpose"], "environment_count": len(expected), "frozen_files_verified": len(frozen["files"]), "selection_environments_replayed": len(cache), "target_environments_replayed": len(expected), "cells_recomputed": len(cells), "aggregate_rows_recomputed": len(aggregate), "paired_comparisons_recomputed": len(differences), "event_count": len(events), "all_suites_frozen_before_any_target_event": True, "natural_model_effect_proven": False, "formal_gate_approved": False, "limitations": ["Replays the existing generator, HGC and metric implementations; not an independent formula proof.", "Synthetic mechanisms do not establish natural task benefit or cross-model independence."]}


def _target_stream(output, stem):
    path = output / "targets" / (stem + ".npz")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("xb")


def main():
    parser = argparse.ArgumentParser(description="固定合成机制检查；不训练真实模型，不代表自然数据收益")
    parser.add_argument("--registered-config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify:
        if args.registered_config or args.output:
            parser.error("--verify cannot be combined with run arguments")
        with threadpool_limits(limits=2):
            print(json.dumps(verify(args.verify), ensure_ascii=False, indent=2))
        return
    if not args.registered_config or not args.output:
        parser.error("--registered-config and --output are required for a run")
    registered = json.loads(args.registered_config.read_text())
    config = registered["mechanisms"] if "mechanisms" in registered else registered
    with threadpool_limits(limits=config["cpu_threads"]):
        report = run(config, args.output, args.registered_config)
    print(json.dumps({"purpose": report["purpose"], "environment_count": report["environment_count"], "cell_count": report["cell_count"], "wall_seconds": report["wall_seconds"], "natural_model_effect_proven": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
