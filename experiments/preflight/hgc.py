"""Pure history-only Historical Group Coverage for the development pilot.

Risk is estimated on all supplied discovery rows, while suites use precisely
the f2-correct pool. No target version, model, artifact path or I/O is accepted.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import time
import unicodedata
from copy import deepcopy
from fractions import Fraction
from numbers import Integral, Real

import numpy as np
from scipy import sparse

from .baselines import _anchors


DEFAULT_HGC_CONFIG = {
    "lambda": 0.5,
    "m": 30,
    "k": 3,
    "min_support": 10,
    "max_groups": 30,
    "jaccard": 0.9,
    "length_boundaries": [10, 20, 40],
    "negation_terms": ["不", "没", "无", "别", "未", "不要", "不能", "not", "no", "never", "without"],
    "question_marks": ["?", "？"],
}


class HgcInputError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code, message):
    raise HgcInputError(code, message)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _validate_config(config):
    if not isinstance(config, dict) or set(config) != set(DEFAULT_HGC_CONFIG):
        _fail("INVALID_CONFIG", "HGC requires the complete declared configuration without extra fields.")
    for field in ("m", "k", "min_support", "max_groups"):
        value = config[field]
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < 1:
            _fail("INVALID_CONFIG", "HGC count parameters must be positive integers.")
    if config["max_groups"] > 30:
        _fail("INVALID_CONFIG", "The pilot permits at most 30 risk groups.")
    for field in ("lambda", "jaccard"):
        value = config[field]
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or not math.isfinite(value) or not 0 <= value <= 1:
            _fail("INVALID_CONFIG", "HGC mixing and duplicate thresholds must lie in [0,1].")
    boundaries = config["length_boundaries"]
    if not isinstance(boundaries, list) or not boundaries or any(isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < 1 for value in boundaries) or boundaries != sorted(set(boundaries)):
        _fail("INVALID_CONFIG", "Length boundaries must be strictly increasing positive integers.")
    for field in ("negation_terms", "question_marks"):
        values = config[field]
        if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value for value in values) or len(values) != len(set(values)):
            _fail("INVALID_CONFIG", "Feature lexicons must contain unique nonempty strings.")
    try:
        _canonical(config)
    except (TypeError, ValueError, UnicodeError):
        _fail("INVALID_CONFIG", "HGC configuration must contain canonical JSON values.")


def _features(row, config):
    text = " ".join(unicodedata.normalize("NFKC", row["text"]).split())
    size = len(text)
    lower = 1
    length_bin = None
    for upper in config["length_boundaries"]:
        if size <= upper:
            length_bin = f"{lower}-{upper}"
            break
        lower = upper + 1
    if length_bin is None:
        length_bin = f"{lower}+"
    negation = False
    for term in config["negation_terms"]:
        if re.fullmatch(r"[A-Za-z]+", term):
            found = re.search(r"\b" + re.escape(term) + r"\b", text, flags=re.IGNORECASE) is not None
        else:
            found = term in text
        if found:
            negation = True
            break
    return {
        "gold_label": row["gold_label"],
        "length_bin": length_bin,
        "has_negation": negation,
        "has_digit": any(character.isdigit() for character in text),
        "has_question_mark": any(mark in text for mark in config["question_marks"]),
    }


def _validate_inputs(rows, history, pool_indices, representations, budgets, config):
    _validate_config(config)
    if not isinstance(rows, list):
        _fail("INVALID_ROWS", "Discovery rows must be a list.")
    ids = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"sample_id", "text", "gold_label"}:
            _fail("INVALID_ROWS", "Discovery rows accept only sample_id, text and gold_label.")
        if any(not isinstance(row[field], str) or not row[field] for field in row):
            _fail("INVALID_ROWS", "Discovery row fields must be nonempty strings.")
        try:
            for value in row.values():
                value.encode("utf-8")
        except UnicodeError:
            _fail("INVALID_ROWS", "Discovery rows must contain valid Unicode.")
        if not " ".join(unicodedata.normalize("NFKC", row["text"]).split()):
            _fail("INVALID_ROWS", "Normalized discovery text must be nonempty.")
        ids.append(row["sample_id"])
    if len(ids) != len(set(ids)):
        _fail("DUPLICATE_IDS", "Discovery sample IDs must be unique.")
    history = np.asarray(history)
    if history.shape != (len(rows), 3):
        _fail("HISTORY_SHAPE", "History must contain exactly f0/f1/f2 labels for every discovery row.")
    if any(not isinstance(label, (str, np.str_)) or not label for label in history.flat):
        _fail("INVALID_HISTORY", "History must contain nonempty parsed label strings.")
    if not isinstance(pool_indices, list) or any(isinstance(index, (bool, np.bool_)) or not isinstance(index, Integral) or not 0 <= index < len(rows) for index in pool_indices):
        _fail("INVALID_POOL", "Pool indices must address the supplied discovery rows.")
    if len(pool_indices) != len(set(pool_indices)):
        _fail("INVALID_POOL", "Pool indices must be unique.")
    gold = np.asarray([row["gold_label"] for row in rows], dtype=str)
    expected = set(np.flatnonzero(history[:, 2] == gold).tolist())
    if set(pool_indices) != expected:
        _fail("POOL_MISMATCH", "Pool must be exactly the f2-correct discovery rows; truncation is forbidden.")
    if not isinstance(budgets, list) or not budgets or any(isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < 1 for value in budgets) or len(budgets) != len(set(budgets)):
        _fail("INVALID_BUDGETS", "Budgets must be unique positive integers.")
    try:
        if np.iscomplexobj(representations):
            _fail("INVALID_REPRESENTATION", "Complex text representations are not supported.")
        vectors = sparse.csr_matrix(representations, dtype=np.float64, copy=True)
    except (ValueError, TypeError, OverflowError) as exc:
        if isinstance(exc, HgcInputError):
            raise
        _fail("INVALID_REPRESENTATION", "Text representations must be a nonnegative numeric matrix.")
    if vectors.ndim != 2 or vectors.shape[0] != len(pool_indices):
        _fail("REPRESENTATION_SHAPE", "Text representation rows must follow pool_indices exactly.")
    if not np.isfinite(vectors.data).all() or np.any(vectors.data < 0):
        _fail("INVALID_REPRESENTATION", "Text representations must be finite and nonnegative.")
    norms = np.sqrt(np.asarray(vectors.multiply(vectors).sum(axis=1)).ravel())
    if not np.isfinite(norms).all():
        _fail("INVALID_REPRESENTATION", "Text representation norms must be finite.")
    inverse = np.divide(1.0, norms, out=np.zeros_like(norms), where=norms > 0)
    vectors = (sparse.diags(inverse) @ vectors).tocsr()
    return history, gold, vectors


def _risk_groups(rows, history, gold, pool_indices, config):
    old_correct = history[:, :2] == gold[:, None]
    negative_flip = old_correct & (history[:, 1:] != gold[:, None])
    global_e = old_correct.sum(axis=0).tolist()
    global_b = negative_flip.sum(axis=0).tolist()
    global_p0 = [Fraction(global_b[t], global_e[t]) if global_e[t] else None for t in range(2)]
    valid_transitions = [t for t in range(2) if global_e[t]]
    global_transitions = [
        {"transition": f"f{t}-f{t + 1}", "e": global_e[t], "b": global_b[t], "p0": float(global_p0[t]) if global_p0[t] is not None else None, "valid": bool(global_e[t]), "excluded_reason": None if global_e[t] else "ZERO_GLOBAL_OLD_CORRECT"}
        for t in range(2)
    ]
    features = [_features(row, config) for row in rows]
    atoms = []
    # Both Boolean values are part of the fixed feature catalog, even if one
    # has empty support. Other values are the observed fixed input categories.
    for feature in sorted(("gold_label", "length_bin", "has_negation", "has_digit", "has_question_mark")):
        values = [False, True] if feature.startswith("has_") else sorted({row[feature] for row in features}, key=lambda value: _canonical(value))
        for value in sorted(values, key=_canonical):
            atom = {"feature": feature, "op": "eq", "value": value}
            members = frozenset(index for index, row in enumerate(features) if row[feature] == value)
            atoms.append((atom, members))
    conditions = [([atom], members) for atom, members in atoms]
    conditions.extend(([left, right], left_members & right_members) for (left, left_members), (right, right_members) in itertools.combinations(atoms, 2) if left["feature"] != right["feature"])
    counts = {"atomic_conditions": len(atoms), "enumerated_candidates": len(conditions), "nonempty_candidates": 0, "positive_weight_candidates": 0, "positive_weight_with_pool_candidates": 0, "excluded_positive_no_pool": 0, "jaccard_duplicates": 0, "omitted_by_group_cap": 0, "retained_groups": 0}
    candidates = []
    d_to_p = {int(d_index): p_index for p_index, d_index in enumerate(pool_indices)}
    for condition, members in conditions:
        if not members:
            continue
        counts["nonempty_candidates"] += 1
        ordered_d = sorted(members, key=lambda index: rows[index]["sample_id"].encode("utf-8"))
        e = old_correct[ordered_d].sum(axis=0).tolist()
        b = negative_flip[ordered_d].sum(axis=0).tolist()
        p, u, low_support = [], [], []
        for t in range(2):
            shrunk = (Fraction(b[t]) + config["m"] * global_p0[t]) / (e[t] + config["m"]) if global_p0[t] is not None else None
            low = e[t] < config["min_support"]
            uplift = max(Fraction(0), shrunk - global_p0[t]) if shrunk is not None and not low else Fraction(0)
            p.append(shrunk)
            u.append(uplift)
            low_support.append(low)
        if valid_transitions:
            q = Fraction(sum(u[t] > 0 for t in valid_transitions), len(valid_transitions))
            weight = sum((u[t] for t in valid_transitions), Fraction(0)) / len(valid_transitions) * (1 + q) / 2
        else:
            q = weight = Fraction(0)
        if not weight:
            continue
        counts["positive_weight_candidates"] += 1
        ordered_p = [d_to_p[index] for index in ordered_d if index in d_to_p]
        if not ordered_p:
            counts["excluded_positive_no_pool"] += 1
            continue
        counts["positive_weight_with_pool_candidates"] += 1
        predicate = {"all": condition}
        canonical = _canonical(predicate)
        public = {
            "predicate": predicate,
            "predicate_canonical": canonical.decode("utf-8"),
            "predicate_sha256": hashlib.sha256(canonical).hexdigest(),
            "d_member_indices": [int(index) for index in ordered_d],
            "p_member_indices": [int(index) for index in ordered_p],
            "d_member_sample_ids": [rows[index]["sample_id"] for index in ordered_d],
            "p_member_sample_ids": [rows[pool_indices[index]]["sample_id"] for index in ordered_p],
            "d_support": len(ordered_d), "p_support": len(ordered_p),
            "e": e, "b": b,
            "p0": [float(value) if value is not None else None for value in global_p0],
            "p": [float(value) if value is not None else None for value in p],
            "u": [float(value) for value in u],
            "low_support": low_support,
            "valid_transition_count": len(valid_transitions),
            "q": float(q), "w": float(weight),
            "statistical_confirmation": "NOT_PERFORMED",
        }
        candidates.append((weight, canonical, members, public))
    candidates.sort(key=lambda candidate: (-candidate[0], -candidate[3]["p_support"], candidate[1]))
    kept = []
    for candidate in candidates:
        if any(Fraction(len(candidate[2] & previous[2]), len(candidate[2] | previous[2])) >= Fraction(str(config["jaccard"])) for previous in kept):
            counts["jaccard_duplicates"] += 1
            continue
        if len(kept) >= config["max_groups"]:
            counts["omitted_by_group_cap"] += 1
            continue
        kept.append(candidate)
    total_weight = sum((candidate[0] for candidate in kept), Fraction(0))
    groups = []
    for rank, candidate in enumerate(kept, 1):
        public = candidate[3]
        public["rank"] = rank
        public["normalized_weight"] = float(candidate[0] / total_weight)
        groups.append(public)
    counts["retained_groups"] = len(groups)
    return groups, global_transitions, counts


def select_hgc(
    rows: list[dict],
    history: np.ndarray,
    pool_indices: list[int],
    representations,
    budgets: list[int],
    config: dict,
) -> tuple[list[dict], dict]:
    """Return HGC selections indexed relative to P, plus JSON-safe diagnostics.

    D/P membership indices in each retained group's diagnostics are explicitly
    named. ``anchor_indices`` and output ``indices`` both address P, whose
    order is exactly ``pool_indices`` and the supplied representation matrix.
    All requested budgets share one objective and one maximum-budget prefix.
    """
    begin = time.perf_counter()
    history, gold, vectors = _validate_inputs(rows, history, pool_indices, representations, budgets, config)
    risk_begin = time.perf_counter()
    groups, transitions, candidate_counts = _risk_groups(rows, history, gold, pool_indices, config)
    risk_seconds = time.perf_counter() - risk_begin
    pool_ids = [rows[index]["sample_id"] for index in pool_indices]
    pool_labels = [rows[index]["gold_label"] for index in pool_indices]
    n = len(pool_indices)
    sorted_indices = np.asarray(sorted(range(n), key=lambda index: pool_ids[index].encode("utf-8")), dtype=int)
    similarity_begin = time.perf_counter()
    anchors = _anchors(pool_ids, pool_labels, sorted_indices)
    similarities = np.asarray((vectors[anchors] @ vectors.T).toarray(), dtype=np.float64) if n else np.empty((0, 0), dtype=np.float64)
    np.clip(similarities, 0.0, 1.0, out=similarities)
    similarity_seconds = time.perf_counter() - similarity_begin
    weights = np.asarray([group["normalized_weight"] for group in groups], dtype=np.float64)
    membership = np.zeros((len(groups), n), dtype=bool)
    for index, group in enumerate(groups):
        membership[index, group["p_member_indices"]] = True
    effective_lambda = float(config["lambda"]) if groups else 0.0
    fallback = "EMPTY_POOL" if not n else "NO_POSITIVE_RISK_REPRESENTATION_ONLY" if not groups else "NONE"
    greedy_begin = time.perf_counter()
    coverage = np.zeros(len(anchors), dtype=np.float64)
    group_counts = np.zeros(len(groups), dtype=np.int64)
    selected = np.zeros(n, dtype=bool)
    order, trace = [], []
    prefix_metrics = [{"G": 0.0, "F": 0.0, "J": 0.0}]
    for rank in range(1, min(max(budgets), n) + 1):
        delta_f = np.maximum(similarities - coverage[:, None], 0.0).sum(axis=0) / len(anchors)
        delta_g = ((weights / config["k"]) * (group_counts < config["k"])) @ membership if groups else np.zeros(n, dtype=np.float64)
        # Lambda=0 and the no-risk fallback use exactly the Facility gains,
        # preserving its floating-point tie behavior as well as its objective.
        gains = delta_f.copy() if effective_lambda == 0 else effective_lambda * delta_g + (1 - effective_lambda) * delta_f
        gains[selected] = -np.inf
        best = int(sorted_indices[int(np.argmax(gains[sorted_indices]))])
        order.append(best)
        selected[best] = True
        group_counts += membership[:, best]
        np.maximum(coverage, similarities[:, best], out=coverage)
        current_g = float(weights @ np.minimum(1.0, group_counts / config["k"])) if groups else 0.0
        current_f = float(coverage.mean())
        current_j = effective_lambda * current_g + (1 - effective_lambda) * current_f
        metrics = {"G": current_g, "F": current_f, "J": current_j}
        prefix_metrics.append(metrics)
        trace.append({"rank": rank, "index": best, "sample_id": pool_ids[best], "delta_G": float(delta_g[best]), "delta_F": float(delta_f[best]), "delta_J": float(gains[best]), **metrics})
    greedy_seconds = time.perf_counter() - greedy_begin
    selections, proxy_values = [], []
    for budget in budgets:
        size = min(int(budget), n)
        selections.append({"method": "hgc", "seed": None, "budget": int(budget), "indices": order[:size]})
        proxy_values.append({"budget": int(budget), "actual_size": size, **prefix_metrics[size]})
    diagnostics = {
        "method": "hgc", "config": deepcopy(config), "d_count": len(rows), "pool_count": n,
        "candidate_counts": candidate_counts, "groups": groups, "weights": weights.tolist(),
        "global_transitions": transitions, "valid_transition_count": sum(transition["valid"] for transition in transitions),
        "anchor_indices": [int(index) for index in anchors], "anchor_sample_ids": [pool_ids[index] for index in anchors],
        "fallback": fallback, "effective_lambda": effective_lambda,
        "proxy_values": proxy_values, "greedy_trace": trace,
        "risk_build_seconds": risk_seconds, "similarity_build_seconds": similarity_seconds,
        "greedy_seconds": greedy_seconds, "total_seconds": time.perf_counter() - begin,
    }
    return selections, diagnostics
