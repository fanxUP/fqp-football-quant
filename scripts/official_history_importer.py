"""Import Sporttery official historical result payloads from local artifacts.

This module intentionally reads local HTML/HAR/JSON files instead of browsing
sporttery.cn. It preserves the Sporttery-only official boundary while giving
the operator a way to import data from pages that can be opened manually but
cannot be read reliably by automation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

from apps.backend.src.db import get_db
from scripts.official_crawler import parse_results_from_response
from scripts.official_storage import (
    record_official_collection_status,
    store_matches,
    store_results,
)

SPORTTERY_RESULT_URL = "https://www.sporttery.cn/jc/zqsgkj/"
OFFICIAL_MATCH_CODE_RE = re.compile(r"^周([一二三四五六日天])(\d{3})$")
WEEKDAY_LABELS = "一二三四五六日"


def _artifact_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _has_result_list(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    value = payload.get("value")
    if isinstance(value, dict) and (
        isinstance(value.get("matchResultList"), list)
        or isinstance(value.get("matchInfoList"), list)
        or isinstance(value.get("matchResult"), list)
    ):
        return True
    return isinstance(payload.get("matchResultList"), list) or isinstance(
        payload.get("matchInfoList"), list
    ) or isinstance(payload.get("matchResult"), list)


def _walk_payloads(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if _has_result_list(value):
            found.append(value)
            return found
        for child in value.values():
            found.extend(_walk_payloads(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_payloads(child))
    return found


def _json_candidates_from_text(text: str) -> list[str]:
    candidates: list[str] = []
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\{\[]", text):
        try:
            _, end = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        candidates.append(text[match.start() : match.start() + end])
    return candidates


def extract_official_result_payloads(text: str) -> list[dict[str, Any]]:
    """Extract Sporttery result JSON payloads from HAR, raw JSON, or saved HTML."""
    payloads: list[dict[str, Any]] = []

    for candidate in [text, *_json_candidates_from_text(text)]:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue

        if isinstance(parsed, dict) and isinstance(parsed.get("log"), dict):
            for entry in parsed["log"].get("entries", []):
                url = ((entry.get("request") or {}).get("url") or "").lower()
                content = (entry.get("response") or {}).get("content") or {}
                body = content.get("text")
                if "getmatchresultv1.qry" not in url or not isinstance(body, str):
                    continue
                try:
                    response_payload = json.loads(body)
                except json.JSONDecodeError:
                    continue
                payloads.extend(_walk_payloads(response_payload))
            continue

        payloads.extend(_walk_payloads(parsed))

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for payload in payloads:
        if isinstance(payload.get("value"), dict):
            result_block = payload["value"].get("matchResultList") or payload["value"].get(
                "matchInfoList"
            ) or payload["value"].get("matchResult")
        else:
            result_block = (
                payload.get("matchResultList")
                or payload.get("matchInfoList")
                or payload.get("matchResult")
            )
        fingerprint = json.dumps(result_block or payload, ensure_ascii=False, sort_keys=True)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(payload)
    return unique


def parse_local_official_results_text(
    text: str,
    source_path: str,
    source_url: str = SPORTTERY_RESULT_URL,
) -> list[dict[str, Any]]:
    """Parse local Sporttery official result artifacts into normalized results."""
    artifact_hash = _artifact_hash(text)
    parsed_results: list[dict[str, Any]] = []
    for payload in extract_official_result_payloads(text):
        for result in parse_results_from_response(payload):
            raw = dict(result.get("raw_json") or {})
            raw["_source_artifact"] = {
                "path": source_path,
                "hash": artifact_hash,
                "source_url": source_url,
            }
            result["raw_json"] = raw
            parsed_results.append(result)
    return parsed_results


def _result_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("value")
    containers = [value] if isinstance(value, dict) else []
    containers.append(payload)
    for container in containers:
        rows = (
            container.get("matchResultList")
            or container.get("matchInfoList")
            or container.get("matchResult")
        )
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _uses_uniform_result_shape(payload: dict[str, Any]) -> bool:
    value = payload.get("value")
    return isinstance(value, dict) and isinstance(value.get("matchResult"), list)


def _first_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def normalize_official_match_code(value: str) -> str:
    value = value.strip().replace("周天", "周日")
    return value if OFFICIAL_MATCH_CODE_RE.fullmatch(value) else ""


def official_match_identity_error(business_date: str, match_code: str) -> str | None:
    if not business_date:
        return "missing official business_date"
    if not match_code:
        return "missing or invalid official display match code"
    try:
        parsed_date = date.fromisoformat(business_date)
    except ValueError:
        return "invalid official business_date"
    match = OFFICIAL_MATCH_CODE_RE.fullmatch(match_code)
    if match is None or match.group(1) != WEEKDAY_LABELS[parsed_date.weekday()]:
        return "match code weekday does not match business_date"
    return None


def derive_business_date_from_match_date(match_date: str, match_code: str) -> str:
    """Derive the ticket business date for uniform result rows without it.

    The official uniform result endpoint supplies the scheduled calendar date
    and the ticket-visible weekday code, but not ``businessDate``. A match
    kicking off after midnight can therefore be listed under the prior ticket
    day. The latest matching weekday on or before ``matchDate`` is the only
    date consistent with both official fields.
    """
    normalized_code = normalize_official_match_code(match_code)
    match = OFFICIAL_MATCH_CODE_RE.fullmatch(normalized_code)
    if not match:
        return ""
    try:
        parsed_date = date.fromisoformat(match_date)
    except ValueError:
        return ""
    target_weekday = WEEKDAY_LABELS.index(match.group(1))
    offset = (parsed_date.weekday() - target_weekday) % 7
    return (parsed_date - timedelta(days=offset)).isoformat()


def parse_local_official_history_text(
    text: str,
    source_path: str,
    source_url: str = SPORTTERY_RESULT_URL,
    default_business_date: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Parse identity-safe historical matches and results from an official artifact.

    A row is accepted only when it has Sporttery's display code (``周五098``)
    and an official business date whose weekday agrees with that code. This is
    deliberately stricter than the legacy result-only parser because display
    codes repeat every week and must never be resolved by code alone.
    """
    artifact_hash = _artifact_hash(text)
    matches: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_identities: set[tuple[str, str]] = set()

    for payload in extract_official_result_payloads(text):
        uses_uniform_result_shape = _uses_uniform_result_shape(payload)
        for row in _result_rows(payload):
            match_code = normalize_official_match_code(
                _first_text(row, "matchNumStr", "matchCode", "matchNum")
            )
            business_date = _first_text(
                row, "businessDate", "matchBusinessDate", "betDate"
            ) or (default_business_date or "")
            derived_business_date = False
            if not business_date and match_code and uses_uniform_result_shape:
                business_date = derive_business_date_from_match_date(
                    _first_text(row, "matchDate"), match_code
                )
                derived_business_date = bool(business_date)
            error = official_match_identity_error(business_date, match_code)
            if error:
                rejected.append(
                    {
                        "business_date": business_date,
                        "official_match_code": _first_text(
                            row, "matchNumStr", "matchCode", "matchNum"
                        ),
                        "reason": error,
                    }
                )
                continue

            normalized_results = parse_results_from_response({"matchResultList": [row]})
            if not normalized_results:
                rejected.append(
                    {
                        "business_date": business_date,
                        "official_match_code": match_code,
                        "reason": "could not parse official result row",
                    }
                )
                continue
            result = normalized_results[0]

            identity = (business_date, match_code)
            if identity in seen_identities:
                continue
            seen_identities.add(identity)

            source_match_id = _first_text(row, "matchId")
            raw = dict(result.get("raw_json") or row)
            if derived_business_date:
                raw["_business_date_derivation"] = {
                    "method": "official_match_date_and_display_code",
                    "match_date": _first_text(row, "matchDate"),
                    "official_match_code": match_code,
                    "derived_business_date": business_date,
                }
            raw["_source_artifact"] = {
                "path": source_path,
                "hash": artifact_hash,
                "source_url": source_url,
            }
            result["raw_json"] = raw
            result["_business_date"] = business_date
            result["_match_code"] = match_code
            result["_source_match_id"] = source_match_id
            results.append(result)

            league_name = _first_text(
                row, "leagueAllName", "leagueName", "leagueAbbName"
            )
            home_team_name = _first_text(
                row, "homeTeamAllName", "allHomeTeam", "homeTeamName", "homeTeam"
            )
            away_team_name = _first_text(
                row, "awayTeamAllName", "allAwayTeam", "awayTeamName", "awayTeam"
            )
            match_date = _first_text(row, "matchDate")
            match_time = _first_text(row, "matchTime")
            kickoff_time = (
                f"{match_date}T{match_time}"
                if match_date and match_time and "T" not in match_time
                else match_time or (f"{match_date}T00:00:00" if match_date else "")
            )
            if league_name and home_team_name and away_team_name and kickoff_time:
                matches.append(
                    {
                        "sport_type": "football",
                        "business_date": business_date,
                        "official_match_code": match_code,
                        "source_match_id": source_match_id or None,
                        "league_name": league_name,
                        "home_team_name": home_team_name,
                        "away_team_name": away_team_name,
                        "kickoff_time": kickoff_time,
                        "sale_stop_time": None,
                        "sale_status": "finished",
                        "match_status": "Settled",
                        "source_url": source_url,
                        "raw_json": raw,
                    }
                )

    return {"matches": matches, "results": results, "rejected": rejected}


