"""Exact fixtures for history-only CPU preflight selection."""

from collections import Counter
import inspect

import numpy as np
import pytest
from scipy import sparse

from preflight.baselines import BaselineInputError, _anchors, select_baselines


def inputs():
    return {
        "sample_ids": ["s4", "s2", "s1", "s3"],
        "labels": ["A", "B", "A", "B"],
        "history": np.asarray([["A", "A", "A"], ["B", "A", "B"], ["B", "B", "A"], ["B", "B", "B"]]),
        "reference_probabilities": np.asarray([[.9, .1], [.2, .8], [.6, .4], [.3, .7]]),
        "representations": sparse.csr_matrix([[1., 0.], [0., 1.], [1., 0.], [0., 1.]]),
        "class_labels": ["A", "B"],
        "budgets": [1, 2, 4, 10],
        "seeds": [0, 1],
    }


def lookup(results, method, seed, budget):
    return next(row["indices"] for row in results if (row["method"], row["seed"], row["budget"]) == (method, seed, budget))


def test_all_methods_share_pool_cover_budgets_and_use_no_duplicates():
    values = inputs()
    results = select_baselines(**values)
    assert {row["method"] for row in results} == {"random", "stratified", "past-flip", "ref-maxprob", "ref-margin", "ref-entropy", "ref-deepgini", "facility", "kcenter"}
    assert len(results) == (4 * 2 + 5) * 4
    for row in results:
        assert len(row["indices"]) == min(row["budget"], 4)
        assert len(set(row["indices"])) == len(row["indices"])
        assert set(row["indices"]) <= {0, 1, 2, 3}
    for method in ("random", "past-flip", "kcenter", "ref-maxprob", "ref-margin", "ref-entropy", "ref-deepgini", "facility"):
        seeds = [0, 1] if method in ("random", "past-flip", "kcenter") else [None]
        for seed in seeds:
            full = lookup(results, method, seed, 4)
            assert lookup(results, method, seed, 1) == full[:1]
            assert lookup(results, method, seed, 2) == full[:2]


def test_past_flip_uses_earlier_repaired_errors_not_only_last_transition():
    results = select_baselines(**inputs())
    # s2: B -> A -> B was wrong after f0, then fixed by f2. It is the
    # sole historically flipped current-correct example; latest flips are zero.
    assert lookup(results, "past-flip", 0, 1) == [1]
    assert lookup(results, "past-flip", 1, 1) == [1]
    assert lookup(results, "past-flip", 0, 4)[0] == 1


def test_reference_score_rankings_have_exact_direction_and_id_tie_break():
    results = select_baselines(**inputs())
    for method in ("ref-maxprob", "ref-margin", "ref-entropy", "ref-deepgini"):
        assert lookup(results, method, None, 4) == [2, 3, 1, 0]
    values = inputs()
    values["reference_probabilities"] = np.asarray([[.8, .2], [.2, .8], [.8, .2], [.2, .8]])
    results = select_baselines(**values)
    for method in ("ref-maxprob", "ref-margin", "ref-entropy", "ref-deepgini"):
        assert lookup(results, method, None, 4) == [2, 1, 3, 0]  # s1,s2,s3,s4


def test_stratified_uses_proportional_largest_remainder_without_class_floor():
    values = inputs()
    results = select_baselines(**values)
    for seed in [0, 1]:
        one = lookup(results, "stratified", seed, 1)
        assert Counter(values["labels"][index] for index in one) == {"A": 1}
        two = lookup(results, "stratified", seed, 2)
        assert Counter(values["labels"][index] for index in two) == {"A": 1, "B": 1}
    # 3:1 proportions with B=2 allocate 2 to A when remainders tie by label.
    values["labels"] = ["A", "A", "A", "B"]
    values["history"] = np.asarray([["A", "A", "A"], ["A", "B", "A"], ["B", "B", "A"], ["B", "B", "B"]])
    values["reference_probabilities"] = np.asarray([[.9, .1], [.8, .2], [.6, .4], [.3, .7]])
    results = select_baselines(**values)
    assert Counter(values["labels"][index] for index in lookup(results, "stratified", 0, 2)) == {"A": 2}


def test_facility_exact_greedy_covers_distinct_vector_groups():
    results = select_baselines(**inputs())
    # Either duplicate has equal initial gain; smallest ID s1 wins. The next
    # point must cover the orthogonal B group, whose smallest ID is s2.
    assert lookup(results, "facility", None, 4) == [2, 1, 3, 0]


def test_kcenter_random_start_then_maximum_minimum_distance():
    values = inputs()
    results = select_baselines(**values)
    sorted_indices = np.asarray([2, 1, 3, 0])
    for seed in [0, 1]:
        first = int(sorted_indices[np.random.default_rng(seed).integers(4)])
        order = lookup(results, "kcenter", seed, 4)
        assert order[0] == first
        assert values["labels"][order[0]] != values["labels"][order[1]]


