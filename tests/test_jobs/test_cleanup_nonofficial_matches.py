from scripts.jobs.cleanup_nonofficial_matches import (
    DELETE_STEPS,
    official_identity_is_valid,
)


def test_official_identity_requires_ticket_code_and_sporttery_match_id():
    assert official_identity_is_valid("周一201", "2040374", None) is True
    assert official_identity_is_valid("500-1363847", None, "500.com") is False
    assert official_identity_is_valid("7213", "2040374", None) is False
    assert official_identity_is_valid("周一201", None, None) is False
    assert official_identity_is_valid("周一201", "2040374", "500.com") is False


def test_cleanup_deletes_children_before_matches_and_clears_supplemental_rows():
    names = [name for name, _sql in DELETE_STEPS]

    assert names.index("simulation_ticket_items") < names.index("model_predictions")
    assert names.index("model_predictions") < names.index("official_odds_snapshots")
    assert names.index("official_odds_snapshots") < names.index("official_markets")
    assert names[-2:] == ["official_matches", "supplemental_matches"]
