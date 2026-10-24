"""Canonical inference identities for the bounded TF-IDF / logistic CPU pilot.

Call from preparation/audit code before any DEV inference. These functions
never predict, deserialize models, or read files. Target identities and arrays
must stay outside selector inputs. Equality is exact canonical state equality;
inequality is not proof of functional difference or statistical independence.
"""

from collections import defaultdict
import hashlib
import json
import re

import numpy as np
from sklearn.feature_extraction.text import TfidfTransformer, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.utils.validation import check_is_fitted

SCHEMA_VERSION = "cpu-inference-identity-v1"
SLOTS = ("f0", "f1", "f2", "f3")


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _canonical(value):
    """Strict JSON; never stringify opaque objects or silently coerce keys."""
    def validate(item):
        if item is None or type(item) in (bool, int):
            return
        if type(item) is float:
            _require(np.isfinite(item), "NONFINITE_IDENTITY_VALUE")
            return
        if type(item) is str:
            item.encode("utf-8")
            return
        if type(item) is list:
            for entry in item:
                validate(entry)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for entry in item.values():
                validate(entry)
            return
        raise ValueError("OPAQUE_IDENTITY_VALUE")

    try:
        validate(value)
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("INVALID_IDENTITY_UNICODE") from exc


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _array(value, shape, name):
    _require(type(value) is np.ndarray and value.dtype.kind in "iuf", f"INVALID_{name}_ARRAY")
    _require(value.shape == shape, f"INVALID_{name}_SHAPE")
    # Normalize numeric dtype, endianness, layout, and IEEE signed zero.
    with np.errstate(over="ignore", invalid="ignore"):
        normalized = np.array(value, dtype="<f8", order="C", copy=True)
    _require(np.isfinite(normalized).all(), f"NONFINITE_{name}_ARRAY")
    normalized[normalized == 0] = 0
    return {"dtype": "<f8", "shape": list(normalized.shape), "order": "C", "bytes_sha256": hashlib.sha256(normalized.tobytes(order="C")).hexdigest()}


def _configuration(vectorizer):
    params = vectorizer.get_params(deep=False)
    _require(params["preprocessor"] is None and params["tokenizer"] is None, "CUSTOM_TEXT_CALLABLE_UNSUPPORTED")
    _require(type(params["analyzer"]) is str and params["analyzer"] in {"word", "char", "char_wb"}, "CUSTOM_ANALYZER_UNSUPPORTED")
    _require(params["strip_accents"] is None or type(params["strip_accents"]) is str and params["strip_accents"] in {"ascii", "unicode"}, "CUSTOM_ACCENT_CALLABLE_UNSUPPORTED")
    _require(type(params["lowercase"]) is bool and type(params["binary"]) is bool, "INVALID_VECTORIZER_BOOLEAN")
    _require(params["input"] in {"content", "filename", "file"} and params["decode_error"] in {"strict", "ignore", "replace"} and type(params["encoding"]) is str, "INVALID_TEXT_DECODING_CONFIG")
    ngrams = params["ngram_range"]
    _require(isinstance(ngrams, (tuple, list)) and len(ngrams) == 2 and all(type(value) is int for value in ngrams) and 1 <= ngrams[0] <= ngrams[1], "INVALID_NGRAM_RANGE")
    dtype = np.dtype(params["dtype"])
    _require(dtype.kind == "f" and dtype.itemsize in {4, 8}, "UNSUPPORTED_TFIDF_DTYPE")
    transformer = vectorizer._tfidf
    _require(type(transformer) is TfidfTransformer, "CUSTOM_TFIDF_TRANSFORMER_UNSUPPORTED")
    _require(transformer.norm in {None, "l1", "l2"} and type(transformer.use_idf) is bool and type(transformer.sublinear_tf) is bool, "INVALID_TFIDF_CONFIG")
    stop_words = None
    token_pattern = None
    configured = params["stop_words"]
    if type(configured) is str:
        _require(configured == "english", "INVALID_STOP_WORDS")
    else:
        _require(configured is None or isinstance(configured, (list, tuple, set, frozenset)), "INVALID_STOP_WORDS")
        if configured is not None:
            _require(all(type(word) is str for word in configured), "OPAQUE_STOP_WORD")
    _require(params["token_pattern"] is None or type(params["token_pattern"]) is str, "INVALID_TOKEN_PATTERN")
    if params["analyzer"] == "word":
        _require(type(params["token_pattern"]) is str, "INVALID_TOKEN_PATTERN")
        token_pattern = params["token_pattern"]
        resolved = vectorizer.get_stop_words()
        if resolved is not None:
            _require(all(type(word) is str for word in resolved), "OPAQUE_STOP_WORD")
            stop_words = sorted(set(resolved), key=lambda value: value.encode("utf-8"))
    # smooth_idf/min_df/max_df/max_features affect fitting, not transform once
    # vocabulary and idf are frozen. char analyzers ignore word token settings.
    return {
        "input": params["input"], "encoding": params["encoding"], "decode_error": params["decode_error"],
        "analyzer": params["analyzer"], "strip_accents": params["strip_accents"], "lowercase": params["lowercase"],
        "ngram_range": list(ngrams), "token_pattern": token_pattern, "stop_words": stop_words,
        "binary": params["binary"], "dtype": dtype.name,
        "norm": transformer.norm, "use_idf": transformer.use_idf, "sublinear_tf": transformer.sublinear_tf,
    }


