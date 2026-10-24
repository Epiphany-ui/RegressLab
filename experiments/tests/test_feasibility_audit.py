"""Hand-computable closeout completeness and cost audit boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import pickle

import numpy as np
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier

from preflight.runner import file_hash
from preflight.verify_feasibility import cost_rows, expected_matrix, trusted_bundle


@pytest.fixture
def config():
    return json.loads((Path(__file__).parents[1]/'configs/feasibility-closeout-v1.json').read_text())


def test_complete_closeout_counts_and_frozen_target_exclusion(config):
    chains, keys, files = expected_matrix(config)
    assert len(chains) == 6
    assert len(keys) == 348 and len(chains)*len(keys) == 2088
    assert len(files) == 86
    assert len(chains)*len(config['methods'])*len(config['budgets']) == 264
    assert len([key for key in keys if key[2]==100])*len(chains) == 522
    assert not any(Path(name).name in {'f3-target.npz','target-costs.json','posttarget-diagnostics.json'} for name in files)
    assert 'data/clinc/dev.json' in files and 'data/massive/dev.json' in files


@pytest.mark.parametrize('change,error', [
    (lambda c:c['methods'].remove('risk-top'),'REGISTERED_METHOD_SET_MISMATCH'),
    (lambda c:c['methods'].append('hgc'),'REGISTERED_METHOD_SET_MISMATCH'),
    (lambda c:c['selection_seeds'].append(0),'INVALID_SELECTION_SEEDS'),
    (lambda c:c.update(primary_budget=50),'PRIMARY_BUDGET_100_REQUIRED'),
    (lambda c:c['profiles'].append(deepcopy(c['profiles'][0])),'DUPLICATE_PROFILE'),
    (lambda c:c['profiles'][0].update(epochs=[1,2,3]),'FOUR_VERSION_RECIPE_REQUIRED'),
    (lambda c:c['profiles'][0].update(fractions=[0,.6,.8,1]),'INVALID_TRAIN_FRACTIONS'),
    (lambda c:c['profiles'][1].update(seeds=[501]),'EXTERNAL_SEED_COUNT_MISMATCH'),
])
def test_incomplete_or_changed_registry_is_not_a_valid_matrix(config,change,error):
    change(config)
    with pytest.raises(ValueError,match=error):expected_matrix(config)


def costs_fixture(config):
    config=deepcopy(config);config['selection_seeds']=[0]
    _,keys,_=expected_matrix(config)
    selections=[dict(method=m,seed=s,budget=b,indices=list(range(min(b,200)))) for m,s,b in sorted(keys,key=str)]
    baseline_methods={(m,s) for m,s,_ in keys if m not in {'hgc','risk-top'}}
    timings=[dict(method=m,seed=s,selection_seconds=.02,max_budget=100,includes_shared_representation=False) for m,s in sorted(baseline_methods,key=str)]
    timings.append(dict(method='__shared_validation__',seed=None,selection_seconds=.01,max_budget=100,includes_shared_representation=False))
    pre=dict(all_budget_baselines=[dict(row,max_budget=200) for row in timings],primary_budget_baselines=timings,selection_representation_seconds=.04,reference_score_rebuild_seconds=.03,primary_budget_hgc=dict(total_seconds=.1),primary_budget_risk_top=dict(risk_build_seconds=.07,total_seconds=.08))
    def block(count,seconds):
        return dict(repetitions=5,wall_seconds=[seconds]*5,median_seconds=seconds,sample_count=count,scope='TEXT_TRANSFORM_AND_PREDICT')
    target=dict(full_pool=block(200,.2),suites=[dict(method=s['method'],seed=s['seed'],budget=100,**block(100,.05)) for s in selections if s['budget']==100])
    chain=dict(chain_id='clinc-example-seed1',dataset='clinc',family='example',pool_count=200)
    return config,chain,selections,pre,target


def test_cost_accounts_hgc_and_risk_top_without_false_representation_charge(config):
    args=costs_fixture(config)
    result={row['method']:row for row in cost_rows(*args)}
    assert len(result)==11
    assert result['ref-margin']['selection_seconds']==pytest.approx(.03)
    assert result['ref-margin']['deployment_cost_ratio']==pytest.approx(.4)
    assert result['facility']['deployment_cost_ratio']==pytest.approx(.6)
    assert result['hgc']['selection_seconds']==pytest.approx(.1)
    assert result['hgc']['shared_validation_seconds']==0
    assert result['hgc']['deployment_cost_ratio']==pytest.approx(.95)
    assert result['risk-top']['selection_seconds']==pytest.approx(.08)
    assert result['risk-top']['representation_seconds']==0
    assert result['risk-top']['deployment_cost_ratio']==pytest.approx(.65)
    assert result['ref-margin']['reference_score_rebuild_seconds_if_uncached']==.03


@pytest.mark.parametrize('mutation,error', [
    (lambda args:args[-1]['suites'].pop(),'TARGET_COST_SUITE_SET_MISMATCH'),
    (lambda args:args[-2]['primary_budget_baselines'].pop(),'SELECTION_TIMING_SET_MISMATCH'),
    (lambda args:args[-1]['full_pool'].update(median_seconds=999),'BENCHMARK_MEDIAN_MISMATCH'),
    (lambda args:args[-2]['primary_budget_risk_top'].update(total_seconds=.01),'RISK_TOP_TIMING_TOTAL_MISMATCH'),
])
def test_cost_audit_rejects_missing_suite_seed_shared_validation_and_false_medians(config,mutation,error):
    args=costs_fixture(config);mutation(args)
    with pytest.raises(ValueError,match=error):cost_rows(*args)


def test_model_hash_checked_before_any_pickle_deserialization(tmp_path,monkeypatch):
    path=tmp_path/'model.pkl';path.write_bytes(b'not a pickle')
    def forbidden(*args,**kwargs):raise AssertionError('hash mismatch must not deserialize')
    monkeypatch.setattr('preflight.verify_feasibility.pickle.load',forbidden)
    with pytest.raises(ValueError,match='MODEL_FILE_HASH_MISMATCH'):
        trusted_bundle(path,'0'*64)


def test_trusted_sgd_bundle_recomputes_compact_linear_identity(tmp_path):
    v=TfidfVectorizer(analyzer='char',ngram_range=(1,2));x=v.fit_transform(['订单开','订单关','天气晴','天气雨'])
    c=SGDClassifier(loss='log_loss',average=False,tol=None,max_iter=2,random_state=1).fit(x,['订单','订单','天气','天气'])
    path=tmp_path/'model.pkl'
    with path.open('wb') as stream:pickle.dump(dict(vectorizer=v,classifier=c),stream)
    bundle,identity=trusted_bundle(path,file_hash(path))
    assert type(bundle['classifier']) is SGDClassifier
    assert len(identity['label_state_sha256'])==64
    assert set(identity['components']['vocabulary'])=={'size','mapping_sha256'}
