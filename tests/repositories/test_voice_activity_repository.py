"""
Tests for bot/repositories/voice_activity.py - VoiceActivityRepository.
"""

from datetime import datetime, timedelta

import pytest


class TestVoiceActivityRepository:
    """Tests for the VoiceActivityRepository class."""

    def test_log_join_and_leave(self, voice_activity_repository, db_connection):
        """Test opening and closing a voice session."""
        join_time = "2025-01-01 10:00:00"
        leave_time = "2025-01-01 11:15:00"

        row_id = voice_activity_repository.log_join("alice", "123", join_time)
        assert row_id > 0

        cursor = db_connection.cursor()
        cursor.execute("SELECT * FROM voice_activity WHERE id = ?", (row_id,))
        row = cursor.fetchone()
        assert row["username"] == "alice"
        assert row["channel_id"] == "123"
        assert row["join_time"] == join_time
        assert row["leave_time"] is None

        updated = voice_activity_repository.log_leave("alice", "123", leave_time)
        assert updated is True

        cursor.execute("SELECT leave_time FROM voice_activity WHERE id = ?", (row_id,))
        row = cursor.fetchone()
        assert row["leave_time"] == leave_time

    def test_log_leave_without_open_session(self, voice_activity_repository):
        """Test closing a session when no open row exists."""
        updated = voice_activity_repository.log_leave(
            "missing-user",
            "999",
            "2025-01-01 10:00:00",
        )
        assert updated is False

    def test_get_user_voice_metrics(self, voice_activity_repository):
        """Test user aggregation with overlap and open sessions."""
        period_start = "2025-01-01 00:00:00"
        period_end = "2025-01-02 00:00:00"

        # Full in-period session: 1 hour.
        voice_activity_repository.log_join("alice", "101", "2025-01-01 10:00:00")
        voice_activity_repository.log_leave("alice", "101", "2025-01-01 11:00:00")

        # Starts before period, ends in period: overlap 1 hour.
        voice_activity_repository.log_join("alice", "101", "2024-12-31 23:00:00")
        voice_activity_repository.log_leave("alice", "101", "2025-01-01 01:00:00")

        # Open session at period end: overlap 30 min.
        voice_activity_repository.log_join("alice", "101", "2025-01-01 23:30:00")

        metrics = voice_activity_repository.get_user_voice_metrics(
            username="alice",
            period_start=period_start,
            period_end=period_end,
        )

        assert metrics["joins"] == 2
        assert metrics["leaves"] == 2
        assert metrics["total_seconds"] == pytest.approx(9000.0, rel=1e-6)
        assert metrics["longest_seconds"] == pytest.approx(3600.0, rel=1e-6)

    def test_get_top_users_by_voice_time(self, voice_activity_repository):
        """Test ranking users by tracked voice time."""
        now = datetime.now().replace(microsecond=0)

        def ts(hours_ago: int) -> str:
            return (now - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")

        # alice: 5 hours
        voice_activity_repository.log_join("alice", "111", ts(6))
        voice_activity_repository.log_leave("alice", "111", ts(1))

        # bob: 3 hours
        voice_activity_repository.log_join("bob", "111", ts(4))
        voice_activity_repository.log_leave("bob", "111", ts(1))

        # old session outside 7-day window
        old_start = (now - timedelta(days=20, hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        old_end = (now - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")
        voice_activity_repository.log_join("charlie", "222", old_start)
        voice_activity_repository.log_leave("charlie", "222", old_end)

        rows = voice_activity_repository.get_top_users_by_voice_time(days=7, limit=10)
        usernames = [row[0] for row in rows]

        assert usernames == ["alice", "bob"]
        assert rows[0][1] > rows[1][1]
        assert rows[0][2] == 1

    def test_get_top_channels_by_voice_time(self, voice_activity_repository):
        """Test ranking channels by aggregate voice time."""
        now = datetime.now().replace(microsecond=0)

        def ts(hours_ago: int) -> str:
            return (now - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")

        # Channel 111 total: 4h + 1h = 5h
        voice_activity_repository.log_join("alice", "111", ts(6))
        voice_activity_repository.log_leave("alice", "111", ts(2))
        voice_activity_repository.log_join("bob", "111", ts(3))
        voice_activity_repository.log_leave("bob", "111", ts(2))

        # Channel 222 total: 2h
        voice_activity_repository.log_join("charlie", "222", ts(4))
        voice_activity_repository.log_leave("charlie", "222", ts(2))

        rows = voice_activity_repository.get_top_channels_by_voice_time(days=7, limit=10)
        channel_ids = [row[0] for row in rows]

        assert channel_ids == ["111", "222"]
        assert rows[0][1] > rows[1][1]
        assert rows[0][2] == 2
