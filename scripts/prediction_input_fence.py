"""Event-version fence for existing model consumers, not observed-input proof.

Capture before reading model inputs; never capture a replacement after computing.
P105 mode revisions and P106 model/run provenance remain separate contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scripts.prediction_input_revisions import _read_transaction
from scripts.prediction_input_updates import InputUpdateSuperseded


@dataclass(frozen=True)
class PredictionInputFence:
    match_id: int
    input_version: int | None

    def __post_init__(self) -> None:
        if type(self.match_id) is not int or self.match_id <= 0:
            raise ValueError("positive match ID required")
        if self.input_version is not None and (
            type(self.input_version) is not int or self.input_version <= 0
        ):
            raise ValueError("positive input version or explicit absent head required")

    def payload(self) -> dict:
        return dict(
            schema_version="prediction-input-fence/v1",
            match_id=self.match_id,
            input_version=self.input_version,
        )


def capture_prediction_input_fence(conn: Any, match_id: int) -> PredictionInputFence:
    """Capture the optional head once, before odds/features/expensive computation."""
    PredictionInputFence(match_id, None)
    _read_transaction(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT d.input_version FROM official_matches m "
            "LEFT JOIN prediction_input_dirty_matches d ON d.match_id=m.id WHERE m.id=%s",
            (match_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError("official match is absent")
    return PredictionInputFence(match_id, row[0])


def bind_prediction_input_fence(
    conn: Any, match_id: int, token: PredictionInputFence, *, odds_snapshot_id: int | None = None
) -> dict:
    """Check and lock the head until the caller's prediction insert commits.

    No head yet has no row lock; a concurrent first observation is still caught
    by the authoritative read gate as soon as that observation commits.
    """
    if not isinstance(token, PredictionInputFence) or token.match_id != match_id:
        raise ValueError("internal token for the prediction match required")
    _read_transaction(conn)
    with conn.cursor() as cur:
        # Bound publication waits even if the caller/role has no lock timeout;
        # keep an existing stricter limit. SET LOCAL ends at commit/rollback.
        cur.execute(
            "SELECT set_config('lock_timeout',CASE WHEN setting::int=0 THEN '500ms' "
            "ELSE LEAST(setting::int,500)::text || 'ms' END,true) "
            "FROM pg_settings WHERE name='lock_timeout'"
        )
        # FK key locks precede the head lock: official writes own their row
        # before their AFTER trigger updates the head.
        cur.execute("SELECT id FROM official_matches WHERE id=%s FOR KEY SHARE", (match_id,))
        if cur.fetchone() is None:
            raise ValueError("official match is absent")
        if odds_snapshot_id is not None:
            cur.execute(
                "SELECT id FROM official_odds_snapshots WHERE id=%s AND match_id=%s FOR KEY SHARE",
                (odds_snapshot_id, match_id),
            )
            if cur.fetchone() is None:
                raise ValueError("official odds for prediction match required")
        cur.execute(
            "SELECT input_version FROM prediction_input_dirty_matches WHERE match_id=%s FOR SHARE",
            (match_id,),
        )
        row = cur.fetchone()
    if (row[0] if row else None) != token.input_version:
        raise InputUpdateSuperseded("prediction inputs changed during computation")
    return token.payload()


# Fixed internal alias mp. Compare complete JSON objects without casting legacy
# JSON values to integers/booleans. An observed match always requires a token;
# only an absent head permits an unbound historical prediction.
CURRENT_PREDICTION_INPUT_SQL = """
    current_setting('transaction_isolation')='read committed' AND COALESCE((
        SELECT (mp.uncertainty_reason->'input_fence') IS NOT DISTINCT FROM
            jsonb_build_object('schema_version','prediction-input-fence/v1',
                'match_id',mp.match_id,'input_version',d.input_version)
        FROM prediction_input_dirty_matches d WHERE d.match_id=mp.match_id
    ), (
        mp.uncertainty_reason->'input_fence' IS NULL
        OR mp.uncertainty_reason->'input_fence' = jsonb_build_object(
            'schema_version','prediction-input-fence/v1',
            'match_id',mp.match_id,'input_version',NULL)
    ))
"""
