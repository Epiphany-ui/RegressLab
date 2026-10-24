"""Completeness and chronology failures that valid hashes alone cannot catch."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from preflight.runner import digest, file_hash
from preflight.verify_incremental import check_benchmark, check_events, close, expected_matrix, observed


@pytest.fixture
def config():
    return json.loads((Path(__file__).parents[1]/'configs/history-increment-v1.json').read_text())


def test_registered_whole_matrix_and_target_exclusion(config):
    specs, keys, files = expected_matrix(config)
    heldout = [s for s in specs if s['role'] == 'heldout']
    dev = [s for s in specs if s['role'] == 'development']
    assert len(specs) == 16 and len(heldout) == 12 and len(dev) == 4
    assert len(keys) == 96 and len(keys)*len(heldout) == 1152
    assert len(files) == 131
    assert not any(path.endswith('/target.npz') for path in files)
    assert all(f"chains/{s['chain_id']}/development-observations.npz" in files for s in dev)
    assert all(f"chains/{s['chain_id']}/frozen-observations.npz" in files for s in heldout)
    assert len({s['seed'] for s in heldout}) == 3


@pytest.mark.parametrize('change', [
    lambda c: c['methods'].remove('risk-top'),
    lambda c: c['methods'].append('margin-lr'),
    lambda c: c.update(heldout_seeds=[1103, 1109]),
    lambda c: c.update(neural_development_seeds=[1103, 907]),
    lambda c: c['budgets'].append(100),
    lambda c: c.update(growth_fractions=[.4, .6, 1., 1.]),
    lambda c: c['predictor'].update(C_grid=[1.]),
    lambda c: c['decision_policy'].update(minimum_events_per_chain=1),
])
def test_registered_matrix_cannot_be_silently_reduced_or_retuned(config, change):
    change(config)
    with pytest.raises(ValueError):
        expected_matrix(config)


def event_fixture(tmp_path, config):
    specs, keys, _ = expected_matrix(config)
    chains = [dict(**s, versions=[dict(slot=f'f{k}', train_seconds=.1) for k in range(4)], future_flip_count=25, pool_count=300, suite_count=len(keys)) for s in specs]
    prereg = dict(config=config, config_sha256=digest(config), chain_specifications=specs)
    report = dict(decision=dict(recommendation='TEST_FIXTURE'))
    (tmp_path/'matrix-freeze.json').write_text('{}\n')
    events = []
    def add(kind, **details):
        events.append(dict(event=kind, details=details, time='2026-10-24T00:00:00+00:00', previous_sha256=None))
    add('PREREGISTERED', config_sha256=prereg['config_sha256'])
    add('DATA_AUDITED', train_count=14995, dev_count=2997, formal_test_model_inputs=0)
    for chain in chains:
        for slot in range(4):
            add('MODEL_TRAINED', chain_id=chain['chain_id'], role=chain['role'], slot=f'f{slot}', seconds=.1, dev_predicted=False, restore_inference_scope='TRAIN_ONLY_UP_TO_32_ROWS')
    add('GLOBAL_IDENTITY_GATE', passed=True, current_node_count=64, previous_node_count=72)
    for chain in chains:
        if chain['role'] == 'development':
            add('DEVELOPMENT_TARGET_EXPOSED', chain_id=chain['chain_id'], role='development', future_flip_count=25)
    add('PREDICTORS_FROZEN', development_chain_ids=dict(sgd=list(config['linear_development_chain_ids']), neural=[s['chain_id'] for s in specs if s['role']=='development']))
    for chain in chains:
        if chain['role'] == 'heldout':
            add('HELDOUT_SUITES_READY', chain_id=chain['chain_id'], pool_count=300, cell_count=len(keys))
    add('ALL_HELDOUT_SUITES_FROZEN', chain_count=12, cell_count=1152, freeze_sha256=file_hash(tmp_path/'matrix-freeze.json'))
    for chain in chains:
        if chain['role'] == 'heldout':
            add('HELDOUT_TARGET_EVALUATED', chain_id=chain['chain_id'], future_flip_count=25)
    add('COMPLETED', recommendation='TEST_FIXTURE')
    return events, prereg, chains, report


def write_events(path, events):
    for i, row in enumerate(events):
        row['previous_sha256'] = digest(events[i-1]) if i else None
    (path/'events.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in events))


def test_development_target_is_permitted_and_all_heldout_targets_follow_global_freeze(tmp_path, config):
    events, prereg, chains, report = event_fixture(tmp_path, config)
    write_events(tmp_path, events)
    assert check_events(tmp_path, prereg, chains, report, 1152) == 98


@pytest.mark.parametrize('kind,before,error', [
    ('HELDOUT_TARGET_EVALUATED', 'ALL_HELDOUT_SUITES_FROZEN', 'HELDOUT_TARGET_BEFORE_GLOBAL_FREEZE'),
    ('DEVELOPMENT_TARGET_EXPOSED', 'GLOBAL_IDENTITY_GATE', 'DEVELOPMENT_TARGET_EVENT_SCOPE_MISMATCH'),
    ('HELDOUT_SUITES_READY', 'PREDICTORS_FROZEN', 'HELDOUT_SUITE_EVENT_SCOPE_MISMATCH'),
])
def test_rehashing_cannot_hide_early_target_or_suite_phases(tmp_path, config, kind, before, error):
    events, prereg, chains, report = event_fixture(tmp_path, config)
    row = next(e for e in events if e['event'] == kind)
    events.remove(row)
    events.insert(next(i for i,e in enumerate(events) if e['event'] == before), row)
    write_events(tmp_path, events)
    with pytest.raises(ValueError, match=error):
        check_events(tmp_path, prereg, chains, report, 1152)


def test_rehashed_missing_heldout_events_are_rejected(tmp_path, config):
    events, prereg, chains, report = event_fixture(tmp_path, config)
    events = [e for e in events if e['event'] != 'HELDOUT_TARGET_EVALUATED']
    write_events(tmp_path, events)
    with pytest.raises(ValueError, match='EVENT_SET_MISMATCH'):
        check_events(tmp_path, prereg, chains, report, 1152)


def test_heldout_chain_cannot_be_claimed_as_predictor_development_source(tmp_path, config):
    events, prereg, chains, report = event_fixture(tmp_path, config)
    fitted = next(e for e in events if e['event'] == 'PREDICTORS_FROZEN')
    fitted['details']['development_chain_ids']['sgd'].append(next(c['chain_id'] for c in chains if c['role']=='heldout'))
    write_events(tmp_path, events)
    with pytest.raises(ValueError, match='PREDICTOR_SOURCE_EVENT_MISMATCH'):
        check_events(tmp_path, prereg, chains, report, 1152)


def test_floating_fit_replay_does_not_ignore_missing_features_or_fields():
    close(dict(coefficients=[.1,.2], score=.8), dict(coefficients=[.1+1e-13,.2], score=.8), 'MISMATCH')
    with pytest.raises(ValueError):
        close(dict(coefficients=[.1]), dict(coefficients=[.1,.2]), 'MISMATCH')
    with pytest.raises(ValueError):
        close(dict(coefficients=[.1,.2]), dict(coefficients=[.1,.2], score=.8), 'MISMATCH')


def test_inference_benchmark_repeated_median_and_scope():
    block = dict(wall_seconds=[.3,.1,.2], median_seconds=.2, sample_count=100, repetitions=3, scope='text_normalize_encode_transform_and_predict_proba_argmax')
    assert check_benchmark(block, 100, 3) == .2
    with pytest.raises(ValueError, match='COST_BENCHMARK_MEDIAN_MISMATCH'):
        check_benchmark(dict(block,median_seconds=.01), 100, 3)
    with pytest.raises(ValueError, match='COST_BENCHMARK_SCOPE_MISMATCH'):
        check_benchmark(block, 200, 3)


def test_heldout_history_observations_cannot_smuggle_target_column(tmp_path):
    ids = ['a','b']
    history = np.array([['A','A','A'],['B','B','B']])
    scores = np.array([[[.9,.1]]*3,[[.1,.9]]*3])
    path = tmp_path/'frozen.npz'
    np.savez(path, sample_ids=ids, history=history, probabilities=scores, target=np.array(['A','B']))
    with pytest.raises(ValueError, match='OBSERVATION_FIELDS_OR_SAMPLE_ALIGNMENT_MISMATCH'):
        observed(path, ids, ['A','B'], development=False)
