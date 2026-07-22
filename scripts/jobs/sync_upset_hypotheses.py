"""Extract evidence-backed research hypotheses without auto-promoting them."""

from __future__ import annotations

from typing import Any

from apps.backend.src.db import get_db
from scripts.upset.hypotheses import extract_review_hypotheses


def run() -> dict[str, Any]:
    with get_db() as conn:
        return extract_review_hypotheses(conn)


if __name__ == "__main__":
    print(run())
