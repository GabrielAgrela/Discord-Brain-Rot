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

    def test_has_action_for_target(self, action_repository):
        """Test checking for an existing action-target pair."""
        action_repository.insert("user1", "weekly_wrapped_sent", "week:2026-02-16", guild_id=123)

        assert action_repository.has_action_for_target(
            action="weekly_wrapped_sent",
            target="week:2026-02-16",
            guild_id=123,
        ) is True
        assert action_repository.has_action_for_target(
            action="weekly_wrapped_sent",
            target="week:2026-02-09",
            guild_id=123,
        ) is False

    def test_has_action_for_target_include_global(self, action_repository):
        """Test guild-scoped checks with optional global-row fallback."""
        action_repository.insert("user1", "weekly_wrapped_sent", "week:2026-02-16")

        assert action_repository.has_action_for_target(
            action="weekly_wrapped_sent",
            target="week:2026-02-16",
            guild_id=123,
        ) is False
        assert action_repository.has_action_for_target(
            action="weekly_wrapped_sent",
            target="week:2026-02-16",
            guild_id=123,
            include_global=True,
        ) is True


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
    
    def test_get_sounds_on_this_day_empty(self, action_repository):
        """Test get_sounds_on_this_day returns empty list when no data."""
        sounds = action_repository.get_sounds_on_this_day(months_ago=12, limit=10)
        assert sounds == []
    
    def test_get_sounds_on_this_day_with_data(self, action_repository, db_connection):
        """Test get_sounds_on_this_day returns historical sounds."""
        from datetime import datetime, timedelta
        
        cursor = db_connection.cursor()
        
        # Insert a sound
        cursor.execute(
            "INSERT INTO sounds (originalfilename, Filename, date, favorite, blacklist, slap) VALUES (?, ?, ?, ?, ?, ?)",
            ("old_sound.mp3", "old_sound.mp3", "2025-01-13 10:00:00", 0, 0, 0)
        )
        sound_id = cursor.lastrowid
        
        # Insert action from ~1 year ago (implementation uses months_ago * 30 days)
        target_date = datetime.now() - timedelta(days=12 * 30)  # 360 days, matches implementation
        action_timestamp = target_date.strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute(
            "INSERT INTO actions (username, action, target, timestamp) VALUES (?, ?, ?, ?)",
            ("user1", "play_request", str(sound_id), action_timestamp)
        )
        cursor.execute(
            "INSERT INTO actions (username, action, target, timestamp) VALUES (?, ?, ?, ?)",
            ("user2", "play_random_sound", str(sound_id), action_timestamp)
        )
        db_connection.commit()
        
        sounds = action_repository.get_sounds_on_this_day(months_ago=12, limit=10)
        
        # Should find the sound with 2 plays
        assert len(sounds) == 1
        assert sounds[0][0] == "old_sound.mp3"
        assert sounds[0][1] == 2
    
    def test_get_sounds_on_this_day_excludes_slaps(self, action_repository, db_connection):
        """Test that slap sounds are excluded from On This Day results."""
        from datetime import datetime, timedelta
        
        cursor = db_connection.cursor()
        
        # Insert a slap sound
        cursor.execute(
            "INSERT INTO sounds (originalfilename, Filename, date, favorite, blacklist, slap) VALUES (?, ?, ?, ?, ?, ?)",
            ("slap_sound.mp3", "slap_sound.mp3", "2025-01-13 10:00:00", 0, 0, 1)  # slap = 1
        )
        slap_sound_id = cursor.lastrowid
        
        # Insert action from ~1 year ago (implementation uses months_ago * 30 days)
        target_date = datetime.now() - timedelta(days=12 * 30)  # 360 days
        action_timestamp = target_date.strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute(
            "INSERT INTO actions (username, action, target, timestamp) VALUES (?, ?, ?, ?)",
            ("user1", "play_request", str(slap_sound_id), action_timestamp)
        )
        db_connection.commit()
        
        sounds = action_repository.get_sounds_on_this_day(months_ago=12, limit=10)
        
        # Should not include slap sounds
        assert len(sounds) == 0
