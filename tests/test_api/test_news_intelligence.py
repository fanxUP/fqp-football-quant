from apps.backend.src.routers import news_intelligence


def test_news_overview_returns_read_only_operational_summary(client, monkeypatch) -> None:
    payload = {
        "articleCount": 12,
        "linkedMatchCount": 4,
        "sourceCount": 3,
        "healthySourceCount": 2,
        "lastCapturedAt": "2026-08-11T01:00:00+00:00",
        "productionFeatureEnabled": False,
    }
    monkeypatch.setattr(news_intelligence, "get_news_overview", lambda _conn: payload)

    response = client.get("/api/news-intelligence/overview")

    assert response.status_code == 200
    assert response.json() == {"overview": payload}


def test_news_articles_are_filterable_by_official_match(client, monkeypatch) -> None:
    items = [{
        "id": 7,
        "matchId": 31,
        "officialMatchCode": "周一101",
        "sourceName": "测试俱乐部官网",
        "sourceLevel": "S",
        "title": "球队公告",
        "canonicalUrl": "https://club.example/news/7",
        "publishedAt": "2026-08-10T08:00:00+00:00",
        "availableAt": "2026-08-10T08:05:00+00:00",
    }]
    monkeypatch.setattr(
        news_intelligence,
        "list_news_articles",
        lambda _conn, **_kwargs: (items, 1),
    )

    response = client.get("/api/news-intelligence/articles?matchId=31&limit=20&offset=0")

    assert response.status_code == 200
    assert response.json()["items"] == items
    assert response.json()["total"] == 1


def test_news_sources_do_not_expose_provider_secrets(client, monkeypatch) -> None:
    sources = [{
        "id": 2,
        "sourceCode": "club-official",
        "sourceName": "俱乐部官网",
        "sourceLevel": "S",
        "enabled": True,
        "lastSuccessAt": None,
        "lastError": None,
    }]
    monkeypatch.setattr(news_intelligence, "list_news_sources", lambda _conn: sources)

    response = client.get("/api/news-intelligence/sources")

    assert response.status_code == 200
    assert response.json() == {"sources": sources, "total": 1}
    assert "apiKey" not in response.text
    assert "secret" not in response.text.lower()


def test_structured_news_events_expose_evidence_and_verification(client, monkeypatch) -> None:
    events = [{
        "id": 9,
        "eventType": "injury",
        "direction": "negative",
        "verificationStatus": "verified",
        "officialMatchCode": "周一101",
        "summary": "主队核心球员确认缺阵",
        "sourceCount": 2,
    }]
    monkeypatch.setattr(news_intelligence, "list_news_events", lambda _conn, **_kwargs: (events, 1))

    response = client.get("/api/news-intelligence/events?matchId=31")

    assert response.status_code == 200
    assert response.json()["items"] == events
    assert response.json()["total"] == 1


def test_event_verification_is_an_explicit_human_action(client, monkeypatch) -> None:
    event = {"id": 9, "verificationStatus": "verified", "reviewNote": "已核对俱乐部公告"}
    monkeypatch.setattr(
        news_intelligence,
        "review_news_event",
        lambda _conn, **_kwargs: event,
    )

    response = client.patch(
        "/api/news-intelligence/events/9/verification",
        json={"status": "verified", "reviewNote": "已核对俱乐部公告"},
    )

    assert response.status_code == 200
    assert response.json() == {"event": event}


def test_source_status_can_be_disabled_without_changing_credentials(client, monkeypatch) -> None:
    source = {"id": 2, "sourceName": "俱乐部官网", "enabled": False}
    monkeypatch.setattr(news_intelligence, "set_news_source_enabled", lambda _conn, **_kwargs: source)

    response = client.patch("/api/news-intelligence/sources/2", json={"enabled": False})

    assert response.status_code == 200
    assert response.json() == {"source": source}


def test_news_feature_snapshots_are_read_only_and_versioned(client, monkeypatch) -> None:
    features = [{
        "snapshotId": 12,
        "matchId": 31,
        "officialMatchCode": "周一101",
        "snapshotLabel": "T45M",
        "snapshotCutoff": "2026-08-11T10:15:00+00:00",
        "homeNetImpact": -0.72,
        "awayNetImpact": 0.4,
        "verifiedEventCount": 2,
        "featureVersion": "news-features-v1",
    }]
    monkeypatch.setattr(
        news_intelligence,
        "list_news_feature_snapshots",
        lambda _conn, **_kwargs: (features, 1),
    )

    response = client.get("/api/news-intelligence/features?matchId=31")

    assert response.status_code == 200
    assert response.json()["items"] == features
    assert response.json()["total"] == 1
