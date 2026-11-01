"""Plan or apply the reviewed 26127–26151 legacy t14c/bqc6 correction.

The default mode only validates and reports a plan. Applying requires an explicit
local PostgreSQL DSN, the exact migration-128 checksum, a fully sealed 25-issue
plan, and all live rows matching the captured source inventory. The 26151 merge
keeps the canonical t14c rows and transfers existing official-match links before
removing the duplicate bqc6 rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.football_fixture_identity import IDENTITY_LOCK  # noqa: E402
from scripts.traditional_history_import import (  # noqa: E402
    _local_database_parameters,
    _pool_raw_hash,
    _require_migration_128,
)

CONTRACT = "sporttery-legacy-pool-issue-type-repair/v2"
MEMBER_SNAPSHOT_SCHEMA = "football-pool-issue-member/v2"
EXPECTED_ISSUES = tuple(str(number) for number in range(26127, 26152))
REPAIR_EVIDENCE_KEY = "legacy_issue_type_repair"
MEMBER_EVIDENCE_KEY = "legacy_issue_type_repair"
DEFAULT_PLAN = (
    ROOT.parent
    / "plans"
    / "local-football-data-integration-20261029"
    / "traditional-catalog-20261101"
    / "TRADITIONAL-HISTORY-TYPE-REPAIR-PLAN-20261101.json"
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _plan_digest(plan: dict[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key != "plan_sha256"}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def seal_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with a deterministic SHA-256 receipt."""
    sealed = {key: value for key, value in plan.items() if key != "plan_sha256"}
    sealed["plan_sha256"] = _plan_digest(sealed)
    return sealed


def _normalized_team(value: object) -> str:
    return "".join(str(value or "").split())


def _identity_date(member: dict[str, Any]) -> str:
    """Use the post-128 date column, or the pre-128 timestamp's stored date.

    Migration 128 intentionally leaves historical rows unbackfilled. The old
    kickoff_time remains the sealed source fact for those rows, and the repair
    plan's separate official API roster still has to agree with that date.
    """
    kickoff_date = member.get("kickoff_date")
    if kickoff_date:
        return str(kickoff_date)[:10]
    kickoff_time = member.get("kickoff_time")
    return str(kickoff_time or "")[:10]


def _member_doc(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "membership_id": int(row[0]),
        "match_order": int(row[1]),
        "match_id": row[2],
        "fixture_id": row[3],
        "identity_status": row[4],
        "source_match_id": row[5],
        "league_name": row[6],
        "home_team_name": row[7],
        "away_team_name": row[8],
        "kickoff_time": row[9],
        "kickoff_date": row[10],
        "kickoff_time_precision": row[11],
        "kickoff_evidence": row[12] or {},
        "source_full_home_goals": row[13],
        "source_full_away_goals": row[14],
        "source_half_home_goals": row[15],
        "source_half_away_goals": row[16],
        "source_product_result_code": row[17],
        "source_result_semantics_key": row[18],
        "source_result_source": row[19],
        "source_result_evidence": row[20] or {},
        "home_win_prob": str(row[21]) if row[21] is not None else None,
        "draw_prob": str(row[22]) if row[22] is not None else None,
        "away_win_prob": str(row[23]) if row[23] is not None else None,
        "upset_score": str(row[24]) if row[24] is not None else None,
        "public_heat_home": str(row[25]) if row[25] is not None else None,
        "public_heat_draw": str(row[26]) if row[26] is not None else None,
        "public_heat_away": str(row[27]) if row[27] is not None else None,
        "identity_evidence": row[28] or {},
        "source_raw_json": row[29] or {},
        "source_raw_md5": row[30],
    }


def _member_evidence_merge(
    canonical: dict[str, Any], donor: dict[str, Any], label: str
) -> dict[str, Any]:
    """Merge structured evidence only when overlapping values agree."""
    merged = dict(canonical)
    for key, value in donor.items():
        if key not in merged:
            merged[key] = value
        elif isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _member_evidence_merge(merged[key], value, f"{label}.{key}")
        elif merged[key] != value:
            raise ValueError(f"{label} contains conflicting evidence field {key}")
    return merged


def _header_doc(row: tuple[Any, ...]) -> dict[str, Any]:
    keys = (
        "id",
        "game_type",
        "source_game_type",
        "issue_no",
        "total_matches",
        "sale_start_time",
        "sale_stop_time",
        "raw_json_md5",
        "saved_combinations",
    )
    return dict(zip(keys, row, strict=True))


