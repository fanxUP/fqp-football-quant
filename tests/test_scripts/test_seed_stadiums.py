from scripts.seed_stadiums import STADIUMS, TEAM_STADIUM_NAMES


def test_current_official_match_home_teams_have_exact_stadium_mappings():
    expected = {
        "布鲁马波卡纳": "Grimsta IP",
        "天狼星": "Studenternas IP",
        "国际图尔库": "Veritas Stadion",
        "坦佩雷山猫": "Tammelan Stadion",
        "布兰": "Brann stadion",
        "赫尔辛基": "Bolt Arena",
        "哥德堡盖斯": "Gamla Ullevi",
        "马尔默": "Eleda Stadion",
        "萨尔普斯堡": "Sarpsborg st KG",
        "奥斯陆KFUM": "KFUM-Arena",
        "桑纳菲尤尔": "Jotun Arena",
        "奥勒松": "Color Line Stadion",
        "弗拉门戈": "Maracana",
        "格雷米奥": "Arena do Grêmio",
        "赫根": "Bravida Arena",
        "罗森博格": "Lerkendal stadion",
        "博德闪耀": "Aspmyra stadion",
        "汉坎": "Briskeby",
        "瓦勒伦加": "Intility Arena",
        "腓特烈斯塔": "Fredrikstad stadion",
        "赫尔辛基火花": "Mustapekka Areena",
        "AIK索尔纳": "Strawberry Arena",
        "圣保罗": "MorumBIS",
        "弗鲁米嫩塞": "Maracana",
        "拉赫蒂": "Lahden Stadion",
        "IFK哥德堡": "Gamla Ullevi",
    }

    assert {team: TEAM_STADIUM_NAMES.get(team) for team in expected} == expected
    stadium_names = {row[0] for row in STADIUMS}
    assert set(expected.values()) <= stadium_names
