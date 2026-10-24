"""Pinned CLINC150 closed-set source audit; TEST and OOS never leave preparation.

All six official partitions participate in model-free duplicate/conflict audit.
Only cleaned in-scope TRAIN and the complete official validation partition are
returned. This independent diagnostic does not tune models or selectors and has
no DEV_MODEL split; do not pool it with MASSIVE's half-DEV protocol.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Collection
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

from .data import normalize_text

COMMIT = "828f8093932c8fe6ca7936c3d2e52903b1c523de"
REPOSITORY_URL = "https://github.com/clinc/oos-eval"
RAW_ROOT = f"https://raw.githubusercontent.com/clinc/oos-eval/{COMMIT}"
DATA_URL = RAW_ROOT + "/data/data_full.json"
LICENSE_URL = RAW_ROOT + "/LICENSE"
DATA_SHA256 = "36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0"
LICENSE_SHA256 = "e6bc9e9c474700b708f568bac9e5a8a9bcb2b1dad53442f5ba449fcb848b8e76"
PARTITIONS = ("train", "val", "test", "oos_train", "oos_val", "oos_test")
CLOSED_PARTITIONS = ("train", "val", "test")


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def fetch_clinc(output: Path) -> dict:
    """Cache two fixed-commit official files and reject changed bytes, offline too."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name, url, expected in [("data_full.json", DATA_URL, DATA_SHA256), ("LICENSE", LICENSE_URL, LICENSE_SHA256)]:
        target = output / name
        if target.exists():
            if not target.is_file() or target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise ValueError("CLINC_CACHED_SOURCE_HASH_MISMATCH")
            continue
        temporary = output / (name + ".part")
        if temporary.is_symlink():
            raise ValueError("CLINC_LINKED_DOWNLOAD_TARGET")
        subprocess.run(["curl", "--fail", "--location", "--max-time", "120", "--silent", "--show-error", "--output", str(temporary), url], check=True)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
            raise ValueError("CLINC_DOWNLOADED_SOURCE_HASH_MISMATCH")
        temporary.rename(target)
    return {
        "dataset": "CLINC150-full", "source_repository": REPOSITORY_URL,
        "source_commit": COMMIT, "source_release": "clinc/oos-eval@" + COMMIT,
        "source_url": DATA_URL, "data_sha256": DATA_SHA256,
        "license_url": LICENSE_URL, "license_sha256": LICENSE_SHA256,
        "license": "CC-BY-3.0", "locale": "en",
        "citation_url": "https://aclanthology.org/D19-1131/",
    }


def _expected_vocabulary(value):
    if isinstance(value, bool):
        raise ValueError("INVALID_CLINC_EXPECTED_LABELS")
    if isinstance(value, int):
        if value < 2:
            raise ValueError("INVALID_CLINC_EXPECTED_LABELS")
        return value
    if isinstance(value, (str, bytes)) or not isinstance(value, Collection):
        raise ValueError("INVALID_CLINC_EXPECTED_LABELS")
    if any(not isinstance(label, str) or not label.strip() for label in value):
        raise ValueError("INVALID_CLINC_EXPECTED_LABELS")
    labels = set(value)
    if len(labels) < 2 or "oos" in labels:
        raise ValueError("INVALID_CLINC_EXPECTED_LABELS")
    return labels