def _validate_plan(plan: dict[str, Any]) -> str:
    if plan.get("contract") != CONTRACT:
        raise ValueError("unsupported legacy issue repair contract")
    if plan.get("member_snapshot_schema") != MEMBER_SNAPSHOT_SCHEMA:
        raise ValueError(
            "repair plan lacks a complete member snapshot; refresh the read-only inventory"
        )
    if plan.get("plan_sha256") != _plan_digest(plan):
        raise ValueError("repair plan SHA-256 mismatch")
    for field in ("source_server_sha", "source_inventory_sha256", "source_preview_sha256"):
        value = str(plan.get(field) or "")
        expected_len = 40 if field == "source_server_sha" else 64
        if len(value) != expected_len or any(char not in "0123456789abcdef" for char in value):
            raise ValueError(f"repair plan has an invalid {field}")
    issues = plan.get("issues")
    if not isinstance(issues, list) or [str(row.get("issue_no")) for row in issues] != list(
        EXPECTED_ISSUES
    ):
        raise ValueError("repair plan must contain each issue 26127–26151 in order")
    if len(issues) > 25:
        raise ValueError("legacy issue repair is bounded to 25 issue keys")
    for operation in issues:
        issue_no = str(operation.get("issue_no"))
        expected_operation = (
            "merge_duplicate_into_canonical" if issue_no == "26151" else "reclassify_header"
        )
        if operation.get("operation") != expected_operation:
            raise ValueError(f"unexpected repair operation for issue {issue_no}")
        expected_header_fields = {
            "id",
            "game_type",
            "source_game_type",
            "issue_no",
            "total_matches",
            "sale_start_time",
            "sale_stop_time",
            "official_status",
            "prize_pool_estimate",
            "raw_hash",
            "raw_json_md5",
            "saved_combinations",
            "source_game_no",
            "source_game_no_source",
            "raw_json",
        }
        header_snapshots = [operation.get("expected_legacy_header")]
        if expected_operation == "merge_duplicate_into_canonical":
            header_snapshots.append(operation.get("expected_canonical_header"))
        if any(
            not isinstance(header, dict) or set(header) != expected_header_fields
            for header in header_snapshots
        ):
            raise ValueError(
                f"issue {issue_no} plan lacks a complete header snapshot; refresh the read-only inventory"
            )
        if (
            operation.get("source_game_no") != 90
            or operation.get("source_game_no_source") != "sporttery_history_api"
        ):
            raise ValueError(f"issue {issue_no} lacks the expected official API namespace")
        expected_count = 14
        rosters = [("source", operation.get("expected_source_roster", []))]
        if expected_operation == "reclassify_header":
            rosters.append(("legacy", operation.get("expected_legacy_roster", [])))
        else:
            rosters.extend(
                [
                    ("legacy", operation.get("expected_legacy_roster", [])),
                    ("canonical", operation.get("expected_canonical_roster", [])),
                ]
            )
        for roster_kind, roster in rosters:
            if len(roster) != expected_count or [
                int(row.get("match_order", 0)) for row in roster
            ] != list(range(1, expected_count + 1)):
                raise ValueError(f"issue {issue_no} requires an exact 14-slot roster")
            if roster_kind != "source" and any(
                set(row) != set(_member_doc_keys()) for row in roster
            ):
                raise ValueError(
                    f"issue {issue_no} plan does not snapshot every member field; refresh the inventory"
                )
    return str(plan["plan_sha256"])


def _member_doc_keys() -> tuple[str, ...]:
    return (
        "membership_id",
        "match_order",
        "match_id",
        "fixture_id",
        "identity_status",
        "source_match_id",
        "league_name",
        "home_team_name",
        "away_team_name",
        "kickoff_time",
        "kickoff_date",
        "kickoff_time_precision",
        "kickoff_evidence",
        "source_full_home_goals",
        "source_full_away_goals",
        "source_half_home_goals",
        "source_half_away_goals",
        "source_product_result_code",
        "source_result_semantics_key",
        "source_result_source",
        "source_result_evidence",
        "home_win_prob",
        "draw_prob",
        "away_win_prob",
        "upset_score",
        "public_heat_home",
        "public_heat_draw",
        "public_heat_away",
        "identity_evidence",
        "source_raw_json",
        "source_raw_md5",
    )


