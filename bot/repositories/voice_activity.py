"""
Voice activity repository for voice session tracking and analytics.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from bot.repositories.base import BaseRepository


class VoiceActivityRepository(BaseRepository):
    """
    Repository for voice activity sessions.

    Stores and queries user voice sessions from the ``voice_activity`` table.
    """

    def _row_to_entity(self, row):
        """Convert a database row to a tuple."""
        return tuple(row) if row else None

    def get_by_id(self, id: int):
        """Get a voice activity record by ID."""
        row = self._execute_one("SELECT * FROM voice_activity WHERE id = ?", (id,))
        return self._row_to_entity(row)

    def get_all(self, limit: int = 100):
        """Get recent voice activity records."""
        rows = self._execute(
            "SELECT * FROM voice_activity ORDER BY join_time DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_entity(row) for row in rows]

    def log_join(
        self,
        username: str,
        channel_id: str,
        join_time: Optional[str] = None,
        guild_id: Optional[int | str] = None,
    ) -> int:
        """
        Log a voice join event by creating an open session.

        Args:
            username: Discord username.
            channel_id: Voice channel ID as string.
            join_time: Optional timestamp; defaults to now.

        Returns:
            Inserted row ID.
        """
        timestamp = join_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return self._execute_write(
            """
            INSERT INTO voice_activity (username, channel_id, join_time, leave_time, guild_id)
            VALUES (?, ?, ?, NULL, ?)
            """,
            (
                username,
                str(channel_id),
                timestamp,
                str(guild_id) if guild_id is not None else None,
            ),
        )

    def log_leave(
        self,
        username: str,
        channel_id: str,
        leave_time: Optional[str] = None,
        guild_id: Optional[int | str] = None,
    ) -> bool:
        """
        Close the latest open session for a user/channel pair.

        Args:
            username: Discord username.
            channel_id: Voice channel ID as string.
            leave_time: Optional timestamp; defaults to now.

        Returns:
            True when an open session was found and closed.
        """
        if guild_id is None:
            open_session = self._execute_one(
                """
                SELECT id
                FROM voice_activity
                WHERE username = ? AND channel_id = ? AND leave_time IS NULL
                ORDER BY join_time DESC, id DESC
                LIMIT 1
                """,
                (username, str(channel_id)),
            )
        else:
            open_session = self._execute_one(
                """
                SELECT id
                FROM voice_activity
                WHERE username = ? AND channel_id = ? AND leave_time IS NULL
                AND (guild_id = ? OR guild_id IS NULL)
                ORDER BY join_time DESC, id DESC
                LIMIT 1
                """,
                (username, str(channel_id), str(guild_id)),
            )
        if not open_session:
            return False

        timestamp = leave_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._execute_write(
            "UPDATE voice_activity SET leave_time = ? WHERE id = ?",
            (timestamp, open_session["id"]),
        )
        return True

    def get_user_voice_metrics(
        self,
        username: str,
        period_start: str,
        period_end: str,
        guild_id: Optional[int | str] = None,
    ) -> Dict[str, float]:
        """
        Aggregate user voice metrics for a time window.

        Args:
            username: Discord username.
            period_start: Inclusive start timestamp.
            period_end: Inclusive end timestamp.

        Returns:
            Dict with joins, leaves, total_seconds, longest_seconds.
        """
        guild_clause = ""
        params = [
            period_start,
            period_end,
            period_start,
            period_end,
            period_end,
            period_end,
            period_start,
            period_end,
            period_end,
            period_start,
            username,
            period_end,
            period_end,
            period_start,
        ]
        if guild_id is not None:
            guild_clause = "AND (guild_id = ? OR guild_id IS NULL)"
            params.append(str(guild_id))

        row = self._execute_one(
            f"""
            SELECT
                COUNT(CASE WHEN join_time BETWEEN ? AND ? THEN 1 END) AS joins_in_period,
                COUNT(CASE WHEN leave_time BETWEEN ? AND ? THEN 1 END) AS leaves_in_period,
                COALESCE(
                    SUM(
                        MAX(
                            0,
                            (
                                julianday(MIN(COALESCE(leave_time, ?), ?))
                                - julianday(MAX(join_time, ?))
                            ) * 86400.0
                        )
                    ),
                    0
                ) AS total_seconds,
                COALESCE(
                    MAX(
                        MAX(
                            0,
                            (
                                julianday(MIN(COALESCE(leave_time, ?), ?))
                                - julianday(MAX(join_time, ?))
                            ) * 86400.0
                        )
                    ),
                    0
                ) AS longest_seconds
            FROM voice_activity
            WHERE username = ?
            AND join_time <= ?
            AND COALESCE(leave_time, ?) >= ?
            {guild_clause}
            """,
            tuple(params),
        )

        if not row:
            return {
                "joins": 0,
                "leaves": 0,
                "total_seconds": 0.0,
                "longest_seconds": 0.0,
            }

        return {
            "joins": int(row["joins_in_period"] or 0),
            "leaves": int(row["leaves_in_period"] or 0),
            "total_seconds": float(row["total_seconds"] or 0.0),
            "longest_seconds": float(row["longest_seconds"] or 0.0),
        }

    def _get_period_bounds(self, days: int) -> Tuple[str, str]:
        """Get normalized period bounds as timestamp strings."""
        period_end = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if days > 0:
            period_start = (datetime.now() - timedelta(days=days)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        else:
            period_start = "1970-01-01 00:00:00"
        return period_start, period_end

    def get_top_users_by_voice_time(
        self,
        days: int = 7,
        limit: int = 10,
        guild_id: Optional[int | str] = None,
    ) -> List[Tuple[str, float, int]]:
        """
        Get users ordered by total voice time.

        Args:
            days: Number of days to look back (0 = all-time).
            limit: Maximum number of results.

        Returns:
            List of tuples: (username, total_seconds, session_count).
        """
        period_start, period_end = self._get_period_bounds(days)
        guild_clause = ""
        params = [
            period_end,
            period_end,
            period_start,
            period_end,
            period_end,
            period_start,
        ]
        if guild_id is not None:
            guild_clause = "AND (guild_id = ? OR guild_id IS NULL)"
            params.append(str(guild_id))
        params.append(limit)
        rows = self._execute(
            f"""
            WITH SessionDurations AS (
                SELECT
                    username,
                    MAX(
                        0,
                        (
                            julianday(MIN(COALESCE(leave_time, ?), ?))
                            - julianday(MAX(join_time, ?))
                        ) * 86400.0
                    ) AS overlap_seconds
                FROM voice_activity
                WHERE join_time <= ?
                AND COALESCE(leave_time, ?) >= ?
                {guild_clause}
            )
            SELECT
                username,
                SUM(overlap_seconds) AS total_seconds,
                COUNT(*) AS session_count
            FROM SessionDurations
            WHERE overlap_seconds > 0
            GROUP BY username
            ORDER BY total_seconds DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [
            (row["username"], float(row["total_seconds"]), int(row["session_count"]))
            for row in rows
        ]

    def get_top_channels_by_voice_time(
        self,
        days: int = 7,
        limit: int = 10,
        guild_id: Optional[int | str] = None,
    ) -> List[Tuple[str, float, int]]:
        """
        Get channels ordered by total voice time.

        Args:
            days: Number of days to look back (0 = all-time).
            limit: Maximum number of results.

        Returns:
            List of tuples: (channel_id, total_seconds, session_count).
        """
        period_start, period_end = self._get_period_bounds(days)
        guild_clause = ""
        params = [
            period_end,
            period_end,
            period_start,
            period_end,
            period_end,
            period_start,
        ]
        if guild_id is not None:
            guild_clause = "AND (guild_id = ? OR guild_id IS NULL)"
            params.append(str(guild_id))
        params.append(limit)
        rows = self._execute(
            f"""
            WITH SessionDurations AS (
                SELECT
                    channel_id,
                    MAX(
                        0,
                        (
                            julianday(MIN(COALESCE(leave_time, ?), ?))
                            - julianday(MAX(join_time, ?))
                        ) * 86400.0
                    ) AS overlap_seconds
                FROM voice_activity
                WHERE join_time <= ?
                AND COALESCE(leave_time, ?) >= ?
                {guild_clause}
            )
            SELECT
                channel_id,
                SUM(overlap_seconds) AS total_seconds,
                COUNT(*) AS session_count
            FROM SessionDurations
            WHERE overlap_seconds > 0
            GROUP BY channel_id
            ORDER BY total_seconds DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [
            (str(row["channel_id"]), float(row["total_seconds"]), int(row["session_count"]))
            for row in rows
        ]
