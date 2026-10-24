"""Hand-computable time-prefix features and whole-chain fitting safeguards."""
from copy import deepcopy
import inspect
import json

import numpy as np
import pytest

from preflight.incremental import (
    COMBINED_FEATURE_NAMES, chain_weights, fit_development, group_risk,
    history_features, score_pair, select_pair,
)


def historical_example():
    gold = np.array(['A', 'A', 'A', 'B'])
    probabilities = np.array([
        [[.8, .2], [.3, .7], [.7, .3]],
        [[.2, .8], [.6, .4], [.9, .1]],
        [[.2, .8], [.1, .9], [.3, .7]],
        [[.8, .2], [.7, .3], [.2, .8]],
    ])
    labels = ['A', 'B']
    history = np.asarray(labels)[probabilities.argmax(axis=2)]
    return gold, history, probabilities, labels


def records():
    output = []
    for index in range(4):
        margin = np.array([.1, .2, .6, .7, .8, .9])[:, None] + .01 * index
        extra = np.array([0, 1, 0, 1, 0, 0], dtype=float)
        combined = np.column_stack((margin, extra, extra * .5, extra * .2, extra * .3, extra * .1))
        output.append(dict(chain_id=f'chain-{index}', margin_features=margin, combined_features=combined, events=np.array([False, True, False, True, False, False])))
    return output


def test_hand_computable_features_and_current_correct_scope():
    gold, history, probabilities, labels = historical_example()
    feature = history_features(gold, history, probabilities, labels, risk_scores=[.5, .2, .1])
    assert feature['pool_indices'] == [0, 1, 3]
    assert feature['margin_feature_names'] == ['reference_margin']
    assert feature['combined_feature_names'] == COMBINED_FEATURE_NAMES
    expected = np.array([
        [.4, .5, 1., .5, .45, .5],
        [.8, .5, 0., 0., .35, .2],
        [.6, 1., 0., 0., .3, .1],
    ])
    np.testing.assert_allclose(feature['combined_features'], expected, atol=1e-14)
    np.testing.assert_allclose(feature['margin_features'], expected[:, :1])
    # The recent f1->f2 negative flip is necessarily absent in P. The earlier
    # f0->f1 flip remains visible on the repaired first row.
    assert not ((history[:, 1] == gold) & (history[:, 2] != gold))[feature['pool_indices']].any()
    assert feature['combined_features'][0, 2] == 1


def test_feature_functions_cannot_receive_any_target_argument():
    assert set(inspect.signature(history_features).parameters) == {'gold', 'history', 'probabilities', 'labels', 'risk_scores'}
    assert set(inspect.signature(group_risk).parameters) == {'rows', 'history', 'pool_indices'}
    gold, history, scores, labels = historical_example()
    with pytest.raises(TypeError):
        history_features(gold, history, scores, labels, risk_scores=[0, 0, 0], target=np.array(['B'] * 4))


@pytest.mark.parametrize('problem', ['proba', 'alignment', 'labels', 'risk', 'risk_range'])
def test_invalid_or_misaligned_inputs_are_rejected(problem):
    gold, history, probabilities, labels = historical_example()
    risk = [0, 0, 0]
    if problem == 'proba': probabilities[0, 0] = [.8, .8]
    if problem == 'alignment': history[0, 0] = 'B'
    if problem == 'labels': labels = ['B', 'B']
    if problem == 'risk': risk = [0]
    if problem == 'risk_range': risk = [1.1, 0, 0]
    with pytest.raises(ValueError):
        history_features(gold, history, probabilities, labels, risk_scores=risk)


def test_group_risk_matches_unchanged_archived_formula_and_rejects_truncation():
    from preflight.hgc import DEFAULT_HGC_CONFIG, _risk_groups
    rows = [{'sample_id': f'd:{i:03}', 'text': ('not good' if i < 20 else 'good'), 'gold_label': 'A'} for i in range(80)]
    history = np.array([['A', 'B', 'A'] if i < 20 else ['A', 'A', 'A'] for i in range(80)])
    pool = list(range(80))
    risks, groups = group_risk(rows, history, pool)
    expected_groups, _, _ = _risk_groups(rows, history, np.array(['A'] * 80), pool, DEFAULT_HGC_CONFIG)
    assert groups == expected_groups
    expected = np.zeros(80)
    for group in expected_groups:
        expected[group['p_member_indices']] += group['normalized_weight']
    np.testing.assert_allclose(risks, expected)
    assert risks[:20].mean() > risks[20:].mean()
    with pytest.raises(ValueError, match='INCOMPLETE_CURRENT_CORRECT_POOL'):
        group_risk(rows, history, pool[:-1])


