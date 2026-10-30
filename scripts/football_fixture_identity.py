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
    return _bind_fixture(
        cur,
        [("sporttery", system, sid) for system, sid in keys],
        names,
        exact,
        dict(
            **names,
            kickoff_time=kickoff.isoformat() if kickoff else None,
            game_type=game_type,
            issue_no=issue_no,
            source_ids=ids,
            official_match_id=official_id,
            method="typed_source_or_exact_unique",
        ),
        official_id,
    )


def _bind_fixture(cur, keys, names, exact, evidence, official_id):
    """Bind under IDENTITY_LOCK; every caller applies its own source proof first."""
    fields = tuple(names)
    candidates = set(exact)
    for source, system, sid in keys:
        cur.execute(
            """SELECT fixture_id FROM football_fixture_source_links
               WHERE source_name=%s AND id_system=%s AND source_match_id=%s""",
            (source, system, sid),
        )
        bound = cur.fetchone()
        if bound:
            candidates.add(bound[0])
    if len(candidates) > 1:
        return _pending("conflicting_fixture_bindings", conflict=True)
    fixture_id = next(iter(candidates), None)
    if fixture_id is not None:
        cur.execute(
            """SELECT source_name,id_system,source_match_id,evidence FROM football_fixture_source_links
               WHERE fixture_id=%s""",
            (fixture_id,),
        )
        for source, system, sid, old_evidence in cur.fetchall():
            if any(src == source and k == system and value != sid for src, k, value in keys):
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
    for source, system, sid in keys:
        cur.execute(
            """INSERT INTO football_fixture_source_links
                (source_name,id_system,source_match_id,fixture_id,evidence)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (source_name,id_system,source_match_id) DO NOTHING""",
            (source, system, sid, fixture_id, Json(evidence)),
        )
    return dict(
        fixture_id=fixture_id,
        official_match_id=official_id,
        identity_status="linked",
        evidence=evidence,
    )


def link_official_history_fixture(
    conn, official_match_id: int, *, batch_id: int, source_match_id: int
) -> dict:
    """Add identity links without rewriting a published historical batch.

    Only explicit lottery IDs with exact directed names, kickoff and confirmed
    score can bridge these namespaces. Caller commits or rolls back the batch.
    Historical acquisition/publication and season meanings remain unchanged.
    """
    if conn.autocommit or any(
        type(value) is not int or not 1 <= value <= 9007199254740991
        for value in (official_match_id, batch_id, source_match_id)
    ):
        raise ValueError("History identity requires a transaction and positive integer IDs")
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (IDENTITY_LOCK,))
        # Stabilize the mutable official proof until the caller commits. History
        # and existing shared links are immutable, and never updated here.
        cur.execute(
            """SELECT m.source_match_id,m.league_name,m.home_team_name,m.away_team_name,
                              m.kickoff_time,r.full_home_goals,r.full_away_goals,r.result_status
                       FROM official_matches m JOIN official_results r ON r.match_id=m.id
                       WHERE m.id=%s FOR SHARE OF m,r""",
            (official_match_id,),
        )
        official = cur.fetchone()
        cur.execute(
            """SELECT m.kickoff_at,m.home_goals,m.away_goals,m.source_metadata,
                              m.official_match_id,b.content_sha256,m.match_status
                       FROM football_history_matches m JOIN football_history_batches b
                         ON b.id=m.batch_id AND b.state='published' AND b.source_name='titan007'
                       WHERE m.batch_id=%s AND m.source_match_id=%s""",
            (batch_id, source_match_id),
        )
        history = cur.fetchone()
        if not official or not history:
            return _pending("missing_published_history_or_official_result")
        sid, league, home, away, kickoff, hg, ag, result_status = official
        htime, hhg, hag, metadata, old_fk, digest, status = history
        official_time = pool_time(kickoff)
        links = metadata.get("lottery_links", [])
        if (
            not isinstance(links, list)
            or not links
            or any(
                not isinstance(link, dict) or str(link.get("lottery_match_id")) != sid
                for link in links
            )
            or not all(
                home in (link.get("home_team"), link.get("home_full_name"))
                and away in (link.get("away_team"), link.get("away_full_name"))
                for link in links
            )
        ):
            return _pending("unverified_or_multiple_lottery_identities", conflict=True)
        if (
            old_fk is not None
            and old_fk != official_match_id
            or official_time is None
            or official_time != pool_time(htime)
            or result_status != "confirmed"
            or status != "finished"
            or hg is None
            or ag is None
            or (hg, ag) != (hhg, hag)
        ):
            return _pending("historical_identity_fields_conflict", conflict=True)
        if history_identity_conflicts(cur, official_match_id, source_match_id):
            return _pending("conflicting_published_history_bindings", conflict=True)
        names = dict(league_name=league, home_team_name=home, away_team_name=away)
        cur.execute(
            """SELECT DISTINCT fixture_id FROM football_pool_issue_matches
                       WHERE identity_status='linked' AND league_name=%s
                         AND home_team_name=%s AND away_team_name=%s AND kickoff_time=%s""",
            (league, home, away, kickoff),
        )
        exact = {r[0] for r in cur.fetchall()}
        evidence = dict(
            **names,
            kickoff_time=official_time.isoformat(),
            official_match_id=official_match_id,
            history_batch_id=batch_id,
            history_content_sha256=digest,
            history_source_match_id=source_match_id,
            lottery_links=links,
            method="verified_history_lottery_link",
            historical_prematch_eligible=False,
        )
        return _bind_fixture(
            cur,
            [("sporttery", "jc.matchId", sid), ("titan007", "matchId", str(source_match_id))],
            names,
            exact,
            evidence,
            official_match_id,
        )


def history_identity_conflicts(cur, official_match_id, source_match_id, *, batch_id=None) -> bool:
    """Check all relevant published rows before limiting to a newest batch.

    Separate FK and source-ID branches permit the FK index and the existing
    (batch_id,source_match_id) primary key, without a broad OR scan.
    """
    cur.execute(
        """SELECT 1 FROM (
             SELECT m.batch_id FROM football_history_matches m
             JOIN football_history_batches b ON b.id=m.batch_id
             WHERE b.state='published' AND b.source_name='titan007'
               AND m.official_match_id=%s AND m.source_match_id<>%s
               AND (%s::bigint IS NULL OR m.batch_id=%s)
             UNION ALL
             SELECT m.batch_id FROM football_history_batches b
             JOIN football_history_matches m ON m.batch_id=b.id AND m.source_match_id=%s
             WHERE b.state='published' AND b.source_name='titan007'
               AND m.official_match_id IS NOT NULL AND m.official_match_id<>%s
               AND (%s::bigint IS NULL OR m.batch_id=%s)
           ) conflicts LIMIT 1""",
        (
            official_match_id,
            source_match_id,
            batch_id,
            batch_id,
            source_match_id,
            official_match_id,
            batch_id,
            batch_id,
        ),
    )
    return cur.fetchone() is not None
