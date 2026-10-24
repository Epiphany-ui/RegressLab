"""Exact small checks for the second-round gate and accounting boundaries."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from preflight.round2 import aggregate_cells, benchmark_predict, screen_report, validate_selection_matrix
from preflight.verify2 import expected_matrix, deployment_costs, benchmark_block


@pytest.fixture
def config():
    return json.loads((Path(__file__).parents[1] / 'configs/cpu-preflight-v2.json').read_text())


def test_registered_complete_matrix_has_exact_counts(config):
    chains, keys, files = expected_matrix(config)
    assert len(chains) == 6
    assert len(keys) == 344
    assert len(files) == 83
    rows = [dict(method=m, seed=s, budget=b, indices=[0, 1]) for m, s, b in keys]
    validate_selection_matrix(rows, config, 2)
    with pytest.raises(ValueError, match='INCOMPLETE_OR_DUPLICATE'):
        validate_selection_matrix(rows[:-1], config, 2)
    with pytest.raises(ValueError, match='INCOMPLETE_OR_DUPLICATE'):
        validate_selection_matrix(rows[:-1] + [rows[0]], config, 2)
    rows[0]['indices'] = [0, 0]
    with pytest.raises(ValueError, match='INVALID_SELECTION_BEFORE_FREEZE'):
        validate_selection_matrix(rows, config, 2)


def test_registration_rejects_unregistered_primary_and_missing_methods(config):
    config['primary_budget'] = 99
    with pytest.raises(ValueError, match='PRIMARY_BUDGET_NOT_REGISTERED'):
        expected_matrix(config)
    config['primary_budget'] = 100
    config['methods'].remove('ref-margin')
    with pytest.raises(ValueError, match='REGISTERED_METHOD_SET_MISMATCH'):
        expected_matrix(config)


def test_aggregate_seed_mean_and_zero_denominator_are_distinct():
    cells = [dict(chain_id='a', family='f', method='random', budget=2, recall=r, detected=d, actual_size=2) for r, d in [(0.25, 1), (0.75, 3)]]
    cells += [dict(chain_id='b', family='f', method='random', budget=2, recall=None, detected=0, actual_size=2)]
    first, zero = aggregate_cells(cells)
    assert first['mean_recall'] == 0.5 and first['std_recall'] == 0.25
    assert first['mean_detected'] == 2 and first['seed_count'] == 2
    assert zero['mean_recall'] is zero['std_recall'] is None


def test_screen_is_descriptive_and_never_authorizes_third_round(config):
    chains, aggregates, costs = [], [], []
    for family in config['families']:
        for i, count in enumerate([20, 20, 0]):
            name = family['id'] + str(i)
            chains.append(dict(chain_id=name, family=family['id'], future_flip_count=count))
            for method, recall in [('hgc', 0.5), ('ref-margin', 0.52)]:
                aggregates.append(dict(chain_id=name, method=method, budget=100, mean_recall=recall if count else None))
            costs.append(dict(chain_id=name, method='hgc', deployment_cost_ratio=0.7))
    result = screen_report(config, chains, aggregates, costs)
    assert result['minimum_event_screen_met'] is True
    assert result['descriptive_hgc_recall_screen_met'] is False  # zero-event chain is not silently removed
    assert result['cached_history_hgc_cost_screen_met'] is True
    assert result['formal_gate_approved'] is False
    assert result['automatic_third_tuning_round_authorized'] is False
    costs[0]['deployment_cost_ratio'] = 1.1
    assert screen_report(config, chains, aggregates, costs)['cached_history_hgc_cost_screen_met'] is False


def test_benchmark_includes_transform_and_predict_and_requires_consistency():
    calls = []
    class Representation:
        def transform(self, texts):
            calls.append(('transform', len(texts)))
            return np.array([len(text) for text in texts])
    class Classifier:
        def predict(self, data):
            calls.append(('predict', len(data)))
            return data.astype(str)
    bundle = dict(vectorizer=Representation(), classifier=Classifier())
    result = benchmark_predict(bundle, ['x', 'xx'], ['1', '2'])
    assert calls == [('transform', 2), ('predict', 2)] * 5
    assert result['sample_count'] == 2 and result['median_seconds'] >= 0
    with pytest.raises(ValueError, match='BENCHMARK_PREDICTION_MISMATCH'):
        benchmark_predict(bundle, ['x'], ['wrong'])
    for invalid in [0, -1, True, 1.5]:
        with pytest.raises(ValueError, match='POSITIVE_BENCHMARK_REPEATS_REQUIRED'):
            benchmark_predict(bundle, ['x'], repeats=invalid)


def test_cost_recomputes_median_and_charges_shared_validation(config):
    config['selection_seeds'] = [0]
    _, keys, _ = expected_matrix(config)
    selections = [dict(method=m, seed=s, budget=b, indices=list(range(min(b, 200)))) for m, s, b in sorted(keys, key=str)]
    timing = [dict(method=m, seed=s, selection_seconds=0.02, max_budget=100, includes_shared_representation=False) for m, s in {(m, s) for m, s, b in keys if m != 'hgc'}]
    timing.append(dict(method='__shared_validation__', seed=None, selection_seconds=0.01, max_budget=100, includes_shared_representation=False))
    pre = dict(all_budget_baselines=[dict(t, max_budget=200) for t in timing], primary_budget_baselines=timing, history_cache_assumed=True, selection_representation_seconds=0.04, full_pool_reference_score_rebuild_seconds=0.03, primary_budget_hgc=dict(total_seconds=0.1))
    def block(n, seconds):
        return dict(repetitions=5, wall_seconds=[seconds]*5, median_seconds=seconds, sample_count=n, scope='TEXT_TRANSFORM_AND_PREDICT')
    target = dict(full_pool=block(200, 0.2), suites=[dict(method=s['method'], seed=s['seed'], budget=100, **block(100, 0.05)) for s in selections if s['budget'] == 100])
    actual = deployment_costs(config, dict(chain_id='c', family='f', pool_count=200), selections, pre, target)
    by_method = {row['method']: row for row in actual}
    assert by_method['ref-margin']['selection_seconds'] == pytest.approx(0.03)
    assert by_method['ref-margin']['deployment_cost_ratio'] == pytest.approx(0.4)
    assert by_method['facility']['deployment_cost_ratio'] == pytest.approx(0.6)
    assert by_method['hgc']['selection_seconds'] == pytest.approx(0.1)
    assert by_method['hgc']['shared_validation_seconds'] == 0
    assert by_method['hgc']['deployment_cost_ratio'] == pytest.approx(0.95)
    tampered = deepcopy(target)
    tampered['suites'].pop()
    with pytest.raises(ValueError, match='TARGET_COST_METHOD_SET_MISMATCH'):
        deployment_costs(config, dict(chain_id='c', family='f', pool_count=200), selections, pre, tampered)
    bad = block(200, 0.2)
    bad['median_seconds'] = 1
    with pytest.raises(ValueError, match='BENCHMARK_MEDIAN_MISMATCH'):
        benchmark_block(bad, 200)
