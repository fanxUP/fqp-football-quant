"""Evidence-backed shared identities; callers own the pool transaction.

Keep source namespaces separate. A provider ID is never a local official FK.
Identity conflicts retain material without changing existing source bindings.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from psycopg2.extras import Json

from scripts.pool_issue_state import pool_time

TRADITIONAL_MATCH_COUNTS = {"t14c": 14, "r9": 14, "bqc6": 6, "jq4": 4}
IDENTITY_LOCK = 1263554640
FIVEHUNDRED_HALF_SCORE_SUPPLEMENT_KEY = "fivehundredcom_half_score_supplement_20261102"
# SHA-256 of the reviewed 753-row P128 public-source manifest. Any later
# supplement batch must be reviewed and pinned separately before acceptance.
FIVEHUNDRED_HALF_SCORE_SUPPLEMENT_SHA256 = (
    "b637cdd2943e1e5a1ba10844af7a0d2ed9bba8f154f735a9b476f63d48a6ada8"
)
# SHA-256 of the exact canonical secondary-source row for the approved
# Burnley-Everton fixture within that manifest. The manifest digest alone is a
# claim in JSON evidence; this row digest binds the accepted identity facts.
FIVEHUNDRED_HALF_SCORE_RECORD_SHA256 = (
    "81c3009ce7f1fb2a36c3b5393f64bceb2e3c5fbac5015602fd75a8b4a0413f87"
)


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


def _traditional_source_score(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    parts = value.strip().replace("：", ":").split(":")
    if len(parts) != 2 or any(not part.isascii() or not part.isdecimal() for part in parts):
        return None
    return int(parts[0]), int(parts[1])


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _traditional_source_integer_matches(value: Any, expected: int) -> bool:
    if type(value) is int:
        return value == expected
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        return False
    parsed = int(value)
    return str(parsed) == value and parsed == expected


def _traditional_primary_result_evidence(result_evidence: Any) -> dict | None:
    if not isinstance(result_evidence, dict):
        return None
    imported = result_evidence.get("sporttery_history_import")
    if isinstance(imported, dict):
        evidence = imported.get("evidence")
        return evidence if isinstance(evidence, dict) else None
    return result_evidence


def _canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _traditional_half_score_supplement_matches(
    result_evidence: Any,
    source_facts: dict,
    *,
    game_type: str,
    issue_no: str,
    match_order: int,
    source_game_no: int,
    league: str,
    home: str,
    away: str,
    kickoff_date: date,
    full_score: tuple[int, int],
    half_score: tuple[int, int],
    result_code: str,
) -> bool:
    """Accept only the reviewed P128 500.com batch for missing API HT scores."""
    if not isinstance(result_evidence, dict) or source_facts.get("half_score_source_text") != "{}":
        return False
    primary_evidence = _traditional_primary_result_evidence(result_evidence)
    if not isinstance(primary_evidence, dict):
        return False
    supplement = result_evidence.get(FIVEHUNDRED_HALF_SCORE_SUPPLEMENT_KEY)
    if not isinstance(supplement, dict):
        return False
    if (
        supplement.get("contract") != "sporttery-half-score-secondary-supplement/v1"
        or supplement.get("source") != "500.com_wanchang_exact_fixture_reconciliation"
        or supplement.get("manifest_sha256") != FIVEHUNDRED_HALF_SCORE_SUPPLEMENT_SHA256
        or supplement.get("sporttery_match_id") is not None
        or supplement.get("source_titan_match_id") is not None
        or primary_evidence.get("source") != "sporttery_history_api"
        or primary_evidence.get("issue_no") != issue_no
        or not _traditional_source_integer_matches(primary_evidence.get("game_no"), source_game_no)
        or not _traditional_source_integer_matches(primary_evidence.get("match_num"), match_order)
        or primary_evidence.get("full_score_source_text")
        != source_facts.get("full_score_source_text")
        or primary_evidence.get("half_score_source_text") != "{}"
        or primary_evidence.get("product_result_code_source_text") != result_code
        or supplement.get("api_full_score_source_text")
        != source_facts.get("full_score_source_text")
        or supplement.get("api_half_score_source_text") != "{}"
        or supplement.get("production_evidence_half_score_source_text") != "{}"
        or supplement.get("api_result_code") != result_code
        or _traditional_source_score(supplement.get("secondary_half_score_source_text"))
        != half_score
    ):
        return False

    checks = supplement.get("identity_checks")
    expected_checks = {
        "event_date_and_official_full_score_exact",
        "finished_source_record_has_valid_half_score",
        "official_away_team_exact_or_same_unique_titan_id",
        "official_home_team_exact_or_same_unique_titan_id",
        "only_one_source_fixture_matches_date_direction_and_full_score",
    }
    if (
        not isinstance(checks, dict)
        or set(checks) != expected_checks
        or any(checks.get(name) is not True for name in expected_checks)
    ):
        return False

    records = supplement.get("secondary_source_records")
    if not isinstance(records, list) or len(records) != 1:
        return False
    record = records[0]
    if not isinstance(record, dict):
        return False
    if _canonical_json_sha256(record) != FIVEHUNDRED_HALF_SCORE_RECORD_SHA256:
        return False
    source_match_id = supplement.get("source_match_id")
    if (
        not isinstance(source_match_id, int)
        or isinstance(source_match_id, bool)
        or source_match_id <= 0
    ):
        return False
    source_file = supplement.get("source_file")
    if (
        supplement.get("source_table") != "wanchang.php historical finished-score row"
        or not isinstance(source_file, str)
        or not source_file.startswith("https://live.500.com/wanchang.php?e=")
        or record.get("source_url") != source_file
        or record.get("source") != "500.com"
        or record.get("league") != league
        or record.get("home_team") != home
        or record.get("away_team") != away
        or record.get("event_date") != kickoff_date.isoformat()
        or record.get("full_score") != list(full_score)
        or record.get("half_score") != list(half_score)
        or not _valid_sha256(record.get("page_sha256"))
        or record.get("source_match_id") != source_match_id
    ):
        return False

    def unique_team_identity(identity: Any, team: str) -> bool:
        if not isinstance(identity, dict):
            return False
        source_ids = identity.get("source_titan_team_ids")
        official_ids = identity.get("official_titan_team_ids")
        if not isinstance(source_ids, list) or len(source_ids) != 1:
            return False
        source_id = source_ids[0]
        return (
            identity.get("method") == "same_unique_titan_team_id"
            and identity.get("source_name") == team
            and identity.get("official_name") == team
            and isinstance(source_id, int)
            and not isinstance(source_id, bool)
            and source_id > 0
            and official_ids == source_ids
        )

    return unique_team_identity(record.get("home_identity"), home) and unique_team_identity(
        record.get("away_identity"), away
    )


def _traditional_member_proof(raw: Any) -> tuple[dict | None, dict | None]:
    if not isinstance(raw, dict):
        return None, None
    imported = raw.get("sporttery_history_import")
    if isinstance(imported, dict):
        source = imported.get("source")
        receipt = imported.get("receipt")
        return (
            source if isinstance(source, dict) else None,
            receipt if isinstance(receipt, dict) else None,
        )
    receipt = raw.get("import_receipt")
    return raw, receipt if isinstance(receipt, dict) else None


def _traditional_issue_receipt(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    imported = raw.get("traditional_history_import")
    receipt = imported.get("receipt") if isinstance(imported, dict) else raw.get("import_receipt")
    return receipt if isinstance(receipt, dict) else None


def _traditional_kickoff_evidence(evidence: Any) -> dict | None:
    if not isinstance(evidence, dict):
        return None
    imported = evidence.get("sporttery_history_import")
    source_evidence = imported.get("evidence") if isinstance(imported, dict) else evidence
    return source_evidence if isinstance(source_evidence, dict) else None


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
            if (
                evidence.get("event_signature")
                and old_evidence.get("event_signature")
                and evidence["event_signature"] != old_evidence["event_signature"]
            ):
                return _pending("source_event_signature_conflict", conflict=True)
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


def link_traditional_issue_slot_group(conn, slots: list[dict[str, Any]]) -> dict[str, Any]:
    """Explicitly link verified completed Sporttery product slots to one fixture.

    The caller owns commit/rollback. This operation never treats a legacy JC ID
    as a source key and never assigns an official match or season. Its savepoint
    guarantees all-or-none behavior even if a later membership update fails.
    """
    if conn.autocommit:
        raise ValueError("Traditional fixture linking requires a transaction")
    with conn.cursor() as cur:
        cur.execute("SELECT current_setting('lock_timeout'),current_setting('statement_timeout')")
        previous_lock_timeout, previous_statement_timeout = cur.fetchone()
        cur.execute("SAVEPOINT fqp_traditional_slot_link")
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '2s'")
            cur.execute("SET LOCAL statement_timeout = '8s'")
        result = _link_traditional_issue_slot_group(conn, slots)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('lock_timeout',%s,true),set_config('statement_timeout',%s,true)",
                (previous_lock_timeout, previous_statement_timeout),
            )
            cur.execute("RELEASE SAVEPOINT fqp_traditional_slot_link")
        return result
    except Exception:
        with conn.cursor() as cur:
            cur.execute("ROLLBACK TO SAVEPOINT fqp_traditional_slot_link")
            cur.execute("RELEASE SAVEPOINT fqp_traditional_slot_link")
        raise


def _link_traditional_issue_slot_group(conn, slots: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate and write one explicit traditional issue-slot identity group."""
    source_game_numbers = {"t14c": 90, "r9": 90, "bqc6": 98, "jq4": 94}
    if not isinstance(slots, list) or len(slots) < 2:
        raise ValueError(
            "Traditional fixture linking requires a transaction and at least two slots"
        )

    normalized: list[tuple[str, str, int]] = []
    for slot in slots:
        if not isinstance(slot, dict) or set(slot) != {"game_type", "issue_no", "match_order"}:
            raise ValueError(
                "Each traditional slot must contain only game_type, issue_no and match_order"
            )
        game_type = slot["game_type"]
        issue_no = str(slot["issue_no"]).strip()
        match_order = slot["match_order"]
        if (
            game_type not in source_game_numbers
            or not issue_no.isascii()
            or not issue_no.isdecimal()
            or str(int(issue_no)) != issue_no
            or type(match_order) is not int
            or not 1 <= match_order <= TRADITIONAL_MATCH_COUNTS[game_type]
        ):
            raise ValueError("Invalid traditional product, issue number or slot order")
        normalized.append((game_type, issue_no, match_order))
    if len(set(normalized)) != len(normalized) or len({slot[0] for slot in normalized}) != len(
        normalized
    ):
        raise ValueError("A group must contain unique slots from distinct traditional products")

    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (IDENTITY_LOCK,))
        verified: list[dict[str, Any]] = []
        for game_type, issue_no, match_order in sorted(normalized):
            cur.execute(
                """SELECT i.id,i.raw_json,i.issue_no,i.game_type,i.source_game_type,
                          i.source_game_no,i.source_game_no_source,
                          m.id,m.match_order,m.fixture_id,m.identity_status,m.identity_evidence,
                          m.league_name,m.home_team_name,m.away_team_name,m.kickoff_time,
                          m.kickoff_date,m.kickoff_time_precision,
                          m.source_full_home_goals,m.source_full_away_goals,
                          m.source_half_home_goals,m.source_half_away_goals,
                          m.source_product_result_code,m.source_result_source,
                          m.source_result_semantics_key,m.source_result_evidence,
                          m.kickoff_evidence,m.source_raw_json
                   FROM football_pool_issues i
                   JOIN football_pool_issue_matches m ON m.issue_id=i.id
                   WHERE i.game_type=%s AND i.issue_no=%s AND m.match_order=%s
                   FOR UPDATE OF m""",
                (game_type, issue_no, match_order),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("traditional_slot_not_found")
            (
                issue_id,
                issue_raw,
                issue_no,
                actual_game_type,
                source_game_type,
                source_game_no,
                source_game_no_source,
                membership_id,
                actual_order,
                old_fixture_id,
                identity_status,
                old_identity_evidence,
                league,
                home,
                away,
                kickoff_time,
                kickoff_date,
                kickoff_precision,
                full_home,
                full_away,
                half_home,
                half_away,
                result_code,
                result_source,
                result_semantics,
                result_evidence,
                kickoff_evidence,
                source_raw,
            ) = row
            if (
                actual_game_type != game_type
                or source_game_type != game_type
                or source_game_no != source_game_numbers[game_type]
                or source_game_no_source != "sporttery_history_api"
                or actual_order != match_order
                or result_source != "sporttery_history_api"
                or result_semantics != f"sporttery_game_no_{source_game_numbers[game_type]}"
            ):
                raise ValueError("traditional_slot_source_mismatch")
            if identity_status not in {"pending", "linked"}:
                raise ValueError("traditional_slot_identity_conflict")
            if identity_status == "linked" and old_fixture_id is None:
                raise ValueError("traditional_slot_identity_conflict")
            if identity_status == "pending" and old_fixture_id is not None:
                raise ValueError("traditional_slot_identity_conflict")
            if (
                not str(result_code or "").strip()
                or "*" in str(result_code)
                or any(value is None for value in (full_home, full_away, half_home, half_away))
            ):
                raise ValueError("cancelled_or_unplayed_slot")
            if not all(str(value or "").strip() for value in (league, home, away)):
                raise ValueError("traditional_slot_event_facts_incomplete")
            if not isinstance(kickoff_date, date):
                try:
                    kickoff_date = date.fromisoformat(str(kickoff_date))
                except (TypeError, ValueError) as error:
                    raise ValueError("traditional_slot_event_facts_incomplete") from error
            if kickoff_precision not in {"date_only", "minute", "second"}:
                raise ValueError("traditional_slot_event_facts_incomplete")
            if kickoff_time is not None and kickoff_time.date() != kickoff_date:
                raise ValueError("traditional_slot_event_date_conflict")
            source_facts, receipt = _traditional_member_proof(source_raw)
            issue_receipt = _traditional_issue_receipt(issue_raw)
            source_kickoff_evidence = _traditional_kickoff_evidence(kickoff_evidence)
            actual_full_score = (int(full_home), int(full_away))
            actual_half_score = (int(half_home), int(half_away))
            source_half_score = (
                _traditional_source_score(source_facts.get("half_score_source_text"))
                if isinstance(source_facts, dict)
                else None
            )
            half_score_matches = source_half_score == actual_half_score
            if source_half_score is None:
                half_score_matches = _traditional_half_score_supplement_matches(
                    result_evidence,
                    source_facts if isinstance(source_facts, dict) else {},
                    game_type=game_type,
                    issue_no=issue_no,
                    match_order=match_order,
                    source_game_no=source_game_numbers[game_type],
                    league=str(league).strip(),
                    home=str(home).strip(),
                    away=str(away).strip(),
                    kickoff_date=kickoff_date,
                    full_score=actual_full_score,
                    half_score=actual_half_score,
                    result_code=str(result_code),
                )
            if (
                not isinstance(result_evidence, dict)
                or not isinstance(source_facts, dict)
                or source_facts.get("source") != "sporttery_history_api"
                or source_facts.get("source_game_no") != source_game_numbers[game_type]
                or str(source_facts.get("issue_no")) != issue_no
                or source_facts.get("match_num") != match_order
                or source_facts.get("league_name") != str(league).strip()
                or source_facts.get("home_team_name") != str(home).strip()
                or source_facts.get("away_team_name") != str(away).strip()
                or source_facts.get("kickoff_date") != kickoff_date.isoformat()
                or source_facts.get("kickoff_time_precision") != "date_only"
                or _traditional_source_score(source_facts.get("full_score_source_text"))
                != actual_full_score
                or not half_score_matches
                or source_facts.get("product_result_code_source_text") != result_code
                or not isinstance(receipt, dict)
                or not isinstance(issue_receipt, dict)
                or receipt.get("contract") != "sporttery-traditional-history-import/v1"
                or receipt.get("contract") != issue_receipt.get("contract")
                or receipt.get("issue_sha256") != issue_receipt.get("issue_sha256")
                or receipt.get("manifest_sha256") != issue_receipt.get("manifest_sha256")
                or issue_receipt.get("contract") != "sporttery-traditional-history-import/v1"
                or not _valid_sha256(issue_receipt.get("issue_sha256"))
                or not _valid_sha256(issue_receipt.get("manifest_sha256"))
                or not all(
                    _valid_sha256(receipt.get(field))
                    for field in ("issue_sha256", "manifest_sha256", "source_row_sha256")
                )
            ):
                raise ValueError("traditional_slot_source_evidence_mismatch")
            if (
                not isinstance(source_kickoff_evidence, dict)
                or source_kickoff_evidence.get("source") != "sporttery_history_api"
            ):
                raise ValueError("traditional_slot_kickoff_evidence_missing")
            verified.append(
                {
                    "game_type": game_type,
                    "issue_no": issue_no,
                    "match_order": match_order,
                    "issue_id": issue_id,
                    "membership_id": membership_id,
                    "fixture_id": old_fixture_id,
                    "identity_status": identity_status,
                    "identity_evidence": old_identity_evidence,
                    "league_name": str(league).strip(),
                    "home_team_name": str(home).strip(),
                    "away_team_name": str(away).strip(),
                    "kickoff_date": kickoff_date.isoformat(),
                    "kickoff_time_precision": kickoff_precision,
                    "full_score": [int(full_home), int(full_away)],
                    "half_score": [int(half_home), int(half_away)],
                    "source_game_no": source_game_no,
                    "source_result_evidence": result_evidence,
                    "kickoff_evidence": kickoff_evidence,
                    "source_import_receipt": receipt,
                }
            )

        first = verified[0]
        signature_fields = (
            "league_name",
            "home_team_name",
            "away_team_name",
            "kickoff_date",
            "full_score",
            "half_score",
        )
        event_signature = {key: first[key] for key in signature_fields}
        if any(
            {key: item[key] for key in signature_fields} != event_signature for item in verified[1:]
        ):
            raise ValueError("traditional_slots_do_not_match_exact_event_facts")
        for item in verified:
            if item["identity_status"] == "linked" and (
                item["identity_evidence"].get("method") != "verified_traditional_issue_slots"
                or item["identity_evidence"].get("event_signature") != event_signature
            ):
                raise ValueError("traditional_slot_already_has_another_identity")

        names = {key: event_signature[key] for key in signature_fields[:3]}
        cur.execute(
            """SELECT DISTINCT fixture_id FROM football_pool_issue_matches
               WHERE identity_status='linked' AND league_name=%s AND home_team_name=%s
                 AND away_team_name=%s
                 AND COALESCE(kickoff_date,kickoff_time::date)=%s
                 AND source_full_home_goals=%s AND source_full_away_goals=%s
                 AND source_half_home_goals=%s AND source_half_away_goals=%s""",
            (
                names["league_name"],
                names["home_team_name"],
                names["away_team_name"],
                date.fromisoformat(event_signature["kickoff_date"]),
                *event_signature["full_score"],
                *event_signature["half_score"],
            ),
        )
        exact = {result[0] for result in cur.fetchall()}
        exact.update(item["fixture_id"] for item in verified if item["fixture_id"] is not None)
        if len(exact) > 1:
            raise ValueError("conflicting_traditional_slot_fixture_bindings")

        keys = [
            (
                "sporttery",
                f"traditional.{item['game_type']}.{item['issue_no']}.matchOrder",
                str(item["match_order"]),
            )
            for item in verified
        ]
        existing_links = 0
        for source_name, id_system, source_match_id in keys:
            cur.execute(
                """SELECT fixture_id,evidence FROM football_fixture_source_links
                   WHERE source_name=%s AND id_system=%s AND source_match_id=%s""",
                (source_name, id_system, source_match_id),
            )
            existing = cur.fetchone()
            if existing:
                if existing[1].get("event_signature") != event_signature:
                    raise ValueError("source_event_signature_conflict")
                existing_links += 1
                exact.add(existing[0])
        if len(exact) > 1:
            raise ValueError("conflicting_traditional_slot_fixture_bindings")

        evidence = {
            **names,
            "event_signature": event_signature,
            "method": "verified_traditional_issue_slots",
            "source": "sporttery_history_api",
            "slots": [
                {
                    "game_type": item["game_type"],
                    "issue_no": item["issue_no"],
                    "match_order": item["match_order"],
                    "issue_id": item["issue_id"],
                    "membership_id": item["membership_id"],
                    "source_game_no": item["source_game_no"],
                    "source_result_evidence": item["source_result_evidence"],
                    "kickoff_evidence": item["kickoff_evidence"],
                    "source_import_receipt": item["source_import_receipt"],
                }
                for item in verified
            ],
            "cancelled_jc_ids_linked": False,
            "official_match_id": None,
            "season_membership": None,
        }
        binding = _bind_fixture(
            cur,
            keys,
            names,
            exact,
            evidence,
            None,
        )
        if binding["identity_status"] != "linked":
            raise ValueError(binding["evidence"].get("reason", "traditional_slot_binding_conflict"))

        updated = 0
        for item in verified:
            if item["identity_status"] == "linked":
                if item["fixture_id"] != binding["fixture_id"]:
                    raise ValueError("conflicting_traditional_slot_fixture_bindings")
                continue
            cur.execute(
                """UPDATE football_pool_issue_matches
                   SET fixture_id=%s,identity_status='linked',identity_evidence=%s
                   WHERE id=%s AND identity_status='pending' AND fixture_id IS NULL""",
                (binding["fixture_id"], Json(evidence), item["membership_id"]),
            )
            if cur.rowcount != 1:
                raise ValueError("traditional_slot_changed_during_link")
            updated += 1

        return {
            "fixture_id": binding["fixture_id"],
            "identity_status": "linked",
            "inserted_fixture": not exact,
            "inserted_source_links": len(keys) - existing_links,
            "updated_memberships": updated,
            "slots": [
                {
                    "game_type": item["game_type"],
                    "issue_no": item["issue_no"],
                    "match_order": item["match_order"],
                }
                for item in verified
            ],
            "evidence": evidence,
        }


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
