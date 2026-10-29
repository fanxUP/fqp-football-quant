"""Odds change monitoring for titan007 feeds."""

from __future__ import annotations

import sys
import time
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from . import odds as odds_parser
from . import store
from .client import AcquisitionStopped, TitanClient, record_operation_failure

ODDS_FEED_URL = "https://live.titan007.com/vbsxml/ch_goalbf3.xml?r=007"
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
VIP_TYPES = {
    "1x2": "europe",
    "handicap": "asian",
    "overunder": "overunder",
    "1x2half": "europe_half",
    "handicaphalf": "asian_half",
    "overunderhalf": "overunder_half",
}

TYPE_LABELS = {
    "europe": "欧赔",
    "asian": "亚盘",
    "overunder": "大小球",
    "europe_half": "半场欧赔",
    "asian_half": "半场亚盘",
    "overunder_half": "半场大小",
}

FIELD_LABELS = {
    "asian": {"live_home": "主水", "live_line": "盘口", "live_away": "客水"},
    "overunder": {"live_home": "大球", "live_line": "进球数", "live_away": "小球"},
    "europe": {"live_home": "主胜", "live_line": "平局", "live_away": "客胜"},
    "asian_half": {"live_home": "主水", "live_line": "盘口", "live_away": "客水"},
    "overunder_half": {"live_home": "大球", "live_line": "进球数", "live_away": "小球"},
    "europe_half": {"live_home": "主胜", "live_line": "平局", "live_away": "客胜"},
}

COMPANY_NAMES = {
    1: "澳*",
    3: "Crow*",
    8: "36*",
    12: "易*",
    18: "12*",
    31: "伟*",
    35: "明*",
    42: "10*",
    281: "Bet365",
}


def field_label(odds_type: str, field: str) -> str:
    key = field if field.startswith("live_") else f"live_{field}"
    return FIELD_LABELS.get(odds_type, {}).get(key, field)


def company_label(company_id: Any, company_name: str | None = None) -> str:
    return company_name or COMPANY_NAMES.get(company_id) or f"公司{company_id}"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


