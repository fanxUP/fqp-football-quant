from scripts.jobs.seed_competitions import LEAGUE_MAP
from scripts.jobs.seed_team_aliases import MANUAL_ALIASES


def test_current_competitions_have_verified_team_counts():
    counts = {item["competition_name_cn"]: item["total_teams"] for item in LEAGUE_MAP}
    assert counts == {
        "挪威超级联赛": 16,
        "芬兰超级联赛": 12,
        "瑞典超级联赛": 16,
        "韩国职业联赛": 12,
        "世界杯": 48,
    }


def test_api_football_competitions_use_independent_season_codes():
    season_codes = [item["season_code"] for item in LEAGUE_MAP]

    assert len(season_codes) == len(set(season_codes))
    assert season_codes == [
        f"apifootball:{item['api_league_id']}:2026" for item in LEAGUE_MAP
    ]


def test_current_selling_teams_have_api_football_aliases():
    required = {
        "英格兰",
        "首尔FC",
        "埃尔夫斯堡",
        "哈尔姆斯塔德",
        "赫根",
        "哈马比",
        "代格福什",
        "雅罗",
        "国际图尔库",
        "TPS图尔库",
        "坦佩雷山猫",
        "玛丽港",
        "拉赫蒂",
        "卡尔马",
        "马尔默",
        "厄尔格里特",
        "佐加顿斯",
    }

    assert required <= MANUAL_ALIASES.keys()


def test_current_k_league_teams_have_provider_aliases():
    assert "Gimcheon Sangmu FC" in MANUAL_ALIASES["金泉尚武"]
    assert "Incheon United" in MANUAL_ALIASES["仁川联"]
    assert "Jeju United FC" in MANUAL_ALIASES["济州SK"]
