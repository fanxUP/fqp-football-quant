"""赛事分类：地区 / 国家 / 类型 / 人群 / 级别 / 优先级。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

# 关键词 -> (国家, 地区)。按顺序匹配名称开头；长词在前避免误判。
COUNTRY_RULES: list[tuple[str, str, str]] = [
    ("中国台湾", "中国台湾", "亚洲"),
    ("中台", "中国台湾", "亚洲"),
    ("阿拉伯联合酋长国", "阿联酋", "亚洲"),
    ("阿联酋", "阿联酋", "亚洲"),
    ("哈萨克斯坦", "哈萨克斯坦", "亚洲"),
    ("乌兹别克斯坦", "乌兹别克斯坦", "亚洲"),
    ("印度尼西亚", "印度尼西亚", "亚洲"),
    ("印尼", "印度尼西亚", "亚洲"),
    ("沙特阿拉伯", "沙特阿拉伯", "亚洲"),
    ("沙特", "沙特阿拉伯", "亚洲"),
    ("沙地", "沙特阿拉伯", "亚洲"),
    ("孟加拉国", "孟加拉国", "亚洲"),
    ("阿尔及利亚", "阿尔及利亚", "非洲"),
    ("阿尔巴尼亚", "阿尔巴尼亚", "欧洲"),
    ("波斯尼亚", "波斯尼亚", "欧洲"),
    ("北马其顿", "北马其顿", "欧洲"),
    ("斯洛伐克", "斯洛伐克", "欧洲"),
    ("斯伐", "斯洛伐克", "欧洲"),
    ("罗马尼亚", "罗马尼亚", "欧洲"),
    ("塞尔维亚", "塞尔维亚", "欧洲"),
    ("克罗地亚", "克罗地亚", "欧洲"),
    ("斯洛文尼亚", "斯洛文尼亚", "欧洲"),
    ("匈牙利", "匈牙利", "欧洲"),
    ("塞尔", "塞尔维亚", "欧洲"),
    ("爱沙尼亚", "爱沙尼亚", "欧洲"),
    ("拉脱维亚", "拉脱维亚", "欧洲"),
    ("立陶宛", "立陶宛", "欧洲"),
    ("白俄罗斯", "白俄罗斯", "欧洲"),
    ("阿美尼亚", "亚美尼亚", "欧洲"),
    ("阿塞拜疆", "阿塞拜疆", "欧洲"),
    ("格鲁吉亚", "格鲁吉亚", "欧洲"),
    ("保加利亚", "保加利亚", "欧洲"),
    ("塞浦路斯", "塞浦路斯", "欧洲"),
    ("斯洛伐克", "斯洛伐克", "欧洲"),
    ("北爱尔兰", "北爱尔兰", "欧洲"),
    ("爱尔兰", "爱尔兰", "欧洲"),
    ("苏格兰", "苏格兰", "欧洲"),
    ("英格兰", "英格兰", "欧洲"),
    ("西班牙", "西班牙", "欧洲"),
    ("意大利", "意大利", "欧洲"),
    ("德意志", "德国", "欧洲"),
    ("德国", "德国", "欧洲"),
    ("法国", "法国", "欧洲"),
    ("荷兰", "荷兰", "欧洲"),
    ("葡萄牙", "葡萄牙", "欧洲"),
    ("比利时", "比利时", "欧洲"),
    ("瑞士", "瑞士", "欧洲"),
    ("奥地利", "奥地利", "欧洲"),
    ("波兰", "波兰", "欧洲"),
    ("捷克", "捷克", "欧洲"),
    ("希腊", "希腊", "欧洲"),
    ("土耳其", "土耳其", "欧洲"),
    ("俄罗斯", "俄罗斯", "欧洲"),
    ("乌克兰", "乌克兰", "欧洲"),
    ("瑞典", "瑞典", "欧洲"),
    ("挪威", "挪威", "欧洲"),
    ("丹麦", "丹麦", "欧洲"),
    ("芬兰", "芬兰", "欧洲"),
    ("冰岛", "冰岛", "欧洲"),
    ("马耳他", "马耳他", "欧洲"),
    ("黑山", "黑山", "欧洲"),
    ("以色列", "以色列", "亚洲"),
    ("法罗", "法罗群岛", "欧洲"),
    ("百慕", "百慕大", "北美"),
    ("阿根廷", "阿根廷", "南美"),
    ("巴西", "巴西", "南美"),
    ("乌拉圭", "乌拉圭", "南美"),
    ("秘鲁", "秘鲁", "南美"),
    ("哥伦比亚", "哥伦比亚", "南美"),
    ("巴拉圭", "巴拉圭", "南美"),
    ("委内瑞拉", "委内瑞拉", "南美"),
    ("玻利维亚", "玻利维亚", "南美"),
    ("厄瓜多尔", "厄瓜多尔", "南美"),
    ("智利", "智利", "南美"),
    ("南美", "南美", "南美"),
    ("美国", "美国", "北美"),
    ("加拿大", "加拿大", "北美"),
    ("墨西哥", "墨西哥", "北美"),
    ("哥斯达黎加", "哥斯达黎加", "北美"),
    ("萨尔瓦多", "萨尔瓦多", "北美"),
    ("巴拿马", "巴拿马", "北美"),
    ("洪都", "洪都拉斯", "北美"),
    ("巴马", "巴哈马", "北美"),
    ("加勒比", "国际", "北美"),
    ("CONCACAF", "国际", "北美"),
    ("澳大利亚", "澳大利亚", "大洋洲"),
    ("澳洲", "澳大利亚", "大洋洲"),
    ("新西兰", "新西兰", "大洋洲"),
    ("新西", "新西兰", "大洋洲"),
    ("所罗岛", "所罗门群岛", "大洋洲"),
    ("南韩", "韩国", "亚洲"),
    ("韩国", "韩国", "亚洲"),
    ("日本", "日本", "亚洲"),
    ("中国", "中国", "亚洲"),
    ("香港", "中国香港", "亚洲"),
    ("新加坡", "新加坡", "亚洲"),
    ("马来西亚", "马来西亚", "亚洲"),
    ("泰国", "泰国", "亚洲"),
    ("越南", "越南", "亚洲"),
    ("缅甸", "缅甸", "亚洲"),
    ("柬埔寨", "柬埔寨", "亚洲"),
    ("印度", "印度", "亚洲"),
    ("伊朗", "伊朗", "亚洲"),
    ("伊拉克", "伊拉克", "亚洲"),
    ("卡塔尔", "卡塔尔", "亚洲"),
    ("巴林", "巴林", "亚洲"),
    ("约旦", "约旦", "亚洲"),
    ("科威特", "科威特", "亚洲"),
    ("阿曼", "阿曼", "亚洲"),
    ("叙利亚", "叙利亚", "亚洲"),
    ("黎巴嫩", "黎巴嫩", "亚洲"),
    ("也门", "也门", "亚洲"),
    ("海湾", "国际", "亚洲"),
    ("亚足联", "国际", "亚洲"),
    ("非洲", "国际", "非洲"),
    ("南非", "南非", "非洲"),
    ("埃及", "埃及", "非洲"),
    ("摩洛哥", "摩洛哥", "非洲"),
    ("突尼斯", "突尼斯", "非洲"),
    ("利比亚", "利比亚", "非洲"),
    ("尼日利亚", "尼日利亚", "非洲"),
    ("加纳", "加纳", "非洲"),
    ("喀麦隆", "喀麦隆", "非洲"),
    ("埃塞俄比亚", "埃塞俄比亚", "非洲"),
    ("肯尼", "肯尼亚", "非洲"),
    ("乌干达", "乌干达", "非洲"),
    ("坦桑尼亚", "坦桑尼亚", "非洲"),
    ("赞比亚", "赞比亚", "非洲"),
    ("安哥拉", "安哥拉", "非洲"),
    ("莫桑比克", "莫桑比克", "非洲"),
    ("苏丹", "苏丹", "非洲"),
    ("卢旺达", "卢旺达", "非洲"),
    ("塞内加尔", "塞内加尔", "非洲"),
    ("科特迪瓦", "科特迪瓦", "非洲"),
    ("马里", "马里", "非洲"),
    ("几内亚", "几内亚", "非洲"),
    ("贝宁", "贝宁", "非洲"),
    ("多哥", "多哥", "非洲"),
    ("加蓬", "加蓬", "非洲"),
    ("利比里亚", "利比里亚", "非洲"),
    ("欧洲", "国际", "欧洲"),
    ("欧罗巴", "国际", "欧洲"),
    ("欧足联", "国际", "欧洲"),
    ("欧青", "国际", "欧洲"),
    ("国际", "国际", "国际"),
    ("球会", "国际", "国际"),
    ("世界", "国际", "国际"),
]

# 简称/缩写（名称不是以完整国家名开头时使用）
SHORT_COUNTRY_RULES: list[tuple[str, str, str]] = [
    ("西青", "西班牙", "欧洲"),
    ("西丁", "西班牙", "欧洲"),
    ("西协", "西班牙", "欧洲"),
    ("意青", "意大利", "欧洲"),
    ("意女", "意大利", "欧洲"),
    ("土U", "土耳其", "欧洲"),
    ("希丙", "希腊", "欧洲"),
    ("芬女", "芬兰", "欧洲"),
    ("丹", "丹麦", "欧洲"),
    ("挪", "挪威", "欧洲"),
    ("捷", "捷克", "欧洲"),
    ("匈", "匈牙利", "欧洲"),
    ("以", "以色列", "亚洲"),
    ("爱", "爱沙尼亚", "欧洲"),
    ("斯伐", "斯洛伐克", "欧洲"),
    ("哥斯", "哥斯达黎加", "北美"),
    ("墨西", "墨西哥", "北美"),
    ("乌拉", "乌拉圭", "南美"),
    ("秘鲁", "秘鲁", "南美"),
    ("委内", "委内瑞拉", "南美"),
    ("哥伦", "哥伦比亚", "南美"),
    ("阿根", "阿根廷", "南美"),
    ("巴青", "巴西", "南美"),
    ("阿尔", "阿尔及利亚", "非洲"),
    ("日联", "日本", "亚洲"),
    ("中U", "中国", "亚洲"),
    ("奥丁", "奥地利", "欧洲"),
    ("葡", "葡萄牙", "欧洲"),
    ("波女", "波兰", "欧洲"),
    ("美预备", "美国", "北美"),
    ("江苏", "中国", "亚洲"),
]

S_LEAGUES = {8, 11, 31, 34, 36, 113}
A_LEAGUES = {
    2,
    4,
    9,
    10,
    12,
    15,
    16,
    21,
    25,
    30,
    33,
    37,
    40,
    60,
    89,
    140,
    292,
    2187,
}


def classify_league(league_id: int, name: str) -> dict[str, Any]:
    name = name or ""
    country, region = _country(name)
    audience = _audience(name)
    ctype = _type(name)
    tier = _tier(name) if ctype == "league" else 0
    priority = _priority(league_id, name, ctype, audience, tier)
    return {
        "league_id": league_id,
        "name": name,
        "region": region,
        "country": country,
        "type": ctype,
        "audience": audience,
        "tier": tier,
        "priority": priority,
        "tags": _tags(name, ctype),
        "source": "auto",
    }


def _country(name: str) -> tuple[str, str]:
    country, region = "未知", "未知"
    for keyword, c, r in COUNTRY_RULES:
        if name.startswith(keyword):
            country, region = c, r
            break
    else:
        for keyword, c, r in SHORT_COUNTRY_RULES:
            if name.startswith(keyword):
                country, region = c, r
                break
        else:
            for keyword, c, r in COUNTRY_RULES:
                if keyword in name:
                    country, region = c, r
                    break
    if any(k in name for k in ("解放者", "世界杯", "欧足联", "亚足联")):
        country = "国际"
    return country, region


def _audience(name: str) -> str:
    youth = bool(re.search(r"U\d{2}", name)) or "青年" in name or "青" in name
    women = "女" in name
    reserve = "后备" in name or "预备" in name
    if women and youth:
        return "women_youth"
    if women:
        return "women"
    if youth:
        return "youth"
    if reserve:
        return "reserve"
    return "men"


def _type(name: str) -> str:
    if "友谊" in name:
        return "friendly"
    if "超级杯" in name or "超级盃" in name:
        return "super_cup"
    if "预选" in name or "资格" in name or "外围" in name or "附加赛" in name:
        return "qualifier"
    if "杯" in name or "盃" in name:
        return "cup"
    if "锦标" in name or name.endswith("锦"):
        return "tournament"
    if "冠军" in name and ("联赛" not in name):
        return "tournament"
    return "league"


def _tier(name: str) -> int:
    if "丁" in name or "戊" in name:
        return 4
    if "丙" in name:
        return 3
    if "乙" in name or "冠军联赛" in name or "K2" in name or "J2" in name:
        return 2
    if "皇家足协甲级" in name:
        return 3
    if "皇家足协乙级" in name:
        return 4
    if any(
        k in name
        for k in ("超级联赛", "甲级", "甲组", "J1", "K联赛", "职业大联盟", "职业联赛", "明星联赛")
    ):
        return 1
    if any(k in name for k in ("地区联赛", "业余", "议会", "城市联赛", "足球联赛", "全联", "超联")):
        return 4
    return 0


def _priority(league_id: int, name: str, ctype: str, audience: str, tier: int) -> str:
    if league_id in S_LEAGUES:
        return "S"
    if league_id in A_LEAGUES:
        return "A"
    if audience != "men":
        return "C"
    if ctype != "league":
        return "C"
    if tier in (1, 2):
        return "B"
    return "C"


def _tags(name: str, ctype: str) -> list[str]:
    tags = []
    if "女子" in name or "女" in name:
        tags.append("女子")
    if re.search(r"U\d{2}", name) or "青年" in name:
        tags.append("青年")
    if "后备" in name or "预备" in name:
        tags.append("预备队")
    if ctype == "cup":
        tags.append("淘汰赛")
    if "解放者" in name:
        tags.append("洲际")
    if "欧" in name:
        tags.append("欧战")
    return tags


def build(conn) -> list[dict[str, Any]]:
    return [
        classify_league(r["league_id"], r["name_simplified"])
        for r in conn.execute("SELECT league_id, name_simplified FROM leagues ORDER BY league_id")
    ]


def write_json(path: str, entries: list[dict[str, Any]]) -> None:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "entries": entries,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def import_json(conn, path: str) -> int:
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    entries = payload.get("entries", payload if isinstance(payload, list) else [])
    rows = [
        (
            e["league_id"],
            e.get("region"),
            e.get("country"),
            e.get("type"),
            e.get("audience"),
            e.get("tier"),
            e.get("priority"),
            json.dumps(e.get("tags") or [], ensure_ascii=False),
            e.get("source") or "auto",
            datetime.now().isoformat(timespec="seconds"),
        )
        for e in entries
    ]
    conn.executemany(
        """INSERT INTO league_categories
           (league_id,region,country,type,audience,tier,priority,tags_json,source,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(league_id) DO UPDATE SET
             region=excluded.region, country=excluded.country, type=excluded.type,
             audience=excluded.audience, tier=excluded.tier, priority=excluded.priority,
             tags_json=excluded.tags_json, source=excluded.source,
             updated_at=excluded.updated_at""",
        rows,
    )
    conn.commit()
    return len(rows)
