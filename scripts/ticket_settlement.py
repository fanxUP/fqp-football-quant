"""Commit the settlement ledger, optional prize credit and ticket status together."""

from __future__ import annotations

from typing import Any

from scripts.real_ticket_storage import create_bankroll_transaction, create_settlement

_TICKET_TABLES = {
    "simulation": ("simulation_tickets", "ticket_status", {"generated", "activated"}),
    "simulator": ("simulator_tickets", "status", {"pending"}),
    "real": ("real_tickets", "settlement_status", {"pending"}),
}


def settle_ticket_atomically(conn: Any, settlement: dict, *, remark: str) -> bool:
    """Serialize retries on the ticket row and roll back every write on failure.

    An existing ledger with a pending ticket needs reconciliation: do not infer
    whether its prize was credited, and never credit it again automatically.
    Real and recommendation accounts remain optional, as in the existing flow.
    """
    source = settlement["ticket_source"]
    table, status_column, pending_statuses = _TICKET_TABLES[source]
    ticket_id = settlement["ticket_id"]
    try:
        with conn.cursor() as cur:
            # Identifiers come exclusively from the fixed mapping above.
            confirm_check = ", confirm_status" if source == "real" else ""
            cur.execute(
                f"SELECT {status_column}{confirm_check} FROM {table} WHERE id = %s FOR UPDATE",
                (ticket_id,),
            )
            ticket = cur.fetchone()
            if (
                not ticket
                or ticket[0] not in pending_statuses
                or (source == "real" and ticket[1] != "confirmed")
            ):
                conn.commit()
                return False
            cur.execute(
                "SELECT id FROM ticket_settlements WHERE ticket_source = %s AND ticket_id = %s",
                (source, ticket_id),
            )
            if cur.fetchone():
                conn.commit()
                return False

        settlement_id = create_settlement(conn, settlement, commit=False)
        if settlement_id is None:
            raise RuntimeError("Settlement insert returned no identifier")
        if settlement.get("is_won") and settlement.get("net_prize", 0) > 0:
            transaction_id = create_bankroll_transaction(
                conn,
                {
                    "account_type": source,
                    "transaction_type": "prize",
                    "amount": settlement["net_prize"],
                    "related_ticket_id": ticket_id,
                    "remark": remark,
                },
                commit=False,
            )
            if transaction_id is None:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM bankroll_accounts WHERE account_type = %s LIMIT 1",
                        (source,),
                    )
                    if cur.fetchone() or source == "simulator":
                        raise RuntimeError("Prize credit could not be recorded")

        with conn.cursor() as cur:
            updated_at = ", updated_at = now()" if source != "simulation" else ""
            cur.execute(
                f"UPDATE {table} SET {status_column} = 'settled'{updated_at} WHERE id = %s",
                (ticket_id,),
            )
            if cur.rowcount != 1:
                raise RuntimeError("Settlement ticket status update failed")
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
