SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

LOCK TABLE player_identity_links, player_identity_link_events IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM player_identity_links)
       OR EXISTS (SELECT 1 FROM player_identity_link_events) THEN
        RAISE EXCEPTION 'identity mappings exist; keep migration 134 to preserve player identity decisions';
    END IF;
END
$$;

DROP TABLE player_identity_link_events;
DROP TABLE player_identity_links;
DROP FUNCTION record_player_identity_link_event();
DROP FUNCTION guard_player_identity_link();
DROP FUNCTION reject_player_identity_event_mutation();
DROP FUNCTION player_identity_evidence_refs_valid(JSONB);
