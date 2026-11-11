"""Cutoff-safe, read-only player inputs for an experimental model candidate."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from scripts.data_catalog import get_data_source
from scripts.observation_storage import (
    ObservationCutoff,
)

SCHEMA_VERSION = "player-feature-projection/v1"
_BUILDER_VERSION = "observed-cutoff-pilot/v1"
_MAX_REGISTRATION_ROWS = 1024
_TIMEZONE = ZoneInfo("Asia/Shanghai")
_AVAILABILITY = {"doubtful", "injured", "suspended", "returned", "unknown"}


def _timestamp(value: Any, field: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"{field} must be an aware timestamp") from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be an aware timestamp")
    return value.astimezone(UTC)


def _source_player_id(value: Any) -> str | None:
    if type(value) is int and value > 0:
        return str(value)
    if isinstance(value, str) and value.isdecimal() and int(value) > 0:
        return value
    return None


def _revision_payload(entries: dict[tuple[str, str], dict]) -> list[dict]:
    return [
        {
            "source_name": source,
            "external_player_id": external_id,
            "player_id": row["player_id"],
            "revision": row["revision"],
            "updated_at": row["updated_at"].astimezone(UTC).isoformat(),
        }
        for (source, external_id), row in sorted(entries.items())
    ]


def _projection(
    *,
    batch: dict,
    cutoff: ObservationCutoff | None,
    as_of: datetime,
    kickoff_at: datetime | None,
    missingness: set[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "withheld",
        "candidate": "player_dependent_shadow",
        "match_id": batch.get("match_id"),
        "feature_batch_id": batch.get("id"),
        "observation_cutoff_id": cutoff.id if cutoff else batch.get("cutoff_id"),
        "cutoff_as_of": cutoff.as_of.isoformat() if cutoff else None,
        "projected_at": as_of.isoformat(),
        "kickoff_at": kickoff_at.isoformat() if kickoff_at else None,
        "competition_season_id": None,
        "identity_map_revision": {"entry_count": 0, "sha256": hashlib.sha256(b"[]").hexdigest()},
        "coverage": {
            side: {
                "confirmed_lineup_players": 0,
                "identity_verified_players": 0,
                "registration_known": 0,
                "availability_report_complete": False,
            }
            for side in ("home", "away")
        },
        "feature_values": {},
        "missingness": sorted(missingness),
        "source_refs": {
            "lineup_revisions": {},
            "availability_revisions": {},
            "registration_fact_ids": [],
            "identity_mapping_revisions": [],
        },
        "probabilities": None,
    }
    return payload


def unavailable_player_feature_projection(batch: dict, *, as_of: datetime) -> dict:
    """Return a sanitized withheld record when the optional read path fails."""
    at = _timestamp(as_of, "as_of")
    cutoff = batch.get("cutoff") if isinstance(batch, dict) else None
    try:
        _, _, kickoff_at = _target_context(batch)
    except (TypeError, ValueError, KeyError):
        kickoff_at = None
    return _projection(
        batch=batch if isinstance(batch, dict) else {},
        cutoff=cutoff if isinstance(cutoff, ObservationCutoff) else None,
        as_of=at,
        kickoff_at=kickoff_at,
        missingness={"projection_read_failed"},
    )


def _target_context(batch: dict) -> tuple[int, int, datetime]:
    features = batch.get("features")
    temperature = features.get("temperature_2m") if isinstance(features, dict) else None
    derivation = temperature.get("derivation") if isinstance(temperature, dict) else None
    context = derivation.get("context") if isinstance(derivation, dict) else None
    if not isinstance(context, dict):
        raise ValueError("player projection requires the batch's retained match context")
    home, away = context.get("home_team_id"), context.get("away_team_id")
    if type(home) is not int or home <= 0 or type(away) is not int or away <= 0 or home == away:
        raise ValueError("player projection requires distinct canonical teams")
    return home, away, _timestamp(context.get("kickoff_at"), "kickoff_at")


def _target_match(conn: Any, match_id: int, kickoff_at: datetime) -> tuple[str, datetime, date]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT league_name,kickoff_time FROM official_matches WHERE id=%s", (match_id,)
        )
        row = cur.fetchone()
    if row is None or not isinstance(row[0], str) or not isinstance(row[1], datetime):
        raise ValueError("player projection target match is unavailable")
    local_kickoff = row[1].replace(tzinfo=_TIMEZONE) if row[1].tzinfo is None else row[1]
    if local_kickoff.astimezone(UTC) != kickoff_at:
        raise ValueError("player projection kickoff differs from official match")
    return row[0], local_kickoff, local_kickoff.date()


def _competition_season_id(
    conn: Any, match_id: int, kickoff_day: date, *, cutoff: datetime
) -> int | None:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT season.competition_season_id
               FROM football_pool_fixture_catalog pool
               JOIN official_matches m ON m.id=pool.official_match_id
               JOIN LATERAL (
                   SELECT revision.material_json
                   FROM football_pool_fixture_revisions revision
                   WHERE revision.issue_id=pool.issue_id
                     AND revision.match_order=pool.match_order
                     AND revision.observed_at<=%s
                   ORDER BY revision.observed_at DESC,revision.id DESC
                   LIMIT 1
               ) revision ON true
               JOIN football_fixture_season_catalog season
                 ON season.fixture_id=pool.fixture_id
                AND season.fixture_id=(revision.material_json->>'fixture_id')::bigint
               WHERE m.id=%s AND pool.identity_status='linked'
                 AND revision.material_json->>'identity_status'='linked'
                 AND revision.material_json->>'match_id'=m.id::text
                 AND revision.material_json->>'fixture_id'=pool.fixture_id::text
                 AND revision.material_json->>'league_name'=m.league_name
                 AND revision.material_json->>'home_team_name'=m.home_team_name
                 AND revision.material_json->>'away_team_name'=m.away_team_name
                 AND (revision.material_json->>'kickoff_time')::timestamp=m.kickoff_time
                 AND pool.league_name=m.league_name
                 AND pool.home_team_name=m.home_team_name
                 AND pool.away_team_name=m.away_team_name
                 AND pool.kickoff_time=m.kickoff_time
                 AND %s::date BETWEEN season.planned_start_date
                                   AND season.planned_end_date
               ORDER BY season.competition_season_id
               LIMIT 2""",
            (cutoff, match_id, kickoff_day),
        )
        rows = cur.fetchall()
    return int(rows[0][0]) if len(rows) == 1 else None


