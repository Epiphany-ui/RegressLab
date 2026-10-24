"""Bounded whole-update validation of information added to reference margin.

Development targets and held-out targets have different paths and phases. Every
held-out suite is frozen globally before the first held-out target inference.
This is a descriptive check on exposed VAL texts, never formal TEST evaluation.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import pickle
import platform
import resource
import subprocess
import time
from uuid import uuid4

import numpy as np
from sklearn.linear_model import SGDClassifier
from threadpoolctl import threadpool_limits

from .data import normalize_text
from .diagnostics import ranking_metrics
from .feasibility import prepare
from .hgc import DEFAULT_HGC_CONFIG
from .incremental import DEFAULT_C_GRID, fit_development, group_risk, history_features, score_pair, select_pair
from .linear_state import linear_identity
from .neural import (DEFAULT_NEURAL_CONFIG, build_vocabulary, fit_neural, load_neural,
                     neural_identity, neural_probabilities, save_neural)
from .runner import (ROOT, canonical, digest, evaluate_cells, file_hash,
                     nested_train_indices, probabilities, utc, vectorizer,
                     verify_freeze, write_json)


def validate_config(config):
    """Reject registered fields that the fixed implementation cannot honor."""
    predictor = config.get('predictor', {})
    expected_features = ['margin', 'past_wrong_fraction', 'negative_flip_opportunity_rate',
                         'max_gold_probability_drop', 'mean_adjacent_total_variation',
                         'frozen_group_risk']
    if (config.get('purpose') != 'FROZEN_HISTORY_INCREMENT_CHECK'
            or config.get('historical_group_config') != DEFAULT_HGC_CONFIG
            or config.get('neural') != DEFAULT_NEURAL_CONFIG
            or config.get('hgc_archived') is not True
            or config.get('dataset') != 'clinc150'
            or config.get('formal_test_model_input_count') != 0):
        raise ValueError('FIXED_INCREMENT_CONFIGURATION_REQUIRED')
    if (config.get('architectures') != ['sgd', 'neural']
            or config.get('families') != ['data-growth', 'data-refresh']
            or config.get('growth_fractions') != [.4, .6, .8, 1.]
            or config.get('basis_fraction') != .4
            or config.get('classifier_representation', {}).get('fit_on') != 'SAME_REALIZATION_FIXED_40_PERCENT_TRAIN_BASIS'
            or config.get('linear_epochs') != 20 or config.get('neural_epochs') != 12):
        raise ValueError('REGISTERED_UPDATE_RECIPE_MISMATCH')
    if (predictor.get('features') != expected_features
            or predictor.get('C_grid') != list(DEFAULT_C_GRID)
            or predictor.get('solver') != 'lbfgs' or predictor.get('max_iter') != 1000
            or predictor.get('architecture_specific') is not True
            or predictor.get('feature_search') is not False):
        raise ValueError('REGISTERED_PREDICTOR_RECIPE_MISMATCH')
    if (config.get('methods') != ['ref-margin', 'margin-lr', 'margin-history-lr', 'risk-top', 'random']
            or config.get('budgets') != [20, 50, 100, 200]
            or config.get('primary_budget') != 100
            or config.get('selection_seeds') != list(range(20))):
        raise ValueError('REGISTERED_SELECTION_MATRIX_MISMATCH')
    dev_seeds, heldout_seeds = config.get('neural_development_seeds'), config.get('heldout_seeds')
    if (not isinstance(dev_seeds, list) or not isinstance(heldout_seeds, list)
            or len(dev_seeds) != 2 or len(heldout_seeds) != 3
            or any(type(seed) is not int or seed < 0 for seed in dev_seeds + heldout_seeds)
            or len(set(dev_seeds + heldout_seeds)) != 5):
        raise ValueError('DEVELOPMENT_HELDOUT_SEED_OVERLAP_OR_INVALID_COUNT')
    policy = config.get('decision_policy', {})
    if (policy.get('chains_per_cell') != 3 or policy.get('minimum_events_per_chain') != 20
            or policy.get('minimum_positive_chains') != 2
            or policy.get('minimum_mean_recall_gain') != .05
            or policy.get('maximum_chain_loss') != .05
            or policy.get('minimum_mean_gain_over_raw_margin') != 0.
            or policy.get('raw_margin_gain_must_be_positive') is not True
            or policy.get('mean_AP_gain_must_be_positive') is not True):
        raise ValueError('REGISTERED_DECISION_POLICY_MISMATCH')
    if (config.get('resource_policy', {}).get('device') != 'cpu'
            or config['resource_policy'].get('threads') != 2
            or config.get('cost_policy', {}).get('target_benchmark_repeats') != 3):
        raise ValueError('REGISTERED_RESOURCE_OR_COST_RECIPE_MISMATCH')


def specifications(config):
    dev = [dict(role='development', architecture='neural', family=family, seed=seed)
           for family in config['families'] for seed in config['neural_development_seeds']]
    heldout = [dict(role='heldout', architecture=architecture, family=family, seed=seed)
               for architecture in config['architectures'] for family in config['families']
               for seed in config['heldout_seeds']]
    return [dict(**s, chain_id=f"{s['role']}-{s['architecture']}-{s['family']}-seed{s['seed']}")
            for s in dev + heldout]


def training_indices(rows, family, slot, seed):
    if family not in {'data-growth', 'data-refresh'} or type(slot) is not int or slot not in range(4):
        raise ValueError('UNKNOWN_REGISTERED_UPDATE')
    if family == 'data-growth':
        return nested_train_indices(rows, [.4, .6, .8, 1.0][slot], seed)
    by_label = defaultdict(list)
    for i, row in enumerate(rows):
        if row['role'] != 'TRAIN':
            raise ValueError('TRAIN_ONLY_REQUIRED')
        by_label[row['gold_label']].append(i)
    result = []
    for label in sorted(by_label):
        order = sorted(by_label[label], key=lambda i: (
            hashlib.sha256(f"pilot-train-v1|{seed}|{rows[i]['sample_id']}".encode()).digest(),
            rows[i]['sample_id'].encode()))
        result.extend(int(i) for k, block in enumerate(np.array_split(order, 5)) if k != slot for i in block)
    return sorted(result, key=lambda i: rows[i]['sample_id'].encode())


def load_bundle(directory, architecture, slot):
    if architecture == 'neural':
        return load_neural(directory / f'f{slot}.pt')
    with (directory / f'f{slot}.pkl').open('rb') as stream:
        return pickle.load(stream)


def inference(bundle, architecture, texts, labels):
    if architecture == 'neural':
        if bundle['labels'] != labels:
            raise ValueError('NEURAL_LABEL_ALIGNMENT')
        return neural_probabilities(bundle, texts)
    return probabilities(bundle['classifier'], bundle['vectorizer'].transform(texts), labels)


def train_chain(spec, train, labels, config, directory, emit):
    directory.mkdir(parents=True)
    basis = nested_train_indices(train, config['basis_fraction'], spec['seed'])
    basis_rows = [train[i] for i in basis]
    architecture = spec['architecture']
    begin = time.perf_counter()
    if architecture == 'sgd':
        representation = vectorizer(config['classifier_representation'])
        x = representation.fit([normalize_text(r['text']) for r in basis_rows]).transform(
            [normalize_text(r['text']) for r in train])
    else:
        vocabulary = build_vocabulary(basis_rows, config['neural'])
    basis_seconds = time.perf_counter() - begin
    versions = []
    for slot in range(4):
        chosen = training_indices(train, spec['family'], slot, spec['seed'])
        begin = time.perf_counter()
        if architecture == 'sgd':
            model = SGDClassifier(max_iter=config['linear_epochs'], random_state=spec['seed'], **config['linear_classifier'])
            model.fit(x[chosen], np.asarray([r['gold_label'] for r in train])[chosen])
            if model.n_iter_ != config['linear_epochs']:
                raise ValueError('FIXED_LINEAR_EPOCHS_NOT_COMPLETED')
            bundle = dict(vectorizer=representation, classifier=model)
            with (directory / f'f{slot}.pkl').open('xb') as stream:
                pickle.dump(bundle, stream, protocol=5)
            identity = linear_identity(representation, model)
            parameter_count = int(model.coef_.size + model.intercept_.size)
        else:
            bundle = fit_neural([train[i] for i in chosen], vocabulary, labels,
                                seed=spec['seed'], epochs=config['neural_epochs'],
                                config=config['neural'], max_seconds=config['resource_policy']['max_fit_seconds'])
            save_neural(bundle, directory / f'f{slot}.pt')
            identity = neural_identity(bundle)
            parameter_count = bundle['training_summary']['parameter_count']
        elapsed = time.perf_counter() - begin
        if elapsed > config['resource_policy']['max_fit_seconds']:
            raise ValueError('FIXED_FIT_TIME_BUDGET_EXCEEDED')
        restored = load_bundle(directory, architecture, slot)
        restored_identity = neural_identity(restored) if architecture == 'neural' else linear_identity(restored['vectorizer'], restored['classifier'])
        train_probe = [normalize_text(train[i]['text']) for i in chosen[:32]]
        if identity != restored_identity or not np.array_equal(
                inference(bundle, architecture, train_probe, labels)[0],
                inference(restored, architecture, train_probe, labels)[0]):
            raise ValueError('MODEL_SAVE_RESTORE_MISMATCH')
        version = dict(slot=f'f{slot}', identity=identity, train_rows=len(chosen),
                       train_ids_sha256=digest([train[i]['sample_id'] for i in chosen]),
                       basis_train_ids_sha256=digest([r['sample_id'] for r in basis_rows]),
                       epochs=config['neural_epochs'] if architecture == 'neural' else config['linear_epochs'],
                       parameter_count=parameter_count, train_seconds=elapsed, restore_exact=True,
                       restore_inference_scope='TRAIN_ONLY_UP_TO_32_ROWS',
                       model_file_sha256=file_hash(directory / f"f{slot}.{'pt' if architecture == 'neural' else 'pkl'}"))
        versions.append(version)
        emit('MODEL_TRAINED', chain_id=spec['chain_id'], role=spec['role'], slot=f'f{slot}', seconds=elapsed,
             dev_predicted=False, restore_inference_scope='TRAIN_ONLY_UP_TO_32_ROWS')
    chain = dict(**spec, versions=versions, basis_seconds=basis_seconds)
    write_json(directory / 'training.json', chain)
    return chain


def previous_nodes(config):
    result = []
    for registered in config['prior_runs']:
        directory = ROOT / registered['path']
        if file_hash(directory / 'matrix-freeze.json') != registered['freeze_sha256']:
            raise ValueError('EXPOSED_RUN_FREEZE_CHANGED')
        frozen = verify_freeze(directory)
        if len(frozen['chain_ids']) != 6:
            raise ValueError('EXPOSED_CHAIN_COUNT_CHANGED')
        for chain_id in frozen['chain_ids']:
            for slot in range(4):
                bundle = load_bundle(directory / 'chains' / chain_id, 'sgd', slot)
                identity = linear_identity(bundle['vectorizer'], bundle['classifier'])
                result.append(dict(run=registered['path'], chain_id=chain_id, slot=f'f{slot}',
                                   label_state_sha256=identity['label_state_sha256']))
    if len(result) != 72:
        raise ValueError('EXPOSED_NODE_COUNT_CHANGED')
    return result


def identity_gate(chains, previous):
    nodes = [dict(chain_id=c['chain_id'], slot=v['slot'],
                  label_state_sha256=v['identity']['label_state_sha256']) for c in chains for v in c['versions']]
    collisions = []
    for node in nodes:
        if node['slot'] != 'f3':
            continue
        for other in nodes + previous:
            if node is other:
                continue
            if node['label_state_sha256'] == other['label_state_sha256']:
                collisions.append(dict(target=node, collision=other))
    return dict(passed=not collisions, current_nodes=nodes, previous_nodes=previous,
                collisions=collisions, scope='Exact stored inference state; not functional non-equivalence or statistical independence.')


def histories(directory, architecture, dev, labels):
    texts = [normalize_text(r['text']) for r in dev]
    scores, predictions = [], []
    for slot in range(3):
        bundle = load_bundle(directory, architecture, slot)
        probability, predicted = inference(bundle, architecture, texts, labels)
        scores.append(probability)
        predictions.append(predicted)
    return np.stack(predictions, axis=1), np.stack(scores, axis=1)


def features(dev, history, scores, labels):
    gold = np.asarray([r['gold_label'] for r in dev])
    pool = np.flatnonzero(history[:, 2] == gold).tolist()
    risk, groups = group_risk(dev, history, pool)
    return history_features(gold, history, scores, labels, risk_scores=risk), groups


def old_development(config, dev, labels):
    directory = ROOT / config['prior_runs'][-1]['path']
    if json.loads((directory / 'data/clinc/dev.json').read_text()) != dev:
        raise ValueError('EXPOSED_DEVELOPMENT_ROWS_CHANGED')
    records = []
    for chain_id in config['linear_development_chain_ids']:
        path = directory / 'chains' / chain_id
        predictions, scores = [], []
        for slot in range(3):
            with np.load(path / f'f{slot}-history.npz', allow_pickle=False) as saved:
                if saved['sample_ids'].tolist() != [r['sample_id'] for r in dev]:
                    raise ValueError('DEVELOPMENT_SAMPLE_ALIGNMENT')
                predictions.append(saved['predictions'])
                scores.append(saved['probabilities'])
        history = np.stack(predictions, axis=1)
        feature, _ = features(dev, history, np.stack(scores, axis=1), labels)
        with np.load(path / 'f3-target.npz', allow_pickle=False) as saved:
            if saved['sample_ids'].tolist() != [r['sample_id'] for r in dev]:
                raise ValueError('DEVELOPMENT_TARGET_ALIGNMENT')
            target = saved['predictions']
        pool = feature['pool_indices']
        records.append(dict(chain_id=chain_id, margin_features=feature['margin_features'],
                            combined_features=feature['combined_features'],
                            events=target[pool] != np.asarray([r['gold_label'] for r in dev])[pool]))
    return records


def ordered(ids, scores):
    return sorted(range(len(ids)), key=lambda i: (-float(scores[i]), ids[i].encode('utf-8')))


def suites(pair, feature, ids, config):
    selections = select_pair(pair, feature, ids, config['budgets'])
    scores = score_pair(pair, feature)
    scores['ref-margin'] = -feature['margin_features'][:, 0]
    scores['risk-top'] = feature['combined_features'][:, -1]
    for method in ['ref-margin', 'risk-top']:
        order = ordered(ids, scores[method])
        selections += [dict(method=method, seed=None, budget=b, indices=order[:min(b, len(ids))]) for b in config['budgets']]
    for seed in config['selection_seeds']:
        order = np.random.default_rng(seed).permutation(len(ids)).tolist()
        selections += [dict(method='random', seed=seed, budget=b, indices=order[:min(b, len(ids))]) for b in config['budgets']]
    validate_suites(selections, len(ids), config)
    return selections, scores


def validate_suites(selected, pool_count, config):
    expected = {(m, s, b) for m in config['methods']
                for s in (config['selection_seeds'] if m == 'random' else [None]) for b in config['budgets']}
    keys = [(s['method'], s['seed'], s['budget']) for s in selected]
    if len(keys) != len(expected) or set(keys) != expected:
        raise ValueError('INCREMENT_MATRIX_INCOMPLETE')
    for s in selected:
        indices = s['indices']
        if len(indices) != min(s['budget'], pool_count) or len(set(indices)) != len(indices) or any(type(i) is not int or not 0 <= i < pool_count for i in indices):
            raise ValueError('INVALID_INCREMENT_SELECTION')


def screen(config, chains, cells, rankings):
    groups = {}
    policy = config['decision_policy']
    if len({c['chain_id'] for c in chains}) != len(chains) or any(c.get('role') == 'development' for c in chains):
        raise ValueError('INVALID_OR_DEVELOPMENT_SCREEN_CHAIN')
    tolerance = 1e-12  # Numerical equality at registered decimal boundaries.
    for architecture in config['architectures']:
        for family in config['families']:
            subset = [c for c in chains if c['architecture'] == architecture and c['family'] == family]
            rows = []
            for chain in subset:
                primary = {x['method']: x for x in cells if x['chain_id'] == chain['chain_id'] and x['budget'] == config['primary_budget'] and x['seed'] is None}
                ap = {x['method']: x['average_precision'] for x in rankings if x['chain_id'] == chain['chain_id']}
                valid = primary['margin-lr']['recall'] is not None
                rows.append(dict(chain_id=chain['chain_id'], future_flip_count=chain['future_flip_count'],
                                 recall_gain=primary['margin-history-lr']['recall'] - primary['margin-lr']['recall'] if valid else None,
                                 gain_over_raw_margin=primary['margin-history-lr']['recall'] - primary['ref-margin']['recall'] if valid else None,
                                 AP_gain=ap['margin-history-lr'] - ap['margin-lr'] if ap['margin-lr'] is not None else None))
            adequate = len(rows) == policy['chains_per_cell'] and all(r['future_flip_count'] >= policy['minimum_events_per_chain'] for r in rows)
            def mean(name):
                values = [r[name] for r in rows]
                return float(np.mean(values)) if values and all(x is not None for x in values) else None
            gain = mean('recall_gain')
            stable = (adequate and gain >= policy['minimum_mean_recall_gain'] - tolerance
                      and sum(r['recall_gain'] > 0 for r in rows) >= policy['minimum_positive_chains']
                      and all(r['recall_gain'] >= -policy['maximum_chain_loss'] - tolerance for r in rows)
                      and mean('gain_over_raw_margin') >= policy['minimum_mean_gain_over_raw_margin'] - tolerance
                      and mean('gain_over_raw_margin') > 0
                      and mean('AP_gain') > 0)
            groups[f'{architecture}/{family}'] = dict(chains=rows, adequate_events=adequate,
                mean_recall_gain=gain, mean_AP_gain=mean('AP_gain'), mean_gain_over_raw_margin=mean('gain_over_raw_margin'),
                stable_increment=bool(stable))
    replicated = [f for f in config['families'] if all(groups[f'{a}/{f}']['stable_increment'] for a in config['architectures'])]
    one_arch = any(g['stable_increment'] for g in groups.values())
    all_adequate = all(g['adequate_events'] for g in groups.values())
    recommendation = ('REPLICATED_INCREMENT_CANDIDATE' if replicated else
                      'CONDITIONAL_SIGNAL_REQUIRES_REPLICATION' if one_arch else
                      'NO_DETECTED_STABLE_INCREMENT' if all_adequate else 'INCONCLUSIVE_EVENT_SUPPORT')
    return dict(recommendation=recommendation, groups=groups, replicated_update_conditions=replicated,
                all_cells_adequate=all_adequate, hgc_archived=True, formal_test_model_inputs=0,
                automatic_further_search=False, statistical_superiority_established=False,
                academic_novelty_established=False, final_title_established=False)


def benchmark(bundle, architecture, texts, labels, expected, repeats):
    if type(repeats) is not int or repeats < 1:
        raise ValueError('POSITIVE_BENCHMARK_REPEATS_REQUIRED')
    expected = np.asarray(expected)
    if expected.shape != (len(texts),):
        raise ValueError('COST_BENCHMARK_SAMPLE_ALIGNMENT')
    times = []
    for _ in range(repeats):
        begin = time.perf_counter()
        normalized = [normalize_text(text) for text in texts]
        if texts:
            _, predicted = inference(bundle, architecture, normalized, labels)
        else:
            predicted = np.empty(0, dtype=str)
        times.append(time.perf_counter() - begin)
        if not np.array_equal(predicted, expected):
            raise ValueError('COST_BENCHMARK_PREDICTION_MISMATCH')
    return dict(wall_seconds=times, median_seconds=float(np.median(times)), sample_count=len(texts),
                repetitions=repeats, scope='text_normalize_encode_transform_and_predict_proba_argmax')


def validate_probe(config, probe):
    registration = json.loads((probe / 'registration.json').read_text())
    report = json.loads((probe / 'report.json').read_text())
    policy = config['resource_policy']
    if (registration['code_sha256'] != file_hash(ROOT / 'experiments/preflight/neural.py')
            or registration['dependency_lock_sha256'] != file_hash(ROOT / 'experiments/neural/uv.lock')
            or registration['config'] != config['neural']
            or registration['seed'] != policy['probe_seed']
            or registration['fraction'] != policy['probe_fraction']
            or registration['epochs'] != policy['probe_epochs']
            or registration['max_seconds'] != policy['probe_max_fit_seconds']
            or registration['max_rss_mib'] != policy['probe_max_rss_mib']
            or registration['dev_allowed'] is not False or registration['test_allowed'] is not False
            or report['registration_sha256'] != file_hash(probe / 'registration.json')
            or report['dev_examples_observed'] != 0 or report['test_examples_observed'] != 0
            or report['passed'] is not True):
        raise ValueError('NEURAL_RESOURCE_GATE_OR_PROVENANCE_FAILED')
    return report


def run(config_path, output):
    config = json.loads(config_path.read_text())
    validate_config(config)
    if file_hash(ROOT / 'experiments/preflight/hgc.py') != config['hgc_code_sha256']:
        raise ValueError('ARCHIVED_HGC_CHANGED')
    probe = ROOT / config['resource_probe_path']
    probe_report = validate_probe(config, probe)
    if output.exists():
        raise ValueError('NEW_RUN_DIRECTORY_REQUIRED')
    output.mkdir(parents=True)
    started = time.perf_counter()
    events = []
    def emit(kind, **details):
        value = dict(event=kind, time=utc(), details=details, previous_sha256=digest(events[-1]) if events else None)
        events.append(value)
        with (output / 'events.jsonl').open('a') as stream:
            stream.write(canonical(value).decode() + '\n')
            stream.flush()
        print(json.dumps(dict(event=kind, **details)), flush=True)
    prereg = dict(run_id=str(uuid4()), config=config, config_sha256=digest(config), registered_at=utc(),
        git_base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        working_tree_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
        code_files={str(p.relative_to(ROOT)): file_hash(p) for p in sorted((ROOT / 'experiments/preflight').glob('*.py'))},
        dependency_locks={name: file_hash(ROOT / name) for name in ['experiments/uv.lock', 'experiments/neural/uv.lock']},
        resource_probe_report_sha256=file_hash(probe / 'report.json'), chain_specifications=specifications(config))
    if prereg['working_tree_dirty']:
        raise ValueError('COMMIT_REGISTRATION_AND_CODE_BEFORE_TRAINING')
    write_json(output / 'preregistration.json', prereg)
    write_json(output / 'resource-probe.json', probe_report)
    write_json(output / 'resource-registration.json', json.loads((probe / 'registration.json').read_text()))
    emit('PREREGISTERED', config_sha256=digest(config))
    dataset = prepare(dict(datasets=['clinc'], clinc_cache=config['clinc_cache']))['clinc']
    train, dev, labels = dataset['train'], dataset['dev_selector'], dataset['manifest']['label_vocab']
    dev = [{k: r[k] for k in ('sample_id', 'text', 'gold_label')} for r in dev]
    write_json(output / 'data-audit.json', dataset['manifest'])
    write_json(output / 'dev.json', dev)
    write_json(output / 'data-role-contract.json', dict(
        current_role='EXPOSED_VAL_FOR_WHOLE_CHAIN_DEVELOPMENT_AND_NEW_UPDATE_VALIDATION',
        legacy_loader_protocol=dataset['manifest']['protocol'],
        legacy_loader_description_is_current_no_tuning_claim=False,
        development_unit='Whole registered model-update chain, not a random text split',
        samples_previously_exposed=True, formal_test_model_input_count=0,
        development_chain_ids=config['linear_development_chain_ids'] + [
            s['chain_id'] for s in specifications(config) if s['role'] == 'development'],
        heldout_chain_ids=[s['chain_id'] for s in specifications(config) if s['role'] == 'heldout']))
    write_json(output / 'train-id-contract.json', dict(ids_sha256=digest([r['sample_id'] for r in train]), rows=len(train), label_count=len(labels)))
    emit('DATA_AUDITED', train_count=len(train), dev_count=len(dev), formal_test_model_inputs=0)
    chains = []
    for spec in specifications(config):
        chains.append(train_chain(spec, train, labels, config, output / 'chains' / spec['chain_id'], emit))
        if time.perf_counter() - started > config['resource_policy']['max_total_seconds']:
            raise ValueError('TOTAL_RESOURCE_GATE_FAILED_NO_EXTRA_CHAINS')
    audit = identity_gate(chains, previous_nodes(config))
    write_json(output / 'identity-audit.json', audit)
    emit('GLOBAL_IDENTITY_GATE', passed=audit['passed'], current_node_count=64, previous_node_count=72)
    if not audit['passed']:
        raise ValueError('TARGET_IDENTITY_REUSED')
    records = dict(sgd=old_development(config, dev, labels), neural=[])
    development_summaries = []
    for chain in [c for c in chains if c['role'] == 'development']:
        directory = output / 'chains' / chain['chain_id']
        history, scores = histories(directory, chain['architecture'], dev, labels)
        feature, _ = features(dev, history, scores, labels)
        _, target = inference(load_bundle(directory, chain['architecture'], 3), chain['architecture'], [normalize_text(r['text']) for r in dev], labels)
        with (directory / 'development-observations.npz').open('xb') as stream:
            np.savez_compressed(stream, history=history, probabilities=scores, target=target, sample_ids=np.asarray([r['sample_id'] for r in dev]))
        pool = feature['pool_indices']
        events_dev = target[pool] != np.asarray([r['gold_label'] for r in dev])[pool]
        records['neural'].append(dict(chain_id=chain['chain_id'], margin_features=feature['margin_features'], combined_features=feature['combined_features'], events=events_dev))
        development_summaries.append(dict(chain_id=chain['chain_id'], pool_count=len(pool), future_flip_count=int(events_dev.sum())))
        emit('DEVELOPMENT_TARGET_EXPOSED', chain_id=chain['chain_id'], role='development', future_flip_count=int(events_dev.sum()))
    fitted, tuning = {}, {}
    for architecture in config['architectures']:
        fitted[architecture], tuning[architecture] = fit_development(records[architecture], c_grid=tuple(config['predictor']['C_grid']))
    with (output / 'predictors.pkl').open('xb') as stream:
        pickle.dump(fitted, stream, protocol=5)
    write_json(output / 'development-tuning.json', tuning)
    write_json(output / 'development-summaries.json', development_summaries)
    emit('PREDICTORS_FROZEN', development_chain_ids={a: [r['chain_id'] for r in records[a]] for a in records})
    heldout = [c for c in chains if c['role'] == 'heldout']
    for chain in heldout:
        directory = output / 'chains' / chain['chain_id']
        begin = time.perf_counter()
        history, scores = histories(directory, chain['architecture'], dev, labels)
        history_seconds = time.perf_counter() - begin
        begin = time.perf_counter()
        feature, groups = features(dev, history, scores, labels)
        feature_seconds = time.perf_counter() - begin
        pool = np.asarray(feature['pool_indices'], dtype=int)
        ids = [dev[i]['sample_id'] for i in pool]
        begin = time.perf_counter()
        selected, rankings = suites(fitted[chain['architecture']], feature, ids, config)
        selection_seconds = time.perf_counter() - begin
        with (directory / 'frozen-observations.npz').open('xb') as stream:
            np.savez_compressed(stream, history=history, probabilities=scores, sample_ids=np.asarray([r['sample_id'] for r in dev]),
                                pool_indices=pool, margin_features=feature['margin_features'], combined_features=feature['combined_features'],
                                **{'score_' + m: v for m, v in rankings.items()})
        write_json(directory / 'suites.json', dict(pool_ids=ids, pool_gold=[dev[i]['gold_label'] for i in pool], selections=selected))
        write_json(directory / 'history-costs.json', dict(history_seconds=history_seconds, feature_construction_seconds=feature_seconds,
                   all_suite_selection_seconds=selection_seconds, group_count=len(groups), cached_history=True,
                   history_setup_free=False, deployment_savings_established=False))
        chain.update(pool_count=len(pool), suite_count=len(selected), history_seconds=history_seconds,
                     reference_accuracy=len(pool) / len(dev))
        emit('HELDOUT_SUITES_READY', chain_id=chain['chain_id'], pool_count=len(pool), cell_count=len(selected))
    files = {str(p.relative_to(output)): file_hash(p) for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'events.jsonl'}
    write_json(output / 'matrix-freeze.json', dict(schema_version='history-increment-matrix-v1', files=files,
               config_sha256=digest(config), heldout_chain_ids=[c['chain_id'] for c in heldout],
               cell_count=sum(c['suite_count'] for c in heldout), target_predictions_generated=False))
    emit('ALL_HELDOUT_SUITES_FROZEN', chain_count=len(heldout), cell_count=sum(c['suite_count'] for c in heldout), freeze_sha256=file_hash(output / 'matrix-freeze.json'))
    verify_freeze(output)
    cells, rankings, costs = [], [], []
    gold = np.asarray([r['gold_label'] for r in dev])
    for chain in heldout:
        directory = output / 'chains' / chain['chain_id']
        saved = np.load(directory / 'frozen-observations.npz', allow_pickle=False)
        selected = json.loads((directory / 'suites.json').read_text())
        pool = saved['pool_indices']
        bundle = load_bundle(directory, chain['architecture'], 3)
        _, target = inference(bundle, chain['architecture'], [normalize_text(r['text']) for r in dev], labels)
        with (directory / 'target.npz').open('xb') as stream:
            np.savez_compressed(stream, predictions=target, sample_ids=np.asarray([r['sample_id'] for r in dev]))
        events_target = target[pool] != gold[pool]
        computed = evaluate_cells(selected['pool_gold'], saved['history'][pool], target[pool], selected['selections'])
        cells.extend(dict(**c, chain_id=chain['chain_id'], architecture=chain['architecture'], family=chain['family']) for c in computed)
        chain.update(future_flip_count=int(events_target.sum()), target_accuracy=float(np.mean(target == gold)))
        for method in ['margin-lr', 'margin-history-lr', 'ref-margin', 'risk-top']:
            score = saved['score_' + method]
            rankings.append(dict(chain_id=chain['chain_id'], method=method, **ranking_metrics(events_target, score),
                                 brier_score=float(np.mean((score - events_target) ** 2)) if method.endswith('-lr') and len(pool) else None))
        repeats = config['cost_policy']['target_benchmark_repeats']
        full = benchmark(bundle, chain['architecture'], [dev[i]['text'] for i in pool], labels, target[pool], repeats)
        for selection in selected['selections']:
            if selection['budget'] != config['primary_budget'] or selection['seed'] is not None:
                continue
            indices = pool[selection['indices']]
            measured = benchmark(bundle, chain['architecture'], [dev[i]['text'] for i in indices], labels, target[indices], repeats)
            costs.append(dict(chain_id=chain['chain_id'], method=selection['method'], full_pool=full, selected=measured,
                              infer_only_ratio=measured['median_seconds'] / full['median_seconds'] if len(pool) and full['median_seconds'] > 0 else None,
                              infer_only_ratio_na_reason=None if len(pool) and full['median_seconds'] > 0 else 'EMPTY_POOL_OR_ZERO_TIMER',
                              includes_selection_cost=False, deployment_savings_established=False))
        emit('HELDOUT_TARGET_EVALUATED', chain_id=chain['chain_id'], future_flip_count=int(events_target.sum()))
    decision = screen(config, heldout, cells, rankings)
    write_json(output / 'evaluation-cells.json', cells)
    write_json(output / 'ranking-metrics.json', rankings)
    write_json(output / 'target-costs.json', costs)
    report = dict(schema_version='history-increment-report-v1', run_id=prereg['run_id'],
                  config_sha256=digest(config), freeze_sha256=file_hash(output / 'matrix-freeze.json'),
                  git_base_commit=prereg['git_base_commit'], chains=heldout, development_chains=development_summaries,
                  total_model_fits=sum(len(c['versions']) for c in chains), heldout_chain_count=len(heldout),
                  evaluation_cell_count=len(cells), ranking_row_count=len(rankings), cost_row_count=len(costs),
                  formal_test_model_input_count=0, decision=decision,
                  elapsed_seconds=time.perf_counter() - started, peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                  environment=dict(python=platform.python_version(), numpy=np.__version__, threads=2, neural_device='cpu'),
                  hgc_code_sha256=config['hgc_code_sha256'], existing_VAL_texts_exposed=True,
                  limitation='Small matched update realizations, one dataset and one neural architecture; no significance, novelty, final title or general null established.')
    write_json(output / 'report.json', report)
    emit('COMPLETED', recommendation=decision['recommendation'])
    verify_freeze(output)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with threadpool_limits(2):
        report = run(args.config.resolve(), args.output.resolve())
    print(json.dumps(report['decision'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