def audit_clinc(payload: dict, *, expected_labels: int | Collection[str] = 150, source: dict | None = None) -> dict:
    """Exclude whole normalized-text leaking/conflicting/OOS components.

    IDs retain fixed official partition and zero-based row position, which are
    stable for the pinned file. No task label is corrected or moved. TEST/OOS
    labels are allowed only inside this model-free audit and are not returned.
    """
    expected_labels = _expected_vocabulary(expected_labels)
    if not isinstance(payload, dict) or set(payload) != set(PARTITIONS):
        raise ValueError("INVALID_CLINC_PARTITION_SET")
    if source is not None and not isinstance(source, dict):
        raise ValueError("INVALID_CLINC_SOURCE_METADATA")
    samples, components = [], defaultdict(list)
    for partition in PARTITIONS:
        values = payload[partition]
        if not isinstance(values, list):
            raise ValueError("INVALID_CLINC_PARTITION_ROWS")
        for position, row in enumerate(values):
            if not isinstance(row, list) or len(row) != 2 or any(not isinstance(value, str) or not value.strip() for value in row):
                raise ValueError("INVALID_CLINC_ROW")
            text, label = row
            normalized = normalize_text(text)
            if not normalized or (partition.startswith("oos_") != (label == "oos")):
                raise ValueError("INVALID_CLINC_TEXT_OR_SCOPE_LABEL")
            sample_id = f"clinc150:{partition}:{position:06d}"
            component_key = "clinc150-text:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            sample = {"sample_id": sample_id, "source_partition": partition,
                      "source_locator": f"data/data_full.json#/{partition}/{position}",
                      "text": text, "gold_label": label, "locale": "en", "component_key": component_key}
            components[component_key].append(sample)
            samples.append(sample)
    if not payload["train"]:
        raise ValueError("EMPTY_CLINC_TRAIN")

    kept, excluded = [], []
    for component_key in sorted(components):
        members = components[component_key]
        partitions = {row["source_partition"] for row in members}
        reasons = []
        if len(partitions) > 1:
            reasons.append("CROSS_PARTITION_COMPONENT")
        if len({row["gold_label"] for row in members}) > 1:
            reasons.append("CONFLICTING_GOLD_COMPONENT")
        if any(row["source_partition"].startswith("oos_") for row in members):
            reasons.append("OUT_OF_SCOPE_COMPONENT")
        for sample in members:
            if reasons:
                excluded.append({"sample_id": sample["sample_id"], "source_partition": sample["source_partition"],
                                 "component_key": component_key, "reasons": reasons.copy()})
            else:
                kept.append(sample)
    labels = sorted({row["gold_label"] for row in kept if row["source_partition"] == "train"}, key=lambda value: value.encode("utf-8"))
    if isinstance(expected_labels, int) and len(labels) != expected_labels or isinstance(expected_labels, set) and set(labels) != expected_labels:
        raise ValueError(f"CLINC_TRAIN_LABELSET_MISMATCH: cleaned TRAIN has {len(labels)} classes")
    if any(row["gold_label"] not in labels for row in kept if row["source_partition"] == "val"):
        raise ValueError("CLINC_DEV_UNSEEN_LABEL")
    train = [{**row, "role": "TRAIN"} for row in kept if row["source_partition"] == "train"]
    dev = [{**row, "role": "DEV_SELECTOR"} for row in kept if row["source_partition"] == "val"]
    for rows in [train, dev, excluded]:
        rows.sort(key=lambda row: row["sample_id"].encode("utf-8"))
    canonical = sorted(samples, key=lambda row: row["sample_id"].encode("utf-8"))

    def counts(rows):
        values = Counter(row["source_partition"] for row in rows)
        return {partition: values[partition] for partition in PARTITIONS}

    train_counts = Counter(row["gold_label"] for row in train)
    dev_counts = Counter(row["gold_label"] for row in dev)
    manifest = {
        "protocol": "clinc150-independent-diagnostic-v1", "locale": "en",
        "source": deepcopy(source) if source else {},
        "counts_raw": counts(samples), "counts_cleaned": counts(kept), "excluded_counts": counts(excluded),
        "component_count_raw": len(components), "component_count_cleaned": len({row["component_key"] for row in kept}),
        "label_vocab": labels, "train_label_counts": {label: train_counts[label] for label in labels},
        "dev_counts": {"DEV_MODEL": 0, "DEV_SELECTOR": len(dev)},
        "dev_label_counts": {"DEV_MODEL": {label: 0 for label in labels}, "DEV_SELECTOR": {label: dev_counts[label] for label in labels}},
        "dev_protocol": "ALL_OFFICIAL_VAL_FIXED_MODEL_AND_SELECTOR_NO_TUNING_NO_DEV_MODEL",
        "comparison_policy": "INDEPENDENT_DIAGNOSTIC_DO_NOT_POOL_WITH_MASSIVE_HALF_DEV",
        "cleaning_policy": "EXCLUDE_WHOLE_CROSS_PARTITION_CONFLICTING_OR_OOS_COMPONENT",
        "test_use": "AUDIT_ONLY_NO_MODEL_INPUT_OR_EVALUATION", "test_samples_returned": 0,
        "oos_use": "AUDIT_AND_EXCLUDE_NO_MODEL_INPUT_OR_EVALUATION", "oos_samples_returned": 0,
        "source_rows_sha256": _digest(canonical), "excluded_sha256": _digest(excluded),
        "train_sha256": _digest(train), "dev_selector_sha256": _digest(dev),
    }
    return {"train": train, "dev_selector": dev, "manifest": manifest, "excluded": excluded}


def main():
    parser = argparse.ArgumentParser(description="固定CLINC150来源和无模型闭集数据审计，不返回TEST/OOS")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path)
    args = parser.parse_args()
    source = fetch_clinc(args.output)
    audited = audit_clinc(json.loads((args.output / "data_full.json").read_text()), source=source)
    if args.audit_output:
        args.audit_output.parent.mkdir(parents=True, exist_ok=True)
        with args.audit_output.open("x", encoding="utf-8") as stream:
            json.dump(audited["manifest"], stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    print(json.dumps(audited["manifest"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