def _batch_observation(batch: dict, field_name: str) -> dict | None:
    """Resolve a source observation only through the validated batch's exact index."""
    fields = batch.get("features")
    field = fields.get(field_name) if isinstance(fields, dict) else None
    observations = batch.get("observations")
    if not isinstance(field, dict) or not isinstance(observations, list):
        return None
    indexes = field.get("observation_indexes")
    derivation = field.get("derivation")
    resolution = derivation.get("resolution") if isinstance(derivation, dict) else None
    candidates = resolution.get("candidates") if isinstance(resolution, dict) else None
    if not isinstance(indexes, list) or not isinstance(candidates, list):
        return None
    selected = [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict)
        and candidate.get("source_id") == "api_football"
        and candidate.get("index") in indexes
    ]
    if len(selected) != 1:
        return None
    index = selected[0].get("index")
    if type(index) is not int or not 0 <= index < len(observations):
        return None
    observation = observations[index]
    if (
        not isinstance(observation, dict)
        or observation.get("revision_id") != selected[0].get("revision_id")
        or observation.get("content_hash") != selected[0].get("content_hash")
    ):
        return None
    return observation


def _valid_observation(observation: dict | None, *, as_of: datetime) -> bool:
    if (
        not isinstance(observation, dict)
        or observation.get("evidence_kind") != "source_observation"
    ):
        return False
    available_at = observation.get("available_at")
    valid_until = observation.get("valid_until")
    return (
        isinstance(available_at, datetime)
        and available_at <= as_of
        and isinstance(valid_until, datetime)
        and valid_until > as_of
    )


