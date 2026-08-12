from unittest.mock import MagicMock, patch


def _connection_with_rows(*rows):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = rows
    return connection


def test_real_ticket_settlement_rejects_unknown_terminal_state(client):
    response = client.post(
        "/api/real-tickets/28/settle",
        json={"settlement_status": "manually_closed"},
    )

    assert response.status_code == 400


def test_real_ticket_settlement_requires_a_ledger_row(client):
    ticket_connection = _connection_with_rows((28,))
    verification_connection = _connection_with_rows(("pending", None))

    with (
        patch(
            "apps.backend.src.routers.tickets.get_db",
            side_effect=[ticket_connection, verification_connection],
        ),
        patch("scripts.jobs.settle_tickets.run", return_value={"status": "ok", "settled": 0}),
    ):
        response = client.post("/api/real-tickets/28/settle")

    assert response.status_code == 409
    assert "官方赛果尚未齐全" in response.json()["detail"]


def test_real_ticket_settlement_returns_only_after_status_and_ledger_agree(client):
    ticket_connection = _connection_with_rows((28,))
    verification_connection = _connection_with_rows(("settled", 115))

    with (
        patch(
            "apps.backend.src.routers.tickets.get_db",
            side_effect=[ticket_connection, verification_connection],
        ),
        patch(
            "scripts.jobs.settle_tickets.run",
            return_value={"status": "ok", "settled": 1},
        ),
    ):
        response = client.post("/api/real-tickets/28/settle")

    assert response.status_code == 200
    assert response.json()["settlement_status"] == "settled"
    assert response.json()["settlement_run"]["settled"] == 1
