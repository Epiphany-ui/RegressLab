"""Hand-calculated HGC risk and exact-greedy development fixtures."""

from copy import deepcopy
from fractions import Fraction
import inspect
import json

import numpy as np
import pytest
from scipy import sparse

from preflight.baselines import select_baselines
from preflight.hgc import DEFAULT_HGC_CONFIG, HgcInputError, _features, select_hgc


def config(**changes):
    return {**deepcopy(DEFAULT_HGC_CONFIG), **changes}


def risk_fixture():
    # FX-RISK: 4 ABA + 4 BAB + 12 AAA in g; 72 AAA + 8 BBB outside.
    triples = ["ABA"] * 4 + ["BAB"] * 4 + ["AAA"] * 12 + ["AAA"] * 72 + ["BBB"] * 8
    rows = [{"sample_id": f"r:{index:03}", "text": "不要设置灯光" if index < 20 else "请你设置灯光", "gold_label": "A"} for index in range(100)]
    history = np.asarray([list(triple) for triple in triples])
    pool = np.flatnonzero(history[:, 2] == "A").tolist()
    vectors = sparse.csr_matrix(np.eye(len(pool), 3)[np.arange(len(pool)) % len(pool)])
    return rows, history, pool, vectors


def group_with_members(diagnostics, sample_ids):
    return next(group for group in diagnostics["groups"] if set(group["d_member_sample_ids"]) == set(sample_ids))


def facility(rows, history, pool, vectors, budgets):
    labels = [rows[index]["gold_label"] for index in pool]
    probabilities = np.asarray([[1., 0.] if label == "A" else [0., 1.] for label in labels], dtype=np.float64).reshape(len(pool), 2)
    all_results = select_baselines([rows[index]["sample_id"] for index in pool], labels, history[pool], probabilities, vectors, ["A", "B"], budgets, [0])
    return [row for row in all_results if row["method"] == "facility"]


def test_fx_risk_exact_shrinkage_u_q_and_weight_are_18_over_253():
    rows, history, pool, vectors = risk_fixture()
    selections, diagnostics = select_hgc(rows, history, pool, vectors, [1, 3, 20], config())
    group = group_with_members(diagnostics, [row["sample_id"] for row in rows[:20]])
    assert diagnostics["global_transitions"] == [
        {"transition": "f0-f1", "e": 88, "b": 4, "p0": 1 / 22, "valid": True, "excluded_reason": None},
        {"transition": "f1-f2", "e": 88, "b": 4, "p0": 1 / 22, "valid": True, "excluded_reason": None},
    ]
    assert group["e"] == [16, 16] and group["b"] == [4, 4]
    assert group["p"] == pytest.approx([59 / 506, 59 / 506])
    assert group["u"] == pytest.approx([18 / 253, 18 / 253])
    assert group["q"] == 1 and group["w"] == pytest.approx(18 / 253)
    assert group["low_support"] == [False, False]
    assert group["p_support"] == 16 and group["d_support"] == 20
    assert group["statistical_confirmation"] == "NOT_PERFORMED"
    assert len(diagnostics["groups"]) == 1
    assert diagnostics["weights"] == [1.]
    assert diagnostics["candidate_counts"]["jaccard_duplicates"] > 0
    assert selections[0]["indices"] == selections[-1]["indices"][:1]
    # These risk groups have b=c, so a net-decline-only filter would lose them.
    for t in [0, 1]:
        ids = group["d_member_indices"]
        c = sum(history[index, t] != "A" and history[index, t + 1] == "A" for index in ids)
        assert c == group["b"][t] == 4


def test_global_zero_opportunity_transition_is_excluded_not_averaged_as_zero():
    rows = [{"sample_id": f"z:{i:03}", "text": "不要开灯" if i < 20 else "请你开灯", "gold_label": "A"} for i in range(100)]
    history = np.asarray([list("BAB" if i < 10 else "BAA") for i in range(100)])
    pool = np.flatnonzero(history[:, 2] == "A").tolist()
    _, diagnostics = select_hgc(rows, history, pool, sparse.csr_matrix(np.ones((len(pool), 1))), [1], config())
    group = group_with_members(diagnostics, [row["sample_id"] for row in rows[:20]])
    assert diagnostics["valid_transition_count"] == 1
    assert diagnostics["global_transitions"][0]["excluded_reason"] == "ZERO_GLOBAL_OLD_CORRECT"
    assert group["e"] == [0, 20] and group["b"] == [0, 10]
    assert group["p0"] == [None, .1] and group["p"][0] is None
    assert group["q"] == 1
    assert group["w"] == pytest.approx(.16)


