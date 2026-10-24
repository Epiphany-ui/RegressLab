"""Inference-state identity is not provenance, sampled behavior, or independence."""

from copy import deepcopy
import json

import numpy as np
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from preflight.identity import audit_identities, semantic_identity


@pytest.fixture
def pipeline():
    texts = ["订单打开", "订单关闭", "播放音乐", "停止音乐", "查询天气", "明天天气"]
    labels = ["order", "order", "music", "music", "weather", "weather"]
    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(1, 2), lowercase=False)
    matrix = vectorizer.fit_transform(texts)
    classifier = LogisticRegression(max_iter=200).fit(matrix, labels)
    return vectorizer, classifier


def identity(pipeline):
    return semantic_identity(*pipeline)


def distinct_identity(pipeline, delta):
    vectorizer, classifier = deepcopy(pipeline)
    classifier.intercept_[0] += delta
    return semantic_identity(vectorizer, classifier)


def matrix_nodes(pipeline):
    return [
        {"chain_id": chain, "slot": f"f{slot}", "identity": distinct_identity(pipeline, 1 + 4 * index + slot)}
        for index, chain in enumerate(["chain-a", "chain-b"])
        for slot in range(4)
    ]


def test_json_safe_identity_excludes_training_and_pickle_provenance(pipeline):
    before = identity(pipeline)
    vectorizer, classifier = deepcopy(pipeline)
    classifier.C = 999
    classifier.max_iter = 17
    classifier.random_state = 42
    classifier.training_ids = ["different", "source"]
    classifier.user_metadata = object()
    classifier.n_iter_ = np.asarray([999])
    vectorizer.min_df = 7
    vectorizer.max_df = .1
    vectorizer.max_features = 1
    vectorizer.smooth_idf = not vectorizer.smooth_idf
    assert semantic_identity(vectorizer, classifier) == before
    assert json.loads(json.dumps(before, allow_nan=False)) == before
    assert len(before["inference_sha256"]) == 64
    assert "C" not in before["components"]


def test_no_prediction_or_file_operation_is_needed(pipeline, monkeypatch):
    # Class methods are patched solely to prove identity does not invoke them.
    def forbidden(*_args, **_kwargs):
        raise AssertionError("unexpected inference")

    monkeypatch.setattr(TfidfVectorizer, "transform", forbidden)
    monkeypatch.setattr(LogisticRegression, "predict", forbidden)
    monkeypatch.setattr(LogisticRegression, "predict_proba", forbidden)
    assert identity(pipeline)["inference_sha256"]


@pytest.mark.parametrize("change", [
    lambda v, c: setattr(c, "coef_", c.coef_ + .01),
    lambda v, c: setattr(c, "intercept_", c.intercept_ + .01),
    lambda v, c: setattr(c, "classes_", np.asarray(["changed", *c.classes_[1:]])),
    lambda v, c: setattr(v, "idf_", v.idf_ + .01),
    lambda v, c: setattr(v, "lowercase", not v.lowercase),
    lambda v, c: setattr(v, "binary", not v.binary),
    lambda v, c: setattr(v, "ngram_range", (1, 3)),
    lambda v, c: setattr(v._tfidf, "norm", "l1"),
    lambda v, c: setattr(v._tfidf, "sublinear_tf", True),
    lambda v, c: setattr(v, "dtype", np.float32),
])
def test_changed_inference_state_changes_hash(pipeline, change):
    before = identity(pipeline)["inference_sha256"]
    modified = deepcopy(pipeline)
    change(*modified)
    assert identity(modified)["inference_sha256"] != before


def test_vocabulary_order_is_irrelevant_but_token_index_mapping_matters(pipeline):
    before = identity(pipeline)
    vectorizer, classifier = deepcopy(pipeline)
    vectorizer.vocabulary_ = dict(reversed(list(vectorizer.vocabulary_.items())))
    assert semantic_identity(vectorizer, classifier) == before
    tokens = list(vectorizer.vocabulary_)
    left, right = tokens[:2]
    vectorizer.vocabulary_[left], vectorizer.vocabulary_[right] = vectorizer.vocabulary_[right], vectorizer.vocabulary_[left]
    assert semantic_identity(vectorizer, classifier)["inference_sha256"] != before["inference_sha256"]


