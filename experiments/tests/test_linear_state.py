"""Linear label reuse is distinct from probability contracts and training metadata."""

from copy import deepcopy
import json

import numpy as np
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, SGDClassifier

from preflight.linear_state import audit_linear_nodes, linear_identity


@pytest.fixture
def pipelines():
    text = ['打开订单', '关闭订单', '播放音乐', '停止音乐', '查询天气', '明天天气']
    labels = ['订单', '订单', '音乐', '音乐', '天气', '天气']
    vectorizer = TfidfVectorizer(analyzer='char', ngram_range=(1, 2), lowercase=False)
    matrix = vectorizer.fit_transform(text)
    lr = LogisticRegression(max_iter=200).fit(matrix, labels)
    sgd = SGDClassifier(loss='log_loss', max_iter=3, tol=None, average=False, random_state=42).fit(matrix, labels)
    return vectorizer, lr, sgd


def test_same_coefficients_cross_estimator_block_label_reuse_but_not_probability_contract(pipelines):
    vectorizer, lr, sgd = deepcopy(pipelines)
    sgd.coef_ = lr.coef_.copy();sgd.intercept_ = lr.intercept_.copy()
    first, second = linear_identity(vectorizer, lr), linear_identity(vectorizer, sgd)
    assert first['label_state_sha256'] == second['label_state_sha256']
    assert first['probability_state_sha256'] != second['probability_state_sha256']
    probe = vectorizer.transform(['订单打开', '播放音乐', '明天天气'])
    assert np.array_equal(lr.predict(probe), sgd.predict(probe))
    assert not np.allclose(lr.predict_proba(probe), sgd.predict_proba(probe))
    assert first['components']['probability_link'] == 'multiclass-softmax'
    assert second['components']['probability_link'] == 'multiclass-normalized-ovr-sigmoid'
    assert set(first['components']['vocabulary']) == {'size', 'mapping_sha256'}
    assert json.loads(json.dumps(first, allow_nan=False)) == first


def test_training_metadata_and_sgd_hyperparameters_are_not_inference_state(pipelines):
    vectorizer, lr, sgd = deepcopy(pipelines)
    before = linear_identity(vectorizer, sgd)
    sgd.alpha = 9;sgd.max_iter = 500;sgd.random_state = 123;sgd.n_iter_ = 900
    sgd.user_metadata = object();sgd.training_ids = ['anything']
    vectorizer.min_df = 10;vectorizer.max_df = .1;vectorizer.max_features = 1
    assert linear_identity(vectorizer, sgd) == before
    before_lr = linear_identity(vectorizer, lr)
    lr.C = 999;lr.max_iter = 1;lr.n_iter_ = np.asarray([1000]);lr.solver = 'sag'
    assert linear_identity(vectorizer, lr) == before_lr


@pytest.mark.parametrize('change', [
    lambda v,c: setattr(c,'coef_',c.coef_+.1),
    lambda v,c: setattr(c,'intercept_',c.intercept_+.1),
    lambda v,c: setattr(c,'classes_',np.asarray(['changed',*c.classes_[1:]])),
    lambda v,c: setattr(v,'idf_',v.idf_+.1),
    lambda v,c: setattr(v._tfidf,'norm','l1'),
    lambda v,c: setattr(v,'lowercase',not v.lowercase),
])
def test_changed_inference_state_changes_both_hashes(pipelines, change):
    vectorizer, _, sgd = deepcopy(pipelines)
    before = linear_identity(vectorizer, sgd)
    change(vectorizer, sgd)
    after = linear_identity(vectorizer, sgd)
    assert before['label_state_sha256'] != after['label_state_sha256']
    assert before['probability_state_sha256'] != after['probability_state_sha256']


def test_changed_vocabulary_mapping_changes_state_without_publishing_words(pipelines):
    vectorizer, _, sgd = deepcopy(pipelines)
    before = linear_identity(vectorizer, sgd)
    left,right = list(vectorizer.vocabulary_)[:2]
    vectorizer.vocabulary_[left],vectorizer.vocabulary_[right] = vectorizer.vocabulary_[right],vectorizer.vocabulary_[left]
    after = linear_identity(vectorizer, sgd)
    assert before['label_state_sha256'] != after['label_state_sha256']
    assert left not in json.dumps(after['components']['vocabulary'],ensure_ascii=False)


def test_never_predicts_or_transforms(pipelines, monkeypatch):
    vectorizer, lr, sgd = pipelines
    def forbidden(*args, **kwargs):
        raise AssertionError('inference is forbidden')
    monkeypatch.setattr(TfidfVectorizer,'transform',forbidden)
    for cls in [LogisticRegression, SGDClassifier]:
        monkeypatch.setattr(cls,'predict',forbidden)
        monkeypatch.setattr(cls,'predict_proba',forbidden)
    assert linear_identity(vectorizer,lr)['label_state_sha256']
    assert linear_identity(vectorizer,sgd)['label_state_sha256']


