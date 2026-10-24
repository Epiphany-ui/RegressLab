"""Exact toy leakage audits; never fit or infer any CLINC model."""

from copy import deepcopy
import hashlib
import json

import pytest

from preflight.clinc import PARTITIONS, audit_clinc, fetch_clinc


def sample():
    result = {partition: [] for partition in PARTITIONS}
    result.update(train=[["training alpha", "A"], ["training beta", "B"]], val=[["validation alpha", "A"], ["validation beta", "B"]])
    return result


def test_only_train_and_complete_val_are_returned_no_test_or_oos_text_or_labels():
    payload = sample()
    payload['test'] = [['SECRET_TEST_UTTERANCE', 'SECRET_TEST_LABEL']]
    payload['oos_test'] = [['SECRET_OOS_UTTERANCE', 'oos']]
    metadata = {'source_commit': 'fixed-fixture', 'data_sha256': 'a'*64}
    audited = audit_clinc(payload, expected_labels={'A', 'B'}, source=metadata)
    assert set(audited) == {'train', 'dev_selector', 'manifest', 'excluded'}
    assert [row['role'] for row in audited['train']] == ['TRAIN', 'TRAIN']
    assert [row['role'] for row in audited['dev_selector']] == ['DEV_SELECTOR', 'DEV_SELECTOR']
    assert audited['manifest']['dev_counts'] == {'DEV_MODEL': 0, 'DEV_SELECTOR': 2}
    assert audited['manifest']['source'] == metadata
    assert audited['manifest']['test_samples_returned'] == audited['manifest']['oos_samples_returned'] == 0
    assert 'SECRET_' not in json.dumps(audited)
    assert audited['manifest']['counts_raw']['test'] == 1
    assert audited['manifest']['counts_cleaned']['oos_test'] == 0


def test_same_normalized_text_across_partitions_excludes_whole_component():
    payload = sample()
    payload['train'] += [['Ａ　Ｂ', 'A'], ['A B', 'A']]
    payload['test'] = [['A B', 'A']]
    audited = audit_clinc(payload, expected_labels=2)
    removed = audited['excluded']
    assert len(removed) == 3
    assert {row['sample_id'] for row in removed} == {'clinc150:train:000002', 'clinc150:train:000003', 'clinc150:test:000000'}
    assert all(row['reasons'] == ['CROSS_PARTITION_COMPONENT'] for row in removed)
    assert audited['manifest']['counts_cleaned']['train'] == 2
    assert audited['manifest']['counts_cleaned']['test'] == 0


def test_within_partition_conflict_excluded_without_relabeling_but_consistent_duplicate_preserved():
    payload = sample()
    payload['train'] += [['conflicting', 'A'], ['conflicting', 'B'], ['same label', 'A'], ['same label', 'A']]
    audited = audit_clinc(payload, expected_labels=2)
    assert len(audited['excluded']) == 2
    assert all(row['reasons'] == ['CONFLICTING_GOLD_COMPONENT'] for row in audited['excluded'])
    assert len(audited['train']) == 4
    assert len({row['component_key'] for row in audited['train']}) == 3


def test_oos_conflict_removes_closed_member_without_returning_oos():
    payload = sample()
    payload['val'] += [['ambiguous scope', 'A']]
    payload['oos_train'] = [['ambiguous scope', 'oos']]
    audited = audit_clinc(payload, expected_labels=2)
    assert len(audited['dev_selector']) == 2
    assert len(audited['excluded']) == 2
    assert all(row['reasons'] == ['CROSS_PARTITION_COMPONENT', 'CONFLICTING_GOLD_COMPONENT', 'OUT_OF_SCOPE_COMPONENT'] for row in audited['excluded'])


def test_source_index_ids_and_hashes_are_stable_and_inputs_are_unchanged():
    payload = sample()
    original = deepcopy(payload)
    first = audit_clinc(payload, expected_labels=2)
    reordered = {key: payload[key] for key in reversed(PARTITIONS)}
    assert first == audit_clinc(reordered, expected_labels=2)
    assert payload == original
    assert first['train'][0]['sample_id'] == 'clinc150:train:000000'
    assert first['train'][0]['source_locator'] == 'data/data_full.json#/train/0'
    assert first['manifest']['excluded_sha256'] == hashlib.sha256(b'[]').hexdigest()
    payload['val'][0][0] += ' changed'
    second = audit_clinc(payload, expected_labels=2)
    assert first['manifest']['source_rows_sha256'] != second['manifest']['source_rows_sha256']
    assert first['manifest']['dev_selector_sha256'] != second['manifest']['dev_selector_sha256']


