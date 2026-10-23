"""Audit official MASSIVE rows before prediction; expose only TRAIN and DEV.

TEST participates solely in duplicate/conflict audit and source fingerprints.
Its text and gold never appear in the returned samples or audit manifest.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection
from copy import deepcopy
import hashlib
import json
import unicodedata


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _digest(value) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _identity(value, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise ValueError(f"INVALID_MASSIVE_{field.upper()}")
    return str(value)


def audit_massive(
    rows: list[dict], *, expected_labels: int | Collection[str] = 60, source: dict | None = None,
) -> dict:
    """Exclude whole leaking/conflicting components and split DEV deterministically.

    ``expected_labels`` is the official class count (60) or an explicit vocabulary;
    tests may supply two classes. Integer intents remain exact decimal strings;
    this function does not invent intent names or rewrite public gold labels.
    ``source`` is caller-supplied source/version/license/file-hash metadata.
    """
    if not isinstance(rows, list) or not rows:
        raise ValueError("EMPTY_MASSIVE_DATA")
    if isinstance(expected_labels, bool) or (
        isinstance(expected_labels, int) and expected_labels < 2
    ):
        raise ValueError("INVALID_EXPECTED_LABELS")
    if not isinstance(expected_labels, int):
        if isinstance(expected_labels, (str, bytes)) or not isinstance(expected_labels, Collection):
            raise ValueError("INVALID_EXPECTED_LABELS")
        expected_labels = {_identity(label, "intent") for label in expected_labels}
        if len(expected_labels) < 2:
            raise ValueError("INVALID_EXPECTED_LABELS")
    if source is not None and not isinstance(source, dict):
        raise ValueError("INVALID_SOURCE_METADATA")

    samples, by_group, by_text = [], defaultdict(list), defaultdict(list)
    for row in rows:
        if not isinstance(row, dict) or not {"id", "locale", "partition", "utt", "intent"} <= row.keys():
            raise ValueError("INVALID_MASSIVE_ROW")
        if row["locale"] != "zh-CN" or row["partition"] not in ("train", "dev", "test"):
            raise ValueError("INVALID_MASSIVE_LOCALE_OR_PARTITION")
        text = row["utt"]
        if not isinstance(text, str) or not normalize_text(text):
            raise ValueError("INVALID_MASSIVE_TEXT")
        sample = {
            "sample_id": "zh-CN:" + _identity(row["id"], "id"),
            "group_id": "massive:" + _identity(row["id"], "id"),
            "source_partition": row["partition"], "text": text,
            "gold_label": _identity(row["intent"], "intent"), "locale": "zh-CN",
        }
        # Official scenario is safe task metadata; worker/person fields are ignored.
        if isinstance(row.get("scenario"), (str, int)) and not isinstance(row.get("scenario"), bool):
            sample["metadata"] = {"scenario": str(row["scenario"])}
        index = len(samples)
        by_group[sample["group_id"]].append(index)
        by_text[normalize_text(text)].append(index)
        samples.append(sample)

    parent = list(range(len(samples)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for indices in [*by_group.values(), *by_text.values()]:
        for index in indices[1:]:
            parent[find(index)] = find(indices[0])
    components = defaultdict(list)
    for index in range(len(samples)):
        components[find(index)].append(index)

    kept, excluded = [], []
    for indices in components.values():
        partitions = {samples[index]["source_partition"] for index in indices}
        labels = {samples[index]["gold_label"] for index in indices}
        ids = [samples[index]["sample_id"] for index in indices]
        reasons = []
        if len(partitions) > 1:
            reasons.append("CROSS_PARTITION_COMPONENT")
        if len(labels) > 1:
            reasons.append("CONFLICTING_GOLD_COMPONENT")
        if len(ids) != len(set(ids)):
            reasons.append("DUPLICATE_SAMPLE_ID_COMPONENT")
        component_key = min((samples[index]["group_id"] for index in indices), key=lambda s: s.encode("utf-8"))
        for index in indices:
            sample = samples[index]
            if reasons:
                excluded.append({
                    "sample_id": sample["sample_id"], "source_partition": sample["source_partition"],
                    "component_key": component_key, "reasons": reasons.copy(),
                })
            else:
                kept.append({**sample, "component_key": component_key})

    labels = sorted({s["gold_label"] for s in kept if s["source_partition"] == "train"}, key=lambda s: s.encode("utf-8"))
    if (isinstance(expected_labels, int) and len(labels) != expected_labels) or (
        isinstance(expected_labels, set) and set(labels) != expected_labels
    ):
        raise ValueError(f"TRAIN_LABELSET_MISMATCH: cleaned TRAIN has {len(labels)} classes")
    if any(s["gold_label"] not in labels for s in kept if s["source_partition"] == "dev"):
        raise ValueError("DEV_UNSEEN_LABEL")

    train, dev_model, dev_selector = [], [], []
    for sample in sorted(kept, key=lambda s: s["sample_id"].encode("utf-8")):
        if sample["source_partition"] == "test":
            continue
        if sample["source_partition"] == "train":
            sample["role"] = "TRAIN"
            train.append(sample)
        else:
            value = int(hashlib.sha256(("pilot-dev-v1|42|" + sample["component_key"]).encode()).hexdigest()[:16], 16)
            model = value < 2**63
            sample["role"] = "DEV_MODEL" if model else "DEV_SELECTOR"
            (dev_model if model else dev_selector).append(sample)

    def counts(values):
        counter = Counter(s["source_partition"] for s in values)
        return {partition: counter[partition] for partition in ("train", "dev", "test")}

    excluded.sort(key=lambda s: (s["sample_id"].encode("utf-8"), s["source_partition"], s["reasons"]))
    canonical = sorted(samples, key=lambda s: (s["sample_id"].encode("utf-8"), s["source_partition"], _digest(s)))
    manifest = {
        "protocol": "massive-zh-preflight-v1", "locale": "zh-CN",
        "source": deepcopy(source) if source else {},
        "counts_raw": counts(samples), "counts_cleaned": counts(kept),
        "excluded_counts": counts(excluded),
        "component_count_raw": len(components),
        "component_count_cleaned": len({s["component_key"] for s in kept}),
        "label_vocab": labels, "train_label_counts": dict(sorted(Counter(s["gold_label"] for s in train).items())),
        "dev_counts": {"DEV_MODEL": len(dev_model), "DEV_SELECTOR": len(dev_selector)},
        "dev_label_counts": {
            role: {label: sum(s["gold_label"] == label for s in subset) for label in labels}
            for role, subset in [("DEV_MODEL", dev_model), ("DEV_SELECTOR", dev_selector)]
        },
        "dev_split_protocol": "pilot-dev-v1", "dev_split_seed": 42,
        "source_rows_sha256": _digest(canonical), "excluded_sha256": _digest(excluded),
        "train_sha256": _digest(train), "dev_model_sha256": _digest(dev_model),
        "dev_selector_sha256": _digest(dev_selector),
        "test_use": "AUDIT_ONLY_NO_MODEL_INPUT_OR_EVALUATION",
        "cleaning_policy": "EXCLUDE_WHOLE_CROSS_PARTITION_CONFLICTING_OR_DUPLICATE_ID_COMPONENT",
        "test_samples_returned": 0,
    }
    return {"train": train, "dev_model": dev_model, "dev_selector": dev_selector, "manifest": manifest, "excluded": excluded}