def _load_header(cur, issue_id: int, *, lock: bool = True) -> tuple[Any, ...] | None:
    suffix = " FOR UPDATE" if lock else ""
    cur.execute(
        """SELECT id,game_type,source_game_type,issue_no,total_matches,
                  sale_start_time::text,sale_stop_time::text,md5(raw_json::text),
                  (SELECT count(*) FROM football_pool_combinations c WHERE c.issue_id=i.id)::int,
                  source_game_no,source_game_no_source,raw_json,
                  official_status,prize_pool_estimate::text,raw_hash
           FROM football_pool_issues i WHERE id=%s"""
        + suffix,
        (issue_id,),
    )
    return cur.fetchone()


def _header_public(row: tuple[Any, ...]) -> dict[str, Any]:
    doc = _header_doc(row[:9])
    doc["source_game_no"] = row[9]
    doc["source_game_no_source"] = row[10]
    doc["raw_json"] = row[11]
    doc["official_status"] = row[12]
    doc["prize_pool_estimate"] = row[13]
    doc["raw_hash"] = row[14]
    return doc


def _load_members(
    cur, issue_id: int, *, lock: bool = True
) -> tuple[list[tuple[Any, ...]], list[dict[str, Any]]]:
    suffix = " FOR UPDATE" if lock else ""
    cur.execute(
        """SELECT id,match_order,match_id,fixture_id,identity_status,source_match_id,
                  league_name,home_team_name,away_team_name,kickoff_time::text,
                  kickoff_date::text,kickoff_time_precision,kickoff_evidence,
                  source_full_home_goals,source_full_away_goals,
                  source_half_home_goals,source_half_away_goals,
                  source_product_result_code,source_result_semantics_key,
                  source_result_source,source_result_evidence,
                  home_win_prob,draw_prob,away_win_prob,upset_score,
                  public_heat_home,public_heat_draw,public_heat_away,
                  identity_evidence,source_raw_json,md5(source_raw_json::text)
           FROM football_pool_issue_matches WHERE issue_id=%s ORDER BY match_order"""
        + suffix,
        (issue_id,),
    )
    rows = cur.fetchall()
    return rows, [_member_doc(row) for row in rows]


def _source_roster(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "match_order": int(row["match_order"]),
            "home_team_name": row["home_team_name"],
            "away_team_name": row["away_team_name"],
            "kickoff_date": _identity_date(row),
        }
        for row in rows
    ]


def _validate_roster(
    issue_no: str, actual: list[dict[str, Any]], expected: list[dict[str, Any]]
) -> None:
    if actual != expected:
        raise ValueError(f"issue {issue_no} roster differs from the sealed repair plan")


def _validate_source_roster(
    issue_no: str, actual: list[dict[str, Any]], expected: list[dict[str, Any]]
) -> None:
    actual_source = _source_roster(actual)
    expected_source = [
        {
            "match_order": int(row["match_order"]),
            "home_team_name": row["home_team_name"],
            "away_team_name": row["away_team_name"],
            "kickoff_date": _identity_date(row),
        }
        for row in expected
    ]
    if actual_source != expected_source:
        raise ValueError(f"issue {issue_no} API roster differs from the live production rows")


def _assert_header_matches(
    actual: tuple[Any, ...], expected: dict[str, Any], issue_no: str, label: str
) -> None:
    public = _header_public(actual)
    for field, value in expected.items():
        if field in public and public[field] != value:
            if field == "saved_combinations" and public[field] > 0:
                raise ValueError(f"issue {issue_no} has saved combinations; refusing repair")
            raise ValueError(f"issue {issue_no} {label} header field {field} changed")


def _add_header_receipt(
    cur, header: tuple[Any, ...], receipt: dict[str, Any], *, game_type: str
) -> None:
    raw_json = header[11]
    if raw_json is None:
        raw_json = {}
    if not isinstance(raw_json, dict):
        raise ValueError(f"issue {receipt['issue_no']} raw_json is not an object")
    merged = dict(raw_json)
    existing = merged.get(REPAIR_EVIDENCE_KEY)
    if existing is not None and existing != receipt:
        raise ValueError(f"issue {receipt['issue_no']} has a conflicting repair receipt")
    merged[REPAIR_EVIDENCE_KEY] = receipt
    cur.execute(
        """UPDATE football_pool_issues
           SET game_type=%s,source_game_type=%s,source_game_no=%s,source_game_no_source=%s,
               raw_json=%s,raw_hash=%s,updated_at=now()
           WHERE id=%s""",
        (
            game_type,
            game_type,
            receipt["source_game_no"],
            receipt["source_game_no_source"],
            Json(merged),
            _pool_raw_hash(merged),
            header[0],
        ),
    )


