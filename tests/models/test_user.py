"""
Tests for bot/models/user.py - User, UserEvent, and UserStats models.
"""

import pytest
from datetime import datetime

from bot.models.user import User, UserEvent, UserStats


class TestUser:
    """Tests for the User model."""
    
    def test_from_db_row_full(self):
        """Test creating a User from a full row."""
        row = (1, "testuser", 123456789)
        user = User.from_db_row(row)
        
        assert user.id == 1
        assert user.username == "testuser"
        assert user.discord_id == 123456789
    
    def test_from_db_row_no_discord_id(self):
        """Test creating a User without discord_id."""
        row = (2, "user2")
        user = User.from_db_row(row)
        
        assert user.id == 2
        assert user.username == "user2"
        assert user.discord_id is None
    
    def test_dataclass_creation(self):
        """Test creating a User directly."""
        user = User(id=5, username="direct_user")
        assert user.id == 5
        assert user.username == "direct_user"
        assert user.discord_id is None


class TestUserEvent:
    """Tests for the UserEvent model."""
    
    def test_from_db_row_full(self):
        """Test creating a UserEvent from a full row."""
        row = (1, "user123", "join", "welcome.mp3")
        event = UserEvent.from_db_row(row)
        
        assert event.id == 1
        assert event.user_id == "user123"
        assert event.event == "join"
        assert event.sound == "welcome.mp3"
    
    def test_from_db_row_no_sound(self):
        """Test creating a UserEvent without sound field."""
        row = (2, "user456", "leave")
        event = UserEvent.from_db_row(row)
        
        assert event.id == 2
        assert event.user_id == "user456"
        assert event.event == "leave"
        assert event.sound == ""
    
    def test_is_join_property(self):
        """Test is_join property."""
        join_event = UserEvent(id=1, user_id="u1", event="join", sound="s.mp3")
        leave_event = UserEvent(id=2, user_id="u2", event="leave", sound="s.mp3")
        
        assert join_event.is_join is True
        assert leave_event.is_join is False
    
    def test_is_leave_property(self):
        """Test is_leave property."""
        join_event = UserEvent(id=1, user_id="u1", event="join", sound="s.mp3")
        leave_event = UserEvent(id=2, user_id="u2", event="leave", sound="s.mp3")
        
        assert leave_event.is_leave is True
        assert join_event.is_leave is False


class TestUserStats:
    """Tests for the UserStats model."""
    
    def test_default_values(self):
        """Test default values are set correctly."""
        stats = UserStats(username="testuser", year=2024)
        
        assert stats.username == "testuser"
        assert stats.year == 2024
        assert stats.total_plays == 0
        assert stats.requested_plays == 0
        assert stats.random_plays == 0
        assert stats.favorite_plays == 0
        assert stats.unique_sounds == 0
        assert stats.top_sounds == []  # Initialized by __post_init__
        assert stats.brain_rot == {}  # Initialized by __post_init__
    
    def test_post_init_top_sounds(self):
        """Test __post_init__ initializes top_sounds to empty list."""
        stats = UserStats(username="user", year=2024, top_sounds=None)
        assert stats.top_sounds == []
    
    def test_post_init_brain_rot(self):
        """Test __post_init__ initializes brain_rot to empty dict."""
        stats = UserStats(username="user", year=2024, brain_rot=None)
        assert stats.brain_rot == {}
    
    def test_with_values(self):
        """Test creating UserStats with values."""
        stats = UserStats(
            username="active_user",
            year=2024,
            total_plays=100,
            requested_plays=50,
            random_plays=50,
            top_sounds=[("sound1.mp3", 30), ("sound2.mp3", 20)],
            brain_rot={"memes": 5}
        )
        
        assert stats.total_plays == 100
        assert stats.requested_plays == 50
        assert len(stats.top_sounds) == 2
        assert stats.brain_rot["memes"] == 5
