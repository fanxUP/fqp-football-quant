-- News Intelligence P6: system-owned trust levels and source switches.
CREATE TABLE IF NOT EXISTS news_source_policies (
    id BIGSERIAL PRIMARY KEY,
    publisher_domain VARCHAR(255) NOT NULL UNIQUE,
    display_name VARCHAR(160) NOT NULL,
    source_level CHAR(1) NOT NULL CHECK (source_level IN ('S', 'A', 'B', 'C', 'D')),
    source_type VARCHAR(32) NOT NULL
        CHECK (source_type IN ('official', 'structured', 'media', 'social')),
    default_language VARCHAR(16),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO news_source_policies (
    publisher_domain, display_name, source_level, source_type, default_language
) VALUES
    ('thecfa.cn', '中国足球协会', 'S', 'official', 'zh'),
    ('fifa.com', 'FIFA', 'S', 'official', 'en'),
    ('uefa.com', 'UEFA', 'S', 'official', 'en'),
    ('the-afc.com', 'AFC', 'S', 'official', 'en'),
    ('premierleague.com', 'Premier League', 'S', 'official', 'en'),
    ('laliga.com', 'LaLiga', 'S', 'official', 'es'),
    ('bundesliga.com', 'Bundesliga', 'S', 'official', 'de'),
    ('legaseriea.it', 'Lega Serie A', 'S', 'official', 'it'),
    ('ligue1.com', 'Ligue 1', 'S', 'official', 'fr'),
    ('reuters.com', 'Reuters', 'A', 'media', 'en'),
    ('news.cn', '新华社', 'A', 'media', 'zh'),
    ('bbc.co.uk', 'BBC Sport', 'B', 'media', 'en'),
    ('theguardian.com', 'The Guardian Football', 'B', 'media', 'en'),
    ('espn.com', 'ESPN', 'B', 'media', 'en'),
    ('skysports.com', 'Sky Sports', 'B', 'media', 'en'),
    ('sports.sina.com.cn', '新浪体育', 'B', 'media', 'zh'),
    ('dongqiudi.com', '懂球帝', 'B', 'media', 'zh'),
    ('sports.163.com', '网易体育', 'C', 'media', 'zh'),
    ('sports.sohu.com', '搜狐体育', 'C', 'media', 'zh')
ON CONFLICT (publisher_domain) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    source_level = EXCLUDED.source_level,
    source_type = EXCLUDED.source_type,
    default_language = EXCLUDED.default_language,
    updated_at = NOW();
