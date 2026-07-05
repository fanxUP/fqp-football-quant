"""Play-type registry — canonical single source of truth.

体彩 5 种核心竞彩玩法 (official lottery play types):
  SPF   = spf   — 胜平负 (Win/Draw/Loss)
  RQSPF = rqspf — 让球胜平负 (Asian Handicap Win/Draw/Loss)
  BF    = bf    — 比分 (Correct Score)
  ZJQ   = zjq   — 总进球数 (Total Goals)
  BQC   = bqc   — 半全场 (Half-Time/Full-Time)

传统足彩 (traditional football lottery) game types:
  T14C  = t14c  — 胜负游戏/14场 (Pick 14 match outcomes)
  R9    = r9    — 任选9场 (Choose 9 out of 14)
  BQC6  = bqc6  — 6场半全场 (6-match half/full)
  JQ4   = jq4   — 4场进球 (4-match correct score)
"""

from __future__ import annotations

# ── Canonical 竞彩 play-type codes ──────────────────────────────────

CANONICAL_CODES = ("spf", "rqspf", "bf", "zjq", "bqc")

# ── Traditional lottery game type codes ─────────────────────────────

TRADITIONAL_GAME_TYPES: dict[int, str] = {
    90: "t14c",   # 胜负游戏（14场）
    91: "r9",     # 任选9场
    98: "bqc6",   # 6场半全场
    99: "jq4",    # 4场进球
}

TRADITIONAL_GAME_LABELS: dict[str, str] = {
    "t14c": "胜负游戏 14场",
    "r9": "任选9场",
    "bqc6": "6场半全场",
    "jq4": "4场进球",
}

# ── Sporttery poolCode → canonical code ───────────────────────────────

SPORTTERY_POOL_MAP: dict[str, str] = {
    "HAD": "spf",
    "HHAD": "rqspf",
    "CRS": "bf",
    "TTG": "zjq",
    "HAFU": "bqc",
}

# ── Code alias map (anything → canonical) ─────────────────────────────

_ALIASES: dict[str, str] = {
    # canonical → self
    "spf": "spf",
    "rqspf": "rqspf",
    "bf": "bf",
    "zjq": "zjq",
    "bqc": "bqc",
    # legacy aliases (backward compat)
    "score": "bf",
    "total_goals": "zjq",
    "half_full": "bqc",
    "HAD": "spf",
    "HHAD": "rqspf",
    "CRS": "bf",
    "TTG": "zjq",
    "HAFU": "bqc",
}

# ── Canonical code → Chinese display name ─────────────────────────────

PLAY_TYPE_LABELS: dict[str, str] = {
    "spf": "胜平负",
    "rqspf": "让球胜平负",
    "bf": "比分",
    "zjq": "总进球数",
    "bqc": "半全场",
    "hhgg": "混合过关",
}

# ── Canonical code → option labels (h/d/a style) ──────────────────────

OPTION_LABELS: dict[str, dict[str, str]] = {
    "spf": {"h": "主胜", "d": "平", "a": "客胜"},
    "rqspf": {"h": "让球主胜", "d": "让球平", "a": "让球客胜"},
}

# ── Canonical code → official_results column name ─────────────────────

RESULT_COLUMN_MAP: dict[str, str] = {
    "spf": "spf_result",
    "rqspf": "rqspf_result",
    "bf": "score_result",
    "zjq": "total_goals_result",
    "bqc": "half_full_result",
}

# ── Canonical code → max matches for single pass ──────────────────────

MAX_MATCHES: dict[str, int] = {
    "spf": 8,
    "rqspf": 8,
    "bf": 4,
    "zjq": 6,
    "bqc": 4,
}

# ── Helper functions ──────────────────────────────────────────────────


def normalize(code: str) -> str:
    """Convert any play-type code (canonical, legacy, sporttery) to canonical.

    >>> normalize('score')
    'bf'
    >>> normalize('CRS')
    'bf'
    >>> normalize('bf')
    'bf'
    """
    return _ALIASES.get(code, code.lower())


def label(code: str) -> str:
    """Get Chinese display name for a play-type code."""
    return PLAY_TYPE_LABELS.get(normalize(code), code)


def result_column(code: str) -> str:
    """Get the official_results column name for a play type."""
    return RESULT_COLUMN_MAP.get(normalize(code), "")


def max_matches(code: str) -> int:
    """Get max matches allowed in a single pass for this play type."""
    return MAX_MATCHES.get(normalize(code), 8)


def canonical_option(code: str, option_code: str) -> str:
    """Map any option code to the canonical display name.

    For SPF/RQSPF:
      'h'/'3' → '主胜', 'd'/'1' → '平', 'a'/'0' → '客胜'

    For BF/ZJQ/BQC the option_code is already the display value
    (e.g. "1:0", "3", "33").
    """
    pt = normalize(code)
    opt_map = OPTION_LABELS.get(pt, {})
    return opt_map.get(option_code, option_code)


def is_valid(code: str) -> bool:
    """Check if a code maps to a known canonical play type."""
    return normalize(code) in CANONICAL_CODES
