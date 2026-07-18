from datetime import datetime

from apps.backend.src.routers import dashboard


def test_dashboard_metadata_uses_business_timezone(monkeypatch):
    monkeypatch.setattr(
        dashboard,
        "business_now",
        lambda: datetime.fromisoformat("2026-07-18T13:30:00+08:00"),
    )

    assert dashboard._meta("view") == {
        "updated_at": "2026-07-18T13:30:00+08:00",
        "source": "view",
    }
