import json

from scripts.local.startup_preflight import evaluate_checks


def test_preflight_blocks_only_on_hard_failures() -> None:
    report = evaluate_checks(
        [
            {"name": "postgres", "ok": True, "blocking": True, "detail": "SELECT 1"},
            {"name": "redis", "ok": True, "blocking": True, "detail": "PONG"},
            {"name": "disk", "ok": True, "blocking": True, "detail": "52%"},
            {"name": "external_api", "ok": False, "blocking": False, "detail": "DNS timeout"},
        ]
    )

    assert report["status"] == "degraded"
    assert report["blocking_failures"] == []
    assert report["warnings"] == ["external_api"]


def test_preflight_blocks_business_start_on_hard_failure() -> None:
    report = evaluate_checks(
        [
            {"name": "postgres", "ok": False, "blocking": True, "detail": "connection refused"},
            {"name": "redis", "ok": True, "blocking": True, "detail": "PONG"},
        ]
    )

    assert report["status"] == "blocked"
    assert report["blocking_failures"] == ["postgres"]


def test_preflight_json_is_machine_readable() -> None:
    report = evaluate_checks(
        [{"name": "clock", "ok": True, "blocking": True, "detail": "synchronized"}]
    )

    encoded = json.dumps(report, ensure_ascii=False)
    assert json.loads(encoded)["status"] == "ready"
