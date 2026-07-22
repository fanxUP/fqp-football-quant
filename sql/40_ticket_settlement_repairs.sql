-- Repair legacy Agent tickets that can never settle because their selections
-- no longer exist. Keep the rows for audit history and mark them explicitly.
UPDATE simulation_tickets AS ticket
SET ticket_status = 'cancelled',
    invalid_reason = COALESCE(
        NULLIF(ticket.invalid_reason, ''),
        '无投注明细，无法结算'
    )
WHERE ticket.ticket_status IN ('generated', 'activated')
  AND NOT EXISTS (
      SELECT 1
      FROM simulation_ticket_items AS item
      WHERE item.ticket_id = ticket.id
  );

CREATE INDEX IF NOT EXISTS idx_ticket_settlements_settle_time
    ON ticket_settlements (settle_time, id);
