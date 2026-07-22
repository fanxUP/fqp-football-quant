"""Seed team aliases from API-Football and manual mappings.

Adds English team names as aliases so enrichment scripts can match
API-Football's data to our internal team IDs.
"""

from __future__ import annotations

from typing import Any

from apps.backend.src.db import get_db

# ── Manual mapping: Chinese name → API-Football English name ──
# These are derived from comparing our official_matches data against
# API-Football /teams responses.
MANUAL_ALIASES: dict[str, list[str]] = {
    # 巴西甲级联赛 (Serie A)
    "米内罗竞技": ["Atletico-MG"],
    "巴伊亚": ["Bahia"],
    "圣保罗": ["Sao Paulo"],
    "巴拉纳竞技": ["Atletico Paranaense"],
    "沙佩科恩斯": ["Chapecoense-sc"],
    "弗拉门戈": ["Flamengo"],
    # 欧洲冠军联赛 (UEFA Champions League)
    "萨巴赫": ["Sabah FA"],
    "库奥皮奥": ["KuPS"],
    "奥胡斯": ["Aarhus"],
    "波兹南莱赫": ["Lech Poznan"],
    "格拉茨风暴": ["Sturm Graz"],
    "哈茨": ["Heart Of Midlothian"],
    "奥莫尼亚": ["Omonia Nicosia"],
    "阿拉木图凯拉特": ["Kairat Almaty"],
    # 美国职业大联盟 (Major League Soccer)
    "迈阿密国际": ["Inter Miami"],
    "芝加哥火焰": ["Chicago Fire"],
    "洛杉矶FC": ["Los Angeles FC"],
    "皇家盐湖城": ["Real Salt Lake"],
    # 瑞典超级联赛 (Allsvenskan)
    "天狼星": ["Sirius", "IK Sirius"],
    "米亚尔比": ["Mjallby AIF", "Mjällby AIF"],
    "埃尔夫斯堡": ["IF Elfsborg", "Elfsborg"],
    "哈尔姆斯塔德": ["Halmstad", "Halmstads BK"],
    "赫根": ["BK Hacken", "BK Häcken"],
    "哈马比": ["Hammarby FF", "Hammarby"],
    "代格福什": ["Degerfors IF", "Degerfors"],
    "卡尔马": ["Kalmar FF", "Kalmar"],
    "马尔默": ["Malmo FF", "Malmö FF"],
    "厄尔格里特": ["Orgryte IS", "Örgryte IS"],
    "佐加顿斯": ["Djurgardens IF", "Djurgårdens IF"],
    # 芬兰超级联赛 (Veikkausliiga)
    "雅罗": ["FF Jaro"],
    "国际图尔库": ["Inter Turku", "FC Inter Turku"],
    "TPS图尔库": ["Turku PS", "TPS"],
    "坦佩雷山猫": ["Ilves Tampere", "Ilves"],
    "玛丽港": ["IFK Mariehamn", "Mariehamn"],
    "拉赫蒂": ["FC Lahti", "Lahti"],
    # 韩国职业联赛 (K League 1)
    "大田市民": ["Daejeon Citizen", "Daejeon Hana Citizen"],
    "富川FC": ["Bucheon FC", "Bucheon FC 1995"],
    "安养FC": ["FC Anyang"],
    "浦项制铁": ["Pohang Steelers"],
    "全北现代": ["Jeonbuk Motors", "Jeonbuk Hyundai Motors"],
    "江原FC": ["Gangwon FC"],
    "光州FC": ["Gwangju FC"],
    "金泉尚武": ["Gimcheon Sangmu FC"],
    "首尔FC": ["FC Seoul"],
    "蔚山现代": ["Ulsan Hyundai FC", "Ulsan HD FC"],
    "仁川联": ["Incheon United"],
    "济州SK": ["Jeju United FC"],
    # 世界杯 (World Cup) — national teams
    "澳大利亚": ["Australia"],
    "埃及": ["Egypt"],
    "阿根廷": ["Argentina"],
    "佛得角": ["Cape Verde", "Cape Verde Islands"],
    "哥伦比亚": ["Colombia"],
    "加纳": ["Ghana"],
    "加拿大": ["Canada"],
    "摩洛哥": ["Morocco"],
    "巴拉圭": ["Paraguay"],
    "法国": ["France"],
    "英格兰": ["England"],
    "西班牙": ["Spain"],
    "奥地利": ["Austria"],
    "美国": ["United States", "USA"],
    "塞内加尔": ["Senegal"],
    "克罗地亚": ["Croatia"],
    "波黑": ["Bosnia and Herzegovina", "Bosnia"],
    "瑞士": ["Switzerland"],
    "比利时": ["Belgium"],
    "阿尔及利亚": ["Algeria"],
    "葡萄牙": ["Portugal"],
}


def run(dry_run: bool = False) -> dict[str, Any]:
    """Add API-Football English names as team aliases.

    Uses manual mapping table above. Safe to re-run (ON CONFLICT DO NOTHING).

    Returns:
        Summary dict.
    """
    aliases_added = 0
    teams_matched = 0

    with get_db() as conn:
        for cn_name, en_names in MANUAL_ALIASES.items():
            # Find internal team by Chinese name
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.id, t.team_name_cn
                    FROM teams t
                    JOIN team_aliases ta ON ta.team_id = t.id
                    WHERE ta.alias_name = %(cn)s
                      AND ta.source_name = 'sporttery'
                    LIMIT 1
                    """,
                    {"cn": cn_name},
                )
                row = cur.fetchone()

            if not row:
                print(f"[seed_aliases] WARNING: no internal team for '{cn_name}', skipping")
                continue

            team_id = row[0]
            teams_matched += 1

            # Add each English alias
            for en_name in en_names:
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO team_aliases (team_id, source_name, alias_name, language)
                            VALUES (%(tid)s, 'apifootball', %(alias)s, 'en')
                            ON CONFLICT (source_name, alias_name) DO NOTHING
                            RETURNING id
                            """,
                            {"tid": team_id, "alias": en_name},
                        )
                        if cur.fetchone():
                            aliases_added += 1
                except Exception as e:
                    print(f"[seed_aliases] error adding '{en_name}' for '{cn_name}': {e}")

        if not dry_run:
            conn.commit()

    return {
        "status": "ok" if not dry_run else "dry_run",
        "teams_matched": teams_matched,
        "aliases_added": aliases_added,
    }


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
