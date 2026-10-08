-- Preserve all existing ledger rows. Abort if duplicates require reconciliation.
-- Run inside the migration runner's transaction as the application table owner.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ticket_settlements
        GROUP BY ticket_source, ticket_id HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate ticket settlements exist; reconcile before migration 104';
    END IF;
    IF EXISTS (
        SELECT 1 FROM bankroll_transactions
        WHERE transaction_type = 'prize' AND related_ticket_id IS NOT NULL
        GROUP BY account_id, related_ticket_id HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate prize credits exist; reconcile before migration 104';
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ticket_settlements_source_ticket
    ON ticket_settlements (ticket_source, ticket_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_bankroll_prize_ticket
    ON bankroll_transactions (account_id, related_ticket_id)
    WHERE transaction_type = 'prize' AND related_ticket_id IS NOT NULL;