def resolve_official_match_id(
    cursor: Any,
    *,
    source_match_id: str,
    business_date: str,
    match_code: str,
) -> int | None:
    """Resolve a historical result without ever matching a weekly code alone."""
    if source_match_id:
        cursor.execute(
            "SELECT id FROM official_matches WHERE source_match_id = %s",
            (source_match_id,),
        )
        row = cursor.fetchone()
        if row:
            return int(row[0])

    cursor.execute(
        """
        SELECT id FROM official_matches
        WHERE business_date = %s AND official_match_code = %s
        """,
        (business_date, match_code),
    )
    row = cursor.fetchone()
    return int(row[0]) if row else None


def import_local_official_results_file(
    path: str,
    business_date: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import one local Sporttery result artifact into official_results."""
    artifact = Path(path)
    text = artifact.read_text(encoding="utf-8")
    artifact_hash = _artifact_hash(text)
    history = parse_local_official_history_text(
        text,
        source_path=str(artifact),
        default_business_date=business_date,
    )
    matches = history["matches"]
    results = history["results"]
    rejected = history["rejected"]
    log_business_date = business_date or min(
        (result["_business_date"] for result in results),
        default=date.today().isoformat(),
    )

    if dry_run:
        return {
            "status": "ok" if not rejected else "partial",
            "dry_run": True,
            "matches_found": len(matches),
            "results_found": len(results),
            "rejected": rejected,
            "source_artifact_hash": artifact_hash,
        }

    with get_db() as conn:
        stored_matches = store_matches(conn, matches) if matches else {
            "inserted": 0,
            "updated": 0,
            "errors": [],
        }
        matched: list[dict[str, Any]] = []
        unresolved: list[str] = []
        with conn.cursor() as cur:
            for result in results:
                code = result.get("_match_code", "")
                result_business_date = result.get("_business_date", "")
                match_id = resolve_official_match_id(
                    cur,
                    source_match_id=result.get("_source_match_id", ""),
                    business_date=result_business_date,
                    match_code=code,
                )
                if match_id is not None:
                    result["match_id"] = match_id
                    matched.append(result)
                else:
                    unresolved.append(f"{result_business_date}/{code}")

        stored = store_results(conn, matched) if matched else {
            "inserted": 0,
            "updated": 0,
            "errors": [],
        }
        matches_inserted = cast(int, stored_matches.get("inserted", 0) or 0)
        results_inserted = cast(int, stored.get("inserted", 0) or 0)
        matches_updated = cast(int, stored_matches.get("updated", 0) or 0)
        results_updated = cast(int, stored.get("updated", 0) or 0)
        record_official_collection_status(
            conn,
            business_date=log_business_date,
            crawl_type="results_import",
            source_name="sporttery",
            status="ok" if not unresolved and not rejected else "partial",
            source_url=SPORTTERY_RESULT_URL,
            source_artifact_path=str(artifact),
            source_artifact_hash=artifact_hash,
            records_found=len(results) + len(rejected),
            records_inserted=matches_inserted + results_inserted,
            records_updated=matches_updated + results_updated,
            error_message=(
                f"unresolved identities: {', '.join(unresolved)}; "
                f"rejected rows: {len(rejected)}"
                if unresolved or rejected
                else None
            ),
            raw_json={"unresolved_match_identities": unresolved, "rejected": rejected},
        )

    return {
        "status": "ok" if not unresolved and not rejected else "partial",
        "matches_found": len(matches),
        "matches_inserted": stored_matches.get("inserted", 0),
        "matches_updated": stored_matches.get("updated", 0),
        "results_found": len(results),
        "results_matched": len(matched),
        "results_inserted": stored.get("inserted", 0),
        "results_updated": stored.get("updated", 0),
        "unresolved_match_identities": unresolved,
        "rejected": rejected,
        "source_artifact_hash": artifact_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Saved Sporttery HTML, HAR, or JSON artifact")
    parser.add_argument(
        "--business-date",
        help="Fallback official business date for a verified single-day artifact only",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = import_local_official_results_file(
        args.path,
        business_date=args.business_date,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"ok", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