def test_binary_contract_is_sigmoid_for_both_estimator_types():
    vectorizer = TfidfVectorizer(analyzer='char', ngram_range=(1,2))
    matrix = vectorizer.fit_transform(['甲甲','甲乙','乙甲','乙乙'])
    lr = LogisticRegression().fit(matrix,['甲','甲','乙','乙'])
    sgd = SGDClassifier(loss='log_loss',tol=None,max_iter=3,average=False).fit(matrix,['甲','甲','乙','乙'])
    sgd.coef_ = lr.coef_.copy();sgd.intercept_ = lr.intercept_.copy()
    assert linear_identity(vectorizer,lr) == linear_identity(vectorizer,sgd)


def distinct(pipelines, delta):
    vectorizer, _, model = deepcopy(pipelines)
    model.intercept_[0] += delta
    return linear_identity(vectorizer, model)


def nodes(pipelines):
    return [dict(chain_id=chain,slot=f'f{slot}',identity=distinct(pipelines,10*index+slot)) for index,chain in enumerate(['a','b']) for slot in range(4)]


def test_complete_unique_matrix_and_label_collision_detection(pipelines):
    matrix = nodes(pipelines)
    first = audit_linear_nodes(matrix)
    assert first['passed'] and first['node_count'] == 8
    assert first['statistical_independence_established'] is False
    matrix[7]['identity'] = deepcopy(matrix[0]['identity'])
    blocked = audit_linear_nodes(matrix)
    assert blocked['passed'] is False
    assert len(blocked['target_history_collisions']) == 1
    assert blocked['target_history_collisions'][0]['target']['chain_id'] == 'b'
    matrix[7]['identity'] = deepcopy(matrix[3]['identity'])
    blocked = audit_linear_nodes(matrix)
    assert len(blocked['target_target_collisions']) == 1
    assert blocked['passed'] is False


def test_cross_estimator_equal_label_hash_is_a_collision(pipelines):
    vectorizer, lr, sgd = deepcopy(pipelines)
    matrix = nodes(pipelines)
    matrix[0]['identity'] = linear_identity(vectorizer,lr)
    sgd.coef_=lr.coef_.copy();sgd.intercept_=lr.intercept_.copy()
    matrix[7]['identity'] = linear_identity(vectorizer,sgd)
    assert matrix[0]['identity']['probability_state_sha256'] != matrix[7]['identity']['probability_state_sha256']
    assert audit_linear_nodes(matrix)['passed'] is False


def test_history_sharing_reported_without_blocking_and_order_independent(pipelines):
    matrix = nodes(pipelines)
    matrix[4]['identity'] = deepcopy(matrix[0]['identity'])
    result = audit_linear_nodes(matrix)
    assert result['passed'] and len(result['history_history_collisions']) == 1
    assert result == audit_linear_nodes(matrix[::-1])


@pytest.mark.parametrize('change,reason', [
    (lambda x: x.pop(),'INCOMPLETE_LINEAR_CHAIN_IDENTITIES'),
    (lambda x: x.append(deepcopy(x[0])),'DUPLICATE_LINEAR_MODEL_NODE'),
    (lambda x: x[0].update(slot='f4'),'INVALID_LINEAR_MODEL_SLOT'),
    (lambda x: x[0]['identity'].update(label_state_sha256='0'*64),'LINEAR_STATE_HASH_MISMATCH'),
])
def test_invalid_matrix_rejected(pipelines, change, reason):
    matrix = nodes(pipelines);change(matrix)
    with pytest.raises(ValueError,match=reason):audit_linear_nodes(matrix)


@pytest.mark.parametrize('average,loss', [(True,'log_loss'),(10,'log_loss'),(False,'hinge')])
def test_unsupported_sgd_contract_rejected(pipelines, average, loss):
    vectorizer,_,model = deepcopy(pipelines)
    model.average=average;model.loss=loss
    with pytest.raises(ValueError,match='UNSUPPORTED_SGD_INFERENCE_CONTRACT'):
        linear_identity(vectorizer,model)


def test_opaque_estimators_subclasses_and_instance_overrides_rejected(pipelines):
    vectorizer,_,model = deepcopy(pipelines)
    class CustomSGD(SGDClassifier):
        pass
    with pytest.raises(ValueError,match='UNSUPPORTED_LINEAR_ESTIMATOR_TYPE'):
        linear_identity(vectorizer,CustomSGD(loss='log_loss'))
    with pytest.raises(ValueError,match='UNSUPPORTED_LINEAR_ESTIMATOR_TYPE'):
        linear_identity(vectorizer,object())
    model.predict = lambda _: []
    with pytest.raises(ValueError,match='OVERRIDDEN_LINEAR_INFERENCE_METHOD'):
        linear_identity(vectorizer,model)


def test_empty_matrix_cannot_vacuously_pass():
    with pytest.raises(ValueError,match='EMPTY_LINEAR_IDENTITY_MATRIX'):
        audit_linear_nodes([])