def test_array_endianness_layout_and_exact_dtype_values_are_normalized(pipeline):
    vectorizer, classifier = deepcopy(pipeline)
    # Exactly representable values avoid conflating dtype normalization with
    # real precision loss in float32 conversion.
    classifier.coef_ = np.arange(classifier.coef_.size).reshape(classifier.coef_.shape).astype(np.float32)
    classifier.intercept_ = np.asarray([0, 1, 2], dtype=np.float32)
    before = semantic_identity(vectorizer, classifier)
    classifier.coef_ = np.asfortranarray(classifier.coef_.astype(">f8"))
    classifier.intercept_ = classifier.intercept_.astype(">f8")
    classifier.intercept_[0] = -0.0
    assert semantic_identity(vectorizer, classifier) == before


def test_effective_fitted_transformer_settings_are_used(pipeline):
    vectorizer, classifier = deepcopy(pipeline)
    before = semantic_identity(vectorizer, classifier)
    # sklearn's transform uses fitted _tfidf, not these public fit parameters.
    vectorizer.set_params(norm="l1", sublinear_tf=True, use_idf=False)
    assert semantic_identity(vectorizer, classifier) == before
    vectorizer._tfidf.norm = "l1"
    assert semantic_identity(vectorizer, classifier) != before


def test_unused_word_settings_do_not_distinguish_char_inference(pipeline):
    vectorizer, classifier = deepcopy(pipeline)
    before = semantic_identity(vectorizer, classifier)
    vectorizer.stop_words = ["ignored"]
    vectorizer.token_pattern = "different but ignored"
    assert semantic_identity(vectorizer, classifier) == before


def test_word_stop_word_order_is_normalized_and_effective_words_change_hash():
    vectorizer = TfidfVectorizer(stop_words=["the", "a"])
    matrix = vectorizer.fit_transform(["the red fox", "a blue bird", "red bird", "blue fox"])
    classifier = LogisticRegression().fit(matrix, ["A", "B", "A", "B"])
    before = semantic_identity(vectorizer, classifier)
    vectorizer.stop_words = ["a", "the", "a"]
    assert semantic_identity(vectorizer, classifier) == before
    vectorizer.stop_words = ["the"]
    assert semantic_identity(vectorizer, classifier) != before


def test_idf_disabled_is_explicit_and_binary_classifier_supported():
    vectorizer = TfidfVectorizer(use_idf=False)
    matrix = vectorizer.fit_transform(["red fox", "blue bird", "red bird", "blue fox"])
    classifier = LogisticRegression().fit(matrix, ["A", "B", "A", "B"])
    result = semantic_identity(vectorizer, classifier)
    assert result["components"]["idf"] is None
    assert result["components"]["probability_link"] == "binary-sigmoid"


@pytest.mark.parametrize("change,code", [
    (lambda v, c: setattr(v, "analyzer", lambda text: list(text)), "CUSTOM_ANALYZER"),
    (lambda v, c: setattr(v, "preprocessor", lambda text: text), "CUSTOM_TEXT_CALLABLE"),
    (lambda v, c: setattr(v, "strip_accents", object()), "CUSTOM_ACCENT"),
    (lambda v, c: setattr(v, "stop_words", [object()]), "OPAQUE_STOP_WORD"),
    (lambda v, c: setattr(v, "token_pattern", object()), "INVALID_TOKEN_PATTERN"),
    (lambda v, c: setattr(c, "coef_", c.coef_.astype(object)), "INVALID_COEF_ARRAY"),
    (lambda v, c: setattr(c, "coef_", c.coef_ * np.nan), "NONFINITE_COEF_ARRAY"),
    (lambda v, c: setattr(c, "intercept_", np.asarray([np.inf] * 3)), "NONFINITE_INTERCEPT"),
    (lambda v, c: setattr(c, "coef_", c.coef_[:, :-1]), "INVALID_COEF_SHAPE"),
    (lambda v, c: v.vocabulary_.update({"invalid": 9999}), "INVALID_VOCABULARY_INDICES"),
    (lambda v, c: setattr(c, "predict", lambda x: x), "OVERRIDDEN_INFERENCE_METHOD"),
])
def test_opaque_nonfinite_or_inconsistent_state_fails_closed(pipeline, change, code):
    change(*pipeline)
    with pytest.raises(ValueError, match=code):
        identity(pipeline)


