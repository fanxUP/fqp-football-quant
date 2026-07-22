from scripts.five100_client import _select_official_match


def test_selects_unique_kickoff_candidate_when_one_team_name_is_exact():
    candidates = [(1216, "杰尔", "雷克雅未克维京人")]

    assert _select_official_match("杰尔", "维京古尔", candidates) == 1216


def test_selects_unique_kickoff_candidate_for_conservative_translation_similarity():
    candidates = [(1219, "比森阿泰尔", "克拉克斯维克")]

    assert _select_official_match("阿特比森", "克拉斯维克", candidates) == 1219


def test_rejects_unrelated_or_ambiguous_kickoff_candidates():
    assert _select_official_match("主队", "客队", [(1, "其他主队", "其他客队")]) is None
    assert (
        _select_official_match(
            "杰尔",
            "维京古尔",
            [
                (1, "杰尔", "雷克雅未克维京人"),
                (2, "杰尔", "维京人"),
            ],
        )
        is None
    )
