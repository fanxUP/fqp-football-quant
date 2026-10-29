"""Command line interface for the titan007 scraper."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import analysis as analysis_parser
from . import assets as assets_mod
from . import backfill as backfill_mod
from . import classify as classify_mod
from . import companies as companies_mod
from . import derive as derive_mod
from . import leagues as leagues_parser
from . import lottery as lottery_mod
from . import monitor as monitor_mod
from . import odds as odds_parser
from . import parsers, store
from . import relations as relations_mod
from . import roster as roster_mod
from . import team_sync as team_sync_mod
from . import teams as teams_parser
from .client import AcquisitionStopped, TitanClient, record_operation_failure

BFDATA_URL = "https://live.titan007.com/vbsxml/bfdata_ut.js?r=007"
CHANGE_URL = "https://live.titan007.com/vbsxml/change2_ut.xml?r=007"
DETAIL_UT_URL = "https://live.titan007.com/vbsxml/detail_ut.js?r=007"
DETAIL_URL = "https://live.titan007.com/detail/{match_id}cn.htm"
ANALYSIS_HEADER_URL = (
    "https://livestatic.titan007.com/phone/txt/analysisheader/cn/3/00/{match_id}.txt"
)
HISTORY_URL = "https://bf.titan007.com/football/{kind}_{yyyymmdd}.htm"
ODDS_FEED_URL = "https://live.titan007.com/vbsxml/ch_goalbf3.xml?r=007"
X1X2D_URL = "https://1x2d.titan007.com/{match_id}.js"
VIP_CHANGE_URL = (
    "https://vip.titan007.com/changeDetail/{page}.aspx?id={match_id}&companyid={company_id}&l=0"
)
VIP_PAGES = {
    "1x2": "1x2",
    "handicap": "handicap",
    "overunder": "overunder",
    "1x2half": "1x2Half",
    "handicaphalf": "handicapHalf",
    "overunderhalf": "overunderHalf",
}
ZQ_ANALYSIS_URL = "https://zq.titan007.com/analysis/{match_id}cn.htm"
ZQ_ANALYZE_DATA_URL = "https://zq.titan007.com/default/getAnalyData?sid={match_id}&t=1"
PLAYER_TECH_URL = "https://live.titan007.com/PlayerTech.aspx?ID={match_id}&l=0"
TEXT_LIVE_URL = "https://live.titan007.com/textLive.aspx?id={match_id}&l=0"
TEAM_JS_URL = "https://info.titan007.com/jsData/teamInfo/teamDetail/tdl{team_id}.js"
SUBLEAGUE_URL = "https://zq.titan007.com/cn/subleague.aspx?sclassid={league_id}"
SEA_URL = "https://zq.titan007.com/jsData/LeagueSeason/sea{league_id}.js"
LEAGUE_JS_URL = "https://zq.titan007.com/jsData/matchResult/{season}/s{league_id}_{sub_id}.js"
LEAGUE_JS_URL_PLAIN = "https://zq.titan007.com/jsData/matchResult/{season}/s{league_id}.js"
CUP_JS_URL = "https://zq.titan007.com/jsData/matchResult/{season}/c{league_id}.js"
ARCHER_URL = "https://zq.titan007.com/cn/Archer/{season}/{league_id}.html"


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def analysis_header_url(match_id: int) -> str:
    return ANALYSIS_HEADER_URL.format(match_id=match_id)


def make_client(args, default_delay=1.5, default_jitter=0.5, default_pause_every=0):
    """按命令行参数构建客户端；未显式指定时用该命令的保守默认节奏。"""
    return TitanClient(
        delay=args.delay if args.delay is not None else default_delay,
        jitter=args.jitter if args.jitter is not None else default_jitter,
        pause_every=args.pause_every if args.pause_every is not None else default_pause_every,
        pause_min=args.pause_min,
        pause_max=args.pause_max,
    )


def cmd_init(args) -> int:
    conn = store.connect(args.db)
    print(f"数据库已初始化：{args.db}")
    print(store.counts(conn))
    return 0


def cmd_live(args) -> int:
    client = make_client(args)
    conn = store.connect(args.db)

    text = client.get(BFDATA_URL)
    data = parsers.parse_bfdata(text)
    n = store.upsert_matches(conn, data["matches"])
    store.upsert_leagues(conn, data["leagues"])
    store.log(conn, "live", BFDATA_URL, "ok", f"{n} matches")
    print(
        f"快照：{n} 场比赛，{len(data['leagues'])} 个联赛，日期 {data['meta'].get('matchdate', '')}"
    )

    last_snapshot = time.time()
    while args.loop:
        time.sleep(max(0.0, args.interval))
        try:
            change_text = client.get(CHANGE_URL)
            changes = parsers.parse_change_xml(change_text)
            updated = store.update_from_change(conn, changes)
            if changes:
                print(f"{datetime.now():%H:%M:%S} 增量 {len(changes)} 条，更新 {updated} 条")
            if args.refresh_snapshot and time.time() - last_snapshot >= args.refresh_snapshot:
                text = client.get(BFDATA_URL)
                data = parsers.parse_bfdata(text)
                store.upsert_matches(conn, data["matches"])
                store.upsert_leagues(conn, data["leagues"])
                last_snapshot = time.time()
                print(f"{datetime.now():%H:%M:%S} 已刷新全量快照")
        except KeyboardInterrupt:
            print("\n已停止")
            return 0
        except AcquisitionStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            record_operation_failure()
            print(f"增量失败：{exc}", file=sys.stderr)
            store.log(conn, "live-change", CHANGE_URL, "error", str(exc))
    return 0


def cmd_history(args) -> int:
    client = make_client(args)
    conn = store.connect(args.db)
    start, end = parse_date(args.start), parse_date(args.end)
    if start > end:
        print("--start 不能晚于 --end", file=sys.stderr)
        return 2

    kinds = ["Over", "Next"] if args.include_next else ["Over"]
    total = 0
    for d in daterange(start, end):
        for kind in kinds:
            url = HISTORY_URL.format(kind=kind, yyyymmdd=d.strftime("%Y%m%d"))
            try:
                html = client.get(url, referer="https://bf.titan007.com/")
                rows = parsers.parse_history_page(html, d)
                n = store.upsert_matches(conn, rows)
                total += n
                store.log(conn, f"history-{kind}", url, "ok", f"{n} matches")
                print(f"{d} {kind}: {n} 场")
            except AcquisitionStopped:
                raise
            except Exception as exc:  # noqa: BLE001
                record_operation_failure()
                store.log(conn, f"history-{kind}", url, "error", str(exc))
                print(f"{d} {kind}: 失败 {exc}", file=sys.stderr)
    print(f"完成，共写入/更新 {total} 场")
    return 0


def cmd_details(args) -> int:
    client = make_client(args)
    conn = store.connect(args.db)

    if args.match_id:
        ids = args.match_id
    elif args.date:
        ids = store.match_ids_for_date(
            conn, args.date, only_missing=args.only_missing, limit=args.limit
        )
    else:
        print("需要 --date 或 --match-id", file=sys.stderr)
        return 2

    if args.jc_only:
        linked = _jc_match_ids(conn)
        ids = [i for i in ids if i in linked]

    if not ids:
        print("没有需要处理的比赛")
        return 0

    scorers = {}
    if args.with_scorers:
        try:
            scorers = parsers.parse_detail_ut(client.get(DETAIL_UT_URL))
            print(f"已加载当日进球球员 {len(scorers)} 组")
        except AcquisitionStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            record_operation_failure()
            print(f"进球球员文件加载失败（跳过）：{exc}", file=sys.stderr)

    ok = 0
    for i, match_id in enumerate(ids, 1):
        url = DETAIL_URL.format(match_id=match_id)
        try:
            html = client.get(url)
            detail = parsers.parse_detail_page(html, match_id)
            if args.with_scorers:
                parsers.merge_scorers(detail, scorers, match_id)
            if args.with_header:
                try:
                    htxt = client.get(analysis_header_url(match_id), referer=url)
                    detail["header"].update(parsers.parse_analysis_header(htxt))
                except AcquisitionStopped:
                    raise
                except Exception:
                    record_operation_failure()
                    pass
            store.save_detail(conn, match_id, detail)
            header = detail.get("header") or {}
            if header.get("weather") or header.get("temperature") or header.get("venue"):
                store.upsert_matches(
                    conn,
                    [
                        {
                            "match_id": match_id,
                            "weather": header.get("weather"),
                            "temperature": header.get("temperature"),
                            "venue": header.get("venue"),
                        }
                    ],
                )
            ok += 1
            print(
                f"[{i}/{len(ids)}] {match_id}: "
                f"{len(detail['stats'])} 项统计, {len(detail['events'])} 个事件, {len(detail['lineups'])} 名球员"
            )
            store.log(conn, "detail", url, "ok", "")
        except AcquisitionStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            record_operation_failure()
            print(f"[{i}/{len(ids)}] {match_id}: 失败 {exc}", file=sys.stderr)
            store.log(conn, "detail", url, "error", str(exc))
    print(f"完成：成功 {ok}/{len(ids)}")
    return 0


def _jc_match_ids(conn) -> set:
    return {
        r[0]
        for r in conn.execute(
            "SELECT titan_match_id FROM lottery_matches WHERE titan_match_id IS NOT NULL"
        )
    }


def _select_match_ids(conn, args) -> list:
    if getattr(args, "match_id", None):
        ids = list(args.match_id)
    elif getattr(args, "date", None):
        ids = store.match_ids_for_date(conn, args.date, only_missing=False, limit=args.limit)
    else:
        ids = []
    if getattr(args, "jc_only", False):
        linked = _jc_match_ids(conn)
        ids = [i for i in ids if i in linked]
    return ids


def _num(value):
    try:
        s = str(value).strip()
        if s == "":
            return None
        return float(s)
    except TypeError, ValueError:
        return None


def _vip_initial_latest(rows):
    if not rows:
        return None, None
    latest = next(
        (
            r
            for r in rows
            if r.get("home") is not None
            or (r.get("line") not in (None, ""))
            or r.get("away") is not None
        ),
        rows[0],
    )
    initial = next((r for r in rows if "初" in str(r.get("status") or "")), None) or rows[-1]
    return initial, latest


def cmd_playertech(args) -> int:
    client = make_client(args)
    conn = store.connect(args.db)
    ids = _select_match_ids(conn, args)
    if not ids:
        print("需要 --date 或 --match-id", file=sys.stderr)
        return 2
    ok = 0
    for i, mid in enumerate(ids, 1):
        url = PLAYER_TECH_URL.format(match_id=mid)
        try:
            data = parsers.parse_player_tech(client.get(url, referer="https://live.titan007.com/"))
            n = store.save_player_stats(conn, mid, data)
            ok += 1
            print(f"[{i}/{len(ids)}] {mid}: {n} 名球员技术统计", flush=True)
            store.log(conn, "playertech", url, "ok", str(n))
        except AcquisitionStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            record_operation_failure()
            print(f"[{i}/{len(ids)}] {mid}: 失败 {exc}", file=sys.stderr, flush=True)
            store.log(conn, "playertech", url, "error", str(exc))
    print(f"完成：成功 {ok}/{len(ids)}")
    return 0


def cmd_jcodds(args) -> int:
    client = make_client(args)
    conn = store.connect(args.db)
    ids = _select_match_ids(conn, args)
    if not ids:
        print("需要 --date 或 --match-id", file=sys.stderr)
        return 2
    ok = 0
    for i, mid in enumerate(ids, 1):
        url = ZQ_ANALYZE_DATA_URL.format(match_id=mid)
        try:
            payload = json.loads(
                client.get(url, referer=f"https://zq.titan007.com/analysis/{mid}cn.htm")
            )
            rows = parsers.parse_jc_odds(payload)
            n = store.save_jc_odds(conn, mid, rows)
            ok += 1
            print(f"[{i}/{len(ids)}] {mid}: {n} 条竞彩赔率", flush=True)
            store.log(conn, "jcodds", url, "ok", str(n))
        except AcquisitionStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            record_operation_failure()
            print(f"[{i}/{len(ids)}] {mid}: 失败 {exc}", file=sys.stderr, flush=True)
            store.log(conn, "jcodds", url, "error", str(exc))
    print(f"完成：成功 {ok}/{len(ids)}")
    return 0


def cmd_textlive(args) -> int:
    client = make_client(args)
    conn = store.connect(args.db)
    ids = _select_match_ids(conn, args)
    if not ids:
        print("需要 --date 或 --match-id", file=sys.stderr)
        return 2
    ok = 0
    empty = 0
    for i, mid in enumerate(ids, 1):
        url = TEXT_LIVE_URL.format(match_id=mid)
        try:
            data = parsers.parse_text_live(
                client.get(url, referer="https://live.titan007.com/", encoding="gb18030")
            )
            store.save_text_live(conn, mid, data)
            if "暂无直播内容" in (data.get("content") or ""):
                empty += 1
            else:
                ok += 1
            print(
                f"[{i}/{len(ids)}] {mid}: {'有' if '暂无直播内容' not in (data.get('content') or '') else '无'}直播内容",
                flush=True,
            )
            store.log(conn, "textlive", url, "ok", "")
        except AcquisitionStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            record_operation_failure()
            print(f"[{i}/{len(ids)}] {mid}: 失败 {exc}", file=sys.stderr, flush=True)
            store.log(conn, "textlive", url, "error", str(exc))
    print(f"完成：有内容 {ok}，无内容 {empty}，共 {len(ids)}")
    return 0


def cmd_odds(args) -> int:
    client = make_client(args)
    conn = store.connect(args.db)

    if args.feed:
        xml = client.get(ODDS_FEED_URL)
        feed = odds_parser.parse_goal_feed(xml)
        rows = []
        for f in feed:
            mid = f["match_id"]
            rows.append(
                {
                    "match_id": mid,
                    "company_id": f["company_id"],
                    "company_name": f["company_name"],
                    "odds_type": "asian",
                    "source": "feed",
                    "live_home": f["asian_home"],
                    "live_line": f["asian_line"],
                    "live_away": f["asian_away"],
                    "updated_at": _now_iso(),
                }
            )
            rows.append(
                {
                    "match_id": mid,
                    "company_id": f["company_id"],
                    "company_name": f["company_name"],
                    "odds_type": "europe",
                    "source": "feed",
                    "live_home": f["euro_home"],
                    "live_line": f["euro_draw"],
                    "live_away": f["euro_away"],
                    "updated_at": _now_iso(),
                }
            )
            rows.append(
                {
                    "match_id": mid,
                    "company_id": f["company_id"],
                    "company_name": f["company_name"],
                    "odds_type": "overunder",
                    "source": "feed",
                    "live_home": f["ou_over"],
                    "live_line": f["ou_line"],
                    "live_away": f["ou_under"],
                    "updated_at": _now_iso(),
                }
            )
            if f["half_asian_line"] is not None:
                rows.append(
                    {
                        "match_id": mid,
                        "company_id": f["company_id"],
                        "company_name": f["company_name"],
                        "odds_type": "asian_half",
                        "source": "feed",
                        "live_line": f["half_asian_line"],
                        "updated_at": _now_iso(),
                    }
                )
            if f["half_ou_line"] is not None:
                rows.append(
                    {
                        "match_id": mid,
                        "company_id": f["company_id"],
                        "company_name": f["company_name"],
                        "odds_type": "overunder_half",
                        "source": "feed",
                        "live_line": f["half_ou_line"],
                        "updated_at": _now_iso(),
                    }
                )
        n = store.save_odds(conn, rows)
        print(f"赔率快照（ch_goalbf3）：{len(feed)} 场，写入 {n} 条")
        store.log(conn, "odds-feed", ODDS_FEED_URL, "ok", str(n))

    ids = _select_match_ids(conn, args)
    if not ids:
        return 0

    companies = [int(x) for x in args.companies.split(",") if x.strip()]
    types = [x.strip().lower() for x in args.types.split(",") if x.strip()]
    mainstream = None
    if not getattr(args, "all_companies", False):
        mainstream = {
            r[0]
            for r in conn.execute(
                "SELECT company_id FROM odds_companies "
                "WHERE tier IN ('tier1','tier2','china_lottery')"
            )
        } or None

    def keep(company_id):
        return mainstream is None or company_id in mainstream

    ok = 0
    for i, mid in enumerate(ids, 1):
        name_map = {}
        try:
            if not args.no_1x2d:
                text = client.get(
                    X1X2D_URL.format(match_id=mid),
                    referer=f"https://1x2.titan007.com/oddslist/{mid}.htm",
                )
                data = odds_parser.parse_1x2d(text)
                rows = []
                for c in data["companies"]:
                    if not keep(c["company_id"]):
                        continue
                    name_map[c["company_id"]] = c.get("company_name_cn") or c.get("company_name")
                    rows.append(
                        {
                            **c,
                            "match_id": mid,
                            "company_name": c.get("company_name_cn") or c.get("company_name"),
                            "odds_type": "europe",
                            "source": "1x2d",
                            "initial_line": c.get("initial_draw"),
                            "live_line": c.get("live_draw"),
                            "updated_at": c.get("change_time"),
                        }
                    )
                store.save_odds(conn, rows)
                by_company: dict[int, list[dict[str, Any]]] = {}
                for h in data["history"]:
                    company_id = int(h["company_id"])
                    if not keep(company_id):
                        continue
                    by_company.setdefault(company_id, []).append(h)
                for cid, hist in by_company.items():
                    store.save_odds_history(conn, mid, cid, "europe", "1x2d", hist)
                print(
                    f"[{i}/{len(ids)}] {mid}: 1x2d {len(rows)} 家公司, {len(data['history'])} 条变化"
                )

            if args.vip:
                for cid in companies:
                    for typ in types:
                        page = VIP_PAGES.get(typ)
                        if not page:
                            continue
                        url = VIP_CHANGE_URL.format(page=page, match_id=mid, company_id=cid)
                        html = client.get(url, referer="https://vip.titan007.com/")
                        rows = odds_parser.parse_vip_change(html)
                        if not rows:
                            continue
                        odds_type = {
                            "1x2": "europe",
                            "handicap": "asian",
                            "overunder": "overunder",
                            "1x2half": "europe_half",
                            "handicaphalf": "asian_half",
                            "overunderhalf": "overunder_half",
                        }[typ]
                        initial, latest = _vip_initial_latest(rows)
                        store.save_odds(
                            conn,
                            [
                                {
                                    "match_id": mid,
                                    "company_id": cid,
                                    "company_name": name_map.get(cid),
                                    "odds_type": odds_type,
                                    "source": "vip",
                                    "initial_home": initial.get("home"),
                                    "initial_line": _num(initial.get("line")),
                                    "initial_away": initial.get("away"),
                                    "live_home": latest.get("home"),
                                    "live_line": _num(latest.get("line")),
                                    "live_away": latest.get("away"),
                                    "updated_at": latest.get("change_time"),
                                }
                            ],
                        )
                        store.save_odds_history(conn, mid, cid, odds_type, "vip", rows)
                        print(f"[{i}/{len(ids)}] {mid}: vip {cid} {typ} {len(rows)} 条")
            ok += 1
            store.log(conn, "odds", str(mid), "ok", "")
        except AcquisitionStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            record_operation_failure()
            print(f"[{i}/{len(ids)}] {mid}: 失败 {exc}", file=sys.stderr)
            store.log(conn, "odds", str(mid), "error", str(exc))
    print(f"完成：成功 {ok}/{len(ids)}")
    return 0


def cmd_analysis(args) -> int:
    client = make_client(args)
    conn = store.connect(args.db)
    ids = _select_match_ids(conn, args)
    if not ids:
        print("需要 --date 或 --match-id", file=sys.stderr)
        return 2

    ok = 0
    for i, mid in enumerate(ids, 1):
        url = ZQ_ANALYSIS_URL.format(match_id=mid)
        try:
            html = client.get(url, referer="https://live.titan007.com/")
            data = analysis_parser.parse_zq_analysis(html)
            meta = data.get("meta") or {}
            kickoff = None
            if meta.get("match_date") and meta.get("kickoff_time"):
                kickoff = f"{meta['match_date']} {meta['kickoff_time']}"
            store.upsert_matches(
                conn,
                [
                    {
                        "match_id": mid,
                        "match_date": meta.get("match_date"),
                        "kickoff": kickoff,
                        "home_id": meta.get("home_id"),
                        "away_id": meta.get("away_id"),
                        "home_name": meta.get("home_name"),
                        "away_name": meta.get("away_name"),
                        "venue": meta.get("venue"),
                        "weather": meta.get("weather"),
                        "temperature": meta.get("temperature"),
                    }
                ],
            )
            for key, value in data.items():
                if key == "sections":
                    for title, text in value.items():
                        store.save_analysis(conn, mid, {f"text:{title}": text})
                else:
                    store.save_analysis(conn, mid, {key: value})
            if args.with_json:
                raw = client.get(ZQ_ANALYZE_DATA_URL.format(match_id=mid), referer=url)
                try:
                    store.save_analysis(conn, mid, {"analy_data": json.loads(raw)})
                except json.JSONDecodeError:
                    store.save_analysis(conn, mid, {"analy_data_raw": raw})
            ok += 1
            print(
                f"[{i}/{len(ids)}] {mid}: h2h {len(data.get('h2h') or [])}, "
                f"form {len(data.get('form_home') or [])}/{len(data.get('form_away') or [])}, "
                f"standings {len(data.get('standings') or [])}, injuries {len(data.get('injuries') or [])}"
            )
            store.log(conn, "analysis", url, "ok", "")
        except AcquisitionStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            record_operation_failure()
            print(f"[{i}/{len(ids)}] {mid}: 失败 {exc}", file=sys.stderr)
            store.log(conn, "analysis", url, "error", str(exc))
    print(f"完成：成功 {ok}/{len(ids)}")
    return 0


def cmd_team(args) -> int:
    client = make_client(args)
    conn = store.connect(args.db)
    ok = 0
    for i, team_id in enumerate(args.team_id, 1):
        url = TEAM_JS_URL.format(team_id=team_id)
        try:
            text = client.get(url, referer="https://info.titan007.com/")
            data = teams_parser.normalize_team(teams_parser.parse_team_js(text))
            store.save_team(conn, data)
            ok += 1
            print(
                f"[{i}/{len(args.team_id)}] {team_id}: {data['profile'].get('name')}，"
                f"阵容 {len(data['squad'])} 人，荣誉 {len(data['honors'])} 项"
            )
            store.log(conn, "team", url, "ok", "")
        except AcquisitionStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            record_operation_failure()
            print(f"[{i}/{len(args.team_id)}] {team_id}: 失败 {exc}", file=sys.stderr)
            store.log(conn, "team", url, "error", str(exc))
    print(f"完成：成功 {ok}/{len(args.team_id)}")
    return 0


def _sync_league(
    client, conn, league_id: int, season: str | None = None, *, include_scorers: bool = True
) -> dict:
    """同步单个赛事的当前赛季（联赛 s{id}.js / 杯赛 c{id}.js）。"""
    sub_html = client.get(
        SUBLEAGUE_URL.format(league_id=league_id), referer="https://zq.titan007.com/"
    )
    sub_id = leagues_parser.parse_sub_league_id(sub_html)
    is_cup = not sub_id and bool(re.search(rf"/c{league_id}\.js", sub_html))

    if not season:
        season = leagues_parser.parse_season_from_title(sub_html)
    if not season:
        sea = client.get(SEA_URL.format(league_id=league_id), referer="https://zq.titan007.com/")
        seasons = leagues_parser.parse_sea_js(sea)
        if not seasons:
            raise RuntimeError("未找到可用赛季")
        season = seasons[0]

    if is_cup:
        url = CUP_JS_URL.format(season=season, league_id=league_id)
        data = leagues_parser.parse_cup_js(client.get(url, referer="https://zq.titan007.com/"))
        if not data["groups"] and not data["standings"]:
            raise RuntimeError("杯赛 JS 无数据")
        data["league"] = leagues_parser.cup_league_info(data)
        results = leagues_parser.normalize_cup_results(data, season, league_id)
        standings = leagues_parser.normalize_cup_standings(data)
    else:
        if sub_id:
            url = LEAGUE_JS_URL.format(season=season, league_id=league_id, sub_id=sub_id)
        else:
            url = LEAGUE_JS_URL_PLAIN.format(season=season, league_id=league_id)
        data = leagues_parser.parse_league_js(client.get(url, referer="https://zq.titan007.com/"))
        if not data["rounds"] and not any(data["standings"].values()):
            raise RuntimeError("联赛 JS 无数据（链接可能已失效）")
        results = leagues_parser.normalize_results(data, season)
        standings = leagues_parser.normalize_standings(data)

    scorers: dict[str, list[dict[str, Any]]] = {}
    if include_scorers:
        try:
            archer_url = ARCHER_URL.format(season=season, league_id=league_id)
            archer = client.get(archer_url, referer="https://zq.titan007.com/")
            scorers = leagues_parser.parse_scorers(archer)
            if not scorers.get("total"):
                tech_url = leagues_parser.find_player_tech_url(archer)
                if tech_url:
                    if tech_url.startswith("//"):
                        tech_url = "https:" + tech_url
                    elif tech_url.startswith("/"):
                        tech_url = "https://zq.titan007.com" + tech_url
                    tech_text = client.get(tech_url, referer=archer_url)
                    scorers = {"total": leagues_parser.parse_player_tech_scorers(tech_text)}
        except AcquisitionStopped:
            raise
        except Exception:  # noqa: BLE001
            record_operation_failure()

    store.save_league(conn, league_id, season, data, results, standings, scorers)
    return {
        "season": season,
        "type": "cup" if is_cup else "league",
        "results": len(results),
        "standings": len(standings),
        "scorers": sum(len(v) for v in scorers.values()),
        "url": url,
    }


def cmd_league(args) -> int:
    client = make_client(args)
    conn = store.connect(args.db)
    try:
        s = _sync_league(client, conn, args.league_id, args.season)
        print(
            f"联赛 {args.league_id} {s['season']}（{s['type']}）：{s['results']} 场赛果，"
            f"{s['standings']} 行积分榜，{s['scorers']} 名射手"
        )
        store.log(conn, "league", s["url"], "ok", "")
    except AcquisitionStopped:
        raise
    except Exception as exc:  # noqa: BLE001
        record_operation_failure()
        print(f"联赛 {args.league_id}: 失败 {exc}", file=sys.stderr)
        store.log(conn, "league", str(args.league_id), "error", str(exc))
        return 1
    return 0


def cmd_lottery_odds(args) -> int:
    conn = store.connect(args.db)
    n = lottery_mod.sync_lottery_odds(conn)
    print(f"已写入竞彩赔率 {n} 场（company_id=0 中国体彩）")
    return 0


def cmd_roster_sync(args) -> int:
    conn = store.connect(args.db)
    client = make_client(args, default_delay=2.0, default_jitter=2.0, default_pause_every=20)
    top = [
        r[0]
        for r in conn.execute(
            "SELECT titan_team_id FROM team_catalog ORDER BY jc_matches DESC, squad_players DESC LIMIT ?",
            (args.top_teams,),
        )
    ]
    do_coaches = args.coaches or not args.transfers
    do_transfers = args.transfers or not args.coaches
    if do_coaches:
        print(f"教练：{len(top)} 支球队", flush=True)
        print(roster_mod.sync_coaches(conn, client, top))
    if do_transfers:
        marks = ",".join("?" * len(top))
        ids = [
            r[0]
            for r in conn.execute(
                f"""SELECT DISTINCT s.player_id FROM team_squad s
                WHERE s.team_id IN ({marks})
                  AND NOT EXISTS(SELECT 1 FROM player_transfer_checked c WHERE c.player_id=s.player_id)
                ORDER BY s.team_id, s.player_id""",
                top,
            )
        ]
        if args.limit:
            ids = ids[: args.limit]
        print(f"转会：{len(ids)} 名球员", flush=True)
        print(roster_mod.sync_transfers(conn, client, ids))
    return 0


def cmd_derive(args) -> int:
    conn = store.connect(args.db)
    stats = derive_mod.derive_all(conn)
    print(f"派生完成：{stats}")
    return 0


def cmd_backfill_teams(args) -> int:
    conn = store.connect(args.db)
    stats = backfill_mod.backfill_team_ids(conn, dry_run=args.dry_run, fuzzy=args.fuzzy)
    print(f"队名回填{'（预演）' if args.dry_run else ''}：{stats}")
    return 0


def cmd_backfill_seasons(args) -> int:
    conn = store.connect(args.db)
    targets = backfill_mod.missing_league_seasons(conn)
    if args.limit:
        targets = targets[: args.limit]
    by_league: dict[int, list[int]] = {}
    for lid, year, _n in targets:
        by_league.setdefault(lid, []).append(year)
    print(f"待补齐 {len(targets)} 个「赛事×年份」，涉及 {len(by_league)} 个赛事", flush=True)
    if args.dry_run:
        for lid, years in list(by_league.items())[:40]:
            print(f"  {lid}: {sorted(years)}")
        return 0

    client = make_client(args, default_delay=3.0, default_jitter=3.0, default_pause_every=12)
    dates_by_league: dict[int, list[str]] = {}
    for lid, day in conn.execute(
        """SELECT league_id, match_date FROM matches
           WHERE home_id IS NULL OR away_id IS NULL"""
    ):
        dates_by_league.setdefault(lid, []).append(day)
    done = failed = 0
    for lid, years in by_league.items():
        try:
            seasons = leagues_parser.parse_sea_js(
                client.get(SEA_URL.format(league_id=lid), referer="https://zq.titan007.com/")
            )
        except AcquisitionStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            record_operation_failure()
            failed += 1
            print(f"赛事 {lid} 赛季列表失败：{exc}", file=sys.stderr, flush=True)
            continue
        wanted = backfill_mod.seasons_for_dates(seasons, dates_by_league.get(lid, []))
        if not wanted:
            failed += 1
            print(f"赛事 {lid}: 站方没有 {sorted(years)} 的赛季", file=sys.stderr, flush=True)
            continue
        for season in wanted:
            try:
                s = _sync_league(client, conn, lid, season)
            except AcquisitionStopped:
                raise
            except Exception as exc:  # noqa: BLE001
                record_operation_failure()
                failed += 1
                store.log(conn, "league", f"{lid}:{season}", "error", str(exc))
                print(f"  赛事 {lid} {season} 失败：{exc}", file=sys.stderr, flush=True)
                continue
            done += 1
            store.log(conn, "league", f"{lid}:{season}", "ok", f"{s['results']} 场")
            print(f"  赛事 {lid} {season}：{s['results']} 场赛果", flush=True)
    print(f"完成：成功 {done} 个赛季，失败 {failed}")
    return 0


def cmd_team_sync(args) -> int:
    conn = store.connect(args.db)
    if args.logos or args.squads:
        client = make_client(args, default_delay=3.0, default_jitter=3.0, default_pause_every=15)
        if args.logos:
            stats = team_sync_mod.download_missing_logos(
                conn,
                client,
                limit=args.limit,
                out_dir=str(Path(args.db).parent / "images" / "teams"),
            )
            print(f"队徽补抓：{stats}")
        if args.squads:
            stats = team_sync_mod.fetch_squads(conn, client, limit=args.limit)
            print(f"阵容补抓：{stats}")
    catalog = team_sync_mod.build_catalog(conn)
    print(f"球队目录：{catalog}")
    return 0


def cmd_league_relations(args) -> int:
    conn = store.connect(args.db)
    if args.fetch:
        client = make_client(args, default_delay=3.0, default_jitter=3.0, default_pause_every=15)
        stats = relations_mod.fetch_previous_standings(conn, client, limit=args.limit)
        print(f"上一季积分榜：{stats}")
    n = relations_mod.build_seasons(conn)
    moves = relations_mod.build_movements(conn)
    rels = relations_mod.build_relations(conn)
    print(f"球队-赛季 {n} 行；流动 {moves}；联赛关系 {rels} 条")
    if rels:
        rows = conn.execute(
            """SELECT lr.*, a.name_simplified from_name, b.name_simplified to_name
               FROM league_relations lr
               LEFT JOIN leagues a ON a.league_id=lr.from_league_id
               LEFT JOIN leagues b ON b.league_id=lr.to_league_id
               ORDER BY lr.team_count DESC LIMIT 15"""
        ).fetchall()
        for r in rows:
            print(f"  {r['from_name']} → {r['to_name']} [{r['direction']}] {r['team_count']} 队")
    return 0


def cmd_lottery(args) -> int:
    client = make_client(args, default_delay=2.0, default_jitter=2.0, default_pause_every=20)
    conn = store.connect(args.db)
    stats = lottery_mod.sync_lottery(conn, client, args.start, args.end)
    print(f"竞彩数据 {args.start} ~ {args.end}：{stats}")
    return 0


def cmd_team_link(args) -> int:
    conn = store.connect(args.db)
    if args.import_file:
        n = lottery_mod.import_aliases(conn, args.import_file)
        print(f"已导入人工别名 {n} 条")
    team_stats = lottery_mod.map_teams(conn)
    link_stats = lottery_mod.link_matches(conn, args.start, args.end)
    review = lottery_mod.write_review(conn, args.review_out)
    print(f"球队映射：{team_stats}")
    print(f"比赛关联：{link_stats}")
    print(f"待人工确认：{review} 条 → {args.review_out}")
    return 0


def cmd_companies(args) -> int:
    conn = store.connect(args.db)
    counts = companies_mod.sync_companies(conn)
    print("已同步博彩公司分级：", counts)
    for tier, label in (
        ("tier1", "第一梯队"),
        ("tier2", "第二梯队"),
        ("china_lottery", "中国体彩"),
    ):
        rows = conn.execute(
            "SELECT company_id,name,tier,category,region,note FROM odds_companies "
            "WHERE tier=? ORDER BY company_id",
            (tier,),
        ).fetchall()
        print(f"\n{label}（{len(rows)}）")
        for r in rows:
            print(f"  {r['company_id']:>4}  {r['name']}  [{r['category']}/{r['region']}]")
    return 0


def cmd_league_classify(args) -> int:
    conn = store.connect(args.db)
    out = args.out
    if args.import_only:
        n = classify_mod.import_json(conn, out)
        print(f"已从 {out} 导入 {n} 条赛事分类")
        return 0
    entries = classify_mod.build(conn)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    classify_mod.write_json(out, entries)
    n = classify_mod.import_json(conn, out)
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["priority"]] = counts.get(e["priority"], 0) + 1
    unknown = sum(1 for e in entries if e["region"] == "未知")
    print(f"已生成 {out} 并导入 {n} 条；优先级 {counts}；地区未知 {unknown} 条")
    return 0


def cmd_league_sync(args) -> int:
    # 批量抓取对站点压力最大，默认放慢并加入随机停顿
    client = make_client(args, default_delay=4.0, default_jitter=4.0, default_pause_every=12)
    conn = store.connect(args.db)

    if args.league_id:
        ids = list(dict.fromkeys(args.league_id))
    elif args.all:
        ids = [
            r["league_id"] for r in conn.execute("SELECT league_id FROM leagues ORDER BY league_id")
        ]
    else:
        feed = parsers.parse_bfdata(client.get(BFDATA_URL))
        ids = sorted({m["league_id"] for m in feed["matches"] if m.get("league_id")})

    if args.skip_done:
        done = {
            int(r["target"])
            for r in conn.execute(
                "SELECT target FROM ingest_log WHERE task='league-sync' AND status='ok'"
                " AND date(created_at)=date('now')"
            )
            if str(r["target"]).isdigit()
        }
        ids = [i for i in ids if i not in done]

    random.shuffle(ids)
    if args.limit:
        ids = ids[: args.limit]
    if not ids:
        print("没有可同步的赛事")
        return 0

    ok = 0
    skipped = []
    for i, league_id in enumerate(ids, 1):
        try:
            s = _sync_league(client, conn, league_id, args.season)
            ok += 1
            print(
                f"[{i}/{len(ids)}] {league_id} {s['season']} {s['type']}: "
                f"{s['results']} 场 / {s['standings']} 积分榜 / {s['scorers']} 射手",
                flush=True,
            )
            store.log(conn, "league-sync", str(league_id), "ok", s["url"])
        except AcquisitionStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            record_operation_failure()
            skipped.append(league_id)
            print(f"[{i}/{len(ids)}] {league_id}: 跳过 {exc}", file=sys.stderr, flush=True)
            store.log(conn, "league-sync", str(league_id), "error", str(exc))
    print(f"完成：成功 {ok}/{len(ids)}，跳过 {len(skipped)}")
    if skipped:
        print("跳过赛事：", ",".join(str(x) for x in skipped))
    return 0


def _fetch_league_teams(client, league_id: int, season: str) -> dict:
    """从联赛/杯赛 JS 的 arrTeam 提取 {team_id: (名称, logo)}。"""
    sub_html = client.get(
        SUBLEAGUE_URL.format(league_id=league_id), referer="https://zq.titan007.com/"
    )
    sub_id = leagues_parser.parse_sub_league_id(sub_html)
    is_cup = not sub_id and bool(re.search(rf"/c{league_id}\.js", sub_html))
    if is_cup:
        url = CUP_JS_URL.format(season=season, league_id=league_id)
        data = leagues_parser.parse_cup_js(client.get(url, referer="https://zq.titan007.com/"))
    else:
        url = (
            LEAGUE_JS_URL.format(season=season, league_id=league_id, sub_id=sub_id)
            if sub_id
            else LEAGUE_JS_URL_PLAIN.format(season=season, league_id=league_id)
        )
        data = leagues_parser.parse_league_js(client.get(url, referer="https://zq.titan007.com/"))
    return assets_mod.extract_team_logos(data.get("teams") or [])


def _save_asset(conn, asset_type, entity_id, name, url, path, size, status):
    store.upsert_assets(
        conn,
        [
            {
                "asset_type": asset_type,
                "entity_id": entity_id,
                "name": name,
                "url": url,
                "path": path,
                "bytes": size,
                "status": status,
                "fetched_at": _now_iso() if status == "ok" else None,
            }
        ],
    )


def _download_all(client, conn, asset_type, items, out_dir, limit=None):
    """items: [(entity_id, name, url)]"""
    subdir = {"team_logo": "teams", "player_photo": "players"}.get(asset_type, asset_type)
    if limit:
        items = items[:limit]
    ok = fail = 0
    for i, (entity_id, name, url) in enumerate(items, 1):
        try:
            path, size, existed = assets_mod.download_image(
                client, url, os.path.join(out_dir, subdir), entity_id
            )
            _save_asset(conn, asset_type, entity_id, name, url, path, size, "ok")
            ok += 1
            print(
                f"[{i}/{len(items)}] {asset_type} {entity_id} {name or ''}: "
                f"{size} 字节{'（已存在）' if existed else ''}",
                flush=True,
            )
        except AcquisitionStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            record_operation_failure()
            fail += 1
            _save_asset(conn, asset_type, entity_id, name, url, None, None, "error")
            print(
                f"[{i}/{len(items)}] {asset_type} {entity_id}: 失败 {exc}",
                file=sys.stderr,
                flush=True,
            )
    return ok, fail


def cmd_assets(args) -> int:
    client = make_client(args, default_delay=3.0, default_jitter=3.0, default_pause_every=15)
    conn = store.connect(args.db)
    out_dir = args.out_dir

    if "team" in args.type:
        if args.scope == "today":
            feed = parsers.parse_bfdata(client.get(BFDATA_URL))
            scope_ids = {
                mid for m in feed["matches"] for mid in (m.get("home_id"), m.get("away_id")) if mid
            }
            print(f"范围：今日比分页 {len(scope_ids)} 支球队")
        elif args.scope == "matches":
            scope_ids = {
                r[0]
                for r in conn.execute(
                    "SELECT home_id FROM matches UNION SELECT away_id FROM matches"
                )
                if r[0]
            }
            print(f"范围：matches 表 {len(scope_ids)} 支球队")
        else:
            scope_ids = None

        known = {}
        for r in conn.execute(
            "SELECT team_id,name,logo FROM team_profiles WHERE logo IS NOT NULL AND logo<>''"
        ):
            known[int(r["team_id"])] = (r["name"], r["logo"])
        if not args.no_league_scan:
            leagues = conn.execute(
                "SELECT league_id,season FROM league_info ORDER BY league_id"
            ).fetchall()
            for i, r in enumerate(leagues, 1):
                try:
                    found = _fetch_league_teams(client, r["league_id"], r["season"])
                    known.update(found)
                    print(
                        f"[联赛 {i}/{len(leagues)}] {r['league_id']} {r['season']}: "
                        f"{len(found)} 支球队",
                        flush=True,
                    )
                except AcquisitionStopped:
                    raise
                except Exception as exc:  # noqa: BLE001
                    record_operation_failure()
                    print(
                        f"[联赛 {i}/{len(leagues)}] {r['league_id']}: 跳过 {exc}",
                        file=sys.stderr,
                        flush=True,
                    )

        targets = set(known) if scope_ids is None else (set(known) & scope_ids)
        if args.fill_missing and scope_ids is not None:
            missing = sorted(scope_ids - set(known))
            if args.limit:
                missing = missing[: args.limit]
            print(f"补抓队徽：{len(missing)} 支球队")
            for i, team_id in enumerate(missing, 1):
                try:
                    text = client.get(
                        TEAM_JS_URL.format(team_id=team_id), referer="https://info.titan007.com/"
                    )
                    data = teams_parser.normalize_team(teams_parser.parse_team_js(text))
                    profile = data.get("profile") or {}
                    if profile.get("logo"):
                        known[team_id] = (profile.get("name"), profile["logo"])
                        targets.add(team_id)
                    print(
                        f"[补 {i}/{len(missing)}] {team_id} {profile.get('name') or ''}", flush=True
                    )
                except AcquisitionStopped:
                    raise
                except Exception as exc:  # noqa: BLE001
                    record_operation_failure()
                    print(
                        f"[补 {i}/{len(missing)}] {team_id}: 跳过 {exc}",
                        file=sys.stderr,
                        flush=True,
                    )

        items = [
            (tid, known[tid][0], assets_mod.team_logo_url(known[tid][1]))
            for tid in sorted(targets)
            if assets_mod.team_logo_url(known[tid][1])
        ]
        ok, fail = _download_all(client, conn, "team_logo", items, out_dir, args.limit)
        print(f"队徽：成功 {ok}，失败 {fail}")

    if "player" in args.type:
        # 球员详情页和头像目录用的是「比赛阵容」那套ID；阵容表(tdl)的ID是另一套编号，
        # 拿它去拼 player 页面只会拿到空页，所以只处理目录里的 lineups 球员。
        have = {
            int(r[0])
            for r in conn.execute(
                "SELECT entity_id FROM assets WHERE asset_type='player_photo' AND status='ok'"
            )
        }
        player_targets = {
            int(r["player_id"]): (r["name"], r["team_id"])
            for r in conn.execute(
                """SELECT player_id, name, team_id FROM player_directory
                   WHERE source='lineup' AND player_id < ?
                   ORDER BY COALESCE(appearances,0) DESC""",
                (derive_mod.SQUAD_ID_OFFSET,),
            )
        }
        missing_players = {pid: value for pid, value in player_targets.items() if pid not in have}
        known_player_photos: dict[int, tuple[Any, str]] = {}
        player_ids = list(missing_players)
        for start in range(0, len(player_ids), 400):
            chunk = player_ids[start : start + 400]
            marks = ",".join("?" * len(chunk))
            for pid, raw in conn.execute(
                f"SELECT player_id, raw FROM lineups WHERE player_id IN ({marks})", chunk
            ):
                url = assets_mod.extract_player_photo(raw or "", int(pid))
                if url and int(pid) not in known_player_photos:
                    known_player_photos[int(pid)] = (missing_players[int(pid)][0], url)
        print(
            f"阵容页解析出头像 {len(known_player_photos)} 个（待补 {len(missing_players)} 人）",
            flush=True,
        )

        if args.fill_missing:
            todo = [pid for pid in missing_players if pid not in known_player_photos]
            if args.limit:
                todo = todo[: args.limit]
            print(f"补抓头像：{len(todo)} 名球员", flush=True)
            for i, pid in enumerate(todo, 1):
                name, tid = missing[pid]
                url = f"https://info.titan007.com/cn/team/player/{tid or 0}/{pid}.html"
                try:
                    html = client.get(url, referer="https://info.titan007.com/")
                    photo = assets_mod.extract_player_photo(html, pid)
                except AcquisitionStopped:
                    raise
                except Exception as exc:  # noqa: BLE001
                    record_operation_failure()
                    print(f"[补 {i}/{len(todo)}] {pid}: 跳过 {exc}", file=sys.stderr, flush=True)
                    continue
                if photo:
                    known[pid] = (name, photo)
                if i % 25 == 0 or not photo:
                    print(
                        f"[补 {i}/{len(todo)}] {pid} {name or ''}: {'有' if photo else '无'}",
                        flush=True,
                    )

        items = [(pid, name, url) for pid, (name, url) in known.items()]
        ok, fail = _download_all(client, conn, "player_photo", items, out_dir, args.limit)
        print(f"头像：成功 {ok}，失败 {fail}")
    return 0


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def cmd_watch(args) -> int:
    client = make_client(args)
    conn = store.connect(args.db)
    ids = _select_match_ids(conn, args)
    companies = [int(x) for x in args.companies.split(",") if x.strip()]
    types = [x.strip().lower() for x in args.types.split(",") if x.strip()]
    mainstream = None
    if not getattr(args, "all_companies", False):
        mainstream = {
            r[0]
            for r in conn.execute(
                "SELECT company_id FROM odds_companies "
                "WHERE tier IN ('tier1','tier2','china_lottery')"
            )
        } or None

    def keep(company_id):
        return mainstream is None or company_id in mainstream

    return monitor_mod.run(
        conn,
        client,
        mode=args.mode,
        interval=args.interval,
        once=args.once,
        match_ids=ids,
        companies=companies,
        types=types,
        min_delta=args.min_delta,
        quiet=args.quiet,
    )


def cmd_alerts(args) -> int:
    conn = store.connect(args.db)
    rows = store.recent_alerts(conn, limit=args.limit, since=args.since)
    if not rows:
        print("没有异动记录")
        return 0
    for a in reversed(rows):
        label = monitor_mod.TYPE_LABELS.get(a["odds_type"], a["odds_type"])
        field = monitor_mod.field_label(a["odds_type"], a["field"])
        company = monitor_mod.company_label(a["company_id"], a.get("company_name"))
        teams = f"{a.get('home_name') or ''} vs {a.get('away_name') or ''}".strip()
        prefix = f"{a.get('league_name') or ''} {teams}".strip()
        if not teams:
            prefix = f"比赛 {a['match_id']}"
        print(
            f"{a['detected_at']} | {prefix} | {company} "
            f"{label} {field} {a['old_value']} -> {a['new_value']} ({a.get('change_time') or ''})"
        )
    return 0


def cmd_export(args) -> int:
    conn = store.connect(args.db)
    n = store.export_table(conn, args.table, args.out)
    print(f"已导出 {n} 行到 {args.out}")
    return 0


def cmd_stats(args) -> int:
    conn = store.connect(args.db)
    print("数据量：", store.counts(conn))
    rows = conn.execute(
        "SELECT match_date, COUNT(*) n FROM matches GROUP BY match_date ORDER BY match_date DESC LIMIT 10"
    ).fetchall()
    if rows:
        print("最近日期：")
        for r in rows:
            print(f"  {r['match_date']}: {r['n']} 场")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="titan007 足球数据采集器（比分/赛果优先）")
    p.add_argument("--db", default="data/titan007.db", help="SQLite 路径")
    p.add_argument(
        "--delay", type=float, default=None, help="请求基础间隔秒数（默认按命令取 1.5–4）"
    )
    p.add_argument("--jitter", type=float, default=None, help="随机抖动上限秒数（默认 0.5–4）")
    p.add_argument(
        "--pause-every", type=int, default=None, help="每 N 次请求停顿一次（默认 0=不停顿）"
    )
    p.add_argument("--pause-min", type=float, default=15.0, help="停顿最短秒数")
    p.add_argument("--pause-max", type=float, default=45.0, help="停顿最长秒数")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="初始化数据库").set_defaults(func=cmd_init)

    live = sub.add_parser("live", help="抓取实时比分快照/增量")
    live.add_argument("--loop", action="store_true", help="持续抓取增量")
    live.add_argument("--interval", type=float, default=5.0, help="增量轮询间隔秒")
    live.add_argument(
        "--refresh-snapshot", type=float, default=300.0, help="每 N 秒刷新全量快照（0=不刷新）"
    )
    live.set_defaults(func=cmd_live)

    hist = sub.add_parser("history", help="按日期抓取历史赛果/未来赛程")
    hist.add_argument("--start", required=True, help="YYYY-MM-DD")
    hist.add_argument("--end", required=True, help="YYYY-MM-DD")
    hist.add_argument("--include-next", action="store_true", help="同时抓 Next_ 未来赛程")
    hist.set_defaults(func=cmd_history)

    det = sub.add_parser("details", help="抓取比赛详情（技术统计/事件/阵容）")
    det.add_argument("--date", help="YYYY-MM-DD，从数据库选择当天比赛")
    det.add_argument("--match-id", type=int, nargs="+", help="直接指定一个或多个比赛ID")
    det.add_argument("--limit", type=int, default=None, help="最多处理多少场")
    det.add_argument("--only-missing", action="store_true", help="只处理尚无技术统计的比赛")
    det.add_argument("--with-scorers", action="store_true", help="用 detail_ut.js 补充进球球员")
    det.add_argument(
        "--with-header", action="store_true", help="额外抓取 analysisheader（场地/天气/温度）"
    )
    det.add_argument("--jc-only", action="store_true", help="只处理已关联到竞彩的比赛")
    det.set_defaults(func=cmd_details)

    pt = sub.add_parser("playertech", help="抓取球员技术统计（PlayerTech.aspx）")
    pt.add_argument("--date", help="YYYY-MM-DD，从数据库选择当天比赛")
    pt.add_argument("--match-id", type=int, nargs="+")
    pt.add_argument("--limit", type=int, default=None)
    pt.set_defaults(func=cmd_playertech)

    jc = sub.add_parser("jcodds", help="抓取竞彩赔率（胜平负/让球/总进球/半全场/比分）")
    jc.add_argument("--date", help="YYYY-MM-DD，从数据库选择当天比赛")
    jc.add_argument("--match-id", type=int, nargs="+")
    jc.add_argument("--limit", type=int, default=None)
    jc.set_defaults(func=cmd_jcodds)

    tl = sub.add_parser("textlive", help="抓取文字直播（仅比赛中有效）")
    tl.add_argument("--date", help="YYYY-MM-DD，从数据库选择当天比赛")
    tl.add_argument("--match-id", type=int, nargs="+")
    tl.add_argument("--limit", type=int, default=None)
    tl.set_defaults(func=cmd_textlive)

    odd = sub.add_parser("odds", help="抓取赔率（1x2d 百家欧赔 / vip 变化史 / 统一赔率快照）")
    odd.add_argument("--date", help="YYYY-MM-DD，从数据库选择当天比赛")
    odd.add_argument("--match-id", type=int, nargs="+", help="直接指定比赛ID")
    odd.add_argument("--limit", type=int, default=None, help="最多处理多少场")
    odd.add_argument("--feed", action="store_true", help="解析 ch_goalbf3.xml 全量快照（一次请求）")
    odd.add_argument("--vip", action="store_true", help="抓取 vip 单公司变化历史（较慢）")
    odd.add_argument("--companies", default="3", help="vip 公司ID，逗号分隔，如 3,8,12")
    odd.add_argument(
        "--types",
        default="1x2,handicap,overunder",
        help="vip 类型：1x2,handicap,overunder,1x2half,handicaphalf,overunderhalf",
    )
    odd.add_argument("--no-1x2d", action="store_true", help="跳过 1x2d 百家欧赔")
    odd.add_argument(
        "--all-companies", action="store_true", help="保存全部公司（默认只保存第一/第二梯队和竞彩）"
    )
    odd.add_argument("--jc-only", action="store_true", help="只处理已关联到竞彩的比赛")
    odd.set_defaults(func=cmd_odds)

    ana = sub.add_parser("analysis", help="抓取 zq 赛前分析（H2H/战绩/积分榜/伤停/简报）")
    ana.add_argument("--date", help="YYYY-MM-DD，从数据库选择当天比赛")
    ana.add_argument("--match-id", type=int, nargs="+", help="直接指定比赛ID")
    ana.add_argument("--limit", type=int, default=None, help="最多处理多少场")
    ana.add_argument("--with-json", action="store_true", help="额外保存 getAnalyData JSON")
    ana.add_argument("--jc-only", action="store_true", help="只处理已关联到竞彩的比赛")
    ana.set_defaults(func=cmd_analysis)

    tm = sub.add_parser("team", help="抓取球队资料/阵容（tdl{teamId}.js）")
    tm.add_argument("--team-id", type=int, nargs="+", required=True)
    tm.set_defaults(func=cmd_team)

    lg = sub.add_parser("league", help="抓取联赛整季赛果/积分榜/射手榜")
    lg.add_argument("--league-id", type=int, required=True)
    lg.add_argument("--season", help="如 2026-2027，缺省取最新赛季")
    lg.set_defaults(func=cmd_league)

    lgs = sub.add_parser("league-sync", help="批量同步多个赛事的当前赛季数据")
    lgs.add_argument(
        "--league-id", type=int, nargs="+", help="指定赛事ID；缺省取今日比分页全部赛事"
    )
    lgs.add_argument("--all", action="store_true", help="同步联赛目录里的全部赛事")
    lgs.add_argument("--season", help="强制赛季")
    lgs.add_argument(
        "--skip-done", action="store_true", help="跳过今天已成功同步的赛事（断点续跑）"
    )
    lgs.add_argument("--limit", type=int, default=None)
    lgs.set_defaults(func=cmd_league_sync)

    lcls = sub.add_parser(
        "league-classify", help="生成/导入赛事分类（地区/国家/类型/人群/级别/优先级）"
    )
    lcls.add_argument("--out", default="config/league_categories.json")
    lcls.add_argument("--import", dest="import_only", action="store_true", help="只导入现有 JSON")
    lcls.set_defaults(func=cmd_league_classify)

    comp = sub.add_parser("companies", help="同步博彩公司分级（第一/第二梯队、中国体彩）")
    comp.set_defaults(func=cmd_companies)

    lot = sub.add_parser("lottery", help="抓取中国体彩竞彩赛果/编号")
    lot.add_argument("--start", required=True, help="YYYY-MM-DD")
    lot.add_argument("--end", required=True, help="YYYY-MM-DD")
    lot.set_defaults(func=cmd_lottery)

    tl = sub.add_parser("team-link", help="建立体彩与 titan007 的球队/比赛映射")
    tl.add_argument("--start", required=True, help="YYYY-MM-DD")
    tl.add_argument("--end", required=True, help="YYYY-MM-DD")
    tl.add_argument("--import", dest="import_file", help="导入人工别名 CSV")
    tl.add_argument("--review-out", default="config/team_mapping_review.csv")
    tl.set_defaults(func=cmd_team_link)

    lo = sub.add_parser("lottery-odds", help="把竞彩胜平负赔率写入 odds 表")
    lo.set_defaults(func=cmd_lottery_odds)

    lrel = sub.add_parser("league-relations", help="补齐上一季积分榜并推断联赛升降级关系")
    lrel.add_argument("--fetch", action="store_true", help="抓取上一季积分榜")
    lrel.add_argument("--limit", type=int, default=None)
    lrel.set_defaults(func=cmd_league_relations)

    tsync = sub.add_parser("team-sync", help="梳理球队目录：竞彩名称、队徽、球员归属")
    tsync.add_argument("--logos", action="store_true", help="下载缺失队徽")
    tsync.add_argument("--squads", action="store_true", help="抓取缺失球队阵容")
    tsync.add_argument("--limit", type=int, default=None)
    tsync.set_defaults(func=cmd_team_sync)

    drv = sub.add_parser("derive", help="派生出场分钟、休息天数、伤停分类、来源记录")
    drv.set_defaults(func=cmd_derive)

    bft = sub.add_parser("backfill-teams", help="用已知队名反查补全比赛缺失的队伍ID（离线）")
    bft.add_argument("--dry-run", action="store_true", help="只统计不写库")
    bft.add_argument("--fuzzy", action="store_true", help="对剩下的比赛在同一联赛内做译名模糊匹配")
    bft.set_defaults(func=cmd_backfill_teams)

    bfs = sub.add_parser("backfill-seasons", help="抓取缺队伍ID的老赛季，补齐队名词典")
    bfs.add_argument("--dry-run", action="store_true", help="只列出待抓的赛事/年份")
    bfs.add_argument("--limit", type=int, default=None, help="最多处理多少个「赛事×年份」")
    bfs.set_defaults(func=cmd_backfill_seasons)

    rs = sub.add_parser("roster-sync", help="抓取重点球队的教练和球员转会")
    rs.add_argument("--coaches", action="store_true")
    rs.add_argument("--transfers", action="store_true")
    rs.add_argument("--top-teams", type=int, default=100)
    rs.add_argument("--limit", type=int, default=None)
    rs.set_defaults(func=cmd_roster_sync)

    w = sub.add_parser("watch", help="赔率异动监控（feed/vip）")
    w.add_argument("--mode", choices=["feed", "vip", "both"], default="feed")
    w.add_argument("--interval", type=float, default=60.0, help="轮询间隔秒")
    w.add_argument("--once", action="store_true", help="只跑一轮（适合 cron）")
    w.add_argument("--date", help="YYYY-MM-DD，vip 模式使用的比赛范围")
    w.add_argument("--match-id", type=int, nargs="+", help="vip 模式指定比赛")
    w.add_argument("--limit", type=int, default=None)
    w.add_argument("--companies", default="3", help="vip 公司ID，逗号分隔")
    w.add_argument("--types", default="1x2,handicap,overunder")
    w.add_argument("--min-delta", type=float, default=0.0, help="忽略小于该值的水位变化")
    w.add_argument("--quiet", action="store_true", help="只写库，不在终端输出异动")
    w.set_defaults(func=cmd_watch)

    al = sub.add_parser("alerts", help="查看最近赔率异动")
    al.add_argument("--limit", type=int, default=50)
    al.add_argument("--since", help="YYYY-MM-DD HH:MM:SS")
    al.set_defaults(func=cmd_alerts)

    ast = sub.add_parser("assets", help="下载球队队徽 / 球员头像")
    ast.add_argument("--type", nargs="+", choices=["team", "player"], default=["team", "player"])
    ast.add_argument(
        "--scope",
        choices=["today", "matches", "all"],
        default="today",
        help="队伍范围：today=今日比分页，matches=matches 表，all=联赛扫描到的全部",
    )
    ast.add_argument(
        "--fill-missing", action="store_true", help="对缺 logo 的球队/球员逐个抓详情页"
    )
    ast.add_argument(
        "--no-league-scan", action="store_true", help="不从联赛 JS 的 arrTeam 提取队徽"
    )
    ast.add_argument("--limit", type=int, default=None, help="每类最多下载/补抓多少个")
    ast.add_argument("--out-dir", default="data/images", help="图片保存目录")
    ast.set_defaults(func=cmd_assets)

    exp = sub.add_parser("export", help="导出表为 CSV")
    exp.add_argument(
        "--table",
        required=True,
        choices=[
            "matches",
            "leagues",
            "match_stats",
            "events",
            "lineups",
            "ingest_log",
            "odds",
            "odds_history",
            "analysis_sections",
            "team_profiles",
            "team_squad",
            "team_league_stats",
            "team_honors",
            "team_cups",
            "team_matches",
            "league_info",
            "league_results",
            "league_standings",
            "scorers",
            "league_teams",
            "league_categories",
            "odds_alerts",
            "odds_companies",
            "lottery_matches",
            "lottery_teams",
            "team_mapping",
            "team_aliases",
            "team_league_seasons",
            "team_movements",
            "league_relations",
            "team_catalog",
            "match_injuries",
            "player_appearances",
            "match_context",
            "data_provenance",
            "player_transfers",
            "team_coaches",
            "assets",
            "player_stats",
            "jc_odds",
            "text_live",
        ],
    )
    exp.add_argument("--out", required=True)
    exp.set_defaults(func=cmd_export)

    sub.add_parser("stats", help="查看数据量").set_defaults(func=cmd_stats)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
