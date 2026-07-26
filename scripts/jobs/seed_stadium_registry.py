"""补齐球队、球场及两者的关联基础数据。"""

from __future__ import annotations

from typing import Any


def run() -> dict[str, Any]:
    """先从官方比赛补齐球队，再幂等写入球场映射。"""
    from scripts.features.populate_teams_leagues import populate_all
    from scripts.seed_stadiums import run as seed_stadiums

    team_result = populate_all()
    stadium_result = seed_stadiums()
    return {
        "status": stadium_result.get("status", "ok"),
        "teams": team_result,
        "stadiums": stadium_result,
    }


if __name__ == "__main__":
    print(run())
