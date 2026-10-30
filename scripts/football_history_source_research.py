"""Local-only Maher research on explicitly namespaced source-reported full scores.

Consumes a saved read-only input receipt, never a database or production model
store. This is not the official TrainingDataset contract or an SPF artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from functools import partial
from pathlib import Path

import numpy as np

from scripts.football_history_research import _label_reason
from scripts.football_history_training import (
    SCORE_SCOPE,
    _batch,
    _positive,
    _scope,
    _time,
    verify_history_training_manifest,
)
from scripts.mle_trainer import _nll_maher_with_gradient
from scripts.model_artifact_identity import canonical_json_bytes

VERSION = "fqp.history-source-labels/v1"
OFFICIAL_FIELDS = frozenset(
    (
        "match_id",
        "result_match_id",
        "result_id",
        "kickoff_at",
        "match_status",
        "home_team_id",
        "away_team_id",
        "home_team_candidate_ids",
        "away_team_candidate_ids",
        "home_goals",
        "away_goals",
        "official_publish_time",
    )
)


def _hashed(payload):
    return {**payload, "sha256": hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}


def _validate_history(history):
    """A content hash detects edits; semantic checks still apply to loaded JSON."""
    verify_history_training_manifest(history)
    scope = history["scope"]
    valid = _scope(
        scope["source_competition_id"],
        scope["study_season"],
        scope["window_start"],
        scope["window_end"],
        scope["as_of"],
        scope["minimum_team_matches"],
        scope["max_matches"],
    )
    if scope != valid:
        raise ValueError("Noncanonical history scope")
    batch = _batch({**history["batch"], "state": "published"}, _time(scope["as_of"]))
    reference = history.get("season_reference", {})
    if (
        not _positive(reference.get("batch_id"))
        or not re.fullmatch(r"[0-9a-f]{64}", str(reference.get("content_sha256", "")))
        or reference.get("source_competition_id") != str(scope["source_competition_id"])
        or reference.get("source_season") != scope["study_season"]
        or _time(reference.get("imported_at")) > _time(scope["as_of"])
        or len(history["included"]) > scope["max_matches"]
    ):
        raise ValueError("Published exact-fixture season evidence is required")
    seen, events = set(), set()
    previous = None
    for ordinal, sample in enumerate(history["included"]):
        mid = sample["source_match_id"]
        kickoff = _time(sample["kickoff_at"])
        key = (kickoff, mid)
        event = (kickoff, *sorted((sample["home_team_id"], sample["away_team_id"])))
        if (
            not _positive(mid)
            or mid in seen
            or event in events
            or sample.get("ordinal") != ordinal
            or (previous is not None and key <= previous)
            or sample.get("source_namespace") != "titan007:match"
            or sample.get("study_season") != scope["study_season"]
            or sample.get("season_reference") != {**reference, "source_match_id": str(mid)}
            or sample.get("match_status") != "finished"
            or sample.get("score_scope") != SCORE_SCOPE
            or sample.get("label_source") != "football_history_matches.home_goals/away_goals"
            or any(
                not _positive(sample.get(f"{prefix}{side}_team_id"))
                for prefix in ("", "source_")
                for side in ("home", "away")
            )
            or sample["home_team_id"] == sample["away_team_id"]
            or any(
                type(sample.get(k)) is not int or sample[k] < 0
                for k in ("home_goals", "away_goals")
            )
            or any(
                sample.get(k) is not None
                for k in ("label_available_by", "source_published_at", "source_acquired_at")
            )
            or (
                sample.get("official_match_id") is not None
                and not _positive(sample["official_match_id"])
            )
            or not _time(scope["window_start"])
            <= kickoff
            < min(_time(scope["window_end"]), _time(scope["as_of"]), _time(batch["imported_at"]))
        ):
            raise ValueError("Invalid source label candidate contract")
        seen.add(mid)
        events.add(event)
        previous = key
    return seen


def build_source_label_manifest(history, official_rows):
    """Keep all source identities; official evidence corroborates, never relabels."""
    identities = _validate_history(history)
    evidence = {}
    for row in official_rows:
        mid = row.get("source_match_id")
        if not _positive(mid) or mid not in identities or mid in evidence:
            raise ValueError("Evidence needs exact unique source identities")
        evidence[mid] = row
    included, excluded = [], []
    for sample in history["included"]:
        mid = sample["source_match_id"]
        row = evidence.get(mid)
        reason = None
        official = None
        if row is None:
            reason = "official_evidence_missing"
        elif not OFFICIAL_FIELDS.issubset(row):
            reason = "official_evidence_incomplete"
        elif sample["official_match_id"] is None:
            # A null join row is positive evidence of no official link in this
            # snapshot. An omitted row is not equivalent, nor is a conflicting join.
            if any(value is not None for key, value in row.items() if key != "source_match_id"):
                reason = "unexpected_official_evidence"
        else:
            reason = _label_reason(sample, row, _time(history["scope"]["as_of"]))
            if reason is None:
                official = {
                    "match_id": row["match_id"],
                    "result_id": row["result_id"],
                    "score_basis": "history_score_equals_official_results_full_score",
                    "official_publish_time": (
                        row["official_publish_time"].isoformat()
                        if hasattr(row.get("official_publish_time"), "isoformat")
                        else row.get("official_publish_time")
                    ),
                    "timestamp_timezone": "Asia/Shanghai",
                }
        if reason:
            excluded.append({"source_match_id": mid, "reason": reason})
            continue
        included.append(
            {
                **sample,
                "label_id": f"titan007:match:{mid}",
                "history_batch_id": history["batch"]["id"],
                "history_batch_sha256": history["batch"]["content_sha256"],
                "evidence_status": "official_corroborated" if official else "source_only",
                "official_evidence": official,
            }
        )
    minimum = history["scope"]["minimum_team_matches"]
    while included:
        counts = Counter(s[f"{side}_team_id"] for s in included for side in ("home", "away"))
        sparse = {team for team, count in counts.items() if count < minimum}
        if not sparse:
            break
        retained = []
        for sample in included:
            if sparse.intersection((sample["home_team_id"], sample["away_team_id"])):
                excluded.append(
                    {
                        "source_match_id": sample["source_match_id"],
                        "reason": "team_below_minimum_history",
                    }
                )
            else:
                retained.append(sample)
        included = retained
    included = [{**s, "ordinal": i} for i, s in enumerate(included)]
    counts = Counter(s[f"{side}_team_id"] for s in included for side in ("home", "away"))
    return _hashed(
        {
            "version": VERSION,
            "target": SCORE_SCOPE,
            "history_manifest_sha256": history["sha256"],
            "scope": history["scope"],
            "batch": history["batch"],
            "season_reference": history["season_reference"],
            "included": included,
            "excluded": sorted(excluded, key=lambda s: s["source_match_id"]),
            "summary": {
                "included_count": len(included),
                "excluded_count": len(excluded),
                "official_corroborated": sum(s["official_evidence"] is not None for s in included),
                "source_only": sum(s["official_evidence"] is None for s in included),
                "team_match_counts": {str(k): v for k, v in sorted(counts.items())},
            },
            "usage": {
                "purpose": "current_observed_source_full_score_offline_research",
                "production_ready": False,
                "point_in_time_replay_verified": False,
                "spf_regulation_score_verified": False,
                "availability_basis": "unknown_source_first_visibility",
                "official_conflict_policy": "exclude_without_source_fallback",
            },
        }
    )


def _source_ridge_objective(params, *args, extra_team_ridge):
    """Add team-only shrinkage to the unchanged objective's existing 0.10 ridge."""
    value, gradient = _nll_maher_with_gradient(params, *args)
    n = args[-1]
    team_parameters = params[: 2 * n]
    value += extra_team_ridge * float(np.dot(team_parameters, team_parameters))
    gradient[: 2 * n] += 2 * extra_team_ridge * team_parameters
    return value, gradient


