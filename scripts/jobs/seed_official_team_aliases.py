"""Seed verified official standings names for teams already in the local match pool."""

from __future__ import annotations

import re

from apps.backend.src.db import get_db

ALIASES = {
    "挪威超级联赛": {
        "奥勒松": "Aalesund", "布兰": "Brann", "桑纳菲尤尔": "Sandefjord",
        "罗森博格": "Rosenborg", "腓特烈斯塔": "Fredrikstad", "维京": "Viking",
        "汉坎": "HamKam", "莫尔德": "Molde", "斯达": "Start",
        "克里斯蒂安松": "Kristiansund", "特罗姆瑟": "Tromsø",
        "博德闪耀": "Bodø/Glimt", "利勒斯特罗姆": "Lillestrøm",
        "萨尔普斯堡": "Sarpsborg", "瓦勒伦加": "Vålerenga", "奥斯陆KFUM": "KFUM",
    },
    "芬兰超级联赛": {
        "拉赫蒂": "FC Lahti", "瓦萨": "VPS", "赫尔辛基火花": "HJK",
        "TPS图尔库": "TPS", "古比斯": "KuPS", "国际图尔库": "FC Inter",
        "AC奥卢": "AC Oulu", "格尼斯坦": "IF Gnistan", "伊尔维斯": "Ilves",
        "塞伊奈约基": "SJK", "雅罗": "FF Jaro", "玛丽港": "IFK Mariehamn",
    },
    "韩国职业联赛": {
        "首尔FC": "서울", "蔚山现代": "울산", "江原FC": "강원", "全北现代": "전북",
        "浦项制铁": "포항", "仁川联": "인천", "安养FC": "안양", "济州SK": "제주",
        "富川FC": "부천", "大田市民": "대전", "金泉尚武": "김천", "光州FC": "광주",
    },
}


def run() -> dict[str, int | str]:
    inserted = 0
    unresolved = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for team_cn, official_name in [
                (cn, name) for league in ALIASES.values() for cn, name in league.items()
            ]:
                cur.execute("SELECT id FROM teams WHERE team_name_cn = %s", (team_cn,))
                row = cur.fetchone()
                if not row:
                    # Official standings may contain a team not yet present in
                    # the current Sporttery match window. Keep its official
                    # name as the canonical label; do not invent a Chinese
                    # translation.
                    code = re.sub(r"[^A-Za-z0-9]+", "", official_name).upper()[:32] or official_name[:32]
                    country = "South Korea" if official_name in {
                        "서울", "울산", "강원", "전북", "포항", "인천", "안양", "제주", "부천", "대전", "김천", "광주",
                    } else "Finland" if official_name in {
                        "KuPS", "FC Inter", "AC Oulu", "IF Gnistan", "VPS", "HJK",
                        "TPS", "FC Lahti", "Ilves", "SJK", "FF Jaro", "IFK Mariehamn",
                    } else "Norway"
                    cur.execute(
                        """
                        INSERT INTO teams (team_code, team_name_cn, team_name_en, short_name, country)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (team_code) DO UPDATE SET team_name_en=EXCLUDED.team_name_en
                        RETURNING id
                        """,
                        (code, official_name, official_name, official_name[:32], country),
                    )
                    row = cur.fetchone()
                    if not row:
                        unresolved += 1
                        continue
                cur.execute(
                    """
                    INSERT INTO team_aliases (team_id, source_name, alias_name, language, confidence, is_verified)
                    VALUES (%s, 'official_standings', %s, 'en', 0.95, true)
                    ON CONFLICT (source_name, alias_name) DO NOTHING
                    RETURNING id
                    """,
                    (row[0], official_name),
                )
                if cur.fetchone():
                    inserted += 1
        conn.commit()
    return {"status": "ok", "aliases_inserted": inserted, "unresolved": unresolved}


if __name__ == "__main__":
    print(run())
