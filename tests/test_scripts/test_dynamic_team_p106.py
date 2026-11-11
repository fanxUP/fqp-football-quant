from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from scripts.dynamic_team_challenger import SeasonMatchContext
from scripts.dynamic_team_p106 import (
    _require_isolated_research_database,
    project_p106_manifest_to_season,
)
from scripts.model_artifact_identity import (
    canonical_json_bytes,
    training_manifest_sha256,
)
from scripts.training_manifest import (
    CandidateMatch,
    ResultLabelObservation,
    build_training_dataset,
)

FIT_CUTOFF = datetime(2026, 3, 1, 0, 0)
SHANGHAI = ZoneInfo("Asia/Shanghai")
MEMBERSHIP_SHA = "a" * 64
VENUE_SHA = "b" * 64


def _parent_dataset():
    pairs = ((1, 2), (3, 4), (1, 3), (2, 4), (1, 4), (2, 3))
    candidates = []
    for index, (home, away) in enumerate(pairs, start=1):
        kickoff = datetime(2026, 1, 1, 18) + timedelta(days=index)
        published = kickoff + timedelta(hours=3)
        published_aware = published.replace(tzinfo=SHANGHAI).astimezone(UTC)
        candidates.append(
            CandidateMatch(
                match_id=100 + index,
                result_id=200 + index,
                kickoff_at=kickoff,
                home_team_id=home,
                away_team_id=away,
                home_goals=index % 4,
                away_goals=(index + 1) % 3,
                match_status="settled",
                official_publish_time=published,
                label_observations=(
                    ResultLabelObservation(
                        revision_id=300 + index,
                        result_id=200 + index,
                        fact_status="value",
                        home_goals=index % 4,
                        away_goals=(index + 1) % 3,
                        published_at=published_aware,
                        first_acquired_at=published_aware + timedelta(minutes=5),
                        available_at=published_aware + timedelta(minutes=10),
                    ),
                ),
            )
        )
    excluded_kickoff = datetime(2026, 2, 1, 18)
    excluded_published = excluded_kickoff + timedelta(hours=3)
    excluded_published_aware = excluded_published.replace(tzinfo=SHANGHAI).astimezone(UTC)
    candidates.append(
        CandidateMatch(
            match_id=999,
            result_id=299,
            kickoff_at=excluded_kickoff,
            home_team_id=None,
            away_team_id=2,
            home_goals=1,
            away_goals=0,
            match_status="settled",
            official_publish_time=excluded_published,
            label_observations=(
                ResultLabelObservation(
                    revision_id=399,
                    result_id=299,
                    fact_status="value",
                    home_goals=1,
                    away_goals=0,
                    published_at=excluded_published_aware,
                    first_acquired_at=excluded_published_aware + timedelta(minutes=5),
                    available_at=excluded_published_aware + timedelta(minutes=10),
                ),
            ),
        )
    )
    return build_training_dataset(candidates, min_matches=1, cutoff_at=FIT_CUTOFF)


def _context(
    season_id: int = 20262027,
    *,
    available_at: datetime = FIT_CUTOFF - timedelta(days=1),
):
    return SeasonMatchContext(
        competition_id=77,
        competition_season_id=season_id,
        neutral_venue=False,
        season_membership_evidence_sha256=MEMBERSHIP_SHA,
        season_membership_available_at=available_at,
        venue_evidence_sha256=VENUE_SHA,
        venue_evidence_available_at=FIT_CUTOFF - timedelta(days=1),
    )