def _team_roster(
    observation: dict | None,
    *,
    team_id: int,
    as_of: datetime,
) -> tuple[list[dict], str | None]:
    if not isinstance(observation, dict) or not _valid_observation(observation, as_of=as_of):
        return [], "lineup_missing_or_stale"
    if observation.get("original_fact_status") != "value":
        return [], "lineup_not_confirmed"
    evidence = observation.get("evidence")
    value = observation.get("value")
    if (
        not isinstance(evidence, dict)
        or evidence.get("coverage_complete") is not True
        or not isinstance(evidence.get("coverage_evidence"), str)
        or not evidence["coverage_evidence"].strip()
        or not isinstance(value, dict)
        or value.get("team_id") != team_id
        or type(value.get("api_fixture_id")) is not int
        or value.get("lineup_status") != "confirmed"
        or not isinstance(value.get("players"), list)
        or len(value["players"]) > 64
    ):
        return [], "lineup_evidence_invalid"
    players = value["players"]
    starters = [
        player
        for player in players
        if isinstance(player, dict) and player.get("is_starting") is True
    ]
    if (
        len(starters) != 11
        or any(type(player.get("is_starting")) is not bool for player in players)
        or any(type(player.get("is_substitute")) is not bool for player in players)
    ):
        return [], "lineup_not_exactly_eleven"
    normalized = []
    for player in starters:
        player_id = player.get("player_id")
        source_id = _source_player_id(player.get("source_player_id"))
        if type(player_id) is not int or player_id <= 0 or source_id is None:
            return [], "lineup_identity_missing"
        normalized.append({"player_id": player_id, "source_player_id": source_id})
    if (
        len({player["player_id"] for player in normalized}) != 11
        or len({player["source_player_id"] for player in normalized}) != 11
    ):
        return [], "lineup_identity_duplicate"
    return sorted(normalized, key=lambda player: player["player_id"]), None


