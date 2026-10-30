"""Read-only historical goal-label candidate review, before model activation.

This manifest deliberately differs from the official Maher TrainingDataset:
source full-match scores are not verified SPF regulation-time labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import RealDictCursor

from scripts.model_artifact_identity import canonical_json_bytes

VERSION = "fqp.history-training-candidates/v1"
SCORE_SCOPE = "source_reported_full_match"


def _positive(value: Any) -> bool:
    return type(value) is int and 0 < value <= 9007199254740991


def _time(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(result, datetime) or result.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return result.astimezone(UTC)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("timestamp must be a valid timezone-aware ISO datetime") from exc


def _text(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _scope(competition_id, season, window_start, window_end, as_of, min_team_matches, max_matches):
    if (
        not _positive(competition_id)
        or not isinstance(season, str)
        or not season.strip()
        or season != season.strip()
        or len(season) > 64
        or type(min_team_matches) is not int
        or not 1 <= min_team_matches <= 100
        or type(max_matches) is not int
        or not 1 <= max_matches <= 5000
    ):
        raise ValueError("Invalid history training scope")
    start, end, cutoff = map(_time, (window_start, window_end, as_of))
    if not timedelta(0) < end - start <= timedelta(days=400) or cutoff <= start:
        raise ValueError("History window must be positive, at most400 days, and precede as_of")
    return {
        "source_competition_id": competition_id,
        "study_season": season,
        "window_start": _text(start),
        "window_end": _text(end),
        "as_of": _text(cutoff),
        "minimum_team_matches": min_team_matches,
        "max_matches": max_matches,
    }


def _batch(batch: Mapping[str, Any], as_of: datetime) -> dict[str, Any]:
    if (
        not _positive(batch.get("id"))
        or batch.get("source_name") != "titan007"
        or batch.get("state") != "published"
        or not re.fullmatch(r"[0-9a-f]{64}", str(batch.get("content_sha256", "")))
        or not isinstance(batch.get("normalization_version"), str)
        or not batch["normalization_version"]
    ):
        raise ValueError("A verified published titan007 batch is required")
    imported = _time(batch.get("imported_at"))
    if imported > as_of:
        raise ValueError("History batch was not available to this system at as_of")
    return {
        "id": batch["id"],
        "source_name": batch["source_name"],
        "content_sha256": batch["content_sha256"],
        "normalization_version": batch["normalization_version"],
        "imported_at": _text(imported),
    }


def _season_reference(reference, scope):
    """Pin a published same-source season; never treat a bare year as an alias."""
    if reference is None:
        return None, {}
    batch = reference.get("batch", {})
    if (
        not _positive(batch.get("id"))
        or batch.get("source_name") != "titan007"
        or batch.get("state") != "published"
        or batch.get("source_competition_id") != str(scope["source_competition_id"])
        or batch.get("source_season") != scope["study_season"]
        or not re.fullmatch(r"[0-9a-f]{64}", str(batch.get("content_sha256", "")))
        or _time(batch.get("imported_at")) > _time(scope["as_of"])
    ):
        raise ValueError("Invalid published season reference")
    info = {
        "batch_id": batch["id"],
        "content_sha256": batch["content_sha256"],
        "source_competition_id": batch["source_competition_id"],
        "source_season": batch["source_season"],
        "imported_at": _text(_time(batch["imported_at"])),
    }
    fixtures = {}
    for fixture in reference.get("fixtures", []):
        mid = fixture.get("source_match_id")
        if (
            fixture.get("batch_id") != batch["id"]
            or not isinstance(mid, str)
            or not mid.isascii()
            or not mid.isdecimal()
            or not _positive(int(mid))
            or str(int(mid)) != mid
            or mid in fixtures
            or len(fixtures) >= scope["max_matches"]
        ):
            raise ValueError("Invalid or non-unique season reference fixture")
        fixtures[mid] = fixture
    return info, fixtures


def build_history_training_manifest(
    batch: Mapping[str, Any],
    matches: Iterable[Mapping[str, Any]],
    *,
    competition_id: int,
    season: str,
    window_start: datetime | str,
    window_end: datetime | str,
    as_of: datetime | str,
    min_team_matches: int = 3,
    max_matches: int = 5000,
    season_reference: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit one cohort without inventing official result IDs or publication times.

    The explicit study window does not fill a missing source season. Batch
    creation time proves neither commit visibility nor source publication.
    """
    scope = _scope(
        competition_id, season, window_start, window_end, as_of, min_team_matches, max_matches
    )
    start, end, cutoff = map(_time, (scope["window_start"], scope["window_end"], scope["as_of"]))
    batch_info = _batch(batch, cutoff)
    reference_info, reference_fixtures = _season_reference(season_reference, scope)
    imported = _time(batch_info["imported_at"])
    candidates: list[tuple[dict[str, Any], str | None]] = []
    seen_ids = set()
    for match in matches:
        if match.get("batch_id") != batch_info["id"]:
            raise ValueError("Mixed history batches are not allowed")
        if match.get("source_competition_id") != competition_id:
            continue
        kickoff = _time(match.get("kickoff_at"))
        if not start <= kickoff < min(end, cutoff):
            continue
        mid = match.get("source_match_id")
        if not _positive(mid) or mid in seen_ids:
            raise ValueError("Source match identities must be unique positive integers")
        seen_ids.add(mid)
        if len(candidates) >= max_matches:
            raise ValueError("History cohort exceeds max_matches; narrow the explicit window")
        metadata = match.get("source_metadata")
        if not isinstance(metadata, Mapping):
            raise ValueError("Invalid source metadata")
        sample: dict[str, Any] = {
            "source_namespace": "titan007:match",
            "source_match_id": mid,
            "official_match_id": match.get("official_match_id"),
            "kickoff_at": _text(kickoff),
            "source_season": match.get("source_season") or None,
            "source_home_team_id": match.get("source_home_team_id"),
            "source_away_team_id": match.get("source_away_team_id"),
            "home_team_id": match.get("home_team_id"),
            "away_team_id": match.get("away_team_id"),
            "home_goals": match.get("home_goals"),
            "away_goals": match.get("away_goals"),
            "match_status": match.get("match_status"),
            "label_source": "football_history_matches.home_goals/away_goals",
            "score_scope": metadata.get("score_scope"),
            "label_available_by": None,
            "source_published_at": None,
            "source_acquired_at": None,
        }
        reason = None
        season_reason = None
        if reference_info is not None:
            fixture = reference_fixtures.get(str(mid))
            if fixture is None:
                season_reason = "season_reference_missing"
            elif (
                fixture.get("home_team_id") != sample["home_team_id"]
                or fixture.get("away_team_id") != sample["away_team_id"]
                or _time(fixture.get("kickoff")) != kickoff
            ):
                season_reason = "season_reference_identity_conflict"
            else:
                sample["study_season"] = season
                sample["season_reference"] = {**reference_info, "source_match_id": str(mid)}
        if sample["match_status"] != "finished":
            reason = "match_not_finished"
        elif any(type(sample[k]) is not int or sample[k] < 0 for k in ("home_goals", "away_goals")):
            reason = "score_invalid"
        elif not all(_positive(sample[k]) for k in ("home_team_id", "away_team_id")):
            reason = "team_unmapped"
        elif sample["home_team_id"] == sample["away_team_id"]:
            reason = "same_canonical_team"
        elif season_reason:
            reason = season_reason
        elif (
            reference_info is None
            and sample["source_season"] is not None
            and sample["source_season"] != season
        ):
            reason = "source_season_conflict"
        elif sample["score_scope"] != SCORE_SCOPE:
            reason = "score_scope_unknown"
        elif any(
            metadata.get(k) is not None
            for k in ("home_extra", "away_extra", "home_penalties", "away_penalties")
        ):
            reason = "extra_time_or_penalties_reported"
        elif kickoff >= imported:
            reason = "finished_after_batch_import"
        candidates.append((sample, reason))

    candidates.sort(key=lambda item: (item[0]["kickoff_at"], item[0]["source_match_id"]))
    # Conflicts are checked across *all* candidate rows. A bad label on one
    # duplicate must not make its competing source identity safe to select.
    event_keys = [
        (s["kickoff_at"], *sorted((s["home_team_id"], s["away_team_id"])))
        if _positive(s["home_team_id"]) and _positive(s["away_team_id"])
        else None
        for s, _ in candidates
    ]
    event_counts = Counter(k for k in event_keys if k is not None)
    official_counts = Counter(
        s["official_match_id"] for s, _ in candidates if s["official_match_id"] is not None
    )
    included, excluded = [], []
    for (sample, reason), event_key in zip(candidates, event_keys, strict=True):
        if (event_key is not None and event_counts[event_key] > 1) or (
            sample["official_match_id"] is not None
            and official_counts[sample["official_match_id"]] > 1
        ):
            reason = "duplicate_match_identity"
        if reason:
            excluded.append({**sample, "reason": reason})
        else:
            included.append(sample)

    while included:
        counts = Counter(team for s in included for team in (s["home_team_id"], s["away_team_id"]))
        sparse = {team for team, count in counts.items() if count < min_team_matches}
        if not sparse:
            break
        retained = []
        for sample in included:
            if sparse.intersection((sample["home_team_id"], sample["away_team_id"])):
                excluded.append({**sample, "reason": "team_below_minimum_history"})
            else:
                retained.append(sample)
        included = retained
    counts = Counter(team for s in included for team in (s["home_team_id"], s["away_team_id"]))
    excluded.sort(key=lambda s: (s["kickoff_at"], s["source_match_id"]))
    manifest = {
        "version": VERSION,
        "batch": batch_info,
        "scope": scope,
        "usage": {
            "purpose": "offline_training_candidate_review",
            "production_ready": False,
            "point_in_time_replay_verified": False,
            "spf_regulation_score_verified": False,
            "label_availability_basis": "unknown_first_visibility_batch_creation_is_not_publication",
            "season_basis": "explicit_study_window_not_inferred_source_season",
            "target": SCORE_SCOPE,
        },
        "included": [{"ordinal": i, **s} for i, s in enumerate(included)],
        "excluded": excluded,
        "summary": {
            "included_count": len(included),
            "excluded_count": len(excluded),
            "source_season_unknown": sum(s["source_season"] is None for s in included),
            "excluded_by_reason": dict(sorted(Counter(s["reason"] for s in excluded).items())),
            "team_match_counts": {str(k): v for k, v in sorted(counts.items())},
        },
    }
    if reference_info is not None:
        manifest["season_reference"] = reference_info
        manifest["usage"]["season_basis"] = "published_reference_exact_fixture_identity"
    return {**manifest, "sha256": hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()}


