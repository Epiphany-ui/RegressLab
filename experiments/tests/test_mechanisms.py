"""Small deterministic checks; never execute the registered 200-environment grid."""
from copy import deepcopy
import inspect

import numpy as np
import pytest

from preflight.mechanisms import DEFAULT_MECHANISM_CONFIG, build_environment, freeze_record, generate_target, select_suites, summarize, target_probability, validate_config
from preflight.runner import digest


def small_suite(seed=17, scenario='risk_persists'):
    environment = build_environment(seed, scenario, n_rows=80)
    suites, diagnostic = select_suites(environment['rows'], environment['history'], environment['pool_indices'], environment['reference_probabilities'])
    return environment, suites, diagnostic


def test_exact_future_probabilities_include_margin_signal_in_both_regimes():
    record = dict(scenario='risk_persists', margin_regime='complementary', latent=dict(negation=[True, False, False], digit=[False, True, False], difficulty=[0, .5, 1]))
    assert target_probability(record).tolist() == pytest.approx([.29, .07, .13])
    record['scenario'] = 'risk_reversed'
    assert target_probability(record).tolist() == pytest.approx([.01, .35, .41])
    record['scenario'] = 'new_risk'
    assert target_probability(record).tolist() == pytest.approx([.01, .35, .13])
    record['scenario'] = 'overlap'
    assert target_probability(record).tolist() == pytest.approx([.15, .21, .13])
    record['margin_regime'] = 'strong_margin'
    assert target_probability(record).tolist() == pytest.approx([.04, .265, .46])
    record['scenario'] = 'no_group_signal'
    assert target_probability(record).tolist() == pytest.approx([.01, .235, .46])


def test_no_group_signal_control_is_unchanged_by_group_membership():
    record = dict(scenario='no_group_signal', margin_regime='complementary', latent=dict(negation=[True, False], digit=[False, True], difficulty=[.2, .8]))
    before = target_probability(record)
    record['latent']['negation'] = [False, True]
    record['latent']['digit'] = [True, False]
    assert np.array_equal(before, target_probability(record))
    assert before[1] > before[0]  # confidence is still informative in the control


def test_history_is_temporally_legal_pool_exact_and_paired_inputs_match():
    environment = build_environment(17, 'risk_persists', n_rows=80)
    repeated = build_environment(17, 'new_risk', n_rows=80)
    gold = np.asarray([r['gold_label'] for r in environment['rows']])
    correct = environment['history'] == gold[:, None]
    negative = correct[:, :-1] & ~correct[:, 1:]
    assert not np.any(negative[:, 0] & negative[:, 1])
    assert environment['pool_indices'] == np.flatnonzero(correct[:, 2]).tolist()
    assert not np.any(negative[environment['pool_indices'], 1])
    assert environment['rows'] == repeated['rows']
    assert environment['latent'] == repeated['latent']
    assert np.array_equal(environment['history'], repeated['history'])
    assert list(gold).count('A') == list(gold).count('B') == 40
    probabilities = environment['reference_probabilities']
    assert np.allclose(probabilities.sum(axis=1), 1)
    assert np.array_equal(np.asarray(['A', 'B'])[probabilities.argmax(axis=1)], gold[environment['pool_indices']])


def test_all_methods_have_complete_budget_seed_matrix_and_shared_prefixes():
    environment, suites, diagnostics = small_suite()
    assert len(suites) == (20 + 4) * 3 == 72
    assert {s['method'] for s in suites} == {'random', 'facility', 'risk-top', 'ref-margin', 'hgc'}
    assert sum(s['method'] == 'random' for s in suites) == 60
    for method, seed in {(s['method'], s['seed']) for s in suites}:
        rows = sorted([s for s in suites if (s['method'], s['seed']) == (method, seed)], key=lambda x: x['budget'])
        longest = rows[-1]['indices']
        for row in rows:
            assert row['indices'] == longest[:min(row['budget'], len(environment['pool_indices']))]
            assert len(set(row['indices'])) == len(row['indices'])
    assert diagnostics['proxy_values'][-1]['budget'] == 100


def test_selector_has_no_latent_scenario_or_future_input():
    assert list(inspect.signature(select_suites).parameters) == ['rows', 'history', 'pool', 'reference_probabilities', 'config']
    environment, suites, diagnostics = small_suite()
    record = freeze_record(environment, 'complementary', suites, diagnostics)
    assert 'target' not in record and 'future_predictions' not in record
    before = deepcopy(record)
    generated = generate_target(record, digest(record))
    assert record == before
    assert np.array_equal(generated, generate_target(record, digest(record)))
    record['selections'][0]['indices'].reverse()
    with pytest.raises(ValueError, match='SYNTHETIC_PRETARGET_FREEZE_CHANGED'):
        generate_target(record, digest(before))


