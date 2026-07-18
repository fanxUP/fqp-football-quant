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
