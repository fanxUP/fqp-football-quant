"""Backfill Sporttery-official historical football results from Uniform API.

Each successful official response is retained as a local JSON artifact before
it is parsed and stored. The importer then keeps the immutable Sporttery
``matchId``, ticket-visible code, raw response lineage, and result details.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

from scripts.official_history_importer import import_local_official_results_file

UNIFORM_RESULT_URL = (
    "https://webapi.sporttery.cn/gateway/uniform/football/"
    "getUniformMatchResultV1.qry"
)
RESULT_REFERER = "https://www.lottery.gov.cn/jc/zqsgkj/"
DEFAULT_OUTPUT_DIR = Path("data/official_history/uniform_results")


def month_chunks(start: date, end: date) -> Iterator[tuple[str, str]]:
    """Yield inclusive monthly date windows for the official historical API."""
    cursor = start.replace(day=1)
    while cursor <= end:
        if cursor.month == 12:
            next_month = cursor.replace(year=cursor.year + 1, month=1)
        else:
            next_month = cursor.replace(month=cursor.month + 1)
        month_end = next_month.fromordinal(next_month.toordinal() - 1)
        yield max(start, cursor).isoformat(), min(end, month_end).isoformat()
        cursor = next_month


def build_artifact(
    *,
    response: dict[str, Any],
    request_params: dict[str, Any],
    request_url: str,
    retrieved_at: str,
) -> dict[str, Any]:
    """Wrap one exact response with enough metadata for a later audit."""
    return {
        "source_name": "sporttery",
        "source_url": UNIFORM_RESULT_URL,
        "request_url": request_url,
        "request_params": request_params,
        "retrieved_at": retrieved_at,
        "response": response,
    }


def fetch_and_backfill(
    *,
    start_date: str,
    end_date: str,
    output_dir: Path,
    dry_run: bool = False,
    pause_seconds: float = 0.8,
) -> dict[str, Any]:
    """Fetch all official pages, retain artifacts, and import each page safely."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start > end:
        raise ValueError("start_date must not be later than end_date")

    output_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Referer": RESULT_REFERER,
        "Accept": "application/json, text/plain, */*",
    }

    with httpx.Client(headers=headers, timeout=40.0, follow_redirects=True) as client:
        for begin, finish in month_chunks(start, end):
            page, pages = 1, 1
            while page <= pages:
                params: dict[str, str | int] = {
                    "matchBeginDate": begin,
                    "matchEndDate": finish,
                    "leagueId": "",
                    "pageSize": 100,
                    "pageNo": page,
                    "isFix": 0,
                    "matchPage": 1,
                    "pcOrWap": 1,
                }
                response = client.get(UNIFORM_RESULT_URL, params=params)
                response.raise_for_status()
                payload = response.json()
                if str(payload.get("errorCode")) != "0":
                    raise RuntimeError(
                        f"Sporttery returned {payload.get('errorCode')}: "
                        f"{payload.get('errorMessage')} for {begin}~{finish} page {page}"
                    )

                value = payload.get("value") or {}
                pages = int(value.get("pages") or 1)
                artifact = build_artifact(
                    response=payload,
                    request_params=params,
                    request_url=str(response.url),
                    retrieved_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                )
                artifact_path = output_dir / f"{begin}_{finish}_p{page:03d}.json"
                artifact_path.write_text(
                    json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                imported = import_local_official_results_file(
                    str(artifact_path), dry_run=dry_run
                )
                if imported["status"] != "ok":
                    raise RuntimeError(
                        f"Official artifact import was not clean for {artifact_path}: "
                        f"{json.dumps(imported, ensure_ascii=False)}"
                    )
                summaries.append(
                    {
                        "artifact_path": str(artifact_path),
                        "requested_window": [begin, finish],
                        "page": page,
                        **imported,
                    }
                )
                page += 1
                if page <= pages:
                    time.sleep(pause_seconds)

    totals = {
        "artifacts": len(summaries),
        "matches_found": sum(item.get("matches_found", 0) for item in summaries),
        "results_found": sum(item.get("results_found", 0) for item in summaries),
        "matches_inserted": sum(item.get("matches_inserted", 0) for item in summaries),
        "matches_updated": sum(item.get("matches_updated", 0) for item in summaries),
        "results_inserted": sum(item.get("results_inserted", 0) for item in summaries),
        "results_updated": sum(item.get("results_updated", 0) for item in summaries),
    }
    summary = {
        "status": "ok",
        "dry_run": dry_run,
        "start_date": start_date,
        "end_date": end_date,
        "totals": totals,
        "artifacts": summaries,
    }
    (output_dir / "run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pause-seconds", type=float, default=0.8)
    args = parser.parse_args()

    result = fetch_and_backfill(
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
        pause_seconds=args.pause_seconds,
    )
    print(json.dumps(result["totals"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
