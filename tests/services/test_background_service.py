"""
Tests for bot/services/background.py - BackgroundService.
"""

import os
import sys
from unittest.mock import AsyncMock, Mock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestBackgroundService:
    """Tests for background service notification behavior."""

    @pytest.mark.asyncio
    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    async def test_notify_scraper_start_sends_red_border_image(self, _mock_sound_repo, _mock_action_repo):
        """Ensure scraper start notification uses image format with red border."""
        from bot.services.background import BackgroundService

        behavior = Mock()
        behavior.send_message = AsyncMock()

        service = BackgroundService(
            bot=Mock(),
            audio_service=Mock(),
            sound_service=Mock(),
            behavior=behavior,
        )

        await service._notify_scraper_start()

        behavior.send_message.assert_awaited_once_with(
            title="MyInstants scraper started",
            message_format="image",
            image_requester="MyInstants Scraper",
            image_show_footer=False,
            image_show_sound_icon=False,
            image_border_color="#ED4245",
        )

    @pytest.mark.asyncio
    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    async def test_notify_scraper_start_without_behavior_noop(self, _mock_sound_repo, _mock_action_repo):
        """Ensure scraper notification exits quietly when no behavior is attached."""
        from bot.services.background import BackgroundService

        service = BackgroundService(
            bot=Mock(),
            audio_service=Mock(),
            sound_service=Mock(),
            behavior=None,
        )

        await service._notify_scraper_start()
