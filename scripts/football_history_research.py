"""Offline Maher research on history-linked, corroborated official score labels.

This entrypoint never stores/activates model versions. Unknown label publication
times permit a current-observed fit, never a historical point-in-time backtest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import RealDictCursor

from scripts.football_history_training import (
    _positive,
    _scope,
    _time,
    build_history_training_manifest,
    verify_history_training_manifest,
)
from scripts.mle_trainer import fit_maher_poisson_dataset
from scripts.model_artifact_identity import canonical_json_bytes, training_manifest_sha256
from scripts.training_manifest import CandidateMatch, TrainingDataset, build_training_dataset

OFFICIAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _official_time(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.tzinfo is not None:
        raise ValueError("Official TIMESTAMP must be business-local and timezone-naive")
    return value


def _label_reason(sample, row, as_of):
    if sample["official_match_id"] is None:
        return "official_link_missing"
    if row is None or row.get("result_id") is None:
        return "official_result_missing"
    if not _positive(row.get("result_id")):
        return "official_score_invalid"
    if (
        row.get("match_id") != sample["official_match_id"]
        or row.get("result_match_id") != row["match_id"]
        or any(
            row.get(f"{side}_team_id") != sample[f"{side}_team_id"]
            or row.get(f"{side}_team_candidate_ids") != [sample[f"{side}_team_id"]]
            for side in ("home", "away")
        )
    ):
        return "official_identity_mismatch"
    try:
        kickoff = _official_time(row.get("kickoff_at")).replace(tzinfo=OFFICIAL_TIMEZONE)
        if kickoff.astimezone(UTC) != _time(sample["kickoff_at"]):
            return "official_identity_mismatch"
    except ValueError, TypeError:
        return "official_identity_mismatch"
    if str(row.get("match_status", "")).lower() != "settled":
        return "official_not_settled"
    if any(type(row.get(k)) is not int or row[k] < 0 for k in ("home_goals", "away_goals")):
        return "official_score_invalid"
    if any(row[k] != sample[k] for k in ("home_goals", "away_goals")):
        return "official_score_conflict"
    if row.get("official_publish_time") is not None:
        published = _official_time(row["official_publish_time"]).replace(tzinfo=OFFICIAL_TIMEZONE)
        if published.astimezone(UTC) > as_of:
            return "official_label_after_review"
    return None


def build_history_official_dataset(
    history: Mapping[str, Any], official_rows
) -> tuple[TrainingDataset, dict[str, Any]]:
    """Adapt only real official identities; history retains a separate provenance map."""
    verify_history_training_manifest(history)
    rows: dict[int, Mapping[str, Any]] = {}
    for row in official_rows:
        mid = row.get("source_match_id")
        if not _positive(mid) or mid in rows or len(rows) >= 5000:
            raise ValueError("Official evidence needs bounded unique source match identities")
        rows[mid] = row
    as_of = _time(history["scope"]["as_of"])
    minimum = history["scope"]["minimum_team_matches"]
    accepted, excluded = [], []
    for sample in history["included"]:
        row = rows.get(sample["source_match_id"])
        reason = _label_reason(sample, row, as_of)
        if reason:
            excluded.append({"source_match_id": sample["source_match_id"], "reason": reason})
        elif row is not None:
            accepted.append((sample, row))
    # Recheck on the final *official subset*, including cascading sparse teams.
    while accepted:
        counts = Counter(
            sample[f"{side}_team_id"] for sample, _ in accepted for side in ("home", "away")
        )
        sparse = {team for team, count in counts.items() if count < minimum}
        if not sparse:
            break
        retained = []
        for sample, row in accepted:
            if sparse.intersection((sample["home_team_id"], sample["away_team_id"])):
                excluded.append(
                    {
                        "source_match_id": sample["source_match_id"],
                        "reason": "team_below_minimum_history",
                    }
                )
            else:
                retained.append((sample, row))
        accepted = retained
    candidates = [
        CandidateMatch(
            match_id=row["match_id"],
            result_id=row["result_id"],
            kickoff_at=_official_time(row["kickoff_at"]),
            home_team_id=row["home_team_id"],
            away_team_id=row["away_team_id"],
            home_goals=row["home_goals"],
            away_goals=row["away_goals"],
            match_status=row["match_status"],
            official_publish_time=(
                _official_time(row["official_publish_time"])
                if row.get("official_publish_time") is not None
                else None
            ),
        )
        for _, row in accepted
    ]
    # No cutoff is invented: these labels are observed now, not known historically.
    dataset = build_training_dataset(candidates, min_matches=minimum, cutoff_at=None)
    training_manifest_sha256(dataset.manifest.to_dict())
    review = {
        "included": [
            {
                "source_match_id": sample["source_match_id"],
                "official_match_id": row["match_id"],
                "official_result_id": row["result_id"],
                "score_basis": "history_score_equals_official_results_full_score",
            }
            for sample, row in accepted
        ],
        "excluded": sorted(excluded, key=lambda r: r["source_match_id"]),
    }
    return dataset, review


def fit_history_official_research(history, official_rows):
    """Reuse the real fitter, emitting a research bundle without activation identity."""
    dataset, review = build_history_official_dataset(history, official_rows)
    fit = fit_maher_poisson_dataset(dataset)
    if fit.pop("training_manifest") != dataset.manifest.to_dict():
        raise ValueError("Fitter inputs differ from the reviewed training manifest")
    for field in ("training_start_date", "training_end_date"):
        value = fit.get(field)
        if value is not None:
            fit[field] = value.isoformat()
    fit_status = (
        "insufficient_data"
        if "error" in fit
        else "converged"
        if fit["converged"]
        else "not_converged"
    )
    root = Path(__file__).resolve().parents[1]
    result = {
        "version": "fqp.history-official-research/v1",
        "history_candidates": history,
        "label_review": review,
        "training_manifest": dataset.manifest.to_dict(),
        "fit": fit,
        "fit_status": fit_status,
        "summary": {
            "history_candidates": len(history["included"]),
            "eligible_matches": len(dataset.samples),
            "fitted_matches": len(dataset.samples) if fit_status == "converged" else 0,
            "official_publication_unknown": sum(
                sample.official_publish_time is None for sample in dataset.samples
            ),
            "excluded_by_reason": dict(
                sorted(Counter(r["reason"] for r in review["excluded"]).items())
            ),
        },
        "usage": {
            "purpose": "current_observed_offline_official_score_crosscheck",
            "production_ready": False,
            "point_in_time_replay_verified": False,
            "source_only_labels_supported": False,
            "official_timestamp_timezone": str(OFFICIAL_TIMEZONE),
            "limitations": "No source-only label promotion, historical backtest, model persistence or activation.",
        },
        "source_fingerprints": {
            path: hashlib.sha256((root / path).read_bytes()).hexdigest()
            for path in (
                "scripts/football_history_training.py",
                "scripts/football_history_research.py",
                "scripts/training_manifest.py",
                "scripts/mle_trainer.py",
            )
        },
    }
    return {**result, "sha256": hashlib.sha256(canonical_json_bytes(result)).hexdigest()}


def load_history_official_inputs(conn, *, batch_id, reference_batch_id, **scope):
    """Read pinned history/reference and current official labels in one short snapshot."""
    if not _positive(batch_id) or not _positive(reference_batch_id):
        raise ValueError("Invalid history/reference batch identity")
    valid = _scope(
        **{
            **scope,
            "min_team_matches": scope.get("min_team_matches", 3),
            "max_matches": scope.get("max_matches", 5000),
        }
    )
    if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE or conn.autocommit:
        raise ValueError(
            "Research reader needs an idle dedicated connection with autocommit disabled"
        )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SET LOCAL statement_timeout='5s'")
            cur.execute(
                "SELECT * FROM football_history_batches WHERE id=%s AND state='published'",
                (batch_id,),
            )
            batch = cur.fetchone()
            cur.execute(
                "SELECT * FROM league_reference_batches WHERE id=%s AND state='published'",
                (reference_batch_id,),
            )
            reference = cur.fetchone()
            if batch is None or reference is None:
                raise LookupError("Published history/season reference batch not found")
            cur.execute(
                """SELECT * FROM football_history_matches
                   WHERE batch_id=%s AND source_competition_id=%s
                     AND kickoff_at >= %s AND kickoff_at < %s
                   ORDER BY kickoff_at,source_match_id LIMIT %s""",
                (
                    batch_id,
                    valid["source_competition_id"],
                    _time(valid["window_start"]),
                    min(_time(valid["window_end"]), _time(valid["as_of"])),
                    valid["max_matches"] + 1,
                ),
            )
            matches = cur.fetchall()
            if len(matches) > valid["max_matches"]:
                raise ValueError("History cohort exceeds max_matches")
            cur.execute(
                """SELECT batch_id,source_match_id,home_team_id,away_team_id,kickoff
                   FROM league_reference_fixtures WHERE batch_id=%s AND source_match_id=ANY(%s)
                   ORDER BY source_match_id LIMIT %s""",
                (
                    reference_batch_id,
                    [str(r["source_match_id"]) for r in matches],
                    valid["max_matches"] + 1,
                ),
            )
            history = build_history_training_manifest(
                batch,
                matches,
                season_reference={"batch": reference, "fixtures": cur.fetchall()},
                **scope,
            )
            cur.execute(
                """SELECT h.source_match_id,m.id match_id,r.match_id result_match_id,r.id result_id,
                          m.kickoff_time kickoff_at,m.match_status,
                          t1.id home_team_id,t2.id away_team_id,
                          t1.ids home_team_candidate_ids,t2.ids away_team_candidate_ids,
                          r.full_home_goals home_goals,r.full_away_goals away_goals,r.official_publish_time
                   FROM football_history_matches h
                   LEFT JOIN official_matches m ON m.id=h.official_match_id
                   LEFT JOIN official_results r ON r.match_id=m.id
                   LEFT JOIN LATERAL (
                       SELECT CASE WHEN count(*)=1 THEN min(id) END id,array_agg(id ORDER BY id) ids
                       FROM teams WHERE team_name_cn=m.home_team_name
                   ) t1 ON true
                   LEFT JOIN LATERAL (
                       SELECT CASE WHEN count(*)=1 THEN min(id) END id,array_agg(id ORDER BY id) ids
                       FROM teams WHERE team_name_cn=m.away_team_name
                   ) t2 ON true
                   WHERE h.batch_id=%s AND h.source_match_id=ANY(%s)
                   ORDER BY h.source_match_id,r.id LIMIT %s""",
                (
                    batch_id,
                    [r["source_match_id"] for r in history["included"]],
                    valid["max_matches"] + 1,
                ),
            )
            official = [dict(r) for r in cur.fetchall()]
            if len(official) > valid["max_matches"]:
                raise ValueError("Official evidence exceeds max_matches")
            return history, official
    finally:
        conn.rollback()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", type=int, required=True)
    parser.add_argument("--reference-batch-id", type=int, required=True)
    parser.add_argument("--competition-id", type=int, required=True)
    parser.add_argument("--season", required=True)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-end", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--min-team-matches", type=int, default=3)
    parser.add_argument("--max-matches", type=int, default=5000)
    parser.add_argument("--output", type=Path, required=True)
    args = vars(parser.parse_args())
    output = args.pop("output")
    if output.exists():
        raise FileExistsError(output)
    import psycopg2

    from scripts.titan007_history import _loopback_parameters

    conn = psycopg2.connect(**_loopback_parameters())
    try:
        history, official = load_history_official_inputs(conn, **args)
    finally:
        conn.close()
    result = fit_history_official_research(history, official)
    with output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "sha256": result["sha256"],
                **result["summary"],
                "converged": result["fit"].get("converged", False),
            }
        )
    )
    if result["fit_status"] != "converged":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
