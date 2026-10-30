"""Parse saved official traditional-football schedules into review candidates.

This offline command never connects to a database or fetches a URL. An official
notice can establish selection evidence without supplying exact kickoff times,
source match IDs, season membership, or the final applicable revision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

OFFICIAL_HOSTS = ("lottery.gov.cn", "sporttery.cn", "gdlottery.cn")
BUSINESS_ZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class _Cell:
    text: str
    origin: tuple[int, int]
    rowspan: int


def _grid(table: Tag) -> list[list[_Cell]]:
    cells: dict[tuple[int, int], _Cell] = {}
    rows = [r for r in table.find_all("tr") if r.find_parent("table") is table]
    if len(rows) > 40:
        raise ValueError("schedule table exceeds row bound")
    for r, row in enumerate(rows):
        col = 0
        for node in row.find_all(["td", "th"], recursive=False):
            while (r, col) in cells:
                col += 1
            spans = [node.get(key, "1") for key in ("rowspan", "colspan")]
            if not all(isinstance(value, str) and value.isdecimal() for value in spans):
                raise ValueError("unsupported table span")
            height, width = (int(str(value)) for value in spans)
            if not 1 <= height <= 28 or not 1 <= width <= 6 or col + width > 6:
                raise ValueError("unsupported table span")
            cell = _Cell(node.get_text(" ", strip=True), (r, col), height)
            for rr in range(r, r + height):
                for cc in range(col, col + width):
                    if (rr, cc) in cells:
                        raise ValueError("overlapping table span")
                    cells[rr, cc] = cell
            col += width
    return [[cells[r, c] for c in range(6) if (r, c) in cells] for r in range(len(rows))]


def _sale_time(text: str, label: str) -> str | None:
    match = re.search(label + r"\s*[:：]\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})", text)
    if not match:
        return None
    value = datetime.fromisoformat(" ".join(match.groups())).replace(tzinfo=BUSINESS_ZONE)
    return value.isoformat()


def _paired(a: list[_Cell], b: list[_Cell], columns: tuple[int, ...]) -> None:
    if any(a[c].origin != b[c].origin or a[c].rowspan != 2 for c in columns):
        raise ValueError("source paired cells do not establish two-slot match layout")


def _parse_table(table: Tag, heading: str, table_no: int) -> list[dict[str, Any]]:
    issue_match = re.search(r"第\s*(\d+)\s*期", heading)
    if issue_match is None:
        raise ValueError("missing issue number in schedule heading")
    issue_no = issue_match.group(1)
    games: tuple[str, ...]
    if "6场半全场" in heading:
        games, expected_slots, width = ("bqc6",), 12, 6
    elif "4场进球" in heading:
        games, expected_slots, width = ("jq4",), 8, 5
    elif "14场" in heading and "任选9场" in heading:
        games, expected_slots, width = ("t14c", "r9"), 14, 6
    else:
        raise ValueError("unsupported official schedule heading")
    grid = _grid(table)
    headers = ["期号", "赛制", "序号"] + (
        ["球队名称", "比赛日期"] if width == 5 else ["主队", "客队", "比赛日期"]
    )
    if not grid or [c.text for c in grid[0]] != headers:
        raise ValueError("unexpected official schedule columns")
    rows = [row for row in grid[1:] if len(row) == width and row[2].text.isdecimal()]
    if [int(row[2].text) for row in rows] != list(range(1, expected_slots + 1)):
        raise ValueError("incomplete or duplicate slot orders")
    for row in rows:
        if re.sub(r"\s", "", row[0].text) != f"第{issue_no}期":
            raise ValueError("heading/member issue mismatch")
        date.fromisoformat(row[-1].text)
        if not row[1].text or not row[3].text or (width == 6 and not row[4].text):
            raise ValueError("missing source team or competition")
    text = table.get_text(" ", strip=True)
    sale_start, sale_stop = _sale_time(text, "开售时间"), _sale_time(text, "停售时间")
    if sale_start and sale_stop and sale_start >= sale_stop:
        raise ValueError("conflicting sale window")
    matches: list[dict[str, Any]] = []
    stride = 1 if expected_slots == 14 else 2
    for index in range(0, expected_slots, stride):
        row = rows[index]
        if expected_slots == 12:
            _paired(row, rows[index + 1], (3, 4, 5))
            if row[1].text != rows[index + 1][1].text:
                raise ValueError("paired competition mismatch")
        if expected_slots == 8:
            _paired(row, rows[index + 1], (4,))
            if row[1].text != rows[index + 1][1].text:
                raise ValueError("paired competition mismatch")
        goals_game = expected_slots == 8
        matches.append(
            {
                "match_order": len(matches) + 1,
                "source_slot_orders": list(range(index + 1, index + stride + 1)),
                "league_name": row[1].text,
                "home_team_name": None if goals_game else row[3].text,
                "away_team_name": None if goals_game else row[4].text,
                "team_names_in_source_order": (
                    [row[3].text, rows[index + 1][3].text]
                    if goals_game
                    else [row[3].text, row[4].text]
                ),
                "orientation_status": "source_order_only" if goals_game else "explicit_columns",
                "match_date": row[-1].text,
                "date_timezone": "Asia/Shanghai",
                "kickoff_time": None,
                "time_precision": "day",
                "source_match_id": None,
                "season_id": None,
                "identity_status": "pending",
            }
        )
    return [
        {
            "game_type": game,
            "issue_no": issue_no,
            "table_no": table_no,
            "source_heading": heading,
            "source_slots": expected_slots,
            "total_matches": len(matches),
            "sale_start": sale_start,
            "sale_stop": sale_stop,
            "matches": matches,
        }
        for game in games
    ]


def parse_notice(html: bytes | str, *, source_url: str, retrieved_at: datetime) -> dict[str, Any]:
    """Extract dated selection candidates without inventing missing identities."""
    url = urlsplit(source_url)
    host = url.hostname or ""
    if url.scheme != "https" or not any(
        host == domain or host.endswith("." + domain) for domain in OFFICIAL_HOSTS
    ):
        raise ValueError("unsupported official source URL")
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at needs an explicit timezone")
    raw = html.encode("utf-8") if isinstance(html, str) else html
    if len(raw) > 5_000_000:
        raise ValueError("notice exceeds size bound")
    soup = BeautifulSoup(raw, "html.parser")
    issues = []
    for table_no, table in enumerate(soup.find_all("table"), 1):
        previous = table.find_previous(["p", "h2", "h3"])
        heading = previous.get_text(" ", strip=True) if previous else ""
        if "足球彩票" in heading and re.search(r"第\s*\d+\s*期", heading):
            issues.extend(_parse_table(table, heading, table_no))
    if not issues:
        raise ValueError("no supported official selection tables")
    keys = [(issue["game_type"], issue["issue_no"]) for issue in issues]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate game/issue tables need revision review")
    return {
        "schema_version": "fqp.official-pool-notice/v1",
        "source_url": source_url,
        "source_body_sha256": hashlib.sha256(raw).hexdigest(),
        "retrieved_at": retrieved_at.isoformat(),
        "evidence_kind": "official_schedule_notice",
        "ready_for_database_import": False,
        "final_revision_verified": False,
        "issues": issues,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--retrieved-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = parse_notice(
        args.html.read_bytes(), source_url=args.source_url, retrieved_at=args.retrieved_at
    )
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"issues": len(result["issues"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