def test_missing_training_class_or_unknown_val_label_stops():
    payload = sample()
    payload['test'] = [['training beta', 'B']]
    with pytest.raises(ValueError, match='CLINC_TRAIN_LABELSET_MISMATCH'):
        audit_clinc(payload, expected_labels=2)
    payload = sample()
    payload['val'] += [['unknown val', 'C']]
    with pytest.raises(ValueError, match='CLINC_DEV_UNSEEN_LABEL'):
        audit_clinc(payload, expected_labels=2)
    with pytest.raises(ValueError, match='CLINC_TRAIN_LABELSET_MISMATCH'):
        audit_clinc(sample())


@pytest.mark.parametrize('bad', [None, {}, {'train': []}])
def test_invalid_partition_set_is_rejected(bad):
    with pytest.raises(ValueError, match='INVALID_CLINC_PARTITION_SET'):
        audit_clinc(bad, expected_labels=2)


@pytest.mark.parametrize('bad', [[['', 'A']], [['x']], [[1, 'A']], [['x', 'oos']]])
def test_invalid_closed_rows_rejected_without_echoing_text(bad):
    payload = sample();payload['test'] = bad
    with pytest.raises(ValueError, match='INVALID_CLINC_'):
        audit_clinc(payload, expected_labels=2)


def test_cached_changed_source_fails_before_download(tmp_path, monkeypatch):
    (tmp_path/'data_full.json').write_bytes(b'not pinned bytes')
    def forbidden(*args, **kwargs):
        raise AssertionError('Should reject an existing changed cache, not download over it')
    monkeypatch.setattr('preflight.clinc.subprocess.run', forbidden)
    with pytest.raises(ValueError, match='CLINC_CACHED_SOURCE_HASH_MISMATCH'):
        fetch_clinc(tmp_path)


@pytest.mark.parametrize('labels', [True, 1, 'AB', {'A'}, {'A', 'oos'}])
def test_invalid_expected_labels_rejected(labels):
    with pytest.raises(ValueError, match='INVALID_CLINC_EXPECTED_LABELS'):
        audit_clinc(sample(), expected_labels=labels)


def test_ids_use_partition_and_source_position_not_text_or_label():
    payload = sample()
    audited = audit_clinc(payload, expected_labels=2)
    train_ids = [row['sample_id'] for row in audited['train']]
    dev_ids = [row['sample_id'] for row in audited['dev_selector']]
    assert train_ids == ['clinc150:train:000000', 'clinc150:train:000001']
    assert dev_ids == ['clinc150:val:000000', 'clinc150:val:000001']
    assert set(train_ids).isdisjoint(dev_ids)
    changed = deepcopy(payload)
    changed['train'][0][0] = 'different text at same source position'
    assert [row['sample_id'] for row in audit_clinc(changed, expected_labels=2)['train']] == train_ids


def test_valid_cached_files_preserve_pinned_provenance_and_do_not_download(tmp_path, monkeypatch):
    from preflight import clinc
    data, license_data = b'synthetic source cache', b'synthetic license cache'
    (tmp_path/'data_full.json').write_bytes(data)
    (tmp_path/'LICENSE').write_bytes(license_data)
    monkeypatch.setattr(clinc, 'DATA_SHA256', hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(clinc, 'LICENSE_SHA256', hashlib.sha256(license_data).hexdigest())
    def forbidden(*args, **kwargs):
        raise AssertionError('Valid cache should be used offline')
    monkeypatch.setattr(clinc.subprocess, 'run', forbidden)
    actual = fetch_clinc(tmp_path)
    assert actual['source_commit'] == '828f8093932c8fe6ca7936c3d2e52903b1c523de'
    assert actual['source_url'] == clinc.DATA_URL
    assert clinc.COMMIT in actual['license_url']
    assert actual['license'] == 'CC-BY-3.0'
    assert actual['data_sha256'] == hashlib.sha256(data).hexdigest()
    assert actual['license_sha256'] == hashlib.sha256(license_data).hexdigest()
    assert (tmp_path/'data_full.json').read_bytes() == data


def test_changed_license_is_rejected_even_when_data_hash_is_correct(tmp_path, monkeypatch):
    from preflight import clinc
    data = b'synthetic data'
    (tmp_path/'data_full.json').write_bytes(data)
    (tmp_path/'LICENSE').write_bytes(b'changed license')
    monkeypatch.setattr(clinc, 'DATA_SHA256', hashlib.sha256(data).hexdigest())
    with pytest.raises(ValueError, match='CLINC_CACHED_SOURCE_HASH_MISMATCH'):
        fetch_clinc(tmp_path)


def test_download_hash_mismatch_does_not_publish_final_filename(tmp_path, monkeypatch):
    from preflight import clinc
    def wrong_download(arguments, **kwargs):
        target = arguments[arguments.index('--output')+1]
        from pathlib import Path
        Path(target).write_bytes(b'wrong source payload')
    monkeypatch.setattr(clinc.subprocess, 'run', wrong_download)
    with pytest.raises(ValueError, match='CLINC_DOWNLOADED_SOURCE_HASH_MISMATCH'):
        fetch_clinc(tmp_path)
    assert not (tmp_path/'data_full.json').exists()
