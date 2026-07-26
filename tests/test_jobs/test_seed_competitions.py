from scripts.jobs.seed_competitions import LEAGUE_MAP
from scripts.jobs.seed_official_team_aliases import ALIASES as OFFICIAL_STANDINGS_ALIASES
from scripts.jobs.seed_team_aliases import MANUAL_ALIASES


def test_current_competitions_have_verified_team_counts():
    counts = {item["competition_name_cn"]: item["total_teams"] for item in LEAGUE_MAP}
    assert counts == {
        "巴西甲级联赛": 20,
        "欧洲冠军联赛": 36,
        "美国职业大联盟": 30,
        "挪威超级联赛": 16,
        "芬兰超级联赛": 12,
        "瑞典超级联赛": 16,
        "韩国职业联赛": 12,
        "世界杯": 48,
    }


def test_api_football_competitions_use_independent_season_codes():
    season_codes = [item["season_code"] for item in LEAGUE_MAP]

    assert len(season_codes) == len(set(season_codes))
    assert season_codes == [f"apifootball:{item['api_league_id']}:2026" for item in LEAGUE_MAP]


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


def test_recent_brazil_champions_league_and_mls_teams_have_provider_aliases():
    required = {
        "米内罗竞技": "Atletico-MG",
        "巴伊亚": "Bahia",
        "萨巴赫": "Sabah FA",
        "库奥皮奥": "KuPS",
        "奥胡斯": "Aarhus",
        "波兹南莱赫": "Lech Poznan",
        "格拉茨风暴": "Sturm Graz",
        "哈茨": "Heart Of Midlothian",
        "奥莫尼亚": "Omonia Nicosia",
        "阿拉木图凯拉特": "Kairat Almaty",
        "圣保罗": "Sao Paulo",
        "巴拉纳竞技": "Atletico Paranaense",
        "沙佩科恩斯": "Chapecoense-sc",
        "弗拉门戈": "Flamengo",
        "迈阿密国际": "Inter Miami",
        "芝加哥火焰": "Chicago Fire",
        "洛杉矶FC": "Los Angeles FC",
        "皇家盐湖城": "Real Salt Lake",
    }

    for chinese_name, provider_name in required.items():
        assert provider_name in MANUAL_ALIASES[chinese_name]


def test_current_selling_card_has_verified_api_football_aliases():
    required = {
        "布鲁马波卡纳": "IF Brommapojkarna",
        "IFK哥德堡": "IFK Goteborg",
        "赫尔辛基火花": "Gnistan",
        "布兰": "Brann",
        "瓦勒伦加": "Valerenga",
        "赫尔辛基": "HJK Helsinki",
        "哥德堡盖斯": "Gais",
        "萨尔普斯堡": "Sarpsborg 08 FF",
        "汉坎": "Ham-Kam",
        "奥斯陆KFUM": "KFUM Oslo",
        "莫尔德": "Molde",
        "桑纳菲尤尔": "Sandefjord",
        "博德闪耀": "Bodo/Glimt",
        "奥勒松": "Aalesund",
        "维京": "Viking",
        "格雷米奥": "Gremio",
        "弗鲁米嫩塞": "Fluminense",
        "罗森博格": "Rosenborg",
        "腓特烈斯塔": "Fredrikstad",
    }

    for chinese_name, provider_name in required.items():
        assert provider_name in MANUAL_ALIASES[chinese_name]


def test_official_standings_aliases_reuse_current_sporttery_team_identity():
    finland = OFFICIAL_STANDINGS_ALIASES["芬兰超级联赛"]

    assert finland["赫尔辛基火花"] == "IF Gnistan"
    assert finland["坦佩雷山猫"] == "Ilves"
    assert finland["赫尔辛基"] == "HJK"
