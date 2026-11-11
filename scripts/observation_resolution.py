"""Resolve field claims from a frozen cutoff, without writes or source access.

A selection is a versioned policy decision, not truth, access authorization,
source independence proof, a completeness guarantee or model eligibility.
"""

from __future__ import annotations

import hashlib
import math
import re
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from scripts.data_catalog import get_data_source, get_field_resolution_policy
from scripts.data_contracts import FactStatus, to_utc
from scripts.observation_storage import (
    ObservationCutoff,
    _canonical,
    load_cutoff_observations,
    load_observation_selection,
)

_FIELDS = {
    "weather.temperature_2m": ("weather", "forecast", "temperature_2m/v1"),
    "lineup.starters": ("lineup", "team", "lineup.starters/v1"),
    "injuries.complete_report": ("injuries", "team", "injuries.complete_report/v1"),
}
_VERSION = re.compile(r"[a-z0-9][a-z0-9_./-]{0,63}\Z")
_TEAM = re.compile(r"team:([1-9][0-9]{0,18})\Z")


def _rule(policy: Any, field: str) -> dict:
    if not isinstance(policy, dict) or set(policy) != {
        "version",
        "field",
        "domain",
        "subject",
        "extractor",
        "max_age_seconds",
        "sources",
    }:
        raise ValueError("field policy requires its complete versioned snapshot")
    if field not in _FIELDS or policy["field"] != field:
        raise ValueError("unsupported field policy")
    if (policy["domain"], policy["subject"], policy["extractor"]) != _FIELDS[field]:
        raise ValueError("field policy domain/subject/extractor mismatch")
    if not isinstance(policy["version"], str) or not _VERSION.fullmatch(policy["version"]):
        raise ValueError("field policy requires a bounded version")
    if type(policy["max_age_seconds"]) is not int or not 1 <= policy["max_age_seconds"] <= 86400:
        raise ValueError("field policy requires a bounded freshness window")
    sources = policy["sources"]
    if not isinstance(sources, dict) or not 1 <= len(sources) <= 16:
        raise ValueError("field policy requires explicit source priorities")
    for source, rank in sources.items():
        if not isinstance(source, str) or type(rank) is not int or not 1 <= rank <= 100:
            raise ValueError("field policy source priority must be an integer")
        get_data_source(source)  # Registry identity only, never coverage or runtime permission.
    _canonical(policy, 8192)
    return deepcopy(policy)