def test_projection_accounts_for_every_parent_sample_and_preserves_p106_labels():
    parent = _parent_dataset().manifest.to_dict()
    included_ids = [row["match_id"] for row in parent["included"]]
    contexts = {
        included_ids[0]: _context(),
        included_ids[1]: _context(),
        included_ids[2]: _context(),
        included_ids[3]: _context(20252026),
        included_ids[4]: _context(available_at=FIT_CUTOFF + timedelta(seconds=1)),
        included_ids[5]: None,
    }

    projection = project_p106_manifest_to_season(
        parent,
        contexts,
        competition_id=77,
        competition_season_id=20262027,
    )

    derived = projection.manifest
    assert [row["match_id"] for row in derived["included"]] == included_ids[:3]
    assert [row["ordinal"] for row in derived["included"]] == [0, 1, 2]
    assert derived["selection_version"] == parent["selection_version"]
    assert derived["minimum_team_matches"] == parent["minimum_team_matches"]
    assert derived["excluded"][-1]["match_id"] == 999
    assert any(row["reason"] == "p111_other_competition_season" for row in derived["excluded"])
    assert any(row["reason"] == "p111_context_after_fit_cutoff" for row in derived["excluded"])
    assert any(row["reason"] == "p111_context_missing" for row in derived["excluded"])
    assert training_manifest_sha256(derived) == derived["sha256"]
    assert set(included_ids) == set(projection.included_match_ids) | set(
        projection.excluded_match_ids
    )
    assert set(projection.included_match_ids).isdisjoint(projection.excluded_match_ids)
    assert projection.parent_training_manifest_sha256 == parent["sha256"]
    assert len(projection.projection_sha256) == 64


def test_projection_hash_is_order_independent_and_parent_hash_is_verified():
    parent = _parent_dataset().manifest.to_dict()
    ids = [row["match_id"] for row in parent["included"]]
    contexts = {match_id: _context() for match_id in ids}
    first = project_p106_manifest_to_season(
        parent, contexts, competition_id=77, competition_season_id=20262027
    )
    second = project_p106_manifest_to_season(
        parent,
        dict(reversed(list(contexts.items()))),
        competition_id=77,
        competition_season_id=20262027,
    )
    assert first.projection_sha256 == second.projection_sha256
    assert first.manifest == second.manifest

    tampered = dict(parent)
    tampered["included"] = list(parent["included"])
    tampered["included"][0] = {**tampered["included"][0], "home_goals": 99}
    with pytest.raises(ValueError, match="SHA-256"):
        project_p106_manifest_to_season(
            tampered, contexts, competition_id=77, competition_season_id=20262027
        )


def test_projection_accepts_missing_source_publication_time_with_system_visibility_evidence():
    parent = _parent_dataset().manifest.to_dict()
    included_ids = [row["match_id"] for row in parent["included"]]
    parent["included"][0]["official_publish_time"] = None
    parent["included"][0]["result_published_at"] = None
    fields = (
        "version",
        "selection_version",
        "minimum_team_matches",
        "cutoff_at",
        "training_start",
        "training_end",
        "included",
        "excluded",
    )
    parent["sha256"] = hashlib.sha256(
        canonical_json_bytes({field: parent[field] for field in fields})
    ).hexdigest()
    contexts = {match_id: _context() for match_id in included_ids}

    projection = project_p106_manifest_to_season(
        parent,
        contexts,
        competition_id=77,
        competition_season_id=20262027,
    )

    assert included_ids[0] in projection.included_match_ids


def test_projection_rejects_source_publication_before_kickoff_when_legacy_publication_is_missing():
    parent = _parent_dataset().manifest.to_dict()
    ids = [row["match_id"] for row in parent["included"]]
    row = dict(parent["included"][0])
    kickoff = datetime.fromisoformat(row["kickoff_time"]).replace(tzinfo=SHANGHAI)
    row["official_publish_time"] = None
    row["result_published_at"] = (kickoff - timedelta(minutes=1)).astimezone(UTC).isoformat()
    parent["included"] = [row, *parent["included"][1:]]
    fields = (
        "version",
        "selection_version",
        "minimum_team_matches",
        "cutoff_at",
        "training_start",
        "training_end",
        "included",
        "excluded",
    )
    parent["sha256"] = hashlib.sha256(
        canonical_json_bytes({field: parent[field] for field in fields})
    ).hexdigest()
    contexts = {match_id: _context() for match_id in ids}

    with pytest.raises(ValueError, match="source label was published before kickoff"):
        project_p106_manifest_to_season(
            parent,
            contexts,
            competition_id=77,
            competition_season_id=20262027,
        )


