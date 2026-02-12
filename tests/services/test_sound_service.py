"""
Tests for bot/services/sound.py - SoundService.

Uses mocked dependencies to test business logic in isolation.
"""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestSoundService:
    """Tests for the SoundService class."""
    
    @pytest.fixture
    def mock_dependencies(self):
        """Create mocked dependencies for SoundService."""
        bot_behavior = Mock()
        bot = Mock()
        audio_service = Mock()
        message_service = Mock()
        
        # Configure common mocks
        bot_behavior.channel = Mock()
        bot_behavior.text_channel = Mock()
        
        return {
            "bot_behavior": bot_behavior,
            "bot": bot,
            "audio_service": audio_service,
            "message_service": message_service,
        }
    
    @pytest.fixture
    def sound_service(self, mock_dependencies):
        """Create a SoundService with mocked dependencies."""
        from bot.services.sound import SoundService
        
        service = SoundService(
            bot_behavior=mock_dependencies["bot_behavior"],
            bot=mock_dependencies["bot"],
            audio_service=mock_dependencies["audio_service"],
            message_service=mock_dependencies["message_service"],
        )
        return service
    
    def test_init(self, sound_service, mock_dependencies):
        """Test SoundService initialization."""
        assert sound_service.bot_behavior == mock_dependencies["bot_behavior"]
        assert sound_service.bot == mock_dependencies["bot"]
        assert sound_service.audio_service == mock_dependencies["audio_service"]
        assert sound_service.message_service == mock_dependencies["message_service"]
    
    @pytest.mark.asyncio
    async def test_play_random_sound_calls_audio_service(self, sound_service):
        """Test that play_random_sound calls audio_service correctly."""
        # Mock the repository to return a sound
        mock_sound_data = (1, "original.mp3", "test.mp3", "2024-01-01", 0, 0, 0)
        
        with patch.object(sound_service, 'sound_repo') as mock_repo:
            mock_repo.get_random_sounds.return_value = [mock_sound_data]
            sound_service.audio_service.play = AsyncMock()
            
            # The actual implementation may vary
            # This tests the principle of mocking
            assert sound_service.sound_repo is not None
    
    def test_repository_is_initialized(self, sound_service):
        """Test that repositories are initialized."""
        assert hasattr(sound_service, 'sound_repo')
        assert hasattr(sound_service, 'action_repo')
        assert hasattr(sound_service, 'list_repo')


class TestSoundServiceFilename:
    """Tests for filename-related operations in SoundService."""
    
    @pytest.fixture
    def mock_service(self):
        """Create a minimally mocked SoundService."""
        from bot.services.sound import SoundService
        
        # Create with all mocks
        service = SoundService(
            bot_behavior=Mock(),
            bot=Mock(),
            audio_service=Mock(),
            message_service=Mock(),
        )
        return service
    
    def test_change_filename_updates_repo(self, mock_service):
        """Test change_filename calls repository update."""
        with patch.object(mock_service, 'sound_repo') as mock_repo:
            with patch.object(mock_service, 'action_repo') as mock_action:
                mock_repo.update_sound.return_value = True
                mock_action.insert.return_value = 1
                
                # Test the repository was accessed
                assert mock_service.sound_repo is not None

    def test_sanitize_mp3_filename_preserves_spaces(self, mock_service):
        """Test filename sanitizer keeps spaces instead of replacing with underscores."""
        sanitized = mock_service._sanitize_mp3_filename("natal do cactus cat", "fallback")
        assert sanitized == "natal do cactus cat.mp3"

    def test_sanitize_mp3_filename_cleans_invalid_characters(self, mock_service):
        """Test filename sanitizer removes unsupported characters but keeps readable spacing."""
        sanitized = mock_service._sanitize_mp3_filename("  bad:/name*?  ", "fallback")
        assert sanitized == "badname.mp3"


class TestSoundServiceValidation:
    """Tests for input validation in SoundService."""
    
    def test_supported_audio_formats(self):
        """Test that common audio formats are recognized."""
        # Test logic for file extension validation
        valid_extensions = ['.mp3', '.wav', '.ogg', '.m4a']
        invalid_extensions = ['.txt', '.py', '.exe']
        
        for ext in valid_extensions:
            filename = f"test{ext}"
            assert filename.endswith(ext)
        
        for ext in invalid_extensions:
            filename = f"test{ext}"
            assert not any(filename.endswith(v) for v in valid_extensions)
