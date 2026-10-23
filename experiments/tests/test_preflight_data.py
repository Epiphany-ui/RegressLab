"""Preflight data audit: public gold, leakage cleanup, no TEST model inputs."""

from copy import deepcopy
import hashlib
import json

import pytest

from preflight.data import audit_massive


def row(identity, text, label="A", partition="train", **extra):
    return {"id": identity, "locale": "zh-CN", "partition": partition, "utt": text, "intent": label, **extra}


def basic_rows():
    return [row(1, "训练甲", "A"), row(2, "训练乙", "B"), row(3, "开发句一", "A", "dev"), row(4, "开发句二", "B", "dev")]


def test_public_labels_and_source_metadata_are_preserved_without_test_content():
    rows = basic_rows() + [row(5, "TEST_SECRET_UTTERANCE", "TEST_SECRET_GOLD", "test")]
    source = {"version": "official-fixture", "license": "synthetic", "raw_sha256": "a" * 64}
    result = audit_massive(rows, expected_labels={"A", "B"}, source=source)
    assert result["manifest"]["source"] == source
    assert result["manifest"]["counts_raw"] == {"train": 2, "dev": 2, "test": 1}
    assert result["manifest"]["test_samples_returned"] == 0
    assert result["train"][0]["sample_id"] == "zh-CN:1"
    assert result["train"][0]["group_id"] == "massive:1"
    assert result["train"][0]["gold_label"] == "A"
    assert "TEST_SECRET" not in json.dumps(result)


def test_transitive_cross_partition_component_is_excluded_in_full():
    rows = basic_rows() + [
        row(10, "Ａ　Ｂ", "A", "train"),
        row(11, "A B", "A", "train"),
        row(11, "测试只用于审计", "A", "test"),
    ]
    result = audit_massive(rows, expected_labels=2)
    assert result["manifest"]["excluded_counts"] == {"train": 2, "dev": 0, "test": 1}
    assert {x["sample_id"] for x in result["excluded"]} == {"zh-CN:10", "zh-CN:11"}
    assert all("CROSS_PARTITION_COMPONENT" in x["reasons"] for x in result["excluded"])
    assert {x["sample_id"] for x in result["train"]} == {"zh-CN:1", "zh-CN:2"}
    assert "测试只用于审计" not in json.dumps(result, ensure_ascii=False)


def test_conflicting_gold_excludes_whole_component_without_relabeling():
    rows = basic_rows() + [row(10, "冲突文本", "A"), row(11, "冲突文本", "B")]
    result = audit_massive(rows, expected_labels=2)
    assert len(result["excluded"]) == 2
    assert all(x["reasons"] == ["CONFLICTING_GOLD_COMPONENT"] for x in result["excluded"])
    assert result["manifest"]["label_vocab"] == ["A", "B"]


def test_dev_split_is_component_stable_and_order_independent():
    rows = basic_rows() + [row(20, "开发重复Ａ", "A", "dev"), row(21, "开发重复A", "A", "dev")]
    result = audit_massive(rows, expected_labels=2)
    assert result == audit_massive(list(reversed(rows)), expected_labels=2)
    model_ids = {x["sample_id"] for x in result["dev_model"]}
    selector_ids = {x["sample_id"] for x in result["dev_selector"]}
    assert model_ids.isdisjoint(selector_ids)
    assert ({"zh-CN:20", "zh-CN:21"} <= model_ids) or ({"zh-CN:20", "zh-CN:21"} <= selector_ids)
    for role in ("dev_model", "dev_selector"):
        for sample in result[role]:
            value = int(hashlib.sha256(("pilot-dev-v1|42|" + sample["component_key"]).encode()).hexdigest()[:16], 16)
            assert (value < 2**63) == (role == "dev_model")


def test_cleanup_that_loses_a_training_class_stops_before_prediction():
    rows = [row(1, "保留甲", "A"), row(2, "泄漏乙", "B"), row(3, "泄漏乙", "B", "dev")]
    with pytest.raises(ValueError, match="TRAIN_LABELSET_MISMATCH"):
        audit_massive(rows, expected_labels=2)


def test_dev_unknown_label_is_rejected_and_integer_intents_are_not_renamed():
    with pytest.raises(ValueError, match="DEV_UNSEEN_LABEL"):
        audit_massive(basic_rows() + [row(5, "未知开发标签", "C", "dev")], expected_labels=2)
    result = audit_massive([row(1, "数字甲", 0), row(2, "数字乙", 1)], expected_labels={"0", "1"})
    assert result["manifest"]["label_vocab"] == ["0", "1"]
    with pytest.raises(ValueError, match="TRAIN_LABELSET_MISMATCH"):
        audit_massive(basic_rows())  # default requires all official 60 classes.


def test_audit_does_not_mutate_input_or_copy_personal_metadata():
    rows = basic_rows()
    rows[0].update(scenario="lighting", worker_id="PRIVATE_WORKER")
    before = deepcopy(rows)
    result = audit_massive(rows, expected_labels=2)
    assert rows == before
    assert result["train"][0]["metadata"] == {"scenario": "lighting"}
    assert "PRIVATE_WORKER" not in json.dumps(result)


@pytest.mark.parametrize("patch", [{"intent": True}, {"utt": "　\t"}, {"locale": "en-US"}, {"partition": "validation"}, {"id": []}])
def test_invalid_official_rows_fail_without_echoing_text(patch):
    rows = basic_rows()
    rows[0].update(patch)
    with pytest.raises(ValueError) as error:
        audit_massive(rows, expected_labels=2)
    assert "训练甲" not in str(error.value)
