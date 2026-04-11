"""
Repository for web user access checks.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlite3

from bot.repositories.base import BaseRepository


class WebUserAccessRepository(BaseRepository[dict[str, Any]]):
    """
    Repository for web-session authorization lookups.
    """

    def _row_to_entity(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a row to a plain dictionary."""
        return dict(row)

    def get_by_id(self, id: int) -> dict[str, Any] | None:
        """Not used for this query-oriented repository."""
        return None

    def get_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """Not used for this query-oriented repository."""
        return []

    def has_voice_activity_for_usernames(self, usernames: Sequence[str]) -> bool:
        """
        Return whether any candidate username has joined a tracked voice channel.

        Args:
            usernames: Discord username/display-name candidates from the web session.

        Returns:
            True when a matching voice activity row exists.
        """
        normalized_names = sorted({str(name).strip() for name in usernames if str(name).strip()})
        if not normalized_names:
            return False

        placeholders = ", ".join("?" for _ in normalized_names)
        row = self._execute_one(
            f"""
            SELECT 1 AS matched
            FROM voice_activity
            WHERE username IN ({placeholders})
            LIMIT 1
            """,
            tuple(normalized_names),
        )
        return row is not None
