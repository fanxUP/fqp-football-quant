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

    response = client.get("/api/news-intelligence/events?matchId=31&limit=20&offset=0")

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
