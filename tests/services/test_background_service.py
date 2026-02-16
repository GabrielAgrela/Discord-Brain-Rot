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

    @staticmethod
    def _history(messages):
        async def _gen():
            for message in messages:
                yield message
        return _gen()

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

    @pytest.mark.asyncio
    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    async def test_controls_normalizer_adds_controls_on_newest_bot_message_without_rewriting_others(
        self, _mock_sound_repo, _mock_action_repo
    ):
        """Ensure the backup normalizer adds controls to the newest eligible message only."""
        from bot.services.background import BackgroundService

        bot_user = Mock()
        guild = Mock()
        bot = Mock(user=bot_user)
        audio_service = Mock()
        sound_service = Mock()
        service = BackgroundService(bot=bot, audio_service=audio_service, sound_service=sound_service, behavior=Mock())

        newest_bot_message = Mock(author=bot_user)
        older_bot_message = Mock(author=bot_user)
        user_message = Mock(author=Mock())

        channel = Mock()
        channel.history = Mock(return_value=self._history([newest_bot_message, older_bot_message, user_message]))

        message_service = Mock()
        message_service.get_bot_channel.return_value = channel
        audio_service.message_service = message_service
        audio_service._message_has_send_controls_button = Mock(return_value=False)
        audio_service._remove_send_controls_button_from_message = AsyncMock()
        audio_service._is_controls_menu_message = Mock(return_value=False)

        service._add_controls_button_to_message = AsyncMock(return_value=True)

        await service._ensure_controls_button_on_last_bot_message_for_guild(guild)

        audio_service._remove_send_controls_button_from_message.assert_not_awaited()
        service._add_controls_button_to_message.assert_awaited_once_with(newest_bot_message)

    @pytest.mark.asyncio
    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    async def test_controls_normalizer_noop_when_newest_already_has_controls(
        self, _mock_sound_repo, _mock_action_repo
    ):
        """Ensure backup normalizer does nothing when newest eligible message already has controls."""
        from bot.services.background import BackgroundService

        bot_user = Mock()
        guild = Mock()
        bot = Mock(user=bot_user)
        audio_service = Mock()
        sound_service = Mock()
        service = BackgroundService(bot=bot, audio_service=audio_service, sound_service=sound_service, behavior=Mock())

        newest_bot_message = Mock(author=bot_user)

        channel = Mock()
        channel.history = Mock(return_value=self._history([newest_bot_message]))

        message_service = Mock()
        message_service.get_bot_channel.return_value = channel
        audio_service.message_service = message_service
        audio_service._message_has_send_controls_button = Mock(return_value=True)
        audio_service._remove_send_controls_button_from_message = AsyncMock()
        audio_service._is_controls_menu_message = Mock(return_value=False)

        service._add_controls_button_to_message = AsyncMock()

        await service._ensure_controls_button_on_last_bot_message_for_guild(guild)

        audio_service._remove_send_controls_button_from_message.assert_not_awaited()
        service._add_controls_button_to_message.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    async def test_controls_normalizer_removes_controls_from_older_messages(
        self, _mock_sound_repo, _mock_action_repo
    ):
        """Ensure older controls buttons are removed once a newer eligible message has controls."""
        from bot.services.background import BackgroundService

        bot_user = Mock()
        guild = Mock()
        bot = Mock(user=bot_user)
        audio_service = Mock()
        sound_service = Mock()
        service = BackgroundService(bot=bot, audio_service=audio_service, sound_service=sound_service, behavior=Mock())

        newest_bot_message = Mock(author=bot_user, id=101)
        older_bot_message = Mock(author=bot_user, id=100)

        channel = Mock()
        channel.history = Mock(return_value=self._history([newest_bot_message, older_bot_message]))

        message_service = Mock()
        message_service.get_bot_channel.return_value = channel
        audio_service.message_service = message_service
        audio_service._message_has_send_controls_button = Mock(
            side_effect=lambda msg: msg in {newest_bot_message, older_bot_message}
        )
        audio_service._remove_send_controls_button_from_message = AsyncMock()
        audio_service._is_controls_menu_message = Mock(return_value=False)

        service._add_controls_button_to_message = AsyncMock()

        await service._ensure_controls_button_on_last_bot_message_for_guild(guild)

        service._add_controls_button_to_message.assert_not_awaited()
        audio_service._remove_send_controls_button_from_message.assert_awaited_once_with(older_bot_message)

    @pytest.mark.asyncio
    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    async def test_controls_normalizer_skips_add_when_newest_bot_message_is_controls_menu(
        self, _mock_sound_repo, _mock_action_repo
    ):
        """Ensure controls menu as newest bot message redirects add to next eligible message."""
        from bot.services.background import BackgroundService

        bot_user = Mock()
        guild = Mock()
        bot = Mock(user=bot_user)
        audio_service = Mock()
        sound_service = Mock()
        service = BackgroundService(bot=bot, audio_service=audio_service, sound_service=sound_service, behavior=Mock())

        newest_bot_message = Mock(author=bot_user)
        older_bot_message = Mock(author=bot_user)

        channel = Mock()
        channel.history = Mock(return_value=self._history([newest_bot_message, older_bot_message]))

        message_service = Mock()
        message_service.get_bot_channel.return_value = channel
        audio_service.message_service = message_service
        audio_service._message_has_send_controls_button = Mock(return_value=False)
        audio_service._remove_send_controls_button_from_message = AsyncMock()
        audio_service._is_controls_menu_message = Mock(side_effect=lambda msg: msg is newest_bot_message)

        service._add_controls_button_to_message = AsyncMock(return_value=True)

        await service._ensure_controls_button_on_last_bot_message_for_guild(guild)

        audio_service._remove_send_controls_button_from_message.assert_not_awaited()
        service._add_controls_button_to_message.assert_awaited_once_with(older_bot_message)

    @pytest.mark.asyncio
    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    async def test_controls_normalizer_falls_back_when_newest_candidate_cannot_fit(
        self, _mock_sound_repo, _mock_action_repo
    ):
        """Ensure fallback to older message when newest eligible message cannot receive controls."""
        from bot.services.background import BackgroundService

        bot_user = Mock()
        guild = Mock()
        bot = Mock(user=bot_user)
        audio_service = Mock()
        sound_service = Mock()
        service = BackgroundService(bot=bot, audio_service=audio_service, sound_service=sound_service, behavior=Mock())

        newest_bot_message = Mock(author=bot_user)
        older_bot_message = Mock(author=bot_user)

        channel = Mock()
        channel.history = Mock(return_value=self._history([newest_bot_message, older_bot_message]))

        message_service = Mock()
        message_service.get_bot_channel.return_value = channel
        audio_service.message_service = message_service
        audio_service._message_has_send_controls_button = Mock(return_value=False)
        audio_service._remove_send_controls_button_from_message = AsyncMock()
        audio_service._is_controls_menu_message = Mock(return_value=False)

        service._add_controls_button_to_message = AsyncMock(side_effect=[False, True])

        await service._ensure_controls_button_on_last_bot_message_for_guild(guild)

        audio_service._remove_send_controls_button_from_message.assert_not_awaited()
        assert service._add_controls_button_to_message.await_count == 2
        service._add_controls_button_to_message.assert_any_await(newest_bot_message)
        service._add_controls_button_to_message.assert_any_await(older_bot_message)

    def test_find_available_component_row_uses_message_component_widths(self):
        """Ensure row selection avoids full row 0 when reconstructed item rows are missing."""
        from bot.services.background import BackgroundService

        # Simulate real message rows where row 0 is full and row 1 has space.
        row0 = Mock(children=[Mock(), Mock(), Mock(), Mock(), Mock()])
        row1 = Mock(children=[Mock(), Mock()])
        message = Mock(components=[row0, row1])

        # Reconstructed views can have items with row=None, so fallback-only logic is wrong.
        view = Mock(children=[Mock(row=None), Mock(row=None)])

        selected_row = BackgroundService._find_available_component_row(message, view)
        assert selected_row == 1

    @pytest.mark.asyncio
    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    async def test_add_controls_button_to_message_skips_when_already_present(
        self, _mock_sound_repo, _mock_action_repo
    ):
        """Ensure no edit occurs when the target message already has controls."""
        from bot.services.background import BackgroundService

        service = BackgroundService(
            bot=Mock(),
            audio_service=Mock(),
            sound_service=Mock(),
            behavior=Mock(),
        )

        component = Mock(custom_id="send_controls_button")
        row = Mock(children=[component])
        message = AsyncMock(components=[row])

        added = await service._add_controls_button_to_message(message)

        assert added is True
        message.edit.assert_not_awaited()
