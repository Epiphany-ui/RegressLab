"""Audit one trusted local feasibility closeout, never tune or infer its target.

This CLI deserializes only hash-checked, locally generated sklearn model files.
It replays existing implementations rather than independently proving formulas.
TEST/OOS may participate in a repeated source-only audit, never model inference.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import pickle
import re
import tarfile

import numpy as np
from scipy import sparse
from sklearn.linear_model import SGDClassifier

from .baselines import select_baselines
from .clinc import COMMIT, DATA_SHA256, DATA_URL, LICENSE_SHA256, LICENSE_URL, audit_clinc
from .data import audit_massive, normalize_text
from .diagnostics import analyze_history_signal
from .feasibility import external_screens, risk_top
from .fetch import SHA256 as MASSIVE_ARCHIVE_SHA256, URL as MASSIVE_URL
from .hgc import DEFAULT_HGC_CONFIG, select_hgc
from .linear_state import audit_linear_nodes, linear_identity
from .round2 import aggregate_cells
from .runner import ROOT, digest, evaluate_cells, nested_train_indices, vectorizer
from .verify import DETERMINISTIC_METHODS, SEEDED_METHODS, file_sha, indexed, integer_values, read_json, require
from .verify2 import benchmark_block, check_hgc, local_file, nonnegative, predictions, timing_index


METHODS = SEEDED_METHODS | DETERMINISTIC_METHODS | {'hgc', 'risk-top'}


def expected_matrix(config):
    require(config['purpose'] == 'FIXED_FEASIBILITY_CLOSEOUT', 'CONFIG_PURPOSE_MISMATCH')
    require(config['hgc'] == DEFAULT_HGC_CONFIG, 'FIXED_HGC_CONFIGURATION_MISMATCH')
    require(type(config['datasets']) is list and len(config['datasets']) == 2 and set(config['datasets']) == {'massive', 'clinc'}, 'DATASET_SET_MISMATCH')
    integer_values(config['selection_seeds'], 0, 'INVALID_SELECTION_SEEDS')
    integer_values(config['budgets'], 1, 'INVALID_BUDGETS')
    require(config['primary_budget'] == 100 and config['primary_budget'] in config['budgets'], 'PRIMARY_BUDGET_100_REQUIRED')
    require(type(config['methods']) is list and len(config['methods']) == len(set(config['methods'])) and set(config['methods']) == METHODS, 'REGISTERED_METHOD_SET_MISMATCH')
    require(type(config['profiles']) is list and bool(config['profiles']), 'EMPTY_PROFILE_MATRIX')
    chains, names, profile_keys = [], set(), set()
    for profile in config['profiles']:
        require(profile['dataset'] in config['datasets'] and type(profile['id']) is str and re.fullmatch(r'[A-Za-z0-9_-]+', profile['id']), 'INVALID_PROFILE_ID')
        key = (profile['dataset'], profile['id'])
        require(key not in profile_keys, 'DUPLICATE_PROFILE')
        profile_keys.add(key)
        integer_values(profile['seeds'], 0, 'INVALID_TRAINING_SEEDS')
        require(len(profile['fractions']) == len(profile['epochs']) == 4, 'FOUR_VERSION_RECIPE_REQUIRED')
        require(all(type(x) in (int, float) and 0 < x <= 1 for x in profile['fractions']), 'INVALID_TRAIN_FRACTIONS')
        require(all(type(x) is int and x > 0 for x in profile['epochs']), 'INVALID_EPOCH_RECIPE')
        for seed in profile['seeds']:
            name = f"{profile['dataset']}-{profile['id']}-seed{seed}"
            require(name not in names, 'DUPLICATE_REGISTERED_CHAIN')
            names.add(name);chains.append((name, profile, seed))
    external = [p for p in config['profiles'] if p['dataset'] == 'clinc']
    require(len(config['external_families']) == len(set(config['external_families'])) and set(config['external_families']) == {p['id'] for p in external}, 'EXTERNAL_FAMILY_SET_MISMATCH')
    require(type(config['seeds_per_external_family']) is int and config['seeds_per_external_family'] > 0 and all(len(p['seeds']) == config['seeds_per_external_family'] for p in external), 'EXTERNAL_SEED_COUNT_MISMATCH')
    keys = {(method, seed, budget) for method in config['methods'] for seed in (config['selection_seeds'] if method in SEEDED_METHODS else [None]) for budget in config['budgets']}
    files = {'preregistration.json', 'identity-audit.json'}
    for dataset in config['datasets']:
        files.update(f'data/{dataset}/{name}' for name in ['audit.json', 'excluded.json', 'dev.json'])
    chain_files = ['training-summary.json', 'history-summary.json', 'selections.json', 'pool-vectors.npz', 'hgc-diagnostics.json', 'pretarget-costs.json', *[f'f{i}.pkl' for i in range(4)], *[f'f{i}-history.npz' for i in range(3)]]
    for name, _, _ in chains:
        files.update(f'chains/{name}/{filename}' for filename in chain_files)
    return chains, keys, files


def source_audit(output, config, name):
    audit = read_json(local_file(output, f'data/{name}/audit.json'))
    excluded = read_json(local_file(output, f'data/{name}/excluded.json'))
    dev = read_json(local_file(output, f'data/{name}/dev.json'))
    source = audit['source']
    require(audit['test_samples_returned'] == 0 and audit['test_use'] == 'AUDIT_ONLY_NO_MODEL_INPUT_OR_EVALUATION', 'DATA_TEST_SCOPE_MISMATCH')
    require(digest(excluded) == audit['excluded_sha256'], 'EXCLUDED_MANIFEST_HASH_MISMATCH')
    raw = None
    if name == 'massive':
        require(source['archive_sha256'] == MASSIVE_ARCHIVE_SHA256 and source['source_url'] == MASSIVE_URL and source['license'] == 'CC-BY-4.0', 'MASSIVE_SOURCE_REGISTRATION_MISMATCH')
        cache = ROOT/'datasets/massive-1.1'
        if (cache/'source.tar.gz').is_file() and (cache/'zh-CN.jsonl').is_file():
            require(file_sha(cache/'source.tar.gz') == MASSIVE_ARCHIVE_SHA256, 'MASSIVE_ARCHIVE_CHANGED')
            require(file_sha(cache/'zh-CN.jsonl') == source['data_sha256'], 'MASSIVE_DATA_CACHE_CHANGED')
            import hashlib
            with tarfile.open(cache/'source.tar.gz') as archive:
                member = archive.getmember('1.1/data/zh-CN.jsonl')
                require(member.isfile() and hashlib.sha256(archive.extractfile(member).read()).hexdigest() == source['data_sha256'], 'MASSIVE_ARCHIVE_DATA_MISMATCH')
            raw = audit_massive([json.loads(line) for line in (cache/'zh-CN.jsonl').read_text().splitlines()], source=source)
    else:
        require(source['source_commit'] == COMMIT and source['data_sha256'] == DATA_SHA256 and source['license_sha256'] == LICENSE_SHA256 and source['source_url'] == DATA_URL and source['license_url'] == LICENSE_URL and source['license'] == 'CC-BY-3.0', 'CLINC_SOURCE_REGISTRATION_MISMATCH')
        require(audit['oos_samples_returned'] == 0 and audit['dev_counts']['DEV_MODEL'] == 0 and audit['dev_protocol'] == 'ALL_OFFICIAL_VAL_FIXED_MODEL_AND_SELECTOR_NO_TUNING_NO_DEV_MODEL', 'CLINC_DIAGNOSTIC_SCOPE_MISMATCH')
        relative = Path(config['clinc_cache'])
        require(not relative.is_absolute() and '..' not in relative.parts, 'UNSAFE_CLINC_CACHE_PATH')
        cache = ROOT/relative
        if (cache/'data_full.json').is_file() and (cache/'LICENSE').is_file():
            require(file_sha(cache/'data_full.json') == DATA_SHA256 and file_sha(cache/'LICENSE') == LICENSE_SHA256, 'CLINC_SOURCE_CACHE_CHANGED')
            raw = audit_clinc(read_json(cache/'data_full.json'), source=source)
    labels = audit['label_vocab']
    require(type(labels) is list and len(labels) >= 2 and labels == sorted(set(labels), key=lambda s: s.encode('utf-8')), 'INVALID_DATA_LABEL_VOCABULARY')
    require(Counter(row['source_partition'] for row in excluded) == Counter({key:value for key,value in audit['excluded_counts'].items() if value}), 'EXCLUDED_COUNTS_MISMATCH')
    require(all(type(row) is dict and set(row) == {'sample_id', 'text', 'gold_label'} and all(type(x) is str and x for x in row.values()) for row in dev), 'INVALID_FROZEN_DEV_ROWS')
    ids = [row['sample_id'] for row in dev]
    require(ids == sorted(set(ids), key=lambda value: value.encode('utf-8')) and len(dev) == audit['dev_counts']['DEV_SELECTOR'], 'DEV_ID_OR_COUNT_MISMATCH')
    require(all(row['gold_label'] in labels and normalize_text(row['text']) for row in dev), 'DEV_TEXT_OR_LABEL_MISMATCH')
    require({label:sum(row['gold_label']==label for row in dev) for label in labels} == audit['dev_label_counts']['DEV_SELECTOR'], 'DEV_LABEL_SUPPORT_MISMATCH')
    require(set(audit['train_label_counts']) == set(labels) and all(type(x) is int and x > 0 for x in audit['train_label_counts'].values()), 'TRAIN_LABEL_SUPPORT_MISMATCH')
    if raw is not None:
        projected = [{k:r[k] for k in ('sample_id','text','gold_label')} for r in raw['dev_selector']]
        require(raw['manifest'] == audit and raw['excluded'] == excluded and projected == dev, 'OFFICIAL_SOURCE_REAUDIT_MISMATCH')
    return audit, dev, raw


def trusted_bundle(path, expected_sha):
    require(file_sha(path) == expected_sha, 'MODEL_FILE_HASH_MISMATCH')
    with path.open('rb') as stream:
        bundle = pickle.load(stream)  # TRUSTED LOCAL RUN ONLY.
    require(type(bundle) is dict and set(bundle) == {'vectorizer', 'classifier'}, 'MODEL_BUNDLE_FIELDS_MISMATCH')
    return bundle, linear_identity(bundle['vectorizer'], bundle['classifier'])


def previous_exposures(config):
    require(type(config['previous_runs']) is list and len(config['previous_runs']) == 2, 'PREVIOUS_RUN_SET_MISMATCH')
    previous = []
    registered_paths = set()
    for registered in config['previous_runs']:
        path = Path(registered['path'])
        require(not path.is_absolute() and '..' not in path.parts and str(path) not in registered_paths, 'UNSAFE_OR_DUPLICATE_PREVIOUS_RUN')
        registered_paths.add(str(path));root = ROOT/path
        frozen = read_json(local_file(root,'matrix-freeze.json'))
        require(file_sha(root/'matrix-freeze.json') == registered['freeze_sha256'], 'PREVIOUS_FREEZE_HASH_MISMATCH')
        for relative, expected in frozen['files'].items():
            require(file_sha(local_file(root,relative)) == expected, 'PREVIOUS_FROZEN_INPUT_CHANGED')
        prereg = read_json(local_file(root,'preregistration.json'))
        expected_chains = [f"{family['id']}-seed{seed}" for family in prereg['config']['families'] for seed in prereg['config']['training_seeds']]
        require(frozen['chain_ids'] == expected_chains and len(expected_chains) == 6, 'PREVIOUS_FROZEN_CHAIN_SET_MISMATCH')
        for chain in expected_chains:
            for slot in range(4):
                relative = f'chains/{chain}/f{slot}.pkl'
                require(relative in frozen['files'], 'PREVIOUS_MODEL_NOT_FROZEN')
                _, identity = trusted_bundle(local_file(root,relative),frozen['files'][relative])
                previous.append(dict(run=registered['path'],chain_id=chain,slot=f'f{slot}',identity=identity))
    require(len(previous) == 48, 'PREVIOUS_EXPOSURE_COUNT_MISMATCH')
    return previous


def cost_rows(config, chain, selections, pretarget, target):
    baseline_config = {**config,'methods':[m for m in config['methods'] if m != 'risk-top']}
    timing_index(pretarget['all_budget_baselines'],baseline_config,max(config['budgets']))
    timings = timing_index(pretarget['primary_budget_baselines'],baseline_config,config['primary_budget'])
    nonnegative(pretarget['selection_representation_seconds']);nonnegative(pretarget['reference_score_rebuild_seconds'])
    require(set(pretarget['primary_budget_risk_top']) == {'risk_build_seconds','total_seconds'}, 'RISK_TOP_TIMING_FIELDS_MISMATCH')
    require(nonnegative(pretarget['primary_budget_risk_top']['total_seconds']) >= nonnegative(pretarget['primary_budget_risk_top']['risk_build_seconds']), 'RISK_TOP_TIMING_TOTAL_MISMATCH')
    suites = [suite for suite in selections if suite['budget'] == config['primary_budget']]
    measured = indexed(target['suites'],['method','seed','budget'],'DUPLICATE_TARGET_COST_SUITE')
    require(set(measured) == {(s['method'],s['seed'],s['budget']) for s in suites}, 'TARGET_COST_SUITE_SET_MISMATCH')
    full = benchmark_block(target['full_pool'],chain['pool_count'])
    require(full > 0,'ZERO_FULL_POOL_BENCHMARK_TIME')
    output = []
    for suite in suites:
        method = suite['method'];entry = measured[(method,suite['seed'],suite['budget'])]
        selected = benchmark_block({k:v for k,v in entry.items() if k not in {'method','seed','budget'}},len(suite['indices']))
        shared = 0.0
        if method == 'hgc':
            selection = nonnegative(pretarget['primary_budget_hgc']['total_seconds'])
        elif method == 'risk-top':
            selection = nonnegative(pretarget['primary_budget_risk_top']['total_seconds'])
        else:
            shared = timings[('__shared_validation__',None)]['selection_seconds']
            selection = timings[(method,suite['seed'])]['selection_seconds'] + shared
        representation = pretarget['selection_representation_seconds'] if method in {'hgc','kcenter','facility'} else 0.0
        total = selection + representation + selected
        output.append(dict(chain_id=chain['chain_id'],dataset=chain['dataset'],family=chain['family'],method=method,seed=suite['seed'],budget=suite['budget'],selection_seconds=selection,shared_validation_seconds=shared,representation_seconds=representation,selected_inference_seconds=selected,full_pool_inference_seconds=full,deployment_seconds_cached_history=total,deployment_cost_ratio=total/full,reference_score_rebuild_seconds_if_uncached=pretarget['reference_score_rebuild_seconds'] if method.startswith('ref-') else 0.0))
    return output


def check_events(output, config, chains, cells, report, previous_count, data_counts):
    events=[]
    for line in local_file(output,'events.jsonl').read_text().splitlines():
        def unique(pairs):
            require(len(dict(pairs)) == len(pairs),'DUPLICATE_EVENT_JSON_KEY');return dict(pairs)
        events.append(json.loads(line,object_pairs_hook=unique))
    counts={'PREREGISTERED':1,'DATA_AUDITED':1,'MODEL_TRAINED':4*len(chains),'GLOBAL_IDENTITY_GATE':1,'HISTORY_PREDICTED':3*len(chains),'CHAIN_SUITES_READY':len(chains),'ALL_SUITES_FROZEN':1,'TARGET_EVALUATED':len(chains),'TARGET_COST_MEASURED':len(chains),'CLOSEOUT_NATURAL_COMPLETE':1}
    require(Counter(e['event'] for e in events) == counts,'EVENT_SET_MISMATCH')
    require(events[0]['event']=='PREREGISTERED' and events[-1]['event']=='CLOSEOUT_NATURAL_COMPLETE','EVENT_BOUNDARY_MISMATCH')
    for index,event in enumerate(events):
        require(set(event)=={'event','time','details','previous_sha256'},'EVENT_FIELDS_MISMATCH')
        require(event['previous_sha256']==(digest(events[index-1]) if index else None),'EVENT_HASH_CHAIN_MISMATCH')
        now=datetime.fromisoformat(event['time'])
        require(now.tzinfo is not None and (not index or now>=datetime.fromisoformat(events[index-1]['time'])),'EVENT_TIME_ORDER_MISMATCH')
    gate=next(i for i,e in enumerate(events) if e['event']=='GLOBAL_IDENTITY_GATE');freeze=next(i for i,e in enumerate(events) if e['event']=='ALL_SUITES_FROZEN')
    require(gate<freeze and events[gate]['details']==dict(passed=True,current_nodes=4*len(chains),previous_nodes=previous_count,dev_predicted=False),'IDENTITY_GATE_EVENT_MISMATCH')
    require(events[freeze]['details']==dict(cell_count=len(cells),freeze_sha256=file_sha(output/'matrix-freeze.json')),'FREEZE_EVENT_MISMATCH')
    require(events[0]['details']==dict(config_sha256=digest(config)),'PREREGISTRATION_EVENT_MISMATCH')
    by_chain={c['chain_id']:c for c in chains}
    data_index=next(i for i,e in enumerate(events) if e['event']=='DATA_AUDITED')
    require(data_index<gate and events[data_index]['details']==dict(datasets=data_counts),'DATA_EVENT_AFTER_GATE_OR_COUNTS_MISMATCH')
    seen={kind:set() for kind in ['MODEL_TRAINED','HISTORY_PREDICTED','CHAIN_SUITES_READY','TARGET_EVALUATED','TARGET_COST_MEASURED']}
    for index,event in enumerate(events):
        kind,detail=event['event'],event['details']
        if kind not in seen:continue
        require(detail['chain_id'] in by_chain,'UNKNOWN_EVENT_CHAIN');chain=by_chain[detail['chain_id']]
        key=(detail['chain_id'],detail['slot']) if kind in {'MODEL_TRAINED','HISTORY_PREDICTED'} else detail['chain_id']
        require(key not in seen[kind],'DUPLICATE_STAGE_EVENT');seen[kind].add(key)
        if kind=='MODEL_TRAINED':
            require(data_index<index<gate and detail['slot'] in {'f0','f1','f2','f3'},'TRAINING_AFTER_IDENTITY_GATE')
            version=next(v for v in chain['versions'] if v['slot']==detail['slot'])
            require(detail==dict(chain_id=chain['chain_id'],slot=detail['slot'],seconds=round(version['train_seconds'],3),dev_predicted=False),'MODEL_TRAIN_EVENT_MISMATCH')
        elif kind=='HISTORY_PREDICTED':
            require(gate<index<freeze and detail['slot'] in {'f0','f1','f2'},'HISTORY_BEFORE_GATE_OR_AFTER_FREEZE')
        elif kind=='CHAIN_SUITES_READY':
            require(gate<index<freeze and all((chain['chain_id'],f'f{s}') in seen['HISTORY_PREDICTED'] for s in range(3)),'SUITES_BEFORE_HISTORY_OR_AFTER_FREEZE')
            require(detail==dict(chain_id=chain['chain_id'],pool_count=chain['pool_count'],cells=chain['selection_cells']),'SUITES_EVENT_MISMATCH')
        elif kind=='TARGET_EVALUATED':
            require(index>freeze and detail==dict(chain_id=chain['chain_id'],future_flips=chain['future_flip_count']),'TARGET_BEFORE_FREEZE_OR_SUMMARY_MISMATCH')
        else:
            count=len(config['selection_seeds'])*len(SEEDED_METHODS)+len(DETERMINISTIC_METHODS)+2
            require(index>freeze and chain['chain_id'] in seen['TARGET_EVALUATED'] and detail==dict(chain_id=chain['chain_id'],suite_count=count),'TARGET_COST_EVENT_MISMATCH')
    names=set(by_chain)
    require(seen['MODEL_TRAINED']=={(c,f'f{s}') for c in names for s in range(4)} and seen['HISTORY_PREDICTED']=={(c,f'f{s}') for c in names for s in range(3)},'MODEL_OR_HISTORY_EVENT_MATRIX_MISMATCH')
    require(all(seen[k]==names for k in ['CHAIN_SUITES_READY','TARGET_EVALUATED','TARGET_COST_MEASURED']),'CHAIN_EVENT_MATRIX_MISMATCH')
    nonnegative(report['wall_seconds'])
    require(events[-1]['details']==dict(screens=report['screens'],wall_seconds=round(report['wall_seconds'],3)),'COMPLETE_EVENT_MISMATCH')
    return len(events)


def verify(output: Path) -> dict:
    output=Path(output).resolve()
    frozen=read_json(local_file(output,'matrix-freeze.json'))
    require(frozen['schema_version']=='feasibility-matrix-v1' and frozen['purpose']=='FIXED_FEASIBILITY_CLOSEOUT' and frozen['target_predictions_generated'] is False,'FREEZE_SCOPE_MISMATCH')
    for relative,expected in frozen['files'].items():
        require(type(expected) is str and re.fullmatch(r'[0-9a-f]{64}',expected) and file_sha(local_file(output,relative))==expected,'FROZEN_INPUT_CHANGED')
    prereg=read_json(local_file(output,'preregistration.json'));config=prereg['config']
    expected_chains,expected_keys,expected_files=expected_matrix(config)
    require(set(frozen['files'])==expected_files,'FROZEN_FILE_SET_MISMATCH')
    require(prereg['config_sha256']==frozen['config_sha256']==digest(config),'CONFIG_HASH_MISMATCH')
    require(frozen['chain_ids']==[name for name,_,_ in expected_chains] and frozen['cell_count']==len(expected_chains)*len(expected_keys),'FROZEN_MATRIX_MISMATCH')
    report=read_json(local_file(output,'report.json'))
    require(report['schema_version']=='feasibility-closeout-natural-v1' and report['run_id']==prereg['run_id'] and report['purpose']==config['purpose'],'REPORT_IDENTITY_MISMATCH')
    require(report['config_sha256']==digest(config) and report['freeze_sha256']==file_sha(output/'matrix-freeze.json'),'REPORT_FREEZE_MISMATCH')
    require(report['formal_test_model_input_count']==0 and report['hgc_config_changed'] is False and report['formal_evaluation'] is False and report['limitations']==config['limitations'],'REPORT_SCOPE_MISMATCH')
    require(report['environment']['cpu_threads']==config['cpu_threads'],'CPU_THREAD_MISMATCH')
    datasets={name:source_audit(output,config,name) for name in config['datasets']}
    reported=indexed(report['chains'],['chain_id'],'DUPLICATE_REPORT_CHAIN')
    require(set(reported)=={(name,) for name,_,_ in expected_chains},'REPORT_CHAIN_SET_MISMATCH')
    all_cells,all_costs,nodes,summaries,diagnostics=[],[],[],[],{}
    for name,profile,seed in expected_chains:
        directory=output/'chains'/name;audit,dev,raw=datasets[profile['dataset']];labels=audit['label_vocab'];ids=[row['sample_id'] for row in dev];gold=np.asarray([row['gold_label'] for row in dev])
        summary=read_json(directory/'history-summary.json');training=read_json(directory/'training-summary.json');chain=reported[(name,)]
        require(all(chain.get(k)==v for k,v in summary.items()),'REPORT_CHAIN_SUMMARY_MISMATCH')
        require(summary['chain_id']==name and summary['dataset']==profile['dataset'] and summary['family']==profile['id'] and summary['training_seed']==seed and summary['dev_count']==len(dev),'CHAIN_REGISTRATION_MISMATCH')
        require([v['slot'] for v in summary['versions']]==[f'f{s}' for s in range(4)] and len(training['versions'])==4,'MODEL_SLOT_SET_MISMATCH')
        require(all(training[k]==summary[k] for k in ['chain_id','dataset','family','training_seed','training_representation_seconds']),'TRAINING_SUMMARY_MISMATCH')
        history,reference=[],None
        for slot,version in enumerate(summary['versions']):
            require(all(version.get(k)==v for k,v in training['versions'][slot].items()),'TRAINING_VERSION_MISMATCH')
            bundle,identity=trusted_bundle(local_file(output,f'chains/{name}/f{slot}.pkl'),version['model_file_sha256'])
            require(identity==version['identity'],'LINEAR_IDENTITY_MISMATCH')
            model=bundle['classifier'];require(type(model) is SGDClassifier,'NATURAL_MODEL_TYPE_MISMATCH')
            require(all(model.get_params()[k]==v for k,v in config['classifier'].items()) and model.max_iter==profile['epochs'][slot] and model.random_state==seed,'FITTED_MODEL_CONFIG_MISMATCH')
            require(model.classes_.tolist()==labels and model.n_iter_==version['n_iter']==profile['epochs'][slot]==version['epochs'] and version['fixed_epoch_budget_completed'] is True and version['restore_check'] is True,'FIXED_EPOCH_OR_RESTORE_GATE_MISMATCH')
            require(all(bundle['vectorizer'].get_params()[k]==(tuple(v) if k=='ngram_range' else v) for k,v in config['classifier_representation'].items() if k!='fit_on'),'FITTED_REPRESENTATION_CONFIG_MISMATCH')
            expected_count=sum(count if profile['fractions'][slot]==1 else max(1,int(profile['fractions'][slot]*count)) for count in audit['train_label_counts'].values())
            require(version['training_rows']==expected_count,'TRAINING_ROW_COUNT_MISMATCH')
            require(nonnegative(version['train_seconds'])<=config['max_fit_seconds'],'FIT_TIME_GATE_FAILED')
            if raw is not None:
                chosen=nested_train_indices(raw['train'],profile['fractions'][slot],seed);base=nested_train_indices(raw['train'],.4,seed)
                require(version['train_ids_sha256']==digest([raw['train'][i]['sample_id'] for i in chosen]) and version['basis_train_ids_sha256']==digest([raw['train'][i]['sample_id'] for i in base]),'TRAINING_IDS_FROM_SOURCE_MISMATCH')
            nodes.append(dict(chain_id=name,slot=f'f{slot}',identity=identity))
            if slot<3:
                predicted,probs=predictions(directory/f'f{slot}-history.npz',labels,ids,with_scores=True)
                require(version['dev_accuracy']==float(np.mean(predicted==gold)),'HISTORY_ACCURACY_MISMATCH');nonnegative(version['history_seconds']);history.append(predicted)
                if slot==2:reference=probs
        require(len({v['basis_train_ids_sha256'] for v in summary['versions']})==1,'CHAIN_BASIS_ID_MISMATCH')
        history=np.asarray(history).T;pool=np.flatnonzero(history[:,2]==gold);selected=read_json(directory/'selections.json')
        require(selected['scope']=='DEV_SELECTOR_CURRENT_CORRECT' and selected['pool_indices_in_dev']==pool.tolist() and selected['pool_ids']==[ids[i] for i in pool] and selected['pool_gold']==gold[pool].tolist() and selected['history']==history[pool].tolist(),'FULL_CURRENT_CORRECT_POOL_MISMATCH')
        require(summary['pool_count']==len(pool) and summary['pool_label_count']==len(set(gold[pool])),'POOL_SUMMARY_MISMATCH')
        selections=selected['selections'];require(set(indexed(selections,['method','seed','budget'],'DUPLICATE_SELECTION_CELL'))==expected_keys and summary['selection_cells']==len(expected_keys),'SELECTION_CELL_SET_MISMATCH')
        texts=[normalize_text(dev[i]['text']) for i in pool];rebuilt=vectorizer(config['selection_representation']).fit_transform(texts) if len(pool) else sparse.csr_matrix((0,0));vectors=sparse.load_npz(directory/'pool-vectors.npz').tocsr()
        require(vectors.shape==rebuilt.shape and np.array_equal(vectors.indptr,rebuilt.indptr) and np.array_equal(vectors.indices,rebuilt.indices) and np.array_equal(vectors.data,rebuilt.data),'POOL_REPRESENTATION_MISMATCH')
        baseline=select_baselines(selected['pool_ids'],selected['pool_gold'],history[pool],reference[pool],vectors,labels,config['budgets'],config['selection_seeds'])
        hgc,groups=select_hgc(dev,history,pool.tolist(),vectors,config['budgets'],config['hgc']);risk,_=risk_top(dev,history,pool.tolist(),config['budgets'],config['hgc'])
        require(selections==baseline+hgc+risk,'SELECTION_REPLAY_MISMATCH');check_hgc(read_json(directory/'hgc-diagnostics.json'),groups)
        require(summary['hgc_group_count']==len(groups['groups']) and summary['hgc_fallback']==groups['fallback'],'HGC_SUMMARY_MISMATCH')
        pre=read_json(directory/'pretarget-costs.json');_,primary_groups=select_hgc(dev,history,pool.tolist(),vectors,[config['primary_budget']],config['hgc']);check_hgc(pre['primary_budget_hgc'],primary_groups)
        target,_=predictions(local_file(output,f'chains/{name}/f3-target.npz'),labels,ids,with_scores=False)
        computed=evaluate_cells(selected['pool_gold'],selected['history'],target[pool],selections)
        for cell in computed:cell.update(chain_id=name,family=chain['family'],dataset=chain['dataset'])
        first=computed[0];require(chain['future_flip_count']==first['future_flip_count'] and chain['historically_unseen_flips']==first['historically_unseen']['denominator'] and chain['repaired_then_recurred_flips']==first['repaired_then_recurred']['denominator'] and chain['target_dev_accuracy']==float(np.mean(target==gold)),'TARGET_SUMMARY_MISMATCH')
        diagnostic=analyze_history_signal(dev,history,pool.tolist(),reference,groups['groups'],target,context='PRESPECIFIED_EXTERNAL' if chain['dataset']=='clinc' else 'PRESPECIFIED_OLD_DEV_NEW_MODEL')
        require(diagnostic==read_json(local_file(output,f'chains/{name}/posttarget-diagnostics.json')),'POSTTARGET_DIAGNOSTIC_MISMATCH');diagnostics[name]=diagnostic
        all_cells.extend(computed);all_costs.extend(cost_rows(config,chain,selections,pre,read_json(local_file(output,f'chains/{name}/target-costs.json'))));summaries.append(chain)
    actual_audit=audit_linear_nodes(nodes);stored_audit=read_json(output/'identity-audit.json')
    require(all(stored_audit.get(k)==v for k,v in actual_audit.items()),'GLOBAL_IDENTITY_AUDIT_MISMATCH')
    previous=previous_exposures(config);require(previous==stored_audit['previously_exposed_nodes'],'PREVIOUS_EXPOSURE_STATE_MISMATCH')
    collisions=[dict(target=node['chain_id'],previous_run=p['run'],previous_chain=p['chain_id'],previous_slot=p['slot']) for node in nodes if node['slot']=='f3' for p in previous if node['identity']['label_state_sha256']==p['identity']['label_state_sha256']]
    require(actual_audit['passed'] and stored_audit['passed'] is True and not collisions and stored_audit['previous_exposure_collisions']==collisions,'TARGET_STATE_COLLISION')
    require(all_cells==read_json(local_file(output,'evaluation-cells.json')) and len(all_cells)==frozen['cell_count'],'EVALUATION_CELLS_MISMATCH')
    require(all_costs==read_json(local_file(output,'deployment-costs.json')),'DEPLOYMENT_COSTS_MISMATCH')
    require(diagnostics==read_json(local_file(output,'history-diagnostics.json')),'GLOBAL_DIAGNOSTIC_SET_MISMATCH')
    aggregates=aggregate_cells(all_cells);require(report['baseline_aggregates']==aggregates and len(aggregates)==len(expected_chains)*len(config['methods'])*len(config['budgets']),'AGGREGATE_SET_OR_VALUE_MISMATCH')
    require(report['screens']==external_screens(config,summaries,aggregates,diagnostics,all_costs),'FINAL_SCREEN_MISMATCH')
    data_counts={name:dict(train=sum(audit['train_label_counts'].values()),dev=len(dev)) for name,(audit,dev,_) in datasets.items()}
    event_count=check_events(output,config,summaries,all_cells,report,len(previous),data_counts)
    source_verified=[name for name,(_,_,raw) in datasets.items() if raw is not None]
    return dict(status='PASS',scope='FIXED_FEASIBILITY_DIAGNOSTIC_ONLY',frozen_files_verified=len(expected_files),chains_verified=len(expected_chains),cells_recomputed=len(all_cells),aggregates_recomputed=len(aggregates),primary_cost_rows_recomputed=len(all_costs),events_verified=event_count,full_current_correct_pools_reconstructed=True,history_only_selection_and_risk_diagnostics_replayed=True,current_linear_identities_verified=len(nodes),previously_exposed_model_states_verified=len(previous),official_source_datasets_reaudited=source_verified,global_identity_gate_before_history_events=True,target_events_after_freeze=True,recommendation=report['screens']['recommendation'],formal_evaluation=False,statistical_independence_established=False,limitations=['Trusted local pickle artifacts only; never apply to untrusted uploads.','Existing selector, metric and decision implementations are replayed, not independently proven.','Cached target labels are checked and aligned; target inference is not rerun by this audit.','Event hashes verify internal consistency, not external proof of hidden access or chronology.','A fixed feasibility screen is not statistical superiority, noninferiority or thesis approval.','Related linear classifiers and fixed-order warm-cache costs do not establish neural-model conclusions.','Missing official source caches prevent repeated model-free source/row-ID reconstruction and are reported explicitly.'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='审计可信本机固定可行性复核目录，会加载hash核验模型pickle')
    parser.add_argument('output',type=Path);args=parser.parse_args()
    print(json.dumps(verify(args.output),ensure_ascii=False,indent=2))
