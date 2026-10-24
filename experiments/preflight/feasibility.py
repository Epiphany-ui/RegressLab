"""One fixed, externally audited feasibility closeout, not a parameter search."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import pickle
import platform
import resource
import subprocess
import time
from uuid import uuid4

import numpy as np
from scipy import sparse
from sklearn.linear_model import SGDClassifier
from threadpoolctl import threadpool_limits

from .baselines import select_baselines
from .clinc import audit_clinc, fetch_clinc
from .data import audit_massive, normalize_text
from .diagnostics import analyze_history_signal
from .fetch import fetch
from .hgc import DEFAULT_HGC_CONFIG, _risk_groups, select_hgc
from .linear_state import audit_linear_nodes, linear_identity
from .round2 import aggregate_cells, benchmark_predict, validate_selection_matrix
from .runner import ROOT, canonical, digest, evaluate_cells, file_hash, nested_train_indices, probabilities, utc, vectorizer, verify_freeze, write_json


def risk_top(rows, history, pool, budgets, config):
    """Static historical group-risk ranking; no target or representation input."""
    begin = time.perf_counter()
    gold = np.asarray([row['gold_label'] for row in rows])
    history = np.asarray(history)
    if history.shape != (len(rows), 3):
        raise ValueError('RISK_TOP_HISTORY_OR_POOL_MISMATCH')
    expected = np.flatnonzero(history[:, 2] == gold).tolist()
    if pool != expected:
        raise ValueError('RISK_TOP_HISTORY_OR_POOL_MISMATCH')
    groups, _, _ = _risk_groups(rows, history, gold, pool, config)
    risk_seconds = time.perf_counter() - begin
    scores = np.zeros(len(pool))
    for group in groups:
        scores[group['p_member_indices']] += group['normalized_weight']
    ordered = sorted(range(len(pool)), key=lambda i: (-scores[i], rows[pool[i]]['sample_id'].encode('utf-8')))
    selections = [dict(method='risk-top', seed=None, budget=b, indices=ordered[:min(b, len(pool))]) for b in budgets]
    return selections, dict(risk_build_seconds=risk_seconds, total_seconds=time.perf_counter()-begin)


def prepare(config):
    output = {}
    for name in config['datasets']:
        if name == 'massive':
            directory = ROOT/'datasets/massive-1.1'
            source = fetch(directory)
            rows = [json.loads(line) for line in (directory/'zh-CN.jsonl').read_text().splitlines()]
            output[name] = audit_massive(rows, source=source)
        elif name == 'clinc':
            directory = ROOT/config['clinc_cache']
            source = fetch_clinc(directory)
            output[name] = audit_clinc(json.loads((directory/'data_full.json').read_text()), source=source)
        else:
            raise ValueError('UNKNOWN_REGISTERED_DATASET')
    return output


def external_screens(config, chains, aggregates, diagnostics, costs):
    results = {}
    for family in config['external_families']:
        subset = [c for c in chains if c['dataset'] == 'clinc' and c['family'] == family]
        differences, risk_random, risk_facility, aucs, additions = [], [], [], [], []
        for chain in subset:
            values = {a['method']:a['mean_recall'] for a in aggregates if a['chain_id']==chain['chain_id'] and a['budget']==config['primary_budget']}
            if values['hgc'] is not None:
                differences.append(values['hgc']-values['ref-margin'])
                risk_random.append(values['risk-top']-values['random'])
                risk_facility.append(values['risk-top']-values['facility'])
            diagnostic = diagnostics[chain['chain_id']]
            aucs.append(diagnostic['risk_top']['roc_auc'])
            additions.append(diagnostic['incremental_over_margin_top100']['risk_only_detected'])
        valid = len(subset) == config['seeds_per_external_family'] and all(c['future_flip_count'] >= config['decision_policy']['minimum_events_per_chain'] for c in subset)
        def mean(values):
            return float(np.mean(values)) if values and all(x is not None for x in values) else None
        results[family] = dict(chain_count=len(subset), adequate_event_support=valid, hgc_minus_margin=mean(differences), risk_top_minus_random=mean(risk_random), risk_top_minus_facility=mean(risk_facility), risk_auc=mean(aucs), chains_with_new_events_beyond_margin=sum(x>0 for x in additions))
    adequate = all(f['adequate_event_support'] for f in results.values())
    policy = config['decision_policy']
    hgc_recall = adequate and all(f['hgc_minus_margin'] >= policy['hgc_min_family_difference'] for f in results.values()) and any(f['hgc_minus_margin'] >= policy['hgc_required_improvement_one_family'] for f in results.values())
    history_signal = adequate and all(f['risk_auc'] is not None and f['risk_auc'] >= policy['risk_auc_floor'] and f['risk_top_minus_random'] >= policy['risk_min_recall_gain'] and f['risk_top_minus_facility'] >= policy['risk_min_recall_gain'] and f['chains_with_new_events_beyond_margin'] >= policy['risk_min_chains_with_additions_per_family'] for f in results.values())
    hgc_costs = [x['deployment_cost_ratio'] for x in costs if x['dataset']=='clinc' and x['method']=='hgc']
    affordable = len(hgc_costs)==len([c for c in chains if c['dataset']=='clinc']) and all(x <= policy['hgc_max_cost_ratio'] for x in hgc_costs)
    decision = 'CONTINUE_HGC_CONDITIONALLY' if hgc_recall and affordable else 'REDIRECT_TO_HISTORY_MECHANISM' if history_signal else 'NO_GO_CURRENT_HGC_METHOD'
    return dict(external_families=results, adequate_natural_event_support=adequate, hgc_practical_recall_screen=hgc_recall, cached_history_hgc_cost_screen=affordable, historical_signal_screen=history_signal, recommendation=decision, statistical_superiority_established=False, thesis_approval_established=False, formal_test_model_input_count=0)


def run(config_path, output):
    config = json.loads(config_path.read_text())
    if config['purpose'] != 'FIXED_FEASIBILITY_CLOSEOUT' or config['hgc'] != DEFAULT_HGC_CONFIG or output.exists():
        raise ValueError('FIXED_CLOSEOUT_NEW_DIRECTORY_REQUIRED')
    output.mkdir(parents=True)
    started = time.perf_counter()
    events = []
    def event(kind, **details):
        value = dict(event=kind,time=utc(),details=details,previous_sha256=digest(events[-1]) if events else None)
        events.append(value)
        with (output/'events.jsonl').open('a') as stream:
            stream.write(canonical(value).decode()+'\n');stream.flush();os.fsync(stream.fileno())
        print(json.dumps(dict(event=kind,**details)),flush=True)
    prereg = dict(run_id=str(uuid4()),registered_at=utc(),config=config,config_sha256=digest(config),code_files={str(p.relative_to(ROOT)):file_hash(p) for p in sorted((ROOT/'experiments/preflight').glob('*.py'))},dependency_lock_sha256=file_hash(ROOT/'experiments/uv.lock'),git_base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),working_tree_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()))
    write_json(output/'preregistration.json',prereg)
    event('PREREGISTERED',config_sha256=digest(config))
    data = prepare(config)
    for name, dataset in data.items():
        directory=output/'data'/name;directory.mkdir(parents=True)
        write_json(directory/'audit.json',dataset['manifest'])
        write_json(directory/'excluded.json',dataset['excluded'])
        dataset['dev']=[{k:r[k] for k in ('sample_id','text','gold_label')} for r in dataset['dev_selector']]
        write_json(directory/'dev.json',dataset['dev'])
    event('DATA_AUDITED',datasets={n:dict(train=len(d['train']),dev=len(d['dev'])) for n,d in data.items()})
    chains,nodes=[],[]
    for profile in config['profiles']:
        dataset=data[profile['dataset']];train=dataset['train'];texts=[normalize_text(r['text']) for r in train];gold=np.asarray([r['gold_label'] for r in train])
        for seed in profile['seeds']:
            chain_id=f"{profile['dataset']}-{profile['id']}-seed{seed}";directory=output/'chains'/chain_id;directory.mkdir(parents=True)
            base=nested_train_indices(train,.4,seed);representation=vectorizer(config['classifier_representation']);begin=time.perf_counter();x_train=representation.fit([texts[i] for i in base]).transform(texts);basis_seconds=time.perf_counter()-begin
            versions=[]
            for slot in range(4):
                selected=nested_train_indices(train,profile['fractions'][slot],seed)
                model=SGDClassifier(max_iter=profile['epochs'][slot],random_state=seed,**config['classifier'])
                begin=time.perf_counter();model.fit(x_train[selected],gold[selected]);elapsed=time.perf_counter()-begin
                if elapsed>config['max_fit_seconds'] or time.perf_counter()-started>config['max_total_seconds'] or model.n_iter_!=profile['epochs'][slot]:
                    raise ValueError('FIXED_TRAINING_BUDGET_GATE_FAILED_NO_RETUNING')
                bundle=dict(vectorizer=representation,classifier=model)
                with (directory/f'f{slot}.pkl').open('xb') as stream:pickle.dump(bundle,stream,protocol=5)
                with (directory/f'f{slot}.pkl').open('rb') as stream:restored=pickle.load(stream)
                if not np.array_equal(model.predict(x_train[:32]),restored['classifier'].predict(x_train[:32])):raise ValueError('MODEL_RESTORE_MISMATCH')
                identity=linear_identity(representation,model)
                node=dict(chain_id=chain_id,slot=f'f{slot}',identity=identity);nodes.append(node)
                versions.append(dict(slot=f'f{slot}',epochs=profile['epochs'][slot],training_rows=len(selected),train_ids_sha256=digest([train[i]['sample_id'] for i in selected]),basis_train_ids_sha256=digest([train[i]['sample_id'] for i in base]),model_file_sha256=file_hash(directory/f'f{slot}.pkl'),identity=identity,train_seconds=elapsed,n_iter=int(model.n_iter_),fixed_epoch_budget_completed=True,restore_check=True))
                event('MODEL_TRAINED',chain_id=chain_id,slot=f'f{slot}',seconds=round(elapsed,3),dev_predicted=False)
            chain=dict(chain_id=chain_id,dataset=profile['dataset'],family=profile['id'],training_seed=seed,versions=versions,training_representation_seconds=basis_seconds)
            chains.append(chain);write_json(directory/'training-summary.json',chain);del x_train,model,restored,bundle
    audit=audit_linear_nodes(nodes);previous=[]
    for registered in config['previous_runs']:
        prior=ROOT/registered['path']
        if file_hash(prior/'matrix-freeze.json')!=registered['freeze_sha256']:raise ValueError('PRIOR_FREEZE_CHANGED')
        frozen=verify_freeze(prior)
        old_registration=json.loads((prior/'preregistration.json').read_text())
        old_config=old_registration['config']
        expected_old_chains=[f"{f['id']}-seed{seed}" for f in old_config['families'] for seed in old_config['training_seeds']]
        if frozen['chain_ids']!=expected_old_chains or len(expected_old_chains)!=6:raise ValueError('PRIOR_EXPOSURE_CHAIN_SET_MISMATCH')
        for chain_id in expected_old_chains:
            for slot in range(4):
                with (prior/'chains'/chain_id/f'f{slot}.pkl').open('rb') as stream:bundle=pickle.load(stream)
                previous.append(dict(run=registered['path'],chain_id=chain_id,slot=f'f{slot}',identity=linear_identity(bundle['vectorizer'],bundle['classifier'])))
    if len(previous)!=48:raise ValueError('PRIOR_EXPOSURE_NODE_COUNT_MISMATCH')
    collisions=[dict(target=n['chain_id'],previous_run=p['run'],previous_chain=p['chain_id'],previous_slot=p['slot']) for n in nodes if n['slot']=='f3' for p in previous if n['identity']['label_state_sha256']==p['identity']['label_state_sha256']]
    audit.update(previously_exposed_nodes=previous,previous_exposure_collisions=collisions)
    audit['passed']=audit['passed'] and not collisions
    write_json(output/'identity-audit.json',audit);event('GLOBAL_IDENTITY_GATE',passed=audit['passed'],current_nodes=len(nodes),previous_nodes=len(previous),dev_predicted=False)
    if not audit['passed']:raise ValueError('TARGET_STATE_REUSED_NO_RETUNING')
    for chain in chains:
        directory=output/'chains'/chain['chain_id'];dataset=data[chain['dataset']];dev=dataset['dev'];texts=[normalize_text(r['text']) for r in dev];gold=np.asarray([r['gold_label'] for r in dev]);labels=dataset['manifest']['label_vocab'];ids=np.asarray([r['sample_id'] for r in dev]);history=[]
        for slot in range(3):
            with (directory/f'f{slot}.pkl').open('rb') as stream:bundle=pickle.load(stream)
            begin=time.perf_counter();scores,predicted=probabilities(bundle['classifier'],bundle['vectorizer'].transform(texts),labels);elapsed=time.perf_counter()-begin
            history.append(predicted);chain['versions'][slot].update(history_seconds=elapsed,dev_accuracy=float(np.mean(predicted==gold)))
            with (directory/f'f{slot}-history.npz').open('xb') as stream:np.savez_compressed(stream,sample_ids=ids,predictions=predicted,probabilities=scores)
            if slot==2:reference=scores
            event('HISTORY_PREDICTED',chain_id=chain['chain_id'],slot=f'f{slot}')
        history=np.asarray(history).T;pool=np.flatnonzero(history[:,2]==gold);pool_ids=ids[pool].tolist();pool_gold=gold[pool].tolist()
        begin=time.perf_counter();representation=vectorizer(config['selection_representation']);vectors=representation.fit_transform([texts[i] for i in pool]) if len(pool) else sparse.csr_matrix((0,0));repr_seconds=time.perf_counter()-begin;sparse.save_npz(directory/'pool-vectors.npz',vectors)
        times=[];selections=select_baselines(pool_ids,pool_gold,history[pool],reference[pool],vectors,labels,config['budgets'],config['selection_seeds'],timings=times)
        hgc,groups=select_hgc(dev,history,pool.tolist(),vectors,config['budgets'],config['hgc']);risk,risk_times=risk_top(dev,history,pool.tolist(),config['budgets'],config['hgc']);selections+=hgc+risk
        validate_selection_matrix(selections,config,len(pool))
        primary=[config['primary_budget']];primary_times=[];probe=select_baselines(pool_ids,pool_gold,history[pool],reference[pool],vectors,labels,primary,config['selection_seeds'],timings=primary_times)
        hprobe,hcost=select_hgc(dev,history,pool.tolist(),vectors,primary,config['hgc']);rprobe,rcost=risk_top(dev,history,pool.tolist(),primary,config['hgc'])
        if probe+hprobe+rprobe!=[s for s in selections if s['budget']==primary[0]]:raise ValueError('PRIMARY_COST_PROBE_CHANGED_SELECTION')
        begin=time.perf_counter()
        if len(pool):bundle['classifier'].predict_proba(bundle['vectorizer'].transform([texts[i] for i in pool]))
        score_rebuild=time.perf_counter()-begin
        write_json(directory/'selections.json',dict(scope='DEV_SELECTOR_CURRENT_CORRECT',pool_indices_in_dev=pool.tolist(),pool_ids=pool_ids,pool_gold=pool_gold,history=history[pool].tolist(),selections=selections))
        write_json(directory/'hgc-diagnostics.json',groups);write_json(directory/'pretarget-costs.json',dict(selection_representation_seconds=repr_seconds,all_budget_baselines=times,primary_budget_baselines=primary_times,primary_budget_hgc=hcost,primary_budget_risk_top=rcost,reference_score_rebuild_seconds=score_rebuild))
        chain.update(dev_count=len(dev),pool_count=len(pool),pool_label_count=len(set(pool_gold)),selection_cells=len(selections),hgc_group_count=len(groups['groups']),hgc_fallback=groups['fallback']);write_json(directory/'history-summary.json',chain);event('CHAIN_SUITES_READY',chain_id=chain['chain_id'],pool_count=len(pool),cells=len(selections))
    files={str(p.relative_to(output)):file_hash(p) for p in sorted(output.rglob('*')) if p.is_file() and p.name!='events.jsonl'}
    write_json(output/'matrix-freeze.json',dict(schema_version='feasibility-matrix-v1',purpose=config['purpose'],config_sha256=digest(config),chain_ids=[c['chain_id'] for c in chains],cell_count=sum(c['selection_cells'] for c in chains),files=files,target_predictions_generated=False));event('ALL_SUITES_FROZEN',cell_count=sum(c['selection_cells'] for c in chains),freeze_sha256=file_hash(output/'matrix-freeze.json'));verify_freeze(output)
    cells,costs,diagnostics=[],[],{}
    for chain in chains:
        directory=output/'chains'/chain['chain_id'];dev=data[chain['dataset']]['dev'];texts=[normalize_text(r['text']) for r in dev];gold=np.asarray([r['gold_label'] for r in dev]);ids=np.asarray([r['sample_id'] for r in dev]);labels=data[chain['dataset']]['manifest']['label_vocab'];selected=json.loads((directory/'selections.json').read_text());pool=np.asarray(selected['pool_indices_in_dev'],dtype=int)
        with (directory/'f3.pkl').open('rb') as stream:bundle=pickle.load(stream)
        _,target=probabilities(bundle['classifier'],bundle['vectorizer'].transform(texts),labels)
        with (directory/'f3-target.npz').open('xb') as stream:np.savez_compressed(stream,sample_ids=ids,predictions=target)
        computed=evaluate_cells(selected['pool_gold'],selected['history'],target[pool],selected['selections'])
        for cell in computed:cell.update(chain_id=chain['chain_id'],family=chain['family'],dataset=chain['dataset'])
        cells+=computed;chain.update(future_flip_count=computed[0]['future_flip_count'],historically_unseen_flips=computed[0]['historically_unseen']['denominator'],repaired_then_recurred_flips=computed[0]['repaired_then_recurred']['denominator'],target_dev_accuracy=float(np.mean(target==gold)))
        full_history=np.asarray([np.load(directory/f'f{s}-history.npz',allow_pickle=False)['predictions'] for s in range(3)]).T;reference=np.load(directory/'f2-history.npz',allow_pickle=False)['probabilities'];groups=json.loads((directory/'hgc-diagnostics.json').read_text())
        diagnostic=analyze_history_signal(dev,full_history,pool.tolist(),reference,groups['groups'],target,context='PRESPECIFIED_EXTERNAL' if chain['dataset']=='clinc' else 'PRESPECIFIED_OLD_DEV_NEW_MODEL');diagnostics[chain['chain_id']]=diagnostic;write_json(directory/'posttarget-diagnostics.json',diagnostic);event('TARGET_EVALUATED',chain_id=chain['chain_id'],future_flips=chain['future_flip_count'])
        pre=json.loads((directory/'pretarget-costs.json').read_text());full=benchmark_predict(bundle,[texts[i] for i in pool],target[pool]);raw=dict(full_pool=full,suites=[])
        for suite in selected['selections']:
            if suite['budget']!=config['primary_budget']:continue
            indices=pool[np.asarray(suite['indices'],dtype=int)];bench=benchmark_predict(bundle,[texts[i] for i in indices],target[indices]);method=suite['method']
            shared=0.0
            if method=='hgc':selection_seconds=pre['primary_budget_hgc']['total_seconds']
            elif method=='risk-top':selection_seconds=pre['primary_budget_risk_top']['total_seconds']
            else:
                selection_seconds=next(t['selection_seconds'] for t in pre['primary_budget_baselines'] if t['method']==method and t['seed']==suite['seed']);shared=next(t['selection_seconds'] for t in pre['primary_budget_baselines'] if t['method']=='__shared_validation__');selection_seconds+=shared
            representation_seconds=pre['selection_representation_seconds'] if method in {'hgc','kcenter','facility'} else 0.0;total=selection_seconds+representation_seconds+bench['median_seconds']
            costs.append(dict(chain_id=chain['chain_id'],dataset=chain['dataset'],family=chain['family'],method=method,seed=suite['seed'],budget=suite['budget'],selection_seconds=selection_seconds,shared_validation_seconds=shared,representation_seconds=representation_seconds,selected_inference_seconds=bench['median_seconds'],full_pool_inference_seconds=full['median_seconds'],deployment_seconds_cached_history=total,deployment_cost_ratio=total/full['median_seconds'],reference_score_rebuild_seconds_if_uncached=pre['reference_score_rebuild_seconds'] if method.startswith('ref-') else 0.0))
            raw['suites'].append(dict(method=method,seed=suite['seed'],budget=suite['budget'],**bench))
        write_json(directory/'target-costs.json',raw);event('TARGET_COST_MEASURED',chain_id=chain['chain_id'],suite_count=len(raw['suites']))
    write_json(output/'evaluation-cells.json',cells);write_json(output/'deployment-costs.json',costs);write_json(output/'history-diagnostics.json',diagnostics)
    aggregates=aggregate_cells(cells);screens=external_screens(config,chains,aggregates,diagnostics,costs)
    report=dict(schema_version='feasibility-closeout-natural-v1',run_id=prereg['run_id'],purpose=config['purpose'],config_sha256=digest(config),freeze_sha256=file_hash(output/'matrix-freeze.json'),chains=chains,baseline_aggregates=aggregates,screens=screens,wall_seconds=time.perf_counter()-started,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,environment=dict(python=platform.python_version(),platform=platform.platform(),cpu_threads=config['cpu_threads']),formal_test_model_input_count=0,hgc_config_changed=False,formal_evaluation=False,limitations=config['limitations'])
    write_json(output/'report.json',report);event('CLOSEOUT_NATURAL_COMPLETE',screens=screens,wall_seconds=round(report['wall_seconds'],3));return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();config=json.loads(args.config.read_text())
    with threadpool_limits(limits=config['cpu_threads']):run(args.config,args.output)


if __name__=='__main__':main()
