"""Hand-check the fixed closeout's scope, fallback and decision boundaries."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from preflight.feasibility import external_screens, risk_top, run
from preflight.round2 import validate_selection_matrix


def configuration():
    return json.loads((Path(__file__).parents[1]/'configs/feasibility-closeout-v1.json').read_text())


def fixture_screen():
    config=configuration();chains=[];aggregates=[];diagnostics={};costs=[]
    for family in config['external_families']:
        for seed in [1,2]:
            name=family+str(seed);chains.append(dict(chain_id=name,dataset='clinc',family=family,future_flip_count=25))
            for method,recall in [('hgc',.7 if family=='sgd-data-growth' else .59),('ref-margin',.6),('risk-top',.65),('random',.15),('facility',.20)]:
                aggregates.append(dict(chain_id=name,method=method,budget=100,mean_recall=recall))
            diagnostics[name]=dict(risk_top=dict(roc_auc=.7),incremental_over_margin_top100=dict(risk_only_detected=1))
            costs.append(dict(dataset='clinc',chain_id=name,method='hgc',deployment_cost_ratio=.7))
    return config,chains,aggregates,diagnostics,costs


def test_three_recommendations_are_mechanical_and_conditional():
    args=fixture_screen()
    result=external_screens(*args)
    assert result['recommendation']=='CONTINUE_HGC_CONDITIONALLY'
    assert result['statistical_superiority_established'] is False
    assert result['thesis_approval_established'] is False
    args[-1][0]['deployment_cost_ratio']=2
    assert external_screens(*args)['recommendation']=='REDIRECT_TO_HISTORY_MECHANISM'
    for d in args[3].values():d['risk_top']['roc_auc']=.5
    assert external_screens(*args)['recommendation']=='NO_GO_CURRENT_HGC_METHOD'


def test_low_events_are_not_silently_removed_or_pooled_with_old_massive():
    args=fixture_screen();args[1][0]['future_flip_count']=19
    args[1].append(dict(chain_id='old',dataset='massive',family='sgd-data-growth',future_flip_count=200))
    result=external_screens(*args)
    assert result['adequate_natural_event_support'] is False
    assert result['recommendation']=='NO_GO_CURRENT_HGC_METHOD'
    assert result['external_families']['sgd-data-growth']['chain_count']==2


def test_all_natural_cells_require_every_seed_and_budget():
    config=configuration();seeded={'random','stratified','past-flip','kcenter'}
    rows=[dict(method=m,seed=s,budget=b,indices=[0]) for m in config['methods'] for s in (config['selection_seeds'] if m in seeded else [None]) for b in config['budgets']]
    assert len(rows)==348
    validate_selection_matrix(rows,config,1)
    with pytest.raises(ValueError,match='INCOMPLETE_OR_DUPLICATE'):validate_selection_matrix(rows[:-1],config,1)


def test_static_risk_uses_full_D_opportunities_then_only_selects_P():
    config=configuration()['hgc']
    rows=[dict(sample_id=f'{i:03}',text='do not play music' if i<20 else 'play music',gold_label='A') for i in range(100)]
    history=np.array([['A','B','A']]*4+[['B','A','B']]*4+[['A','A','A']]*12+[['A','A','A']]*72+[['B','B','B']]*8)
    pool=np.flatnonzero(history[:,2]=='A').tolist()
    selected,timing=risk_top(rows,history,pool,[10,100],config)
    assert len(selected[0]['indices'])==10 and len(selected[1]['indices'])==len(pool)
    assert all(pool[i]<20 for i in selected[0]['indices'])
    assert selected[0]['indices']==selected[1]['indices'][:10]
    assert timing['total_seconds']>=timing['risk_build_seconds']>=0
    with pytest.raises(ValueError,match='HISTORY_OR_POOL_MISMATCH'):risk_top(rows,history,pool[:-1],[10],config)
    with pytest.raises(ValueError,match='HISTORY_OR_POOL_MISMATCH'):risk_top(rows,np.array([]),[],[10],config)


def test_hgc_configuration_cannot_be_changed_by_the_closeout(tmp_path):
    config=configuration();config['hgc']['lambda']=.75
    path=tmp_path/'config.json';path.write_text(json.dumps(config))
    with pytest.raises(ValueError,match='FIXED_CLOSEOUT'):run(path,tmp_path/'output')
    assert not (tmp_path/'output').exists()