def _aware(value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("resolution timing requires aware timestamps")
    return to_utc(value)


def _coverage(evidence: Any) -> bool:
    return (
        isinstance(evidence, dict)
        and evidence.get("coverage_complete") is True
        and isinstance(evidence.get("coverage_evidence"), str)
        and bool(evidence["coverage_evidence"].strip())
        and len(evidence["coverage_evidence"]) <= 256
    )


def _extract(value: Any, rule: dict, subject: str) -> Any:
    if not isinstance(value, dict):
        raise ValueError("field requires a structured source claim")
    if rule["field"] == "weather.temperature_2m":
        number = value.get("temperature_2m")
        # Explicit v1 input sanity range in Celsius, not a derived weather score.
        if (
            not isinstance(number, (int, float))
            or isinstance(number, bool)
            or not math.isfinite(number)
            or not -100 <= number <= 70
        ):
            raise ValueError("invalid Celsius temperature")
        return float(number) if number else 0.0
    team = _TEAM.fullmatch(subject)
    if team is None or type(value.get("team_id")) is not int or value["team_id"] != int(team[1]):
        raise ValueError("field claim belongs to another canonical team")
    players = value.get("players")
    limit = 64 if rule["domain"] == "lineup" else 128
    if not isinstance(players, list) or not 1 <= len(players) <= limit:
        raise ValueError("field requires a bounded nonempty roster")
    ids = []
    for player in players:
        if (
            not isinstance(player, dict)
            or type(player.get("player_id")) is not int
            or player["player_id"] <= 0
        ):
            raise ValueError("field requires canonical player identities")
        ids.append(player["player_id"])
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate canonical player identity")
    if rule["domain"] == "lineup":
        if any(type(p.get("is_starting")) is not bool for p in players):
            raise ValueError("lineup requires explicit starter flags")
        starters = sorted(p["player_id"] for p in players if p["is_starting"])
        if len(starters) != 11:
            raise ValueError("lineup requires eleven distinct starters")
        return starters
    if any(
        p.get(key) is not None and not isinstance(p[key], str)
        for p in players
        for key in ("reported_type", "reported_reason")
    ):
        raise ValueError("injury report requires raw text or explicit unknown")
    return sorted(
        [
            dict(
                player_id=p["player_id"],
                reported_type=p.get("reported_type"),
                reported_reason=p.get("reported_reason"),
            )
            for p in players
        ],
        key=lambda p: p["player_id"],
    )


def _candidate(
    index: int, ref: dict, obs: dict | None, rule: dict, at: datetime, subject: str
) -> dict:
    result = dict(
        index=index,
        source_id=ref["source_id"],
        source_family=ref["source_family"],
        revision_id=ref["revision_id"],
        latest_check_id=ref["latest_check_id"],
        freshness_check_id=ref["freshness_check_id"],
        priority=rule["sources"].get(ref["source_id"]),
        value=None,
        fact_status="unknown",
        acquisition_status=None,
        content_hash=None,
        effective_at=None,
        last_success_acquired_at=None,
        expires_at=None,
        reason="missing",
        asserted=False,
    )
    if obs is not None:
        result.update(
            acquisition_status=obs["acquisition_status"], content_hash=obs["content_hash"]
        )
    if result["priority"] is None:
        result["reason"] = "source_not_admitted"
        return result
    if obs is None or obs["revision_id"] is None:
        return result
    if obs["evidence_kind"] != "source_observation":
        result["reason"] = "not_source_observation"
        return result
    status = FactStatus(obs["original_fact_status"]).value
    result["fact_status"] = status
    try:
        checked = _aware(obs["last_success_acquired_at"])
        if checked > at or _aware(obs["available_at"]) > at:
            raise ValueError("future acquisition")
        expires = checked + timedelta(seconds=rule["max_age_seconds"])
        if obs["valid_until"] is not None:
            expires = min(expires, _aware(obs["valid_until"]))
    except ValueError, KeyError, OverflowError:
        result.update(reason="invalid_timing", fact_status="unknown")
        return result
    result.update(last_success_acquired_at=checked.isoformat(), expires_at=expires.isoformat())
    if at >= expires:
        result.update(reason="stale", fact_status="stale")
        return result
    if status == "conflict":
        result.update(reason="source_conflict", asserted=True)
        return result
    if status not in {"value", "confirmed_absent"}:
        result["reason"] = status
        return result
    if rule["domain"] == "injuries" and not _coverage(obs["evidence"]):
        result.update(reason="coverage_unverified", fact_status="unknown")
        return result
    if status == "confirmed_absent":
        if rule["domain"] != "injuries" or obs["value"] is not None:
            result.update(reason="invalid_field_value", fact_status="unknown")
            return result
    else:
        try:
            if rule["domain"] == "weather":
                result["effective_at"] = _aware(obs.get("effective_at")).isoformat()
            result["value"] = _extract(obs["value"], rule, subject)
        except ValueError, OverflowError:
            result.update(reason="invalid_field_value", fact_status="unknown")
            return result
    result.update(reason="eligible", asserted=True)
    return result


def resolve_observed_field(
    conn: Any,
    *,
    cutoff: ObservationCutoff,
    match_id: int,
    subject_key: str,
    field: str,
    policy: dict | None = None,
) -> dict:
    """Read one field using exact cutoff refs and a trusted internal policy.

    Persist/retain the returned policy snapshot with a consumer decision for
    replay; the default catalog may change. A supplied historical policy is
    not an end-user override or authorization mechanism. No commit or writes.
    """
    if not isinstance(cutoff, ObservationCutoff) or cutoff.include_reconstruction:
        raise ValueError("research cutoffs cannot resolve runtime fields")
    at = _aware(cutoff.as_of)
    if type(match_id) is not int or match_id <= 0:
        raise ValueError("field requires a canonical match")
    rule = _rule(policy if policy is not None else get_field_resolution_policy(field), field)
    if not isinstance(subject_key, str) or (
        subject_key != "forecast"
        if rule["subject"] == "forecast"
        else not _TEAM.fullmatch(subject_key)
    ):
        raise ValueError("field requires its declared canonical subject")
    selections = load_observation_selection(conn, cutoff)
    observations = load_cutoff_observations(conn, cutoff)
    if len(selections) != len(observations):
        raise ValueError("cutoff observation selection mismatch")
    scoped = [
        (i, r, observations[i])
        for i, r in enumerate(selections)
        if r["match_id"] == match_id
        and r["domain"] == rule["domain"]
        and r["subject_key"] == subject_key
    ]
    if not set(rule["sources"]) <= {r["source_id"] for _, r, _ in scoped}:
        raise ValueError(
            "all policy sources must be declared in the cutoff, including missing streams"
        )
    candidates = [_candidate(i, ref, obs, rule, at, subject_key) for i, ref, obs in scoped]
    eligible = [c for c in candidates if c["asserted"]]
    selected: list[int] = []
    disagreements: list[int] = []
    value = None
    if eligible:
        best = min(c["priority"] for c in eligible)
        leading = [c for c in eligible if c["priority"] == best]
        claims = {_claim(c) for c in leading}
        if len(claims) != 1 or any(c["fact_status"] == "conflict" for c in leading):
            status = "conflict"
            for c in leading:
                c["reason"] = "equal_authority_conflict"
        else:
            status = leading[0]["fact_status"]
            value = deepcopy(leading[0]["value"])
            selected = [c["index"] for c in leading]
            for c in leading:
                c["reason"] = "selected"
        for c in eligible:
            if c["priority"] != best:
                c["reason"] = "lower_authority"
                if len(claims) != 1 or _claim(c) not in claims:
                    disagreements.append(c["index"])
    else:
        admitted = [c for c in candidates if c["priority"] is not None]
        best = min(c["priority"] for c in admitted)
        states = {c["fact_status"] for c in admitted if c["priority"] == best}
        status = next(iter(states)) if len(states) == 1 else "unknown"
    return dict(
        field=field,
        match_id=match_id,
        subject_key=subject_key,
        cutoff_id=cutoff.id,
        as_of=at.isoformat(),
        policy=rule,
        policy_hash=hashlib.sha256(_canonical(rule, 8192).encode()).hexdigest(),
        fact_status=status,
        value=value,
        selected_indexes=selected,
        selected_family_count=len(
            {c["source_family"] for c in candidates if c["index"] in selected}
        ),
        disagreement_indexes=disagreements,
        candidates=candidates,
    )


def _claim(candidate: dict) -> str:
    # Forecasts for different business target times are not equivalent claims.
    # Future targets remain valid: availability was already checked at cutoff.
    return _canonical(
        [candidate["fact_status"], candidate["value"], candidate["effective_at"]], 131072
    )
