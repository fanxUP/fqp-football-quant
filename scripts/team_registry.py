"""Canonical Sporttery team registry helpers.

Official match names are the identity boundary. Team codes use a stable hash
instead of a visible-name prefix so senior/youth teams cannot collide.
"""

from __future__ import annotations

import hashlib
from typing import Any

from scripts.data_catalog import get_data_source
from scripts.data_contracts import EntityKind, IdentityResolution


def resolve_team_alias(conn: Any, alias_name: str, *, source_name: str) -> IdentityResolution:
    """Read exact source-scoped aliases; preserve missing/ambiguous identity.

    Never mutate mappings, fuzzy-match a display name, or claim an as-of mapping
    revision. Existing aliases lack temporal revision history (P104).
    """
    namespace = get_data_source(source_name)["alias_namespace"]
    if namespace is None:
        raise ValueError(f"source {source_name} has no registered team-alias namespace")
    name = alias_name.strip()
    if not name:
        return IdentityResolution(EntityKind.TEAM, source_name, name, ())
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT t.id FROM teams t
            JOIN team_aliases ta ON ta.team_id = t.id
            WHERE ta.alias_name = %(alias_name)s AND ta.source_name = %(source_name)s
            ORDER BY t.id
            LIMIT 2
            """,
            {"alias_name": name, "source_name": namespace},
        )
        candidates = tuple(row[0] for row in cur.fetchall())
    return IdentityResolution(EntityKind.TEAM, source_name, name, candidates)


def official_team_code(team_name: str) -> str:
    """Return a stable collision-resistant code for one official team name."""
    normalized = team_name.strip()
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:20]
    return f"sporttery-team:{digest}"


def ensure_official_match_teams(conn: Any) -> int:
    """Create missing canonical teams referenced by official match history."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT team_name
            FROM (
                SELECT NULLIF(BTRIM(home_team_name), '') AS team_name
                FROM official_matches
                UNION
                SELECT NULLIF(BTRIM(away_team_name), '') AS team_name
                FROM official_matches
            ) official_names
            WHERE team_name IS NOT NULL
            ORDER BY team_name
            """
        )
        names = [row[0] for row in cur.fetchall()]

        cur.execute("SELECT DISTINCT BTRIM(team_name_cn) FROM teams WHERE team_name_cn IS NOT NULL")
        existing_names = {row[0] for row in cur.fetchall() if row[0]}

        created = 0
        for team_name in names:
            if team_name in existing_names:
                continue

            cur.execute(
                """
                INSERT INTO teams (team_code, team_name_cn, short_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (team_code) DO UPDATE SET
                    team_name_cn = EXCLUDED.team_name_cn,
                    short_name = EXCLUDED.short_name,
                    updated_at = now()
                RETURNING id
                """,
                (official_team_code(team_name), team_name, team_name[:64]),
            )
            if cur.fetchone():
                created += 1
                existing_names.add(team_name)

    conn.commit()
    return created
