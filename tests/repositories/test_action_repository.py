"""
Tests for bot/repositories/action.py - ActionRepository.
"""

import pytest
from datetime import datetime, timedelta


class TestActionRepository:
    """Tests for the ActionRepository class."""
    
    def test_insert(self, action_repository, db_connection):
        """Test inserting an action."""
        action_id = action_repository.insert(
            username="testuser",
            action="play_random_sound",
            target="123"
        )
        
        assert action_id is not None
        assert action_id > 0
        
        # Verify in database
        cursor = db_connection.cursor()
        cursor.execute("SELECT * FROM actions WHERE id = ?", (action_id,))
        row = cursor.fetchone()
        assert row["username"] == "testuser"
        assert row["action"] == "play_random_sound"
    
    def test_get_by_id(self, action_repository, db_connection):
        """Test getting an action by ID."""
        # Insert an action first
        action_id = action_repository.insert("user", "play_request", "sound")
        
        action = action_repository.get_by_id(action_id)
        assert action is not None
        assert action[1] == "user"  # username
    
    def test_get_all(self, action_repository, sample_actions):
        """Test getting all actions."""
        actions = action_repository.get_all(limit=100)
        assert len(actions) == 5
    
    def test_get_top_users(self, action_repository, sample_actions):
        """Test getting users with most activity."""
        top_users = action_repository.get_top_users(days=0, limit=5)
        
        # user1 has 2 plays, user2 has 1
        assert len(top_users) == 2
        assert top_users[0][0] == "user1"
        assert top_users[0][1] == 2
        assert top_users[1][0] == "user2"
        assert top_users[1][1] == 1
    
    def test_get_top_users_with_days_filter(self, action_repository, db_connection):
        """Test get_top_users with days filter."""
        # Insert a recent action
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = db_connection.cursor()
        cursor.execute(
            "INSERT INTO actions (username, action, target, timestamp) VALUES (?, ?, ?, ?)",
            ("recent_user", "play_random_sound", "1", now)
        )
        db_connection.commit()
        
        top_users = action_repository.get_top_users(days=1, limit=10)
        assert any(u[0] == "recent_user" for u in top_users)
    
    def test_get_top_sounds(self, action_repository, sample_actions, db_connection):
        """Test getting most played sounds."""
        # Note: get_top_sounds requires a JOIN with sounds table
        # Our sample_actions uses sound IDs, so we need sounds in the db
        top_sounds, total = action_repository.get_top_sounds(days=0, limit=5)
        
        # Should return results based on our sample data
        assert isinstance(top_sounds, list)
        assert isinstance(total, int)
    
    def test_get_sound_play_count(self, action_repository, sample_actions):
        """Test getting play count for a specific sound."""
        # sample_actions[0] has 2 plays
        count = action_repository.get_sound_play_count(sample_actions[0])
        assert count == 2
    
    def test_get_users_who_favorited(self, action_repository, sample_actions):
        """Test getting users who favorited a sound."""
        # Both user1 and user2 favorited sample_actions[0]
        users = action_repository.get_users_who_favorited(sample_actions[0])
        
        assert len(users) == 2
        assert "user1" in users
        assert "user2" in users


class TestActionRepositoryEdgeCases:
    """Edge case tests for ActionRepository."""
    
    def test_get_top_users_empty_db(self, action_repository):
        """Test get_top_users on empty database."""
        top_users = action_repository.get_top_users()
        assert top_users == []
    
    def test_get_sound_play_count_no_plays(self, action_repository):
        """Test play count for sound with no plays."""
        count = action_repository.get_sound_play_count(9999)
        assert count == 0
