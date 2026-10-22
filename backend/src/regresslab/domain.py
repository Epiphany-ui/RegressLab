"""Pure, deterministic data and analysis rules for the descriptive Demo.

No function in this module reads files, opens a database, or performs inference.
Confirmation and AUDIT evaluation are deliberately outside this Demo boundary.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from copy import deepcopy
from uuid import UUID


ALGORITHM_VERSION = "regression-v1"
MAX_DATASET_ROWS = 5000
ROLES = ("TRAIN", "DEV", "DISCOVERY", "CONFIRM", "AUDIT")
PREDICTION_ROLES = ("DISCOVERY", "CONFIRM")
DEFAULT_CONFIG = {
    "max_depth": 2,
    "top_m": 20,
    "min_discovery_support": 30,
    "min_discovery_drop": 0.05,
    "duplicate_jaccard": 0.9,
    "min_confirm_support": 40,
    "min_confirm_drop": 0.05,
    "alpha": 0.05,
    "bootstrap_reps": 2000,
    "seed": 42,
    "feature_catalog_version": "surface-v1",
}
FEATURE_CATALOG = {
    "version": "surface-v1",
    "normalization": "NFKC;collapse-unicode-whitespace;strip",
    "locale": "input-locale",
    "length_bin": ["1-8", "9-20", "21-40", "41+"],
    "has_negation": "zh:不没别无未;en:word-boundary-no-not-never-without-cannot-can't-don't",
    "has_digit": "unicode-regex-digit",
    "has_question_mark": "? or ？",
}


class DomainError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _canonical(value) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise DomainError("INVALID_JSON_VALUE", "内容不能编码为规范 JSON。") from exc


def hash_json(value) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _utf8(value: str) -> bytes:
    try:
        return value.encode("utf-8")
    except UnicodeError as exc:
        raise DomainError("INVALID_UNICODE", "不接受未配对的 Unicode 代理字符。") from exc


def _reject_constant(value):
    raise ValueError(f"non-finite JSON number: {value}")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(value: str):
    return json.loads(value, object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def parse_jsonl(text: str) -> list[dict]:
    if not isinstance(text, str):
        raise DomainError("INVALID_ENCODING", "JSONL 必须是 UTF-8 文本。")
    if text.startswith("\ufeff"):
        raise DomainError("INVALID_ENCODING", "JSONL 不接受 UTF-8 BOM。", {"line": 1})
    _utf8(text)
    if not text:
        raise DomainError("EMPTY_FILE", "JSONL 文件不能为空。")
    rows = []
    # split on LF rather than splitlines: Unicode line separators can occur in text.
    lines = text.split("\n")
    for line_no, line in enumerate(lines, 1):
        if line_no == len(lines) and line == "" and text.endswith("\n"):
            continue
        if not line.strip():
            raise DomainError("EMPTY_LINE", "JSONL 不接受空行。", {"line": line_no})
        try:
            row = _load_json(line)
            _canonical(row)  # Reject overflow to infinity and invalid Unicode, too.
        except (ValueError, DomainError) as exc:
            raise DomainError("INVALID_JSON", "JSON 行无效、键重复或包含非有限数。", {"line": line_no}) from exc
        if not isinstance(row, dict):
            raise DomainError("INVALID_JSON_ROW", "每行必须是一个 JSON 对象。", {"line": line_no})
        rows.append(row)
    return rows


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def surface_features(text: str, locale: str) -> dict:
    normalized = normalize_text(text)
    size = len(normalized)
    length_bin = "1-8" if size <= 8 else "9-20" if size <= 20 else "21-40" if size <= 40 else "41+"
    language = locale.lower().split("-")[0]
    negation = False
    if language == "zh":
        negation = any(character in normalized for character in "不没别无未")
    elif language == "en":
        negation = bool(re.search(r"\b(?:no|not|never|without|cannot|can't|don't)\b", normalized, re.IGNORECASE))
    return {
        "locale": locale,
        "length_bin": length_bin,
        "has_negation": negation,
        "has_digit": bool(re.search(r"\d", normalized)),
        "has_question_mark": "?" in normalized or "？" in normalized,
    }


def _string(value, field: str, minimum: int, maximum: int, line: int):
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise DomainError("INVALID_SAMPLE", f"字段 {field} 类型或长度无效。", {"line": line, "field": field})
    _utf8(value)


def validate_dataset(rows: list[dict], source: dict) -> dict:
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_DATASET_ROWS:
        raise DomainError("DATASET_SIZE", "Demo 数据必须包含 1—5000 行。", {"limit": MAX_DATASET_ROWS})
    if not isinstance(source, dict):
        raise DomainError("INVALID_SOURCE", "必须提供数据来源。")
    required = {"sample_id", "group_id", "source_partition", "text", "gold_label", "locale"}
    limits = {"sample_id": (1, 160), "group_id": (1, 160), "text": (1, 8192), "gold_label": (1, 100), "locale": (2, 16)}
    samples = []
    seen_ids = set()
    by_text = defaultdict(list)
    by_group = defaultdict(list)
    for line, row in enumerate(rows, 1):
        if not isinstance(row, dict) or not required <= row.keys() or row.keys() - required - {"metadata"}:
            raise DomainError("INVALID_SAMPLE", "样本字段缺失或包含未允许字段（不能传入 role）。", {"line": line})
        for field, bounds in limits.items():
            _string(row[field], field, *bounds, line)
        if row["source_partition"] not in ("train", "dev", "test"):
            raise DomainError("INVALID_SAMPLE", "source_partition 必须为 train/dev/test。", {"line": line})
        if not normalize_text(row["text"]):
            raise DomainError("EMPTY_TEXT", "归一化后的文本不能为空。", {"line": line})
        if "metadata" in row:
            metadata = row["metadata"]
            if not isinstance(metadata, dict) or metadata.keys() - {"scenario"}:
                raise DomainError("INVALID_SAMPLE", "metadata 只允许 scenario 字符串。", {"line": line})
            if "scenario" in metadata:
                _string(metadata["scenario"], "metadata.scenario", 1, 100, line)
        if row["sample_id"] in seen_ids:
            raise DomainError("DUPLICATE_SAMPLE_ID", "sample_id 必须唯一。", {"line": line, "sample_id": row["sample_id"]})
        seen_ids.add(row["sample_id"])
        sample = deepcopy(row)
        sample["text_sha256"] = hashlib.sha256(_utf8(normalize_text(row["text"]))).hexdigest()
        sample["features"] = surface_features(row["text"], row["locale"])
        index = len(samples)
        by_text[sample["text_sha256"]].append(index)
        by_group[row["group_id"]].append(index)
        samples.append(sample)

    parent = list(range(len(samples)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        parent[find(right)] = find(left)

    for indices in itertools.chain(by_text.values(), by_group.values()):
        for index in indices[1:]:
            union(indices[0], index)
    for indices in by_text.values():
        if len({samples[index]["gold_label"] for index in indices}) > 1:
            raise DomainError("CONFLICTING_GOLD", "相同归一化文本存在不同 gold_label。", {"sample_ids": sorted((samples[i]["sample_id"] for i in indices), key=_utf8)})
    components = defaultdict(list)
    for index in range(len(samples)):
        components[find(index)].append(index)
    for indices in components.values():
        partitions = {samples[index]["source_partition"] for index in indices}
        if len(partitions) != 1:
            raise DomainError("SPLIT_LEAKAGE", "同 group 或归一化文本的连通组件跨原始分区。", {"sample_ids": sorted((samples[i]["sample_id"] for i in indices), key=_utf8)})
        component_key = min((samples[index]["group_id"] for index in indices), key=_utf8)
        partition = next(iter(partitions))
        if partition != "test":
            role = "TRAIN" if partition == "train" else "DEV"
        else:
            split_value = int(hashlib.sha256(_utf8("split-v1|42|" + component_key)).hexdigest()[:16], 16)
            role = "DISCOVERY" if split_value < 2**63 else "CONFIRM" if split_value < 3 * 2**62 else "AUDIT"
        for index in indices:
            samples[index]["component_key"] = component_key
            samples[index]["role"] = role

    labels = sorted({sample["gold_label"] for sample in samples if sample["role"] == "TRAIN"}, key=_utf8)
    if not 2 <= len(labels) <= 200:
        raise DomainError("INVALID_LABELSET", "TRAIN 必须包含 2—200 个标签。", {"label_count": len(labels)})
    unseen = sorted({sample["gold_label"] for sample in samples} - set(labels), key=_utf8)
    if unseen:
        raise DomainError("UNSEEN_LABEL", "DEV/TEST 包含 TRAIN 未出现的标签。", {"unseen_label_count": len(unseen)})
    samples.sort(key=lambda sample: _utf8(sample["sample_id"]))
    canonical_rows = [{key: value for key, value in sample.items() if key in required | {"metadata"}} for sample in samples]
    split_manifest = [{"sample_id": sample["sample_id"], "component_key": sample["component_key"], "role": sample["role"]} for sample in samples]
    fingerprints = {
        "canonical_rows_sha256": hash_json(canonical_rows),
        "labelset_sha256": hash_json(labels),
        "split_manifest_sha256": hash_json(split_manifest),
        "feature_catalog_sha256": hash_json(FEATURE_CATALOG),
    }
    evaluation = {key: fingerprints[key] for key in ("canonical_rows_sha256", "labelset_sha256", "split_manifest_sha256")}
    counts = {role: sum(sample["role"] == role for sample in samples) for role in ROLES}
    manifest = {
        **fingerprints,
        "evaluation_data_sha256": hash_json(evaluation),
        "content_sha256": hash_json({**fingerprints, "source": source}),
        "label_vocab": labels,
        "counts": counts,
        "row_count": len(samples),
        "component_count": len(components),
        "independent_counts": {role: len({sample["component_key"] for sample in samples if sample["role"] == role}) for role in ROLES},
        "label_counts": {label: sum(sample["gold_label"] == label for sample in samples) for label in labels},
        "protocol_version": "1.3",
        "split_protocol": "split-v1",
        "feature_catalog_version": "surface-v1",
    }
    return {"samples": samples, "manifest": manifest, "source": deepcopy(source)}


def _scope(dataset: dict) -> tuple[list[str], str]:
    samples = dataset["samples"]
    if not any(sample["role"] == "DISCOVERY" for sample in samples):
        raise DomainError("INVALID_SCOPE", "成对分析至少需要一个 DISCOVERY 样本。")
    expected = sorted((sample["sample_id"] for sample in samples if sample["role"] in PREDICTION_ROLES), key=_utf8)
    scope_hash = hash_json({"dataset_content_sha256": dataset["manifest"]["content_sha256"], "scope": {"kind": "ROLES", "roles": list(PREDICTION_ROLES)}})
    return expected, scope_hash


def validate_predictions(rows: list[dict], dataset: dict, parser_version: str = "label-json-v1") -> dict:
    if parser_version not in ("label-json-v1", "label-literal-v1"):
        raise DomainError("INVALID_PARSER", "只支持固定标签 JSON 或标签原文解析器。")
    expected, scope_hash = _scope(dataset)
    expected_ids = set(expected)
    labels = set(dataset["manifest"]["label_vocab"])
    if not isinstance(rows, list):
        raise DomainError("INVALID_PREDICTIONS", "预测必须为逐行 JSON 对象列表。")
    seen = Counter()
    valid = {}
    runs = set()
    issues = []
    extras = []
    required = {"sample_id", "prediction_label", "run_id", "raw_response"}
    for line, row in enumerate(rows, 1):
        sample_id = row.get("sample_id") if isinstance(row, dict) else None
        issue = None
        if isinstance(sample_id, str):
            seen[sample_id] += 1
            if sample_id not in expected_ids:
                extras.append(sample_id)
        if not isinstance(row, dict) or not required <= row.keys() or row.keys() - required - {"latency_ms"}:
            issue = "INVALID_PREDICTION_ROW"
        elif not isinstance(sample_id, str) or not 1 <= len(sample_id) <= 160:
            issue = "INVALID_PREDICTION_ROW"
        elif not isinstance(row["prediction_label"], str) or row["prediction_label"] not in labels:
            issue = "INVALID_LABEL"
        elif not isinstance(row["raw_response"], str) or not 1 <= len(row["raw_response"]) <= 32768:
            issue = "INVALID_RAW_RESPONSE"
        elif "latency_ms" in row and (isinstance(row["latency_ms"], bool) or not isinstance(row["latency_ms"], (int, float)) or not math.isfinite(row["latency_ms"]) or row["latency_ms"] < 0):
            issue = "INVALID_LATENCY"
        else:
            try:
                if not isinstance(row["run_id"], str):
                    raise ValueError("run_id must be string")
                run_id = str(UUID(row["run_id"]))
                runs.add(run_id)
            except (ValueError, TypeError, AttributeError):
                issue = "INVALID_RUN_ID"
            try:
                _utf8(row["raw_response"])
                if parser_version == "label-json-v1":
                    parsed = _load_json(row["raw_response"])
                    if not isinstance(parsed, dict) or set(parsed) != {"label"} or not isinstance(parsed["label"], str) or parsed["label"] not in labels:
                        raise ValueError("invalid label object")
                    parsed_label = parsed["label"]
                else:
                    parsed_label = row["raw_response"]
                    if parsed_label not in labels:
                        raise ValueError("invalid literal label")
                if parsed_label != row["prediction_label"]:
                    issue = "RAW_LABEL_MISMATCH"
            except (ValueError, DomainError):
                issue = issue or "INVALID_RAW_RESPONSE"
        if issue:
            issues.append({"line": line, "sample_id": sample_id if isinstance(sample_id, str) else None, "code": issue})
        elif sample_id in expected_ids and seen[sample_id] == 1:
            valid[sample_id] = deepcopy(row)
    duplicates = sorted((sample_id for sample_id, count in seen.items() if count > 1), key=_utf8)
    missing = sorted(expected_ids - seen.keys(), key=_utf8)
    # A duplicated ID is not a legally covered sample, even when one row is valid.
    for sample_id in duplicates:
        valid.pop(sample_id, None)
    coverage = {
        "expected_count": len(expected), "legal_count": len(valid),
        "missing_count": len(missing), "invalid_count": len(rows) - len(valid),
        "failed_count": 0, "ratio": len(valid) / len(expected) if expected else None,
    }
    if missing or extras or duplicates or issues or len(runs) != 1:
        code = "PREDICTION_COVERAGE" if missing or extras or duplicates else "MIXED_PREDICTION_RUNS" if len(runs) != 1 and not issues else issues[0]["code"]
        raise DomainError(code, "预测必须完整合法覆盖冻结的 D+C 范围，并来自单次运行。", {"coverage": coverage, "missing_ids": missing[:20], "extra_ids": sorted(set(extras), key=_utf8)[:20], "duplicate_ids": duplicates[:20], "issues": issues[:20]})
    ordered = [valid[sample_id] for sample_id in expected]
    return {
        "rows": ordered, "run_id": next(iter(runs)), "coverage": coverage,
        "content_sha256": hash_json(ordered), "scope_hash": scope_hash,
        "scope": {"kind": "ROLES", "roles": list(PREDICTION_ROLES)},
        "dataset_content_sha256": dataset["manifest"]["content_sha256"],
        "parser_version": parser_version,
    }


def _metrics(rows: list[dict], labels: list[str]) -> dict:
    if not rows:
        raise DomainError("INVALID_SCOPE", "空范围不产生正确率。")
    a = b = c = d = 0
    support = Counter()
    predicted = {"old_prediction_label": Counter(), "new_prediction_label": Counter()}
    true_positives = {"old_prediction_label": Counter(), "new_prediction_label": Counter()}
    for row in rows:
        gold = row["gold_label"]
        support[gold] += 1
        for field in predicted:
            predicted[field][row[field]] += 1
            if row[field] == gold:
                true_positives[field][gold] += 1
        old_ok = row["old_prediction_label"] == row["gold_label"]
        new_ok = row["new_prediction_label"] == row["gold_label"]
        if old_ok and new_ok:
            a += 1
        elif old_ok:
            b += 1
        elif new_ok:
            c += 1
        else:
            d += 1
    n = len(rows)

    def macro_f1(field):
        scores = []
        for label in labels:
            denominator = support[label] + predicted[field][label]
            scores.append(2 * true_positives[field][label] / denominator if denominator else 0.0)
        return sum(scores) / len(labels)

    return {
        "n": n, "a": a, "b": b, "c": c, "d": d,
        "old_accuracy": (a + b) / n, "new_accuracy": (a + c) / n,
        "accuracy_drop": (b - c) / n, "negative_flip_rate": b / n,
        "positive_flip_rate": c / n,
        "old_correct_regression_rate": b / (a + b) if a + b else None,
        "old_macro_f1": macro_f1("old_prediction_label"),
        "new_macro_f1": macro_f1("new_prediction_label"),
        "per_label_support": {label: support[label] for label in labels},
    }


def _discover(rows: list[dict], labels: list[str]) -> tuple[list[dict], str]:
    # A conjunction cannot have more support than either atom. Build inverted
    # memberships once and discard unsupported atoms before enumerating pairs;
    # this also bounds work when an upload contains thousands of locales.
    memberships = defaultdict(lambda: defaultdict(set))
    for index, row in enumerate(rows):
        for feature, value in row["features"].items():
            memberships[feature][_canonical(value)].add(index)
    atoms = []
    for feature in sorted(memberships, key=_utf8):
        for encoded, members in sorted(memberships[feature].items()):
            if len(members) >= DEFAULT_CONFIG["min_discovery_support"]:
                atoms.append(({"feature": feature, "op": "eq", "value": json.loads(encoded)}, members))
    conditions = [([atom], members) for atom, members in atoms]
    conditions.extend(([left, right], left_members & right_members) for (left, left_members), (right, right_members) in itertools.combinations(atoms, 2) if left["feature"] != right["feature"])
    candidates = []
    for condition, member_indices in conditions:
        predicate = {"all": condition}
        if len(member_indices) < DEFAULT_CONFIG["min_discovery_support"]:
            continue
        members = [rows[index] for index in sorted(member_indices)]
        metrics = _metrics(members, labels)
        if metrics["b"] <= metrics["c"] or metrics["accuracy_drop"] < DEFAULT_CONFIG["min_discovery_drop"]:
            continue
        member_ids = {row["sample_id"] for row in members}
        candidates.append({"predicate": predicate, "predicate_hash": hash_json(predicate), "discovery": metrics, "rank_score": (metrics["b"] - metrics["c"]) / math.sqrt(metrics["n"]), "member_ids": member_ids})
    candidates.sort(key=lambda candidate: (-candidate["rank_score"], -candidate["discovery"]["n"], _canonical(candidate["predicate"])))
    kept = []
    for candidate in candidates:
        if any(len(candidate["member_ids"] & previous["member_ids"]) / len(candidate["member_ids"] | previous["member_ids"]) >= DEFAULT_CONFIG["duplicate_jaccard"] for previous in kept):
            continue
        kept.append(candidate)
        if len(kept) == DEFAULT_CONFIG["top_m"]:
            break
    fingerprint = hash_json({"algorithm_version": ALGORITHM_VERSION, "config_sha256": hash_json(DEFAULT_CONFIG), "candidates": [{"predicate": candidate["predicate"], "discovery_member_ids_sha256": hash_json(sorted(candidate["member_ids"], key=_utf8))} for candidate in kept]})
    slices = [{"rank": rank, "predicate": candidate["predicate"], "predicate_hash": candidate["predicate_hash"], "discovery": candidate["discovery"], "rank_score": candidate["rank_score"], "row_support": candidate["discovery"]["n"], "independent_support": len({row["component_key"] for row in rows if row["sample_id"] in candidate["member_ids"]}), "status": "PROPOSED", "confirmation": None} for rank, candidate in enumerate(kept, 1)]
    return slices, fingerprint


def analyze(dataset: dict, old_predictions: dict, new_predictions: dict) -> dict:
    validated = []
    for prediction_set in (old_predictions, new_predictions):
        if not isinstance(prediction_set, dict) or "rows" not in prediction_set:
            raise DomainError("INVALID_PREDICTIONS", "分析需要已验证的预测集。")
        if prediction_set.get("dataset_content_sha256") != dataset["manifest"]["content_sha256"]:
            raise DomainError("SCOPE_MISMATCH", "预测与数据版本指纹不一致。")
        checked = validate_predictions(prediction_set["rows"], dataset, prediction_set.get("parser_version", "label-json-v1"))
        if prediction_set.get("scope_hash") != checked["scope_hash"] or prediction_set.get("content_sha256") != checked["content_sha256"]:
            raise DomainError("SCOPE_MISMATCH", "预测内容或冻结范围指纹不一致。")
        validated.append(checked)
    if validated[0]["run_id"] == validated[1]["run_id"]:
        raise DomainError("PREDICTION_RUN_REUSED", "旧、新预测必须分别来自各自的单次运行。")
    old, new = ({row["sample_id"]: row["prediction_label"] for row in prediction_set["rows"]} for prediction_set in validated)
    rows = []
    for sample in dataset["samples"]:
        # Only D sample gold/text/features enter the analysis and discovery functions.
        if sample["role"] != "DISCOVERY":
            continue
        old_label, new_label = old[sample["sample_id"]], new[sample["sample_id"]]
        old_ok, new_ok = old_label == sample["gold_label"], new_label == sample["gold_label"]
        outcome = "both_correct" if old_ok and new_ok else "negative_flip" if old_ok else "positive_flip" if new_ok else "both_wrong"
        rows.append({"sample_id": sample["sample_id"], "text": sample["text"], "gold_label": sample["gold_label"], "old_prediction_label": old_label, "new_prediction_label": new_label, "outcome": outcome, "features": deepcopy(sample["features"]), "component_key": sample["component_key"]})
    labels = dataset["manifest"]["label_vocab"]
    metrics = _metrics(rows, labels)
    slices, candidate_hash = _discover(rows, labels)
    old_confusions = Counter((row["gold_label"], row["old_prediction_label"]) for row in rows)
    new_confusions = Counter((row["gold_label"], row["new_prediction_label"]) for row in rows)
    cells = [{"gold_label": gold, "prediction_label": prediction, "old_count": old_confusions[gold, prediction], "new_count": new_confusions[gold, prediction], "delta": new_confusions[gold, prediction] - old_confusions[gold, prediction]} for gold, prediction in old_confusions.keys() | new_confusions.keys()]
    cells.sort(key=lambda cell: (-abs(cell["delta"]), _utf8(cell["gold_label"]), _utf8(cell["prediction_label"])))
    return {
        "metrics": {"discovery": metrics, "confirmation": None},
        "confusion_changes": {"role": "DISCOVERY", "cells": cells[:50], "total_nonzero": len(cells), "truncated": len(cells) > 50},
        "slices": slices, "candidate_set_hash": candidate_hash,
        "evidence_mode": "DESCRIPTIVE_ONLY", "verdict": "INCONCLUSIVE", "summary": "INCONCLUSIVE",
        "summary_reason": "EVIDENCE_NOT_CONFIRMABLE", "config": deepcopy(DEFAULT_CONFIG),
        "discovery_cases": [{key: value for key, value in row.items() if key != "component_key"} for row in rows],
        "row_support": len(rows), "independent_support": len({row["component_key"] for row in rows}),
        "distinct_negative_flips": metrics["b"], "algorithm_version": ALGORITHM_VERSION,
        "fixture": bool(dataset["source"].get("fixture_only", False)),
        "limitations": ["仅描述性 Demo；没有读取确认集 gold 或执行独立确认。", "未确认退化不代表已证明安全或非劣。", "分组可相互重叠，各组计数不能相加。", "外部预测和模型训练来源由提供者声明，未独立核验。"],
    }
