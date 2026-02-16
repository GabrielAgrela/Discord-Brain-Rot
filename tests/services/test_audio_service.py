"""
Tests for bot/services/audio.py - AudioService helper behavior.
"""

import os
import sys
from unittest.mock import AsyncMock, Mock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class _DummyView:
    """Simple stand-in for a Discord view used in unit tests."""

    def __init__(self, children):
        self.children = children

    def remove_item(self, item):
        self.children.remove(item)


class _DummyComponent:
    """Simple stand-in for a Discord message component."""

    def __init__(self, payload, custom_id=None, emoji=None, label=None):
        self._payload = payload
        self.custom_id = custom_id
        self.emoji = emoji
        self.label = label

    def to_dict(self):
        return dict(self._payload)


class _DummyRow:
    """Simple stand-in for a Discord action row component."""

    def __init__(self, children, row_id=None):
        self.children = children
        self.id = row_id


class TestAudioService:
    """Tests for AudioService utility methods."""

    @pytest.fixture
    def audio_service(self):
        """Create an AudioService instance without running full initialization."""
        from bot.services.audio import AudioService

        service = AudioService.__new__(AudioService)
        service._last_gear_message_by_channel = {}
        service._progress_update_task = None
        return service

    @pytest.mark.asyncio
    async def test_remove_send_controls_button_from_message_removes_gear_only(self, audio_service):
        """Ensure only the gear button is removed using raw component payload edits."""
        gear_button = _DummyComponent(
            payload={"type": 2, "style": 1, "custom_id": "send_controls_button", "emoji": {"name": "⚙️"}, "label": ""},
            custom_id="send_controls_button",
            emoji="⚙️",
            label="",
        )
        play_button = _DummyComponent(
            payload={"type": 2, "style": 1, "custom_id": "progress_button", "label": "✅ ▬▬🔘▬▬ 0:02"},
            custom_id="progress_button",
            emoji=None,
            label="✅ ▬▬🔘▬▬ 0:02",
        )
        row = _DummyRow([gear_button, play_button], row_id=0)

        message = AsyncMock()
        message.components = [row]
        message.id = 123
        message.channel = Mock(id=456)
        message.channel.fetch_message = AsyncMock(return_value=message)
        message._state = Mock()
        message._state.http = Mock()
        message._state.http.edit_message = AsyncMock()

        await audio_service._remove_send_controls_button_from_message(message)

        message._state.http.edit_message.assert_awaited_once_with(
            456,
            123,
            components=[
                {
                    "type": 1,
                    "id": 0,
                    "components": [play_button.to_dict()],
                }
            ],
        )

    def test_is_send_controls_item_accepts_normalized_gear_emoji(self, audio_service):
        """Ensure gear matching works for both emoji representations used by Discord."""
        item_with_vs = Mock(emoji="⚙️", label="")
        item_without_vs = Mock(emoji="⚙", label="")
        item_with_text_vs = Mock(emoji="⚙︎", label="")
        item_by_custom_id = Mock(custom_id="send_controls_button", emoji="x", label="foo")

        assert audio_service._is_send_controls_item(item_with_vs) is True
        assert audio_service._is_send_controls_item(item_without_vs) is True
        assert audio_service._is_send_controls_item(item_with_text_vs) is True
        assert audio_service._is_send_controls_item(item_by_custom_id) is True

    def test_message_has_send_controls_button_from_raw_components(self, audio_service):
        """Ensure raw message component scanning finds controls buttons without view reconstruction."""
        controls_component = Mock(custom_id="send_controls_button")
        row = Mock(children=[controls_component])
        message = Mock(components=[row])

        with patch("bot.services.audio.discord.ui.View.from_message", side_effect=RuntimeError("boom")):
            assert audio_service._message_has_send_controls_button(message) is True

    @pytest.mark.asyncio
    async def test_remove_send_controls_button_from_message_no_gear_no_edit(self, audio_service):
        """Ensure no message edit occurs when no gear button exists."""
        play_button = _DummyComponent(
            payload={"type": 2, "style": 1, "custom_id": "progress_button", "label": "▶️ ▬▬🔘▬▬ 0:02"},
            custom_id="progress_button",
            emoji=None,
            label="▶️ ▬▬🔘▬▬ 0:02",
        )
        row = _DummyRow([play_button], row_id=0)

        message = AsyncMock()
        message.components = [row]
        message.id = 123
        message.channel = Mock(id=456)
        message.channel.fetch_message = AsyncMock(return_value=message)
        message._state = Mock()
        message._state.http = Mock()
        message._state.http.edit_message = AsyncMock()

        await audio_service._remove_send_controls_button_from_message(message)

        message._state.http.edit_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_remove_send_controls_button_uses_refreshed_message_components(self, audio_service):
        """Ensure gear removal uses the latest fetched message state to preserve progress text."""
        stale_progress = _DummyComponent(
            payload={"type": 2, "style": 1, "custom_id": "progress_button", "label": "▶️ ▬▬🔘▬▬ 0:02"},
            custom_id="progress_button",
            label="▶️ ▬▬🔘▬▬ 0:02",
        )
        stale_gear = _DummyComponent(
            payload={"type": 2, "style": 1, "custom_id": "send_controls_button", "emoji": {"name": "⚙️"}, "label": ""},
            custom_id="send_controls_button",
            emoji="⚙️",
            label="",
        )
        stale_message = AsyncMock()
        stale_message.id = 999
        stale_message.components = [_DummyRow([stale_progress, stale_gear], row_id=0)]
        stale_message.channel = Mock(id=777)

        fresh_progress = _DummyComponent(
            payload={"type": 2, "style": 1, "custom_id": "progress_button", "label": "👋 ▬▬🔘▬▬ 0:04"},
            custom_id="progress_button",
            label="👋 ▬▬🔘▬▬ 0:04",
        )
        fresh_gear = _DummyComponent(
            payload={"type": 2, "style": 1, "custom_id": "send_controls_button", "emoji": {"name": "⚙️"}, "label": ""},
            custom_id="send_controls_button",
            emoji="⚙️",
            label="",
        )
        fresh_message = AsyncMock()
        fresh_message.id = 999
        fresh_message.channel = Mock(id=777)
        fresh_message.components = [_DummyRow([fresh_progress, fresh_gear], row_id=0)]
        fresh_message._state = Mock()
        fresh_message._state.http = Mock()
        fresh_message._state.http.edit_message = AsyncMock()

        stale_message.channel.fetch_message = AsyncMock(return_value=fresh_message)

        await audio_service._remove_send_controls_button_from_message(stale_message)

        stale_message.channel.fetch_message.assert_awaited_once_with(999)
        fresh_message._state.http.edit_message.assert_awaited_once_with(
            777,
            999,
            components=[
                {
                    "type": 1,
                    "id": 0,
                    "components": [fresh_progress.to_dict()],
                }
            ],
        )

    @pytest.mark.asyncio
    async def test_handle_new_bot_message_without_gear_keeps_previous_tracked_message(self, audio_service):
        """Ensure non-controls bot messages do not clear the currently tracked gear message."""
        previous = Mock(id=10)
        channel = Mock(id=50)
        audio_service._last_gear_message_by_channel[channel.id] = previous

        current = Mock(id=11, channel=channel, components=[])

        audio_service._remove_send_controls_button_from_message = AsyncMock()
        audio_service._message_has_send_controls_button = Mock(side_effect=lambda message: message is previous)

        await audio_service.handle_new_bot_message_for_controls_cleanup(current)

        audio_service._remove_send_controls_button_from_message.assert_not_awaited()
        assert audio_service._last_gear_message_by_channel[channel.id] is previous

    @pytest.mark.asyncio
    async def test_handle_new_bot_message_with_gear_replaces_previous_tracked_message(self, audio_service):
        """Ensure a new controls message replaces the previously tracked controls message."""
        channel = Mock(id=77)
        previous = Mock(id=21)
        audio_service._last_gear_message_by_channel[channel.id] = previous
        current = Mock(id=22, channel=channel, components=[Mock()])

        audio_service._remove_send_controls_button_from_message = AsyncMock()
        audio_service._message_has_send_controls_button = Mock(return_value=True)

        await audio_service.handle_new_bot_message_for_controls_cleanup(current)

        audio_service._remove_send_controls_button_from_message.assert_awaited_once_with(previous)
        assert audio_service._last_gear_message_by_channel[channel.id] is current

    @pytest.mark.asyncio
    async def test_handle_new_bot_message_controls_menu_does_not_remove_previous(self, audio_service):
        """Ensure controls menu messages do not clear the previously tracked gear button."""
        previous = Mock(id=30)
        channel = Mock(id=90)
        audio_service._last_gear_message_by_channel[channel.id] = previous
        current = Mock(id=31, channel=channel, components=[Mock()])

        audio_service._remove_send_controls_button_from_message = AsyncMock()
        audio_service._is_controls_menu_message = Mock(return_value=True)
        audio_service._message_has_send_controls_button = Mock(return_value=False)

        await audio_service.handle_new_bot_message_for_controls_cleanup(current)

        audio_service._remove_send_controls_button_from_message.assert_not_awaited()
        audio_service._message_has_send_controls_button.assert_not_called()
        assert audio_service._last_gear_message_by_channel[channel.id] is previous

    def test_cancel_progress_update_task_cancels_active_task(self, audio_service):
        """Ensure active progress updater tasks are canceled before starting a new one."""
        task = Mock()
        task.done.return_value = False
        audio_service._progress_update_task = task

        audio_service._cancel_progress_update_task()

        task.cancel.assert_called_once()
        assert audio_service._progress_update_task is None

    @pytest.mark.asyncio
    async def test_update_progress_bar_exits_when_message_is_no_longer_current(self, audio_service):
        """Ensure stale progress tasks stop without editing old playback messages."""
        audio_service.stop_progress_update = False
        audio_service.current_sound_message = Mock(id=222)
        audio_service.current_view = Mock()

        sound_message = AsyncMock()
        sound_message.id = 111
        sound_message.embeds = []

        view = Mock()
        view.update_progress_label = Mock()

        await audio_service.update_progress_bar(sound_message, duration=3.0, view=view)

        sound_message.edit.assert_not_awaited()
        view.update_progress_label.assert_not_called()
