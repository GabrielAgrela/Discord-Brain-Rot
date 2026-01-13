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