def test_projection_rejects_disagreeing_official_and_source_publication_times():
    parent = _parent_dataset().manifest.to_dict()
    ids = [row["match_id"] for row in parent["included"]]
    row = dict(parent["included"][0])
    source_published = datetime.fromisoformat(row["result_published_at"])
    row["result_published_at"] = (source_published + timedelta(seconds=1)).isoformat()
    parent["included"] = [row, *parent["included"][1:]]
    fields = (
        "version",
        "selection_version",
        "minimum_team_matches",
        "cutoff_at",
        "training_start",
        "training_end",
        "included",
        "excluded",
    )
    parent["sha256"] = hashlib.sha256(
        canonical_json_bytes({field: parent[field] for field in fields})
    ).hexdigest()
    contexts = {match_id: _context() for match_id in ids}

    with pytest.raises(ValueError, match="publication timestamps disagree"):
        project_p106_manifest_to_season(
            parent,
            contexts,
            competition_id=77,
            competition_season_id=20262027,
        )


def test_projection_requires_explicit_context_for_every_parent_included_match():
    parent = _parent_dataset().manifest.to_dict()
    ids = [row["match_id"] for row in parent["included"]]
    contexts = {match_id: _context() for match_id in ids[:-1]}

    with pytest.raises(ValueError, match="exactly match parent included samples"):
        project_p106_manifest_to_season(
            parent, contexts, competition_id=77, competition_season_id=20262027
        )


def test_projection_evidence_digest_binds_missing_and_rejected_contexts():
    parent = _parent_dataset().manifest.to_dict()
    ids = [row["match_id"] for row in parent["included"]]
    contexts = {match_id: _context() for match_id in ids}
    contexts[ids[0]] = None
    first = project_p106_manifest_to_season(
        parent, contexts, competition_id=77, competition_season_id=20262027
    )
    changed = dict(contexts)
    changed[ids[1]] = _context(20252026)
    second = project_p106_manifest_to_season(
        parent, changed, competition_id=77, competition_season_id=20262027
    )
    assert first.projection_sha256 != second.projection_sha256
    assert first.season_context_sha256 != second.season_context_sha256


def test_p106_shadow_writer_refuses_non_fixture_database_targets():
    class Connection:
        autocommit = False

        def get_dsn_parameters(self):
            return {"host": "10.0.0.12", "dbname": "fqp"}

        def get_transaction_status(self):
            return 0

    with pytest.raises(ValueError, match="loopback fqp_p106_test_"):
        _require_isolated_research_database(Connection())


@pytest.mark.parametrize(
    "parameters",
    [
        {
            "host": "localhost",
            "hostaddr": "10.0.0.12",
            "dbname": "fqp_p106_test_provenance",
        },
        {
            "host": "127.0.0.1,10.0.0.12",
            "dbname": "fqp_p106_test_provenance",
        },
    ],
)
def test_p106_shadow_writer_rejects_hostaddr_override_and_multi_host(parameters):
    class Connection:
        autocommit = False

        def get_dsn_parameters(self):
            return parameters

        def get_transaction_status(self):
            return 0

    with pytest.raises(ValueError, match="loopback fqp_p106_test_"):
        _require_isolated_research_database(Connection())


def test_p106_shadow_writer_requires_server_side_database_attestation():
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _query):
            return None

        def fetchone(self):
            return "fqp_p106_test_provenance", "not-the-p111-fixture-marker"

    class Connection:
        autocommit = False
        rolled_back = False

        def get_dsn_parameters(self):
            return {
                "host": "127.0.0.1",
                "dbname": "fqp_p106_test_provenance",
            }

        def get_transaction_status(self):
            return 0

        def cursor(self):
            return Cursor()

        def rollback(self):
            self.rolled_back = True

    connection = Connection()
    with pytest.raises(ValueError, match="database attestation"):
        _require_isolated_research_database(connection)
    assert connection.rolled_back is True