def semantic_identity(vectorizer, classifier) -> dict:
    """Return JSON-safe inference state/hash, independent of training provenance.

    Only exact built-in fitted estimator types are supported. Custom analyzers,
    preprocessors, tokenizers, subclasses, object arrays, and nonfinite state
    fail closed. No prediction or model-file operation occurs.
    """
    _require(type(vectorizer) is TfidfVectorizer and type(classifier) is LogisticRegression, "UNSUPPORTED_ESTIMATOR_TYPE")
    _require(not any(name in obj.__dict__ for obj, names in [(vectorizer, ("transform", "build_analyzer", "build_preprocessor", "build_tokenizer", "decode", "get_params", "get_stop_words")), (classifier, ("predict", "predict_proba", "decision_function"))] for name in names), "OVERRIDDEN_INFERENCE_METHOD")
    try:
        check_is_fitted(vectorizer, attributes=["vocabulary_", "_tfidf"])
        check_is_fitted(classifier, attributes=["classes_", "coef_", "intercept_", "n_features_in_"])
    except (TypeError, ValueError) as exc:
        raise ValueError("UNFITTED_ESTIMATOR") from exc
    config = _configuration(vectorizer)
    vocabulary = vectorizer.vocabulary_
    _require(type(vocabulary) is dict and bool(vocabulary), "INVALID_VOCABULARY")
    _require(all(type(token) is str and token and isinstance(index, (int, np.integer)) and not isinstance(index, (bool, np.bool_)) for token, index in vocabulary.items()), "INVALID_VOCABULARY_ENTRY")
    width = len(vocabulary)
    _require({int(index) for index in vocabulary.values()} == set(range(width)), "INVALID_VOCABULARY_INDICES")
    labels = classifier.classes_
    _require(type(labels) is np.ndarray and labels.ndim == 1 and labels.dtype.kind == "U" and len(labels) >= 2, "INVALID_CLASS_LABELS")
    classes = labels.tolist()
    _require(all(classes) and len(set(classes)) == len(classes), "INVALID_CLASS_LABELS")
    _require(classifier.n_features_in_ == width, "FEATURE_DIMENSION_MISMATCH")
    rows = 1 if len(classes) == 2 else len(classes)
    # The current locked sklearn uses sigmoid for binary and softmax for
    # multiclass LogisticRegression. Legacy liblinear/OvR is unsupported.
    legacy_mode = getattr(classifier, "multi_class", None)
    _require(legacy_mode not in {"ovr", "multinomial"} and not (len(classes) > 2 and classifier.solver == "liblinear"), "LEGACY_PROBABILITY_LINK_UNSUPPORTED")
    components = {
        "pipeline": "sklearn-tfidf-logistic-v1", "vectorizer": config,
        "vocabulary": [[token, int(vocabulary[token])] for token in sorted(vocabulary, key=lambda value: value.encode("utf-8"))],
        "idf": _array(vectorizer.idf_, (width,), "IDF") if config["use_idf"] else None,
        "classes": classes, "probability_link": "binary-sigmoid" if rows == 1 else "multiclass-softmax",
        "coef": _array(classifier.coef_, (rows, width), "COEF"),
        "intercept": _array(classifier.intercept_, (rows,), "INTERCEPT"),
    }
    return {"schema_version": SCHEMA_VERSION, "inference_sha256": _digest(components), "components": components}


