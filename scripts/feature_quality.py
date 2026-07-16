"""Feature coverage scoring and auditable job-quality summaries."""

from __future__ import annotations

from typing import Any

FEATURE_DIMENSIONS = (
    "odds",
    "team_mapping",
    "team_profile",
    "lineup",
    "injury",
    "rotation",
    "travel",
    "weather",
    "motivation",
    "tournament",
)


def compute_full_completeness(dimensions: dict[str, bool]) -> dict[str, Any]:
    """Score only dimensions backed by usable match-level data."""
    completeness = round(
        sum(10.0 for dimension in FEATURE_DIMENSIONS if dimensions.get(dimension, False)),
        4,
    )
    return {
        "data_completeness_score": completeness,
        "uncertainty_score": round(100.0 - completeness, 4),
        "source_confidence_score": round(completeness / 100.0 * 0.95, 4),
        "missing_dimensions": [
            dimension
            for dimension in FEATURE_DIMENSIONS
            if not dimensions.get(dimension, False)
        ],
    }


def snapshot_job_result(
    *,
    feature_version: str,
    matches_processed: int,
    snapshots_built: int,
    profiles_updated: int,
    dim_stats: dict[str, float],
    failed_matches: list[dict[str, Any]],
) -> dict[str, Any]:
    """Separate execution success from actual feature-data quality."""
    execution_failed = matches_processed > 0 and snapshots_built == 0
    dimension_rates = {
        dimension: round(dim_stats.get(dimension, 0.0) / matches_processed, 4)
        if matches_processed
        else 0.0
        for dimension in FEATURE_DIMENSIONS
    }
    average_completeness = round(
        sum(dimension_rates.values()) / len(FEATURE_DIMENSIONS) * 100,
        1,
    )
    quality_status = (
        "failed"
        if execution_failed
        else "healthy"
        if average_completeness >= 80
        else "degraded"
    )
    return {
        "status": "failed" if execution_failed else "ok",
        "quality_status": quality_status,
        "quality_note": f"平均特征完整度 {average_completeness:.1f}%",
        "average_completeness": average_completeness,
        "feature_version": feature_version,
        "snapshots_built": snapshots_built,
        "profiles_updated": profiles_updated,
        "matches_processed": matches_processed,
        "failed_count": len(failed_matches),
        "failed_matches": failed_matches,
        "dimensions_coverage": {
            dimension: f"{dim_stats.get(dimension, 0.0):g}/{matches_processed}"
            for dimension in FEATURE_DIMENSIONS
        },
        "dimension_rates": dimension_rates,
    }
