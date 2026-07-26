from datetime import date

from scripts.competition_storage import compute_user_daily_stats


class _Cursor:
    def __init__(self, owner):
        self.owner = owner
        self.rows = []

    def execute(self, sql, params):
        self.owner.sql.append(sql)
        if "ticket_settlements" in sql:
            self.rows = [(8, 2)]
        else:
            self.rows = [(30, 2)]

    def fetchone(self):
        return self.rows[0]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Connection:
    def __init__(self):
        self.sql = []

    def cursor(self):
        return _Cursor(self)


def test_user_competition_stats_include_real_and_simulator_tickets():
    conn = _Connection()

    stats = compute_user_daily_stats(conn, date(2026, 7, 14))

    assert "real_tickets" in conn.sql[0]
    assert "simulator_tickets" in conn.sql[0]
    assert "ticket_source IN ('real', 'simulator')" in conn.sql[1]
    assert all("AT TIME ZONE 'Asia/Shanghai'" in sql for sql in conn.sql)
    assert stats["daily_stake"] == 30.0
    assert stats["ticket_count"] == 2
