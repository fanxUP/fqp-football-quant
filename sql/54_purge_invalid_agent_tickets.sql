-- Invalidated Agent recommendations are not financial tickets and must not
-- remain in the betting ledger as permanently pending records.
CREATE TEMP TABLE invalid_agent_ticket_cleanup AS
SELECT id
FROM simulation_tickets
WHERE ticket_status IN ('invalid', 'invalidated');

UPDATE real_tickets
SET related_simulation_ticket_id = NULL,
    updated_at = NOW()
WHERE related_simulation_ticket_id IN (
    SELECT id FROM invalid_agent_ticket_cleanup
);

DELETE FROM evidence_chain_audit_logs
WHERE ticket_id IN (SELECT id FROM invalid_agent_ticket_cleanup);

DELETE FROM ticket_settlements
WHERE ticket_source = 'simulation'
  AND ticket_id IN (SELECT id FROM invalid_agent_ticket_cleanup);

DELETE FROM simulation_ticket_items
WHERE ticket_id IN (SELECT id FROM invalid_agent_ticket_cleanup);

DELETE FROM simulation_tickets
WHERE id IN (SELECT id FROM invalid_agent_ticket_cleanup);

DROP TABLE invalid_agent_ticket_cleanup;