def test_low_group_support_zero_u_remains_in_globally_valid_q_denominator():
    rows = [{"sample_id": f"low:{i:03}", "text": "不要开灯" if i < 20 else "请你开灯", "gold_label": "A"} for i in range(100)]
    history = np.asarray([list("ABA")] * 11 + [list("BAA")] * 9 + [list("AAA")] * 80)
    pool = list(range(100))
    _, diagnostics = select_hgc(rows, history, pool, sparse.csr_matrix(np.ones((100, 1))), [1], config())
    group = group_with_members(diagnostics, [row["sample_id"] for row in rows[:20]])
    uplift = (Fraction(11) + 30 * Fraction(11, 91)) / 41 - Fraction(11, 91)
    assert group["e"] == [11, 9]
    assert group["low_support"] == [False, True]
    assert group["u"] == pytest.approx([float(uplift), 0])
    assert group["q"] == .5  # low-support second transition still counts.
    assert group["w"] == pytest.approx(float(uplift * Fraction(3, 8)))


def test_risk_uses_discovery_rows_outside_current_correct_pool():
    rows = [{"sample_id": f"d:{i:03}", "text": "不要开灯" if i < 20 else "请你开灯", "gold_label": "A"} for i in range(100)]
    history = np.asarray([list("AAA")] * 10 + [list("AAB")] * 10 + [list("AAA")] * 80)
    pool = np.flatnonzero(history[:, 2] == "A").tolist()
    _, diagnostics = select_hgc(rows, history, pool, sparse.csr_matrix(np.ones((len(pool), 1))), [3], config())
    group = group_with_members(diagnostics, [row["sample_id"] for row in rows[:20]])
    assert group["b"] == [0, 10] and group["w"] == pytest.approx(.06)
    assert group["d_support"] == 20 and group["p_support"] == 10
    assert diagnostics["global_transitions"][1]["b"] == 10
    latest_pool_flips = (history[pool, 1] == "A") & (history[pool, 2] != "A")
    assert not latest_pool_flips.any()
    # Estimating risk on P alone would miss all ten informative recent flips.
    projected_rows = [rows[index] for index in pool]
    _, projected = select_hgc(projected_rows, history[pool], list(range(len(pool))), sparse.csr_matrix(np.ones((len(pool), 1))), [3], config())
    assert projected["groups"] == []


def test_jaccard_exact_point_nine_is_duplicate_using_d_members():
    rows = [{"sample_id": f"j:{i:03}", "text": "不要1设置灯光" if i < 18 else "不要甲设置灯光" if i < 20 else "请你甲设置灯光", "gold_label": "A"} for i in range(100)]
    history = np.asarray([list("ABA")] * 5 + [list("AAA")] * 95)
    _, diagnostics = select_hgc(rows, history, list(range(100)), sparse.csr_matrix(np.ones((100, 1))), [3], config())
    assert any(group["d_support"] == 18 for group in diagnostics["groups"])
    assert not any(group["d_support"] == 20 for group in diagnostics["groups"])
    assert diagnostics["candidate_counts"]["positive_weight_with_pool_candidates"] > 1
    assert diagnostics["candidate_counts"]["jaccard_duplicates"] > 0


def test_features_use_nfkc_unicode_digits_normalized_len_and_negation_boundaries():
    cfg = config()
    assert _features({"text": "  不要　Ａ１２？  ", "gold_label": "intent"}, cfg) == {"gold_label": "intent", "length_bin": "1-10", "has_negation": True, "has_digit": True, "has_question_mark": True}
    assert _features({"text": "notebook", "gold_label": "A"}, cfg)["has_negation"] is False
    assert _features({"text": "DO NOT PLAY", "gold_label": "A"}, cfg)["has_negation"] is True
    assert _features({"text": "甲" * 10 + "\t  乙", "gold_label": "A"}, cfg)["length_bin"] == "11-20"
    assert _features({"text": "第٢项", "gold_label": "A"}, cfg)["has_digit"] is True


def test_false_boolean_groups_are_enumerated_as_real_risk_candidates():
    rows, history, pool, vectors = risk_fixture()
    for index, row in enumerate(rows):
        row["text"] = "请你设置灯光" if index < 20 else "不要设置灯光"
    _, diagnostics = select_hgc(rows, history, pool, vectors, [1], config())
    group = group_with_members(diagnostics, [row["sample_id"] for row in rows[:20]])
    assert any(atom == {"feature": "has_negation", "op": "eq", "value": False} for atom in group["predicate"]["all"])
    assert group["w"] == pytest.approx(18 / 253)


