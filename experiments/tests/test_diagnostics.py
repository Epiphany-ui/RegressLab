"""Hand-computable checks of post-hoc ranking and nonduplicated detections."""

from copy import deepcopy

import numpy as np
import pytest

from preflight.diagnostics import analyze_history_signal, ranking_metrics


def data(size=4):
    rows = [{'sample_id': f's:{i:03}', 'text': f'text {i}', 'gold_label': 'A'} for i in range(size)]
    history = np.asarray([['A', 'A', 'A']] * size)
    scores = np.tile([.9, .1], (size, 1))
    return rows, history, list(range(size)), scores


def test_auc_ties_reverse_and_threshold_group_average_precision():
    events = np.asarray([True, False, True, False])
    perfect = ranking_metrics(events, [4, 2, 3, 1])
    assert perfect['roc_auc'] == perfect['average_precision'] == 1
    reverse = ranking_metrics(events, [1, 3, 2, 4])
    assert reverse['roc_auc'] == 0
    assert reverse['average_precision'] == pytest.approx((1 / 3 + 2 / 4) / 2)
    tied = ranking_metrics(events, [1, 1, 1, 1])
    assert tied['roc_auc'] == tied['average_precision'] == .5
    assert tied['constant_score'] is True
    half = ranking_metrics(np.asarray([True, False, True]), [2, 2, 1])
    assert half['roc_auc'] == .25
    assert half['average_precision'] == pytest.approx((1 / 2 + 2 / 3) / 2)


def test_zero_and_all_positive_auc_have_explicit_na():
    zero = ranking_metrics(np.array([False, False]), [1, 2])
    assert zero['roc_auc'] is zero['average_precision'] is None
    assert zero['roc_auc_na_reason'] == 'NO_POSITIVE_EVENTS'
    all_positive = ranking_metrics(np.array([True, True]), [1, 2])
    assert all_positive['roc_auc'] is None
    assert all_positive['roc_auc_na_reason'] == 'NO_NEGATIVE_EVENTS'
    assert all_positive['average_precision'] == 1
    with pytest.raises(ValueError, match='NONFINITE'):
        ranking_metrics(np.array([True, False]), [float('nan'), 0])


def test_full_discovery_pool_scope_and_group_mapping():
    rows, history, _, scores = data()
    history[0, 2] = 'B'
    groups = [{'d_member_indices': [0, 1], 'p_member_indices': [0], 'normalized_weight': 1.0}]
    output = analyze_history_signal(rows, history, [1, 2, 3], scores, groups, np.array(['B', 'B', 'A', 'A']))
    assert output['discovery_count'] == 4 and output['pool_count'] == 3
    assert output['future_flip_count'] == 1
    assert output['risk_groups'][0]['discovery_support'] == 2
    assert output['risk_groups'][0]['pool_support'] == 1
    assert output['risk_groups'][0]['future_flip_enrichment'] == 3
    assert output['risk_top']['roc_auc'] == 1
    with pytest.raises(ValueError, match='INCOMPLETE_CURRENT_CORRECT_POOL'):
        analyze_history_signal(rows, history, [0, 1, 2, 3], scores, groups, np.array(['B', 'B', 'A', 'A']))
    broken = deepcopy(groups);broken[0]['p_member_indices'] = [1]
    with pytest.raises(ValueError, match='GROUP_DISCOVERY_POOL_SCOPE_MISMATCH'):
        analyze_history_signal(rows, history, [1, 2, 3], scores, broken, np.array(['B', 'B', 'A', 'A']))


def test_overlap_groups_do_not_duplicate_target_events():
    rows, history, pool, scores = data()
    groups = [
        {'d_member_indices': [0, 1], 'p_member_indices': [0, 1], 'normalized_weight': .5},
        {'d_member_indices': [1, 2], 'p_member_indices': [1, 2], 'normalized_weight': .5},
    ]
    output = analyze_history_signal(rows, history, pool, scores, groups, np.array(['A', 'B', 'A', 'A']))
    assert sum(g['future_flip_count'] for g in output['risk_groups']) == 2
    assert output['group_union_future_flip_count'] == 1
    assert output['positive_risk_coverage']['pool_count'] == 3
    assert output['incremental_over_margin_top100']['union_detected'] == 1
    assert sum(x['sample_count'] for x in output['top100_confusion_strata']) == 4
    assert sum(x['future_flip_count'] for x in output['top100_confusion_strata']) == 1


