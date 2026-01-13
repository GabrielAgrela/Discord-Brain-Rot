"""
Tests for bot/repositories/event.py - EventRepository.
"""

import pytest


class TestEventRepository:
    """Tests for the EventRepository class."""
    
    def test_insert(self, event_repository, db_connection):
        """Test inserting a user event."""
        event_repository.insert(
            user_id="user123",
            event_type="join",
            sound="welcome.mp3"
        )
        
        cursor = db_connection.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", ("user123",))
        row = cursor.fetchone()
        
        assert row is not None
        assert row["event"] == "join"
        assert row["sound"] == "welcome.mp3"
    
    def test_get_user_events(self, event_repository, db_connection):
        """Test getting user events."""
        # Insert some events
        event_repository.insert("user1", "join", "sound1.mp3")
        event_repository.insert("user1", "join", "sound2.mp3")
        event_repository.insert("user1", "leave", "goodbye.mp3")
        
        join_events = event_repository.get_user_events("user1", "join")
        assert len(join_events) == 2
        
        leave_events = event_repository.get_user_events("user1", "leave")
        assert len(leave_events) == 1
    
    def test_remove(self, event_repository, db_connection):
        """Test removing a user event."""
        event_repository.insert("user2", "join", "remove_me.mp3")
        
        result = event_repository.remove("user2", "join", "remove_me.mp3")
        assert result is True
        
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE id = ? AND sound = ?",
            ("user2", "remove_me.mp3")
        )
        assert cursor.fetchone() is None
    
    def test_toggle_add(self, event_repository):
        """Test toggle adds event when it doesn't exist."""
        result = event_repository.toggle("toggleuser", "join", "toggle.mp3")
        
        assert result is True  # Added
        
        # Verify it was added
        events = event_repository.get_user_events("toggleuser", "join")
        sounds = [e[2] for e in events]  # sound is third element in tuple
        assert "toggle.mp3" in sounds
    
    def test_toggle_remove(self, event_repository):
        """Test toggle removes event when it exists."""
        # First add
        event_repository.insert("toggleuser2", "leave", "toggle2.mp3")
        
        # Then toggle (should remove)
        result = event_repository.toggle("toggleuser2", "leave", "toggle2.mp3")
        
        assert result is False  # Removed
        
        # Verify it was removed
        event = event_repository.get_event_sound("toggleuser2", "leave", "toggle2.mp3")
        assert event is None
    
    def test_get_event_sound(self, event_repository):
        """Test checking if specific event sound exists."""
        event_repository.insert("checkuser", "join", "check.mp3")
        
        result = event_repository.get_event_sound("checkuser", "join", "check.mp3")
        assert result is not None
        
        result = event_repository.get_event_sound("checkuser", "join", "notexist.mp3")
        assert result is None
    
    def test_get_all_users_with_events(self, event_repository):
        """Test getting all users with configured events."""
        event_repository.insert("userA", "join", "a.mp3")
        event_repository.insert("userB", "leave", "b.mp3")
        event_repository.insert("userA", "leave", "a2.mp3")  # Same user
        
        users = event_repository.get_all_users_with_events()
        
        assert len(users) == 2
        assert "userA" in users
        assert "userB" in users


class TestEventRepositoryEdgeCases:
    """Edge case tests for EventRepository."""
    
    def test_get_user_events_empty(self, event_repository):
        """Test getting events for user with none configured."""
        events = event_repository.get_user_events("nonexistent", "join")
        assert events == []
    
    def test_remove_nonexistent(self, event_repository):
        """Test removing non-existent event."""
        # Should not raise, just return True
        result = event_repository.remove("nobody", "join", "nothing.mp3")
        assert result is True