def test_group_cap_retains_only_thirty_in_fixed_risk_support_predicate_order():
    rows, triples = [], []
    for group_index in range(31):
        gold = f"intent-{group_index:02}"
        for local in range(20):
            rows.append({"sample_id": f"cap:{group_index:02}:{local:02}", "text": "请你设置灯光", "gold_label": gold})
            triples.append([gold, "other" if local < 4 else gold, gold])
    for index in range(1000):
        rows.append({"sample_id": f"background:{index:04}", "text": "请你设置灯光", "gold_label": "background"})
        triples.append(["background"] * 3)
    history = np.asarray(triples)
    _, diagnostics = select_hgc(rows, history, list(range(len(rows))), sparse.csr_matrix(np.ones((len(rows), 1))), [1], config())
    assert len(diagnostics["groups"]) == diagnostics["candidate_counts"]["retained_groups"] == 30
    assert diagnostics["candidate_counts"]["omitted_by_group_cap"] > 0
    assert all(group["d_support"] == 20 for group in diagnostics["groups"])
    identities = [group["d_member_sample_ids"][0].split(":")[1] for group in diagnostics["groups"]]
    assert identities == [f"{index:02}" for index in range(30)]


def test_row_and_pool_order_do_not_change_group_identity_or_selected_id_sequence():
    rows, history, pool, vectors = risk_fixture()
    before, diagnostics = select_hgc(rows, history, pool, vectors, [1, 3, 20], config())
    row_permutation = list(reversed(range(len(rows))))
    old_to_new = {old: new for new, old in enumerate(row_permutation)}
    pool_permutation = list(reversed(range(len(pool))))
    new_pool = [old_to_new[pool[index]] for index in pool_permutation]
    shuffled = [rows[index] for index in row_permutation]
    after, other = select_hgc(shuffled, history[row_permutation], new_pool, vectors[pool_permutation], [1, 3, 20], config())
    for left, right in zip(before, after, strict=True):
        assert [rows[pool[index]]["sample_id"] for index in left["indices"]] == [shuffled[new_pool[index]]["sample_id"] for index in right["indices"]]
    assert diagnostics["anchor_sample_ids"] == other["anchor_sample_ids"]
    assert diagnostics["candidate_counts"] == other["candidate_counts"]
    for left, right in zip(diagnostics["groups"], other["groups"], strict=True):
        for key in ("predicate", "predicate_sha256", "d_member_sample_ids", "p_member_sample_ids", "e", "b", "u", "q", "w"):
            assert left[key] == right[key]


def test_exact_saturated_greedy_matches_exhaustive_candidate_marginals():
    rows, history, pool, vectors = risk_fixture()
    # Use a deliberately small P representation with three shared directions.
    dense = np.zeros((len(pool), 3))
    for index in range(len(pool)):
        dense[index, index % 3] = 1
    vectors = sparse.csr_matrix(dense)
    selections, diagnostics = select_hgc(rows, history, pool, vectors, [1, 3, 6], config())
    groups = diagnostics["groups"]
    anchors = diagnostics["anchor_indices"]
    similarity = dense[anchors] @ dense.T

    def objective(selected):
        g = sum(group["normalized_weight"] * min(1, len(set(selected) & set(group["p_member_indices"])) / 3) for group in groups)
        f = float(similarity[:, selected].max(axis=1).mean()) if selected else 0
        return .5 * g + .5 * f

    selected = []
    for actual in selections[-1]["indices"]:
        candidates = [index for index in range(len(pool)) if index not in selected]
        candidates.sort(key=lambda index: (- (objective(selected + [index]) - objective(selected)), rows[pool[index]]["sample_id"].encode()))
        assert actual == candidates[0]
        selected.append(actual)
    assert diagnostics["proxy_values"][-1]["J"] == pytest.approx(objective(selected))
    # First three group representatives saturate G; selecting another member
    # yields no group gain, while the objective remains monotone.
    covered = groups[0]["p_member_indices"][:3]
    assert len(covered) == 3
    for extra in groups[0]["p_member_indices"][3:]:
        old_g = min(1, len(covered) / 3)
        new_g = min(1, len(covered + [extra]) / 3)
        assert new_g - old_g == 0
    for trace in diagnostics["greedy_trace"]:
        assert trace["delta_J"] >= 0
        assert trace["delta_G"] >= 0 and trace["delta_F"] >= 0


@pytest.mark.parametrize("use_lambda_zero", [False, True])
def test_zero_risk_or_zero_lambda_is_exactly_same_facility_prefix(use_lambda_zero):
    rows, history, pool, vectors = risk_fixture()
    if not use_lambda_zero:
        history = np.asarray([list("AAA")] * len(rows))
        pool = list(range(len(rows)))
        vectors = sparse.csr_matrix(np.eye(len(pool), 3)[np.arange(len(pool)) % len(pool)])
    budgets = [1, 3, 20, 200]
    result, diagnostics = select_hgc(rows, history, pool, vectors, budgets, config(**{"lambda": 0.0 if use_lambda_zero else .5}))
    baseline = facility(rows, history, pool, vectors, budgets)
    assert [row["indices"] for row in result] == [row["indices"] for row in baseline]
    assert diagnostics["effective_lambda"] == 0
    if not use_lambda_zero:
        assert diagnostics["groups"] == []
        assert diagnostics["fallback"] == "NO_POSITIVE_RISK_REPRESENTATION_ONLY"


