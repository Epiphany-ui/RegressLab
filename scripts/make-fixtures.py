#!/usr/bin/env python3
"""Regenerate the explicitly synthetic, dependency-free RegressLab demo inputs."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from math import comb
from pathlib import Path
import unicodedata
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "examples"
CONTRACTS = ROOT / "docs" / "archive" / "v1.3" / "contracts"
RUN_IDS = {
    "basic-old": "00000000-0000-4000-8000-000000000101",
    "basic-new": "00000000-0000-4000-8000-000000000102",
    "discovery-old": "00000000-0000-4000-8000-000000000201",
    "discovery-new": "00000000-0000-4000-8000-000000000202",
}


def role_of(group_id: str) -> str:
    value = int(hashlib.sha256(f"split-v1|42|{group_id}".encode()).hexdigest()[:16], 16)
    ratio = value / 2**64
    return "DISCOVERY" if ratio < 0.50 else "CONFIRM" if ratio < 0.75 else "AUDIT"


def groups(profile: str, role: str, count: int) -> list[str]:
    """Choose reproducible group IDs using only the public split rule, never predictions."""
    result = []
    candidate = 0
    while len(result) < count:
        group_id = f"synthetic:{profile}:{role.lower()}:{candidate:05d}"
        if role_of(group_id) == role:
            result.append(group_id)
        candidate += 1
    return result


def sample(sample_id: str, group_id: str, partition: str, text: str, label: str) -> dict:
    return {
        "sample_id": sample_id,
        "group_id": group_id,
        "source_partition": partition,
        "text": text,
        "gold_label": label,
        "locale": "zh-CN",
        "metadata": {"scenario": "synthetic_engineering_fixture"},
    }


def prediction(sample_id: str, label: str, run_id: str) -> dict:
    return {
        "sample_id": sample_id,
        "prediction_label": label,
        "run_id": run_id,
        "raw_response": json.dumps({"label": label}, ensure_ascii=False, separators=(",", ":")),
    }


def training_rows(profile: str) -> list[dict]:
    # Both labels have four independent training examples. DEV has one of each.
    # This is not a benchmark or evidence of classifier quality.
    rows = []
    for index in range(8):
        label = "A" if index < 4 else "B"
        verb = "开启" if label == "A" else "关闭"
        rows.append(sample(
            f"{profile}:train:{index + 1:02d}", f"synthetic:{profile}:train:{index + 1:02d}",
            "train", f"合成训练语句{profile}请{verb}房间{index + 1}的照明", label,
        ))
    for index, label in enumerate(["A", "B"]):
        rows.append(sample(
            f"{profile}:dev:{index + 1:02d}", f"synthetic:{profile}:dev:{index + 1:02d}",
            "dev", f"合成开发语句{profile}灯光测试项目{index + 1}", label,
        ))
    return rows


def basic_fixture() -> tuple[list[dict], list[dict], list[dict]]:
    fixture_path = CONTRACTS / "fixtures" / "paired-cases.jsonl"
    paired = [json.loads(line) for line in fixture_path.read_text(encoding="utf-8").splitlines() if line]
    assert len(paired) == 12, "The canonical paired fixture must contain 12 rows."
    rows = training_rows("basic")
    old, new = [], []
    for index, (case, group_id) in enumerate(zip(paired, groups("basic", "DISCOVERY", 12))):
        rows.append(sample(case["sample_id"], group_id, "test", f"合成计数案例{index + 1}请打开客厅灯", case["gold_label"]))
        old.append(prediction(case["sample_id"], case["old_prediction_label"], RUN_IDS["basic-old"]))
        new.append(prediction(case["sample_id"], case["new_prediction_label"], RUN_IDS["basic-new"]))
    # Confirmation has two both-correct, one negative flip and one positive flip.
    confirm_labels = [("A", "A", "A"), ("B", "B", "B"), ("A", "A", "B"), ("B", "A", "B")]
    for index, (values, group_id) in enumerate(zip(confirm_labels, groups("basic", "CONFIRM", 4))):
        gold, previous, current = values
        sample_id = f"basic:confirm:{index + 1:02d}"
        rows.append(sample(sample_id, group_id, "test", f"合成保留确认案例{index + 1}请调整照明", gold))
        old.append(prediction(sample_id, previous, RUN_IDS["basic-old"]))
        new.append(prediction(sample_id, current, RUN_IDS["basic-new"]))
    for index, group_id in enumerate(groups("basic", "AUDIT", 4)):
        rows.append(sample(f"basic:audit:{index + 1:02d}", group_id, "test", f"合成最终审计案例{index + 1}请检查定时灯", "A" if index % 2 == 0 else "B"))
    return rows, old, new


def alphabetic_token(role: str, index: int) -> str:
    # Fixed-width ASCII letters keep unique text without accidentally adding a digit.
    prefix = {"DISCOVERY": "q", "CONFIRM": "r", "AUDIT": "s"}[role]
    return prefix + chr(ord("a") + index // 26) + chr(ord("a") + index % 26)


def surface_text(role: str, index: int, risky: bool) -> str:
    token = alphabetic_token(role, index)
    if risky:
        templates = [
            "不关灯{token}",
            "不要关闭书房照明{token}？",
            "请不要在今晚自动关闭二楼走廊和客厅的灯光{number}{token}",
            "请不要按照原来的定时设置自动关闭楼上走廊以及楼下客厅的全部照明我希望继续保持这些灯光直到明天早晨{number}{token}？",
        ]
    else:
        templates = [
            "开灯{token}",
            "请打开书房照明{token}？",
            "请在今晚按照新的计划打开二楼走廊和客厅灯光{number}{token}",
            "请按照新的定时设置在晚餐结束以后打开楼上走廊以及楼下客厅的全部照明并继续保持这些灯光直到明天早晨{number}{token}？",
        ]
    return templates[index % 4].format(token=token, number=index + 101)


def large_outcome(index: int, risky: bool) -> tuple[bool, bool]:
    if risky:
        return (True, True) if index < 20 else (True, False) if index < 44 else (False, False)
    return (True, True) if index < 44 else (False, True)


def discovery_fixture() -> tuple[list[dict], list[dict], list[dict]]:
    rows = training_rows("discovery")
    old, new = [], []
    for role, count in [("DISCOVERY", 96), ("CONFIRM", 96), ("AUDIT", 32)]:
        for index, group_id in enumerate(groups("discovery", role, count)):
            risky = index < count // 2
            within_group = index % (count // 2)
            gold = "A" if index % 2 == 0 else "B"
            sample_id = f"discovery:{role.lower()}:{index + 1:03d}"
            rows.append(sample(sample_id, group_id, "test", surface_text(role, index, risky), gold))
            if role == "AUDIT":
                continue
            previous_ok, current_ok = large_outcome(within_group, risky)
            other = "B" if gold == "A" else "A"
            old.append(prediction(sample_id, gold if previous_ok else other, RUN_IDS["discovery-old"]))
            new.append(prediction(sample_id, gold if current_ok else other, RUN_IDS["discovery-new"]))
    return rows, old, new


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def metrics(rows: list[dict], old: list[dict], new: list[dict], role: str | None = None) -> dict:
    previous = {row["sample_id"]: row["prediction_label"] for row in old}
    current = {row["sample_id"]: row["prediction_label"] for row in new}
    counts = Counter({"a": 0, "b": 0, "c": 0, "d": 0})
    for row in rows:
        sample_id = row["sample_id"]
        if sample_id not in previous or (role is not None and role_of(row["group_id"]) != role):
            continue
        key = {(True, True): "a", (True, False): "b", (False, True): "c", (False, False): "d"}[
            previous[sample_id] == row["gold_label"], current[sample_id] == row["gold_label"]
        ]
        counts[key] += 1
    n = sum(counts.values())
    a, b, c, d = (counts[key] for key in "abcd")
    discordant = b + c
    return {
        "n": n, "a": a, "b": b, "c": c, "d": d,
        "old_accuracy": (a + b) / n,
        "new_accuracy": (a + c) / n,
        "accuracy_drop": (b - c) / n,
        "negative_flip_rate": b / n,
        "positive_flip_rate": c / n,
        "old_correct_regression_rate": b / (a + b) if a + b else None,
        "exact_one_sided_p": sum(comb(discordant, k) for k in range(b, discordant + 1)) / 2**discordant if discordant else 1.0,
    }


def validate(rows: list[dict], old: list[dict], new: list[dict], expected: dict[str, int]) -> None:
    assert len({row["sample_id"] for row in rows}) == len(rows)
    assert len({row["group_id"] for row in rows}) == len(rows)
    assert len({normalize(row["text"]) for row in rows}) == len(rows), "Normalized text must be globally unique."
    counts = Counter(row["source_partition"].upper() if row["source_partition"] != "test" else role_of(row["group_id"]) for row in rows)
    assert dict(counts) == expected, (counts, expected)
    assert {row["gold_label"] for row in rows if row["source_partition"] == "train"} == {"A", "B"}
    expected_ids = {row["sample_id"] for row in rows if row["source_partition"] == "test" and role_of(row["group_id"]) in {"DISCOVERY", "CONFIRM"}}
    for predictions in [old, new]:
        assert len(predictions) == len(expected_ids)
        assert {row["sample_id"] for row in predictions} == expected_ids
        assert len({row["run_id"] for row in predictions}) == 1
        for row in predictions:
            UUID(row["run_id"])
            assert json.loads(row["raw_response"]) == {"label": row["prediction_label"]}
            assert row["prediction_label"] in {"A", "B"}
            assert set(row) == {"sample_id", "prediction_label", "run_id", "raw_response"}
    for row in rows:
        assert set(row) == {"sample_id", "group_id", "source_partition", "text", "gold_label", "locale", "metadata"}
        assert row["metadata"] == {"scenario": "synthetic_engineering_fixture"}


def write_jsonl(name: str, rows: list[dict]) -> None:
    (OUTPUT / name).write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    basic = basic_fixture()
    discovery = discovery_fixture()
    validate(*basic, {"TRAIN": 8, "DEV": 2, "DISCOVERY": 12, "CONFIRM": 4, "AUDIT": 4})
    validate(*discovery, {"TRAIN": 8, "DEV": 2, "DISCOVERY": 96, "CONFIRM": 96, "AUDIT": 32})
    basic_discovery = metrics(*basic, "DISCOVERY")
    assert [basic_discovery[key] for key in ["n", "a", "b", "c", "d"]] == [12, 6, 3, 1, 2]
    for prefix, values in [("", basic), ("discovery-", discovery)]:
        for filename, rows in zip(["dataset.jsonl", "old-predictions.jsonl", "new-predictions.jsonl"], values):
            write_jsonl(prefix + filename, rows)
    summary = {
        "synthetic_only": True,
        "basic": {"DISCOVERY": basic_discovery, "CONFIRM": metrics(*basic, "CONFIRM"), "D_PLUS_C": metrics(*basic)},
        "discovery": {"DISCOVERY": metrics(*discovery, "DISCOVERY"), "CONFIRM": metrics(*discovery, "CONFIRM"), "D_PLUS_C": metrics(*discovery)},
    }
    (OUTPUT / "expected-metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"basic": {"dataset_rows": len(basic[0]), "predictions_per_file": len(basic[1])}, "discovery": {"dataset_rows": len(discovery[0]), "predictions_per_file": len(discovery[1])}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
