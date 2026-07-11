from scripts.jobs.run_feature_snapshot_build import can_build_team_dependent_features


def test_team_enrichment_requires_both_internal_team_ids():
    assert can_build_team_dependent_features(1, 2) is True
    assert can_build_team_dependent_features(None, 2) is False
    assert can_build_team_dependent_features(1, None) is False
    assert can_build_team_dependent_features(None, None) is False
