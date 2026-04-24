"""
Repository for web-visible guild discovery.
"""

from __future__ import annotations

from typing import Any

import sqlite3

from bot.repositories.base import BaseRepository


class WebGuildRepository(BaseRepository[dict[str, Any]]):
    """
    Query known guilds from stable persisted bot data.

    The web process cannot inspect live Discord objects, so it discovers guilds
    from tables written by the bot process.
    """

    def _row_to_entity(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a SQLite row into a dictionary."""
        return dict(row)

    def get_by_id(self, id: int) -> dict[str, Any] | None:
        """Return one known guild option by ID."""
        rows = self.get_known_guilds()
        for row in rows:
            if int(row["guild_id"]) == int(id):
                return row
        return None

    def get_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return known guild options."""
        return self.get_known_guilds(limit=limit)

    def get_known_guilds(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        Return distinct guild IDs with best-effort display names.

        Args:
            limit: Maximum number of guilds to return.

        Returns:
            List of dictionaries with ``guild_id`` and ``name``.
        """
        rows = self._execute(
            """
            WITH guild_sources AS (
                SELECT guild_id, NULL AS guild_name, 1 AS priority FROM guild_settings
                UNION ALL
                SELECT guild_id, guild_name, 0 AS priority FROM web_bot_status
                UNION ALL
                SELECT guild_id, NULL AS guild_name, 2 AS priority FROM sounds
                UNION ALL
                SELECT guild_id, NULL AS guild_name, 2 AS priority FROM actions
                UNION ALL
                SELECT guild_id, NULL AS guild_name, 2 AS priority FROM voice_activity
            ),
            ranked AS (
                SELECT
                    CAST(guild_id AS INTEGER) AS guild_id,
                    guild_name,
                    ROW_NUMBER() OVER (
                        PARTITION BY CAST(guild_id AS INTEGER)
                        ORDER BY
                            CASE WHEN guild_name IS NOT NULL AND TRIM(guild_name) != '' THEN 0 ELSE 1 END,
                            priority ASC
                    ) AS rn
                FROM guild_sources
                WHERE guild_id IS NOT NULL AND TRIM(CAST(guild_id AS TEXT)) != ''
            )
            SELECT
                guild_id,
                COALESCE(NULLIF(TRIM(guild_name), ''), 'Guild ' || guild_id) AS name
            FROM ranked
            WHERE rn = 1
            ORDER BY name COLLATE NOCASE ASC, guild_id ASC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_entity(row) for row in rows]