def test_p111_shadow_comparison_requires_the_explicit_active_incumbent(monkeypatch):
    from scripts import backtest_engine
    from scripts.dynamic_team_p106 import (
        MODEL_NAME,
        evaluate_dynamic_team_p106_shadow_vs_incumbent,
    )

    candidate_run_id = "00000000-0000-0000-0000-000000000501"
    candidate_report = {
        "evaluation_mode": "prediction_replay",
        "official_prediction_writes": 0,
        "predictions": [{"model_name": MODEL_NAME, "model_is_active": False}],
    }
    incumbent_report = {
        "evaluation_mode": "prediction_replay",
        "prediction_run_id": "00000000-0000-0000-0000-000000000010",
        "predictions": [],
    }
    paired_report = {
        "evaluation_mode": "paired_prediction_replay",
        "status": "evaluated_descriptive_only",
        "sample_count": 4,
    }
    conn = MagicMock()
    conn.autocommit = False
    conn.get_transaction_status.return_value = 0
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [
        ("completed", [{"model_name": MODEL_NAME, "model_version_id": 501}]),
        (MODEL_NAME, False, {"rollout_mode": "shadow", "publishable": False}),
    ]
    monkeypatch.setattr(
        "scripts.dynamic_team_p106._require_isolated_research_database", lambda _: None
    )
    monkeypatch.setattr(
        backtest_engine,
        "evaluate_prediction_replay",
        MagicMock(return_value=candidate_report),
    )
    compare = MagicMock(return_value=paired_report)
    store = MagicMock(return_value=42)
    monkeypatch.setattr(backtest_engine, "compare_prediction_replay_reports", compare)
    monkeypatch.setattr(backtest_engine, "store_research_evaluation_run", store)

    result = evaluate_dynamic_team_p106_shadow_vs_incumbent(
        conn,
        prediction_run_id=candidate_run_id,
        incumbent_replay_report=incumbent_report,
        incumbent_model_version_id=10,
        name="p111-vs-active-model",
        predeclared_window=True,
    )

    assert result["status"] == "evaluated_descriptive_only"
    assert result["sample_count"] == 4
    assert result["evaluation_run_id"] == 42
    compare.assert_called_once_with(
        candidate_report,
        incumbent_report,
        challenger_model_version_id=501,
        incumbent_model_version_id=10,
        require_active_incumbent=True,
        predeclared_window=True,
    )
    store.assert_called_once_with(conn, paired_report, name="p111-vs-active-model")


def test_p111_shadow_comparison_rejects_candidate_activated_before_replay(monkeypatch):
    from scripts import backtest_engine
    from scripts.dynamic_team_p106 import (
        MODEL_NAME,
        evaluate_dynamic_team_p106_shadow_vs_incumbent,
    )

    conn = MagicMock()
    conn.autocommit = False
    conn.get_transaction_status.return_value = 0
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [
        ("completed", [{"model_name": MODEL_NAME, "model_version_id": 501}]),
        (MODEL_NAME, False, {"rollout_mode": "shadow", "publishable": False}),
    ]
    monkeypatch.setattr(
        "scripts.dynamic_team_p106._require_isolated_research_database", lambda _: None
    )
    monkeypatch.setattr(
        backtest_engine,
        "evaluate_prediction_replay",
        MagicMock(
            return_value={
                "official_prediction_writes": 0,
                "predictions": [{"model_name": MODEL_NAME, "model_is_active": True}],
            }
        ),
    )
    compare = MagicMock()
    monkeypatch.setattr(backtest_engine, "compare_prediction_replay_reports", compare)

    with pytest.raises(ValueError, match="not an inactive shadow candidate at replay"):
        evaluate_dynamic_team_p106_shadow_vs_incumbent(
            conn,
            prediction_run_id="00000000-0000-0000-0000-000000000501",
            incumbent_replay_report={"prediction_run_id": "00000000-0000-0000-0000-000000000010"},
            incumbent_model_version_id=10,
            name="p111-vs-active-model",
        )

    compare.assert_not_called()