def _assert_safe_delete_schema(cur) -> None:
    cur.execute(
        """SELECT con.conname,con.conrelid::regclass::text,con.confrelid::regclass::text
           FROM pg_constraint con
           WHERE con.contype='f' AND con.confrelid IN (
             'football_pool_issues'::regclass,
             'football_pool_issue_matches'::regclass)
           ORDER BY 1"""
    )
    actual = {(row[0], row[1].split(".")[-1], row[2].split(".")[-1]) for row in cur.fetchall()}
    expected = {
        (
            "football_pool_combinations_issue_id_fkey",
            "football_pool_combinations",
            "football_pool_issues",
        ),
        (
            "football_pool_fixture_revisions_issue_id_match_order_fkey",
            "football_pool_fixture_revisions",
            "football_pool_issue_matches",
        ),
        (
            "football_pool_issue_matches_issue_id_fkey",
            "football_pool_issue_matches",
            "football_pool_issues",
        ),
    }
    if actual != expected:
        raise ValueError(
            "issue/member foreign-key graph changed; duplicate removal needs a new audit"
        )


def _assert_no_references_block_delete(cur, issue_id: int, issue_no: str) -> None:
    cur.execute("SELECT count(*) FROM football_pool_combinations WHERE issue_id=%s", (issue_id,))
    if cur.fetchone()[0]:
        raise ValueError(f"issue {issue_no} has saved combinations; refusing duplicate removal")
    cur.execute(
        "SELECT count(*) FROM football_pool_fixture_revisions WHERE issue_id=%s", (issue_id,)
    )
    if cur.fetchone()[0]:
        raise ValueError(f"issue {issue_no} has fixture revisions; refusing duplicate removal")


def _repair_receipt(plan_sha256: str, issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": CONTRACT,
        "plan_sha256": plan_sha256,
        "issue_no": str(issue["issue_no"]),
        "operation": issue["operation"],
        "legacy_issue_id": int(issue["legacy_issue_id"]),
        "canonical_issue_id": (
            int(issue["canonical_issue_id"])
            if issue.get("canonical_issue_id") is not None
            else int(issue["legacy_issue_id"])
        ),
        "from_game_type": "bqc6",
        "to_game_type": "t14c",
        "source_game_no": 90,
        "source_game_no_source": "sporttery_history_api",
        "preserved_source_header": issue["expected_legacy_header"],
    }


def _member_merge_receipt(
    plan_sha256: str, issue: dict[str, Any], donor_member: dict[str, Any]
) -> dict[str, Any]:
    return {
        "contract": CONTRACT,
        "plan_sha256": plan_sha256,
        "issue_no": str(issue["issue_no"]),
        "legacy_issue_id": int(issue["legacy_issue_id"]),
        "legacy_membership_id": int(donor_member["membership_id"]),
        "preserved_official_match_id": donor_member["match_id"],
        "preserved_donor_member": donor_member,
    }


def _member_state_sha256(members: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical_json(members).encode("utf-8")).hexdigest()


def _assert_repaired_header_matches(
    current: tuple[Any, ...], issue: dict[str, Any], stored_receipt: dict[str, Any]
) -> None:
    issue_no = str(issue["issue_no"])
    header_key = (
        "expected_canonical_header"
        if issue["operation"] == "merge_duplicate_into_canonical"
        else "expected_legacy_header"
    )
    expected = dict(issue[header_key])
    expected_raw = expected.get("raw_json")
    expected_raw = dict(expected_raw) if isinstance(expected_raw, dict) else {}
    expected_raw[REPAIR_EVIDENCE_KEY] = stored_receipt
    expected.update(
        {
            "game_type": "t14c",
            "source_game_type": "t14c",
            "source_game_no": 90,
            "source_game_no_source": "sporttery_history_api",
            "raw_json": expected_raw,
            "raw_hash": _pool_raw_hash(expected_raw),
        }
    )
    actual = _header_public(current)
    for field, value in expected.items():
        if field == "raw_json_md5":
            # PostgreSQL's jsonb text formatting differs from Python's JSON
            # formatter. Exact raw_json equality and raw_hash validate content.
            continue
        if actual.get(field) != value:
            raise ValueError(f"issue {issue_no} repaired header field {field} changed")


