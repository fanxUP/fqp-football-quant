"""Run the isolated news shadow comparison; never writes formal predictions."""

from __future__ import annotations

from typing import Any

from apps.backend.src.db import get_db
from scripts.news_shadow_storage import evaluate_shadow_predictions, generate_shadow_predictions


def run() -> dict[str, Any]:
    with get_db() as conn:
        predictions = generate_shadow_predictions(conn)
        evaluations = evaluate_shadow_predictions(conn)
    return {"status": "ok", "predictionsCreated": predictions, "evaluationsCreated": evaluations}


if __name__ == "__main__":
    print(run())
