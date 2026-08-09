"""贝叶斯近期状态影子模型：仅从已结算的赛前历史构造胜平负概率。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

MIN_TEAM_MATCHES = 6
MAX_TEAM_MATCHES = 12

# 轻微主场先验，防止少量近期赛果把单场概率推到极端。
TEAM_OUTCOME_PRIOR = {"3": 1.3, "1": 1.2, "0": 1.0}


def _posterior(outcomes: Sequence[str]) -> dict[str, float] | None:
    if len(outcomes) < MIN_TEAM_MATCHES:
        return None
    counts = Counter(outcome for outcome in outcomes[:MAX_TEAM_MATCHES] if outcome in TEAM_OUTCOME_PRIOR)
    if sum(counts.values()) < MIN_TEAM_MATCHES:
        return None
    total = sum(TEAM_OUTCOME_PRIOR.values()) + sum(counts.values())
    return {
        code: (TEAM_OUTCOME_PRIOR[code] + counts[code]) / total
        for code in ("3", "1", "0")
    }


def probabilities_from_team_outcomes(
    home_outcomes: Sequence[str], away_outcomes: Sequence[str]
) -> dict[str, float] | None:
    """Blend two Dirichlet-smoothed form distributions into match 1x2 codes.

    Each input is from its own team's viewpoint. Away wins therefore map to
    match-level 客胜, avoiding a home/away reversal in the prediction pipeline.
    """
    home = _posterior(home_outcomes)
    away = _posterior(away_outcomes)
    if home is None or away is None:
        return None
    away_as_match = {"3": away["0"], "1": away["1"], "0": away["3"]}
    raw = {
        code: (home[code] ** 0.55) * (away_as_match[code] ** 0.45)
        for code in ("3", "1", "0")
    }
    total = sum(raw.values())
    home_win = round(raw["3"] / total, 8)
    draw = round(raw["1"] / total, 8)
    return {"3": home_win, "1": draw, "0": round(1.0 - home_win - draw, 8)}
