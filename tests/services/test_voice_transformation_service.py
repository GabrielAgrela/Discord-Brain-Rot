"""
Tests for bot/services/voice_transformation.py - VoiceTransformationService.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestVoiceTransformationService:
    """Tests for action logging around STS and isolation flows."""

    @pytest.mark.asyncio
    async def test_sts_el_logs_resolved_sound_id(self):
        """STS should log a stable sound ID so downstream stats can join against sounds."""
        with patch("bot.services.voice_transformation.TTS") as mock_tts_cls, patch(
            "bot.services.voice_transformation.ActionRepository"
        ) as mock_action_repo_cls, patch(
            "bot.services.voice_transformation.SoundRepository"
        ) as mock_sound_repo_cls:
            action_repo = Mock()
            sound_repo = Mock()
            sound_repo.get_sound_by_name.return_value = (17, "orig.mp3", "clip.mp3")

            tts_engine = Mock()
            tts_engine.speech_to_speech = AsyncMock(return_value=None)

            mock_action_repo_cls.return_value = action_repo
            mock_sound_repo_cls.return_value = sound_repo
            mock_tts_cls.return_value = tts_engine

            from bot.services.voice_transformation import VoiceTransformationService

            service = VoiceTransformationService(bot=Mock(), audio_service=Mock(), message_service=Mock())
            user = SimpleNamespace(name="gabi", display_name="Gabi", guild=SimpleNamespace(id=123))

            await service.sts_EL(user, "clip", "ventura")

            action_repo.insert.assert_called_once_with("gabi", "sts_EL", "17", guild_id=123)

    @pytest.mark.asyncio
    async def test_isolate_voice_logs_actor_and_falls_back_to_sound_name(self):
        """Isolation should still log when the source sound cannot be resolved to a DB row."""
        with patch("bot.services.voice_transformation.TTS") as mock_tts_cls, patch(
            "bot.services.voice_transformation.ActionRepository"
        ) as mock_action_repo_cls, patch(
            "bot.services.voice_transformation.SoundRepository"
        ) as mock_sound_repo_cls:
            action_repo = Mock()
            sound_repo = Mock()
            sound_repo.get_sound_by_name.return_value = None

            tts_engine = Mock()
            tts_engine.isolate_voice = AsyncMock(return_value=None)

            mock_action_repo_cls.return_value = action_repo
            mock_sound_repo_cls.return_value = sound_repo
            mock_tts_cls.return_value = tts_engine

            from bot.services.voice_transformation import VoiceTransformationService

            service = VoiceTransformationService(bot=Mock(), audio_service=Mock(), message_service=Mock())

            await service.isolate_voice("mystery-sound", guild_id=456, requested_by="moderator")

            action_repo.insert.assert_called_once_with(
                "moderator",
                "isolate",
                "mystery-sound",
                guild_id=456,
            )
