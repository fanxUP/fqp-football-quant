"""Evidence-backed shared identities; callers own the pool transaction.

Keep source namespaces separate. A provider ID is never a local official FK.
Identity conflicts retain material without changing existing source bindings.
"""

from __future__ import annotations

from typing import Any

from psycopg2.extras import Json

from scripts.pool_issue_state import pool_time

TRADITIONAL_MATCH_COUNTS = {"t14c": 14, "r9": 14, "bqc6": 6, "jq4": 4}
IDENTITY_LOCK = 1263554640


def traditional_source_ids(raw: dict) -> dict[str, str]:
    """Keep the actual source field names, without trusting booleans/empty IDs."""
    return {
        key: str(value).strip()
        for key in ("infohubMatchId", "matchId")
        if isinstance(value := raw.get(key), (int, str))
        and not isinstance(value, bool)
        and str(value).strip() not in ("", "0")
    }


def _pending(reason: str, *, conflict: bool = False) -> dict:
    return dict(
        fixture_id=None,
        official_match_id=None,
        identity_status="conflict" if conflict else "pending",
        evidence={"reason": reason},
    )


def resolve_pool_fixture(
    cur: Any, row: dict, *, game_type: str, issue_no: str, source_game_type: str | None
) -> dict:
    """Resolve under a transaction-level lock acquired by the batch writer.

    An explicit traditional infohub ID survives reschedules. The generic
    matchId field is scoped to game+issue until wider semantics are verified.
    Only a unique exact league/teams/Shanghai kickoff can bridge namespaces.
    No fuzzy aliases, date-only joins, guessed seasons or automatic merges.
    """
    if row.get("identity_block_reason"):
        return _pending(str(row["identity_block_reason"]))
    if game_type not in TRADITIONAL_MATCH_COUNTS:
        return _pending("unverified_game_type")
    if source_game_type != game_type:
        return _pending("unverified_game_source")
    ids = row.get("source_ids") or {}
    # Only IDs carried with their original raw field constitute typed evidence.
    raw = row.get("raw_json") or {}
    if ids != traditional_source_ids(raw):
        return _pending("source_id_evidence_mismatch", conflict=True)
    keys = []
    if ids.get("infohubMatchId"):
        keys.append(("traditional.infohubMatchId", ids["infohubMatchId"]))
    if ids.get("matchId"):
        keys.append((f"traditional.{game_type}.{issue_no}.matchId", ids["matchId"]))
    fields = ("league_name", "home_team_name", "away_team_name")
    names = {k: str(row.get(k) or "").strip() for k in fields}
    kickoff = pool_time(row.get("kickoff_time"))
    # Legacy TIMESTAMP schedule columns are Shanghai wall time, not UTC.
    wall_time = kickoff.replace(tzinfo=None) if kickoff else None
    official_id = None
    exact: set[int] = set()
    if all(names.values()) and wall_time:
        params = (*(names[k] for k in fields), wall_time)
        cur.execute(
            """SELECT id,source_match_id FROM official_matches
               WHERE league_name=%s AND home_team_name=%s AND away_team_name=%s
                 AND kickoff_time=%s""",
            params,
        )
        officials = cur.fetchall()
        if len(officials) > 1:
            return _pending("ambiguous_official_identity", conflict=True)
        if officials:
            official_id, official_source_id = officials[0]
            keys.append(("jc.matchId", str(official_source_id)))
        cur.execute(
            """SELECT DISTINCT fixture_id FROM football_pool_issue_matches
               WHERE identity_status='linked' AND league_name=%s
                 AND home_team_name=%s AND away_team_name=%s AND kickoff_time=%s""",
            params,
        )
        exact = {r[0] for r in cur.fetchall()}
    if not keys:
        return _pending("missing_typed_source_identity")
    candidates = set(exact)
    for system, sid in keys:
        cur.execute(
            """SELECT fixture_id FROM football_fixture_source_links
               WHERE source_name='sporttery' AND id_system=%s AND source_match_id=%s""",
            (system, sid),
        )
        bound = cur.fetchone()
        if bound:
            candidates.add(bound[0])
    if len(candidates) > 1:
        return _pending("conflicting_fixture_bindings", conflict=True)
    fixture_id = next(iter(candidates), None)
    evidence = dict(
        **names,
        kickoff_time=kickoff.isoformat() if kickoff else None,
        game_type=game_type,
        issue_no=issue_no,
        source_ids=ids,
        official_match_id=official_id,
        method="typed_source_or_exact_unique",
    )
    if fixture_id is not None:
        cur.execute(
            """SELECT id_system,source_match_id,evidence FROM football_fixture_source_links
               WHERE fixture_id=%s AND source_name='sporttery'""",
            (fixture_id,),
        )
        for system, sid, old_evidence in cur.fetchall():
            if any(k == system and value != sid for k, value in keys):
                return _pending("source_namespace_collision", conflict=True)
            if any(
                names[k] and old_evidence.get(k) and names[k] != old_evidence[k] for k in fields
            ):
                return _pending("source_identity_fields_conflict", conflict=True)
        # An initial ID may arrive without team names. Later positive evidence
        # must still protect it, even after that membership has been replaced.
        cur.execute(
            """SELECT material_json FROM football_pool_fixture_revisions
               WHERE fixture_id=%s""",
            (fixture_id,),
        )
        for (material,) in cur.fetchall():
            if any(
                names[k]
                and str(material.get(k) or "").strip()
                and names[k] != str(material[k]).strip()
                for k in fields
            ):
                return _pending("source_identity_fields_conflict", conflict=True)
    else:
        cur.execute("INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")
        fixture_id = cur.fetchone()[0]
    for system, sid in keys:
        cur.execute(
            """INSERT INTO football_fixture_source_links
                (source_name,id_system,source_match_id,fixture_id,evidence)
                VALUES ('sporttery',%s,%s,%s,%s)
                ON CONFLICT (source_name,id_system,source_match_id) DO NOTHING""",
            (system, sid, fixture_id, Json(evidence)),
        )
    return dict(
        fixture_id=fixture_id,
        official_match_id=official_id,
        identity_status="linked",
        evidence=evidence,
    )
