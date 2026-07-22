from unittest.mock import MagicMock

import pytest

from scripts.model_storage import activate_simulation_ticket


def test_activation_requires_risk_approval():
    with pytest.raises(PermissionError):
        activate_simulation_ticket(MagicMock(), 1, "pending")


def test_activation_updates_only_generated_ticket():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = [1]
    assert activate_simulation_ticket(conn, 1, "approved") is True
    assert "ticket_status = 'activated'" in cur.execute.call_args[0][0]