def _fit_source_labels(manifest, *, extra_team_ridge=0):
    """Use the existing numeric objective without fabricating TrainingDataset IDs.

    Optimizer policy mirrors the official fitter, checked on identical samples.
    Keeping this adapter outside mle_trainer preserves active artifact hashes.
    """
    if (
        isinstance(extra_team_ridge, bool)
        or not isinstance(extra_team_ridge, (int, float))
        or not math.isfinite(extra_team_ridge)
        or not 0 <= extra_team_ridge <= 100
    ):
        raise ValueError("Additional team ridge must be finite and between 0 and 100")
    samples = manifest["included"]
    teams = sorted({s[f"{side}_team_id"] for s in samples for side in ("home", "away")})
    indexes = {team: i for i, team in enumerate(teams)}
    n = len(teams)
    result = {"n_matches": len(samples), "n_teams": n}
    if extra_team_ridge:
        result["extra_team_ridge"] = extra_team_ridge
    if n < 2 or len(samples) < 10:
        return {**result, "error": "Insufficient data", "converged": False}
    from scipy.optimize import minimize

    optimized = minimize(
        partial(_source_ridge_objective, extra_team_ridge=extra_team_ridge)
        if extra_team_ridge
        else _nll_maher_with_gradient,
        np.concatenate([np.zeros(n * 2), [0.3, 0.5]]),
        args=(
            teams,
            [indexes[s["home_team_id"]] for s in samples],
            [indexes[s["away_team_id"]] for s in samples],
            [s["home_goals"] for s in samples],
            [s["away_goals"] for s in samples],
            n,
        ),
        method="L-BFGS-B",
        jac=True,
        bounds=[(-2.5, 2.5)] * (n * 2) + [(-1.0, 1.0), (-1.0, 2.0)],
        options={"maxiter": 1000, "ftol": 1e-9, "gtol": 1e-6},
    )
    finite = bool(
        np.isfinite(optimized.x).all()
        and np.isfinite(optimized.fun)
        and np.isfinite(optimized.jac).all()
    )
    if not finite:
        return {**result, "converged": False, "optimizer_message": "Non-finite optimizer output"}
    return {
        **result,
        "attack": {t: round(float(optimized.x[i]), 4) for i, t in enumerate(teams)},
        "defense": {t: round(float(optimized.x[n + i]), 4) for i, t in enumerate(teams)},
        "team_match_counts": manifest["summary"]["team_match_counts"],
        "home_advantage": round(float(optimized.x[-2]), 4),
        "league_intercept": round(float(optimized.x[-1]), 4),
        "nll": round(float(optimized.fun), 2),
        "converged": bool(optimized.success),
        "optimizer_message": str(optimized.message),
        "optimizer_iterations": int(optimized.nit),
        "optimizer_gradient_norm": float(np.linalg.norm(optimized.jac, ord=np.inf)),
    }


