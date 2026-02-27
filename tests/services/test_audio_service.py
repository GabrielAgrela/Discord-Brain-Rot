"""
Tests for bot/services/audio.py - AudioService helper behavior.
"""

import asyncio
import os
import sys
from types import SimpleNamespace
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
        service.playback_done = asyncio.Event()
        service.playback_done.set()
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

    def test_is_stt_enabled_for_guild_defaults_true_without_settings_service(self, audio_service):
        """Ensure STT defaults to enabled when guild settings service is unavailable."""
        guild = Mock(id=123, name="Guild A")
        assert audio_service._is_stt_enabled_for_guild(guild) is True

    @pytest.mark.asyncio
    async def test_start_keyword_detection_skips_when_stt_disabled(self, audio_service):
        """Ensure keyword detection does not start when guild STT setting is disabled."""
        from bot.services.audio import AudioService

        audio_service.keyword_sinks = {}
        audio_service._behavior = SimpleNamespace(
            _guild_settings_service=SimpleNamespace(
                get=Mock(return_value=SimpleNamespace(stt_enabled=False))
            )
        )

        guild = Mock(id=999, name="Guild B")
        voice_client = Mock()
        guild.voice_client = voice_client

        result = await AudioService.start_keyword_detection(audio_service, guild)

        assert result is False
        voice_client.start_recording.assert_not_called()

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

    def test_build_ffmpeg_before_options(self, audio_service):
        """Ensure audio latency mode translates to the correct FFmpeg flags."""
        audio_service.audio_latency_mode = "high_quality"
        assert audio_service._build_ffmpeg_before_options() == "-nostdin"

        audio_service.audio_latency_mode = "balanced"
        assert audio_service._build_ffmpeg_before_options() == "-nostdin -fflags +genpts"

        audio_service.audio_latency_mode = "low_latency"
        assert audio_service._build_ffmpeg_before_options() == "-nostdin -fflags nobuffer -flags low_delay"

    def test_build_slap_ffmpeg_options(self, audio_service):
        """Ensure slap playback options include startup delay."""
        assert audio_service._build_slap_ffmpeg_options() == '-vn -af "adelay=120:all=1"'

    def test_build_slap_ffmpeg_before_options(self, audio_service):
        """Ensure slap playback uses conservative ffmpeg startup flags."""
        assert audio_service._build_slap_ffmpeg_before_options() == "-nostdin"

    def test_should_use_short_clip_safety(self, audio_service):
        """Ensure short low-latency MP3 clips opt into conservative playback startup."""
        audio_service.audio_latency_mode = "low_latency"
        audio_service.short_clip_duration_threshold_seconds = 2.0

        assert audio_service._should_use_short_clip_safety("clip.mp3", 1.0) is True
        assert audio_service._should_use_short_clip_safety("clip.mp3", 2.5) is False
        assert audio_service._should_use_short_clip_safety("clip.wav", 1.0) is False
        assert audio_service._should_use_short_clip_safety("clip.mp3", None) is False

        audio_service.audio_latency_mode = "balanced"
        assert audio_service._should_use_short_clip_safety("clip.mp3", 1.0) is False

    def test_is_low_latency_mp3_playback(self, audio_service):
        """Ensure MP3 startup safety detection is tied to low-latency mode."""
        audio_service.audio_latency_mode = "low_latency"
        assert audio_service._is_low_latency_mp3_playback("clip.mp3") is True
        assert audio_service._is_low_latency_mp3_playback("clip.wav") is False

        audio_service.audio_latency_mode = "balanced"
        assert audio_service._is_low_latency_mp3_playback("clip.mp3") is False

    def test_get_play_audio_start_preroll_ms_uses_general_low_latency_preroll(self, audio_service):
        """Ensure normal low-latency playback gets startup pre-roll protection."""
        audio_service.audio_latency_mode = "low_latency"
        audio_service.playback_start_preroll_ms = 180
        audio_service.short_clip_start_delay_ms = 120

        assert audio_service._get_play_audio_start_preroll_ms(use_short_clip_safety=False) == 180
        assert audio_service._get_play_audio_start_preroll_ms(use_short_clip_safety=True) == 180

    def test_get_play_audio_start_preroll_ms_uses_low_latency_mp3_floor(self, audio_service):
        """Ensure low-latency MP3 playback gets a stronger startup delay floor."""
        audio_service.audio_latency_mode = "low_latency"
        audio_service.playback_start_preroll_ms = 180
        audio_service.low_latency_mp3_start_preroll_ms = 650
        audio_service.short_clip_start_delay_ms = 120

        assert (
            audio_service._get_play_audio_start_preroll_ms(
                use_short_clip_safety=False,
                is_low_latency_mp3=True,
            )
            == 650
        )

        audio_service.playback_start_preroll_ms = 900
        assert (
            audio_service._get_play_audio_start_preroll_ms(
                use_short_clip_safety=False,
                is_low_latency_mp3=True,
            )
            == 900
        )

    def test_get_play_audio_start_preroll_ms_falls_back_to_short_clip_delay(self, audio_service):
        """Ensure short-clip path keeps its minimum delay when general pre-roll is disabled."""
        audio_service.audio_latency_mode = "low_latency"
        audio_service.playback_start_preroll_ms = 0
        audio_service.short_clip_start_delay_ms = 120

        assert audio_service._get_play_audio_start_preroll_ms(use_short_clip_safety=False) == 0
        assert audio_service._get_play_audio_start_preroll_ms(use_short_clip_safety=True) == 120

    def test_get_play_audio_start_preroll_ms_disabled_outside_low_latency(self, audio_service):
        """Ensure playback pre-roll is only applied in low-latency mode."""
        audio_service.audio_latency_mode = "balanced"
        audio_service.playback_start_preroll_ms = 180
        audio_service.short_clip_start_delay_ms = 120

        assert audio_service._get_play_audio_start_preroll_ms(use_short_clip_safety=False) == 0
        assert audio_service._get_play_audio_start_preroll_ms(use_short_clip_safety=True) == 0

    def test_db_to_volume_multiplier(self, audio_service):
        """Ensure dB conversion produces expected ffmpeg volume multipliers."""
        assert round(audio_service._db_to_volume_multiplier(-6.0), 3) == 0.501
        assert round(audio_service._db_to_volume_multiplier(0.0), 3) == 1.000

    def test_is_earrape_like_filename(self, audio_service):
        """Ensure filename keyword matching works for ear-protection escalation."""
        audio_service.earrape_keywords = ("earrape", "bass boost")

        assert audio_service._is_earrape_like_filename("microondas-earrape.mp3") is True
        assert audio_service._is_earrape_like_filename("mega bass boost remix.mp3") is True
        assert audio_service._is_earrape_like_filename("normal-sound.mp3") is False

    def test_build_playback_ear_protection_filters_default_profile(self, audio_service):
        """Ensure default playback ear-protection filters are generated."""
        audio_service.playback_ear_protection_enabled = True
        audio_service.playback_ear_protection_gain_db = -3.0
        audio_service.playback_ear_protection_threshold_db = -16.0
        audio_service.playback_ear_protection_ratio = 6.0
        audio_service.playback_ear_protection_lowpass_hz = 12000
        audio_service.earrape_keywords = ("earrape",)
        audio_service.earrape_extra_attenuation_db = -6.0
        audio_service.earrape_lowpass_hz = 9000
        audio_service.earrape_compression_threshold_db = -20.0
        audio_service.earrape_compression_ratio = 12.0

        filters = audio_service._build_playback_ear_protection_filters("normal.mp3")

        assert filters[0] == "acompressor=threshold=-16.0dB:ratio=6.00:attack=5:release=80:makeup=1"
        assert filters[1] == "lowpass=f=12000"
        assert filters[2] == "volume=0.7079"

    def test_build_playback_ear_protection_filters_earrape_profile(self, audio_service):
        """Ensure earrape-like filenames get stronger protective filtering."""
        audio_service.playback_ear_protection_enabled = True
        audio_service.playback_ear_protection_gain_db = -3.0
        audio_service.playback_ear_protection_threshold_db = -16.0
        audio_service.playback_ear_protection_ratio = 6.0
        audio_service.playback_ear_protection_lowpass_hz = 12000
        audio_service.earrape_keywords = ("earrape",)
        audio_service.earrape_extra_attenuation_db = -6.0
        audio_service.earrape_lowpass_hz = 9000
        audio_service.earrape_compression_threshold_db = -20.0
        audio_service.earrape_compression_ratio = 12.0

        filters = audio_service._build_playback_ear_protection_filters("microondas earrape 3.mp3")

        assert filters[0] == "acompressor=threshold=-20.0dB:ratio=12.00:attack=5:release=80:makeup=1"
        assert filters[1] == "lowpass=f=9000"
        assert filters[2] == "volume=0.3548"

    @pytest.mark.asyncio
    async def test_play_slap_waits_for_lingering_player_thread(self, audio_service):
        """Ensure slap playback waits for lingering AudioPlayer thread before play()."""
        from bot.services.audio import AudioService

        audio_service.ffmpeg_path = "/usr/bin/ffmpeg"
        audio_service.audio_latency_mode = "low_latency"
        audio_service.volume = 1.0
        audio_service._cancel_progress_update_task = Mock()
        audio_service._log_perf = Mock()

        voice_client = Mock()
        voice_client.is_connected.return_value = True
        voice_client.is_playing.return_value = False
        voice_client.is_paused.return_value = False
        voice_client.play = Mock()
        player = Mock()
        player.is_alive.return_value = True
        voice_client._player = player

        audio_service.ensure_voice_connected = AsyncMock(return_value=voice_client)
        audio_service._wait_for_audio_player_thread = AsyncMock(return_value=True)

        channel = Mock()
        channel.guild = Mock(id=123)

        with patch("bot.services.audio.os.path.exists", return_value=True), \
             patch("bot.services.audio.discord.FFmpegPCMAudio", return_value=Mock()), \
             patch("bot.services.audio.discord.PCMVolumeTransformer", return_value=Mock()), \
             patch("bot.services.audio.asyncio.sleep", new=AsyncMock()):
            result = await AudioService.play_slap(audio_service, channel, "slap.mp3", "tester")

        assert result is True
        audio_service._wait_for_audio_player_thread.assert_awaited_once_with(player, timeout=2.0)
        voice_client.play.assert_called_once()

    @pytest.mark.asyncio
    async def test_play_slap_treats_paused_voice_client_as_active_playback(self, audio_service):
        """Ensure paused playback is stopped/waited before slap starts."""
        from bot.services.audio import AudioService

        audio_service.ffmpeg_path = "/usr/bin/ffmpeg"
        audio_service.audio_latency_mode = "low_latency"
        audio_service.volume = 1.0
        audio_service._cancel_progress_update_task = Mock()
        audio_service._stop_voice_client_and_wait = AsyncMock()
        audio_service._wait_for_audio_player_thread = AsyncMock(return_value=False)
        audio_service._log_perf = Mock()

        voice_client = Mock()
        voice_client.is_connected.return_value = True
        voice_client.is_playing.return_value = False
        voice_client.is_paused.return_value = True
        voice_client.play = Mock()
        voice_client._player = Mock()

        audio_service.ensure_voice_connected = AsyncMock(return_value=voice_client)

        channel = Mock()
        channel.guild = Mock(id=456)

        with patch("bot.services.audio.os.path.exists", return_value=True), \
             patch("bot.services.audio.discord.FFmpegPCMAudio", return_value=Mock()), \
             patch("bot.services.audio.discord.PCMVolumeTransformer", return_value=Mock()), \
             patch("bot.services.audio.asyncio.sleep", new=AsyncMock()):
            result = await AudioService.play_slap(audio_service, channel, "slap.mp3", "tester")

        assert result is True
        audio_service._stop_voice_client_and_wait.assert_awaited_once_with(voice_client)
        audio_service._wait_for_audio_player_thread.assert_not_awaited()
        voice_client.play.assert_called_once()
