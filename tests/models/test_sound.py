"""
Tests for bot/models/sound.py - Sound, SoundEffect, and SoundList models.
"""

import pytest
from datetime import datetime

from bot.models.sound import Sound, SoundEffect, SoundList


class TestSound:
    """Tests for the Sound model."""
    
    def test_from_db_row_full(self):
        """Test creating a Sound from a full database row."""
        row = (1, "original.mp3", "renamed.mp3", "2024-01-15 10:30:00", 1, 0, 1)
        sound = Sound.from_db_row(row)
        
        assert sound.id == 1
        assert sound.original_filename == "original.mp3"
        assert sound.filename == "renamed.mp3"
        assert sound.favorite is True
        assert sound.slap is True
        assert sound.date == datetime(2024, 1, 15, 10, 30, 0)
    
    def test_from_db_row_minimal(self):
        """Test creating a Sound from a minimal row (id, original, filename)."""
        row = (5, "test.mp3", "test.mp3")
        sound = Sound.from_db_row(row)
        
        assert sound.id == 5
        assert sound.original_filename == "test.mp3"
        assert sound.filename == "test.mp3"
        assert sound.favorite is False
        assert sound.slap is False
    
    def test_from_db_row_invalid_length(self):
        """Test that invalid row length raises ValueError."""
        row = (1, "only_two")
        with pytest.raises(ValueError, match="Invalid row length"):
            Sound.from_db_row(row)
    
    def test_name_property(self):
        """Test the name property strips .mp3 extension."""
        sound = Sound(id=1, original_filename="test.mp3", filename="cool_sound.mp3")
        assert sound.name == "cool_sound"
    
    def test_name_property_no_extension(self):
        """Test name property when filename has no .mp3 extension."""
        sound = Sound(id=1, original_filename="test", filename="no_extension")
        assert sound.name == "no_extension"
    
    def test_str_returns_name(self):
        """Test __str__ returns the name."""
        sound = Sound(id=1, original_filename="test.mp3", filename="display.mp3")
        assert str(sound) == "display"


class TestSoundEffect:
    """Tests for the SoundEffect model."""
    
    def test_default_values(self):
        """Test default effect values."""
        effect = SoundEffect()
        assert effect.speed == 1.0
        assert effect.volume == 1.0
        assert effect.reverse is False
    
    def test_speed_clamping_min(self):
        """Test speed is clamped to minimum 0.5."""
        effect = SoundEffect(speed=0.1)
        assert effect.speed == 0.5
    
    def test_speed_clamping_max(self):
        """Test speed is clamped to maximum 3.0."""
        effect = SoundEffect(speed=5.0)
        assert effect.speed == 3.0
    
    def test_volume_clamping_min(self):
        """Test volume is clamped to minimum 0.1."""
        effect = SoundEffect(volume=0.01)
        assert effect.volume == 0.1
    
    def test_volume_clamping_max(self):
        """Test volume is clamped to maximum 5.0."""
        effect = SoundEffect(volume=10.0)
        assert effect.volume == 5.0
    
    def test_from_dict_empty(self):
        """Test from_dict with None returns defaults."""
        effect = SoundEffect.from_dict(None)
        assert effect.speed == 1.0
        assert effect.volume == 1.0
        assert effect.reverse is False
    
    def test_from_dict_with_values(self):
        """Test from_dict with values."""
        data = {"speed": 1.5, "volume": 2.0, "reverse": True}
        effect = SoundEffect.from_dict(data)
        
        assert effect.speed == 1.5
        assert effect.volume == 2.0
        assert effect.reverse is True
    
    def test_to_dict(self):
        """Test to_dict conversion."""
        effect = SoundEffect(speed=2.0, volume=1.5, reverse=True)
        d = effect.to_dict()
        
        assert d["speed"] == 2.0
        assert d["volume"] == 1.5
        assert d["reverse"] is True
    
    def test_has_effects_true(self):
        """Test has_effects returns True when effects are applied."""
        assert SoundEffect(speed=1.5).has_effects() is True
        assert SoundEffect(volume=2.0).has_effects() is True
        assert SoundEffect(reverse=True).has_effects() is True
    
    def test_has_effects_false(self):
        """Test has_effects returns False for defaults."""
        effect = SoundEffect()
        assert effect.has_effects() is False


class TestSoundList:
    """Tests for the SoundList model."""
    
    def test_from_db_row_full(self):
        """Test creating a SoundList from a full row."""
        row = (1, "favorites", "user1", "2024-01-01 00:00:00", 10)
        sound_list = SoundList.from_db_row(row)
        
        assert sound_list.id == 1
        assert sound_list.name == "favorites"
        assert sound_list.creator == "user1"
        assert sound_list.created_at == datetime(2024, 1, 1, 0, 0, 0)
        assert sound_list.sound_count == 10
    
    def test_from_db_row_minimal(self):
        """Test creating a SoundList without sound_count."""
        row = (2, "my_list", "user2", None)
        sound_list = SoundList.from_db_row(row)
        
        assert sound_list.id == 2
        assert sound_list.name == "my_list"
        assert sound_list.creator == "user2"
        assert sound_list.created_at is None
        assert sound_list.sound_count == 0
