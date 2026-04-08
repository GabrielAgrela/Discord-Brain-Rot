"""
Repository for web analytics queries.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import sqlite3

from bot.models.web import AnalyticsQuery
from bot.repositories.base import BaseRepository

PLAY_ACTIONS_FOR_COUNTS = (
    "'play_random_sound', 'replay_sound', 'play_random_favorite_sound', "
    "'play_request', 'play_from_list', 'play_similar_sound', "
    "'play_sound_periodically', 'play_sound_generic'"
)
PLAY_ACTIONS_FOR_USERS = (
    "'play_random_sound', 'replay_sound', 'play_random_favorite_sound', "
    "'play_request', 'play_from_list', 'play_similar_sound'"
)
RECENT_ACTIVITY_ACTIONS = (
    "'play_random_sound', 'replay_sound', 'play_random_favorite_sound', "
    "'play_request', 'play_from_list', 'play_similar_sound', "
    "'play_sound_periodically', 'favorite_sound', 'unfavorite_sound', 'join', 'leave'"
)


class WebAnalyticsRepository(BaseRepository[dict[str, Any]]):
    """
    Repository for analytics dashboard data.
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

    def get_summary_stats(self, days: int) -> dict[str, int]:
        """
        Fetch summary metrics for the analytics dashboard.

        Args:
            days: Optional day window. ``0`` means all time.

        Returns:
            Summary counts used by the dashboard cards.
        """
        stats = {
            "total_sounds": 0,
            "total_plays": 0,
            "active_users": 0,
            "sounds_this_week": 0,
        }

        total_sounds_row = self._execute_one("SELECT COUNT(*) AS count FROM sounds")
        stats["total_sounds"] = int(total_sounds_row["count"]) if total_sounds_row else 0

        time_filter = ""
        params: list[object] = []
        if days > 0:
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            time_filter = "AND timestamp >= ?"
            params.append(cutoff)

        total_plays_row = self._execute_one(
            f"""
            SELECT COUNT(*) AS count
            FROM actions
            WHERE action IN ({PLAY_ACTIONS_FOR_COUNTS})
            {time_filter}
            """,
            tuple(params),
        )
        stats["total_plays"] = int(total_plays_row["count"]) if total_plays_row else 0

        active_users_row = self._execute_one(
            f"""
            SELECT COUNT(DISTINCT username) AS count
            FROM actions
            WHERE action IN ({PLAY_ACTIONS_FOR_USERS})
            {time_filter}
            """,
            tuple(params),
        )
        stats["active_users"] = int(active_users_row["count"]) if active_users_row else 0

        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        sounds_this_week_row = self._execute_one(
            "SELECT COUNT(*) AS count FROM sounds WHERE timestamp >= ?",
            (week_ago,),
        )
        stats["sounds_this_week"] = (
            int(sounds_this_week_row["count"]) if sounds_this_week_row else 0
        )
        return stats

    def get_top_users(self, query: AnalyticsQuery) -> list[dict[str, Any]]:
        """
        Fetch the top playback users.

        Args:
            query: Analytics query parameters.

        Returns:
            List of user/count rows.
        """
        time_filter = ""
        params: list[object] = []
        if query.days > 0:
            cutoff = (datetime.now() - timedelta(days=query.days)).strftime("%Y-%m-%d %H:%M:%S")
            time_filter = "AND timestamp >= ?"
            params.append(cutoff)
        params.append(query.limit)

        rows = self._execute(
            f"""
            SELECT username AS username, COUNT(*) AS count
            FROM actions
            WHERE action IN ({PLAY_ACTIONS_FOR_USERS})
            {time_filter}
            GROUP BY username
            ORDER BY count DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [self._row_to_entity(row) for row in rows]

    def get_top_sounds(self, query: AnalyticsQuery) -> list[dict[str, Any]]:
        """
        Fetch the top played sounds.

        Args:
            query: Analytics query parameters.

        Returns:
            List of sound/count rows.
        """
        time_filter = ""
        params: list[object] = []
        if query.days > 0:
            cutoff = (datetime.now() - timedelta(days=query.days)).strftime("%Y-%m-%d %H:%M:%S")
            time_filter = "AND a.timestamp >= ?"
            params.append(cutoff)
        params.append(query.limit)

        rows = self._execute(
            f"""
            SELECT
                MIN(s.id) AS sound_id,
                s.Filename AS filename,
                COUNT(*) AS count
            FROM actions a
            JOIN sounds s ON a.target = s.id
            WHERE a.action IN ({PLAY_ACTIONS_FOR_COUNTS})
              AND s.slap = 0
              {time_filter}
            GROUP BY s.Filename
            ORDER BY count DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [self._row_to_entity(row) for row in rows]

    def get_activity_heatmap(self, days: int) -> list[dict[str, Any]]:
        """
        Fetch activity counts grouped by day of week and hour.

        Args:
            days: Optional day window. ``0`` means all time.

        Returns:
            Heatmap buckets.
        """
        time_filter = ""
        params: list[object] = []
        if days > 0:
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            time_filter = "AND timestamp >= ?"
            params.append(cutoff)

        rows = self._execute(
            f"""
            SELECT
                CAST(strftime('%w', timestamp) AS INTEGER) AS day,
                CAST(strftime('%H', timestamp) AS INTEGER) AS hour,
                COUNT(*) AS count
            FROM actions
            WHERE action IN ({PLAY_ACTIONS_FOR_COUNTS})
            {time_filter}
            GROUP BY day, hour
            ORDER BY day, hour
            """,
            tuple(params),
        )
        return [self._row_to_entity(row) for row in rows]

    def get_activity_timeline(self, days: int) -> list[dict[str, Any]]:
        """
        Fetch activity counts grouped for the timeline chart.

        Args:
            days: Optional day window. ``0`` uses weekly all-time grouping.

        Returns:
            Timeline buckets.
        """
        if days == 0:
            rows = self._execute(
                f"""
                SELECT
                    MIN(date(timestamp)) AS date,
                    COUNT(*) AS count
                FROM actions
                WHERE action IN ({PLAY_ACTIONS_FOR_COUNTS})
                GROUP BY strftime('%Y-W%W', timestamp)
                ORDER BY strftime('%Y-W%W', timestamp) ASC
                """
            )
            return [self._row_to_entity(row) for row in rows]

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = self._execute(
            f"""
            SELECT
                date(timestamp) AS date,
                COUNT(*) AS count
            FROM actions
            WHERE action IN ({PLAY_ACTIONS_FOR_COUNTS})
              AND date(timestamp) >= ?
            GROUP BY date(timestamp)
            ORDER BY date(timestamp) ASC
            """,
            (cutoff,),
        )
        return [self._row_to_entity(row) for row in rows]

    def get_recent_activity(self, limit: int) -> list[dict[str, Any]]:
        """
        Fetch the recent activity feed.

        Args:
            limit: Maximum rows to return.

        Returns:
            Recent activity rows.
        """
        rows = self._execute(
            f"""
            SELECT
                a.username AS username,
                a.action AS action,
                a.timestamp AS timestamp,
                s.Filename AS filename
            FROM actions a
            LEFT JOIN sounds s ON a.target = s.id
            WHERE a.action IN ({RECENT_ACTIVITY_ACTIONS})
            ORDER BY a.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_entity(row) for row in rows]
