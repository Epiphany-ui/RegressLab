"""Update data membership and prespecified decision boundaries, without fitting."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from preflight import incremental_run
from preflight.incremental_run import (
    benchmark, identity_gate, screen, specifications, training_indices,
    validate_config, validate_suites,
)
from preflight.runner import nested_train_indices


@pytest.fixture
def config():
    return json.loads((Path(__file__).parents[1] / 'configs/history-increment-v1.json').read_text())


def train_rows():
    return [dict(sample_id=f'train:{label}:{i:03}', text=f'example {label} {i}', gold_label=label, role='TRAIN')
            for label, count in [('A', 10), ('B', 11)] for i in range(count)]


def selected_ids(rows, selected):
    return [rows[i]['sample_id'] for i in selected]


def test_refresh_updates_exchange_class_stratified_blocks_and_are_order_invariant():
    rows = train_rows()
    versions = [training_indices(rows, 'data-refresh', slot, 17) for slot in range(4)]
    id_sets = [set(selected_ids(rows, chosen)) for chosen in versions]
    assert len({frozenset(values) for values in id_sets}) == 4
    assert [Counter(rows[i]['gold_label'] for i in version) for version in versions] == [
        Counter(A=8, B=8), Counter(A=8, B=9), Counter(A=8, B=9), Counter(A=8, B=9)]
    # Each datum is retained in three of the four slots, except block four
    # which remains in all slots. No examples outside TRAIN are introduced.
    appearances = Counter(sample for selected in id_sets for sample in selected)
    assert set(appearances.values()) == {3, 4}
    assert len(appearances) == len(rows)
    reversed_rows = list(reversed(rows))
    for slot, expected in enumerate(id_sets):
        actual = training_indices(reversed_rows, 'data-refresh', slot, 17)
        assert set(selected_ids(reversed_rows, actual)) == expected
    # The registered representation basis is fixed TRAIN state. For refresh
    # it can contain rows excluded from f0; its provenance must say so.
    basis = set(selected_ids(rows, nested_train_indices(rows, .4, 17)))
    assert basis - id_sets[0]


def test_growth_updates_are_nested_and_reject_non_train_members():
    rows = train_rows()
    choices = [set(training_indices(rows, 'data-growth', slot, 19)) for slot in range(4)]
    assert choices[0] < choices[1] < choices[2] < choices[3] == set(range(len(rows)))
    assert choices[0] == set(nested_train_indices(rows, .4, 19))
    rows[0]['role'] = 'TEST'
    for family in ['data-growth', 'data-refresh']:
        with pytest.raises(ValueError, match='TRAIN_ONLY_REQUIRED'):
            training_indices(rows, family, 0, 19)
    with pytest.raises(ValueError, match='UNKNOWN_REGISTERED_UPDATE'):
        training_indices(train_rows(), 'data-refresh', True, 19)


def test_registration_has_four_development_and_twelve_whole_heldout_chains(config):
    validate_config(config)
    specs = specifications(config)
    development = [s for s in specs if s['role'] == 'development']
    heldout = [s for s in specs if s['role'] == 'heldout']
    assert len(development) == 4 and len(heldout) == 12
    assert {s['architecture'] for s in development} == {'neural'}
    assert len({s['chain_id'] for s in specs}) == 16
    assert {s['seed'] for s in development}.isdisjoint({s['seed'] for s in heldout})
    assert len(specs) * 4 == 64


@pytest.mark.parametrize('mutation,code', [
    (lambda c: c['growth_fractions'].__setitem__(1, .5), 'UPDATE_RECIPE'),
    (lambda c: c['predictor']['features'].reverse(), 'PREDICTOR_RECIPE'),
    (lambda c: c['predictor']['C_grid'].append(100), 'PREDICTOR_RECIPE'),
    (lambda c: c['heldout_seeds'].__setitem__(0, c['neural_development_seeds'][0]), 'SEED_OVERLAP'),
    (lambda c: c['methods'].remove('ref-margin'), 'SELECTION_MATRIX'),
    (lambda c: c['decision_policy'].__setitem__('minimum_events_per_chain', 19), 'DECISION_POLICY'),
])
def test_configuration_fields_cannot_describe_an_unimplemented_recipe(config, mutation, code):
    mutation(config)
    with pytest.raises(ValueError, match=code):
        validate_config(config)


def screen_data(config):
    chains, cells, rankings = [], [], []
    for architecture in config['architectures']:
        for family in config['families']:
            for index in range(3):
                chain_id = f'{architecture}-{family}-{index}'
                chains.append(dict(chain_id=chain_id, architecture=architecture, family=family, role='heldout', future_flip_count=20))
                for method, recall, ap in [('margin-lr', .55, .2), ('margin-history-lr', .6, .3), ('ref-margin', .59, .25), ('risk-top', .1, .1)]:
                    cells.append(dict(chain_id=chain_id, method=method, budget=100, seed=None, recall=recall))
                    rankings.append(dict(chain_id=chain_id, method=method, average_precision=ap))
    return chains, cells, rankings


def test_exact_registered_recall_and_event_boundaries_pass_descriptively(config):
    result = screen(config, *screen_data(config))
    assert result['recommendation'] == 'REPLICATED_INCREMENT_CANDIDATE'
    assert set(result['replicated_update_conditions']) == set(config['families'])
    assert all(g['adequate_events'] and g['stable_increment'] for g in result['groups'].values())
    assert result['formal_test_model_inputs'] == 0
    assert result['statistical_superiority_established'] is False
    assert result['academic_novelty_established'] is False
    assert result['final_title_established'] is False
    assert result['automatic_further_search'] is False


def test_low_event_chain_is_not_dropped_or_repaired_with_extra_updates(config):
    chains, cells, rankings = screen_data(config)
    # One insufficient chain in each update cell; strong scores cannot
    # override the fixed event support condition.
    for chain in chains[::3]: chain['future_flip_count'] = 19
    result = screen(config, chains, cells, rankings)
    assert result['recommendation'] == 'INCONCLUSIVE_EVENT_SUPPORT'
    assert all(not group['adequate_events'] for group in result['groups'].values())


def test_absence_of_increment_with_adequate_events_has_explicit_stop_result(config):
    chains, cells, rankings = screen_data(config)
    for row in cells:
        if row['method'] == 'margin-history-lr': row['recall'] = .55
    result = screen(config, chains, cells, rankings)
    assert result['recommendation'] == 'NO_DETECTED_STABLE_INCREMENT'
    assert result['all_cells_adequate'] is True
    assert result['automatic_further_search'] is False


def test_one_architecture_signal_is_exploratory_and_requires_replication(config):
    chains, cells, rankings = screen_data(config)
    sgd_ids = {c['chain_id'] for c in chains if c['architecture'] == 'sgd'}
    for row in cells:
        if row['chain_id'] in sgd_ids and row['method'] == 'margin-history-lr': row['recall'] = .55
    result = screen(config, chains, cells, rankings)
    assert result['recommendation'] == 'CONDITIONAL_SIGNAL_REQUIRES_REPLICATION'
    assert result['replicated_update_conditions'] == []


@pytest.mark.parametrize('failure', ['raw_margin', 'raw_tie', 'AP', 'one_positive_only', 'excess_chain_loss'])
def test_stability_requires_more_than_a_positive_average(config, failure):
    chains, cells, rankings = screen_data(config)
    for group in [(a, f) for a in config['architectures'] for f in config['families']]:
        ids = [c['chain_id'] for c in chains if (c['architecture'], c['family']) == group]
        for row in cells:
            if row['chain_id'] not in ids: continue
            if failure == 'raw_margin' and row['method'] == 'ref-margin': row['recall'] = .61
            if failure == 'raw_tie' and row['method'] == 'ref-margin': row['recall'] = .6
            if failure == 'one_positive_only' and row['method'] == 'margin-history-lr':
                row['recall'] = [.55, .55, .85][ids.index(row['chain_id'])]
            if failure == 'excess_chain_loss' and row['method'] == 'margin-history-lr':
                row['recall'] = [.499, .75, .75][ids.index(row['chain_id'])]
        if failure == 'AP':
            for row in rankings:
                if row['chain_id'] in ids and row['method'] == 'margin-history-lr': row['average_precision'] = .2
    result = screen(config, chains, cells, rankings)
    assert result['recommendation'] == 'NO_DETECTED_STABLE_INCREMENT'


def test_identity_gate_rejects_reused_target_and_accepts_distinct_states():
    chain = dict(chain_id='new', versions=[dict(slot=f'f{i}', identity=dict(label_state_sha256=f'state{i}')) for i in range(4)])
    assert identity_gate([chain], [])['passed'] is True
    for previous in [dict(chain_id='old', slot='f0', label_state_sha256='state3'), dict(chain_id='old', slot='f3', label_state_sha256='state3')]:
        assert identity_gate([chain], [previous])['passed'] is False
    duplicate = deepcopy(chain)
    duplicate['chain_id'] = 'other'
    assert identity_gate([chain, duplicate], [])['passed'] is False


def test_exact_selection_matrix_and_duplicate_indices_are_checked(config):
    selected = [dict(method=method, seed=seed, budget=b, indices=list(range(min(3, b))))
                for method in config['methods'] for seed in (config['selection_seeds'] if method == 'random' else [None]) for b in config['budgets']]
    assert len(selected) == 96
    validate_suites(selected, 3, config)
    with pytest.raises(ValueError, match='MATRIX_INCOMPLETE'):
        validate_suites(selected[:-1], 3, config)
    selected[0]['indices'] = [0, 0, 1]
    with pytest.raises(ValueError, match='INVALID_INCREMENT_SELECTION'):
        validate_suites(selected, 3, config)


def test_benchmark_measures_normalization_and_transform_and_does_not_infer_empty_pool(monkeypatch):
    calls = []
    def normalize(text):
        calls.append(('normalize', text))
        return text.strip()
    def infer(bundle, architecture, texts, labels):
        calls.append(('infer', list(texts)))
        return None, np.array(texts)
    monkeypatch.setattr(incremental_run, 'normalize_text', normalize)
    monkeypatch.setattr(incremental_run, 'inference', infer)
    result = benchmark({}, 'sgd', [' A ', ' B '], ['A', 'B'], ['A', 'B'], 3)
    assert calls == [('normalize', ' A '), ('normalize', ' B '), ('infer', ['A', 'B'])] * 3
    assert result['scope'] == 'text_normalize_encode_transform_and_predict_proba_argmax'
    assert result['sample_count'] == 2 and result['repetitions'] == 3
    calls.clear()
    assert benchmark({}, 'sgd', [], ['A', 'B'], [], 3)['sample_count'] == 0
    assert calls == []
    with pytest.raises(ValueError, match='POSITIVE_BENCHMARK_REPEATS'):
        benchmark({}, 'sgd', [], ['A', 'B'], [], True)