def _already_repaired(cur, plan_sha256: str, issue: dict[str, Any]) -> bool:
    issue_no = str(issue["issue_no"])
    receipt = _repair_receipt(plan_sha256, issue)
    canonical_id = int(issue.get("canonical_issue_id") or issue["legacy_issue_id"])
    canonical = _load_header(cur, canonical_id, lock=True)
    if canonical is None:
        return False
    raw_json = canonical[11]
    if not isinstance(raw_json, dict):
        return False
    stored_receipt = raw_json.get(REPAIR_EVIDENCE_KEY)
    if not isinstance(stored_receipt, dict) or any(
        stored_receipt.get(key) != value for key, value in receipt.items()
    ):
        return False
    recorded_member_hash = stored_receipt.get("post_members_sha256")
    if not isinstance(recorded_member_hash, str) or len(recorded_member_hash) != 64:
        raise ValueError(f"issue {issue_no} repair receipt lacks its post-state member hash")
    if any(character not in "0123456789abcdef" for character in recorded_member_hash):
        raise ValueError(f"issue {issue_no} repair receipt has an invalid member hash")
    _assert_repaired_header_matches(canonical, issue, stored_receipt)
    _, current_members = _load_members(cur, canonical_id, lock=True)
    if _member_state_sha256(current_members) != recorded_member_hash:
        raise ValueError(f"issue {issue_no} canonical member state changed after repair")
    if issue["operation"] == "merge_duplicate_into_canonical":
        donor = _load_header(cur, int(issue["legacy_issue_id"]), lock=True)
        if donor is not None:
            raise ValueError(f"issue {issue_no} duplicate still exists despite its repair receipt")
        cur.execute(
            "SELECT id FROM football_pool_issues WHERE game_type='bqc6' AND issue_no=%s FOR UPDATE",
            (issue_no,),
        )
        if cur.fetchone() is not None:
            raise ValueError(f"issue {issue_no} has a replacement duplicate after repair")
        if len(current_members) != 14:
            raise ValueError(f"issue {issue_no} canonical roster changed after duplicate merge")
        _verify_official_match_rows(cur, issue_no, current_members)
        expected_donor = {
            int(member["match_order"]): member for member in issue["expected_legacy_roster"]
        }
        for current_member in current_members:
            match_order = int(current_member["match_order"])
            source_raw_json = current_member["source_raw_json"]
            if not isinstance(source_raw_json, dict):
                raise ValueError(f"issue {issue_no} canonical member receipt is missing")
            expected_member_receipt = _member_merge_receipt(
                plan_sha256, issue, expected_donor[int(match_order)]
            )
            if source_raw_json.get(MEMBER_EVIDENCE_KEY) != expected_member_receipt:
                raise ValueError(
                    f"issue {issue_no} member merge receipts are incomplete or changed"
                )
        if set(expected_donor) != set(range(1, 15)):
            raise ValueError(f"issue {issue_no} member merge receipts are incomplete")
    else:
        _validate_roster(issue_no, current_members, issue["expected_legacy_roster"])
    return True


def _apply_reclassification(cur, plan_sha256: str, issue: dict[str, Any]) -> bool:
    issue_no = str(issue["issue_no"])
    donor_id = int(issue["legacy_issue_id"])
    header = _load_header(cur, donor_id, lock=True)
    if header is None:
        if _already_repaired(cur, plan_sha256, issue):
            return False
        raise ValueError(f"issue {issue_no} legacy issue disappeared after plan creation")
    if header[1] == "t14c" and _already_repaired(cur, plan_sha256, issue):
        return False
    if header[1] != "bqc6" or header[3] != issue_no:
        raise ValueError(f"issue {issue_no} legacy issue key changed")
    _assert_header_matches(header, issue["expected_legacy_header"], issue_no, "legacy")
    if header[2] not in (None, "bqc6") or header[9] is not None or header[10] is not None:
        raise ValueError(f"issue {issue_no} already has conflicting source type metadata")
    if header[4] != 14:
        raise ValueError(f"issue {issue_no} is not the expected 14-slot legacy roster")
    if int(header[8]) != 0:
        raise ValueError(f"issue {issue_no} has saved combinations; refusing reclassification")
    cur.execute(
        "SELECT id FROM football_pool_issues WHERE game_type='t14c' AND issue_no=%s FOR UPDATE",
        (issue_no,),
    )
    if cur.fetchone() is not None:
        raise ValueError(
            f"issue {issue_no} already has a t14c key; duplicate merge must be audited"
        )
    _, members = _load_members(cur, donor_id, lock=True)
    _validate_roster(issue_no, members, issue["expected_legacy_roster"])
    _validate_source_roster(issue_no, members, issue["expected_source_roster"])
    _verify_official_match_rows(cur, issue_no, members)
    receipt = _repair_receipt(plan_sha256, issue)
    receipt["post_members_sha256"] = _member_state_sha256(members)
    _add_header_receipt(cur, header, receipt, game_type="t14c")
    return True


