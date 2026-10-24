"""A small, controlled test of historical information beyond reference margin.

This is a score-enabled adaptation of the planned Risk-LR diagnostic, not a new
selection algorithm. Feature construction has no target argument. Only
``fit_development`` accepts outcomes, and its records are whole exposed chains.
The runner is responsible for keeping all held-out chains out of those records.
"""
from __future__ import annotations

from numbers import Integral, Real
import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .diagnostics import ranking_metrics
from .hgc import DEFAULT_HGC_CONFIG, _risk_groups


MARGIN_FEATURE_NAMES = ['reference_margin']
COMBINED_FEATURE_NAMES = MARGIN_FEATURE_NAMES + [
    'past_wrong_fraction_f0_f1',
    'past_negative_flip_rate',
    'maximum_gold_probability_drop',
    'mean_adjacent_probability_total_variation',
    'frozen_group_risk_sum',
]
METHOD_FEATURE_KEYS = {'margin-lr': 'margin_features', 'margin-history-lr': 'combined_features'}
DEFAULT_C_GRID = (.01, .1, 1., 10.)


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _strings(values, code, *, unique=False):
    array = np.asarray(values, dtype=str) if isinstance(values, (list, tuple)) and not values else np.asarray(values)
    _require(array.ndim == 1 and array.dtype.kind == 'U' and all(array), code)
    _require(not unique or len(set(array.tolist())) == len(array), code)
    for value in array:
        value.encode('utf-8')
    return array


def _history(gold, history):
    gold = _strings(gold, 'INVALID_GOLD')
    history = np.asarray(history)
    _require(history.shape == (len(gold), 3) and history.dtype.kind == 'U' and all(history.flat), 'INVALID_HISTORY')
    return gold, history


def group_risk(rows, history, pool_indices):
    """Reuse the archived group's *risk estimate*, without its HGC objective.

    Group discovery receives all supplied D rows. Scores and member indices
    address precisely the current-correct pool in the supplied order. The fixed
    archived configuration is used without modification or parameter search.
    """
    _require(isinstance(rows, list), 'INVALID_DISCOVERY_ROWS')
    for row in rows:
        _require(isinstance(row, dict) and set(row) == {'sample_id', 'text', 'gold_label'} and all(isinstance(v, str) and v for v in row.values()), 'INVALID_DISCOVERY_ROWS')
    _require(len({row['sample_id'] for row in rows}) == len(rows), 'DUPLICATE_SAMPLE_ID')
    gold, history = _history(np.asarray([row['gold_label'] for row in rows], dtype=str), history)
    _require(isinstance(pool_indices, list) and all(isinstance(i, Integral) and not isinstance(i, (bool, np.bool_)) and 0 <= i < len(rows) for i in pool_indices), 'INVALID_POOL')
    _require(len(set(pool_indices)) == len(pool_indices) and set(pool_indices) == set(np.flatnonzero(history[:, 2] == gold).tolist()), 'INCOMPLETE_CURRENT_CORRECT_POOL')
    groups, _, _ = _risk_groups(rows, history, gold, pool_indices, DEFAULT_HGC_CONFIG)
    scores = np.zeros(len(pool_indices), dtype=np.float64)
    for group in groups:
        scores[group['p_member_indices']] += group['normalized_weight']
    _require(np.isfinite(scores).all() and np.all((scores >= 0) & (scores <= 1 + 1e-12)), 'INVALID_GROUP_RISK')
    return np.clip(scores, 0, 1), groups


