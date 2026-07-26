from scripts.team_registry import official_team_code


def test_official_team_code_is_stable_and_does_not_collide_on_shared_prefix():
    slovakia = official_team_code("斯洛伐克")
    slovakia_u21 = official_team_code("斯洛伐克U21")

    assert slovakia.startswith("sporttery-team:")
    assert slovakia == official_team_code("斯洛伐克")
    assert slovakia != slovakia_u21
    assert len(slovakia) <= 64
