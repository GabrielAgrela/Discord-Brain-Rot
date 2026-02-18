"""
Tests for bot/repositories/sound.py - SoundRepository.
"""

import pytest
from datetime import datetime


class TestSoundRepository:
    """Tests for the SoundRepository class."""
    
    def test_insert_sound(self, sound_repository, db_connection):
        """Test inserting a new sound."""
        sound_id = sound_repository.insert_sound(
            original_filename="new_sound.mp3",
            filename="new_sound.mp3"
        )
        
        assert sound_id is not None
        assert sound_id > 0
        
        # Verify in database
        cursor = db_connection.cursor()
        cursor.execute("SELECT * FROM sounds WHERE id = ?", (sound_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["Filename"] == "new_sound.mp3"
    
    def test_get_by_id(self, sound_repository, sample_sounds):
        """Test getting a sound by ID."""
        sound = sound_repository.get_by_id(sample_sounds[0])
        
        assert sound is not None
        assert sound.id == sample_sounds[0]
        assert sound.filename == "sound1.mp3"
    
    def test_get_by_id_not_found(self, sound_repository):
        """Test getting a non-existent sound returns None."""
        sound = sound_repository.get_by_id(9999)
        assert sound is None
    
    def test_get_by_filename(self, sound_repository, sample_sounds):
        """Test getting a sound by filename."""
        sound = sound_repository.get_by_filename("sound2.mp3")
        
        assert sound is not None
        assert sound.filename == "sound2.mp3"
    
    def test_get_by_filename_without_extension(self, sound_repository, sample_sounds):
        """Test getting a sound by filename without .mp3 extension."""
        sound = sound_repository.get_by_filename("sound1")
        
        assert sound is not None
        assert sound.filename == "sound1.mp3"
    
    def test_get_all(self, sound_repository, sample_sounds):
        """Test getting all sounds."""
        sounds = sound_repository.get_all(limit=100)
        
        assert len(sounds) == 4
    
    def test_get_random(self, sound_repository, sample_sounds):
        """Test getting random sounds."""
        sounds = sound_repository.get_random(count=2)
        
        assert len(sounds) == 2
        for sound in sounds:
            assert sound.id in sample_sounds
    
    def test_get_random_favorite_only(self, sound_repository, sample_sounds):
        """Test getting random favorite sounds."""
        sounds = sound_repository.get_random(count=5, favorite_only=True)
        
        # Only sound1 is a favorite
        assert len(sounds) == 1
        assert sounds[0].favorite is True
    
    def test_update_sound(self, sound_repository, sample_sounds, db_connection):
        """Test updating a sound."""
        sound_repository.update_sound("sound1.mp3", new_filename="updated.mp3")
        
        # Verify the update
        cursor = db_connection.cursor()
        cursor.execute("SELECT Filename FROM sounds WHERE id = ?", (sample_sounds[0],))
        row = cursor.fetchone()
        assert row["Filename"] == "updated.mp3"
    
    def test_update_favorite_status(self, sound_repository, sample_sounds):
        """Test updating favorite status."""
        sound_repository.update(sample_sounds[1], favorite=True)
        
        sound = sound_repository.get_by_id(sample_sounds[1])
        assert sound.favorite is True
    
    def test_get_favorites(self, sound_repository, sample_sounds):
        """Test getting favorite sounds."""
        favorites = sound_repository.get_favorites()
        
        assert len(favorites) == 1
        assert favorites[0].favorite is True
    
    def test_search(self, sound_repository, sample_sounds):
        """Test basic sound search."""
        results = sound_repository.search("sound1")
        
        assert len(results) > 0
        # Results are (Sound, score) tuples
        assert results[0][0].filename == "sound1.mp3"
    
    def test_delete(self, sound_repository, sample_sounds, db_connection):
        """Test deleting a sound."""
        sound_repository.delete(sample_sounds[0])
        
        cursor = db_connection.cursor()
        cursor.execute("SELECT * FROM sounds WHERE id = ?", (sample_sounds[0],))
        row = cursor.fetchone()
        assert row is None
    
    def test_get_play_count(self, sound_repository, sample_sounds, db_connection):
        """Test getting play count for a sound."""
        # Insert some play actions directly using the action names that get_play_count filters for
        cursor = db_connection.cursor()
        cursor.execute(
            "INSERT INTO actions (username, action, target, timestamp) VALUES (?, ?, ?, ?)",
            ("user1", "play", str(sample_sounds[0]), "2024-01-01 10:00:00")
        )
        cursor.execute(
            "INSERT INTO actions (username, action, target, timestamp) VALUES (?, ?, ?, ?)",
            ("user2", "play_random", str(sample_sounds[0]), "2024-01-01 11:00:00")
        )
        db_connection.commit()
        
        count = sound_repository.get_play_count(sample_sounds[0])
        assert count == 2


class TestSoundRepositoryEdgeCases:
    """Edge case tests for SoundRepository."""
    
    def test_get_random_empty_db(self, sound_repository):
        """Test getting random from empty database."""
        sounds = sound_repository.get_random(count=1)
        assert sounds == []
    
    def test_search_no_results(self, sound_repository, sample_sounds):
        """Test search with no matching results."""
        results = sound_repository.search("nonexistent_xyz")
        assert len(results) == 0

    def test_get_by_filename_prefers_guild_local_over_global(self, sound_repository, db_connection):
        """Guild-scoped lookups should prefer guild-local row over global fallback."""
        cursor = db_connection.cursor()
        cursor.execute(
            """
            INSERT INTO sounds (originalfilename, Filename, date, favorite, blacklist, slap, is_elevenlabs, timestamp, guild_id)
            VALUES (?, ?, ?, 0, 0, 0, 0, ?, NULL)
            """,
            ("shared.mp3", "shared.mp3", "2025-01-01 00:00:00", "2025-01-01 00:00:00"),
        )
        cursor.execute(
            """
            INSERT INTO sounds (originalfilename, Filename, date, favorite, blacklist, slap, is_elevenlabs, timestamp, guild_id)
            VALUES (?, ?, ?, 0, 0, 0, 0, ?, ?)
            """,
            ("shared.mp3", "shared.mp3", "2025-01-01 00:00:01", "2025-01-01 00:00:01", "42"),
        )
        db_connection.commit()

        sound = sound_repository.get_by_filename("shared.mp3", guild_id=42)
        assert sound is not None
        assert sound.id == 2

    def test_get_sounds_scoped_to_guild_keeps_global_fallback(self, sound_repository, db_connection):
        """Guild-scoped sound listing should include guild-local and global rows only."""
        cursor = db_connection.cursor()
        rows = [
            ("global.mp3", "global.mp3", "2025-01-01 00:00:00", None),
            ("guild42.mp3", "guild42.mp3", "2025-01-01 00:00:01", "42"),
            ("guild43.mp3", "guild43.mp3", "2025-01-01 00:00:02", "43"),
        ]
        for original, filename, ts, guild_id in rows:
            cursor.execute(
                """
                INSERT INTO sounds (originalfilename, Filename, date, favorite, blacklist, slap, is_elevenlabs, timestamp, guild_id)
                VALUES (?, ?, ?, 0, 0, 0, 0, ?, ?)
                """,
                (original, filename, ts, ts, guild_id),
            )
        db_connection.commit()

        sounds = sound_repository.get_sounds(num_sounds=20, guild_id=42)
        filenames = {row[2] for row in sounds}
        assert "global.mp3" in filenames
        assert "guild42.mp3" in filenames
        assert "guild43.mp3" not in filenames
