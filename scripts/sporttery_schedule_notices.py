"""Retain official sales arrangements and revisions without inferring missing fixtures."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup
from psycopg2.extras import Json

from apps.backend.src.db import get_db
from scripts.football_fixture_identity import IDENTITY_LOCK
from scripts.football_pool_notice import parse_notice
from scripts.prematch_schedule import BEIJING, acquire_prematch_notice_write_lock
from scripts.sporttery_client import SportteryClient

logger = logging.getLogger(__name__)
JC_NOTICE_PAGE = "https://www.sporttery.cn/ssgg/"
POOL_NOTICE_PAGE = "https://www.sporttery.cn/ctzc/zcgg/"
_POOL_LINK = re.compile(r"/ctzc/(?:zcgg|czgg)/(\d{8})/\d+\.html\Z")
_DATE = r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日"
_CLOCK = r"([0-2]?\d:[0-5]\d)"
_MAX_BODY_BYTES = 5_000_000


def _date(parts: tuple[str | None, str, str], published: datetime) -> date:
    year, month, day = parts
    return date(int(year) if year else published.year, int(month), int(day))


def parse_jc_bulletin(row: dict[str, Any]) -> tuple[datetime, dict] | None:
    if not isinstance(row, dict) or not str(row.get("bulletinId", "")).isdigit():
        return None
    try:
        published = datetime.fromisoformat(row["bulletinStarttime"]).replace(tzinfo=BEIJING)
    except KeyError, TypeError, ValueError:
        return None
    title = str(row.get("bulletinSubject") or "")
    body = BeautifulSoup(str(row.get("bulletinContent") or ""), "html.parser").get_text(" ")
    source = f"{JC_NOTICE_PAGE}#bulletin-{row['bulletinId']}"
    evidence = {"source_url": source, "raw": row}
    window = re.search(
        _DATE + r"(?:竞彩游戏|竞彩足球|竞彩足球).*?(?:停售时间为|停止销售时间为)\s*" + _CLOCK, body
    )
    if window:
        try:
            day = _date((window.group(1), window.group(2), window.group(3)), published)
            cutoff = datetime.fromisoformat(f"{day.isoformat()}T{window[4].zfill(5)}").replace(
                tzinfo=BEIJING
            )
        except ValueError:
            return None
        if abs(day - published.date()) <= timedelta(days=10):
            return published, {
                **evidence,
                "kind": "jc_sales_window",
                "business_date": day.isoformat(),
                "cutoff": cutoff.isoformat(),
            }
    code = re.search(r"(周[一二三四五六日])\s*(\d{3})", title)
    teams = re.search(r"[“\"]\s*([^“”\"]+?)\s+VS\s+([^“”\"]+?)\s*[”\"]", body, re.I)
    if not code or not teams:
        return None
    if "取消竞猜" in title or "比赛无效" in title:
        status = "withdrawn"
    elif "恢复销售" in title:
        status = "resumed"
    elif any(term in title for term in ("推迟", "提前", "中断", "暂停", "调整")):
        status = "changed"
    else:
        return None
    changed_to = re.search(
        r"(?:推迟至|提前至|调整为)\s*(?:北京时间)?\s*" + _DATE + r"\s*" + _CLOCK, body
    )
    kickoff = None
    if changed_to:
        try:
            day = _date((changed_to.group(1), changed_to.group(2), changed_to.group(3)), published)
            kickoff = datetime.fromisoformat(
                f"{day.isoformat()}T{changed_to[4].zfill(5)}"
            ).isoformat(timespec="seconds")
        except ValueError:
            pass
    return published, {
        **evidence,
        "kind": "jc_fixture_change",
        "match_code": "".join(code.groups()),
        "home": teams[1].strip(),
        "away": teams[2].strip(),
        "state": status,
        "kickoff": kickoff,
    }


def _store_notices(rows: list[tuple[datetime, dict]]) -> None:
    if not rows:
        return
    with get_db() as conn, conn.cursor() as cur:
        if any(
            evidence["kind"] in {"jc_fixture_change", "jc_sales_window", "pool_schedule"}
            for _, evidence in rows
        ):
            acquire_prematch_notice_write_lock(cur)
        if any(evidence["kind"] == "pool_schedule" for _, evidence in rows):
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (IDENTITY_LOCK,))
        for published, evidence in rows:
            digest = (
                evidence.get("source_body_sha256")
                or hashlib.sha256(
                    json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest()
            )
            cur.execute(
                """INSERT INTO sporttery_schedule_notices
                      (source_url, content_sha256, published_at, evidence, raw_body)
                   VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (
                    evidence["source_url"],
                    digest,
                    published,
                    Json({k: v for k, v in evidence.items() if k != "official_html"}),
                    evidence.get("official_html"),
                ),
            )
        conn.commit()


def refresh_jc_notices() -> int:
    client = SportteryClient(timeout=7, max_retries=1)
    try:
        rows = [
            notice for row in client.get_match_bulletins() if (notice := parse_jc_bulletin(row))
        ]
    finally:
        client.close()
    _store_notices(rows)
    return len(rows)


def _read_html(client: httpx.Client, url: str) -> bytes:
    with client.stream("GET", url) as response:
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > _MAX_BODY_BYTES:
                raise ValueError("Sporttery HTML exceeds the source size bound")
    return bytes(body)


def refresh_pool_notices() -> int:
    now = datetime.now(BEIJING)
    rows: list[tuple[datetime, dict]] = []
    with httpx.Client(timeout=7, headers={"User-Agent": "Mozilla/5.0"}) as client:
        soup = BeautifulSoup(_read_html(client, POOL_NOTICE_PAGE), "html.parser")
        urls = {}
        for node in soup.find_all("a", href=True):
            path = str(node["href"])
            match = _POOL_LINK.fullmatch(path)
            if not match or not any(
                term in node.get_text(strip=True)
                for term in ("竞猜场次安排", "竞猜场次的通知", "增设", "增开", "增补")
            ):
                continue
            day = datetime.strptime(match[1], "%Y%m%d").date()
            if now.date() - timedelta(days=14) <= day <= now.date():
                urls[f"https://www.sporttery.cn{path}"] = day
        with get_db() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT source_url FROM sporttery_schedule_notices
                           WHERE source_url=ANY(%s) AND observed_at>=clock_timestamp()-INTERVAL '6 hours'""",
                (list(urls),),
            )
            recent = {row[0] for row in cur.fetchall()}
        for url in [
            url for url in sorted(urls, key=urls.__getitem__, reverse=True) if url not in recent
        ][:8]:
            try:
                raw = _read_html(client, url)
                page = BeautifulSoup(raw, "html.parser")
                stamp = page.select_one(".m-r1")
                if not stamp:
                    continue
                published = datetime.fromisoformat(stamp.get_text(strip=True)).replace(
                    tzinfo=BEIJING
                )
                evidence = parse_notice(raw, source_url=url, retrieved_at=now)
            except (httpx.HTTPError, ValueError) as exc:
                logger.info("Traditional pool notice pending verification (%s): %s", url, exc)
                continue
            rows.append(
                (
                    published,
                    {
                        **evidence,
                        "kind": "pool_schedule",
                        "title": page.title.get_text(strip=True) if page.title else "",
                        "official_html": raw.decode("utf-8", errors="replace"),
                    },
                )
            )
    _store_notices(rows)
    return len(rows)