def _verify_official_match_rows(cur, issue_no: str, members: list[dict[str, Any]]) -> None:
    ids = sorted({int(row["match_id"]) for row in members if row.get("match_id") is not None})
    if not ids:
        return
    cur.execute(
        """SELECT id,home_team_name,away_team_name,
                  kickoff_time::date::text,business_date::text
           FROM official_matches WHERE id=ANY(%s) ORDER BY id""",
        (ids,),
    )
    # Sporttery's business_date follows the match-code day (for example,
    # Wednesday's slate can contain a Thursday 00:45 kickoff). Pool identity
    # uses the actual kickoff calendar date when it is available.
    matches = {int(row[0]): (row[1], row[2], row[3] or row[4]) for row in cur.fetchall()}
    if set(matches) != set(ids):
        raise ValueError(f"issue {issue_no} references a missing official match")
    for member in members:
        match_id = member.get("match_id")
        if match_id is None:
            continue
        home, away, match_date = matches[int(match_id)]
        if (
            _normalized_team(home) != _normalized_team(member["home_team_name"])
            or _normalized_team(away) != _normalized_team(member["away_team_name"])
            or str(match_date)[:10] != _identity_date(member)
        ):
            raise ValueError(f"issue {issue_no} official-match link differs from its slot identity")


def _apply_duplicate_merge(cur, plan_sha256: str, issue: dict[str, Any]) -> tuple[bool, int]:
    issue_no = str(issue["issue_no"])
    donor_id = int(issue["legacy_issue_id"])
    canonical_id = int(issue["canonical_issue_id"])
    donor = _load_header(cur, donor_id, lock=True)
    canonical = _load_header(cur, canonical_id, lock=True)
    if donor is None:
        if _already_repaired(cur, plan_sha256, issue):
            return False, 0
        raise ValueError(f"issue {issue_no} duplicate legacy issue disappeared without receipt")
    if canonical is None:
        raise ValueError(f"issue {issue_no} canonical t14c issue disappeared")
    if donor[1] != "bqc6" or donor[3] != issue_no:
        raise ValueError(f"issue {issue_no} duplicate legacy issue key changed")
    if canonical[1] != "t14c" or canonical[3] != issue_no:
        raise ValueError(f"issue {issue_no} canonical issue key changed")
    _assert_header_matches(donor, issue["expected_legacy_header"], issue_no, "legacy")
    _assert_header_matches(canonical, issue["expected_canonical_header"], issue_no, "canonical")
    if donor[2] not in (None, "bqc6") or donor[9] is not None or donor[10] is not None:
        raise ValueError(f"issue {issue_no} duplicate has conflicting source type metadata")
    if canonical[2] not in (None, "t14c"):
        raise ValueError(f"issue {issue_no} canonical source type conflicts")
    if donor[4] != 14 or canonical[4] != 14:
        raise ValueError(f"issue {issue_no} duplicate pair is not 14 slots")
    if int(donor[8]) != 0 or int(canonical[8]) != 0:
        raise ValueError(f"issue {issue_no} has saved combinations; refusing duplicate merge")
    if (donor[5], donor[6]) != (canonical[5], canonical[6]):
        raise ValueError(f"issue {issue_no} duplicate sale windows differ")
    _, donor_members = _load_members(cur, donor_id, lock=True)
    _, canonical_members = _load_members(cur, canonical_id, lock=True)
    _validate_roster(issue_no, donor_members, issue["expected_legacy_roster"])
    _validate_roster(issue_no, canonical_members, issue["expected_canonical_roster"])
    _validate_source_roster(issue_no, donor_members, issue["expected_source_roster"])
    _validate_source_roster(issue_no, canonical_members, issue["expected_source_roster"])
    _verify_official_match_rows(cur, issue_no, canonical_members)
    _verify_official_match_rows(cur, issue_no, donor_members)
    _assert_safe_delete_schema(cur)
    _assert_no_references_block_delete(cur, donor_id, issue_no)

    transferred = 0
    scalar_fields = (
        "source_match_id",
        "source_full_home_goals",
        "source_full_away_goals",
        "source_half_home_goals",
        "source_half_away_goals",
        "source_product_result_code",
        "source_result_semantics_key",
        "source_result_source",
        "home_win_prob",
        "draw_prob",
        "away_win_prob",
        "upset_score",
        "public_heat_home",
        "public_heat_draw",
        "public_heat_away",
    )
    evidence_fields = ("kickoff_evidence", "source_result_evidence", "identity_evidence")
    for donor_member, canonical_member in zip(donor_members, canonical_members, strict=True):
        donor_match = donor_member["match_id"]
        canonical_match = canonical_member["match_id"]
        if donor_match is not None and canonical_match not in (None, donor_match):
            raise ValueError(
                f"issue {issue_no} slot {donor_member['match_order']} has conflicting official matches"
            )
        if donor_member["fixture_id"] is not None or canonical_member["fixture_id"] is not None:
            if donor_member["fixture_id"] != canonical_member["fixture_id"]:
                raise ValueError(
                    f"issue {issue_no} slot {donor_member['match_order']} has conflicting fixture links"
                )
            raise ValueError(
                f"issue {issue_no} already has a shared fixture link; manual merge review required"
            )
        updates: dict[str, Any] = {}
        for field in scalar_fields:
            donor_value = donor_member[field]
            canonical_value = canonical_member[field]
            if canonical_value is None and donor_value is not None:
                updates[field] = donor_value
            elif (
                donor_value is not None
                and canonical_value is not None
                and donor_value != canonical_value
            ):
                raise ValueError(
                    f"issue {issue_no} slot {donor_member['match_order']} has conflicting {field} values"
                )

        donor_time = donor_member["kickoff_time"]
        canonical_time = canonical_member["kickoff_time"]
        donor_precision = donor_member["kickoff_time_precision"]
        canonical_precision = canonical_member["kickoff_time_precision"]
        if canonical_member["kickoff_date"] is None and donor_member["kickoff_date"] is not None:
            updates["kickoff_date"] = donor_member["kickoff_date"]
        if donor_time is not None and canonical_time is None:
            updates["kickoff_time"] = donor_time
            updates["kickoff_time_precision"] = donor_precision
            updates["kickoff_date"] = donor_member["kickoff_date"]
        elif donor_time is not None and canonical_time is not None and donor_time != canonical_time:
            raise ValueError(
                f"issue {issue_no} slot {donor_member['match_order']} has conflicting kickoff_time values"
            )
        elif (
            donor_precision in {"minute", "second"}
            and canonical_precision == "date_only"
            and donor_member["kickoff_date"] == canonical_member["kickoff_date"]
        ):
            updates["kickoff_time_precision"] = donor_precision
        elif canonical_precision == "unknown" and donor_precision != "unknown":
            updates["kickoff_time_precision"] = donor_precision
        elif (
            donor_precision == "second"
            and canonical_precision == "minute"
            and donor_time == canonical_time
        ):
            updates["kickoff_time_precision"] = "second"
        elif (
            donor_precision != canonical_precision
            and donor_precision not in (None, "unknown")
            and canonical_precision not in (None, "unknown")
            and not (
                donor_precision in {"minute", "second"}
                and canonical_precision == "date_only"
                and donor_member["kickoff_date"] == canonical_member["kickoff_date"]
            )
        ):
            raise ValueError(
                f"issue {issue_no} slot {donor_member['match_order']} has conflicting kickoff precision"
            )

        if (
            donor_member["identity_status"] == "conflict"
            and canonical_member["identity_status"] != "conflict"
        ):
            updates["identity_status"] = "conflict"
        elif (
            donor_member["identity_status"] != canonical_member["identity_status"]
            and donor_member["identity_status"] != "conflict"
            and canonical_member["identity_status"] != "conflict"
        ):
            raise ValueError(
                f"issue {issue_no} slot {donor_member['match_order']} has conflicting identity_status values"
            )

        for field in evidence_fields:
            donor_value = donor_member[field]
            canonical_value = canonical_member[field]
            if not canonical_value and donor_value:
                updates[field] = donor_value
            elif canonical_value and donor_value:
                updates[field] = _member_evidence_merge(
                    canonical_value,
                    donor_value,
                    f"{issue_no} slot {donor_member['match_order']} {field}",
                )

        raw_value = canonical_member["source_raw_json"] or {}
        if not isinstance(raw_value, dict):
            raise ValueError(f"issue {issue_no} slot raw evidence is not an object")
        donor_raw = donor_member["source_raw_json"] or {}
        if not isinstance(donor_raw, dict):
            raise ValueError(f"issue {issue_no} donor slot raw evidence is not an object")
        if not raw_value and donor_raw:
            raw_value = donor_raw
        member_receipt = _member_merge_receipt(plan_sha256, issue, donor_member)
        old_receipt = raw_value.get(MEMBER_EVIDENCE_KEY)
        if old_receipt is not None and old_receipt != member_receipt:
            raise ValueError(f"issue {issue_no} slot already has conflicting merge evidence")
        raw_value[MEMBER_EVIDENCE_KEY] = member_receipt
        if donor_match is not None and canonical_match is None:
            updates["match_id"] = donor_match
            transferred += 1
        updates["source_raw_json"] = raw_value
        assignments = ",".join(f"{field}=%s" for field in updates)
        values = [Json(value) if isinstance(value, dict) else value for value in updates.values()]
        cur.execute(
            f"UPDATE football_pool_issue_matches SET {assignments} WHERE id=%s",
            (*values, canonical_member["membership_id"]),
        )

    _, post_members = _load_members(cur, canonical_id, lock=True)
    if len(post_members) != 14:
        raise ValueError(f"issue {issue_no} canonical roster changed during duplicate merge")
    receipt = _repair_receipt(plan_sha256, issue)
    receipt["post_members_sha256"] = _member_state_sha256(post_members)
    _add_header_receipt(cur, canonical, receipt, game_type="t14c")
    cur.execute("DELETE FROM football_pool_issue_matches WHERE issue_id=%s", (donor_id,))
    deleted_members = cur.rowcount
    if deleted_members != 14:
        raise ValueError(f"issue {issue_no} deleted an unexpected number of duplicate slots")
    cur.execute("DELETE FROM football_pool_issues WHERE id=%s", (donor_id,))
    if cur.rowcount != 1:
        raise ValueError(f"issue {issue_no} duplicate header was not removed exactly once")
    return True, transferred


