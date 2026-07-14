"""Unit tests for model_storage.py — model predictions, committee votes, simulation tickets."""

from __future__ import annotations

from unittest.mock import MagicMock

from scripts.model_storage import (
    store_committee_vote,
    store_model_prediction,
    store_simulation_ticket,
)


def _mock_conn(fetchone=None, rowcount=1):
    """Create a mock connection that supports `with conn.cursor() as cur:`."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = fetchone
    mock_cur.rowcount = rowcount
    return mock_conn, mock_cur


class TestStoreModelPrediction:
    def test_inserts_and_returns_id(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[42])

        pred = {
            "match_id": 101,
            "model_version_id": 5,
            "play_type": "SPF",
            "option_code": "胜",
            "model_probability": 0.45,
            "market_probability": 0.42,
        }
        result = store_model_prediction(mock_conn, pred)
        assert result == 42
        call_args = mock_cur.execute.call_args[0][1]
        assert call_args["feature_snapshot_id"] is None
        assert call_args["raw_model_probability"] == 0.45
        mock_cur.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_handles_json_uncertainty_reason(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[1])

        pred = {
            "match_id": 101,
            "model_version_id": 5,
            "play_type": "SPF",
            "option_code": "胜",
            "uncertainty_reason": {"missing_features": ["weather"]},
        }
        result = store_model_prediction(mock_conn, pred)
        assert result == 1
        # uncertainty_reason should be JSON-serialized
        call_args = mock_cur.execute.call_args[0][1]
        assert "uncertainty_reason" in call_args

    def test_returns_none_when_no_row_returned(self):
        mock_conn, mock_cur = _mock_conn(fetchone=None)

        pred = {"match_id": 101, "model_version_id": 5, "play_type": "SPF", "option_code": "胜"}
        result = store_model_prediction(mock_conn, pred)
        assert result is None


class TestStoreCommitteeVote:
    def test_inserts_and_returns_id(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[7])

        vote = {
            "match_id": 101,
            "play_type": "SPF",
            "option_code": "胜",
            "model_name": "xgboost_v2",
            "model_probability": 0.45,
        }
        result = store_committee_vote(mock_conn, vote)
        assert result == 7
        mock_conn.commit.assert_called_once()

    def test_uses_defaults_for_missing_fields(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[1])

        vote = {"match_id": 101, "play_type": "SPF", "option_code": "胜", "model_name": "test"}
        result = store_committee_vote(mock_conn, vote)
        assert result == 1
        call_args = mock_cur.execute.call_args[0][1]
        assert call_args["vote_weight"] == 1.0  # default

    def test_returns_none_when_no_row(self):
        mock_conn, mock_cur = _mock_conn(fetchone=None)

        vote = {"match_id": 101, "play_type": "SPF", "option_code": "胜", "model_name": "test"}
        result = store_committee_vote(mock_conn, vote)
        assert result is None


class TestStoreSimulationTicket:
    def test_creates_ticket_with_items(self):
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [[1], [100]]  # budget_plan_id, ticket_id
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        ticket = {"suggested_stake": 100.0, "strategy_pool": "main"}
        items = [
            {
                "match_id": 101,
                "play_type": "SPF",
                "option_code": "胜",
                "sp_value": 2.10,
                "feature_snapshot_id": 88,
            }
        ]
        result = store_simulation_ticket(mock_conn, ticket, items)
        assert result == 100
        item_call_args = mock_cur.execute.call_args_list[-1][0][1]
        assert item_call_args["feature_snapshot_id"] == 88
        mock_conn.commit.assert_called_once()
        # Should have called execute 3 times: budget query, ticket insert, item insert
        assert mock_cur.execute.call_count == 3

    def test_rolls_back_when_ticket_insert_fails(self):
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [[1], None]  # budget OK, ticket fails
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        ticket = {"suggested_stake": 50.0}
        items = []
        result = store_simulation_ticket(mock_conn, ticket, items)
        assert result is None
        mock_conn.rollback.assert_called_once()

    def test_inserts_multiple_items(self):
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [[1], [200]]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        ticket = {"suggested_stake": 200.0}
        items = [
            {"match_id": 1, "play_type": "SPF", "option_code": "胜", "sp_value": 1.8},
            {"match_id": 2, "play_type": "SPF", "option_code": "平", "sp_value": 3.2},
        ]
        result = store_simulation_ticket(mock_conn, ticket, items)
        assert result == 200
        # 1 budget + 1 ticket + 2 items = 4 execute calls
        assert mock_cur.execute.call_count == 4
