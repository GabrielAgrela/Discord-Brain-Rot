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
            title="🔍 MyInstants scraper started",
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

    @pytest.mark.asyncio
    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    async def test_notify_scraper_complete_sends_short_summary_image(
        self, _mock_sound_repo, _mock_action_repo
    ):
        """Ensure scraper completion notification includes a compact summary."""
        from bot.services.background import BackgroundService

        behavior = Mock()
        behavior.send_message = AsyncMock()

        service = BackgroundService(
            bot=Mock(),
            audio_service=Mock(),
            sound_service=Mock(),
            behavior=behavior,
        )

        await service._notify_scraper_complete(
            {
                "countries_scanned": 3,
                "total_sounds_seen": 312,
                "new_sounds_detected": 14,
                "sounds_added": 9,
                "sounds_invalid": 5,
                "scrape_errors": 1,
                "duration_seconds": 12.8,
            }
        )

        behavior.send_message.assert_awaited_once_with(
            title="✅ MyInstants scraper finished",
            description="3 sites checked in 12.8s | 312 sounds seen | 14 new sounds found (9 downloaded) | 5 skipped/invalid | 1 site errors",
            message_format="image",
            image_requester="MyInstants Scraper",
            image_show_footer=False,
            image_show_sound_icon=False,
            image_border_color="#ED4245",
        )

    @pytest.mark.asyncio
    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    async def test_notify_scraper_failure_sends_error_image(self, _mock_sound_repo, _mock_action_repo):
        """Ensure scraper failure notification is sent with error details."""
        from bot.services.background import BackgroundService

        behavior = Mock()
        behavior.send_message = AsyncMock()

        service = BackgroundService(
            bot=Mock(),
            audio_service=Mock(),
            sound_service=Mock(),
            behavior=behavior,
        )

        await service._notify_scraper_failure(RuntimeError("network timeout"))

        behavior.send_message.assert_awaited_once_with(
            title="⚠️ MyInstants scraper failed",
            description="network timeout",
            message_format="image",
            image_requester="MyInstants Scraper",
            image_show_footer=False,
            image_show_sound_icon=False,
            image_border_color="#ED4245",
        )
