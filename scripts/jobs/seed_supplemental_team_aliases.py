"""Map verified 500.com team-name variants to existing team records."""

from __future__ import annotations

import re

from apps.backend.src.db import get_db

ALIASES = {
    "瑞典超级联赛": {
        "瓦斯特拉斯": "韦斯特罗斯",
        "哈尔姆": "哈尔姆斯塔德",
        "哥德堡": "IFK哥德堡",
        "奥尔格里特": "厄尔格里特",
    },
    "芬兰超级联赛": {
        "查路": "FF Jaro",
        "格尼斯坦": "IF Gnistan",
        "库普斯": "KuPS",
        "国际图尔库": "FC Inter",
        "埃尔维斯": "Ilves",
        "塞那乔恩": "塞伊奈约基",
        "TPS土尔库": "TPS图尔库",
        "赫尔辛基": "赫尔辛基火花",
    },
    "韩国职业联赛": {
        "济州联队": "济州SK",
        "仁川联合": "仁川联",
    },
}

LEAGUE_COUNTRIES = {
    "挪威超级联赛": "Norway",
    "瑞典超级联赛": "Sweden",
    "芬兰超级联赛": "Finland",
    "韩国职业联赛": "South Korea",
    "世界杯": "International",
}


def run() -> dict[str, int | str]:
    inserted = 0
    source_teams_created = 0
    unresolved = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for variants in ALIASES.values():
                for alias_name, canonical_name in variants.items():
                    cur.execute("SELECT id FROM teams WHERE team_name_cn=%s", (canonical_name,))
                    team = cur.fetchone()
                    if not team:
                        unresolved += 1
                        continue
                    cur.execute(
                        """
                        INSERT INTO team_aliases
                            (team_id, source_name, alias_name, language, confidence, is_verified)
                        VALUES (%s, '500.com', %s, 'zh', 0.95, true)
                        ON CONFLICT (source_name, alias_name) DO NOTHING
                        RETURNING id
                        """,
                        (team[0], alias_name),
                    )
                    if cur.fetchone():
                        inserted += 1
            cur.execute(
                """
                SELECT DISTINCT sm.league_name, v.team_name
                FROM supplemental_matches sm
                CROSS JOIN LATERAL (VALUES (sm.home_team_name), (sm.away_team_name)) v(team_name)
                WHERE sm.source_name='500.com'
                """
            )
            for league_name, team_name in cur.fetchall():
                cur.execute("SELECT id FROM teams WHERE team_name_cn=%s", (team_name,))
                team = cur.fetchone()
                if not team:
                    prefix = "NAT-" if league_name == "世界杯" else "500-"
                    code = prefix + (re.sub(r"[^A-Za-z0-9]+", "", team_name) or team_name)[:28]
                    cur.execute(
                        """
                        INSERT INTO teams (team_code, team_name_cn, team_name_en, short_name, country)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (team_code) DO UPDATE SET team_name_cn=EXCLUDED.team_name_cn
                        RETURNING id
                        """,
                        (code, team_name, team_name, team_name[:32], LEAGUE_COUNTRIES[league_name]),
                    )
                    team = cur.fetchone()
                    if team:
                        source_teams_created += 1
                if team:
                    cur.execute(
                        """
                        INSERT INTO team_aliases
                            (team_id, source_name, alias_name, language, confidence, is_verified)
                        VALUES (%s, '500.com', %s, 'zh', 0.90, true)
                        ON CONFLICT (source_name, alias_name) DO NOTHING
                        RETURNING id
                        """,
                        (team[0], team_name),
                    )
                    if cur.fetchone():
                        inserted += 1
                else:
                    unresolved += 1
        conn.commit()
    return {"status": "ok", "aliases_inserted": inserted,
            "source_teams_created": source_teams_created,
            "unresolved": unresolved}


if __name__ == "__main__":
    print(run())