def verify_history_training_manifest(manifest: Mapping[str, Any]) -> None:
    payload = {key: value for key, value in manifest.items() if key != "sha256"}
    if (
        manifest.get("version") != VERSION
        or manifest.get("sha256") != hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    ):
        raise ValueError("Historical candidate manifest SHA-256 does not match content")


def load_history_training_manifest(conn, *, batch_id: int, **scope) -> dict[str, Any]:
    """Own a short read-only snapshot on an idle dedicated connection only."""
    if not _positive(batch_id):
        raise ValueError("Invalid batch_id")
    validated = _scope(
        **{
            **scope,
            "min_team_matches": scope.get("min_team_matches", 3),
            "max_matches": scope.get("max_matches", 5000),
        }
    )
    if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
        raise ValueError("History reader requires an idle dedicated connection")
    if conn.autocommit:
        raise ValueError("History reader requires autocommit disabled for a consistent snapshot")
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SET LOCAL statement_timeout='5s'")
            cur.execute(
                """SELECT id,source_name,state,content_sha256,normalization_version,imported_at
                   FROM football_history_batches
                   WHERE id=%s AND source_name='titan007' AND state='published'""",
                (batch_id,),
            )
            batch = cur.fetchone()
            if batch is None:
                raise LookupError("Published history batch not found")
            _batch(batch, _time(validated["as_of"]))
            cur.execute(
                """SELECT * FROM football_history_matches
                   WHERE batch_id=%s AND source_competition_id=%s
                     AND kickoff_at >= %s AND kickoff_at < %s
                   ORDER BY kickoff_at,source_match_id LIMIT %s""",
                (
                    batch_id,
                    validated["source_competition_id"],
                    _time(validated["window_start"]),
                    min(_time(validated["window_end"]), _time(validated["as_of"])),
                    validated["max_matches"] + 1,
                ),
            )
            return build_history_training_manifest(batch, cur.fetchall(), **scope)
    finally:
        conn.rollback()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", type=int, required=True)
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
    import psycopg2

    from scripts.titan007_history import _loopback_parameters

    conn = psycopg2.connect(**_loopback_parameters())
    try:
        manifest = load_history_training_manifest(conn, **args)
    finally:
        conn.close()
    # This is a research artifact, not another business database or a backup.
    with output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"sha256": manifest["sha256"], **manifest["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