def test_chain_and_class_weights_are_exact_even_for_unequal_chain_sizes():
    data = [dict(events=np.array([True, False, False])), dict(events=np.array([True] * 4 + [False] * 8))]
    weights = chain_weights(data)
    assert weights[:3].sum() == pytest.approx(1)
    assert weights[3:].sum() == pytest.approx(1)
    for offset, record in [(0, data[0]), (3, data[1])]:
        chain = weights[offset:offset + len(record['events'])]
        assert chain[record['events']].sum() == pytest.approx(.5)
        assert chain[~record['events']].sum() == pytest.approx(.5)


def test_loco_folds_are_whole_chains_and_scaler_never_sees_validation_rows():
    data = records()
    fitted, provenance = fit_development(data, c_grid=[.1, 1])
    assert set(fitted) == {'margin-lr', 'margin-history-lr'}
    assert provenance['C_grid'] == [.1, 1.]
    json.dumps(provenance, allow_nan=False)
    names = {r['chain_id'] for r in data}
    for method, result in provenance['methods'].items():
        key = 'margin_features' if method == 'margin-lr' else 'combined_features'
        for candidate in result['candidates']:
            for fold in candidate['folds']:
                assert set(fold['train_chain_ids']) == names - {fold['validation_chain_id']}
                training = [r for r in data if r['chain_id'] != fold['validation_chain_id']]
                expected = np.average(np.concatenate([r[key] for r in training]), axis=0, weights=chain_weights(training))
                np.testing.assert_allclose(fold['training_feature_mean'], expected)
    # There is a real incremental signal deliberately independent of margin.
    assert provenance['methods']['margin-history-lr']['selected_macro_average_precision'] == pytest.approx(1)
    assert provenance['methods']['margin-history-lr']['selected_macro_average_precision'] > provenance['methods']['margin-lr']['selected_macro_average_precision']


def test_c_ties_choose_smaller_value_and_input_records_are_immutable():
    data = records()
    for row in data:
        row['margin_features'][:] = 0
        row['combined_features'][:] = 0
    before = deepcopy(data)
    _, provenance = fit_development(data, c_grid=[10, .01, 1])
    assert all(m['selected_C'] == .01 for m in provenance['methods'].values())
    for actual, expected in zip(data, before):
        for key in ['events', 'margin_features', 'combined_features']:
            np.testing.assert_array_equal(actual[key], expected[key])


def test_single_class_validation_chain_is_explicit_na_and_retained_for_training():
    data = records()
    data[0]['events'][:] = False
    _, provenance = fit_development(data, c_grid=[1])
    assert provenance['development_chains'][0]['positive_events'] == 0
    for method in provenance['methods'].values():
        skipped = method['candidates'][0]['folds'][0]
        assert skipped['na_reason'] == 'ONE_CLASS_VALIDATION'
        assert skipped['average_precision'] is None
        assert 'chain-0' in method['candidates'][0]['folds'][1]['train_chain_ids']


def test_no_usable_development_folds_does_not_fabricate_fit_or_default_C():
    data = records()
    for row in data: row['events'][:] = False
    with pytest.raises(ValueError, match='INSUFFICIENT_TWO_CLASS_CHAIN_FOLDS'):
        fit_development(data)
    data = records()
    data[1]['chain_id'] = data[0]['chain_id']
    with pytest.raises(ValueError, match='DUPLICATE_DEVELOPMENT_CHAIN'):
        fit_development(data)


def test_selection_has_same_budget_and_fixed_id_ties_without_target_input():
    data = records()
    fitted, _ = fit_development(data, c_grid=[1])
    # Equal feature vectors tie in both models, irrespective of input order.
    features = dict(margin_features=np.zeros((3, 1)), combined_features=np.zeros((3, 6)))
    selected = select_pair(fitted, features, ['c', 'a', 'b'], [1, 2, 5])
    assert len(selected) == 6
    for method in fitted:
        actual = [s for s in selected if s['method'] == method]
        assert [s['indices'] for s in actual] == [[1], [1, 2], [1, 2, 0]]
    assert set(inspect.signature(select_pair).parameters) == {'fitted', 'features', 'sample_ids', 'budgets'}


def test_empty_current_correct_pool_is_supported_in_features_scores_and_selection():
    gold, history, probabilities, labels = historical_example()
    gold = np.asarray(labels)[1 - probabilities[:, 2].argmax(axis=1)]
    feature = history_features(gold, history, probabilities, labels, risk_scores=[])
    assert feature['pool_indices'] == []
    assert feature['margin_features'].shape == (0, 1)
    assert feature['combined_features'].shape == (0, 6)
    fitted, _ = fit_development(records(), c_grid=[1])
    assert all(score.size == 0 for score in score_pair(fitted, feature).values())
    assert all(not s['indices'] for s in select_pair(fitted, feature, [], [20, 100]))


def test_disagreeing_margin_column_between_the_two_models_is_rejected():
    data = records()
    data[0]['combined_features'][0, 0] += .1
    with pytest.raises(ValueError, match='INCONSISTENT_MARGIN_DESIGNS'):
        fit_development(data)
