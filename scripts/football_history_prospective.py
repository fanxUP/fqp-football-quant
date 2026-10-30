"""Local frozen source-score research: freeze, pre-kickoff predict, later score.

No database, network, training, official model identity or production writes.
Local clocks and content hashes are not external timestamp attestations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.backtest_engine import (
    ResearchTimeSplit,
    _research_metric_summary,
    _research_prediction_probabilities,
)
from scripts.evaluation_metrics import compute_match_metrics
from scripts.football_history_source_evaluation import _actual, _training_manifest
from scripts.football_history_source_research import _hashed, build_source_label_manifest
from scripts.football_history_training import SCORE_SCOPE, _positive, _time
from scripts.maher_goal_rate_runtime import MIN_MAHER_MATCHES
from scripts.model_artifact_identity import canonical_json_bytes
from scripts.model_prediction_run_identity import (
    _reject_json_constant,
    _unique_json_object,
    build_run_manifest,
    content_sha256,
    fingerprint_runtime_sources,
    verify_prediction_run_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "fqp.history-source-"
SOURCE_PATHS = (
    "scripts/football_history_prospective.py",
    "scripts/football_history_source_evaluation.py",
    "scripts/football_history_source_research.py",
    "scripts/football_history_training.py",
    "scripts/football_history_research.py",
    "scripts/model_prediction_run_identity.py",
    "scripts/model_artifact_identity.py",
    "scripts/backtest_engine.py",
    "scripts/maher_goal_rate_runtime.py",
    "scripts/poisson_model.py",
    "scripts/evaluation_metrics.py",
    "scripts/market_metric_validation.py",
    "scripts/mle_trainer.py",
    "scripts/probability_calibration.py",
)
USAGE = {
    "production_ready": False,
    "spf_regulation_score_verified": False,
    "historical_point_in_time_replay_verified": False,
    "purpose": "local_frozen_source_full_score_prospective_research",
    "limitations": "Local clock/input receipt evidence, not externally attested. Unknown original publication; no roster/transfer/injury dynamics, calibrated confidence or market advantage proof.",
}


def _verify(value, expected, version):
    if (
        not isinstance(value, dict)
        or value.get("version") != PREFIX + version + "/v1"
        or not re.fullmatch(r"[0-9a-f]{64}", str(expected))
        or value.get("sha256") != expected
        or content_sha256({k: v for k, v in value.items() if k != "sha256"}) != expected
    ):
        raise ValueError("Research content identity or version mismatch")


def _clock(now):
    return datetime.now(UTC) if now is None else _time(now)


def freeze_candidate(diagnosis, receipt, *, expected_sha256, receipt_sha256, now=None):
    """Pin the reviewed development fit without refitting or consulting later results."""
    _verify(diagnosis, expected_sha256, "training-diagnosis")
    at = _clock(now)
    observed = _time(receipt["checked_at"])
    history = receipt["history"]
    if (
        receipt_sha256 != diagnosis["input_receipt_sha256"]
        or observed > at
        or _time(history["scope"]["as_of"]) > observed
        or diagnosis["diagnosis_status"] != "selected_for_research"
        or diagnosis["calibration"].get("applied") is not False
    ):
        raise ValueError("Selected diagnosis and actual observed input receipt required")
    sources = diagnosis["source_fingerprints"]
    if (
        not sources
        or not set(sources).issubset(SOURCE_PATHS)
        or fingerprint_runtime_sources(ROOT, list(sources))["files"] != sources
    ):
        raise ValueError("Diagnosis source fingerprints changed")
    labels = build_source_label_manifest(history, receipt["official_rows"])
    cutoff = _time(diagnosis["development_cutoff"])
    # Reuse the same explicit boundary adapter as training diagnosis.
    from scripts.football_history_source_evaluation import TZ

    boundary = cutoff.astimezone(TZ).date() + timedelta(days=1)
    training = _training_manifest(
        labels, ResearchTimeSplit(None, boundary, boundary), MIN_MAHER_MATCHES
    )
    fit = diagnosis["selected_refit"]
    counts = training["summary"]["team_match_counts"]
    if (
        training != diagnosis["development_manifest"]
        or fit.get("converged") is not True
        or content_sha256(fit) != diagnosis["selected_refit_sha256"]
        or fit.get("extra_team_ridge", 0) != diagnosis["selected_extra_team_ridge"]
        or fit.get("n_matches") != len(training["included"])
        or fit.get("team_match_counts") != counts
        or not counts
        or min(counts.values()) < MIN_MAHER_MATCHES
        or {str(k) for k in fit["attack"]} != set(counts)
        or {str(k) for k in fit["defense"]} != set(counts)
        or cutoff > observed
        or at >= _time(history["scope"]["window_end"])
    ):
        raise ValueError("Selected parameters do not match the reviewed development inputs")
    outcomes = Counter(_actual(s) for s in training["included"])
    return _hashed(
        {
            "version": PREFIX + "frozen-candidate/v1",
            "frozen_at": at.isoformat(),
            "observation_end": min(
                at + timedelta(days=14), _time(history["scope"]["window_end"])
            ).isoformat(),
            "diagnosis_sha256": expected_sha256,
            "input_receipt_sha256": receipt_sha256,
            "input_observed_at": observed.isoformat(),
            "source_scope": history["scope"],
            "training_manifest": training,
            "fit": fit,
            "fit_sha256": content_sha256(fit),
            "selected_extra_team_ridge": diagnosis["selected_extra_team_ridge"],
            "baseline_probabilities": {
                "uniform": dict.fromkeys(("3", "1", "0"), 1 / 3),
                "training_frequency": {
                    k: (outcomes[k] + 1) / (len(training["included"]) + 3) for k in ("3", "1", "0")
                },
            },
            "policy": {
                "selection": "all_supplied_eligible_fixtures_with_exclusions_reported",
                "model_updates": "none_during_observation",
                "calibration_applied": False,
                "target": SCORE_SCOPE,
                "automatic_promotion": False,
            },
            "source_files": fingerprint_runtime_sources(ROOT, SOURCE_PATHS)["files"],
            "usage": USAGE,
        }
    )


def _fixture_identity(row):
    if (
        any(not _positive(row.get(k)) for k in ("source_match_id", "home_team_id", "away_team_id"))
        or row["home_team_id"] == row["away_team_id"]
    ):
        raise ValueError("Invalid fixture identity")
    kickoff = _time(row.get("kickoff_at"))
    return {k: row[k] for k in ("source_match_id", "home_team_id", "away_team_id")} | {
        "kickoff_at": kickoff.isoformat()
    }


def _receipt_rows(receipt, scope, at):
    if (
        receipt.get("version") != PREFIX + "fixtures/v1"
        or receipt.get("source_name") != "titan007"
        or type(receipt.get("source_competition_id")) is not int
        or receipt["source_competition_id"] != scope["source_competition_id"]
        or receipt.get("study_season") != scope["study_season"]
        or _time(receipt.get("captured_at")) > at
    ):
        raise ValueError("Exact source scope and non-future fixture observation required")
    batch = receipt.get("batch", {})
    if (
        batch.get("state") != "published"
        or not _positive(batch.get("id"))
        or not re.fullmatch(r"[0-9a-f]{64}", str(batch.get("content_sha256")))
        or _time(batch.get("imported_at")) > _time(receipt["captured_at"])
    ):
        raise ValueError("Published fixture batch identity required")
    rows = receipt.get("fixtures")
    if not isinstance(rows, list) or len(rows) > 5000 or any(not isinstance(r, dict) for r in rows):
        raise ValueError("Fixture receipt must contain at most 5000 rows")
    seen, events = set(), set()
    for row in rows:
        mid = row.get("source_match_id")
        if not _positive(mid):
            raise ValueError("Positive source match identity required")
        if mid in seen:
            raise ValueError("Duplicate source identity")
        seen.add(mid)
        try:
            identity = _fixture_identity(row)
        except ValueError:
            continue  # Invalid identities are retained as exclusions below.
        event = (
            identity["kickoff_at"],
            *sorted((identity["home_team_id"], identity["away_team_id"])),
        )
        if event in events:
            raise ValueError("Duplicate fixture event")
        events.add(event)
    return sorted(rows, key=lambda r: r["source_match_id"])


def predict_fixtures(candidate, receipt, *, expected_sha256, now=None):
    """Actual CLI clock, fixed parameters, all eligible supplied fixtures, no labels."""
    _verify(candidate, expected_sha256, "frozen-candidate")
    at = _clock(now)
    if (
        at < _time(candidate["frozen_at"])
        or candidate["source_files"] != fingerprint_runtime_sources(ROOT, SOURCE_PATHS)["files"]
    ):
        raise ValueError("Candidate clock or runtime sources changed")
    scope = candidate["source_scope"]
    rows = _receipt_rows(receipt, scope, at)
    trained = {r["source_match_id"] for r in candidate["training_manifest"]["included"]}
    counts = candidate["fit"]["team_match_counts"]
    predictions, excluded = [], []
    for row in rows:
        reason, identity, probabilities = None, None, None
        try:
            identity = _fixture_identity(row)
        except ValueError:
            reason = "invalid_fixture_identity"
        if identity is not None:
            kickoff = _time(identity["kickoff_at"])
            if kickoff <= at:
                reason = "already_started"
            elif kickoff >= _time(candidate["observation_end"]) or kickoff < _time(
                scope["window_start"]
            ):
                reason = "outside_observation_window"
            elif row.get("status") != "scheduled" or any(
                row.get(k) is not None for k in ("home_goals", "away_goals")
            ):
                reason = "not_scheduled_or_has_score"
            elif row["source_match_id"] in trained:
                reason = "seen_in_training"
            elif any(str(row[k]) not in counts for k in ("home_team_id", "away_team_id")):
                reason = "team_unseen_in_training"
            else:
                probabilities = _research_prediction_probabilities(
                    candidate["fit"], row["home_team_id"], row["away_team_id"]
                )
                if probabilities is None:
                    reason = "model_rate_unavailable"
        if reason:
            excluded.append({"source_match_id": row["source_match_id"], "reason": reason})
        else:
            predictions.append(
                {**identity, "predicted_at": at.isoformat(), "model_probabilities": probabilities}
            )
    # Receipt hashing is order-independent but preserves every supplied row.
    input_manifest = {
        "fixture_receipt_sha256": content_sha256({**receipt, "fixtures": rows}),
        "batch": receipt["batch"],
        "captured_at": _time(receipt["captured_at"]).isoformat(),
        "predicted_at": at.isoformat(),
        "fixtures": [
            {k: v for k, v in p.items() if k != "model_probabilities"} for p in predictions
        ],
    }
    run = build_run_manifest(
        release_id=f"local-research:{expected_sha256}",
        source_root=ROOT,
        source_paths=SOURCE_PATHS,
        model_manifest=[
            {
                "model_name": "history_source_maher_research",
                "candidate_sha256": expected_sha256,
                "parameters_sha256": candidate["fit_sha256"],
                "training_manifest_sha256": candidate["training_manifest"]["sha256"],
            }
        ],
        input_manifest=input_manifest,
    )
    completed = _clock(now)
    retained = []
    for prediction in predictions:
        if _time(prediction["kickoff_at"]) <= completed:
            excluded.append(
                {
                    "source_match_id": prediction["source_match_id"],
                    "reason": "started_during_computation",
                }
            )
        else:
            retained.append(prediction)
    predictions = retained
    excluded.sort(key=lambda row: row["source_match_id"])
    # Keep the source fingerprint from the actual run builder; rebind the final
    # fixture list after checking the clock, without another slow filesystem read.
    run["input_manifest"].update(
        calculated_at=completed.isoformat(),
        fixtures=[{k: v for k, v in p.items() if k != "model_probabilities"} for p in predictions],
    )
    run["sha256"] = content_sha256({k: v for k, v in run.items() if k != "sha256"})
    return _hashed(
        {
            "version": PREFIX + "forecast/v1",
            "forecast_status": "recorded" if predictions else "no_eligible_fixtures",
            "candidate_sha256": expected_sha256,
            "predicted_at": at.isoformat(),
            "calculated_at": completed.isoformat(),
            "source_scope": scope,
            "run_manifest": run,
            "baseline_probabilities": candidate["baseline_probabilities"],
            "predictions": predictions,
            "excluded": excluded,
            "summary": {
                "supplied": len(rows),
                "predicted": len(predictions),
                "excluded": len(excluded),
            },
            "usage": USAGE,
        }
    )


def score_forecast(forecast, receipt, *, expected_sha256, now=None):
    """Score only exact later source-full-score matches; never fit or calibrate."""
    _verify(forecast, expected_sha256, "forecast")
    at = _clock(now)
    run = forecast["run_manifest"]
    verify_prediction_run_manifest(
        run_manifest=run,
        run_manifest_sha256=run["sha256"],
        model_manifest=run["model_manifest"],
        model_manifest_sha256=content_sha256(run["model_manifest"]),
        input_manifest=run["input_manifest"],
        input_manifest_sha256=content_sha256(run["input_manifest"]),
    )
    rows = _receipt_rows(receipt, forecast["source_scope"], at)
    observed = _time(receipt["captured_at"])
    if observed <= _time(forecast["calculated_at"]):
        raise ValueError("Results must be independently observed after prediction")
    by_id = {r["source_match_id"]: r for r in rows}
    scored, pending, excluded = [], [], []
    for prediction in forecast["predictions"]:
        mid = prediction["source_match_id"]
        row, reason = by_id.get(mid), None
        if row is None:
            pending.append({"source_match_id": mid, "reason": "result_missing"})
            continue
        try:
            identity = _fixture_identity(row)
        except ValueError:
            identity = None
        if identity != {
            k: prediction[k]
            for k in ("source_match_id", "home_team_id", "away_team_id", "kickoff_at")
        }:
            reason = "fixture_identity_changed"
        elif row.get("status") != "finished":
            pending.append({"source_match_id": mid, "reason": "result_not_finished"})
            continue
        elif receipt.get("score_scope") != SCORE_SCOPE:
            reason = "score_scope_unverified"
        elif _time(row["kickoff_at"]) >= observed:
            reason = "result_observed_before_kickoff"
        elif any(type(row.get(k)) is not int or row[k] < 0 for k in ("home_goals", "away_goals")):
            reason = "invalid_score"
        if reason:
            excluded.append({"source_match_id": mid, "reason": reason})
            continue
        actual = _actual(row)
        vectors = {"model": prediction["model_probabilities"], **forecast["baseline_probabilities"]}
        metrics = {
            name: {
                k: v
                for k, v in compute_match_metrics(vector, {}, actual).items()
                if k in ("brier_score", "log_loss", "rps")
            }
            for name, vector in vectors.items()
        }
        scored.append(
            {
                **identity,
                "home_goals": row["home_goals"],
                "away_goals": row["away_goals"],
                "actual_result": actual,
                "model_probabilities": prediction["model_probabilities"],
                "metrics": metrics,
            }
        )
    return _hashed(
        {
            "version": PREFIX + "prospective-score/v1",
            "forecast_sha256": expected_sha256,
            "candidate_sha256": forecast["candidate_sha256"],
            "evaluated_at": at.isoformat(),
            "result_receipt_sha256": content_sha256({**receipt, "fixtures": rows}),
            "result_batch": receipt["batch"],
            "result_observed_at": observed.isoformat(),
            "evaluation_status": "partially_scored"
            if scored and pending
            else "evaluated"
            if scored
            else "awaiting_results"
            if pending
            else "unscorable",
            "summary": {
                "predicted": len(forecast["predictions"]),
                "scored": len(scored),
                "pending": len(pending),
                "excluded": len(excluded),
            },
            "metrics": {
                name: _research_metric_summary([p["metrics"][name] for p in scored])
                for name in ("model", "uniform", "training_frequency")
            },
            "scored": scored,
            "pending": pending,
            "excluded": excluded,
            "promotion_allowed": False,
            "usage": USAGE,
        }
    )


def _load(path):
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Input exceeds 32MiB")
    raw = path.read_bytes()
    return json.loads(
        raw, object_pairs_hook=_unique_json_object, parse_constant=_reject_json_constant
    ), hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "predict", "score"))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--sha256", required=True, help="Previously recorded canonical input identity"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    value, _ = _load(args.input)
    receipt, receipt_digest = _load(args.receipt)
    kwargs = {"expected_sha256": args.sha256}
    if args.mode == "freeze":
        kwargs["receipt_sha256"] = receipt_digest
    result = {"freeze": freeze_candidate, "predict": predict_fixtures, "score": score_forecast}[
        args.mode
    ](value, receipt, **kwargs)
    if len(canonical_json_bytes(result)) > 5_000_000:
        raise ValueError("Output exceeds 5MB")
    with args.output.open("x", encoding="utf-8") as handle:
        try:
            handle.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            handle.flush()
            if args.mode == "predict" and any(
                _time(p["kickoff_at"]) <= _clock(None) for p in result["predictions"]
            ):
                raise ValueError(
                    "Fixture started before local output finished; no forecast retained"
                )
        except BaseException:
            # This call exclusively created the file. Remove only its failed
            # partial output; pre-existing files were rejected by open('x').
            args.output.unlink()
            raise
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k in ("sha256", "forecast_status", "evaluation_status", "summary", "frozen_at")
            }
        )
    )
    if result.get("forecast_status") == "no_eligible_fixtures":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
