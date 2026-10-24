"""Post-hoc diagnostics of frozen historical risk; never used for selection.

Targets are accepted by this diagnostic evaluator only. Scores/groups must be
formed before the target is observed. No fitting, parameter search, model load,
or mutation of an earlier run occurs here. Results on an exposed development
set are descriptive and do not constitute independent future validation.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from numbers import Integral
from pathlib import Path

import numpy as np

from .runner import file_hash, verify_freeze
from .verify import read_json

PRIMARY_BUDGET = 100
LOW_EVENT_COUNT = 20
LOW_GROUP_EVENT_COUNT = 5


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _indices(value, size, code):
    _require(isinstance(value, list), code)
    _require(all(isinstance(i, Integral) and not isinstance(i, (bool, np.bool_)) and 0 <= i < size for i in value), code)
    result = [int(i) for i in value]
    _require(len(set(result)) == len(result), code)
    return result


def ranking_metrics(events, scores):
    """ROC AUC with half credit for ties; threshold-group average precision.

    AP=sum over descending equal-score blocks of (positives in block / all
    positives) * precision after including the whole block. Thus AP is invariant
    to sample-ID order within a score tie and equals prevalence for a constant
    score. AUC is NA without both positive and negative outcomes; AP is NA
    without positive outcomes. No interpolation or significance test is used.
    """
    events = np.asarray(events)
    scores = np.asarray(scores, dtype=np.float64)
    _require(events.ndim == 1 and events.dtype.kind == 'b' and scores.shape == events.shape, 'INVALID_RANKING_ARRAYS')
    _require(np.isfinite(scores).all(), 'NONFINITE_RANKING_SCORE')
    positives, negatives = int(events.sum()), int((~events).sum())
    unique = np.unique(scores)
    auc = None
    auc_reason = 'NO_POSITIVE_EVENTS' if not positives else 'NO_NEGATIVE_EVENTS' if not negatives else None
    if positives and negatives:
        negative_before, favorable = 0, 0.0
        for score in unique:
            block = scores == score
            block_positive = int(events[block].sum())
            block_negative = int((~events[block]).sum())
            favorable += block_positive * (negative_before + 0.5 * block_negative)
            negative_before += block_negative
        auc = favorable / (positives * negatives)
    ap = None
    if positives:
        cumulative_positive, cumulative_count, ap = 0, 0, 0.0
        for score in unique[::-1]:
            block = scores == score
            block_positive = int(events[block].sum())
            cumulative_positive += block_positive
            cumulative_count += int(block.sum())
            ap += (block_positive / positives) * (cumulative_positive / cumulative_count)
    return {
        'roc_auc': auc, 'roc_auc_na_reason': auc_reason,
        'average_precision': ap, 'average_precision_na_reason': None if positives else 'NO_POSITIVE_EVENTS',
        'positive_events': positives, 'negative_events': negatives,
        'score_unique_values': len(unique), 'constant_score': len(unique) <= 1,
    }


def _top(ids, scores):
    return sorted(range(len(ids)), key=lambda i: (-float(scores[i]), ids[i].encode('utf-8')))[:min(PRIMARY_BUDGET, len(ids))]


def _selection_metrics(selected, events):
    count = int(events[selected].sum())
    total = int(events.sum())
    return {'actual_size': len(selected), 'detected': count, 'recall': count / total if total else None, 'precision': count / len(selected) if selected else None}


def analyze_history_signal(rows, history, pool_indices, reference_probabilities, groups, target, *, context='POST_HOC'):
    """Diagnose full-D frozen histories/groups against full-D target labels.

    ``pool_indices`` must be exactly the f2-correct set (any order), and group
    ``p_member_indices`` address that pool order. Reference probabilities have
    D rows and at least two frozen class columns; the caller's frozen score
    contract establishes which labels the columns represent. This function
    needs only their top-two gap and does not infer column names from DEV gold.
    ``context`` describes whether the unchanged diagnostic was specified before
    a new external/new-model target or is post-hoc on an exposed old run; it
    never changes scores, groups, rankings or measurements.
    """
    _require(context in {'POST_HOC', 'PRESPECIFIED_EXTERNAL', 'PRESPECIFIED_OLD_DEV_NEW_MODEL'}, 'UNKNOWN_DIAGNOSTIC_CONTEXT')
    _require(isinstance(rows, list), 'INVALID_DISCOVERY_ROWS')
    for row in rows:
        _require(isinstance(row, dict) and set(row) == {'sample_id', 'text', 'gold_label'} and all(isinstance(v, str) and v for v in row.values()), 'INVALID_DISCOVERY_ROWS')
        for value in row.values():
            value.encode('utf-8')
    ids = [row['sample_id'] for row in rows]
    _require(len(set(ids)) == len(ids), 'DUPLICATE_SAMPLE_ID')
    gold = np.asarray([row['gold_label'] for row in rows], dtype=str)
    history = np.asarray(history)
    target = np.asarray(target)
    _require(history.shape == (len(rows), 3) and target.shape == (len(rows),), 'FULL_DISCOVERY_ARRAY_SHAPE')
    _require(history.dtype.kind == target.dtype.kind == 'U' and all(value for value in history.flat) and all(value for value in target), 'INVALID_PREDICTED_LABELS')
    pool = _indices(pool_indices, len(rows), 'INVALID_CURRENT_CORRECT_POOL')
    _require(set(pool) == set(np.flatnonzero(history[:, 2] == gold).tolist()), 'INCOMPLETE_CURRENT_CORRECT_POOL')
    try:
        probabilities = np.asarray(reference_probabilities, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise ValueError('INVALID_REFERENCE_PROBABILITIES') from error
    _require(probabilities.ndim == 2 and probabilities.shape[0] == len(rows) and probabilities.shape[1] >= 2, 'REFERENCE_PROBABILITY_SHAPE')
    _require(np.isfinite(probabilities).all() and np.all((probabilities >= 0) & (probabilities <= 1)) and np.allclose(probabilities.sum(axis=1), 1, rtol=0, atol=1e-8), 'INVALID_REFERENCE_PROBABILITIES')
    _require(isinstance(groups, list), 'INVALID_RISK_GROUPS')
    risk = np.zeros(len(pool), dtype=np.float64)
    group_members = []
    total_weight = 0.0
    for group in groups:
        _require(isinstance(group, dict) and {'normalized_weight', 'd_member_indices', 'p_member_indices'} <= set(group), 'INVALID_RISK_GROUP')
        weight = group['normalized_weight']
        _require(type(weight) in (float, int) and math.isfinite(weight) and 0 <= weight <= 1, 'INVALID_GROUP_WEIGHT')
        d_members = _indices(group['d_member_indices'], len(rows), 'INVALID_GROUP_DISCOVERY_MEMBERS')
        p_members = _indices(group['p_member_indices'], len(pool), 'INVALID_GROUP_POOL_MEMBERS')
        expected = {i for i, d_index in enumerate(pool) if d_index in set(d_members)}
        _require(set(p_members) == expected, 'GROUP_DISCOVERY_POOL_SCOPE_MISMATCH')
        _require(group.get('d_support', len(d_members)) == len(d_members) and group.get('p_support', len(p_members)) == len(p_members), 'GROUP_SUPPORT_MISMATCH')
        risk[p_members] += weight
        total_weight += weight
        group_members.append(p_members)
    _require(not groups or math.isclose(total_weight, 1.0, rel_tol=0, abs_tol=1e-8), 'GROUP_WEIGHTS_NOT_NORMALIZED')
    pool_array = np.asarray(pool, dtype=int)
    pool_ids = [ids[i] for i in pool]
    events = target[pool_array] != gold[pool_array]
    ordered_probabilities = np.sort(probabilities[pool_array], axis=1)
    margin = -(ordered_probabilities[:, -1] - ordered_probabilities[:, -2])
    risk_order, margin_order = _top(pool_ids, risk), _top(pool_ids, margin)
    risk_set, margin_set = set(risk_order), set(margin_order)
    event_set = set(np.flatnonzero(events).tolist())
    total = len(event_set)
    base_rate = total / len(pool) if pool else None
    positive_risk = set(np.flatnonzero(risk > 0).tolist())
    group_reports = []
    for index, (group, members) in enumerate(zip(groups, group_members)):
        count = len(set(members) & event_set)
        rate = count / len(members) if members else None
        group_reports.append({
            'group_number': index + 1, 'predicate': deepcopy(group.get('predicate')),
            'normalized_weight': float(group['normalized_weight']), 'historical_weight': group.get('w'),
            'historical_old_correct_opportunities': deepcopy(group.get('e')),
            'historical_negative_flips': deepcopy(group.get('b')),
            'discovery_support': len(group['d_member_indices']), 'pool_support': len(members),
            'future_flip_count': count, 'future_flip_rate': rate,
            'future_flip_enrichment': rate / base_rate if base_rate and rate is not None else None,
            'enrichment_na_reason': 'NO_POOL_EVENTS' if not total else 'EMPTY_GROUP_POOL' if not members else None,
            'low_future_event_support': count < LOW_GROUP_EVENT_COUNT,
        })
    historical_flip = np.any((history[pool_array, :2] == gold[pool_array, None]) & (history[pool_array, 1:] != gold[pool_array, None]), axis=1)
    confusion = []
    for label, members in [('both_top100', risk_set & margin_set), ('risk_top100_only', risk_set - margin_set), ('margin_top100_only', margin_set - risk_set), ('neither_top100', set(range(len(pool))) - (risk_set | margin_set))]:
        count = len(members & event_set)
        confusion.append({'stratum': label, 'sample_count': len(members), 'future_flip_count': count, 'future_flip_rate': count / len(members) if members else None})
    scope = {
        'POST_HOC': 'EXPOSED_DEVELOPMENT_POST_HOC_DIAGNOSTIC',
        'PRESPECIFIED_EXTERNAL': 'PRESPECIFIED_EXTERNAL_FEASIBILITY_DIAGNOSTIC',
        'PRESPECIFIED_OLD_DEV_NEW_MODEL': 'PRESPECIFIED_NEW_MODEL_OLD_DEV_FEASIBILITY_DIAGNOSTIC',
    }[context]
    scope_limitation = {
        'POST_HOC': 'Post-hoc diagnosis on an already exposed DEV set, not independent future validation or model selection.',
        'PRESPECIFIED_EXTERNAL': 'Prespecified fixed diagnostic on independently sourced external validation data; no selector tuning or formal TEST evaluation, and model chains are not thereby statistically independent.',
        'PRESPECIFIED_OLD_DEV_NEW_MODEL': 'Prespecified fixed diagnostic of new model realizations on previously exposed DEV rows; does not make the data untouched or constitute formal TEST evaluation.',
    }[context]
    risk_top_limitation = 'Risk-Top is an exploratory diagnostic ranking, not a preregistered additional winner in the completed round-two comparison.' if context == 'POST_HOC' else 'Risk-Top is preregistered for this fixed feasibility closeout; it does not retroactively enter or alter the completed round-two comparison.'
    return {
        'scope': scope, 'budget': PRIMARY_BUDGET,
        'discovery_count': len(rows), 'pool_count': len(pool), 'future_flip_count': total,
        'pool_future_flip_rate': base_rate, 'low_future_event_support': total < LOW_EVENT_COUNT,
        'historical_flip_pool_count': int(historical_flip.sum()),
        'repaired_then_recurred_count': int(np.sum(historical_flip & events)),
        'historically_unseen_future_flip_count': int(np.sum(~historical_flip & events)),
        'risk_score_definition': 'sum of frozen normalized group weights covering each pool row; not calibrated future probability',
        'margin_score_definition': 'negative f2 top-one minus top-two probability gap',
        'roc_auc_definition': 'positive-negative pair agreement with 0.5 credit for exactly tied scores',
        'average_precision_definition': 'noninterpolated threshold-group AP; include all tied scores together before computing block precision',
        'top_budget_tie_rule': 'descending score, then sample_id UTF-8 bytes',
        'reference_probability_label_alignment': 'inherited frozen score contract; no inference of class columns from DEV gold',
        'risk_top': {**ranking_metrics(events, risk), 'top100': _selection_metrics(risk_order, events)},
        'margin': {**ranking_metrics(events, margin), 'top100': _selection_metrics(margin_order, events)},
        'positive_risk_coverage': {
            'pool_count': len(positive_risk), 'pool_fraction': len(positive_risk) / len(pool) if pool else None,
            'future_flip_count': len(positive_risk & event_set), 'future_flip_recall': len(positive_risk & event_set) / total if total else None,
        },
        'incremental_over_margin_top100': {
            'common_selected_count': len(risk_set & margin_set),
            'risk_only_detected': len((risk_set - margin_set) & event_set),
            'margin_only_detected': len((margin_set - risk_set) & event_set),
            'shared_detected': len((risk_set & margin_set) & event_set),
            'union_detected': len((risk_set | margin_set) & event_set),
            'margin_missed_future_flips': len(event_set - margin_set),
        },
        'top100_confusion_strata': confusion,
        'group_union_pool_count': len(positive_risk),
        'group_union_future_flip_count': len(positive_risk & event_set),
        'risk_groups': group_reports,
        'limitations': [
            scope_limitation,
            'No significance, causal, conditional-independence, superiority or noninferiority claim; sparse group event rates are unstable.',
            'Risk groups overlap; unique detections use sets and group event counts must not be summed.',
            risk_top_limitation,
            'AUC, threshold-group AP and a fixed-budget ID tie break answer different descriptive questions.',
        ],
    }


def analyze_run(output: Path):
    """Read only a completed frozen round-two run; never write into it."""
    output = Path(output).resolve()
    frozen = verify_freeze(output)
    _require(frozen['schema_version'] == 'cpu-preflight-matrix-v2', 'SECOND_ROUND_FROZEN_RUN_REQUIRED')
    report = read_json(output / 'report.json')
    _require([chain['chain_id'] for chain in report['chains']] == frozen['chain_ids'], 'REPORT_FROZEN_CHAIN_SET_MISMATCH')
    rows = read_json(output / 'dev-data.json')
    classes = read_json(output / 'data-audit.json')['label_vocab']
    expected_ids = [row['sample_id'] for row in rows]
    chains = []
    for chain in report['chains']:
        directory = output / 'chains' / chain['chain_id']
        selection = read_json(directory / 'selections.json')
        groups = read_json(directory / 'hgc-diagnostics.json')['groups']
        histories = []
        for slot in range(3):
            with np.load(directory / f'f{slot}-history.npz', allow_pickle=False) as stored:
                _require(stored['sample_ids'].tolist() == expected_ids, 'HISTORY_SAMPLE_ID_MISMATCH')
                histories.append(stored['predictions'])
                if slot == 2:
                    reference = stored['probabilities'].copy()
        with np.load(directory / 'f3-target.npz', allow_pickle=False) as stored:
            _require(stored['sample_ids'].tolist() == expected_ids, 'TARGET_SAMPLE_ID_MISMATCH')
            target = stored['predictions'].copy()
        history = np.asarray(histories).T
        _require(set(history.ravel().tolist()) <= set(classes) and set(target.tolist()) <= set(classes), 'UNKNOWN_PREDICTION_LABEL')
        _require(reference.shape == (len(rows), len(classes)) and np.array_equal(np.asarray(classes)[reference.argmax(axis=1)], history[:, 2]), 'F2_SCORE_LABEL_ALIGNMENT_MISMATCH')
        diagnosis = analyze_history_signal(rows, history, selection['pool_indices_in_dev'], reference, groups, target)
        _require(diagnosis['future_flip_count'] == chain['future_flip_count'] and diagnosis['pool_count'] == chain['pool_count'], 'FROZEN_SCOPE_OR_TARGET_REPORT_MISMATCH')
        chains.append({'chain_id': chain['chain_id'], 'family': chain['family'], 'cached_target_file_sha256': file_hash(directory / 'f3-target.npz'), **diagnosis})
    return {'schema_version': 'cpu-frozen-history-diagnostics-v1', 'scope': 'POST_HOC_DEVELOPMENT_ONLY', 'source_run_id': report['run_id'], 'source_freeze_sha256': file_hash(output / 'matrix-freeze.json'), 'source_report_sha256': file_hash(output / 'report.json'), 'diagnostic_code_sha256': file_hash(Path(__file__)), 'all_frozen_bytes_verified': True, 'new_training_executed': False, 'selectors_changed': False, 'chains': chains}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='只读已冻结CPU第二轮工件；后验诊断，不训练或调参')
    parser.add_argument('output', type=Path)
    arguments = parser.parse_args()
    print(json.dumps(analyze_run(arguments.output), ensure_ascii=False, indent=2, allow_nan=False))