def test_empty_pool_and_no_globally_valid_history_are_valid_json_safe_results():
    rows = [{"sample_id": "no-correct", "text": "请开灯", "gold_label": "A"}]
    results, diagnostics = select_hgc(rows, np.asarray([list("BBB")]), [], sparse.csr_matrix((0, 2)), [20, 50], config())
    assert [row["indices"] for row in results] == [[], []]
    assert diagnostics["fallback"] == "EMPTY_POOL"
    assert diagnostics["valid_transition_count"] == 0
    assert diagnostics["anchor_indices"] == []
    assert diagnostics["proxy_values"] == [{"budget": budget, "actual_size": 0, "G": 0., "F": 0., "J": 0.} for budget in [20, 50]]
    json.dumps(diagnostics, allow_nan=False)


def test_empty_discovery_and_zero_vectors_have_defined_outputs():
    result, diagnostics = select_hgc([], np.empty((0, 3), dtype=str), [], sparse.csr_matrix((0, 2)), [1], config())
    assert result[0]["indices"] == [] and diagnostics["fallback"] == "EMPTY_POOL"
    rows, history, pool, _ = risk_fixture()
    result, diagnostics = select_hgc(rows, history, pool, sparse.csr_matrix((len(pool), 2)), [1, 3], config())
    assert all(proxy["F"] == 0 for proxy in diagnostics["proxy_values"])
    assert diagnostics["proxy_values"][-1]["G"] == 1


def test_diagnostics_counts_and_times_are_json_safe_and_membership_spaces_explicit():
    rows, history, pool, vectors = risk_fixture()
    _, diagnostics = select_hgc(rows, history, pool, vectors, [1, 3], config())
    json.dumps(diagnostics, allow_nan=False)
    assert diagnostics["candidate_counts"]["enumerated_candidates"] >= diagnostics["candidate_counts"]["nonempty_candidates"]
    assert diagnostics["candidate_counts"]["retained_groups"] == len(diagnostics["groups"])
    for field in ("risk_build_seconds", "similarity_build_seconds", "greedy_seconds", "total_seconds"):
        assert diagnostics[field] >= 0
    assert diagnostics["total_seconds"] >= sum(diagnostics[field] for field in ("risk_build_seconds", "similarity_build_seconds", "greedy_seconds"))
    for group in diagnostics["groups"]:
        assert [rows[index]["sample_id"] for index in group["d_member_indices"]] == group["d_member_sample_ids"]
        assert [rows[pool[index]]["sample_id"] for index in group["p_member_indices"]] == group["p_member_sample_ids"]


@pytest.mark.parametrize("mutation,code", [
    ("future_history", "HISTORY_SHAPE"),
    ("truncated_pool", "POOL_MISMATCH"),
    ("duplicate_pool", "INVALID_POOL"),
    ("future_row_field", "INVALID_ROWS"),
    ("negative_representation", "INVALID_REPRESENTATION"),
    ("wrong_representation_rows", "REPRESENTATION_SHAPE"),
    ("duplicate_budget", "INVALID_BUDGETS"),
    ("unknown_config", "INVALID_CONFIG"),
])
def test_invalid_or_temporally_unsafe_inputs_are_rejected(mutation, code):
    rows, history, pool, vectors = risk_fixture()
    budgets, cfg = [1, 3], config()
    if mutation == "future_history":
        history = np.column_stack([history, history[:, 2]])
    elif mutation == "truncated_pool":
        pool = pool[:-1]
        vectors = vectors[:-1]
    elif mutation == "duplicate_pool":
        pool = pool + [pool[0]]
    elif mutation == "future_row_field":
        rows[0]["f3"] = "forbidden"
    elif mutation == "negative_representation":
        vectors = -sparse.csr_matrix(np.ones((len(pool), 1)))
    elif mutation == "wrong_representation_rows":
        vectors = vectors[:-1]
    elif mutation == "duplicate_budget":
        budgets = [1, 1]
    elif mutation == "unknown_config":
        cfg["target_information"] = "forbidden"
    with pytest.raises(HgcInputError) as error:
        select_hgc(rows, history, pool, vectors, budgets, cfg)
    assert error.value.code == code


def test_pure_interface_has_no_future_or_model_argument():
    assert list(inspect.signature(select_hgc).parameters) == ["rows", "history", "pool_indices", "representations", "budgets", "config"]
    rows, history, pool, vectors = risk_fixture()
    with pytest.raises(TypeError):
        select_hgc(rows, history, pool, vectors, [1], config(), target_predictions=history[:, 2])