def _identity_rows(
    conn: Any, source_name: str, source_ids: list[str]
) -> dict[tuple[str, str], dict]:
    if not source_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT source_name,external_player_id,player_id,status,revision,updated_at,reviewed_at
               FROM player_identity_links
               WHERE source_name=%s AND external_player_id=ANY(%s)""",
            (source_name, source_ids),
        )
        rows = cur.fetchall()
    return {
        (row[0], row[1]): {
            "player_id": row[2],
            "status": row[3],
            "revision": row[4],
            "updated_at": row[5],
            "reviewed_at": row[6],
        }
        for row in rows
    }


def _identity_known(row: dict | None, *, player_id: int, cutoff: datetime) -> bool:
    return (
        isinstance(row, dict)
        and row.get("status") == "verified"
        and type(row.get("player_id")) is int
        and row["player_id"] == player_id
        and type(row.get("revision")) is int
        and row["revision"] > 0
        and isinstance(row.get("updated_at"), datetime)
        and row["updated_at"] <= cutoff
        and isinstance(row.get("reviewed_at"), datetime)
        and row["reviewed_at"] <= cutoff
    )


def _registration_rows(
    conn: Any, *, player_ids: list[int], competition_season_id: int, cutoff: datetime
) -> list[dict]:
    if not player_ids:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """SELECT l.source_name,l.external_player_id,l.player_id,l.revision,
                      l.updated_at,l.reviewed_at,
                      f.id,f.source_competition_id,f.source_season,f.source_record_key,
                      f.source_revision,f.content_sha256,f.status,f.eligible,
                      f.source_authority,f.valid_from,f.valid_to,f.acquired_at,
                      f.created_at,f.reviewed_at,
                      authority.status,authority.authority,authority.revision
               FROM player_identity_links l
               JOIN player_registration_facts f
                 ON f.source_name=l.source_name AND f.external_player_id=l.external_player_id
               LEFT JOIN LATERAL (
                   SELECT a.status,a.authority,a.revision
                   FROM player_registration_authority_sources a
                   WHERE a.source_name=f.source_name
                     AND a.created_at<=%s AND a.reviewed_at<=%s
                   ORDER BY a.revision DESC LIMIT 1
               ) authority ON true
               WHERE l.player_id=ANY(%s) AND l.status='verified'
                 AND l.updated_at<=%s AND l.reviewed_at<=%s
                 AND f.competition_season_id=%s
                 AND f.acquired_at<=%s AND f.created_at<=%s
                 AND (f.reviewed_at IS NULL OR f.reviewed_at<=%s)
               ORDER BY l.player_id,l.source_name,l.external_player_id,
                        f.source_competition_id,f.source_season,f.source_record_key,
                        f.acquired_at DESC,f.id DESC
               LIMIT %s""",
            (
                cutoff,
                cutoff,
                player_ids,
                cutoff,
                cutoff,
                competition_season_id,
                cutoff,
                cutoff,
                cutoff,
                _MAX_REGISTRATION_ROWS + 1,
            ),
        )
        rows = cur.fetchall()
    if len(rows) > _MAX_REGISTRATION_ROWS:
        raise ValueError("player registration evidence exceeds the projection bound")
    fields = (
        "source_name",
        "external_player_id",
        "player_id",
        "identity_revision",
        "identity_updated_at",
        "identity_reviewed_at",
        "fact_id",
        "source_competition_id",
        "source_season",
        "source_record_key",
        "source_revision",
        "content_sha256",
        "fact_status",
        "eligible",
        "source_authority",
        "valid_from",
        "valid_to",
        "acquired_at",
        "created_at",
        "reviewed_at",
        "authority_status",
        "authority_name",
        "authority_revision",
    )
    return [dict(zip(fields, row, strict=True)) for row in rows]


def _eligibility_by_player(
    rows: list[dict], *, kickoff_day: date
) -> tuple[dict[int, dict], set[int], list[int]]:
    latest: dict[tuple, dict] = {}
    for row in rows:
        key = (
            row["player_id"],
            row["source_name"],
            row["source_competition_id"],
            row["source_season"],
            row["source_record_key"],
        )
        previous = latest.get(key)
        order = (row["acquired_at"], row["fact_id"])
        if previous is None or order > (previous["acquired_at"], previous["fact_id"]):
            latest[key] = row

    eligible: dict[int, set[bool]] = {}
    fact_ids: set[int] = set()
    for row in latest.values():
        if (
            row["authority_status"] != "approved"
            or row["authority_name"] != row["source_authority"]
            or row["fact_status"] != "confirmed"
            or type(row["eligible"]) is not bool
            or not isinstance(row["valid_from"], date)
            or not isinstance(row["valid_to"], date)
            or not row["valid_from"] <= kickoff_day < row["valid_to"]
        ):
            continue
        eligible.setdefault(row["player_id"], set()).add(row["eligible"])
        fact_ids.add(row["fact_id"])
    resolved = {
        player_id: dict(eligible=next(iter(values)), status="confirmed")
        for player_id, values in eligible.items()
        if len(values) == 1
    }
    conflicts = {player_id for player_id, values in eligible.items() if len(values) > 1}
    return resolved, conflicts, sorted(fact_ids)


def _availability(
    observation: dict | None, *, team_id: int, roster: list[dict], as_of: datetime
) -> tuple[dict[str, int] | None, str | None, int]:
    if not isinstance(observation, dict) or not _valid_observation(observation, as_of=as_of):
        return None, "availability_coverage_incomplete", 0
    evidence = observation.get("evidence")
    if (
        not isinstance(evidence, dict)
        or evidence.get("coverage_complete") is not True
        or not isinstance(evidence.get("coverage_evidence"), str)
        or not evidence["coverage_evidence"].strip()
    ):
        return None, "availability_coverage_incomplete", 0
    status = observation.get("fact_status")
    if status == "confirmed_absent" and observation.get("value") is None:
        return {"reported_unavailable": 0, "doubtful": 0}, None, 0
    value = observation.get("value")
    if (
        status != "value"
        or not isinstance(value, dict)
        or value.get("team_id") != team_id
        or not isinstance(value.get("players"), list)
        or len(value["players"]) > 128
    ):
        return None, "availability_coverage_incomplete", 0
    by_source = {player["source_player_id"]: player for player in roster}
    by_player = {player["player_id"]: player for player in roster}
    conflicts = 0
    player_statuses: dict[int, set[str]] = {}
    for item in value["players"]:
        if not isinstance(item, dict):
            return None, "availability_evidence_invalid", conflicts
        source_id = _source_player_id(item.get("source_player_id"))
        player_id = item.get("player_id")
        if source_id is None or type(player_id) is not int or player_id <= 0:
            return None, "availability_identity_missing", conflicts
        starter_by_source = by_source.get(source_id)
        starter_by_player = by_player.get(player_id)
        if starter_by_source is None and starter_by_player is None:
            continue
        if (
            starter_by_source is None
            or starter_by_player is None
            or starter_by_source["player_id"] != player_id
            or starter_by_source["player_id"] != starter_by_player["player_id"]
        ):
            conflicts += 1
            continue
        availability = item.get("availability_status")
        if availability not in _AVAILABILITY:
            return None, "availability_status_unknown", conflicts
        if availability == "unknown":
            return None, "availability_status_unknown", conflicts
        player_statuses.setdefault(player_id, set()).add(availability)
    if conflicts:
        return None, "availability_identity_conflict", conflicts
    counts = {"reported_unavailable": 0, "doubtful": 0}
    for statuses in player_statuses.values():
        if len(statuses) > 1 and not statuses <= {"injured", "suspended"}:
            return None, "availability_status_conflict", conflicts
        if statuses & {"injured", "suspended"}:
            counts["reported_unavailable"] += 1
        elif "doubtful" in statuses:
            counts["doubtful"] += 1
    return counts, None, conflicts


def load_player_feature_projection(conn: Any, *, batch: dict, as_of: datetime) -> dict:
    """Build a fail-closed player input projection from an already validated batch.

    ``batch`` must be the complete object returned by ``load_feature_batch``.
    This function re-reads only its persisted P104 cutoff references. It performs
    bounded SELECTs and never calls a provider, writes rows, or commits.
    """
    at = _timestamp(as_of, "as_of")
    missingness: set[str] = set()
    cutoff = batch.get("cutoff") if isinstance(batch, dict) else None
    try:
        if (
            not isinstance(batch, dict)
            or type(batch.get("match_id")) is not int
            or batch["match_id"] <= 0
            or type(batch.get("id")) is not int
            or batch["id"] <= 0
            or batch.get("status") != "complete"
            or batch.get("builder_version") != _BUILDER_VERSION
            or not isinstance(cutoff, ObservationCutoff)
            or cutoff.include_reconstruction
            or batch.get("cutoff_id") != cutoff.id
        ):
            raise ValueError("player projection requires one exact complete runtime batch")
        home_team_id, away_team_id, kickoff_at = _target_context(batch)
    except (TypeError, ValueError, KeyError):
        return _projection(
            batch=batch if isinstance(batch, dict) else {},
            cutoff=cutoff if isinstance(cutoff, ObservationCutoff) else None,
            as_of=at,
            kickoff_at=None,
            missingness={"exact_batch_unavailable"},
        )

    result = _projection(
        batch=batch,
        cutoff=cutoff,
        as_of=at,
        kickoff_at=kickoff_at,
        missingness=missingness,
    )
    if at < cutoff.as_of:
        missingness.add("projection_before_cutoff")
    if at >= kickoff_at:
        missingness.add("decision_after_kickoff")
    if missingness:
        result["missingness"] = sorted(missingness)
        return result

    match_id = batch["match_id"]
    try:
        league_name, _, kickoff_day = _target_match(conn, match_id, kickoff_at)
    except (TypeError, ValueError, KeyError):
        missingness.add("target_match_mismatch")
        result["missingness"] = sorted(missingness)
        return result
    competition_season_id = _competition_season_id(conn, match_id, kickoff_day, cutoff=cutoff.as_of)
    result["competition_season_id"] = competition_season_id
    if competition_season_id is None:
        missingness.add("competition_season_unknown")

    source_name = get_data_source("api_football")["alias_namespace"]
    team_data: dict[str, dict] = {}
    source_ids: set[str] = set()
    player_ids: set[int] = set()
    for side, team_id in (("home", home_team_id), ("away", away_team_id)):
        lineup = _batch_observation(batch, f"{side}_lineup_confirmed")
        injury = _batch_observation(batch, f"{side}_key_absence_count")
        roster, lineup_error = _team_roster(lineup, team_id=team_id, as_of=at)
        if lineup_error or not isinstance(lineup, dict):
            missingness.add(lineup_error or "lineup_missing_or_stale")
        else:
            source_ids.update(player["source_player_id"] for player in roster)
            player_ids.update(player["player_id"] for player in roster)
            result["coverage"][side]["confirmed_lineup_players"] = len(roster)
            result["source_refs"]["lineup_revisions"][side] = {
                "revision_id": lineup["revision_id"],
                "content_hash": lineup["content_hash"],
            }
        team_data[side] = {"team_id": team_id, "roster": roster, "injury": injury}

    identity_rows = _identity_rows(conn, source_name, sorted(source_ids))
    identity_entries: dict[tuple[str, str], dict] = {}
    for side, data in team_data.items():
        verified_count = 0
        for player in data["roster"]:
            key = (source_name, player["source_player_id"])
            row = identity_rows.get(key)
            if isinstance(row, dict) and _identity_known(
                row, player_id=player["player_id"], cutoff=cutoff.as_of
            ):
                identity_entries[key] = row
                verified_count += 1
            else:
                missingness.add("identity_mapping_incomplete")
        result["coverage"][side]["identity_verified_players"] = verified_count

    availability_by_side: dict[str, dict[str, int]] = {}
    for side, data in team_data.items():
        counts, error, _ = _availability(
            data["injury"], team_id=data["team_id"], roster=data["roster"], as_of=at
        )
        if error:
            missingness.add(error)
        elif counts is not None:
            availability_by_side[side] = counts
            result["coverage"][side]["availability_report_complete"] = True
            result["source_refs"]["availability_revisions"][side] = {
                "revision_id": data["injury"]["revision_id"],
                "content_hash": data["injury"]["content_hash"],
            }

    if competition_season_id is not None and player_ids:
        registration_rows = _registration_rows(
            conn,
            player_ids=sorted(player_ids),
            competition_season_id=competition_season_id,
            cutoff=cutoff.as_of,
        )
        eligibility, conflicts, fact_ids = _eligibility_by_player(
            registration_rows, kickoff_day=kickoff_day
        )
        result["source_refs"]["registration_fact_ids"] = fact_ids
        for row in registration_rows:
            if row["fact_id"] in fact_ids:
                key = (row["source_name"], row["external_player_id"])
                identity_entries[key] = {
                    "player_id": row["player_id"],
                    "revision": row["identity_revision"],
                    "updated_at": row["identity_updated_at"],
                }
        if conflicts:
            missingness.add("registration_conflict")
        for side, data in team_data.items():
            known = sum(player["player_id"] in eligibility for player in data["roster"])
            result["coverage"][side]["registration_known"] = known
            if known != len(data["roster"]):
                missingness.add("registration_unknown")
            if any(
                eligibility.get(player["player_id"], {}).get("eligible") is False
                for player in data["roster"]
            ):
                missingness.add("lineup_registration_conflict")
    elif player_ids:
        missingness.add("registration_unknown")

    identity_payload = _revision_payload(identity_entries)
    identity_json = json.dumps(identity_payload, sort_keys=True, separators=(",", ":"))
    result["identity_map_revision"] = {
        "entry_count": len(identity_payload),
        "sha256": hashlib.sha256(identity_json.encode()).hexdigest(),
    }
    result["source_refs"]["identity_mapping_revisions"] = identity_payload

    if not missingness:
        result["status"] = "candidate_inputs_ready"
        result["feature_values"] = {
            "home_registered_starters": 11,
            "away_registered_starters": 11,
            "home_reported_unavailable_starters": availability_by_side["home"][
                "reported_unavailable"
            ],
            "away_reported_unavailable_starters": availability_by_side["away"][
                "reported_unavailable"
            ],
            "home_doubtful_starters": availability_by_side["home"]["doubtful"],
            "away_doubtful_starters": availability_by_side["away"]["doubtful"],
        }
    result["missingness"] = sorted(missingness)
    return result
