"""
Tests for bot/repositories/stats.py - StatsRepository.
"""

import pytest
from datetime import datetime, timedelta


class TestStatsRepository:
    """Tests for the StatsRepository class."""
    
    def test_get_sound_download_date(self, stats_repository, sample_sounds):
        """Test getting the download date for a sound."""
        date = stats_repository.get_sound_download_date(sample_sounds[0])
        
        # Should return the timestamp from sample data
        # Our fixture includes timestamp column with "2024-01-01 10:00:00"
        assert date == "2024-01-01 10:00:00"
    
    def test_get_sound_download_date_not_found(self, stats_repository):
        """Test getting download date for non-existent sound."""
        date = stats_repository.get_sound_download_date(9999)
        assert date is None
    
    def test_get_users_who_favorited_sound(self, stats_repository, sample_actions):
        """Test getting users who favorited a sound."""
        users = stats_repository.get_users_who_favorited_sound(sample_actions[0])
        
        # Based on sample_actions fixture, both user1 and user2 favorited first sound
        assert len(users) == 2
        assert "user1" in users
        assert "user2" in users
    
    def test_get_users_who_favorited_sound_none(self, stats_repository, sample_sounds):
        """Test getting favorited users for sound with no favorites."""
        # sound 2 has no favorites in our sample data
        users = stats_repository.get_users_who_favorited_sound(sample_sounds[1])
        assert len(users) == 0
    
    def test_get_activity_heatmap(self, stats_repository, sample_actions):
        """Test getting activity heatmap data."""
        heatmap = stats_repository.get_activity_heatmap(days=0)
        
        # Should return a list of dicts with day_of_week, hour, count
        assert isinstance(heatmap, list)
        if heatmap:
            assert "day_of_week" in heatmap[0] or len(heatmap[0]) >= 3
    
    def test_get_activity_timeline(self, stats_repository, sample_actions):
        """Test getting activity timeline data."""
        timeline = stats_repository.get_activity_timeline(days=30)
        
        assert isinstance(timeline, list)
    
    def test_get_summary_stats(self, stats_repository, sample_sounds, sample_actions):
        """Test getting summary statistics."""
        stats = stats_repository.get_summary_stats(days=0)
        
        assert isinstance(stats, dict)
        assert "total_sounds" in stats
        assert "total_plays" in stats
        assert "active_users" in stats
        assert stats["total_sounds"] == 4  # Based on sample_sounds fixture
        # Total plays includes actions from sample_actions fixture
        assert stats["total_plays"] >= 0


class TestStatsRepositoryEdgeCases:
    """Edge case tests for StatsRepository."""
    
    def test_get_activity_heatmap_empty(self, stats_repository):
        """Test heatmap with no data."""
        heatmap = stats_repository.get_activity_heatmap(days=30)
        assert isinstance(heatmap, list)
    
    def test_get_activity_timeline_empty(self, stats_repository):
        """Test timeline with no data."""
        timeline = stats_repository.get_activity_timeline(days=30)
        assert isinstance(timeline, list)
    
    def test_get_summary_stats_empty(self, stats_repository):
        """Test summary stats on empty database."""
        stats = stats_repository.get_summary_stats(days=0)
        
        assert isinstance(stats, dict)
        assert stats["total_sounds"] == 0


class TestStatsRepositoryVoiceAnalytics:
    """Voice analytics tests for StatsRepository."""

    def test_get_user_year_stats_populates_voice_metrics(
        self, stats_repository, db_connection
    ):
        """Test year stats include voice session aggregates."""
        cursor = db_connection.cursor()

        rows = [
            ("user1", "10", "2025-01-01 10:00:00", "2025-01-01 11:00:00"),  # 1h
            ("user1", "10", "2025-06-01 12:00:00", "2025-06-01 14:00:00"),  # 2h
            ("user1", "10", "2024-12-31 23:00:00", "2025-01-01 00:30:00"),  # 0.5h overlap
        ]
        cursor.executemany(
            """
            INSERT INTO voice_activity (username, channel_id, join_time, leave_time)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )
        db_connection.commit()

        stats = stats_repository.get_user_year_stats("user1", 2025)

        assert stats["voice_joins"] == 2
        assert stats["voice_leaves"] == 3
        assert stats["total_voice_hours"] == 3.5
        assert stats["longest_session_minutes"] == 120
        assert stats["longest_session_hours"] == 2.0

    def test_get_top_voice_users(self, stats_repository, db_connection):
        """Test top voice users mapping and ordering."""
        now = datetime.now().replace(microsecond=0)
        cursor = db_connection.cursor()

        rows = [
            (
                "alice",
                "10",
                (now - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
            ),  # 2h
            (
                "bob",
                "10",
                (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
            ),  # 1h
        ]
        cursor.executemany(
            """
            INSERT INTO voice_activity (username, channel_id, join_time, leave_time)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )
        db_connection.commit()

        top_users = stats_repository.get_top_voice_users(days=7, limit=5)

        assert len(top_users) == 2
        assert top_users[0]["username"] == "alice"
        assert top_users[1]["username"] == "bob"
        assert top_users[0]["total_hours"] > top_users[1]["total_hours"]

    def test_get_top_voice_channels(self, stats_repository, db_connection):
        """Test top voice channels mapping and ordering."""
        now = datetime.now().replace(microsecond=0)
        cursor = db_connection.cursor()

        rows = [
            (
                "alice",
                "100",
                (now - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
            ),  # 3h
            (
                "bob",
                "200",
                (now - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
            ),  # 2h
        ]
        cursor.executemany(
            """
            INSERT INTO voice_activity (username, channel_id, join_time, leave_time)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )
        db_connection.commit()

        top_channels = stats_repository.get_top_voice_channels(days=7, limit=5)

        assert len(top_channels) == 2
        assert top_channels[0]["channel_id"] == "100"
        assert top_channels[1]["channel_id"] == "200"
        assert top_channels[0]["total_hours"] > top_channels[1]["total_hours"]

    def test_get_summary_stats_includes_voice_totals(
        self, stats_repository, db_connection
    ):
        """Test summary stats include voice user and hour totals."""
        now = datetime.now().replace(microsecond=0)
        cursor = db_connection.cursor()

        rows = [
            (
                "alice",
                "10",
                (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
            ),  # 1h
            (
                "bob",
                "10",
                (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=1, minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
            ),  # 0.5h
        ]
        cursor.executemany(
            """
            INSERT INTO voice_activity (username, channel_id, join_time, leave_time)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )
        db_connection.commit()

        summary = stats_repository.get_summary_stats(days=7)

        assert summary["active_voice_users"] == 2
        assert summary["total_voice_hours"] == 1.5
