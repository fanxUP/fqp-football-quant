"""Parsers for titan007 pages and feeds."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup

from . import jsfmt

# detail 页 techStatisticData 的指标顺序（与 scoreOddsNew.js 的 techKindNameList 一致）
TECH_KIND_NAMES = (
    "角球",
    "半场角球",
    "黄牌",
    "红牌",
    "射门",
    "射正",
    "进攻",
    "危险进攻",
    "射门不中",
    "射门被挡",
    "任意球",
    "控球率",
    "半场控球率",
    "传球",
    "传球成功率",
    "犯规",
    "越位",
    "头球",
    "头球成功",
    "救球",
    "铲球",
    "换人数",
    "过人",
    "界外球",
    "中柱",
    "角球数（加时）",
    "越位（加时）",
    "乌龙球数",
    "黄牌数（加时）",
    "守门员出击",
    "丟球",
    "成功抢断",
    "阻截",
    "成功传中",
    "助攻",
    "换人数（加时）",
    "长传",
    "短传",
    "先开球",
    "第一张黄牌",
    "最后一张黄牌",
    "第一个换人",
    "最后一个换人",
    "第一个角球",
    "最后一个角球",
    "第一个越位",
    "最后越位",
    "预期进球(xG)",
    "运动战预期进球",
    "定位球预期进球",
    "非点球预期进球",
    "射正预期进球",
    "得分机会",
    "错失得分机会",
    "禁区内射门",
    "禁区外射门",
    "对方禁区触球",
    "解围",
    "地面对抗成功",
    "争顶成功",
)


def parse_tech_statistic_data(html: str) -> dict[str, dict[str, str]]:
    """解析 detail 页内嵌的 techStatisticData（部分比赛没有 HTML 统计表）。"""
    m = re.search(r'var\s+techStatisticData\s*=\s*"([^"]*)"', html)
    if not m:
        return {}
    data = jsfmt.js_literal(m.group(1))
    if not isinstance(data, list) or not data:
        return {}
    block = data[0]
    rows = block[1:] if isinstance(block, list) and block and block[0] == 0 else block
    out: dict[str, dict[str, str]] = {}
    for row in rows or []:
        if not isinstance(row, list) or len(row) < 3:
            continue
        idx = _int(row[0])
        if idx is None or not (0 <= idx < len(TECH_KIND_NAMES)):
            continue
        out[TECH_KIND_NAMES[idx]] = {"home": str(row[1]), "away": str(row[2])}
    return out


# ---------------------------------------------------------------- 状态码

STATUS_CODE = {
    "推迟": -14,
    "推": -14,
    "中断": -13,
    "断": -13,
    "腰斩": -12,
    "腰": -12,
    "待定": -11,
    "待": -11,
    "取消": -10,
    "取": -10,
    "完": -1,
    "未": 0,
    "上": 1,
    "中": 2,
    "下": 3,
    "加": 4,
    "点": 5,
}

STATUS_TEXT = {
    -14: "推迟",
    -13: "中断",
    -12: "腰斩",
    -11: "待定",
    -10: "取消",
    -1: "完场",
    0: "未开赛",
    1: "上半场",
    2: "中场",
    3: "下半场",
    4: "加时",
    5: "点球",
}


def status_text(code: int | None) -> str:
    if code is None:
        return ""
    return STATUS_TEXT.get(int(code), str(code))


def _int(v: Any) -> int | None:
    try:
        s = str(v).strip()
        if s == "" or s == "-":
            return None
        return int(float(s))
    except TypeError, ValueError:
        return None


def _float(v: Any) -> float | None:
    try:
        s = str(v).strip()
        if s == "" or s == "-":
            return None
        return float(s)
    except TypeError, ValueError:
        return None


def _clean(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _js_unescape(s: str) -> str:
    return s.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")


def parse_yyyymmdd(value: str) -> str | None:
    value = (value or "").strip()
    if not re.fullmatch(r"\d{8}", value):
        return None
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def parse_server_datetime(value: str) -> str | None:
    """把 '2026,9,17,19,23,18'（月从0开始）转成 ISO 字符串。"""
    parts = (value or "").split(",")
    if len(parts) != 6:
        return None
    try:
        year, month0, day, hour, minute, second = map(int, parts)
        return datetime(year, month0 + 1, day, hour, minute, second).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


# ---------------------------------------------------------------- 实时快照


def parse_bfdata(text: str) -> dict[str, Any]:
    """解析 vbsxml/bfdata_ut.js。

    返回 {"matches": [...], "leagues": [...], "meta": {...}}
    """
    meta: dict[str, Any] = {}
    for key in ("matchcount", "sclasscount", "matchdate", "topLeagueIds", "firstschematchtime"):
        m = re.search(rf"var\s+{key}\s*=\s*\"?([^\";]*)\"?;", text)
        if m:
            meta[key] = m.group(1)

    def extract(name: str) -> dict[int, list[str]]:
        out: dict[int, list[str]] = {}
        for idx, raw in re.findall(rf'{name}\[(\d+)\]="([^"]*)"\.split', text):
            out[int(idx)] = _js_unescape(raw).split("^")
        return out

    a = extract("A")
    b = extract("B")

    matches = []
    for i in sorted(a):
        f = a[i]
        if len(f) < 60:
            continue
        year = _int(f[43]) if len(f) > 43 else None
        md = f[36] if len(f) > 36 else ""
        match_date = None
        if year and re.fullmatch(r"\d{2}-\d{2}", md):
            match_date = f"{year:04d}-{md}"
        kickoff = f"{match_date} {f[11]}".strip() if match_date else f[11]
        status = _int(f[13])
        matches.append(
            {
                "match_id": _int(f[0]),
                "source": "live",
                "match_date": match_date,
                "kickoff": kickoff,
                "league_id": _int(f[45]),
                "sub_league_id": None,
                "league_name": f[2],
                "league_color": f[1],
                "country_id": _int(f[40]),
                "home_id": _int(f[37]),
                "home_name": f[5],
                "away_id": _int(f[38]),
                "away_name": f[8],
                "status_code": status,
                "status_text": status_text(status),
                "home_score": _int(f[14]),
                "away_score": _int(f[15]),
                "home_half": _int(f[16]),
                "away_half": _int(f[17]),
                "home_red": _int(f[18]),
                "away_red": _int(f[19]),
                "home_yellow": _int(f[20]),
                "away_yellow": _int(f[21]),
                "home_rank": _int(f[22]),
                "away_rank": _int(f[23]),
                "ah_line": _float(f[29]),
                "ou_line": _float(f[46]),
                "home_corners": _int(f[48]),
                "away_corners": _int(f[49]),
                "has_odds": 1 if f[29] not in ("", None) else 0,
                "has_animation": _int(f[47]),
                "is_hot": _int(f[62]),
                "lottery_jc": f[57] or None,
                "lottery_bf": f[58] or None,
                "lottery_dc": f[59] or None,
                "updated_at": parse_server_datetime(f[12]) or f[12],
                "raw": "^".join(f),
            }
        )

    leagues = []
    for i in sorted(b):
        f = b[i]
        if len(f) < 14:
            continue
        leagues.append(
            {
                "league_id": _int(f[4]),
                "name_simplified": f[0],
                "name_traditional": f[1],
                "kind": _int(f[3]),
                "info_url": f[8],
                "has_hd_live": _int(f[13]),
            }
        )
    return {"matches": matches, "leagues": leagues, "meta": meta}


def parse_change_xml(text: str) -> list[dict[str, Any]]:
    """解析 change2_ut.xml 增量。"""
    out = []
    for raw in re.findall(r"<!\[CDATA\[(.*?)\]\]>", text):
        f = raw.split("^")
        if len(f) < 12:
            continue
        out.append(
            {
                "match_id": _int(f[0]),
                "status_code": _int(f[1]),
                "home_score": _int(f[2]),
                "away_score": _int(f[3]),
                "home_half": _int(f[4]),
                "away_half": _int(f[5]),
                "home_red": _int(f[6]),
                "away_red": _int(f[7]),
                "kickoff_time": f[8],
                "updated_at": parse_server_datetime(f[9]) or f[9],
                "home_yellow": _int(f[12]) if len(f) > 12 else None,
                "away_yellow": _int(f[13]) if len(f) > 13 else None,
                "match_date_md": f[14] if len(f) > 14 else None,
                "home_corners": _int(f[16]) if len(f) > 16 else None,
                "away_corners": _int(f[17]) if len(f) > 17 else None,
                "raw": raw,
            }
        )
    return out


# ---------------------------------------------------------------- 历史赛果


def _parse_kickoff(text: str, page_date: date) -> str | None:
    text = _clean(text)
    # 历史页：16日13:30
    m = re.search(r"(\d{1,2})日\s*(\d{1,2}):(\d{2})", text)
    if m:
        day, hh, mm = int(m.group(1)), int(m.group(2)), int(m.group(3))
        dt = date(page_date.year, page_date.month, day)
        # 跨月：页面日期接近月末，而比赛日很小
        if day < 10 and page_date.day > 20:
            year, month = (
                (page_date.year + 1, 1)
                if page_date.month == 12
                else (page_date.year, page_date.month + 1)
            )
            dt = date(year, month, day)
        return f"{dt.isoformat()} {hh:02d}:{mm:02d}"
    # 赛程页：10-18 10:30 / 2026-10-18 10:30
    m = re.search(r"(?:(\d{4})-)?(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", text)
    if m:
        year = int(m.group(1)) if m.group(1) else page_date.year
        month, day, hh, mm = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        if not m.group(1) and month < page_date.month - 6:
            year += 1
        try:
            return f"{date(year, month, day).isoformat()} {hh:02d}:{mm:02d}"
        except ValueError:
            return None
    # 只有时间：13:30（用页面日期）
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if m:
        return f"{page_date.isoformat()} {int(m.group(1)):02d}:{m.group(2)}"
    return None


def _count_cards(cell) -> tuple[int | None, int | None]:
    html = str(cell)
    yellow = re.findall(r"yellow(\d+)\.gif", html)
    red = re.findall(r"redcard(\d+)\.gif", html)
    return (max(map(int, yellow)) if yellow else 0, max(map(int, red)) if red else 0)


def parse_history_page(html: str, page_date: date) -> list[dict[str, Any]]:
    """解析 bf.titan007.com/football/Over_*.htm 或 Next_*.htm。"""
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, Any]] = []
    for tr in soup.find_all("tr", id=re.compile(r"^tr1_")):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 9:
            continue
        match_id = _int(tr.get("sid") or tr.get("sId"))
        if not match_id:
            m = re.search(r"(?:showgoallist|analysis|AsianOdds|EuropeOdds)\((\d+)\)", str(tr))
            match_id = _int(m.group(1)) if m else None
        if not match_id:
            continue
        league_ids = (tr.get("name") or "").split(",")
        league_id = _int(league_ids[0]) if league_ids else None
        sub_league_id = _int(league_ids[1]) if len(league_ids) > 1 else None
        country_id = _int(tr.get("infoid"))

        league_name = _clean(tds[0].get_text(" ", strip=True))
        kickoff = _parse_kickoff(tds[1].get_text(" ", strip=True), page_date)
        # 用实际开球日期做 match_date（凌晨比赛可能落在页面日期的次日）
        match_date = kickoff[:10] if kickoff else page_date.isoformat()
        status_raw = _clean(tds[2].get_text(" ", strip=True))
        status = None
        if status_raw:
            status = STATUS_CODE.get(status_raw[0], STATUS_CODE.get(status_raw, None))

        home_yellow, home_red = _count_cards(tds[3])
        away_yellow, away_red = _count_cards(tds[5])

        def team_cell(cell) -> tuple[str, int | None]:
            rank = None
            for span in cell.find_all("span", attrs={"name": "order"}):
                m = re.search(r"\d+", span.get_text(" ", strip=True))
                if m:
                    rank = int(m.group())
                span.decompose()
            return _clean(cell.get_text(" ", strip=True)), rank

        home_name, home_rank = team_cell(tds[3])
        away_name, away_rank = team_cell(tds[5])

        score = _clean(tds[4].get_text(" ", strip=True))
        half = _clean(tds[6].get_text(" ", strip=True))

        def split_score(s: str) -> tuple[int | None, int | None]:
            m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", s)
            return (_int(m.group(1)), _int(m.group(2))) if m else (None, None)

        hs, as_ = split_score(score)
        hh, ah = split_score(half)

        hdp_cell = tds[7]
        ou_cell = tds[8]
        ah_line = _float(hdp_cell.get("val"))
        ou_line = _float(ou_cell.get("val"))
        ah_text = _clean(hdp_cell.get_text(" ", strip=True))
        ou_text = _clean(ou_cell.get_text(" ", strip=True))

        out.append(
            {
                "match_id": match_id,
                "source": "history",
                "match_date": match_date,
                "kickoff": kickoff,
                "league_id": league_id,
                "sub_league_id": sub_league_id,
                "league_name": league_name,
                "country_id": country_id,
                "home_name": home_name,
                "away_name": away_name,
                "home_rank": home_rank,
                "away_rank": away_rank,
                "status_code": status,
                "status_text": STATUS_TEXT.get(status, status_raw)
                if status is not None
                else status_raw,
                "home_score": hs,
                "away_score": as_,
                "home_half": hh,
                "away_half": ah,
                "home_yellow": home_yellow,
                "away_yellow": away_yellow,
                "home_red": home_red,
                "away_red": away_red,
                "ah_line": ah_line,
                "ou_line": ou_line,
                "ah_text": ah_text,
                "ou_text": ou_text,
                "raw": str(tr),
            }
        )
    return out


# ---------------------------------------------------------------- 比赛详情


def parse_detail_page(html: str, match_id: int) -> dict[str, Any]:
    """解析 live.titan007.com/detail/{id}cn.htm。

    返回 header / stats / events / lineups。
    """
    soup = BeautifulSoup(html, "html.parser")
    header: dict[str, Any] = {"match_id": match_id}

    def js_var(name: str):
        m = re.search(rf"var\s+{name}\s*=\s*'([^']*)'", html)
        if m:
            return m.group(1)
        m = re.search(rf"var\s+{name}\s*=\s*(-?\d+)", html)
        return m.group(1) if m else None

    header["kickoff"] = js_var("strTime")
    header["state"] = _int(js_var("state"))
    header["home_name"] = js_var("homeTeamName")
    header["away_name"] = js_var("guestTeamName")
    header["home_logo"] = js_var("homeTeamFlg")
    header["away_logo"] = js_var("guestTeamFlg")

    # 天气 / 温度（详情页头部 <label>天气：…</label><label>温度：…</label>）
    for label in soup.find_all("label"):
        text = _clean(label.get_text(" ", strip=True))
        if text.startswith("天气："):
            header["weather"] = text.split("：", 1)[1].strip() or None
        elif text.startswith("温度："):
            header["temperature"] = text.split("：", 1)[1].strip() or None

    # 技术统计
    stats: dict[str, dict[str, str]] = {}
    for div in soup.select("ul#teamTechDiv li.lists div.data"):
        spans = div.find_all("span", recursive=False)
        if len(spans) < 3:
            continue
        label = _clean(spans[1].get_text(" ", strip=True))
        home_value = _clean(spans[0].get_text(" ", strip=True))
        away_value = _clean(spans[2].get_text(" ", strip=True))
        if not label or (not home_value and not away_value):
            continue
        stats[label] = {
            "home": home_value,
            "away": away_value,
        }
    if not stats:
        stats = parse_tech_statistic_data(html)

    # 重要事件
    events: list[dict[str, Any]] = []
    for li in soup.select("ul#teamEventDiv li.lists"):
        div = li.find("div", class_="data")
        if not div:
            continue
        spans = div.find_all("span", recursive=False)
        if len(spans) < 3:
            continue
        minute = _clean(spans[1].get_text(" ", strip=True))
        left, right = spans[0], spans[2]
        side = "home" if left.find(["img", "a", "i"]) else "away"
        node = left if side == "home" else right
        titles = [img.get("title") for img in node.find_all("img") if img.get("title")]
        event_type = titles[-1] if titles else ""
        if not event_type and node.find("i", class_="goalicon"):
            event_type = "入球"
        players = []
        for a in node.find_all("a"):
            name = _clean(a.get("title") or a.get_text(" ", strip=True))
            if name:
                players.append(name)
        assist = players[1] if len(players) > 1 else None
        if assist:
            assist = re.sub(r"^助攻\s*[:：]?\s*", "", assist).strip()
        if not minute:
            continue
        events.append(
            {
                "seq": len(events) + 1,
                "minute": minute,
                "side": side,
                "event_type": event_type,
                "player_name": players[0] if players else None,
                "assist_name": assist,
                "raw": str(div)[:1000],
            }
        )

    # 预计阵容 / 替补（有数据时才有内容）
    lineups: list[dict[str, Any]] = []
    box = soup.find(id="matchBox2")
    if box:
        for side, css, starter in (
            ("home", "div.plays div.home", 1),
            ("away", "div.plays div.guest", 1),
            ("home", "div.backupPlay2 div.home", 0),
            ("away", "div.backupPlay2 div.guest", 0),
        ):
            node = box.select_one(css)
            if not node:
                continue
            for play in node.select("div.play"):
                name_node = play.select_one("div.name a")
                if not name_node:
                    continue
                href = name_node.get("href") or ""
                m = re.search(r"/player/\d+/(\d+)\.html", href)
                info = {}
                for li in play.select("ul li"):
                    txt = _clean(li.get_text(" ", strip=True))
                    parts = re.split(r"[：:]", txt, maxsplit=1)
                    if len(parts) == 2:
                        info[parts[0].strip()] = parts[1].strip()
                lineups.append(
                    {
                        "side": side,
                        "player_id": _int(m.group(1)) if m else None,
                        "player_name": _clean(name_node.get_text(" ", strip=True)),
                        "number": _clean(play.select_one("em.num").get_text(strip=True))
                        if play.select_one("em.num")
                        else None,
                        "position": info.get("位置"),
                        "starter": starter,
                        "birth": info.get("生日"),
                        "height": info.get("身高"),
                        "value": info.get("身价"),
                        "nationality": info.get("国籍"),
                        "raw": str(play)[:2000],
                    }
                )

    # 比分（从事件区标题）
    home_score = away_score = None
    tit = soup.select_one("li.teamtit span.homeTN i")
    if tit:
        home_score = _int(tit.get_text(strip=True))
    tit = soup.select_one("li.teamtit span.guestTN i")
    if tit:
        away_score = _int(tit.get_text(strip=True))

    return {
        "header": header,
        "stats": stats,
        "events": events,
        "lineups": lineups,
        "home_score": home_score,
        "away_score": away_score,
    }


def parse_detail_ut(text: str) -> dict[tuple[int, str], list[dict[str, str]]]:
    """解析 vbsxml/detail_ut.js，返回 {(match_id, minute): [事件]}。"""
    out: dict[tuple[int, str], list[dict[str, str]]] = {}
    for raw in re.findall(r'rq\[\d+\]="([^"]*)"', text):
        f = raw.split("^")
        if len(f) < 7:
            continue
        mid = _int(f[0])
        minute = f[3].strip()
        if not mid or not minute:
            continue
        out.setdefault((mid, minute), []).append(
            {
                "side": "home" if f[1] == "1" else "away",
                "event_type": f[2],
                "player_name": f[6] or f[4],
                "player_name_traditional": f[4],
                "player_name_english": f[9] if len(f) > 9 else "",
                "player_id": f[5],
            }
        )
    return out


def parse_analysis_header(text: str) -> dict[str, Any]:
    """解析 phone/txt/analysisheader 文件（^ 分隔）。"""
    f = text.split("^")
    out: dict[str, Any] = {"raw": text}
    if len(f) > 40:
        kickoff = f[5]
        if re.fullmatch(r"\d{14}", kickoff):
            kickoff = datetime.strptime(kickoff, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M")
        out.update(
            {
                "home_name": f[0],
                "away_name": f[1],
                "home_name_traditional": f[2],
                "away_name_traditional": f[3],
                "state": _int(f[4]),
                "kickoff": kickoff,
                "home_rank": _int(f[6]),
                "away_rank": _int(f[7]),
                "home_logo": f[8],
                "away_logo": f[9],
                "league_id": _int(f[13]),
                "league_name": f[15],
                "home_id": _int(f[17]),
                "away_id": _int(f[18]),
                "temperature": f[19] or None,
                "weather": f[20] or None,
                "venue": f[31] or None,
                "round": f[39] or None,
            }
        )
    for value in f:
        if any(k in value for k in ("体育场", "球场", "Stadium", "Arena")):
            out.setdefault("venue", value)
            break
    return out


def merge_scorers(
    detail: dict[str, Any], scorers: dict[tuple[int, str], list[dict[str, str]]], match_id: int
) -> None:
    """把 detail_ut.js 里的进球球员合并进事件（只补空）。"""
    for ev in detail.get("events", []):
        candidates = scorers.get((match_id, ev["minute"]), [])
        for c in candidates:
            if c["side"] == ev["side"]:
                if not ev.get("player_name"):
                    ev["player_name"] = c["player_name"]
                if not ev.get("player_name_english"):
                    ev["player_name_english"] = c.get("player_name_english")
                break


def parse_player_tech(html: str) -> dict[str, list[dict[str, Any]]]:
    """PlayerTech.aspx：两张表（主队/客队），表头即字段名。"""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, list[dict[str, str]]] = {"home": [], "away": []}
    for side, table in zip(("home", "away"), soup.find_all("table")[:2], strict=False):
        rows = table.find_all("tr")
        if not rows:
            continue
        header = [c.get_text(" ", strip=True) for c in rows[0].find_all(["td", "th"])]
        for tr in rows[1:]:
            cell_nodes = tr.find_all(["td", "th"])
            cells = [c.get_text(" ", strip=True) for c in cell_nodes]
            if len(cells) < 4 or not cells[1]:
                continue
            row = {header[i]: cells[i] for i in range(min(len(header), len(cells))) if header[i]}
            m = re.search(r"PlayerID=(\d+)", str(cell_nodes[1]))
            row["player_id"] = int(m.group(1)) if m else None
            out[side].append(row)
    return out


def parse_jc_odds(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """getAnalyData 的 jcOdds：胜平负 / 让球 / 总进球 / 半全场 / 比分。"""
    jc = payload.get("jcOdds") or {}
    if not isinstance(jc, dict):
        return []
    out = []
    for key, market in (
        ("sfOdds", "sf"),
        ("wlOdds", "wl"),
        ("goalOdds", "goal"),
        ("hfOdds", "hf"),
        ("scoreOdds", "score"),
    ):
        block = jc.get(key)
        if not isinstance(block, dict):
            continue
        for phase in ("first", "live"):
            value = block.get(phase)
            if not isinstance(value, dict):
                continue
            out.append(
                {
                    "market": market,
                    "phase": phase,
                    "home": value.get("win"),
                    "draw": value.get("draw"),
                    "away": value.get("lose"),
                    "line": block.get("rf") if key == "sfOdds" else None,
                    "payload": value,
                }
            )
    return out


def parse_text_live(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else None
    content = soup.get_text("\n", strip=True)
    return {"title": title, "content": content}


def parse_player_photo_map(html: str) -> dict[int, str]:
    """详情页 playerImgData：player_id -> images/.../xxx.png。"""
    m = re.search(r'var\s+playerImgData\s*=\s*"([^"]*)"', html)
    if not m or not m.group(1):
        return {}
    out = {}
    for item in m.group(1).split("^"):
        pid, _, path = item.partition(",")
        if pid.strip().isdigit() and path.strip():
            out[int(pid.strip())] = path.strip()
    return out


def parse_predicted_lineup(html: str) -> dict[str, Any]:
    """详情页“预计阵容”：教练和双方球员（有数据时）。"""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Any] = {"home": [], "away": [], "coaches": {}}
    for side, klass in (("home", "homeN"), ("away", "guestN")):
        node = soup.select_one(f"div.{klass}")
        if not node:
            continue
        coach = node.select_one("a.coach")
        if coach:
            out["coaches"][side] = coach.get("title") or coach.get_text(" ", strip=True)
    box = soup.find(id="matchBox2")
    if not box:
        return out
    for side, klass in (("home", "home"), ("away", "guest")):
        container = box.select_one(f"div.plays div.{klass}")
        if not container:
            continue
        for play in container.select("div.play"):
            num = play.select_one(".num")
            link = play.select_one(".name a") or play.select_one("a")
            name = (link.get("title") if link else None) or (
                link.get_text(" ", strip=True) if link else ""
            )
            if not name:
                continue
            out[side].append(
                {
                    "number": num.get_text(" ", strip=True) if num else None,
                    "player_name": name.strip(),
                    "position": None,
                }
            )
    return out