def test_novel_and_recurrent_events_are_disjoint_and_no_events_na():
    rows, history, pool, scores = data()
    history[0] = ['A', 'B', 'A']
    output = analyze_history_signal(rows, history, pool, scores, [], np.array(['B', 'B', 'A', 'A']))
    assert output['historical_flip_pool_count'] == 1
    assert output['repaired_then_recurred_count'] == 1
    assert output['historically_unseen_future_flip_count'] == 1
    assert output['risk_top']['constant_score'] is True
    no_events = analyze_history_signal(rows, history, pool, scores, [], np.array(['A'] * 4))
    assert no_events['risk_top']['top100']['recall'] is None
    assert no_events['risk_top']['top100']['precision'] == 0
    assert no_events['positive_risk_coverage']['future_flip_recall'] is None


def test_primary_budget_incremental_detected_counts_are_unique():
    rows, history, pool, scores = data(102)
    # Margin selects IDs 0..99; history risk selects 1..100 then low-ID fillers.
    scores[:] = [.9, .1]
    scores[:100] = [.6, .4]
    groups = [{'d_member_indices': list(range(1, 101)), 'p_member_indices': list(range(1, 101)), 'normalized_weight': 1.0}]
    target = np.array(['A'] * 102);target[[0, 100]] = 'B'
    output = analyze_history_signal(rows, history, pool, scores, groups, target)
    assert output['risk_top']['top100']['actual_size'] == 100
    assert output['risk_top']['top100']['detected'] == 1
    assert output['margin']['top100']['detected'] == 1
    assert output['incremental_over_margin_top100'] == {
        'common_selected_count': 99, 'risk_only_detected': 1, 'margin_only_detected': 1,
        'shared_detected': 0, 'union_detected': 2, 'margin_missed_future_flips': 1,
    }


def test_empty_pool_and_bad_probabilities():
    rows, history, _, scores = data()
    history[:, 2] = 'B'
    output = analyze_history_signal(rows, history, [], scores, [], np.array(['B'] * 4))
    assert output['pool_count'] == output['future_flip_count'] == 0
    assert output['risk_top']['roc_auc'] is None
    assert output['margin']['top100']['precision'] is None
    scores[0] = [.9, .9]
    with pytest.raises(ValueError, match='INVALID_REFERENCE_PROBABILITIES'):
        analyze_history_signal(rows, history, [], scores, [], np.array(['B'] * 4))


def test_prespecified_context_changes_labels_only_and_preserves_default():
    rows, history, pool, scores = data()
    target = np.array(['B', 'A', 'A', 'A'])
    default = analyze_history_signal(rows, history, pool, scores, [], target)
    explicit = analyze_history_signal(rows, history, pool, scores, [], target, context='POST_HOC')
    assert default == explicit
    assert default['scope'] == 'EXPOSED_DEVELOPMENT_POST_HOC_DIAGNOSTIC'
    assert 'Post-hoc diagnosis' in default['limitations'][0]
    assert 'not a preregistered' in default['limitations'][3]
    contexts = {
        'PRESPECIFIED_EXTERNAL': 'PRESPECIFIED_EXTERNAL_FEASIBILITY_DIAGNOSTIC',
        'PRESPECIFIED_OLD_DEV_NEW_MODEL': 'PRESPECIFIED_NEW_MODEL_OLD_DEV_FEASIBILITY_DIAGNOSTIC',
    }
    for context, scope in contexts.items():
        actual = analyze_history_signal(rows, history, pool, scores, [], target, context=context)
        assert actual['scope'] == scope
        assert 'preregistered for this fixed feasibility closeout' in actual['limitations'][3]
        assert {k:v for k,v in actual.items() if k not in {'scope','limitations'}} == {k:v for k,v in default.items() if k not in {'scope','limitations'}}
    with pytest.raises(ValueError, match='UNKNOWN_DIAGNOSTIC_CONTEXT'):
        analyze_history_signal(rows, history, pool, scores, [], target, context='FORMAL')
