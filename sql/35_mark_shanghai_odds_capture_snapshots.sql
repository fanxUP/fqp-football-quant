-- The first durable capture batches were written with Shanghai wall-clock
-- snapshot_time before the explicit timezone marker was added. Match them to
-- their durable batch attempt and mark only that narrow deployment window.
UPDATE official_odds_snapshots snapshot
SET raw_json = COALESCE(snapshot.raw_json, '{}'::jsonb)
               || '{"_collector_timezone":"Asia/Shanghai"}'::jsonb
FROM official_odds_capture_batches batch
WHERE batch.match_id = snapshot.match_id
  AND batch.status = 'complete'
  AND snapshot.raw_json->>'_collector_timezone' IS NULL
  AND snapshot.snapshot_time BETWEEN
      timezone('Asia/Shanghai', batch.attempted_at) - INTERVAL '2 minutes'
      AND timezone('Asia/Shanghai', batch.attempted_at) + INTERVAL '2 minutes';
