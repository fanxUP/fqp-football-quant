"""比赛球场解析器。

官方中立场地备注优先于主队球场；普通主客场比赛再从球队球场历史中解析。
天气采集与特征快照共用这一规则，避免两套映射漂移。
"""

from __future__ import annotations

from typing import Any, TypedDict


class StadiumLocation(TypedDict):
    stadium_id: int
    latitude: float
    longitude: float
    source: str


VENUE_CITY_ALIASES = {
    "英格尔伍德": "Inglewood",
    "迈阿密加登斯": "Miami Gardens",
    "堪萨斯城": "Kansas City",
    "东拉瑟福德": "East Rutherford",
}


def _official_venue_city(raw_json: dict[str, Any] | None) -> str | None:
    remark = str((raw_json or {}).get("remark") or "")
    return next(
        (city for venue_name, city in VENUE_CITY_ALIASES.items() if venue_name in remark),
        None,
    )


def resolve_match_stadium_location(
    conn: Any,
    raw_json: dict[str, Any] | None,
    home_team_name: str | None,
) -> StadiumLocation | None:
    """解析比赛球场及坐标。

    官方备注一旦命中中立城市，即不再回退到主队球场，
    以免世界杯等中立场赛事使用错误位置。
    """
    venue_city = _official_venue_city(raw_json)
    if venue_city:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, latitude, longitude
                FROM stadiums
                WHERE city ILIKE %s
                  AND latitude IS NOT NULL
                  AND longitude IS NOT NULL
                ORDER BY data_confidence DESC NULLS LAST, id
                LIMIT 1
                """,
                (venue_city,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "stadium_id": int(row[0]),
            "latitude": float(row[1]),
            "longitude": float(row[2]),
            "source": "official_venue_remark",
        }

    if not home_team_name:
        return None

    with conn.cursor() as cur:
        cur.execute(
            """
            WITH matched_team AS (
                SELECT t.id, t.primary_stadium_id
                FROM teams t
                JOIN team_aliases ta ON ta.team_id = t.id
                WHERE ta.source_name = 'sporttery'
                  AND ta.alias_name = %s
                LIMIT 1
            ), candidates AS (
                SELECT tsh.stadium_id, 0 AS priority,
                       tsh.is_primary, tsh.start_date
                FROM matched_team mt
                JOIN team_stadium_history tsh ON tsh.team_id = mt.id
                WHERE tsh.end_date IS NULL OR tsh.end_date >= CURRENT_DATE
                UNION ALL
                SELECT mt.primary_stadium_id, 1, true, NULL::date
                FROM matched_team mt
                WHERE mt.primary_stadium_id IS NOT NULL
            )
            SELECT s.id, s.latitude, s.longitude
            FROM candidates c
            JOIN stadiums s ON s.id = c.stadium_id
            WHERE s.latitude IS NOT NULL AND s.longitude IS NOT NULL
            ORDER BY c.priority, c.is_primary DESC, c.start_date DESC NULLS LAST, s.id
            LIMIT 1
            """,
            (home_team_name,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return {
        "stadium_id": int(row[0]),
        "latitude": float(row[1]),
        "longitude": float(row[2]),
        "source": "home_team_stadium",
    }