class OddsMonitor:
    def __init__(self, conn, client: TitanClient, min_delta: float = 0.0, quiet: bool = False):
        self.conn = conn
        self.client = client
        self.min_delta = max(0.0, min_delta)
        self.quiet = quiet

    def _changed(self, field: str, old: Any, new: Any) -> bool:
        if old is None and new is None:
            return False
        if str(old) == str(new):
            return False
        if field == "live_line":
            return True
        if old is None or new is None:
            return True
        try:
            return abs(float(new) - float(old)) >= self.min_delta
        except TypeError, ValueError:
            return True

    def _alert(
        self,
        match_id: int,
        company_id: int,
        company_name: str | None,
        odds_type: str,
        source: str,
        field: str,
        old: Any,
        new: Any,
        change_time: str,
        info: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "match_id": match_id,
            "company_id": company_id,
            "company_name": company_name,
            "odds_type": odds_type,
            "source": source,
            "field": field,
            "old_value": _fmt(old),
            "new_value": _fmt(new),
            "change_time": change_time,
            "detected_at": _now(),
            "match_date": info.get("match_date"),
            "league_name": info.get("league_name"),
            "home_name": info.get("home_name"),
            "away_name": info.get("away_name"),
        }

    def poll_feed(self) -> tuple[int, int, list[dict[str, Any]]]:
        xml = self.client.get(ODDS_FEED_URL)
        feed = odds_parser.parse_goal_feed(xml)
        rows: list[dict[str, Any]] = []
        alerts: list[dict[str, Any]] = []
        for f in feed:
            mid = f["match_id"]
            info = store.get_match_info(self.conn, mid)
            specs = [
                (
                    "asian",
                    {
                        "live_home": f["asian_home"],
                        "live_line": f["asian_line"],
                        "live_away": f["asian_away"],
                    },
                ),
                (
                    "europe",
                    {
                        "live_home": f["euro_home"],
                        "live_line": f["euro_draw"],
                        "live_away": f["euro_away"],
                    },
                ),
                (
                    "overunder",
                    {
                        "live_home": f["ou_over"],
                        "live_line": f["ou_line"],
                        "live_away": f["ou_under"],
                    },
                ),
            ]
            for odds_type, values in specs:
                old = store.get_odds(self.conn, mid, f["company_id"], odds_type, "feed")
                if old:
                    for field, new in values.items():
                        if self._changed(field, old.get(field), new):
                            alerts.append(
                                self._alert(
                                    mid,
                                    f["company_id"],
                                    f["company_name"],
                                    odds_type,
                                    "feed",
                                    field,
                                    old.get(field),
                                    new,
                                    _now(),
                                    info,
                                )
                            )
                rows.append(
                    {
                        "match_id": mid,
                        "company_id": f["company_id"],
                        "company_name": f["company_name"],
                        "odds_type": odds_type,
                        "source": "feed",
                        "live_home": values["live_home"],
                        "live_line": values["live_line"],
                        "live_away": values["live_away"],
                        "updated_at": _now(),
                    }
                )
        store.save_odds(self.conn, rows)
        inserted = store.insert_alerts(self.conn, alerts)
        return len(feed), inserted, alerts

    def poll_vip(
        self,
        match_ids: Iterable[int],
        companies: Iterable[int],
        types: Iterable[str],
    ) -> tuple[int, int, list[dict[str, Any]]]:
        checked = 0
        alerts: list[dict[str, Any]] = []
        for mid in match_ids:
            info = store.get_match_info(self.conn, mid)
            for cid in companies:
                for typ in types:
                    page = VIP_PAGES.get(typ)
                    odds_type = VIP_TYPES.get(typ)
                    if not page or not odds_type:
                        continue
                    url = VIP_CHANGE_URL.format(page=page, match_id=mid, company_id=cid)
                    try:
                        html = self.client.get(url, referer="https://vip.titan007.com/")
                        rows = odds_parser.parse_vip_change(html)
                        if not rows:
                            continue
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
                        old = store.get_latest_history(self.conn, mid, cid, odds_type, "vip")
                        if old:
                            for field in ("home", "line", "away"):
                                if self._changed(field, old.get(field), latest.get(field)):
                                    alerts.append(
                                        self._alert(
                                            mid,
                                            cid,
                                            None,
                                            odds_type,
                                            "vip",
                                            field,
                                            old.get(field),
                                            latest.get(field),
                                            latest.get("change_time") or _now(),
                                            info,
                                        )
                                    )
                        initial = (
                            next((r for r in rows if "初" in str(r.get("status") or "")), None)
                            or rows[-1]
                        )
                        store.save_odds(
                            self.conn,
                            [
                                {
                                    "match_id": mid,
                                    "company_id": cid,
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
                        store.save_odds_history(self.conn, mid, cid, odds_type, "vip", rows)
                        checked += 1
                    except AcquisitionStopped:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        record_operation_failure()
                        print(f"vip 监控失败 {mid}/{cid}/{typ}: {exc}", file=sys.stderr)
        inserted = store.insert_alerts(self.conn, alerts)
        return checked, inserted, alerts

    def print_alerts(self, alerts: Iterable[dict[str, Any]]) -> None:
        if self.quiet:
            return
        for a in alerts:
            label = TYPE_LABELS.get(a["odds_type"], a["odds_type"])
            field = field_label(a["odds_type"], a["field"])
            company = company_label(a["company_id"], a.get("company_name"))
            teams = f"{a.get('home_name') or ''} vs {a.get('away_name') or ''}".strip()
            league = a.get("league_name") or ""
            prefix = f"{league} {teams}".strip()
            if not teams:
                prefix = f"比赛 {a['match_id']}"
            print(
                f"[{a['detected_at'][11:]}] {prefix} | {company} "
                f"{label} {field} {a['old_value']} -> {a['new_value']} ({a.get('change_time') or ''})"
            )


def _num(value):
    try:
        s = str(value).strip()
        if s == "":
            return None
        return float(s)
    except TypeError, ValueError:
        return None


def run(
    conn,
    client: TitanClient,
    mode: str = "feed",
    interval: float = 60.0,
    once: bool = False,
    match_ids: list[int] | None = None,
    companies: list[int] | None = None,
    types: list[str] | None = None,
    min_delta: float = 0.0,
    quiet: bool = False,
) -> int:
    monitor = OddsMonitor(conn, client, min_delta=min_delta, quiet=quiet)
    companies = companies or [3]
    types = types or ["1x2", "handicap", "overunder"]
    if mode in ("vip", "both") and not match_ids:
        print("vip 监控需要 --date 或 --match-id 指定比赛", file=sys.stderr)
        return 2

    total_alerts = 0
    while True:
        started = time.time()
        iter_alerts = 0
        try:
            if mode in ("feed", "both"):
                matches, inserted, alerts = monitor.poll_feed()
                iter_alerts += inserted
                total_alerts += inserted
                monitor.print_alerts(alerts)
                if not quiet:
                    print(f"[{_now()}] feed: {matches} 场，异动 {inserted} 条")
            if mode in ("vip", "both"):
                checked, inserted, alerts = monitor.poll_vip(match_ids or [], companies, types)
                iter_alerts += inserted
                total_alerts += inserted
                monitor.print_alerts(alerts)
                if not quiet:
                    print(f"[{_now()}] vip: {checked} 个盘口，异动 {inserted} 条")
            store.log(conn, "watch", mode, "ok", f"alerts={iter_alerts}")
        except KeyboardInterrupt:
            break
        except AcquisitionStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            record_operation_failure()
            print(f"监控轮询失败：{exc}", file=sys.stderr)
            store.log(conn, "watch", mode, "error", str(exc))
        if once:
            break
        elapsed = time.time() - started
        time.sleep(max(0.0, interval - elapsed))
    return 0
