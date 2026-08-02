-- 将同一业务日、同一投注内容的 Agent 拆分票重新排布为连续的 50 倍单票。
-- 仅处理总倍投刚好可被 50 整除且结算状态相同的票组；不同玩法、不同投注内容
-- 或存在未结算混合状态的票绝不合并。
CREATE TEMP TABLE agent_ticket_split_consolidation AS
WITH ticket_shapes AS (
    SELECT st.id,
           (st.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::DATE AS ticket_date,
           st.strategy_pool,
           st.ticket_type,
           st.pass_type,
           st.ticket_status,
           st.multiple,
           st.suggested_stake,
           st.estimated_return,
           st.max_return,
           st.rule_metadata,
           STRING_AGG(
               item.match_id::TEXT || ':' || item.play_type || ':' || item.option_code,
               ',' ORDER BY item.id
           ) AS selection_key,
           settlement.id AS settlement_id,
           settlement.is_won,
           settlement.stake_amount,
           settlement.prize_amount,
           settlement.tax_amount,
           settlement.net_prize,
           settlement.profit_loss,
           settlement.settlement_detail_json
    FROM simulation_tickets st
    JOIN simulation_ticket_items item ON item.ticket_id = st.id
    LEFT JOIN ticket_settlements settlement
      ON settlement.ticket_source = 'simulation'
     AND settlement.ticket_id = st.id
    WHERE st.rule_metadata::TEXT LIKE '%physical_ticket_split%'
    GROUP BY st.id, settlement.id
), grouped AS (
    SELECT ticket_date, strategy_pool, ticket_type, pass_type, ticket_status,
           selection_key, is_won,
           COUNT(*) AS source_count,
           SUM(multiple) AS total_multiple,
           SUM(suggested_stake) AS total_stake,
           SUM(estimated_return) AS total_estimated_return,
           SUM(max_return) AS total_max_return,
           SUM(stake_amount) AS total_settlement_stake,
           SUM(prize_amount) AS total_prize,
           SUM(tax_amount) AS total_tax,
           SUM(net_prize) AS total_net_prize,
           SUM(profit_loss) AS total_profit_loss
    FROM ticket_shapes
    GROUP BY ticket_date, strategy_pool, ticket_type, pass_type, ticket_status,
             selection_key, is_won
    HAVING SUM(multiple) % 50 = 0
       AND COUNT(*) > SUM(multiple) / 50
), ranked AS (
    SELECT shape.*,
           grouped.total_multiple AS total_multiple,
           grouped.total_multiple / 50 AS target_count,
           grouped.total_stake,
           grouped.total_estimated_return,
           grouped.total_max_return,
           grouped.total_settlement_stake,
           grouped.total_prize,
           grouped.total_tax,
           grouped.total_net_prize,
           grouped.total_profit_loss,
           ROW_NUMBER() OVER (
               PARTITION BY shape.ticket_date, shape.strategy_pool, shape.ticket_type,
                            shape.pass_type, shape.ticket_status, shape.selection_key,
                            shape.is_won
               ORDER BY shape.multiple DESC, shape.id
           ) AS ticket_rank
    FROM ticket_shapes shape
    JOIN grouped
      ON grouped.ticket_date = shape.ticket_date
     AND grouped.strategy_pool = shape.strategy_pool
     AND grouped.ticket_type = shape.ticket_type
     AND grouped.pass_type = shape.pass_type
     AND grouped.ticket_status = shape.ticket_status
     AND grouped.selection_key = shape.selection_key
     AND grouped.is_won IS NOT DISTINCT FROM shape.is_won
)
SELECT * FROM ranked;

UPDATE simulation_tickets ticket
SET multiple = 50,
    suggested_stake = CASE
        WHEN source.ticket_rank = source.target_count
        THEN source.total_stake - ROUND(source.total_stake / source.target_count, 2) * (source.target_count - 1)
        ELSE ROUND(source.total_stake / source.target_count, 2)
    END,
    estimated_return = CASE
        WHEN source.total_estimated_return IS NULL THEN NULL
        WHEN source.ticket_rank = source.target_count
        THEN source.total_estimated_return - ROUND(source.total_estimated_return / source.target_count, 2) * (source.target_count - 1)
        ELSE ROUND(source.total_estimated_return / source.target_count, 2)
    END,
    max_return = CASE
        WHEN source.total_max_return IS NULL THEN NULL
        WHEN source.ticket_rank = source.target_count
        THEN source.total_max_return - ROUND(source.total_max_return / source.target_count, 2) * (source.target_count - 1)
        ELSE ROUND(source.total_max_return / source.target_count, 2)
    END,
    rule_metadata = COALESCE(ticket.rule_metadata, '{}'::JSONB)
        || jsonb_build_object(
            'physical_ticket_consolidation', jsonb_build_object(
                'total_multiple', source.total_multiple,
                'physical_ticket_count', source.target_count,
                'single_ticket_multiple', 50
            )
        )
FROM agent_ticket_split_consolidation source
WHERE ticket.id = source.id
  AND source.ticket_rank <= source.target_count;

UPDATE ticket_settlements settlement
SET stake_amount = CASE
        WHEN source.ticket_rank = source.target_count
        THEN source.total_settlement_stake - ROUND(source.total_settlement_stake / source.target_count, 2) * (source.target_count - 1)
        ELSE ROUND(source.total_settlement_stake / source.target_count, 2)
    END,
    prize_amount = CASE
        WHEN source.ticket_rank = source.target_count
        THEN source.total_prize - ROUND(source.total_prize / source.target_count, 2) * (source.target_count - 1)
        ELSE ROUND(source.total_prize / source.target_count, 2)
    END,
    tax_amount = CASE
        WHEN source.ticket_rank = source.target_count
        THEN source.total_tax - ROUND(source.total_tax / source.target_count, 2) * (source.target_count - 1)
        ELSE ROUND(source.total_tax / source.target_count, 2)
    END,
    net_prize = CASE
        WHEN source.ticket_rank = source.target_count
        THEN source.total_net_prize - ROUND(source.total_net_prize / source.target_count, 2) * (source.target_count - 1)
        ELSE ROUND(source.total_net_prize / source.target_count, 2)
    END,
    profit_loss = CASE
        WHEN source.ticket_rank = source.target_count
        THEN source.total_profit_loss - ROUND(source.total_profit_loss / source.target_count, 2) * (source.target_count - 1)
        ELSE ROUND(source.total_profit_loss / source.target_count, 2)
    END,
    roi = CASE
        WHEN source.total_settlement_stake > 0
        THEN source.total_profit_loss / source.total_settlement_stake
        ELSE 0
    END,
    settlement_detail_json = jsonb_set(
        COALESCE(settlement.settlement_detail_json, '{}'::JSONB),
        '{multiple}', to_jsonb(50), true
    )
FROM agent_ticket_split_consolidation source
WHERE settlement.id = source.settlement_id
  AND source.ticket_rank <= source.target_count;

DELETE FROM ticket_settlements settlement
USING agent_ticket_split_consolidation source
WHERE settlement.id = source.settlement_id
  AND source.ticket_rank > source.target_count;

DELETE FROM simulation_ticket_items item
USING agent_ticket_split_consolidation source
WHERE item.ticket_id = source.id
  AND source.ticket_rank > source.target_count;

DELETE FROM simulation_tickets ticket
USING agent_ticket_split_consolidation source
WHERE ticket.id = source.id
  AND source.ticket_rank > source.target_count;