def fit_source_score_research(history, official_rows, *, input_receipt_sha256=None):
    manifest = build_source_label_manifest(history, official_rows)
    fit = _fit_source_labels(manifest)
    status = (
        "insufficient_data"
        if "error" in fit
        else "converged"
        if fit["converged"]
        else "not_converged"
    )
    root = Path(__file__).resolve().parents[1]
    return _hashed(
        {
            "version": "fqp.history-source-score-research/v1",
            "input_receipt_sha256": input_receipt_sha256,
            "history_candidates": history,
            "label_manifest": manifest,
            "fit": fit,
            "fit_status": status,
            "summary": {
                **manifest["summary"],
                "fitted_matches": len(manifest["included"]) if status == "converged" else 0,
                "fitted_source_only": manifest["summary"]["source_only"]
                if status == "converged"
                else 0,
            },
            "usage": {
                **manifest["usage"],
                "limitations": "Source-reported scores; no historical replay, accuracy proof, model persistence or activation.",
            },
            "optimizer_policy": "maher-existing-objective-lbfgsb-unweighted/v1",
            "source_fingerprints": {
                path: hashlib.sha256((root / path).read_bytes()).hexdigest()
                for path in (
                    "scripts/football_history_source_research.py",
                    "scripts/football_history_training.py",
                    "scripts/football_history_research.py",
                    "scripts/mle_trainer.py",
                    "scripts/model_artifact_identity.py",
                )
            },
        }
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.input.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Input receipt exceeds 32MiB")
    raw = args.input.read_bytes()
    receipt = json.loads(raw)
    result = fit_source_score_research(
        receipt["history"],
        receipt["official_rows"],
        input_receipt_sha256=hashlib.sha256(raw).hexdigest(),
    )
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {"sha256": result["sha256"], "fit_status": result["fit_status"], **result["summary"]}
        )
    )
    if result["fit_status"] != "converged":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