def apply_issue_type_repair(conn, plan: dict[str, Any]) -> dict[str, int]:
    plan_sha256 = _validate_plan(plan)
    counts = {
        "reclassified_issues": 0,
        "merged_duplicate_issues": 0,
        "deleted_duplicate_members": 0,
        "transferred_match_links": 0,
        "already_repaired_issues": 0,
    }
    if not plan["issues"]:
        return counts

    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        cur.execute("SET LOCAL lock_timeout = '2s'")
        cur.execute("SET LOCAL statement_timeout = '90s'")
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (IDENTITY_LOCK,))
        _require_migration_128(conn)
        for issue in plan["issues"]:
            if issue["operation"] == "reclassify_header":
                if _apply_reclassification(cur, plan_sha256, issue):
                    counts["reclassified_issues"] += 1
                else:
                    counts["already_repaired_issues"] += 1
            else:
                changed, transferred = _apply_duplicate_merge(cur, plan_sha256, issue)
                if changed:
                    counts["merged_duplicate_issues"] += 1
                    counts["deleted_duplicate_members"] += 14
                    counts["transferred_match_links"] += transferred
                else:
                    counts["already_repaired_issues"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument(
        "--apply", action="store_true", help="Apply to a loopback/local PostgreSQL target"
    )
    args = parser.parse_args(argv)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    digest = _validate_plan(plan)
    report = {
        "mode": "apply" if args.apply else "plan",
        "contract": CONTRACT,
        "plan_sha256": digest,
        "issue_count": len(plan["issues"]),
        "reclassify_header_count": sum(
            row["operation"] == "reclassify_header" for row in plan["issues"]
        ),
        "merge_duplicate_count": sum(
            row["operation"] == "merge_duplicate_into_canonical" for row in plan["issues"]
        ),
        "database_writes": 0,
        "backup": False,
    }
    if args.apply:
        params = _local_database_parameters()
        with closing(psycopg2.connect(**params)) as conn, conn:
            report.update(apply_issue_type_repair(conn, plan))
        report["database_writes"] = sum(
            report[key]
            for key in (
                "reclassified_issues",
                "merged_duplicate_issues",
                "deleted_duplicate_members",
            )
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
