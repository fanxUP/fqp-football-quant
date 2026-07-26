-- 为三类彩票建立统一、稳定的业务编号：购买日期(YYYYMMDD) + 当日流水号(001)。

ALTER TABLE simulator_tickets
    ADD COLUMN IF NOT EXISTS ledger_ticket_no VARCHAR(32);
ALTER TABLE real_tickets
    ADD COLUMN IF NOT EXISTS ledger_ticket_no VARCHAR(32);
ALTER TABLE simulation_tickets
    ADD COLUMN IF NOT EXISTS ledger_ticket_no VARCHAR(32);

CREATE TABLE IF NOT EXISTS betting_ticket_daily_sequences (
    purchase_date DATE PRIMARY KEY,
    last_value BIGINT NOT NULL CHECK (last_value > 0)
);

CREATE TEMP TABLE ticket_number_backfill AS
WITH unified_tickets AS (
    SELECT 'simulator'::TEXT AS ticket_source, id,
           COALESCE(created_at, NOW())::DATE AS purchase_date,
           COALESCE(created_at, NOW()) AS purchased_at
    FROM simulator_tickets
    UNION ALL
    SELECT 'real'::TEXT, id,
           COALESCE(purchase_time, created_at, NOW())::DATE,
           COALESCE(purchase_time, created_at, NOW())
    FROM real_tickets
    UNION ALL
    SELECT 'agent'::TEXT, id,
           COALESCE(created_at, NOW())::DATE,
           COALESCE(created_at, NOW())
    FROM simulation_tickets
), ranked AS (
    SELECT ticket_source, id, purchase_date,
           ROW_NUMBER() OVER (
               PARTITION BY purchase_date
               ORDER BY purchased_at, ticket_source, id
           ) AS running_no
    FROM unified_tickets
)
SELECT ticket_source, id, purchase_date, running_no,
       TO_CHAR(purchase_date, 'YYYYMMDD')
       || LPAD(
           running_no::TEXT,
           GREATEST(3, LENGTH(running_no::TEXT)),
           '0'
       ) AS ticket_no
FROM ranked;

UPDATE simulator_tickets AS ticket
SET ledger_ticket_no = numbered.ticket_no
FROM ticket_number_backfill AS numbered
WHERE numbered.ticket_source = 'simulator'
  AND numbered.id = ticket.id
  AND ticket.ledger_ticket_no IS NULL;

UPDATE real_tickets AS ticket
SET ledger_ticket_no = numbered.ticket_no
FROM ticket_number_backfill AS numbered
WHERE numbered.ticket_source = 'real'
  AND numbered.id = ticket.id
  AND ticket.ledger_ticket_no IS NULL;

UPDATE simulation_tickets AS ticket
SET ledger_ticket_no = numbered.ticket_no
FROM ticket_number_backfill AS numbered
WHERE numbered.ticket_source = 'agent'
  AND numbered.id = ticket.id
  AND ticket.ledger_ticket_no IS NULL;

INSERT INTO betting_ticket_daily_sequences (purchase_date, last_value)
SELECT purchase_date, MAX(running_no)
FROM ticket_number_backfill
GROUP BY purchase_date
ON CONFLICT (purchase_date) DO UPDATE
SET last_value = GREATEST(
    betting_ticket_daily_sequences.last_value,
    EXCLUDED.last_value
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_simulator_tickets_ledger_no
    ON simulator_tickets (ledger_ticket_no);
CREATE UNIQUE INDEX IF NOT EXISTS uq_real_tickets_ledger_no
    ON real_tickets (ledger_ticket_no);
CREATE UNIQUE INDEX IF NOT EXISTS uq_simulation_tickets_ledger_no
    ON simulation_tickets (ledger_ticket_no);

CREATE OR REPLACE FUNCTION assign_betting_ticket_number()
RETURNS TRIGGER AS $$
DECLARE
    ticket_date DATE;
    next_value BIGINT;
BEGIN
    IF NEW.ledger_ticket_no IS NOT NULL THEN
        RETURN NEW;
    END IF;

    IF TG_TABLE_NAME = 'real_tickets' THEN
        ticket_date := COALESCE(NEW.purchase_time, NEW.created_at, NOW())::DATE;
    ELSE
        ticket_date := COALESCE(NEW.created_at, NOW())::DATE;
    END IF;

    INSERT INTO betting_ticket_daily_sequences (purchase_date, last_value)
    VALUES (ticket_date, 1)
    ON CONFLICT (purchase_date) DO UPDATE
    SET last_value = betting_ticket_daily_sequences.last_value + 1
    RETURNING last_value INTO next_value;

    NEW.ledger_ticket_no := TO_CHAR(ticket_date, 'YYYYMMDD')
        || LPAD(
            next_value::TEXT,
            GREATEST(3, LENGTH(next_value::TEXT)),
            '0'
        );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_simulator_ticket_number ON simulator_tickets;
CREATE TRIGGER trg_simulator_ticket_number
BEFORE INSERT ON simulator_tickets
FOR EACH ROW EXECUTE FUNCTION assign_betting_ticket_number();

DROP TRIGGER IF EXISTS trg_real_ticket_number ON real_tickets;
CREATE TRIGGER trg_real_ticket_number
BEFORE INSERT ON real_tickets
FOR EACH ROW EXECUTE FUNCTION assign_betting_ticket_number();

DROP TRIGGER IF EXISTS trg_agent_ticket_number ON simulation_tickets;
CREATE TRIGGER trg_agent_ticket_number
BEFORE INSERT ON simulation_tickets
FOR EACH ROW EXECUTE FUNCTION assign_betting_ticket_number();
