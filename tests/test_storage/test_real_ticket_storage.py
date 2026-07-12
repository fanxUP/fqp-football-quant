"""Unit tests for real_ticket_storage.py — tickets, items, settlements, reviews."""

from __future__ import annotations

from unittest.mock import MagicMock

from scripts.real_ticket_storage import (
    create_bankroll_transaction,
    create_error_analyses_batch,
    create_real_ticket,
    create_real_ticket_items_batch,
    create_settlement,
    delete_real_ticket,
    get_daily_review,
    get_error_summary,
    get_real_ticket,
    get_settlement_summary,
    get_settlements_by_date,
    list_daily_reviews,
    list_error_analyses,
    list_real_tickets,
    list_weekly_reviews,
    update_real_ticket,
    upsert_daily_review,
    upsert_weekly_review,
)


def _mock_conn(fetchone=None, fetchall=None, rowcount=1):
    """Create a mock connection with cursor."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = fetchone
    mock_cur.fetchall.return_value = fetchall if fetchall is not None else []
    mock_cur.rowcount = rowcount
    return mock_conn, mock_cur


class TestCreateRealTicket:
    def test_inserts_and_returns_id(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[42])

        ticket = {"pass_type": "2串1", "total_amount": 100}
        result = create_real_ticket(mock_conn, ticket)
        assert result == 42
        mock_conn.commit.assert_called_once()

    def test_uses_defaults(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[1])

        ticket = {}
        result = create_real_ticket(mock_conn, ticket)
        assert result == 1
        call_args = mock_cur.execute.call_args[0][1]
        assert call_args["pass_type"] == "single"
        assert call_args["total_amount"] == 0
        assert call_args["settlement_status"] == "pending"

    def test_returns_none_when_no_row(self):
        mock_conn, mock_cur = _mock_conn(fetchone=None)

        result = create_real_ticket(mock_conn, {})
        assert result is None


class TestUpdateRealTicket:
    def test_updates_allowed_fields(self):
        mock_conn, mock_cur = _mock_conn(rowcount=1)

        updates = {"confirm_status": "confirmed", "total_amount": 200}
        result = update_real_ticket(mock_conn, 1, updates)
        assert result is True

    def test_ignores_disallowed_fields(self):
        """Only allowed fields should be in the UPDATE SQL."""
        mock_conn, mock_cur = _mock_conn(rowcount=1)

        updates = {"confirm_status": "confirmed", "unknown_field": "value"}
        result = update_real_ticket(mock_conn, 1, updates)
        assert result is True
        # The first execute call is the UPDATE; _audit_log makes a second call
        update_call_args = mock_cur.execute.call_args_list[0][0][1]
        assert "unknown_field" not in update_call_args
        assert "confirm_status" in update_call_args

    def test_returns_false_when_no_allowed_fields(self):
        mock_conn, mock_cur = _mock_conn()

        result = update_real_ticket(mock_conn, 1, {"secret_field": "x"})
        assert result is False
        mock_cur.execute.assert_not_called()

    def test_returns_false_when_zero_rows_affected(self):
        mock_conn, mock_cur = _mock_conn(rowcount=0)

        result = update_real_ticket(mock_conn, 999, {"confirm_status": "confirmed"})
        assert result is False


class TestGetRealTicket:
    def test_returns_formatted_ticket(self):
        now = MagicMock(isoformat=lambda: "2025-01-01T00:00:00")
        mock_conn, mock_cur = _mock_conn(fetchone=[
            1, 1, None, None, "T-001", now, "StoreA", 100.0, 1, "2串1",
            None, "manual_entry", "not_applicable", "confirmed", "pending",
            now, now, 3,
        ])

        result = get_real_ticket(mock_conn, 1)
        assert result is not None
        assert result["id"] == 1
        assert result["ticket_no"] == "T-001"
        assert result["total_amount"] == 100.0
        assert result["item_count"] == 3

    def test_returns_none_when_not_found(self):
        mock_conn, mock_cur = _mock_conn(fetchone=None)

        result = get_real_ticket(mock_conn, 999)
        assert result is None


class TestListRealTickets:
    def test_returns_formatted_list(self):
        now = MagicMock(isoformat=lambda: "2025-01-01T00:00:00")
        mock_conn, mock_cur = _mock_conn(fetchall=[
            (1, "单关", 50.0, 1, None, "manual_entry", "not_applicable",
             "confirmed", "pending", now, now, None, 2),
        ])

        result = list_real_tickets(mock_conn)
        assert len(result) == 1
        assert result[0]["pass_type"] == "单关"

    def test_filters_by_status(self):
        mock_conn, mock_cur = _mock_conn(fetchall=[])

        result = list_real_tickets(mock_conn, status="settled")
        assert result == []
        call_args = mock_cur.execute.call_args[0][1]
        assert call_args["status"] == "settled"


class TestDeleteRealTicket:
    def test_deletes_items_and_ticket(self):
        """delete_real_ticket calls: get_real_ticket, DELETE items, DELETE ticket, _audit_log."""
        now = MagicMock(isoformat=lambda: "2025-01-01T00:00:00")
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = [
            1, 1, None, None, "T-X", now, "S", 0, 1, "单关",
            None, "manual_entry", "ok", "confirmed", "pending", now, now, 0,
        ]
        mock_cur.rowcount = 1
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        result = delete_real_ticket(mock_conn, 1)
        assert result is True
        # get_real_ticket (1) + DELETE items (1) + DELETE ticket (1) + _audit_log (1) = 4
        assert mock_cur.execute.call_count == 4

    def test_returns_false_when_not_found(self):
        mock_conn, mock_cur = _mock_conn(fetchone=None, rowcount=0)

        result = delete_real_ticket(mock_conn, 999)
        assert result is False


class TestCreateRealTicketItemsBatch:
    def test_inserts_multiple_items(self):
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [[1], [2], [3]]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        items = [
            {"match_id": 1, "option_code": "胜", "sp_value": 2.10},
            {"match_id": 2, "option_code": "平", "sp_value": 3.50},
            {"match_id": 3, "option_code": "负", "sp_value": 2.80},
        ]
        result = create_real_ticket_items_batch(mock_conn, 1, items)
        assert result == [1, 2, 3]
        assert mock_cur.execute.call_count == 3


class TestSettlements:
    def test_create_settlement_returns_id(self):
        """create_settlement checks for existing then inserts."""
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [None, [99]]  # no existing, new id=99
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        settlement = {"ticket_source": "real", "ticket_id": 1, "stake_amount": 100}
        result = create_settlement(mock_conn, settlement)
        assert result == 99
        assert mock_cur.execute.call_count == 2  # check + insert

    def test_create_settlement_skips_if_exists(self):
        """Returns existing id if settlement already exists."""
        mock_conn, mock_cur = _mock_conn(fetchone=[5])

        settlement = {"ticket_source": "real", "ticket_id": 1}
        result = create_settlement(mock_conn, settlement)
        assert result == 5
        assert mock_cur.execute.call_count == 1  # only the check query

    def test_get_settlements_by_date(self):
        now = MagicMock(isoformat=lambda: "2025-01-01T00:00:00")
        # 12 columns: id, ticket_source, ticket_id, settle_time, is_won,
        # stake_amount, prize_amount, tax_amount, net_prize, profit_loss, roi,
        # settlement_detail_json
        mock_conn, mock_cur = _mock_conn(fetchall=[
            (1, "real", 10, now, True, 100.0, 250.0, 0.0, 250.0, 150.0, 1.5, "{}"),
        ])

        result = get_settlements_by_date(mock_conn, "2025-01-01")
        assert len(result) == 1
        assert result[0]["is_won"] is True
        assert result[0]["ticket_source"] == "real"

    def test_get_settlement_summary_returns_stats(self):
        mock_conn, mock_cur = _mock_conn(
            fetchall=[
                ("real", 5, 500.0, 1250.0, 750.0, 1.5),
            ]
        )

        result = get_settlement_summary(mock_conn, "2025-01-01")
        assert result["date"] == "2025-01-01"
        assert result["total_settled"] == 5
        assert "real" in result["sources"]
        assert result["sources"]["real"]["count"] == 5


class TestReviews:
    def test_upsert_daily_review_returns_id(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[1])

        review = {"review_date": "2025-01-01"}
        result = upsert_daily_review(mock_conn, review)
        assert result == 1

    def test_get_daily_review_found(self):
        """_daily_review_row_to_dict needs 21 columns (index 0-20)."""
        now = MagicMock(isoformat=lambda: "2025-01-01")
        # Build a 21-element tuple matching daily_reviews columns
        row = [1, now, 5, 5, 3, 2, 1, 500.0, 200.0, 0.0, 0.0, 0.0, 0.0,
               0.0, 0.0, 0.0, 0.0, 0.0, "summary", None, now]
        mock_conn, mock_cur = _mock_conn(fetchone=tuple(row))

        result = get_daily_review(mock_conn, "2025-01-01")
        assert result is not None
        assert result["id"] == 1
        assert result["real_ticket_count"] == 1

    def test_get_daily_review_not_found(self):
        mock_conn, mock_cur = _mock_conn(fetchone=None)

        result = get_daily_review(mock_conn, "2099-01-01")
        assert result is None

    def test_list_daily_reviews(self):
        now = MagicMock(isoformat=lambda: "2025-01-01")
        row = [1, now, 5, 5, 3, 2, 1, 500.0, 200.0, 0.0, 0.0, 0.0, 0.0,
               0.0, 0.0, 0.0, 0.0, 0.0, "summary", None, now]
        mock_conn, mock_cur = _mock_conn(fetchall=[tuple(row)])

        result = list_daily_reviews(mock_conn)
        assert len(result) == 1
        assert result[0]["id"] == 1

    def test_upsert_weekly_review(self):
        mock_conn, mock_cur = _mock_conn(fetchone=[1])

        review = {"week_start": "2024-12-30", "week_end": "2025-01-05"}
        result = upsert_weekly_review(mock_conn, review)
        assert result == 1

    def test_list_weekly_reviews(self):
        mock_conn, mock_cur = _mock_conn(fetchall=[])

        result = list_weekly_reviews(mock_conn)
        assert result == []


class TestErrorAnalyses:
    def test_create_batch_returns_count(self):
        """create_error_analyses_batch loops and calls cur.execute for each error."""
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [[1], [2], [3]]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        errors = [
            {"prediction_id": 1, "error_type": "over_confidence"},
            {"prediction_id": 2, "error_type": "direction_wrong"},
            {"prediction_id": 3, "error_type": "calibration"},
        ]
        result = create_error_analyses_batch(mock_conn, errors)
        assert result == 3
        assert mock_cur.execute.call_count == 3

    def test_list_error_analyses(self):
        mock_conn, mock_cur = _mock_conn(fetchall=[])

        result = list_error_analyses(mock_conn)
        assert result == []

    def test_error_summary_parameterizes_interval_days(self):
        mock_conn, mock_cur = _mock_conn(fetchall=[])

        result = get_error_summary(mock_conn, days=7)

        sql, params = mock_cur.execute.call_args.args
        assert "%(days)s * INTERVAL '1 day'" in sql
        assert params == {"days": 7}
        assert result == {"total_errors": 0, "days": 7, "error_types": {}}


class TestBankroll:
    def test_create_bankroll_transaction_returns_id(self):
        """SELECT account, INSERT txn, UPDATE balance."""
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [
            [1, 5000.0],   # account SELECT: id, current_balance
            [100],          # txn INSERT RETURNING id
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        txn = {"transaction_type": "deposit", "amount": 500.0, "account_type": "main"}
        result = create_bankroll_transaction(mock_conn, txn)
        assert result == 100
        assert mock_cur.execute.call_count == 3  # SELECT + INSERT + UPDATE
