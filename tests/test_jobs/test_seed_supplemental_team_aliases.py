from scripts.jobs.seed_supplemental_team_aliases import ALIASES, LEAGUE_COUNTRIES


def test_verified_supplemental_aliases_are_scoped_to_known_leagues():
    assert set(ALIASES) == {"瑞典超级联赛", "芬兰超级联赛", "韩国职业联赛"}
    assert ALIASES["韩国职业联赛"]["仁川联合"] == "仁川联"
    assert ALIASES["芬兰超级联赛"]["库普斯"] == "KuPS"
    assert LEAGUE_COUNTRIES["挪威超级联赛"] == "Norway"
