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
from pathlib import Path
from typing import Any

from apps.backend.src.db import get_db
from scripts.official_crawler import parse_results_from_response
from scripts.official_storage import record_official_collection_status, store_results

SPORTTERY_RESULT_URL = "https://www.sporttery.cn/jc/zqsgkj/"


def _artifact_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _has_result_list(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    value = payload.get("value")
    if isinstance(value, dict) and (
        isinstance(value.get("matchResultList"), list)
        or isinstance(value.get("matchInfoList"), list)
    ):
        return True
    return isinstance(payload.get("matchResultList"), list) or isinstance(
        payload.get("matchInfoList"), list
    )


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
            )
        else:
            result_block = payload.get("matchResultList") or payload.get("matchInfoList")
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


def import_local_official_results_file(
    path: str,
    business_date: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import one local Sporttery result artifact into official_results."""
    artifact = Path(path)
    text = artifact.read_text(encoding="utf-8")
    artifact_hash = _artifact_hash(text)
    results = parse_local_official_results_text(text, source_path=str(artifact))

    if dry_run:
        return {
            "status": "ok",
            "dry_run": True,
            "results_found": len(results),
            "source_artifact_hash": artifact_hash,
        }

    with get_db() as conn:
        matched: list[dict[str, Any]] = []
        unresolved: list[str] = []
        with conn.cursor() as cur:
            for result in results:
                code = result.pop("_match_code", "")
                cur.execute(
                    """
                    SELECT id FROM official_matches
                    WHERE official_match_code = %s
                    ORDER BY business_date DESC
                    LIMIT 1
                    """,
                    (code,),
                )
                row = cur.fetchone()
                if row:
                    result["match_id"] = row[0]
                    matched.append(result)
                else:
                    unresolved.append(code)

        stored = store_results(conn, matched) if matched else {
            "inserted": 0,
            "updated": 0,
            "errors": [],
        }
        record_official_collection_status(
            conn,
            business_date=business_date,
            crawl_type="results_import",
            source_name="sporttery",
            status="ok" if not unresolved else "partial",
            source_url=SPORTTERY_RESULT_URL,
            source_artifact_path=str(artifact),
            source_artifact_hash=artifact_hash,
            records_found=len(results),
            records_inserted=stored.get("inserted", 0),
            records_updated=stored.get("updated", 0),
            error_message=f"unresolved match codes: {', '.join(unresolved)}"
            if unresolved
            else None,
            raw_json={"unresolved_match_codes": unresolved},
        )

    return {
        "status": "ok" if not unresolved else "partial",
        "results_found": len(results),
        "results_matched": len(matched),
        "results_inserted": stored.get("inserted", 0),
        "results_updated": stored.get("updated", 0),
        "unresolved_match_codes": unresolved,
        "source_artifact_hash": artifact_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Saved Sporttery HTML, HAR, or JSON artifact")
    parser.add_argument("--business-date", required=True, help="Official business date")
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
