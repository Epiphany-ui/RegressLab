"""Audit a trusted local history-increment run after its global target freeze.

This checks cached data against pinned official sources, actual stored model
states and replayed inference. It refits only the small *development* predictors
with the registered procedure; no task model is trained and no selector changes.
Do not apply it to untrusted pickle uploads. Internal hashes/events are not an
external proof that an operator never inspected a target outside this workflow.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import re
import subprocess

import numpy as np
from sklearn.linear_model import SGDClassifier
from threadpoolctl import threadpool_limits

from .clinc import COMMIT, DATA_SHA256, DATA_URL, LICENSE_SHA256, LICENSE_URL, audit_clinc
from .data import normalize_text
from .diagnostics import ranking_metrics
from .hgc import DEFAULT_HGC_CONFIG
from .incremental import fit_development, model_metadata
from .incremental_run import (features, identity_gate, inference, load_bundle,
                              old_development, previous_nodes, screen, validate_config,
                              specifications, suites, training_indices)
from .linear_state import linear_identity
from .neural import DEFAULT_NEURAL_CONFIG, build_vocabulary, load_neural, neural_identity
from .runner import ROOT, digest, evaluate_cells, nested_train_indices, vectorizer
from .verify import file_sha, indexed, integer_values, read_json, require
from .verify2 import local_file, nonnegative

METHODS = {'ref-margin', 'margin-lr', 'margin-history-lr', 'risk-top', 'random'}
RANK_METHODS = ['margin-lr', 'margin-history-lr', 'ref-margin', 'risk-top']


def expected_matrix(config):
    """Reconstruct the exact fixed matrix; never trust manifest self-enumeration."""
    validate_config(config)
    require(config['schema_version'] == 'regresslab-history-increment-v1' and config['purpose'] == 'FROZEN_HISTORY_INCREMENT_CHECK', 'CONFIG_SCOPE_MISMATCH')
    require(config['dataset'] == 'clinc150' and config['hgc_archived'] is True and config['historical_group_config'] == DEFAULT_HGC_CONFIG and config['neural'] == DEFAULT_NEURAL_CONFIG, 'FIXED_MODEL_OR_HISTORY_CONTRACT_MISMATCH')
    require(config['architectures'] == ['sgd', 'neural'] and config['families'] == ['data-growth', 'data-refresh'], 'ARCHITECTURE_OR_FAMILY_MATRIX_MISMATCH')
    require(config['heldout_seeds'] == [1103, 1109, 1117] and config['neural_development_seeds'] == [901, 907], 'REGISTERED_TRAINING_SEEDS_MISMATCH')
    for key, lower in [('selection_seeds', 0), ('budgets', 1)]:
        integer_values(config[key], lower, 'INVALID_' + key.upper())
    require(config['selection_seeds'] == list(range(20)) and config['budgets'] == [20, 50, 100, 200] and config['primary_budget'] == 100, 'REGISTERED_BUDGET_OR_SELECTION_SEEDS_MISMATCH')
    require(type(config['methods']) is list and len(config['methods']) == len(METHODS) and set(config['methods']) == METHODS, 'REGISTERED_METHOD_SET_MISMATCH')
    require(config['basis_fraction'] == .4 and config['growth_fractions'] == [.4, .6, .8, 1.] and config['linear_epochs'] == 20 and config['neural_epochs'] == 12, 'FIXED_TRAINING_RECIPE_MISMATCH')
    require(config['predictor']['C_grid'] == [.01, .1, 1., 10.] and config['predictor']['feature_search'] is False, 'PREDICTOR_SEARCH_CONTRACT_MISMATCH')
    require(config['formal_test_model_input_count'] == 0, 'FORMAL_TEST_ACCESS_NOT_ZERO')
    specs = specifications(config)
    keys = {(method, seed, budget) for method in config['methods']
            for seed in (config['selection_seeds'] if method == 'random' else [None])
            for budget in config['budgets']}
    files = {'preregistration.json', 'resource-probe.json', 'resource-registration.json',
             'data-audit.json', 'dev.json', 'data-role-contract.json', 'train-id-contract.json',
             'identity-audit.json', 'predictors.pkl', 'development-tuning.json', 'development-summaries.json'}
    for spec in specs:
        prefix = 'chains/' + spec['chain_id'] + '/'
        extension = 'pt' if spec['architecture'] == 'neural' else 'pkl'
        names = ['training.json', *[f'f{s}.{extension}' for s in range(4)]]
        names += ['development-observations.npz'] if spec['role'] == 'development' else ['frozen-observations.npz', 'suites.json', 'history-costs.json']
        files.update(prefix + name for name in names)
    require(len(specs) == 16 and len(keys) == 96, 'EXPECTED_MATRIX_SIZE_MISMATCH')
    return specs, keys, files


def close(actual, expected, code, *, atol=1e-11):
    """Recursively compare replayed numerical records without hiding missing keys."""
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and set(actual) == set(expected), code)
        for key in expected:
            close(actual[key], expected[key], code, atol=atol)
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected), code)
        for left, right in zip(actual, expected):
            close(left, right, code, atol=atol)
    elif isinstance(expected, float):
        require(type(actual) in (int, float) and np.isfinite(actual) and np.isclose(actual, expected, atol=atol, rtol=atol), code)
    else:
        require(actual == expected, code)


def check_source(output, config, specs):
    audit = read_json(local_file(output, 'data-audit.json'))
    source = audit['source']
    require(source['source_commit'] == COMMIT and source['data_sha256'] == DATA_SHA256 and source['license_sha256'] == LICENSE_SHA256 and source['source_url'] == DATA_URL and source['license_url'] == LICENSE_URL and source['license'] == 'CC-BY-3.0', 'CLINC_PINNED_SOURCE_MISMATCH')
    relative = Path(config['clinc_cache'])
    require(not relative.is_absolute() and '..' not in relative.parts, 'UNSAFE_SOURCE_CACHE_PATH')
    cache = ROOT / relative
    require(file_sha(local_file(cache, 'data_full.json')) == DATA_SHA256 and file_sha(local_file(cache, 'LICENSE')) == LICENSE_SHA256, 'CLINC_SOURCE_CACHE_CHANGED')
    prepared = audit_clinc(read_json(local_file(cache, 'data_full.json')), source=source)
    require(prepared['manifest'] == audit and audit['test_samples_returned'] == audit['oos_samples_returned'] == 0, 'OFFICIAL_SOURCE_REAUDIT_MISMATCH')
    dev = [{k: row[k] for k in ('sample_id', 'text', 'gold_label')} for row in prepared['dev_selector']]
    require(read_json(local_file(output, 'dev.json')) == dev, 'FROZEN_DEV_SOURCE_MISMATCH')
    train, labels = prepared['train'], audit['label_vocab']
    require(read_json(local_file(output, 'train-id-contract.json')) == dict(ids_sha256=digest([r['sample_id'] for r in train]), rows=len(train), label_count=len(labels)), 'TRAIN_ID_SOURCE_CONTRACT_MISMATCH')
    role = read_json(local_file(output, 'data-role-contract.json'))
    require(role == dict(current_role='EXPOSED_VAL_FOR_WHOLE_CHAIN_DEVELOPMENT_AND_NEW_UPDATE_VALIDATION', legacy_loader_protocol=audit['protocol'], legacy_loader_description_is_current_no_tuning_claim=False,
                        development_unit='Whole registered model-update chain, not a random text split', samples_previously_exposed=True, formal_test_model_input_count=0,
                        development_chain_ids=config['linear_development_chain_ids'] + [s['chain_id'] for s in specs if s['role'] == 'development'],
                        heldout_chain_ids=[s['chain_id'] for s in specs if s['role'] == 'heldout']), 'DATA_ROLE_CONTRACT_MISMATCH')
    return train, dev, labels


def check_resource(output, config, train, prereg):
    reg = read_json(local_file(output, 'resource-registration.json'))
    report = read_json(local_file(output, 'resource-probe.json'))
    policy = config['resource_policy']
    relative = Path(config['resource_probe_path'])
    require(not relative.is_absolute() and '..' not in relative.parts, 'UNSAFE_RESOURCE_PROBE_PATH')
    probe = ROOT / relative
    require(report == read_json(local_file(probe, 'report.json')) and reg == read_json(local_file(probe, 'registration.json')), 'RESOURCE_PROBE_SOURCE_COPY_MISMATCH')
    require(prereg['resource_probe_report_sha256'] == file_sha(probe/'report.json') and report['registration_sha256'] == file_sha(probe/'registration.json'), 'RESOURCE_PROBE_HASH_MISMATCH')
    selected = [train[i] for i in nested_train_indices(train, policy['probe_fraction'], policy['probe_seed'])]
    require(reg['config'] == config['neural'] and reg['seed'] == policy['probe_seed'] and reg['fraction'] == policy['probe_fraction'] and reg['epochs'] == policy['probe_epochs'] and reg['max_seconds'] == policy['probe_max_fit_seconds'] and reg['max_rss_mib'] == policy['probe_max_rss_mib'], 'RESOURCE_PROBE_RECIPE_MISMATCH')
    require(reg['train_rows'] == len(train) and reg['probe_rows'] == len(selected) <= 2000 and reg['probe_train_ids_sha256'] == digest([r['sample_id'] for r in selected]) and reg['dev_allowed'] is reg['test_allowed'] is False, 'RESOURCE_PROBE_TRAIN_SCOPE_MISMATCH')
    require(reg['code_sha256'] == prereg['code_files']['experiments/preflight/neural.py'] and reg['dependency_lock_sha256'] == prereg['dependency_locks']['experiments/neural/uv.lock'], 'RESOURCE_PROBE_CODE_OR_LOCK_MISMATCH')
    model = load_neural(local_file(probe, 'probe.pt'))
    require(neural_identity(model) == report['identity'] and model['training_summary'] == report['summary'] and model['vocabulary'] == build_vocabulary(selected, config['neural']), 'RESOURCE_MODEL_STATE_MISMATCH')
    require(report['device'] == 'cpu' and report['threads'] == 2 and report['passed'] is report['restore_exact'] is report['fit_seconds_within_limit'] is report['rss_within_limit'] is True, 'RESOURCE_GATE_NOT_PASSED')
    require(report['dev_examples_observed'] == report['test_examples_observed'] == 0 and report['inference_probe_partition'] == 'TRAIN' and report['inference_probe_examples'] == min(32, len(selected)), 'RESOURCE_PROBE_INFERENCE_SCOPE_MISMATCH')
    require(nonnegative(report['peak_process_rss_mib']) <= policy['probe_max_rss_mib'] and nonnegative(report['summary']['train_seconds']) <= policy['probe_max_fit_seconds'], 'RESOURCE_LIMIT_EXCEEDED')


def check_training(output, spec, train, labels, config):
    directory = output / 'chains' / spec['chain_id']
    training = read_json(local_file(directory, 'training.json'))
    require(all(training.get(k) == v for k, v in spec.items()) and [v['slot'] for v in training['versions']] == ['f0', 'f1', 'f2', 'f3'], 'TRAINING_SPEC_OR_VERSION_SET_MISMATCH')
    nonnegative(training['basis_seconds'])
    base = nested_train_indices(train, config['basis_fraction'], spec['seed'])
    basis_rows = [train[i] for i in base]
    if spec['architecture'] == 'sgd':
        representation = vectorizer(config['classifier_representation']).fit([normalize_text(r['text']) for r in basis_rows])
    else:
        vocabulary = build_vocabulary(basis_rows, config['neural'])
    bundles = []
    for slot, version in enumerate(training['versions']):
        extension = 'pt' if spec['architecture'] == 'neural' else 'pkl'
        require(file_sha(local_file(directory, f'f{slot}.{extension}')) == version['model_file_sha256'], 'MODEL_FILE_HASH_MISMATCH')
        bundle = load_bundle(directory, spec['architecture'], slot)
        chosen = training_indices(train, spec['family'], slot, spec['seed'])
        require(version['train_rows'] == len(chosen) and version['train_ids_sha256'] == digest([train[i]['sample_id'] for i in chosen]) and version['basis_train_ids_sha256'] == digest([r['sample_id'] for r in basis_rows]), 'TRAINING_IDS_NOT_REGISTERED_TRAIN_RECIPE')
        epochs = config['neural_epochs'] if spec['architecture'] == 'neural' else config['linear_epochs']
        require(version['epochs'] == epochs and version['restore_exact'] is True and version['restore_inference_scope'] == 'TRAIN_ONLY_UP_TO_32_ROWS' and nonnegative(version['train_seconds']) <= config['resource_policy']['max_fit_seconds'], 'TRAINING_RESOURCE_OR_RESTORE_MISMATCH')
        if spec['architecture'] == 'sgd':
            model = bundle['classifier']
            require(type(model) is SGDClassifier and model.classes_.tolist() == labels and model.n_iter_ == epochs and model.max_iter == epochs and model.random_state == spec['seed'], 'LINEAR_FITTED_CONTRACT_MISMATCH')
            require(all(model.get_params()[k] == v for k, v in config['linear_classifier'].items()), 'LINEAR_CLASSIFIER_CONFIG_MISMATCH')
            require(all(bundle['vectorizer'].get_params()[k] == (tuple(v) if k == 'ngram_range' else v) for k, v in config['classifier_representation'].items() if k != 'fit_on'), 'LINEAR_REPRESENTATION_CONFIG_MISMATCH')
            identity = linear_identity(bundle['vectorizer'], model)
            require(identity == linear_identity(representation, model), 'FIXED_TRAIN_ONLY_BASIS_MISMATCH')
            parameters = int(model.coef_.size + model.intercept_.size)
        else:
            summary = bundle['training_summary']
            require(bundle['config'] == config['neural'] and bundle['labels'] == labels and bundle['vocabulary'] == vocabulary, 'NEURAL_BASIS_OR_CONFIG_MISMATCH')
            require(summary['seed'] == spec['seed'] and summary['epochs'] == epochs and summary['rows'] == len(chosen) and summary['train_ids_sha256'] == version['train_ids_sha256'] and summary['fixed_epoch_budget_completed'] is True and summary['dev_examples_observed'] == summary['test_examples_observed'] == 0, 'NEURAL_TRAINING_CONTRACT_MISMATCH')
            require(len(summary['epoch_train_cross_entropy']) == epochs and all(np.isfinite(v) and v >= 0 for v in summary['epoch_train_cross_entropy']), 'INVALID_NEURAL_TRAINING_LOSS')
            parameters = sum(tensor.numel() for tensor in bundle['state_dict'].values())
            require(parameters == summary['parameter_count'], 'NEURAL_PARAMETER_COUNT_MISMATCH')
            identity = neural_identity(bundle)
        require(identity == version['identity'] and parameters == version['parameter_count'], 'STORED_MODEL_IDENTITY_MISMATCH')
        bundles.append(bundle)
    return training, bundles


def observed(path, ids, labels, *, development):
    with np.load(path, allow_pickle=False) as data:
        saved = {key: data[key] for key in data.files}
    expected = {'history', 'probabilities', 'sample_ids', 'target'} if development else {'history', 'probabilities', 'sample_ids', 'pool_indices', 'margin_features', 'combined_features', *['score_' + m for m in RANK_METHODS]}
    require(set(saved) == expected and saved['sample_ids'].tolist() == ids, 'OBSERVATION_FIELDS_OR_SAMPLE_ALIGNMENT_MISMATCH')
    history, scores = saved['history'], saved['probabilities']
    require(history.shape == (len(ids), 3) and history.dtype.kind == 'U' and set(history.flat) <= set(labels), 'HISTORY_ARRAY_SHAPE_OR_LABEL_MISMATCH')
    require(scores.shape == (len(ids), 3, len(labels)) and np.isfinite(scores).all() and np.all((scores >= 0) & (scores <= 1)) and np.allclose(scores.sum(axis=2), 1, rtol=0, atol=1e-8), 'HISTORY_PROBABILITY_CONTRACT_MISMATCH')
    require(np.array_equal(np.asarray(labels)[scores.argmax(axis=2)], history), 'HISTORY_PROBABILITY_LABEL_MISMATCH')
    if development:
        require(saved['target'].shape == (len(ids),) and saved['target'].dtype.kind == 'U' and set(saved['target'].tolist()) <= set(labels), 'DEVELOPMENT_TARGET_ARRAY_MISMATCH')
    return saved


def check_benchmark(block, count, repeats):
    require(set(block) == {'wall_seconds', 'median_seconds', 'sample_count', 'repetitions', 'scope'}, 'COST_BENCHMARK_FIELDS_MISMATCH')
    require(block['sample_count'] == count and block['repetitions'] == repeats and len(block['wall_seconds']) == repeats, 'COST_BENCHMARK_SCOPE_MISMATCH')
    require(block['scope'] == 'text_normalize_encode_transform_and_predict_proba_argmax', 'COST_BENCHMARK_INFERENCE_SCOPE_MISMATCH')
    for value in block['wall_seconds']:
        nonnegative(value)
    require(block['median_seconds'] == float(np.median(block['wall_seconds'])), 'COST_BENCHMARK_MEDIAN_MISMATCH')
    return nonnegative(block['median_seconds'])


def check_events(output, prereg, chains, report, cell_count):
    events = [read_json_line(line) for line in local_file(output, 'events.jsonl').read_text().splitlines()]
    specs = prereg['chain_specifications']
    dev = {s['chain_id'] for s in specs if s['role'] == 'development'}
    heldout = {s['chain_id'] for s in specs if s['role'] == 'heldout'}
    expected = {'PREREGISTERED': 1, 'DATA_AUDITED': 1, 'MODEL_TRAINED': 4*len(specs), 'GLOBAL_IDENTITY_GATE': 1,
                'DEVELOPMENT_TARGET_EXPOSED': len(dev), 'PREDICTORS_FROZEN': 1, 'HELDOUT_SUITES_READY': len(heldout),
                'ALL_HELDOUT_SUITES_FROZEN': 1, 'HELDOUT_TARGET_EVALUATED': len(heldout), 'COMPLETED': 1}
    require(Counter(e['event'] for e in events) == expected, 'EVENT_SET_MISMATCH')
    require(events[0]['event'] == 'PREREGISTERED' and events[-1]['event'] == 'COMPLETED', 'EVENT_BOUNDARY_MISMATCH')
    for index, event in enumerate(events):
        require(set(event) == {'event', 'time', 'details', 'previous_sha256'} and event['previous_sha256'] == (digest(events[index-1]) if index else None), 'EVENT_HASH_CHAIN_MISMATCH')
        now = datetime.fromisoformat(event['time'])
        require(now.tzinfo is not None and (not index or now >= datetime.fromisoformat(events[index-1]['time'])), 'EVENT_TIME_ORDER_MISMATCH')
    positions = {kind: next(i for i, e in enumerate(events) if e['event'] == kind) for kind in ['DATA_AUDITED', 'GLOBAL_IDENTITY_GATE', 'PREDICTORS_FROZEN', 'ALL_HELDOUT_SUITES_FROZEN']}
    data, gate, fitted, frozen = [positions[k] for k in positions]
    require(0 < data < gate < fitted < frozen < len(events)-1, 'EVENT_GLOBAL_PHASE_ORDER_MISMATCH')
    require(events[0]['details'] == dict(config_sha256=prereg['config_sha256']), 'PREREGISTER_EVENT_MISMATCH')
    if (output/'train-id-contract.json').is_file() and (output/'dev.json').is_file():
        require(events[data]['details'] == dict(train_count=read_json(output/'train-id-contract.json')['rows'], dev_count=len(read_json(output/'dev.json')), formal_test_model_inputs=0), 'DATA_EVENT_COUNTS_OR_TEST_SCOPE_MISMATCH')
    require(events[gate]['details'] == dict(passed=True, current_node_count=4*len(specs), previous_node_count=72), 'IDENTITY_GATE_EVENT_MISMATCH')
    require(events[frozen]['details'] == dict(chain_count=len(heldout), cell_count=cell_count, freeze_sha256=file_sha(output/'matrix-freeze.json')), 'FREEZE_EVENT_MISMATCH')
    by_id = {s['chain_id']: s for s in chains}
    seen = {k: set() for k in ['MODEL_TRAINED', 'DEVELOPMENT_TARGET_EXPOSED', 'HELDOUT_SUITES_READY', 'HELDOUT_TARGET_EVALUATED']}
    for index, event in enumerate(events):
        kind, detail = event['event'], event['details']
        if kind not in seen:
            continue
        require(detail['chain_id'] in by_id, 'UNKNOWN_EVENT_CHAIN')
        chain = by_id[detail['chain_id']]
        key = (detail['chain_id'], detail['slot']) if kind == 'MODEL_TRAINED' else detail['chain_id']
        require(key not in seen[kind], 'DUPLICATE_STAGE_EVENT')
        seen[kind].add(key)
        if kind == 'MODEL_TRAINED':
            require(data < index < gate and detail['role'] == chain['role'] and detail['slot'] in {'f0', 'f1', 'f2', 'f3'} and detail['dev_predicted'] is False and detail['restore_inference_scope'] == 'TRAIN_ONLY_UP_TO_32_ROWS', 'MODEL_EVENT_SCOPE_OR_PHASE_MISMATCH')
            version = next(v for v in chain['versions'] if v['slot'] == detail['slot'])
            require(detail['seconds'] == version['train_seconds'], 'MODEL_TIME_EVENT_MISMATCH')
        elif kind == 'DEVELOPMENT_TARGET_EXPOSED':
            require(gate < index < fitted and detail['chain_id'] in dev and detail['role'] == 'development' and detail['future_flip_count'] == chain['future_flip_count'], 'DEVELOPMENT_TARGET_EVENT_SCOPE_MISMATCH')
        elif kind == 'HELDOUT_SUITES_READY':
            require(fitted < index < frozen and detail['chain_id'] in heldout and detail['pool_count'] == chain['pool_count'] and detail['cell_count'] == chain['suite_count'], 'HELDOUT_SUITE_EVENT_SCOPE_MISMATCH')
        else:
            require(index > frozen and detail['chain_id'] in heldout and detail['future_flip_count'] == chain['future_flip_count'], 'HELDOUT_TARGET_BEFORE_GLOBAL_FREEZE')
    require(seen['MODEL_TRAINED'] == {(s['chain_id'], f'f{k}') for s in specs for k in range(4)} and seen['DEVELOPMENT_TARGET_EXPOSED'] == dev and seen['HELDOUT_SUITES_READY'] == seen['HELDOUT_TARGET_EVALUATED'] == heldout, 'EVENT_COMPLETE_CHAIN_MATRIX_MISMATCH')
    require(events[fitted]['details'] == dict(development_chain_ids={'sgd': prereg['config']['linear_development_chain_ids'], 'neural': [s['chain_id'] for s in specs if s['role'] == 'development']}), 'PREDICTOR_SOURCE_EVENT_MISMATCH')
    require(events[-1]['details'] == dict(recommendation=report['decision']['recommendation']), 'COMPLETE_EVENT_DECISION_MISMATCH')
    return len(events)


def read_json_line(line):
    def unique(pairs):
        require(len(dict(pairs)) == len(pairs), 'DUPLICATE_EVENT_JSON_KEY')
        return dict(pairs)
    return json.loads(line, object_pairs_hook=unique)


def verify(output):
    output = Path(output).resolve()
    frozen = read_json(local_file(output, 'matrix-freeze.json'))
    require(frozen['schema_version'] == 'history-increment-matrix-v1' and frozen['target_predictions_generated'] is False, 'FREEZE_SCOPE_MISMATCH')
    for relative, expected in frozen['files'].items():
        require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected) and file_sha(local_file(output, relative)) == expected, 'FROZEN_INPUT_CHANGED')
    prereg = read_json(local_file(output, 'preregistration.json'))
    config = prereg['config']
    specs, keys, expected_files = expected_matrix(config)
    require(set(frozen['files']) == expected_files, 'FROZEN_FILE_SET_MISMATCH')
    held_specs = [s for s in specs if s['role'] == 'heldout']
    require(prereg['chain_specifications'] == specs and prereg['working_tree_dirty'] is False, 'PREREGISTRATION_CHAIN_OR_CLEAN_COMMIT_MISMATCH')
    require(frozen['heldout_chain_ids'] == [s['chain_id'] for s in held_specs] and frozen['cell_count'] == len(keys)*len(held_specs), 'FROZEN_MATRIX_MISMATCH')
    require(prereg['config_sha256'] == frozen['config_sha256'] == digest(config), 'CONFIG_HASH_MISMATCH')
    require(re.fullmatch('[0-9a-f]{40}', prereg['git_base_commit']), 'INVALID_REGISTERED_COMMIT')
    require(set(prereg['code_files']) == {str(p.relative_to(ROOT)) for p in (ROOT/'experiments/preflight').glob('*.py')}, 'REGISTERED_CODE_FILE_SET_MISMATCH')
    committed_config = subprocess.check_output(['git', 'show', prereg['git_base_commit'] + ':experiments/configs/history-increment-v1.json'], cwd=ROOT)
    require(json.loads(committed_config) == config, 'CONFIG_NOT_REGISTERED_COMMIT_CONTENT')
    for relative, expected in prereg['code_files'].items():
        require(file_sha(local_file(ROOT, relative)) == expected, 'EXECUTED_CODE_CHANGED')
        committed = subprocess.check_output(['git', 'show', prereg['git_base_commit'] + ':' + relative], cwd=ROOT)
        require(hashlib.sha256(committed).hexdigest() == expected, 'CODE_NOT_REGISTERED_COMMIT_CONTENT')
    for relative, expected in prereg['dependency_locks'].items():
        require(file_sha(local_file(ROOT, relative)) == expected, 'EXECUTED_DEPENDENCY_LOCK_CHANGED')
    require(config['hgc_code_sha256'] == prereg['code_files']['experiments/preflight/hgc.py'], 'ARCHIVED_HGC_CODE_CHANGED')
    train, dev, labels = check_source(output, config, specs)
    check_resource(output, config, train, prereg)
    ids = [r['sample_id'] for r in dev]
    texts = [normalize_text(r['text']) for r in dev]
    gold = np.asarray([r['gold_label'] for r in dev])
    report = read_json(local_file(output, 'report.json'))
    require(report['schema_version'] == 'history-increment-report-v1' and report['run_id'] == prereg['run_id'] and report['config_sha256'] == digest(config) and report['git_base_commit'] == prereg['git_base_commit'] and report['freeze_sha256'] == file_sha(output/'matrix-freeze.json'), 'REPORT_IDENTITY_OR_FREEZE_MISMATCH')
    require(report['formal_test_model_input_count'] == 0 and report['existing_VAL_texts_exposed'] is True and report['hgc_code_sha256'] == config['hgc_code_sha256'], 'REPORT_SCOPE_MISMATCH')
    require(report['environment']['threads'] == 2 and report['environment']['neural_device'] == 'cpu', 'REPORT_DEVICE_MISMATCH')
    reported = indexed(report['chains'], ['chain_id'], 'DUPLICATE_REPORT_CHAIN')
    require(set(reported) == {(s['chain_id'],) for s in held_specs}, 'REPORT_HELDOUT_CHAIN_SET_MISMATCH')
    chain_states, bundles, observations, computed_features = {}, {}, {}, {}
    records = {'sgd': old_development(config, dev, labels), 'neural': []}
    development = []
    for spec in specs:
        chain_id = spec['chain_id']
        training, models = check_training(output, spec, train, labels, config)
        chain_states[chain_id] = training
        directory = output/'chains'/chain_id
        saved = observed(local_file(directory, 'development-observations.npz' if spec['role'] == 'development' else 'frozen-observations.npz'), ids, labels, development=spec['role'] == 'development')
        for slot in range(3):
            actual_scores, predicted = inference(models[slot], spec['architecture'], texts, labels)
            require(np.array_equal(predicted, saved['history'][:, slot]) and np.array_equal(actual_scores, saved['probabilities'][:, slot]), 'HISTORY_CACHE_NOT_ACTUAL_STORED_MODEL_OUTPUT')
        feature, groups = features(dev, saved['history'], saved['probabilities'], labels)
        computed_features[chain_id] = (feature, groups)
        observations[chain_id] = saved
        if spec['role'] == 'development':
            _, target = inference(models[3], spec['architecture'], texts, labels)
            require(np.array_equal(target, saved['target']), 'DEVELOPMENT_TARGET_NOT_STORED_MODEL_OUTPUT')
            pool = feature['pool_indices']
            events = target[pool] != gold[pool]
            records['neural'].append(dict(chain_id=chain_id, margin_features=feature['margin_features'], combined_features=feature['combined_features'], events=events))
            summary = dict(chain_id=chain_id, pool_count=len(pool), future_flip_count=int(events.sum()))
            development.append(summary)
            training.update(summary)
        else:
            bundles[chain_id] = models[3]
    # Old targets were exposed previously; validate their labels against stored
    # states too, because their post-freeze cache files train the new predictors.
    old_root = ROOT/config['prior_runs'][-1]['path']
    for chain_id in config['linear_development_chain_ids']:
        with np.load(local_file(old_root, f'chains/{chain_id}/f3-target.npz'), allow_pickle=False) as saved:
            old_target = saved['predictions']
        _, actual = inference(load_bundle(old_root/'chains'/chain_id, 'sgd', 3), 'sgd', texts, labels)
        require(np.array_equal(old_target, actual), 'EXPOSED_DEVELOPMENT_TARGET_CACHE_MISMATCH')
    previous = previous_nodes(config)
    audit = identity_gate(list(chain_states.values()), previous)
    require(audit['passed'] and audit == read_json(local_file(output, 'identity-audit.json')), 'GLOBAL_MODEL_IDENTITY_AUDIT_MISMATCH')
    require(development == read_json(local_file(output, 'development-summaries.json')) == report['development_chains'], 'DEVELOPMENT_CHAIN_SUMMARY_MISMATCH')
    with local_file(output, 'predictors.pkl').open('rb') as stream:
        fitted = pickle.load(stream)  # TRUSTED HASH-VERIFIED LOCAL RUN ONLY.
    tuning = read_json(local_file(output, 'development-tuning.json'))
    require(set(fitted) == set(tuning) == set(config['architectures']), 'PREDICTOR_ARCHITECTURE_SET_MISMATCH')
    for architecture in config['architectures']:
        recomputed, provenance = fit_development(records[architecture], c_grid=tuple(config['predictor']['C_grid']))
        close(tuning[architecture], provenance, 'DEVELOPMENT_FIT_OR_FOLD_REPLAY_MISMATCH')
        require(set(fitted[architecture]) == {'margin-lr', 'margin-history-lr'}, 'PREDICTOR_METHOD_SET_MISMATCH')
        for method in fitted[architecture]:
            close(model_metadata(fitted[architecture][method]), model_metadata(recomputed[method]), 'PREDICTOR_STORED_STATE_MISMATCH')
    all_cells, all_rankings = [], []
    for spec in held_specs:
        chain_id = spec['chain_id']
        directory = output/'chains'/chain_id
        saved = observations[chain_id]
        feature, groups = computed_features[chain_id]
        pool = np.asarray(feature['pool_indices'], dtype=int)
        require(saved['pool_indices'].dtype.kind in 'iu' and np.array_equal(saved['pool_indices'], pool) and np.array_equal(saved['margin_features'], feature['margin_features']) and np.array_equal(saved['combined_features'], feature['combined_features']), 'FROZEN_POOL_OR_HISTORY_FEATURE_REPLAY_MISMATCH')
        expected_suites, scores = suites(fitted[spec['architecture']], feature, [ids[i] for i in pool], config)
        selection = read_json(local_file(directory, 'suites.json'))
        require(selection == dict(pool_ids=[ids[i] for i in pool], pool_gold=gold[pool].tolist(), selections=expected_suites), 'FROZEN_SELECTION_REPLAY_MISMATCH')
        for method, score in scores.items():
            require(np.array_equal(saved['score_'+method], score), 'FROZEN_RANKING_SCORE_REPLAY_MISMATCH')
        with np.load(local_file(directory, 'target.npz'), allow_pickle=False) as target_data:
            require(set(target_data.files) == {'predictions', 'sample_ids'} and target_data['sample_ids'].tolist() == ids, 'HELDOUT_TARGET_FIELDS_OR_IDS_MISMATCH')
            target = target_data['predictions']
        require(target.shape == gold.shape and target.dtype.kind == 'U' and set(target.tolist()) <= set(labels), 'HELDOUT_TARGET_LABEL_CONTRACT_MISMATCH')
        _, actual_target = inference(bundles[chain_id], spec['architecture'], texts, labels)
        require(np.array_equal(target, actual_target), 'HELDOUT_TARGET_CACHE_NOT_ACTUAL_MODEL_OUTPUT')
        events = target[pool] != gold[pool]
        computed = evaluate_cells(selection['pool_gold'], saved['history'][pool], target[pool], expected_suites)
        all_cells.extend(dict(**row, chain_id=chain_id, architecture=spec['architecture'], family=spec['family']) for row in computed)
        for method in RANK_METHODS:
            score = scores[method]
            all_rankings.append(dict(chain_id=chain_id, method=method, **ranking_metrics(events, score), brier_score=float(np.mean((score-events)**2)) if method.endswith('-lr') and len(pool) else None))
        state = chain_states[chain_id]
        chain = reported[(chain_id,)]
        require(all(chain.get(k) == v for k, v in state.items()), 'REPORT_TRAINING_STATE_MISMATCH')
        expected = dict(pool_count=len(pool), suite_count=len(keys), reference_accuracy=len(pool)/len(dev), future_flip_count=int(events.sum()), target_accuracy=float(np.mean(target == gold)))
        require(all(chain.get(k) == v for k, v in expected.items()), 'REPORT_CHAIN_METRIC_MISMATCH')
        costs = read_json(local_file(directory, 'history-costs.json'))
        require(costs['cached_history'] is True and costs['history_setup_free'] is costs['deployment_savings_established'] is False and costs['group_count'] == len(groups) and costs['history_seconds'] == chain['history_seconds'], 'HISTORY_COST_SCOPE_MISMATCH')
        for key in ['history_seconds', 'feature_construction_seconds', 'all_suite_selection_seconds']:
            nonnegative(costs[key])
        state.update(expected, history_seconds=chain['history_seconds'])
    require(all_cells == read_json(local_file(output, 'evaluation-cells.json')), 'EVALUATION_CELLS_RECOMPUTATION_MISMATCH')
    close(read_json(local_file(output, 'ranking-metrics.json')), all_rankings, 'RANKING_METRIC_RECOMPUTATION_MISMATCH')
    decision = screen(config, [chain_states[s['chain_id']] for s in held_specs], all_cells, all_rankings)
    require(decision == report['decision'], 'DECISION_RECOMPUTATION_MISMATCH')
    costs = read_json(local_file(output, 'target-costs.json'))
    measured = indexed(costs, ['chain_id', 'method'], 'DUPLICATE_TARGET_COST')
    require(set(measured) == {(s['chain_id'], m) for s in held_specs for m in RANK_METHODS}, 'TARGET_COST_COMPLETE_MATRIX_MISMATCH')
    for key, row in measured.items():
        chain_id, method = key
        count = chain_states[chain_id]['pool_count']
        full = check_benchmark(row['full_pool'], count, config['cost_policy']['target_benchmark_repeats'])
        selected = check_benchmark(row['selected'], min(config['primary_budget'], count), config['cost_policy']['target_benchmark_repeats'])
        valid_ratio = count > 0 and full > 0
        require(row['infer_only_ratio'] == (selected/full if valid_ratio else None) and row['infer_only_ratio_na_reason'] == (None if valid_ratio else 'EMPTY_POOL_OR_ZERO_TIMER') and row['includes_selection_cost'] is row['deployment_savings_established'] is False, 'TARGET_COST_RATIO_OR_SAVINGS_SCOPE_MISMATCH')
    require(report['total_model_fits'] == 4*len(specs) and report['heldout_chain_count'] == len(held_specs) and report['evaluation_cell_count'] == len(all_cells) and report['ranking_row_count'] == len(all_rankings) and report['cost_row_count'] == len(costs), 'REPORT_TOTAL_COUNT_MISMATCH')
    nonnegative(report['elapsed_seconds']); nonnegative(report['peak_rss_mib'])
    events = check_events(output, prereg, list(chain_states.values()), report, len(all_cells))
    return dict(status='PASS', frozen_files_verified=len(expected_files), current_model_states_verified=4*len(specs), previous_model_states_verified=len(previous),
                heldout_chains_verified=len(held_specs), development_chains_refitted={a: len(records[a]) for a in records}, cells_recomputed=len(all_cells), ranking_rows_recomputed=len(all_rankings),
                target_cost_rows_verified=len(costs), events_verified=events, actual_model_prediction_caches_replayed=True,
                whole_heldout_matrix_frozen_before_target_events=True, formal_test_model_input_count=0, recommendation=decision['recommendation'],
                limitations=['Trusted local pickle artifacts only; no task models retrained; inference replay and development predictor refit add audit cost.',
                             'Metric, selection and decision functions are replayed, not an independent proof of all formulas.',
                             'Source hashes, training metadata and event chains establish internal consistency, not an adversarial execution sandbox.',
                             'VAL texts were exposed previously; only model-update chains are held out; no formal TEST or significance claim.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Audit a trusted local history-increment run and replay its stored inference caches')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    with threadpool_limits(2):
        print(json.dumps(verify(args.output), ensure_ascii=False, indent=2, allow_nan=False))
