"""
Repository for web soundboard content queries.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlite3

from bot.models.web import PaginatedQuery
from bot.repositories.base import BaseRepository


class WebContentRepository(BaseRepository[dict[str, Any]]):
    """
    Repository for web soundboard tables and filter metadata.
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

    def get_actions_page(self, query: PaginatedQuery) -> list[dict[str, Any]]:
        """
        Fetch paginated web action rows.

        Args:
            query: Pagination, search, and filter parameters.

        Returns:
            List of raw action rows.
        """
        conditions, params = self._build_action_conditions(query)
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = self._execute(
            f"""
            SELECT
                s.Filename AS filename,
                a.username AS username,
                a.action AS action,
                a.target AS target,
                a.timestamp AS timestamp
            FROM actions a
            LEFT JOIN sounds s ON a.target = s.id
            {where_clause}
            ORDER BY a.timestamp DESC, a.id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, query.per_page, query.offset),
        )
        return [self._row_to_entity(row) for row in rows]

    def count_actions(self, query: PaginatedQuery) -> int:
        """
        Count action rows matching the current query.

        Args:
            query: Pagination, search, and filter parameters.

        Returns:
            Matching row count.
        """
        conditions, params = self._build_action_conditions(query)
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""

        row = self._execute_one(
            f"""
            SELECT COUNT(*) AS count
            FROM actions a
            LEFT JOIN sounds s ON a.target = s.id
            {where_clause}
            """,
            tuple(params),
        )
        return int(row["count"]) if row else 0

    def get_action_filters(self) -> dict[str, list[str]]:
        """
        Fetch filter options for the actions table.

        Returns:
            Filter values grouped by column.
        """
        return {
            "action": self._fetch_distinct_values(
                """
                SELECT DISTINCT action AS value
                FROM actions
                WHERE action IS NOT NULL AND TRIM(action) != ''
                ORDER BY value COLLATE NOCASE ASC
                """
            ),
            "user": self._fetch_distinct_values(
                """
                SELECT DISTINCT username AS value
                FROM actions
                WHERE username IS NOT NULL AND TRIM(username) != ''
                ORDER BY value COLLATE NOCASE ASC
                """
            ),
            "sound": self._fetch_distinct_values(
                """
                SELECT DISTINCT COALESCE(s.Filename, a.target) AS value
                FROM actions a
                LEFT JOIN sounds s ON a.target = s.id
                WHERE COALESCE(s.Filename, a.target) IS NOT NULL
                  AND TRIM(COALESCE(s.Filename, a.target)) != ''
                ORDER BY value COLLATE NOCASE ASC
                """
            ),
        }

    def get_favorites_page(self, query: PaginatedQuery) -> list[dict[str, Any]]:
        """
        Fetch paginated favorite sounds.

        Args:
            query: Pagination, search, and filter parameters.

        Returns:
            List of raw favorite sound rows.
        """
        conditions = ["s.favorite = 1", "s.is_elevenlabs = 0"]
        params: list[object] = []

        if query.search_query:
            search_term = f"%{query.search_query}%"
            conditions.append("(s.Filename LIKE ? OR s.originalfilename LIKE ?)")
            params.extend([search_term, search_term])

        sound_filters = query.filters.get("sound", [])
        if sound_filters:
            clause, clause_params = self._build_in_clause("s.Filename", sound_filters)
            conditions.append(clause)
            params.extend(clause_params)

        where_clause = f" WHERE {' AND '.join(conditions)}"
        rows = self._execute(
            f"""
            WITH LatestFavorite AS (
                SELECT
                    CAST(target AS INTEGER) AS sound_id,
                    MAX(timestamp) AS last_favorited
                FROM actions
                WHERE action = 'favorite_sound'
                GROUP BY CAST(target AS INTEGER)
            )
            SELECT
                s.id AS sound_id,
                s.Filename AS filename
            FROM sounds s
            LEFT JOIN LatestFavorite lf ON lf.sound_id = s.id
            {where_clause}
            ORDER BY lf.last_favorited DESC, s.id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, query.per_page, query.offset),
        )
        return [self._row_to_entity(row) for row in rows]

    def count_favorites(self, query: PaginatedQuery) -> int:
        """
        Count favorite sounds matching the current query.

        Args:
            query: Pagination, search, and filter parameters.

        Returns:
            Matching row count.
        """
        conditions = ["favorite = 1", "is_elevenlabs = 0"]
        params: list[object] = []

        if query.search_query:
            search_term = f"%{query.search_query}%"
            conditions.append("(Filename LIKE ? OR originalfilename LIKE ?)")
            params.extend([search_term, search_term])

        sound_filters = query.filters.get("sound", [])
        if sound_filters:
            clause, clause_params = self._build_in_clause("Filename", sound_filters)
            conditions.append(clause)
            params.extend(clause_params)

        row = self._execute_one(
            f"""
            SELECT COUNT(*) AS count
            FROM sounds
            WHERE {' AND '.join(conditions)}
            """,
            tuple(params),
        )
        return int(row["count"]) if row else 0

    def get_favorite_filters(self) -> dict[str, list[str]]:
        """
        Fetch filter options for the favorites table.

        Returns:
            Filter values grouped by column.
        """
        return {
            "sound": self._fetch_distinct_values(
                """
                SELECT DISTINCT Filename AS value
                FROM sounds
                WHERE favorite = 1
                  AND is_elevenlabs = 0
                  AND Filename IS NOT NULL
                  AND TRIM(Filename) != ''
                ORDER BY value COLLATE NOCASE ASC
                """
            )
        }

    def get_all_sounds_page(self, query: PaginatedQuery) -> list[dict[str, Any]]:
        """
        Fetch paginated sounds for the full soundboard table.

        Args:
            query: Pagination, search, and filter parameters.

        Returns:
            List of raw sound rows.
        """
        conditions = ["is_elevenlabs = 0"]
        params: list[object] = []

        if query.search_query:
            search_term = f"%{query.search_query}%"
            conditions.append("(Filename LIKE ? OR originalfilename LIKE ?)")
            params.extend([search_term, search_term])

        sound_filters = query.filters.get("sound", [])
        if sound_filters:
            clause, clause_params = self._build_in_clause("Filename", sound_filters)
            conditions.append(clause)
            params.extend(clause_params)

        date_filters = query.filters.get("date", [])
        if date_filters:
            clause, clause_params = self._build_in_clause("date(timestamp)", date_filters)
            conditions.append(clause)
            params.extend(clause_params)

        rows = self._execute(
            f"""
            SELECT
                id AS sound_id,
                Filename AS filename,
                timestamp AS timestamp
            FROM sounds
            WHERE {' AND '.join(conditions)}
            ORDER BY timestamp DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, query.per_page, query.offset),
        )
        return [self._row_to_entity(row) for row in rows]

    def count_all_sounds(self, query: PaginatedQuery) -> int:
        """
        Count sounds matching the current query.

        Args:
            query: Pagination, search, and filter parameters.

        Returns:
            Matching row count.
        """
        conditions = ["is_elevenlabs = 0"]
        params: list[object] = []

        if query.search_query:
            search_term = f"%{query.search_query}%"
            conditions.append("(Filename LIKE ? OR originalfilename LIKE ?)")
            params.extend([search_term, search_term])

        sound_filters = query.filters.get("sound", [])
        if sound_filters:
            clause, clause_params = self._build_in_clause("Filename", sound_filters)
            conditions.append(clause)
            params.extend(clause_params)

        date_filters = query.filters.get("date", [])
        if date_filters:
            clause, clause_params = self._build_in_clause("date(timestamp)", date_filters)
            conditions.append(clause)
            params.extend(clause_params)

        row = self._execute_one(
            f"""
            SELECT COUNT(*) AS count
            FROM sounds
            WHERE {' AND '.join(conditions)}
            """,
            tuple(params),
        )
        return int(row["count"]) if row else 0

    def get_all_sound_filters(self) -> dict[str, list[str]]:
        """
        Fetch filter options for the full sounds table.

        Returns:
            Filter values grouped by column.
        """
        return {
            "sound": self._fetch_distinct_values(
                """
                SELECT DISTINCT Filename AS value
                FROM sounds
                WHERE is_elevenlabs = 0
                  AND Filename IS NOT NULL
                  AND TRIM(Filename) != ''
                ORDER BY value COLLATE NOCASE ASC
                """
            ),
            "date": self._fetch_distinct_values(
                """
                SELECT DISTINCT date(timestamp) AS value
                FROM sounds
                WHERE is_elevenlabs = 0
                  AND timestamp IS NOT NULL
                  AND TRIM(timestamp) != ''
                ORDER BY value DESC
                """
            ),
        }

    def _build_action_conditions(self, query: PaginatedQuery) -> tuple[list[str], list[object]]:
        """Build the WHERE clause parts for action queries."""
        conditions: list[str] = []
        params: list[object] = []

        if query.search_query:
            search_term = f"%{query.search_query}%"
            conditions.append(
                "(a.username LIKE ? OR a.action LIKE ? OR a.target LIKE ? "
                "OR (s.Filename IS NOT NULL AND s.Filename LIKE ?))"
            )
            params.extend([search_term, search_term, search_term, search_term])

        action_filters = query.filters.get("action", [])
        if action_filters:
            clause, clause_params = self._build_in_clause("a.action", action_filters)
            conditions.append(clause)
            params.extend(clause_params)

        user_filters = query.filters.get("user", [])
        if user_filters:
            clause, clause_params = self._build_in_clause("a.username", user_filters)
            conditions.append(clause)
            params.extend(clause_params)

        sound_filters = query.filters.get("sound", [])
        if sound_filters:
            clause, clause_params = self._build_in_clause(
                "COALESCE(s.Filename, a.target)",
                sound_filters,
            )
            conditions.append(clause)
            params.extend(clause_params)

        return conditions, params

    def _fetch_distinct_values(
        self,
        query: str,
        params: Sequence[object] = (),
    ) -> list[str]:
        """Fetch distinct non-empty string values from a query."""
        rows = self._execute(query, tuple(params))
        values: list[str] = []
        for row in rows:
            value = row["value"]
            if value is None:
                continue
            text = str(value).strip()
            if text:
                values.append(text)
        return values

    @staticmethod
    def _build_in_clause(column: str, values: Sequence[str]) -> tuple[str, list[str]]:
        """Build a parameterized ``IN`` clause."""
        placeholders = ", ".join("?" for _ in values)
        return f"{column} IN ({placeholders})", [str(value) for value in values]
