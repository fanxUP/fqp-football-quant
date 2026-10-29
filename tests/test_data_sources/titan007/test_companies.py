import sqlite3

from scripts.sources.titan007 import companies


def test_sync_companies_seeds_tiers(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    counts = companies.sync_companies(conn)
    assert counts["tier1"] >= 8
    assert counts["tier2"] >= 7
    assert counts["china_lottery"] == 1
    row = conn.execute("SELECT tier, brand FROM odds_companies WHERE company_id=177").fetchone()
    assert row["tier"] == "tier1" and row["brand"] == "Pinnacle"
    row = conn.execute("SELECT tier FROM odds_companies WHERE company_id=3").fetchone()
    assert row["tier"] == "tier2"
    row = conn.execute("SELECT tier, category FROM odds_companies WHERE company_id=0").fetchone()
    assert row["tier"] == "china_lottery" and row["category"] == "lottery"
    companies.sync_companies(conn)
    assert (
        conn.execute("SELECT COUNT(*) FROM odds_companies WHERE company_id=177").fetchone()[0] == 1
    )
