"""Local retrospective chronological evaluation of source-reported full scores.

Unknown source publication times preclude historical point-in-time claims.
No database, market odds, model persistence or production activation is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.backtest_engine import (
    ResearchEvaluationConfig,
    ResearchTimeSplit,
    _research_metric_summary,
    _research_prediction_probabilities,
    build_research_time_splits,
)
from scripts.evaluation_metrics import compute_match_metrics
from scripts.football_history_source_research import (
    _fit_source_labels,
    _hashed,
    build_source_label_manifest,
)
from scripts.football_history_training import _time
from scripts.maher_goal_rate_runtime import MIN_MAHER_MATCHES
from scripts.model_artifact_identity import canonical_json_bytes
from scripts.probability_calibration import evaluate_temperature_scaling_temporal_holdout

TZ = ZoneInfo("Asia/Shanghai")
EMBARGO_HOURS = 24
METRICS = ("brier_score", "log_loss", "rps")


@dataclass(frozen=True)
class _DatedLabel:
    # The existing calendar splitter reads only business_date. No fictitious
    # official match/result identity is needed for this source-only adapter.
    business_date: date


def _business_date(sample):
    return _time(sample["kickoff_at"]).astimezone(TZ).date()


def _actual(sample):
    h, a = sample["home_goals"], sample["away_goals"]
    return "3" if h > a else "1" if h == a else "0"


def _training_manifest(labels, split, minimum):
    start = datetime.combine(split.test_start, time.min, TZ)
    cutoff = start - timedelta(hours=EMBARGO_HOURS)
    included, excluded = [], []
    for sample in labels["included"]:
        kickoff = _time(sample["kickoff_at"])
        if kickoff < cutoff:
            included.append(sample)
        elif kickoff < start:
            excluded.append(
                {"source_match_id": sample["source_match_id"], "reason": "kickoff_embargo"}
            )
    while included:
        counts = Counter(s[k] for s in included for k in ("home_team_id", "away_team_id"))
        sparse = {t for t, n in counts.items() if n < minimum}
        if not sparse:
            break
        retained = []
        for sample in included:
            if sparse.intersection((sample["home_team_id"], sample["away_team_id"])):
                excluded.append(
                    {
                        "source_match_id": sample["source_match_id"],
                        "reason": "team_below_training_minimum",
                    }
                )
            else:
                retained.append(sample)
        included = retained
    included = [{**s, "ordinal": i} for i, s in enumerate(included)]
    counts = Counter(s[k] for s in included for k in ("home_team_id", "away_team_id"))
    return _hashed(
        {
            "version": "fqp.history-source-fold-training/v1",
            "parent_label_manifest_sha256": labels["sha256"],
            "target": labels["target"],
            "train_cutoff": cutoff.isoformat(),
            "cutoff_comparison": "kickoff_strictly_before",
            "minimum_team_matches": minimum,
            "included": included,
            "excluded": sorted(excluded, key=lambda s: s["source_match_id"]),
            "summary": {
                "included_count": len(included),
                "team_match_counts": {str(k): v for k, v in sorted(counts.items())},
            },
            "availability_basis": "retrospective_kickoff_order_not_source_visibility",
        }
    )


def _evaluate_window(labels, split, config, *, extra_team_ridge=0):
    training = _training_manifest(labels, split, config.min_team_matches)
    samples = training["included"]
    fit = (
        _fit_source_labels(training, extra_team_ridge=extra_team_ridge)
        if extra_team_ridge
        else _fit_source_labels(training)
    )
    outcome_counts = Counter(_actual(s) for s in samples)
    baselines = {
        "uniform": dict.fromkeys(("3", "1", "0"), 1 / 3),
        "training_frequency": {
            k: (outcome_counts[k] + 1) / (len(samples) + 3) for k in ("3", "1", "0")
        },
    }
    scoped = [
        s for s in labels["included"] if split.test_start <= _business_date(s) <= split.test_end
    ]
    excluded, predictions = [], []
    counts = training["summary"]["team_match_counts"]
    for sample in scoped:
        reason, probabilities = None, None
        if fit.get("converged") is not True:
            reason = "model_fit_unavailable"
        elif any(str(sample[k]) not in counts for k in ("home_team_id", "away_team_id")):
            reason = "team_unseen_in_training"
        else:
            probabilities = _research_prediction_probabilities(
                fit, sample["home_team_id"], sample["away_team_id"]
            )
            if probabilities is None:
                reason = "model_rate_unavailable"
        if reason:
            excluded.append({"source_match_id": sample["source_match_id"], "reason": reason})
            continue
        actual = _actual(sample)
        vectors = {"model": probabilities, **baselines}
        metrics = {}
        for name, vector in vectors.items():
            scored = compute_match_metrics(vector, {}, actual, name)
            metrics[name] = {k: scored[k] for k in METRICS}
        predictions.append(
            {
                "source_match_id": sample["source_match_id"],
                "label_id": sample["label_id"],
                "kickoff_at": sample["kickoff_at"],
                "business_date": _business_date(sample).isoformat(),
                "home_team_id": sample["home_team_id"],
                "away_team_id": sample["away_team_id"],
                "home_goals": sample["home_goals"],
                "away_goals": sample["away_goals"],
                "evidence_status": sample["evidence_status"],
                "source_published_at": sample["source_published_at"],
                "actual_result": actual,
                "model_probabilities": probabilities,
                "metrics": metrics,
            }
        )
    metrics = {
        name: _research_metric_summary([r["metrics"][name] for r in predictions])
        for name in ("model", *baselines)
    }
    comparison = {
        name: {
            "sample_count": len(predictions),
            "log_loss_delta_model_minus_baseline": round(
                metrics["model"]["log_loss"] - metrics[name]["log_loss"], 8
            )
            if predictions
            else None,
        }
        for name in baselines
    }
    return {
        "window_index": split.index,
        "final_holdout": split.final_holdout,
        "test_start": split.test_start.isoformat(),
        "test_end": split.test_end.isoformat(),
        "train_cutoff": training["train_cutoff"],
        "training_manifest": training,
        "fit": fit,
        "fit_sha256": hashlib.sha256(canonical_json_bytes(fit)).hexdigest(),
        "baseline_probabilities": baselines,
        "candidate_count": len(scoped),
        "sample_count": len(predictions),
        "coverage": len(predictions) / len(scoped) if scoped else None,
        "metrics": metrics,
        "comparison": comparison,
        "predictions": predictions,
        "excluded": excluded,
        "excluded_by_reason": dict(sorted(Counter(s["reason"] for s in excluded).items())),
    }


def evaluate_source_score_research(
    history, official_rows, *, config=None, input_receipt_sha256=None
):
    """Fixed-policy rolling blocks, then one final block; no tuning or promotion."""
    config = config or ResearchEvaluationConfig(fold_count=2, test_window_days=7, holdout_days=7)
    if not isinstance(config, ResearchEvaluationConfig):
        raise TypeError("Expected ResearchEvaluationConfig")
    settings = {
        k: getattr(config, k)
        for k in (
            "fold_count",
            "test_window_days",
            "holdout_days",
            "min_team_matches",
            "max_matches",
            "max_report_bytes",
        )
    }
    if (
        any(type(v) is not int for v in settings.values())
        or not MIN_MAHER_MATCHES <= config.min_team_matches <= 100
    ):
        raise ValueError("Integer settings and the existing runtime team minimum are required")
    labels = build_source_label_manifest(history, official_rows)
    if len(labels["included"]) > config.max_matches:
        raise ValueError("Source labels exceed configured max_matches")
    dated = [_DatedLabel(_business_date(s)) for s in labels["included"]]
    # Existing splitter accesses only business_date; its annotation is narrower
    # than this adapter. Do not forge official ResearchMatch identities to fit it.
    splits = build_research_time_splits(dated, config)
    windows = [_evaluate_window(labels, split, config) for split in splits]
    complete = all(w["sample_count"] > 0 for w in windows)
    # Nonempty, partially covered windows remain evaluated, with explicit counts.
    predictions = [r for w in windows for r in w["predictions"]]
    root = Path(__file__).resolve().parents[1]
    fingerprints = {
        path: hashlib.sha256((root / path).read_bytes()).hexdigest()
        for path in (
            "scripts/football_history_source_evaluation.py",
            "scripts/football_history_source_research.py",
            "scripts/football_history_training.py",
            "scripts/football_history_research.py",
            "scripts/backtest_engine.py",
            "scripts/mle_trainer.py",
            "scripts/maher_goal_rate_runtime.py",
            "scripts/poisson_model.py",
            "scripts/evaluation_metrics.py",
            "scripts/market_metric_validation.py",
            "scripts/model_artifact_identity.py",
        )
    }
    report = _hashed(
        {
            "version": "fqp.history-source-time-split/v1",
            "evaluation_mode": "retrospective_current_observed_kickoff_split",
            "evaluation_status": "evaluated" if complete else "incomplete",
            "input_receipt_sha256": input_receipt_sha256,
            "label_manifest": labels,
            "source_fingerprints": fingerprints,
            "config": {
                **settings,
                "timezone": "Asia/Shanghai",
                "kickoff_embargo_hours": EMBARGO_HOURS,
            },
            "policy": {
                "model": "maher-existing-objective-lbfgsb-unweighted/v1",
                "probability": "existing_runtime_goal_rates_and_0_to_7_renormalized_poisson",
                "training_frequency_baseline": "training_retained_outcomes_add_one_smoothing",
                "selection": "fixed_configuration_no_model_selection_or_tuning",
                "holdout": "single_evaluation_this_invocation_now_viewed_not_reusable_as_unseen",
                "previously_sealed_blind_holdout": False,
                "aggregation": "pooled_nonoverlapping_test_rows_not_average_of_fold_means",
                "metrics": "multiclass_Brier_sum_LogLoss_RPS_lower_is_better",
            },
            "folds": windows[:-1],
            "final_holdout": windows[-1],
            "summary": {
                "candidate_count": sum(w["candidate_count"] for w in windows),
                "scored_count": len(predictions),
                "excluded_count": sum(len(w["excluded"]) for w in windows),
                "scored_official_corroborated": sum(
                    r["evidence_status"] == "official_corroborated" for r in predictions
                ),
                "scored_source_only": sum(
                    r["evidence_status"] == "source_only" for r in predictions
                ),
            },
            "aggregate_metrics": {
                name: _research_metric_summary([r["metrics"][name] for r in predictions])
                for name in ("model", "uniform", "training_frequency")
            },
            "usage": {
                **labels["usage"],
                "limitations": "Retrospective frozen batch; unknown first visibility, unverified regulation scores, no roster/transfer/injury model, no prospective performance or profitability proof.",
            },
            "market_comparison": {
                "status": "not_evaluated",
                "reason": "no_verified_prematch_odds_in_this_input",
            },
            "claims_model_beats_market": False,
            "production_model_writes": 0,
        }
    )
    if len(canonical_json_bytes(report)) > config.max_report_bytes:
        raise ValueError("Evaluation report exceeds configured size limit")
    return report


def diagnose_source_score_training(
    history, official_rows, *, development_cutoff, input_receipt_sha256=None
):
    """Explore a fixed ridge grid strictly inside an explicit development cutoff.

    These windows select parameters, so their losses are development losses,
    never independent validation of the winner. Later labels are not scored.
    """
    cutoff = _time(development_cutoff).astimezone(TZ)
    if cutoff.timetz().replace(tzinfo=None) != time.min:
        raise ValueError("Development cutoff must be an explicit Beijing midnight")
    if cutoff > _time(history["scope"]["as_of"]):
        raise ValueError("Development cutoff is after input review time")
    config = ResearchEvaluationConfig(fold_count=1, test_window_days=7, holdout_days=7)
    labels = build_source_label_manifest(history, official_rows)
    # The reused manifest builder subtracts 24h; offset the synthetic start so
    # this outer boundary is exactly the caller's explicit strict cutoff.
    boundary = cutoff.date() + timedelta(days=1)
    development = _training_manifest(
        labels, ResearchTimeSplit(None, boundary, boundary), config.min_team_matches
    )
    splits = build_research_time_splits(
        [_DatedLabel(_business_date(s)) for s in development["included"]], config
    )
    candidates = []
    for strength in (0, 1, 5):
        windows = [
            _evaluate_window(development, split, config, extra_team_ridge=strength)
            for split in splits
        ]
        for index, window in enumerate(windows):
            window.update(window_index=index, final_holdout=False, role="development_selection")
        predictions = [p for w in windows for p in w["predictions"]]
        candidates.append(
            {
                "extra_team_ridge": strength,
                "development_windows": windows,
                "fully_paired": all(w["sample_count"] == w["candidate_count"] > 0 for w in windows),
                "aggregate_metrics": {
                    name: _research_metric_summary([p["metrics"][name] for p in predictions])
                    for name in ("model", "uniform", "training_frequency")
                },
            }
        )
    # All candidates must cover the same fixtures; otherwise losses are not a
    # valid paired selection criterion. A failed candidate blocks selection.
    ids = [
        [p["source_match_id"] for w in c["development_windows"] for p in w["predictions"]]
        for c in candidates
    ]
    complete = (
        all(c["fully_paired"] for c in candidates)
        and all(current == ids[0] for current in ids)
        and len(ids[0]) >= 10
    )
    selected = None
    if complete:
        best_loss = min(c["aggregate_metrics"]["model"]["log_loss"] for c in candidates)
        selected = next(
            c for c in candidates if c["aggregate_metrics"]["model"]["log_loss"] <= best_loss + 1e-8
        )
    fit, strength, predictions = None, None, []
    calibration = {"status": "selection_unavailable"}
    status = "incomplete"
    if selected is not None:
        strength = selected["extra_team_ridge"]
        fit = _fit_source_labels(development, extra_team_ridge=strength)
        status = "selected_for_research" if fit.get("converged") is True else "refit_failed"
        predictions = [p for w in selected["development_windows"] for p in w["predictions"]]
        profile = evaluate_temperature_scaling_temporal_holdout(
            [(p["model_probabilities"], p["actual_result"]) for p in predictions]
        )
        calibration = {
            "status": "exploratory_profile" if profile else "insufficient_samples",
            "available_out_of_fold_samples": len(predictions),
            "minimum_training_samples": 100,
            "minimum_validation_samples": 25,
            "profile": profile,
            "applied": False,
            "independent_of_ridge_selection": False,
        }
    counts = development["summary"]["team_match_counts"]
    root = Path(__file__).resolve().parents[1]
    report = _hashed(
        {
            "version": "fqp.history-source-training-diagnosis/v1",
            "diagnosis_status": status,
            "input_receipt_sha256": input_receipt_sha256,
            "development_cutoff": cutoff.isoformat(),
            "development_manifest": development,
            "later_labels_not_evaluated": sum(
                _time(s["kickoff_at"]) >= cutoff for s in labels["included"]
            ),
            "policy": {
                "existing_base_team_ridge": 0.10,
                "extra_team_ridge_grid": [0, 1, 5],
                "penalized_parameters": "team_attack_and_defense_only",
                "selection": "paired_development_LogLoss_tie_1e-8_smaller_ridge",
                "minimum_paired_development_matches": 10,
                "windows": "two_seven_day_development_windows_24h_embargo_minimum5",
                "independent_validation": False,
                "previously_viewed_development_data": True,
                "later_labels_evaluated": False,
                "production_promotion": False,
            },
            "candidates": candidates,
            "selected_extra_team_ridge": strength,
            "selected_refit": fit,
            "selected_refit_sha256": hashlib.sha256(canonical_json_bytes(fit)).hexdigest()
            if fit is not None
            else None,
            "calibration": calibration,
            "uncertainty": {
                "confidence_intervals": "not_estimated",
                "team_match_counts": counts,
                "minimum_team_matches": min(counts.values()) if counts else None,
                "maximum_team_matches": max(counts.values()) if counts else None,
                "development_predictions_above_80_percent": sum(
                    max(p["model_probabilities"].values()) > 0.8 for p in predictions
                ),
                "interpretation": "Descriptive counts, not calibrated confidence or effective sample size.",
            },
            "source_fingerprints": {
                path: hashlib.sha256((root / path).read_bytes()).hexdigest()
                for path in (
                    "scripts/football_history_source_evaluation.py",
                    "scripts/football_history_source_research.py",
                    "scripts/football_history_training.py",
                    "scripts/football_history_research.py",
                    "scripts/backtest_engine.py",
                    "scripts/mle_trainer.py",
                    "scripts/maher_goal_rate_runtime.py",
                    "scripts/poisson_model.py",
                    "scripts/evaluation_metrics.py",
                    "scripts/market_metric_validation.py",
                    "scripts/model_artifact_identity.py",
                    "scripts/probability_calibration.py",
                )
            },
            "usage": {
                **labels["usage"],
                "purpose": "training_side_exploration_not_winner_performance_validation",
                "limitations": "Unknown first availability and regulation score scope; current-season score-only model, no roster/transfer/injury dynamics; no prospective or market advantage claim.",
            },
            "production_model_writes": 0,
        }
    )
    if len(canonical_json_bytes(report)) > config.max_report_bytes:
        raise ValueError("Training diagnosis exceeds configured size limit")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--development-cutoff", help="Explicit Beijing-midnight training diagnosis boundary"
    )
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.input.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Input receipt exceeds 32MiB")
    raw = args.input.read_bytes()
    receipt = json.loads(raw)
    kwargs = {"input_receipt_sha256": hashlib.sha256(raw).hexdigest()}
    if args.development_cutoff:
        result = diagnose_source_score_training(
            receipt["history"],
            receipt["official_rows"],
            development_cutoff=args.development_cutoff,
            **kwargs,
        )
    else:
        result = evaluate_source_score_research(
            receipt["history"], receipt["official_rows"], **kwargs
        )
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    if args.development_cutoff:
        print(
            json.dumps(
                {k: result[k] for k in ("sha256", "diagnosis_status", "selected_extra_team_ridge")}
            )
        )
        success = result["diagnosis_status"] == "selected_for_research"
    else:
        print(
            json.dumps(
                {
                    "sha256": result["sha256"],
                    "evaluation_status": result["evaluation_status"],
                    **result["summary"],
                }
            )
        )
        success = result["evaluation_status"] == "evaluated"
    if not success:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