def test_seeded_selection_is_reproducible_and_independent_of_input_row_order():
    original = inputs()
    before = select_baselines(**original)
    assert before == select_baselines(**original)
    permutation = [3, 2, 1, 0]
    shuffled = {**original, "sample_ids": [original["sample_ids"][i] for i in permutation], "labels": [original["labels"][i] for i in permutation], "history": original["history"][permutation], "reference_probabilities": original["reference_probabilities"][permutation], "representations": original["representations"][permutation]}
    after = select_baselines(**shuffled)
    for old, new in zip(before, after, strict=True):
        assert {key: value for key, value in old.items() if key != "indices"} == {key: value for key, value in new.items() if key != "indices"}
        assert [original["sample_ids"][i] for i in old["indices"]] == [shuffled["sample_ids"][i] for i in new["indices"]]
    assert lookup(before, "random", 0, 4) != lookup(before, "random", 1, 4)


def test_zero_vectors_are_valid_and_have_zero_facility_gain():
    values = inputs()
    values["representations"] = sparse.csr_matrix((4, 2))
    result = select_baselines(**values)
    assert lookup(result, "facility", None, 4) == [2, 1, 3, 0]


def test_facility_anchor_cap_is_class_proportional_hash_stable():
    ids = [f"sample:{index:04}" for index in range(600)]
    gold = ["A"] * 450 + ["B"] * 150
    anchors = _anchors(ids, gold, np.arange(600))
    assert len(anchors) == len(set(anchors)) == 256
    assert Counter(gold[index] for index in anchors) == {"A": 192, "B": 64}
    reverse = _anchors(list(reversed(ids)), list(reversed(gold)), np.arange(600))
    assert [ids[index] for index in anchors] == [list(reversed(ids))[index] for index in reverse]


def test_empty_pool_is_preserved_as_empty_budget_results():
    values = inputs()
    values.update(sample_ids=[], labels=[], history=np.empty((0, 3), dtype=str), reference_probabilities=np.empty((0, 2)), representations=sparse.csr_matrix((0, 2)))
    results = select_baselines(**values)
    assert results
    assert all(row["indices"] == [] for row in results)


@pytest.mark.parametrize("change,code", [
    ({"sample_ids": ["same"] * 4}, "DUPLICATE_IDENTIFIERS"),
    ({"history": np.asarray([["A", "A", "A", "B"]] * 4)}, "HISTORY_SHAPE"),
    ({"history": np.asarray([["A", "A", "A"]] * 4)}, "POOL_NOT_CURRENT_CORRECT"),
    ({"reference_probabilities": np.asarray([[.5, .1]] * 4)}, "PROBABILITY_NORMALIZATION"),
    ({"reference_probabilities": np.asarray([[np.nan, .1]] * 4)}, "INVALID_PROBABILITIES"),
    ({"reference_probabilities": np.asarray([[.1, .9]] * 4)}, "REFERENCE_SCORE_LABEL_MISMATCH"),
    ({"reference_probabilities": np.ones((4, 1))}, "PROBABILITY_SHAPE"),
    ({"representations": sparse.csr_matrix([[-1., 0.]] * 4)}, "INVALID_REPRESENTATION"),
    ({"representations": sparse.csr_matrix((3, 2))}, "REPRESENTATION_SHAPE"),
    ({"budgets": [1, 1]}, "DUPLICATE_CONFIGURATION"),
    ({"seeds": [0, 0]}, "DUPLICATE_CONFIGURATION"),
    ({"budgets": [True]}, "INVALID_CONFIGURATION"),
])
def test_invalid_inputs_fail_instead_of_changing_pool_or_denominator(change, code):
    values = {**inputs(), **change}
    with pytest.raises(BaselineInputError) as error:
        select_baselines(**values)
    assert error.value.code == code


def test_class_probability_column_order_is_explicit_not_assumed_alphabetical():
    values = inputs()
    values["class_labels"] = ["B", "A"]
    values["reference_probabilities"] = values["reference_probabilities"][:, ::-1]
    result = select_baselines(**values)
    assert lookup(result, "ref-maxprob", None, 4) == [2, 3, 1, 0]


def test_selector_signature_cannot_accept_an_extra_future_version():
    assert list(inspect.signature(select_baselines).parameters) == ["sample_ids", "labels", "history", "reference_probabilities", "representations", "class_labels", "budgets", "seeds"]
    with pytest.raises(TypeError):
        select_baselines(**inputs(), target_predictions=np.asarray(["B"] * 4))
