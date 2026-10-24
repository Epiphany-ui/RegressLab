"""Canonical label and probability states for trusted frozen linear pipelines.

No prediction, text transformation, model deserialization or file operation is
performed here. Equal label states block target reuse even across LR/SGD model
types; different states do not establish behavioral or statistical independence.
"""

from collections import defaultdict
import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.utils.validation import check_is_fitted

from .identity import _array, _configuration, _digest, _require

SCHEMA_VERSION = "linear-inference-state-v1"
SLOTS = ("f0", "f1", "f2", "f3")


def _state_payloads(components):
    labels = {key: value for key, value in components.items() if key != "probability_link"}
    return labels, components


def linear_identity(vectorizer, model) -> dict:
    """Separate linear decision-state equality from class-probability equality.

    Only exact sklearn TF-IDF, LogisticRegression and non-averaged log-loss SGD
    types are supported. Vocabulary entries are hashed, not retained in output.
    The decision identity deliberately omits training recipe and estimator type.
    """
    _require(type(vectorizer) is TfidfVectorizer and type(model) in (LogisticRegression, SGDClassifier), "UNSUPPORTED_LINEAR_ESTIMATOR_TYPE")
    _require(not any(name in obj.__dict__ for obj, names in [(vectorizer, ("transform", "build_analyzer", "build_preprocessor", "build_tokenizer", "decode", "get_params", "get_stop_words")), (model, ("predict", "predict_proba", "decision_function", "_predict_proba_lr"))] for name in names), "OVERRIDDEN_LINEAR_INFERENCE_METHOD")
    if type(model) is SGDClassifier:
        _require(model.loss == "log_loss" and type(model.average) is bool and model.average is False, "UNSUPPORTED_SGD_INFERENCE_CONTRACT")
    try:
        check_is_fitted(vectorizer, attributes=["vocabulary_", "_tfidf"])
        check_is_fitted(model, attributes=["classes_", "coef_", "intercept_", "n_features_in_"])
    except (TypeError, ValueError) as exc:
        raise ValueError("UNFITTED_LINEAR_PIPELINE") from exc
    configuration = _configuration(vectorizer)
    vocabulary = vectorizer.vocabulary_
    _require(type(vocabulary) is dict and bool(vocabulary), "INVALID_LINEAR_VOCABULARY")
    _require(all(type(token) is str and token and isinstance(index, (int, np.integer)) and not isinstance(index, (bool, np.bool_)) for token, index in vocabulary.items()), "INVALID_LINEAR_VOCABULARY_ENTRY")
    width = len(vocabulary)
    _require({int(index) for index in vocabulary.values()} == set(range(width)), "INVALID_LINEAR_VOCABULARY_INDICES")
    _require(type(model.classes_) is np.ndarray and model.classes_.ndim == 1 and model.classes_.dtype.kind == "U" and len(model.classes_) >= 2, "INVALID_LINEAR_CLASS_LABELS")
    classes = model.classes_.tolist()
    _require(all(classes) and len(classes) == len(set(classes)), "INVALID_LINEAR_CLASS_LABELS")
    _require(model.n_features_in_ == width, "LINEAR_FEATURE_DIMENSION_MISMATCH")
    rows = 1 if len(classes) == 2 else len(classes)
    if type(model) is LogisticRegression:
        legacy = getattr(model, "multi_class", None)
        _require(legacy not in {"ovr", "multinomial"} and not (len(classes) > 2 and model.solver == "liblinear"), "LEGACY_LINEAR_PROBABILITY_CONTRACT_UNSUPPORTED")
    probability_link = "binary-sigmoid" if rows == 1 else "multiclass-softmax" if type(model) is LogisticRegression else "multiclass-normalized-ovr-sigmoid"
    components = {
        "pipeline": "canonical-tfidf-linear-state-v1", "vectorizer": configuration,
        "vocabulary": {"size": width, "mapping_sha256": _digest([[token, int(vocabulary[token])] for token in sorted(vocabulary, key=lambda value: value.encode("utf-8"))])},
        "idf": _array(vectorizer.idf_, (width,), "LINEAR_IDF") if configuration["use_idf"] else None,
        "classes": classes, "decision_rule": "binary-positive-class1-otherwise-class0" if rows == 1 else "multiclass-argmax-first-class-tie",
        "coef": _array(model.coef_, (rows, width), "LINEAR_COEF"),
        "intercept": _array(model.intercept_, (rows,), "LINEAR_INTERCEPT"),
        "probability_link": probability_link,
    }
    label_payload, probability_payload = _state_payloads(components)
    return {"schema_version": SCHEMA_VERSION, "label_state_sha256": _digest(label_payload), "probability_state_sha256": _digest(probability_payload), "components": components}


