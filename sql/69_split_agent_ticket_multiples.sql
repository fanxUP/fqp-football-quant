-- 体彩单张票最高 50 倍；Agent 的日预算可以拆分为多张独立票。
-- 修复历史上误以 99 倍作为单票上限创建的 Agent 票，同时保持总投入、
-- 奖金和盈亏不变。原票保留其业务编号，新增拆分票由现有触发器分配编号。
DO $$
DECLARE
    source_ticket RECORD;
    source_settlement RECORD;
    original_multiple INTEGER;
    remaining_multiple INTEGER;
    part_multiple INTEGER;
    part_index INTEGER;
    part_count INTEGER;
    new_ticket_id BIGINT;
    has_settlement BOOLEAN;
    remaining_stake NUMERIC;
    remaining_prize NUMERIC;
    remaining_tax NUMERIC;
    remaining_net NUMERIC;
    remaining_profit NUMERIC;
    part_stake NUMERIC;
    part_prize NUMERIC;
    part_tax NUMERIC;
    part_net NUMERIC;
    part_profit NUMERIC;
    part_metadata JSONB;
    part_detail JSONB;
BEGIN
    FOR source_ticket IN
        SELECT *
        FROM simulation_tickets
        WHERE multiple > 50
        FOR UPDATE
    LOOP
        original_multiple := source_ticket.multiple;
        remaining_multiple := original_multiple;
        part_index := 0;
        part_count := CEIL(original_multiple::NUMERIC / 50)::INTEGER;

        SELECT * INTO source_settlement
        FROM ticket_settlements
        WHERE ticket_source = 'simulation'
          AND ticket_id = source_ticket.id
        FOR UPDATE;
        has_settlement := FOUND;

        IF has_settlement THEN
            remaining_stake := source_settlement.stake_amount;
            remaining_prize := source_settlement.prize_amount;
            remaining_tax := source_settlement.tax_amount;
            remaining_net := source_settlement.net_prize;
            remaining_profit := source_settlement.profit_loss;
        END IF;

        WHILE remaining_multiple > 0 LOOP
            part_multiple := LEAST(50, remaining_multiple);
            part_index := part_index + 1;
            part_metadata := COALESCE(source_ticket.rule_metadata, '{}'::JSONB)
                || jsonb_build_object(
                    'physical_ticket_split', jsonb_build_object(
                        'original_multiple', original_multiple,
                        'part_index', part_index,
                        'part_count', part_count,
                        'single_ticket_max_multiple', 50
                    )
                );

            IF has_settlement THEN
                IF remaining_multiple = part_multiple THEN
                    part_stake := remaining_stake;
                    part_prize := remaining_prize;
                    part_tax := remaining_tax;
                    part_net := remaining_net;
                    part_profit := remaining_profit;
                ELSE
                    part_stake := ROUND(source_settlement.stake_amount * part_multiple / original_multiple, 2);
                    part_prize := ROUND(source_settlement.prize_amount * part_multiple / original_multiple, 2);
                    part_tax := ROUND(source_settlement.tax_amount * part_multiple / original_multiple, 2);
                    part_net := ROUND(source_settlement.net_prize * part_multiple / original_multiple, 2);
                    part_profit := ROUND(source_settlement.profit_loss * part_multiple / original_multiple, 2);
                END IF;
                remaining_stake := remaining_stake - part_stake;
                remaining_prize := remaining_prize - part_prize;
                remaining_tax := remaining_tax - part_tax;
                remaining_net := remaining_net - part_net;
                remaining_profit := remaining_profit - part_profit;
                part_detail := jsonb_set(
                    COALESCE(source_settlement.settlement_detail_json, '{}'::JSONB),
                    '{multiple}', to_jsonb(part_multiple), true
                );
            END IF;

            IF part_index = 1 THEN
                UPDATE simulation_tickets
                SET multiple = part_multiple,
                    suggested_stake = ROUND(source_ticket.suggested_stake * part_multiple / original_multiple, 2),
                    estimated_return = CASE WHEN source_ticket.estimated_return IS NULL THEN NULL ELSE ROUND(source_ticket.estimated_return * part_multiple / original_multiple, 2) END,
                    max_return = CASE WHEN source_ticket.max_return IS NULL THEN NULL ELSE ROUND(source_ticket.max_return * part_multiple / original_multiple, 2) END,
                    rule_metadata = part_metadata
                WHERE id = source_ticket.id;

                IF has_settlement THEN
                    UPDATE ticket_settlements
                    SET stake_amount = part_stake,
                        prize_amount = part_prize,
                        tax_amount = part_tax,
                        net_prize = part_net,
                        profit_loss = part_profit,
                        roi = CASE WHEN part_stake > 0 THEN part_profit / part_stake ELSE 0 END,
                        settlement_detail_json = part_detail
                    WHERE id = source_settlement.id;
                END IF;
            ELSE
                INSERT INTO simulation_tickets (
                    budget_plan_id, strategy_pool, ticket_type, pass_type,
                    suggested_stake, multiple, estimated_return, max_return,
                    expected_value, risk_level, ticket_status, bet_count,
                    rule_metadata, created_at
                ) VALUES (
                    source_ticket.budget_plan_id, source_ticket.strategy_pool,
                    source_ticket.ticket_type, source_ticket.pass_type,
                    ROUND(source_ticket.suggested_stake * part_multiple / original_multiple, 2),
                    part_multiple,
                    CASE WHEN source_ticket.estimated_return IS NULL THEN NULL ELSE ROUND(source_ticket.estimated_return * part_multiple / original_multiple, 2) END,
                    CASE WHEN source_ticket.max_return IS NULL THEN NULL ELSE ROUND(source_ticket.max_return * part_multiple / original_multiple, 2) END,
                    source_ticket.expected_value, source_ticket.risk_level,
                    source_ticket.ticket_status, source_ticket.bet_count,
                    part_metadata, source_ticket.created_at
                )
                RETURNING id INTO new_ticket_id;

                INSERT INTO simulation_ticket_items (
                    ticket_id, match_id, odds_snapshot_id, model_prediction_id,
                    feature_snapshot_id, play_type, option_code, option_name,
                    sp_value, model_probability, market_probability, ev,
                    confidence_score, risk_score, is_dan, odds_source, created_at
                )
                SELECT new_ticket_id, match_id, odds_snapshot_id, model_prediction_id,
                       feature_snapshot_id, play_type, option_code, option_name,
                       sp_value, model_probability, market_probability, ev,
                       confidence_score, risk_score, is_dan, odds_source, created_at
                FROM simulation_ticket_items
                WHERE ticket_id = source_ticket.id;

                IF has_settlement THEN
                    INSERT INTO ticket_settlements (
                        ticket_source, ticket_id, settle_time, is_won,
                        stake_amount, prize_amount, tax_amount, net_prize,
                        profit_loss, roi, settlement_detail_json, created_at
                    ) VALUES (
                        source_settlement.ticket_source, new_ticket_id,
                        source_settlement.settle_time, source_settlement.is_won,
                        part_stake, part_prize, part_tax, part_net, part_profit,
                        CASE WHEN part_stake > 0 THEN part_profit / part_stake ELSE 0 END,
                        part_detail, source_settlement.created_at
                    );
                END IF;
            END IF;

            remaining_multiple := remaining_multiple - part_multiple;
        END LOOP;
    END LOOP;
END;
$$;