def test_hgc_zero_risk_case_matches_facility_without_fabricated_groups():
    environment = build_environment(17, 'risk_persists', n_rows=80)
    gold = np.asarray([r['gold_label'] for r in environment['rows']])
    history = np.column_stack([gold, gold, gold])
    confidence = np.full(len(gold), .8)
    probability_a = np.where(gold == 'A', confidence, 1-confidence)
    probabilities = np.column_stack([probability_a, 1-probability_a])
    suites, diagnostics = select_suites(environment['rows'], history, list(range(len(gold))), probabilities)
    assert diagnostics['groups'] == []
    for budget in [20, 50, 100]:
        selected = {s['method']: s['indices'] for s in suites if s['budget'] == budget and s['seed'] is None}
        assert selected['hgc'] == selected['facility']


def test_summary_aggregates_random_seeds_before_environment_differences():
    config = deepcopy(DEFAULT_MECHANISM_CONFIG)
    config.update(scenarios=['risk_persists'], environment_seeds=[1, 2], selection_seeds=[0, 1], budgets=[100])
    config['margin_regimes'] = {'complementary': config['margin_regimes']['complementary']}
    cells = []
    for seed in [1, 2]:
        for method in config['methods']:
            values = ([.2, .4] if seed == 1 else [.6, .8]) if method == 'random' else ([.5] if seed == 1 else [.75]) if method == 'hgc' else [.4]
            for selection_seed, recall in enumerate(values):
                cells.append(dict(environment_id=f'env{seed}', scenario='risk_persists', margin_regime='complementary', environment_seed=seed, method=method, budget=100, seed=selection_seed if method == 'random' else None, recall=recall, detected=10*recall, future_flip_count=10))
    env_rows, aggregate, paired = summarize(cells, config)
    random = next(a for a in aggregate if a['method'] == 'random')
    assert random['environment_count'] == 2
    assert random['mean_recall'] == pytest.approx(.5)
    assert random['std_recall'] == pytest.approx(.2)
    assert [r['selection_seed_count'] for r in env_rows if r['method'] == 'random'] == [2, 2]
    versus_random = next(d for d in paired if d['comparator'] == 'random')
    assert versus_random['mean_hgc_recall_difference'] == pytest.approx(.125)
    assert versus_random['paired_environment_count'] == 2


def test_fixed_registration_rejects_new_config_and_retuning():
    validate_config(deepcopy(DEFAULT_MECHANISM_CONFIG))
    changed = deepcopy(DEFAULT_MECHANISM_CONFIG)
    changed['hgc']['lambda'] = .75
    with pytest.raises(ValueError, match='FIXED_MECHANISM_REGISTRATION_REQUIRED'):
        validate_config(changed)
    changed = deepcopy(DEFAULT_MECHANISM_CONFIG)
    changed['environment_seeds'].append(9001)
    with pytest.raises(ValueError, match='FIXED_MECHANISM_REGISTRATION_REQUIRED'):
        validate_config(changed)


def test_small_mocked_registration_run_seals_entire_grid_before_targets(tmp_path, monkeypatch):
    """Two small unit environments; never the actual registered 200-grid run."""
    import json
    import preflight.mechanisms as mechanism
    config = deepcopy(DEFAULT_MECHANISM_CONFIG)
    config.update(n_rows=80, scenarios=['risk_persists'], environment_seeds=[17, 23], selection_seeds=[0, 1], budgets=[3, 5], primary_budget=5)
    config['margin_regimes'] = {'complementary': config['margin_regimes']['complementary']}
    monkeypatch.setattr(mechanism, 'validate_config', lambda _: None)
    original_target = mechanism.generate_target
    output = tmp_path / 'unit-only'
    calls = []
    def target_after_physical_freeze(record, frozen_sha, actual_config):
        frozen = json.loads((output / 'matrix-freeze.json').read_text())
        assert frozen['environment_count'] == 2
        assert len(frozen['semantic_record_hashes']) == 2
        events = [json.loads(line)['event'] for line in (output / 'events.jsonl').read_text().splitlines()]
        assert 'ALL_ENVIRONMENT_SUITES_FROZEN' in events
        calls.append(record['environment_id'])
        return original_target(record, frozen_sha, actual_config)
    monkeypatch.setattr(mechanism, 'generate_target', target_after_physical_freeze)
    report = mechanism.run(config, output)
    assert report['environment_count'] == 2 and report['cell_count'] == 24
    assert report['natural_model_effect_proven'] is False
    assert len(calls) == 2
    audited = mechanism.verify(output)
    assert audited['status'] == 'PASS' and audited['cells_recomputed'] == 24
    assert audited['event_count'] == 7
    changed = json.loads((output / 'report.json').read_text())
    changed['aggregates'] = []
    (output / 'report.json').write_text(json.dumps(changed))
    with pytest.raises(ValueError, match='MECHANISM_REPORT_REPLAY_MISMATCH'):
        mechanism.verify(output)