def _validated_state(identity):
    _require(type(identity) is dict and set(identity) == {"schema_version", "label_state_sha256", "probability_state_sha256", "components"}, "INVALID_LINEAR_IDENTITY_OBJECT")
    _require(identity["schema_version"] == SCHEMA_VERSION and type(identity["components"]) is dict, "UNSUPPORTED_LINEAR_IDENTITY_SCHEMA")
    components = identity["components"]
    _require(set(components) == {"pipeline", "vectorizer", "vocabulary", "idf", "classes", "decision_rule", "coef", "intercept", "probability_link"} and components["pipeline"] == "canonical-tfidf-linear-state-v1", "INVALID_LINEAR_IDENTITY_COMPONENTS")
    _require(components["probability_link"] in {"binary-sigmoid", "multiclass-softmax", "multiclass-normalized-ovr-sigmoid"}, "INVALID_LINEAR_PROBABILITY_LINK")
    _require(type(components["vocabulary"]) is dict and set(components["vocabulary"]) == {"size", "mapping_sha256"} and type(components["vocabulary"]["size"]) is int and components["vocabulary"]["size"] > 0, "INVALID_LINEAR_VOCABULARY_STATE")
    for value in [identity["label_state_sha256"], identity["probability_state_sha256"], components["vocabulary"]["mapping_sha256"]]:
        _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None, "INVALID_LINEAR_STATE_HASH")
    label_payload, probability_payload = _state_payloads(components)
    _require(_digest(label_payload) == identity["label_state_sha256"] and _digest(probability_payload) == identity["probability_state_sha256"], "LINEAR_STATE_HASH_MISMATCH")
    return identity["label_state_sha256"], identity["probability_state_sha256"]


def audit_linear_nodes(nodes: list[dict]) -> dict:
    """Block equal target/history or target/target label states, not recipes.

    Every supplied chain must contain all four slots. The caller separately
    checks the supplied chain list against the registration and checks previously
    exposed runs. History sharing is reported and does not itself block the gate.
    """
    _require(type(nodes) is list and bool(nodes), "EMPTY_LINEAR_IDENTITY_MATRIX")
    groups, ordered = defaultdict(set), []
    for node in nodes:
        _require(type(node) is dict and set(node) == {"chain_id", "slot", "identity"}, "INVALID_LINEAR_IDENTITY_NODE")
        chain, slot = node["chain_id"], node["slot"]
        _require(type(chain) is str and bool(chain.strip()), "INVALID_LINEAR_CHAIN_ID")
        try:
            chain.encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("INVALID_LINEAR_CHAIN_ID") from exc
        _require(type(slot) is str and slot in SLOTS, "INVALID_LINEAR_MODEL_SLOT")
        _require(slot not in groups[chain], "DUPLICATE_LINEAR_MODEL_NODE")
        groups[chain].add(slot)
        label_sha, probability_sha = _validated_state(node["identity"])
        ordered.append({"chain_id": chain, "slot": slot, "label_state_sha256": label_sha, "probability_state_sha256": probability_sha})
    _require(all(slots == set(SLOTS) for slots in groups.values()), "INCOMPLETE_LINEAR_CHAIN_IDENTITIES")
    ordered.sort(key=lambda node: (node["chain_id"].encode("utf-8"), SLOTS.index(node["slot"])))
    target = [node for node in ordered if node["slot"] == "f3"]
    history = [node for node in ordered if node["slot"] != "f3"]
    target_history = [{"target": future, "history": past} for future in target for past in history if future["label_state_sha256"] == past["label_state_sha256"]]
    def pairs(values):
        return [{"left": left, "right": right} for i, left in enumerate(values) for right in values[i+1:] if left["label_state_sha256"] == right["label_state_sha256"]]
    target_target, history_history = pairs(target), pairs(history)
    return {
        "schema_version": "linear-node-audit-v1", "passed": not target_history and not target_target,
        "node_count": len(ordered), "chain_count": len(groups), "target_count": len(target),
        "unique_label_state_count": len({node["label_state_sha256"] for node in ordered}), "nodes": ordered,
        "target_history_collisions": target_history, "target_target_collisions": target_target,
        "history_history_collisions": history_history,
        "statistical_independence_established": False,
        "limitations": [
            "Equal canonical linear states block reuse across estimator types regardless of training provenance.",
            "No exact-state collision is not proof of functional difference or statistical independence.",
            "The runner must enforce the full registered chain set and all previously exposed model states.",
            "Target identities and parameters are preparation/audit only and cannot be selector inputs.",
        ],
    }