def test_unknown_and_unfitted_estimators_are_rejected(pipeline):
    with pytest.raises(ValueError, match="UNSUPPORTED_ESTIMATOR"):
        semantic_identity(object(), pipeline[1])
    with pytest.raises(ValueError, match="UNFITTED_ESTIMATOR"):
        semantic_identity(TfidfVectorizer(), LogisticRegression())


def test_no_collisions_passes_without_claiming_independence(pipeline):
    nodes = matrix_nodes(pipeline)
    result = audit_identities(nodes)
    assert result["passed"] is True
    assert result["node_count"] == result["unique_inference_count"] == 8
    assert result["chain_count"] == result["target_count"] == 2
    assert result["statistical_independence_established"] is False
    assert result == audit_identities(list(reversed(nodes)))
    assert json.loads(json.dumps(result)) == result


def test_cross_chain_target_history_collision_blocks(pipeline):
    nodes = matrix_nodes(pipeline)
    nodes[3]["identity"] = deepcopy(nodes[6]["identity"])
    result = audit_identities(nodes)
    assert result["passed"] is False
    assert len(result["target_history_collisions"]) == 1
    collision = result["target_history_collisions"][0]
    assert collision["target"]["chain_id"] == "chain-a"
    assert collision["history"]["chain_id"] == "chain-b"
    assert collision["history"]["slot"] == "f2"


def test_same_chain_target_history_collision_also_blocks(pipeline):
    nodes = matrix_nodes(pipeline)
    nodes[3]["identity"] = deepcopy(nodes[0]["identity"])
    result = audit_identities(nodes)
    assert result["passed"] is False
    assert result["target_history_collisions"][0]["history"]["slot"] == "f0"


def test_target_target_collision_blocks(pipeline):
    nodes = matrix_nodes(pipeline)
    nodes[7]["identity"] = deepcopy(nodes[3]["identity"])
    result = audit_identities(nodes)
    assert result["passed"] is False
    assert result["target_history_collisions"] == []
    assert len(result["target_target_collisions"]) == 1


def test_history_history_sharing_is_reported_without_blocking(pipeline):
    nodes = matrix_nodes(pipeline)
    nodes[4]["identity"] = deepcopy(nodes[0]["identity"])
    result = audit_identities(nodes)
    assert result["passed"] is True
    assert len(result["history_history_collisions"]) == 1
    assert result["target_target_collisions"] == result["target_history_collisions"] == []


def test_collision_lists_include_all_pairs(pipeline):
    nodes = matrix_nodes(pipeline)
    for index in [0, 4, 7]:
        nodes[index]["identity"] = deepcopy(nodes[3]["identity"])
    result = audit_identities(nodes)
    assert len(result["target_history_collisions"]) == 4
    assert len(result["target_target_collisions"]) == 1
    assert len(result["history_history_collisions"]) == 1


@pytest.mark.parametrize("mutation,code", [
    (lambda n: n.append(deepcopy(n[0])), "DUPLICATE_MODEL_NODE"),
    (lambda n: n[0].update(slot="future"), "INVALID_MODEL_SLOT"),
    (lambda n: n[0].update(chain_id=""), "INVALID_CHAIN_ID"),
    (lambda n: n[0]["identity"].update(inference_sha256="not-a-hash"), "INVALID_INFERENCE_HASH"),
    (lambda n: n[0]["identity"].update(inference_sha256="0" * 64), "INFERENCE_HASH_MISMATCH"),
    (lambda n: n[0]["identity"]["components"].update(opaque=object()), "OPAQUE_IDENTITY_VALUE"),
    (lambda n: n.pop(), "INCOMPLETE_CHAIN_IDENTITIES"),
])
def test_invalid_or_incomplete_matrix_cannot_pass(pipeline, mutation, code):
    nodes = matrix_nodes(pipeline)
    mutation(nodes)
    with pytest.raises(ValueError, match=code):
        audit_identities(nodes)


def test_empty_matrix_is_rejected():
    with pytest.raises(ValueError, match="EMPTY_IDENTITY_MATRIX"):
        audit_identities([])
