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
    # 瑞典超级联赛 (Allsvenskan)
    "天狼星": ["Sirius", "IK Sirius"],
    "米亚尔比": ["Mjallby AIF", "Mjällby AIF"],
    # 韩国职业联赛 (K League 1)
    "大田市民": ["Daejeon Citizen", "Daejeon Hana Citizen"],
    "富川FC": ["Bucheon FC", "Bucheon FC 1995"],
    "安养FC": ["FC Anyang"],
    "浦项制铁": ["Pohang Steelers"],
    "全北现代": ["Jeonbuk Motors", "Jeonbuk Hyundai Motors"],
    "江原FC": ["Gangwon FC"],
    "光州FC": ["Gwangju FC"],
    "蔚山现代": ["Ulsan Hyundai FC", "Ulsan HD FC"],
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
