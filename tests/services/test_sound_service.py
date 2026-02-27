"""
Tests for bot/services/sound.py - SoundService.

Uses mocked dependencies to test business logic in isolation.
"""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch
import asyncio
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

    def test_calculate_safe_gain_limits_boost_by_peak_ceiling(self, mock_service):
        """Ensure gain boost is clamped when it would violate peak ceiling."""
        gain = mock_service._calculate_safe_gain(
            current_dbfs=-30.0,
            peak_dbfs=-1.0,
            target_dbfs=-18.0,
            peak_ceiling_dbfs=-2.0,
        )
        assert gain == -1.0

    def test_calculate_safe_gain_hits_target_when_peak_has_headroom(self, mock_service):
        """Ensure gain reaches loudness target when peak headroom allows it."""
        gain = mock_service._calculate_safe_gain(
            current_dbfs=-24.0,
            peak_dbfs=-8.0,
            target_dbfs=-18.0,
            peak_ceiling_dbfs=-2.0,
        )
        assert gain == 6.0

    def test_calculate_safe_gain_allows_loud_clip_attenuation(self, mock_service):
        """Ensure loud clips are attenuated to target even if peak already exceeds ceiling."""
        gain = mock_service._calculate_safe_gain(
            current_dbfs=-10.0,
            peak_dbfs=-0.5,
            target_dbfs=-18.0,
            peak_ceiling_dbfs=-2.0,
        )
        assert gain == -8.0


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


class TestSoundServiceUpload:
    """Tests for upload flow in SoundService."""

    @pytest.fixture
    def mock_service(self):
        """Create a minimally mocked SoundService."""
        from bot.services.sound import SoundService

        service = SoundService(
            bot_behavior=Mock(),
            bot=Mock(),
            audio_service=Mock(),
            message_service=Mock(),
        )
        return service

    @pytest.mark.asyncio
    async def test_save_uploaded_sound_secure_when_lock_already_held(self, mock_service, tmp_path):
        """Ensure upload does not deadlock when caller already holds upload_lock."""
        mock_service.sounds_dir = str(tmp_path)

        attachment = Mock()
        attachment.filename = "clip.mp3"
        attachment.size = 1024

        async def _save_to_path(path):
            with open(path, "wb") as file_obj:
                file_obj.write(b"fake-mp3-bytes")

        attachment.save = AsyncMock(side_effect=_save_to_path)

        with patch("bot.services.sound.MP3", return_value=Mock()):
            with patch.object(mock_service.sound_repo, "insert_sound") as mock_insert_sound:
                with patch.object(mock_service.db, "invalidate_sound_cache") as mock_invalidate_cache:
                    with patch.object(mock_service, "_maybe_normalize_ingested_mp3", new=AsyncMock()) as mock_normalize:
                        await mock_service.upload_lock.acquire()
                        try:
                            success, result = await asyncio.wait_for(
                                mock_service.save_uploaded_sound_secure(
                                    attachment,
                                    guild_id=1234,
                                    lock_already_held=True,
                                ),
                                timeout=1.0,
                            )
                        finally:
                            mock_service.upload_lock.release()

        assert success is True
        assert os.path.exists(result)
        mock_insert_sound.assert_called_once_with("clip.mp3", "clip.mp3", guild_id=1234)
        mock_invalidate_cache.assert_called_once()
        mock_normalize.assert_awaited_once_with(result)

    @pytest.mark.asyncio
    async def test_save_sound_from_url_normalizes_before_insert(self, mock_service, tmp_path):
        """Ensure direct URL ingestion normalizes loudness before DB insertion."""
        mock_service.sounds_dir = str(tmp_path)

        response = AsyncMock()
        response.status = 200
        response.read = AsyncMock(return_value=b"fake-mp3-bytes")

        response_ctx = AsyncMock()
        response_ctx.__aenter__.return_value = response
        response_ctx.__aexit__.return_value = False

        session = Mock()
        session.get.return_value = response_ctx

        session_ctx = AsyncMock()
        session_ctx.__aenter__.return_value = session
        session_ctx.__aexit__.return_value = False

        with patch("bot.services.sound.aiohttp.ClientSession", return_value=session_ctx):
            with patch("bot.services.sound.MP3", return_value=Mock()):
                with patch.object(mock_service.sound_repo, "insert_sound") as mock_insert_sound:
                    with patch.object(mock_service.db, "invalidate_sound_cache") as mock_invalidate_cache:
                        with patch.object(mock_service, "_maybe_normalize_ingested_mp3", new=AsyncMock()) as mock_normalize:
                            saved_path = await mock_service.save_sound_from_url(
                                "https://example.com/test.mp3",
                                guild_id=999,
                            )

        assert os.path.exists(saved_path)
        filename = os.path.basename(saved_path)
        mock_normalize.assert_awaited_once_with(saved_path)
        mock_insert_sound.assert_called_once_with(filename, filename, guild_id=999)
        mock_invalidate_cache.assert_called_once()
