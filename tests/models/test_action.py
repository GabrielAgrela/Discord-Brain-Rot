"""
Tests for bot/models/action.py - Action model.
"""

import pytest
from datetime import datetime

from bot.models.action import Action


class TestAction:
    """Tests for the Action model."""
    
    def test_from_db_row_full(self):
        """Test creating an Action from a full database row."""
        row = (1, "testuser", "play_random_sound", "5", "2024-01-15 10:30:00")
        action = Action.from_db_row(row)
        
        assert action.id == 1
        assert action.username == "testuser"
        assert action.action == "play_random_sound"
        assert action.target == "5"
        assert action.timestamp == datetime(2024, 1, 15, 10, 30, 0)
    
    def test_from_db_row_no_timestamp(self):
        """Test creating an Action without timestamp."""
        row = (2, "user2", "favorite", "sound.mp3", None)
        action = Action.from_db_row(row)
        
        assert action.id == 2
        assert action.target == "sound.mp3"
        assert action.timestamp is None
    
    def test_from_db_row_minimal(self):
        """Test creating an Action with minimal row (no target/timestamp)."""
        row = (3, "user3", "join")
        action = Action.from_db_row(row)
        
        assert action.id == 3
        assert action.username == "user3"
        assert action.action == "join"
        assert action.target == ""
    
    def test_action_constants(self):
        """Test that action type constants are defined."""
        assert Action.PLAY == "play"
        assert Action.PLAY_RANDOM == "play_random"
        assert Action.PLAY_FAVORITE == "play_favorite"
        assert Action.JOIN == "join"
        assert Action.LEAVE == "leave"
        assert Action.TTS == "tts"
        assert Action.STS == "sts"
        assert Action.MUTE == "mute"
        assert Action.UNMUTE == "unmute"
        assert Action.FAVORITE == "favorite"
        assert Action.UNFAVORITE == "unfavorite"
        assert Action.UPLOAD == "upload"
        assert Action.RENAME == "rename"
    
    def test_dataclass_creation(self):
        """Test creating an Action directly."""
        action = Action(
            id=10,
            username="direct_user",
            action="custom_action",
            target="target_value"
        )
        
        assert action.id == 10
        assert action.username == "direct_user"
        assert action.action == "custom_action"
        assert action.target == "target_value"
        assert action.timestamp is None
