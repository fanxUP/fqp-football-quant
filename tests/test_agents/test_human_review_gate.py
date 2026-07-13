import pytest

from scripts.agents.human_review_gate import assert_recommendation_publishable


def test_recommendation_publish_requires_approval():
    with pytest.raises(PermissionError):
        assert_recommendation_publishable(None)
    with pytest.raises(PermissionError):
        assert_recommendation_publishable("pending")


def test_approved_recommendation_can_cross_publish_boundary():
    assert assert_recommendation_publishable("approved") is None