def history_features(gold, history, probabilities, labels, *, risk_scores):
    """Construct fixed 1- and 6-column designs from f0/f1/f2 only.

    ``probabilities`` has shape D x 3 x L in the explicit ``labels`` order;
    ``risk_scores`` follows the returned ascending D-index pool order. The
    past-flip denominator is the number of old-correct opportunities in the
    two observed transitions, with zero when none were available. No time
    prefix is fabricated: every row has the same complete three-version
    history and the intended supervised outcome is the next f2 -> f3 update.
    """
    gold, history = _history(gold, history)
    labels = _strings(labels, 'INVALID_CLASS_LABELS', unique=True)
    _require(len(labels) >= 2 and set(gold.tolist()) <= set(labels.tolist()) and set(history.flat) <= set(labels.tolist()), 'INVALID_CLASS_LABELS')
    try:
        scores = np.asarray(probabilities, dtype=np.float64)
        risk = np.asarray(risk_scores, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError('INVALID_FEATURE_NUMBERS') from exc
    _require(scores.shape == (len(gold), 3, len(labels)) and np.isfinite(scores).all() and np.all((scores >= 0) & (scores <= 1)) and np.allclose(scores.sum(axis=2), 1, rtol=0, atol=1e-8), 'INVALID_HISTORY_PROBABILITIES')
    _require(np.array_equal(labels[scores.argmax(axis=2)], history), 'HISTORY_PROBABILITY_LABEL_MISMATCH')
    pool = np.flatnonzero(history[:, 2] == gold)
    _require(risk.shape == (len(pool),) and np.isfinite(risk).all() and np.all((risk >= 0) & (risk <= 1)), 'INVALID_POOL_RISK_SCORES')
    previous_correct = history[:, :2] == gold[:, None]
    negative_flip = previous_correct & (history[:, 1:] != gold[:, None])
    opportunities = previous_correct.sum(axis=1)
    flip_rate = np.divide(negative_flip.sum(axis=1), opportunities, out=np.zeros(len(gold), dtype=float), where=opportunities > 0)
    label_to_index = {label: i for i, label in enumerate(labels)}
    gold_indices = np.asarray([label_to_index[label] for label in gold], dtype=int)
    gold_probabilities = scores[np.arange(len(gold))[:, None], np.arange(3)[None, :], gold_indices[:, None]]
    gold_drop = np.maximum(0., np.max(gold_probabilities[:, :-1] - gold_probabilities[:, 1:], axis=1))
    drift = np.abs(scores[:, 1:, :] - scores[:, :-1, :]).sum(axis=2).mean(axis=1) / 2
    ordered = np.sort(scores[pool, 2, :], axis=1)
    margin = (ordered[:, -1] - ordered[:, -2]).reshape(-1, 1)
    combined = np.column_stack((margin[:, 0], (~previous_correct[pool]).mean(axis=1), flip_rate[pool], gold_drop[pool], drift[pool], risk))
    return dict(pool_indices=pool.tolist(), margin_features=margin, combined_features=combined,
                margin_feature_names=list(MARGIN_FEATURE_NAMES), combined_feature_names=list(COMBINED_FEATURE_NAMES))


def _designs(features):
    _require(isinstance(features, dict) and set(METHOD_FEATURE_KEYS.values()) <= set(features), 'MISSING_FEATURE_DESIGN')
    output = {}
    for key, size in [('margin_features', 1), ('combined_features', 6)]:
        try:
            values = np.asarray(features[key], dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError('INVALID_FEATURE_DESIGN') from exc
        _require(values.ndim == 2 and values.shape[1] == size and np.isfinite(values).all(), 'INVALID_FEATURE_DESIGN')
        output[key] = values.copy()
    _require(len(output['margin_features']) == len(output['combined_features']) and np.array_equal(output['margin_features'][:, 0], output['combined_features'][:, 0]), 'INCONSISTENT_MARGIN_DESIGNS')
    return output


def _records(records):
    _require(isinstance(records, list) and len(records) >= 2, 'WHOLE_DEVELOPMENT_CHAINS_REQUIRED')
    output = []
    for record in records:
        _require(isinstance(record, dict) and isinstance(record.get('chain_id'), str) and record['chain_id'], 'INVALID_DEVELOPMENT_CHAIN')
        features = _designs(record)
        events = np.asarray(record.get('events'))
        _require(events.dtype.kind == 'b' and events.shape == (len(features['margin_features']),), 'INVALID_DEVELOPMENT_EVENTS')
        _require(len(events) > 0, 'EMPTY_DEVELOPMENT_CHAIN')
        output.append(dict(chain_id=record['chain_id'], **features, events=events.copy()))
    _require(len({r['chain_id'] for r in output}) == len(output), 'DUPLICATE_DEVELOPMENT_CHAIN')
    return sorted(output, key=lambda r: r['chain_id'].encode('utf-8'))


def chain_weights(records):
    """Each chain has mass one, equally split among its observed outcome classes.

    A no-event chain is retained with mass one on its only observed class. It
    cannot produce an AP validation fold, and does not fabricate positives.
    """
    result = []
    for record in records:
        events = np.asarray(record['events'])
        _require(events.dtype.kind == 'b' and events.ndim == 1 and len(events) > 0, 'INVALID_DEVELOPMENT_EVENTS')
        classes, counts = np.unique(events, return_counts=True)
        weights = np.empty(len(events), dtype=float)
        for value, count in zip(classes, counts):
            weights[events == value] = 1 / (len(classes) * int(count))
        result.append(weights)
    return np.concatenate(result)


def _fit_model(records, feature_key, c):
    x = np.concatenate([r[feature_key] for r in records], axis=0)
    y = np.concatenate([r['events'] for r in records])
    _require(len(np.unique(y)) == 2, 'NO_TWO_CLASS_DEVELOPMENT_FIT')
    weights = chain_weights(records)
    # Mean weight one keeps the interpretation of the common C grid stable
    # across leave-one-chain-out folds with different numbers of rows.
    weights *= len(weights) / weights.sum()
    fitted = Pipeline([('scale', StandardScaler()), ('lr', LogisticRegression(C=float(c), solver='lbfgs', max_iter=1000, tol=1e-8, class_weight=None, random_state=0))])
    with warnings.catch_warnings():
        warnings.simplefilter('error', ConvergenceWarning)
        fitted.fit(x, y, scale__sample_weight=weights, lr__sample_weight=weights)
    _require(fitted.named_steps['lr'].classes_.tolist() == [False, True], 'BINARY_CLASS_CONTRACT')
    return fitted


def model_metadata(fitted):
    """Small JSON-safe fitted-state description, suitable for a frozen record."""
    scale, lr = fitted.named_steps['scale'], fitted.named_steps['lr']
    return dict(C=float(lr.C), scale_mean=scale.mean_.tolist(), scale_scale=scale.scale_.tolist(), coefficients=lr.coef_[0].tolist(), intercept=float(lr.intercept_[0]), n_iter=int(lr.n_iter_[0]), class_order=[False, True])


def fit_development(records, c_grid=DEFAULT_C_GRID):
    """Select each model's C using the same whole-chain LOCO AP procedure.

    Returns ``(fitted_pair, provenance)``. Each fold fits its scaler and LR
    using only other chains. Validation folds without both outcome classes are
    explicitly NA and excluded for both methods; fewer than two usable folds
    aborts the diagnostic. No new-chain labels or sample-level split exists.
    """
    records = _records(records)
    _require(isinstance(c_grid, (list, tuple)) and c_grid and all(isinstance(c, Real) and not isinstance(c, (bool, np.bool_)) and np.isfinite(c) and c > 0 for c in c_grid), 'INVALID_C_GRID')
    _require(len(set(c_grid)) == len(c_grid), 'INVALID_C_GRID')
    c_grid = sorted(float(c) for c in c_grid)
    folds = []
    for held_out in records:
        train = [r for r in records if r['chain_id'] != held_out['chain_id']]
        validation_two_class = len(np.unique(held_out['events'])) == 2
        training_two_class = len(np.unique(np.concatenate([r['events'] for r in train]))) == 2
        folds.append(dict(validation_chain_id=held_out['chain_id'], train_chain_ids=[r['chain_id'] for r in train], eligible=validation_two_class and training_two_class, na_reason='ONE_CLASS_VALIDATION' if not validation_two_class else 'ONE_CLASS_TRAINING' if not training_two_class else None))
    _require(sum(f['eligible'] for f in folds) >= 2, 'INSUFFICIENT_TWO_CLASS_CHAIN_FOLDS')
    fits, methods = {}, {}
    for method, feature_key in METHOD_FEATURE_KEYS.items():
        candidates = []
        for c in c_grid:
            results = []
            for held_out, fold in zip(records, folds):
                result = dict(fold)
                if fold['eligible']:
                    train = [r for r in records if r['chain_id'] != held_out['chain_id']]
                    fitted = _fit_model(train, feature_key, c)
                    scores = fitted.predict_proba(held_out[feature_key])[:, 1]
                    result.update(average_precision=ranking_metrics(held_out['events'], scores)['average_precision'], training_feature_mean=fitted.named_steps['scale'].mean_.tolist())
                else:
                    result.update(average_precision=None, training_feature_mean=None)
                results.append(result)
            mean = float(np.mean([r['average_precision'] for r in results if r['average_precision'] is not None]))
            candidates.append(dict(C=c, macro_average_precision=mean, folds=results))
        best_score = max(candidate['macro_average_precision'] for candidate in candidates)
        selected = next(candidate for candidate in candidates if candidate['macro_average_precision'] >= best_score - 1e-12)
        fitted = _fit_model(records, feature_key, selected['C'])
        fits[method] = fitted
        methods[method] = dict(selected_C=selected['C'], selected_macro_average_precision=selected['macro_average_precision'], candidates=candidates, final_state=model_metadata(fitted))
    provenance = dict(schema_version='incremental-risk-lr-v1', purpose='CONTROLLED_ADDED_VALUE_DIAGNOSTIC', method_origin='score_enabled_Risk_LR_adaptation_not_new_algorithm', feature_names={'margin-lr': list(MARGIN_FEATURE_NAMES), 'margin-history-lr': list(COMBINED_FEATURE_NAMES)}, C_grid=c_grid, tuning='leave_one_entire_exposed_chain_out_macro_threshold_group_AP', tie_rule='smallest_C_within_1e-12_of_best_macro_AP', weighting='each_chain_mass_one_split_equally_among_observed_outcome_classes_then_global_mean_one', probability_interpretation='class-balanced diagnostic scores, not natural-prevalence calibrated probabilities', development_chains=[dict(chain_id=r['chain_id'], rows=len(r['events']), positive_events=int(r['events'].sum())) for r in records], methods=methods)
    return fits, provenance


def score_pair(fitted, features):
    _require(isinstance(fitted, dict) and set(fitted) == set(METHOD_FEATURE_KEYS), 'INVALID_FITTED_PAIR')
    designs = _designs(features)
    result = {}
    for method, key in METHOD_FEATURE_KEYS.items():
        scores = fitted[method].predict_proba(designs[key])[:, 1] if len(designs[key]) else np.empty(0, dtype=float)
        _require(np.isfinite(scores).all() and np.all((scores >= 0) & (scores <= 1)), 'INVALID_INCREMENTAL_SCORES')
        result[method] = scores
    return result


def select_pair(fitted, features, sample_ids, budgets):
    """Rank each model at the same budgets; all indices address the common P."""
    ids = _strings(sample_ids, 'INVALID_SAMPLE_IDS', unique=True)
    _require(isinstance(budgets, list) and budgets and len(set(budgets)) == len(budgets) and all(isinstance(b, Integral) and not isinstance(b, (bool, np.bool_)) and b > 0 for b in budgets), 'INVALID_BUDGETS')
    scores = score_pair(fitted, features)
    _require(all(len(s) == len(ids) for s in scores.values()), 'SCORE_SAMPLE_ID_MISMATCH')
    selections = []
    for method, values in scores.items():
        order = sorted(range(len(ids)), key=lambda i: (-float(values[i]), ids[i].encode('utf-8')))
        selections.extend(dict(method=method, seed=None, budget=int(b), indices=order[:min(int(b), len(ids))]) for b in budgets)
    return selections
