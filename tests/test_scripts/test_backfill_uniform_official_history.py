from datetime import date

from scripts.backfill_uniform_official_history import (
    build_artifact,
    month_chunks,
)


def test_month_chunks_split_a_cross_month_range():
    assert list(month_chunks(date(2026, 6, 29), date(2026, 7, 2))) == [
        ("2026-06-29", "2026-06-30"),
        ("2026-07-01", "2026-07-02"),
    ]


def test_build_artifact_preserves_exact_official_response_and_request_metadata():
    response = {"errorCode": 0, "value": {"matchResult": [{"matchId": 2040456}]}}

    artifact = build_artifact(
        response=response,
        request_params={"matchBeginDate": "2026-07-10", "matchEndDate": "2026-07-10"},
        request_url="https://webapi.sporttery.cn/gateway/uniform/football/getUniformMatchResultV1.qry?x",
        retrieved_at="2026-07-11T20:00:00+08:00",
    )

    assert artifact["source_name"] == "sporttery"
    assert artifact["request_params"]["matchBeginDate"] == "2026-07-10"
    assert artifact["response"] == response
