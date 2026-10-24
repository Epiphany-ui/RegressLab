"""History-only baselines for a bounded CPU development pilot.

Indices in every result address the supplied current-correct pool. The caller
fits the text representation on that pool and freezes selections before running
the held-out update. This module has no model, file, or evaluation access.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from numbers import Integral
from time import perf_counter

import numpy as np
from scipy import sparse


class BaselineInputError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _reject(code, message):
    raise BaselineInputError(code, message)


def _ids(values, name, *, unique):
    if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
        _reject("INVALID_IDENTIFIERS", f"{name} must contain nonempty strings.")
    try:
        for value in values:
            value.encode("utf-8")
    except UnicodeError:
        _reject("INVALID_IDENTIFIERS", f"{name} must contain valid Unicode.")
    if unique and len(values) != len(set(values)):
        _reject("DUPLICATE_IDENTIFIERS", f"{name} must be unique.")


def _integer_list(values, name, *, minimum):
    if not isinstance(values, list) or not values:
        _reject("INVALID_CONFIGURATION", f"{name} must be a nonempty list.")
    if any(isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < minimum for value in values):
        _reject("INVALID_CONFIGURATION", f"{name} contains an invalid integer.")
    if len(values) != len(set(values)):
        _reject("DUPLICATE_CONFIGURATION", f"{name} must be unique.")


def _proportional_quotas(labels, size):
    """Largest remainder allocation using exact integer arithmetic."""
    counts = Counter(labels)
    classes = sorted(counts, key=lambda value: value.encode("utf-8"))
    total = len(labels)
    if not total:
        return {}
    quotas = {label: size * counts[label] // total for label in classes}
    remainder_order = sorted(classes, key=lambda label: (-(size * counts[label] % total), label.encode("utf-8")))
    remaining = size - sum(quotas.values())
    for label in remainder_order[:remaining]:
        quotas[label] += 1
    return quotas


def _anchors(sample_ids, labels, sorted_indices):
    """Frozen class-proportional anchors, capped at 256, with no class floor."""
    quotas = _proportional_quotas(labels, min(256, len(sample_ids)))
    selected = []
    for label in sorted(quotas, key=lambda value: value.encode("utf-8")):
        members = [index for index in sorted_indices if labels[index] == label]
        members.sort(key=lambda index: (
            hashlib.sha256(("anchor-v2|42|" + sample_ids[index]).encode("utf-8")).digest(),
            sample_ids[index].encode("utf-8"),
        ))
        selected.extend(members[:quotas[label]])
    return sorted(selected, key=lambda index: sample_ids[index].encode("utf-8"))


def _facility_order(vectors, anchors, sorted_indices, size):
    if not size:
        return []
    # The largest dense array is anchors x pool, never pool x pool when n>256.
    similarities = np.asarray((vectors[anchors] @ vectors.T).toarray(), dtype=np.float64)
    np.clip(similarities, 0.0, 1.0, out=similarities)
    coverage = np.zeros(len(anchors), dtype=np.float64)
    selected = np.zeros(vectors.shape[0], dtype=bool)
    ordered = []
    for _ in range(size):
        gains = np.maximum(similarities - coverage[:, None], 0.0).sum(axis=0) / len(anchors)
        gains[selected] = -np.inf
        # sorted_indices supplies the explicit source-ID tie break to argmax.
        best = int(sorted_indices[int(np.argmax(gains[sorted_indices]))])
        ordered.append(best)
        selected[best] = True
        np.maximum(coverage, similarities[:, best], out=coverage)
    return ordered


def _kcenter_order(vectors, sorted_indices, seed, size):
    if not size:
        return []
    rng = np.random.default_rng(seed)
    first = int(sorted_indices[int(rng.integers(len(sorted_indices)))])
    selected = np.zeros(vectors.shape[0], dtype=bool)
    nearest = np.full(vectors.shape[0], np.inf, dtype=np.float64)
    ordered = []
    best = first
    for _ in range(size):
        ordered.append(best)
        selected[best] = True
        similarity = np.asarray((vectors @ vectors[best].T).toarray()).ravel()
        np.clip(similarity, 0.0, 1.0, out=similarity)
        np.minimum(nearest, 1.0 - similarity, out=nearest)
        nearest[selected] = -np.inf
        best = int(sorted_indices[int(np.argmax(nearest[sorted_indices]))])
    return ordered


def select_baselines(
    sample_ids: list[str],
    labels: list[str],
    history: np.ndarray,
    reference_probabilities: np.ndarray,
    representations,
    class_labels: list[str],
    budgets: list[int],
    seeds: list[int],
    *,
    timings: list[dict] | None = None,
) -> list[dict]:
    """Select nine baselines from f2-correct rows using only f0/f1/f2.

    ``history`` contains predicted label strings with shape (n, 3).
    ``reference_probabilities`` contains f2 scores with columns ordered exactly
    as ``class_labels``. Rows of ``representations`` are nonnegative TF-IDF
    vectors fitted by the caller using only the candidate pool. Zero vectors
    have similarity zero, including to another zero vector.

    Random, Stratified, PastFlip and KCenter run once for each supplied seed;
    reference-score rankings and Facility are deterministic (seed=None).
    Every ranking/greedy sequence is computed once, then shared across budgets.
    Stratified recomputes its proportional quotas for each effective budget.

    Optional ``timings`` receives one wall-time row per method/seed, covering
    its maximum-budget selection and every requested budget result. Nominal
    ``max_budget`` is max(budgets), including when the pool is smaller. A
    separate ``__shared_validation__`` row covers input validation, vector
    normalization and common ID sorting. Method-specific preparation (including
    Facility anchors and similarities) belongs to that method's row. Caller-fit
    representations and model inference are excluded. Random permutations and
    method scores are recomputed within each method/seed so one row describes
    a standalone selection, not twenty seeds' combined deployment cost.
    """
    shared_begin = perf_counter()
    _ids(sample_ids, "sample_ids", unique=True)
    _ids(labels, "labels", unique=False)
    _ids(class_labels, "class_labels", unique=True)
    _integer_list(budgets, "budgets", minimum=1)
    _integer_list(seeds, "seeds", minimum=0)
    if len(class_labels) < 2:
        _reject("INVALID_LABELSET", "At least two frozen class labels are required.")
    n = len(sample_ids)
    if len(labels) != n or not set(labels) <= set(class_labels):
        _reject("LABEL_MISMATCH", "Gold labels must match the frozen class vocabulary.")
    history = np.asarray(history)
    if history.shape != (n, 3):
        _reject("HISTORY_SHAPE", "History must contain exactly f0, f1 and f2 labels.")
    if any(not isinstance(value, (str, np.str_)) or str(value) not in class_labels for value in history.flat):
        _reject("INVALID_HISTORY_LABEL", "History contains a label outside the frozen vocabulary.")
    gold = np.asarray(labels, dtype=str)
    if not np.all(history[:, 2] == gold):
        _reject("POOL_NOT_CURRENT_CORRECT", "Every pool row must be correct under f2.")

    try:
        probabilities = np.asarray(reference_probabilities, dtype=np.float64)
    except (ValueError, TypeError, OverflowError):
        _reject("INVALID_PROBABILITIES", "Reference scores must be a finite numeric matrix.")
    if probabilities.shape != (n, len(class_labels)):
        _reject("PROBABILITY_SHAPE", "Reference score columns must match the frozen vocabulary.")
    if not np.isfinite(probabilities).all() or np.any(probabilities < 0) or np.any(probabilities > 1):
        _reject("INVALID_PROBABILITIES", "Reference scores must be finite values in [0,1].")
    if not np.allclose(probabilities.sum(axis=1), 1.0, rtol=0, atol=1e-8):
        _reject("PROBABILITY_NORMALIZATION", "Reference score rows must sum to one.")
    predicted = np.asarray(class_labels, dtype=str)[np.argmax(probabilities, axis=1)]
    if not np.array_equal(predicted, history[:, 2]):
        _reject("REFERENCE_SCORE_LABEL_MISMATCH", "f2 scores and its parsed prediction must agree.")

    try:
        vectors = sparse.csr_matrix(representations, dtype=np.float64, copy=True)
    except (ValueError, TypeError, OverflowError):
        _reject("INVALID_REPRESENTATION", "Representation must be a nonnegative numeric matrix.")
    if vectors.ndim != 2 or vectors.shape[0] != n:
        _reject("REPRESENTATION_SHAPE", "Representation rows must match the pool.")
    if not np.isfinite(vectors.data).all() or np.any(vectors.data < 0):
        _reject("INVALID_REPRESENTATION", "Representation must contain finite nonnegative values.")
    norms = np.sqrt(np.asarray(vectors.multiply(vectors).sum(axis=1)).ravel())
    if not np.isfinite(norms).all():
        _reject("INVALID_REPRESENTATION", "Representation row norms must be finite.")
    inverse_norms = np.divide(1.0, norms, out=np.zeros_like(norms), where=norms > 0)
    vectors = sparse.diags(inverse_norms) @ vectors
    vectors = vectors.tocsr()

    sorted_indices = np.asarray(sorted(range(n), key=lambda index: sample_ids[index].encode("utf-8")), dtype=int)
    max_size = min(max(budgets), n)
    output = []

    def record_timing(method, seed, begin):
        if timings is not None:
            timings.append({
                "method": method, "seed": int(seed) if seed is not None else None,
                "selection_seconds": perf_counter() - begin,
                "max_budget": int(max(budgets)), "includes_shared_representation": False,
            })

    record_timing("__shared_validation__", None, shared_begin)

    def append_prefixes(method, seed, order):
        for budget in budgets:
            output.append({"method": method, "seed": int(seed) if seed is not None else None, "budget": int(budget), "indices": [int(index) for index in order[:min(budget, n)]]})

    for seed in seeds:
        begin = perf_counter()
        permutation = np.random.default_rng(int(seed)).permutation(sorted_indices)
        append_prefixes("random", seed, permutation)
        record_timing("random", seed, begin)

        begin = perf_counter()
        permutation = np.random.default_rng(int(seed)).permutation(sorted_indices)
        for budget in budgets:
            quotas = _proportional_quotas(labels, min(budget, n))
            used = Counter()
            chosen = []
            for index in permutation:
                label = labels[int(index)]
                if used[label] < quotas[label]:
                    chosen.append(int(index))
                    used[label] += 1
            output.append({"method": "stratified", "seed": int(seed), "budget": int(budget), "indices": chosen})
        record_timing("stratified", seed, begin)

        begin = perf_counter()
        permutation = np.random.default_rng(int(seed)).permutation(sorted_indices)
        old_correct = history[:, :2] == gold[:, None]
        flips = old_correct & (history[:, 1:3] != gold[:, None])
        opportunities = old_correct.sum(axis=1)
        past_risk = np.divide(flips.sum(axis=1), opportunities, out=np.zeros(n, dtype=np.float64), where=opportunities > 0)
        # Stable sorting retains the seeded permutation within equal risk.
        past_order = sorted(permutation.tolist(), key=lambda index: -past_risk[index])
        append_prefixes("past-flip", seed, past_order)
        record_timing("past-flip", seed, begin)

        begin = perf_counter()
        append_prefixes("kcenter", seed, _kcenter_order(vectors, sorted_indices, int(seed), max_size))
        record_timing("kcenter", seed, begin)

    for method in ("ref-maxprob", "ref-margin", "ref-entropy", "ref-deepgini"):
        begin = perf_counter()
        if not n:
            scores = np.empty(0)
        elif method in ("ref-maxprob", "ref-margin"):
            ordered_probabilities = np.sort(probabilities, axis=1)
            scores = -ordered_probabilities[:, -1] if method == "ref-maxprob" else -(ordered_probabilities[:, -1] - ordered_probabilities[:, -2])
        elif method == "ref-entropy":
            with np.errstate(divide="ignore", invalid="ignore"):
                log_probabilities = np.zeros_like(probabilities)
                np.log(probabilities, out=log_probabilities, where=probabilities > 0)
            scores = -(probabilities * log_probabilities).sum(axis=1)
        else:
            scores = 1.0 - np.square(probabilities).sum(axis=1)
        order = sorted(sorted_indices.tolist(), key=lambda index: (-scores[index], sample_ids[index].encode("utf-8")))
        append_prefixes(method, None, order)
        record_timing(method, None, begin)

    begin = perf_counter()
    anchor_indices = _anchors(sample_ids, labels, sorted_indices)
    append_prefixes("facility", None, _facility_order(vectors, anchor_indices, sorted_indices, max_size))
    record_timing("facility", None, begin)
    return output