def _validated_hash(identity):
    _require(type(identity) is dict and set(identity) == {"schema_version", "inference_sha256", "components"}, "INVALID_IDENTITY_OBJECT")
    _require(identity["schema_version"] == SCHEMA_VERSION and type(identity["components"]) is dict, "UNSUPPORTED_IDENTITY_SCHEMA")
    value = identity["inference_sha256"]
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None, "INVALID_INFERENCE_HASH")
    _require(_digest(identity["components"]) == value, "INFERENCE_HASH_MISMATCH")
    components = identity["components"]
    _require(set(components) == {"pipeline", "vectorizer", "vocabulary", "idf", "classes", "probability_link", "coef", "intercept"} and components["pipeline"] == "sklearn-tfidf-logistic-v1", "INVALID_IDENTITY_COMPONENTS")
    return value


def audit_identities(nodes: list[dict]) -> dict:
    """Audit a complete supplied matrix; caller must check registered chain IDs.

    Any f3/history equality (including within a chain), or f3/f3 equality,
    blocks the gate. History/history sharing is reported without blocking.
    A complete quartet is required for every supplied chain, preventing an
    omitted target from producing a vacuous PASS. An omitted entire chain
    still requires a separate preregistration-to-matrix completeness check.
    """
    _require(type(nodes) is list and bool(nodes), "EMPTY_IDENTITY_MATRIX")
    groups = defaultdict(set)
    ordered = []
    for node in nodes:
        _require(type(node) is dict and set(node) == {"chain_id", "slot", "identity"}, "INVALID_IDENTITY_NODE")
        chain, slot = node["chain_id"], node["slot"]
        _require(type(chain) is str and bool(chain.strip()), "INVALID_CHAIN_ID")
        _require(type(slot) is str and slot in SLOTS, "INVALID_MODEL_SLOT")
        try:
            chain.encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("INVALID_CHAIN_ID") from exc
        _require(slot not in groups[chain], "DUPLICATE_MODEL_NODE")
        groups[chain].add(slot)
        ordered.append({"chain_id": chain, "slot": slot, "inference_sha256": _validated_hash(node["identity"])})
    _require(all(slots == set(SLOTS) for slots in groups.values()), "INCOMPLETE_CHAIN_IDENTITIES")
    ordered.sort(key=lambda node: (node["chain_id"].encode("utf-8"), SLOTS.index(node["slot"])))
    targets = [node for node in ordered if node["slot"] == "f3"]
    history = [node for node in ordered if node["slot"] != "f3"]
    target_history = [{"target": target, "history": past} for target in targets for past in history if target["inference_sha256"] == past["inference_sha256"]]

    def pairs(values):
        return [{"left": left, "right": right} for i, left in enumerate(values) for right in values[i + 1:] if left["inference_sha256"] == right["inference_sha256"]]

    target_target, history_history = pairs(targets), pairs(history)
    return {
        "schema_version": "cpu-identity-audit-v1", "passed": not target_history and not target_target,
        "node_count": len(ordered), "chain_count": len(groups), "target_count": len(targets),
        "unique_inference_count": len({node["inference_sha256"] for node in ordered}), "nodes": ordered,
        "target_history_collisions": target_history, "target_target_collisions": target_target,
        "history_history_collisions": history_history,
        "statistical_independence_established": False,
        "limitations": [
            "No exact canonical-state collision does not prove functional difference or statistical independence.",
            "Related data, representations and training realizations can remain correlated despite distinct hashes.",
            "Caller must compare supplied chain IDs against the entire preregistered matrix before any DEV prediction.",
            "Target identities/weights are audit-only and must not be supplied to a history-only selector.",
        ],
    }
