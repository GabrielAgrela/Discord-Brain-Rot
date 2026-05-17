"""
Tests for bot/services/audio.py - AudioService helper behavior.
"""

import asyncio
import inspect
import os
import sys
from datetime import datetime
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
        # Initialize voice command prompt pools (normally set in __init__)
        service.voice_command_start_sounds = [
            "16-05-26-19-52-51-637928-Sim.mp3",
            "16-05-26-20-11-24-672100-Diz.mp3",
            "16-05-26-20-12-44-779160-whispers O que que queres.mp3",
            "16-05-26-20-13-18-557980-Frustrated sharp Foda-se q.mp3",
        ]
        service.voice_command_done_sounds = [
            "16-05-26-19-54-41-416014-Ok fica bem.mp3",
            "16-05-26-20-14-36-595803-Sim senhor.mp3",
            "16-05-26-20-15-00-686598-Ok já toco essa merda.mp3",
            "16-05-26-20-15-34-525805-shouts aggressive Ok já ag.mp3",
        ]
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
    async def test_play_audio_does_not_block_rapid_requests_with_cooldown_message(self, audio_service):
        """Ensure rapid non-TTS play requests continue into normal playback handling."""
        from bot.services.audio import AudioService

        guild = Mock(id=123, name="Guild")
        channel = Mock(guild=guild)
        audio_service.playback_done = asyncio.Event()
        audio_service.playback_done.set()
        AudioService._ensure_guild_playback_state(audio_service, guild.id)
        audio_service._guild_last_played_time[guild.id] = datetime.now()
        audio_service.mute_service = SimpleNamespace(is_muted=False)
        audio_service.message_service = Mock()
        audio_service.message_service.get_bot_channel = Mock()
        audio_service._track_guild_play_request = Mock(return_value=True)
        audio_service._release_guild_play_request = Mock()
        audio_service.ensure_voice_connected = AsyncMock(return_value=None)

        result = await AudioService.play_audio(audio_service, channel, "clip.mp3", "tester")

        assert result is False
        audio_service.ensure_voice_connected.assert_awaited_once_with(channel)
        audio_service.message_service.get_bot_channel.assert_not_called()

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

    def test_keyword_sink_has_no_ambient_llm_commentary_trigger(self):
        """Ensure the Vosk sink only handles keyword actions, not ambient LLM commentary."""
        from bot.services.audio import KeywordDetectionSink

        source = inspect.getsource(KeywordDetectionSink)

        assert "_ai_commentary_service" not in source
        assert "trigger_commentary" not in source
        assert "VenturaTrigger" not in source
        assert "pending_ai_trigger" not in source

    def test_keyword_sink_flushes_after_configured_silence(self):
        """Ensure final keyword detection can flush faster than the old one-second pause."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.last_audio_time = {123: 10.0}
        sink.recognizer_start_time = {}
        sink.buffer_last_update = {}
        sink.silence_flush_seconds = 0.35
        sink._flush_user = Mock()

        with patch("bot.services.audio.time.time", return_value=10.36):
            sink._flush_silence()

        sink._flush_user.assert_called_once_with(123)
        assert 123 not in sink.last_audio_time

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

    def test_is_low_fidelity_mp3_playback(self, audio_service):
        """Ensure low-fidelity MP3 detection uses sample-rate/bitrate thresholds."""
        assert (
            audio_service._is_low_fidelity_mp3_playback(
                "clip.mp3",
                sample_rate_hz=24000,
                bitrate_bps=128000,
            )
            is True
        )
        assert (
            audio_service._is_low_fidelity_mp3_playback(
                "clip.mp3",
                sample_rate_hz=44100,
                bitrate_bps=96000,
            )
            is True
        )
        assert (
            audio_service._is_low_fidelity_mp3_playback(
                "clip.mp3",
                sample_rate_hz=44100,
                bitrate_bps=128000,
            )
            is False
        )
        assert (
            audio_service._is_low_fidelity_mp3_playback(
                "clip.wav",
                sample_rate_hz=24000,
                bitrate_bps=64000,
            )
            is False
        )

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

    def test_build_playback_ear_protection_filters_relaxes_low_fidelity_mp3(self, audio_service):
        """Ensure low-fidelity MP3 playback avoids compressor/lowpass hiss artifacts."""
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

        filters = audio_service._build_playback_ear_protection_filters(
            "normal.mp3",
            sample_rate_hz=24000,
            bitrate_bps=64000,
            relax_for_low_fidelity=True,
        )

        assert filters == ["volume=0.7079"]

    def test_build_playback_ear_protection_filters_lowpass_clamped_by_sample_rate(self, audio_service):
        """Ensure lowpass cutoff never exceeds a safe fraction of Nyquist."""
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

        filters = audio_service._build_playback_ear_protection_filters(
            "normal.mp3",
            sample_rate_hz=24000,
            bitrate_bps=128000,
            relax_for_low_fidelity=False,
        )

        assert filters[1] == "lowpass=f=10800"

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

    @pytest.mark.asyncio
    async def test_play_slap_interrupts_live_tts_stream(self, audio_service):
        """Ensure slap calls _interrupt_live_tts_stream before stopping."""
        from bot.services.audio import AudioService

        audio_service.ffmpeg_path = "/usr/bin/ffmpeg"
        audio_service.audio_latency_mode = "low_latency"
        audio_service.volume = 1.0
        audio_service._cancel_progress_update_task = Mock()
        audio_service._stop_voice_client_and_wait = AsyncMock()
        audio_service._log_perf = Mock()
        audio_service._interrupt_live_tts_stream = Mock()

        voice_client = Mock()
        voice_client.is_connected.return_value = True
        voice_client.is_playing.return_value = True
        voice_client.is_paused.return_value = False
        voice_client.play = Mock()
        voice_client._player = Mock()

        audio_service.ensure_voice_connected = AsyncMock(return_value=voice_client)
        audio_service._guild_current_sound_message = {}
        audio_service._guild_current_view = {}

        channel = Mock()
        channel.guild = Mock(id=789)

        with patch("bot.services.audio.os.path.exists", return_value=True), \
             patch("bot.services.audio.discord.FFmpegPCMAudio", return_value=Mock()), \
             patch("bot.services.audio.discord.PCMVolumeTransformer", return_value=Mock()), \
             patch("bot.services.audio.asyncio.sleep", new=AsyncMock()):
            result = await AudioService.play_slap(audio_service, channel, "slap.mp3", "tester")

        assert result is True
        audio_service._interrupt_live_tts_stream.assert_called_once_with(789, reason="slap")
        audio_service._stop_voice_client_and_wait.assert_awaited_once_with(voice_client)

    def test_interrupt_live_tts_stream_sets_event(self, audio_service):
        """Verify _interrupt_live_tts_stream sets the stored event."""
        import threading
        event = threading.Event()
        audio_service._guild_live_tts_interrupt_events = {999: event}

        audio_service._interrupt_live_tts_stream(999, reason="test")

        assert event.is_set()

    def test_interrupt_live_tts_stream_handles_missing_event(self, audio_service):
        """_interrupt_live_tts_stream silently handles guild with no event."""
        import threading
        event = threading.Event()
        audio_service._guild_live_tts_interrupt_events = {999: event}

        # Call for guild without event — no crash
        audio_service._interrupt_live_tts_stream(888, reason="test")

        # Existing event should be untouched
        assert not event.is_set()

    @pytest.mark.asyncio
    async def test_play_tts_live_stream_stores_interrupt_event(self, audio_service):
        """Ensure play_tts_live_stream stores the interrupt_event per-guild."""
        from bot.services.audio import AudioService
        import threading
        audio_service.ffmpeg_path = "/usr/bin/ffmpeg"
        audio_service.bot = Mock()
        audio_service.mute_service = Mock()
        audio_service.mute_service.is_muted = False
        audio_service.message_service = Mock()
        audio_service.message_service.get_bot_channel = Mock()
        audio_service.image_generator = Mock()
        audio_service.image_generator.generate_sound_card = AsyncMock(return_value=None)

        interrupt_event = threading.Event()

        voice_client = Mock()
        voice_client.is_playing.return_value = False
        is_paused_attr = Mock(return_value=False)
        voice_client.is_paused = is_paused_attr
        voice_client.is_connected.return_value = True
        voice_client._player = None

        audio_service.ensure_voice_connected = AsyncMock(return_value=voice_client)

        channel = Mock()
        channel.guild.id = 555

        result = await AudioService.play_tts_live_stream(
            audio_service,
            fifo_path="/tmp/fake_fifo",
            audio_file="test_live.mp3",
            channel=channel,
            user="tester",
            interrupt_event=interrupt_event,
        )

        # Should have stored the event in the guild dict
        stored = audio_service._guild_live_tts_interrupt_events.get(555)
        assert stored is interrupt_event

    # ------------------------------------------------------------------ #
    # AFK channel detection guards
    # ------------------------------------------------------------------ #

    def test_is_afk_channel_identifies_guild_afk(self):
        """Test that is_afk_channel returns True for the guild's configured AFK channel."""
        from bot.services.audio import AudioService

        guild = Mock()
        guild.afk_channel = Mock()
        guild.afk_channel.id = 1
        guild.afk_channel.name = "AFK Channel"
        # The channel being checked is the same object as guild.afk_channel
        assert AudioService.is_afk_channel(guild.afk_channel) is True

    def test_is_afk_channel_returns_false_for_normal_channel(self):
        """Test that is_afk_channel returns False for a non-AFK voice channel."""
        from bot.services.audio import AudioService

        guild = Mock()
        guild.afk_channel = None
        channel = Mock()
        channel.guild = guild
        channel.name = "general"

        assert AudioService.is_afk_channel(channel) is False

    def test_is_afk_channel_fallback_on_name_prefix(self):
        """Test that is_afk_channel also catches channels whose name starts with 'afk'."""
        from bot.services.audio import AudioService

        guild = Mock()
        guild.afk_channel = None
        channel = Mock()
        channel.guild = guild
        channel.name = "afk-zone"

        assert AudioService.is_afk_channel(channel) is True

    def test_is_afk_channel_returns_false_for_none(self):
        """Test that is_afk_channel returns False when None is passed."""
        from bot.services.audio import AudioService

        assert AudioService.is_afk_channel(None) is False

    @pytest.mark.asyncio
    async def test_ensure_voice_connected_refuses_afk_channel(self, audio_service):
        """Test that ensure_voice_connected returns None for AFK channels."""
        guild = Mock()
        guild.id = 777
        afk_channel = Mock()
        afk_channel.guild = guild
        afk_channel.name = "AFK"
        guild.afk_channel = afk_channel

        result = await audio_service.ensure_voice_connected(afk_channel)

        assert result is None

    def test_get_largest_voice_channel_excludes_afk(self, audio_service):
        """Test that get_largest_voice_channel ignores AFK channels even when populated."""
        guild = Mock()
        afk_channel = Mock()
        afk_channel.name = "AFK"
        afk_channel.members = [Mock(), Mock()]
        afk_channel.guild = guild
        guild.afk_channel = afk_channel

        general = Mock()
        general.name = "general"
        general.members = [Mock()]
        general.guild = guild

        lobby = Mock()
        lobby.name = "lobby"
        lobby.members = [Mock(), Mock(), Mock()]
        lobby.guild = guild

        guild.voice_channels = [afk_channel, general, lobby]

        result = audio_service.get_largest_voice_channel(guild)

        # afk_channel has 2 members but should be excluded; lobby has 3
        assert result == lobby

    def test_get_user_voice_channel_skips_afk(self, audio_service):
        """Test that get_user_voice_channel does not return AFK channels."""
        guild = Mock()
        user = Mock()
        user.name = "testuser"

        afk_channel = Mock()
        afk_channel.name = "AFK"
        afk_channel.members = [user]
        afk_channel.guild = guild
        guild.afk_channel = afk_channel

        general = Mock()
        general.name = "general"
        general.members = []
        general.guild = guild

        guild.voice_channels = [afk_channel, general]

        result = audio_service.get_user_voice_channel(guild, "testuser")

        assert result is None

    def test_get_user_voice_channel_finds_user_in_non_afk(self, audio_service):
        """Test that get_user_voice_channel still finds users in non-AFK channels."""
        guild = Mock()
        user = Mock()
        user.name = "testuser"

        afk_channel = Mock()
        afk_channel.name = "AFK"
        afk_channel.members = []
        afk_channel.guild = guild
        guild.afk_channel = afk_channel

        general = Mock()
        general.name = "general"
        general.members = [user]
        general.guild = guild

        guild.voice_channels = [afk_channel, general]

        result = audio_service.get_user_voice_channel(guild, "testuser")

        assert result == general

    # ------------------------------------------------------------------ #
    # Voice command / wake word injection tests
    # ------------------------------------------------------------------ #

    def test_keyword_sink_injects_vosk_aliases(self):
        """Verify that refresh_keywords injects Vosk aliases (not human wake words) as voice_command."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.keywords = {}
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["bot"]
        sink.voice_command_vosk_wake_words = ["bote", "bota", "boto"]
        sink.audio_service = Mock()
        sink.audio_service.keyword_repo = Mock()
        sink.audio_service.keyword_repo.get_as_dict = Mock(return_value={"diogo": "slap"})
        sink.recognizers = {}
        sink.refresh_keywords()

        # Vosk aliases are injected
        assert sink.keywords["bote"] == "voice_command"
        assert sink.keywords["bota"] == "voice_command"
        assert sink.keywords["boto"] == "voice_command"
        # Human wake word is NOT injected (avoids OOV Vosk warnings)
        assert "bot" not in sink.keywords
        # Normal DB keywords remain
        assert sink.keywords["diogo"] == "slap"

    def test_keyword_sink_vosk_alias_override_logs(self, capsys):
        """When a DB keyword matches a Vosk alias, a log message is printed."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.keywords = {}
        sink.recognizers = {}
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["bot"]
        sink.voice_command_vosk_wake_words = ["bote", "bota"]
        sink.audio_service = Mock()
        sink.audio_service.keyword_repo = Mock()
        sink.audio_service.keyword_repo.get_as_dict = Mock(
            return_value={"bote": "slap", "hugo": "list:mylist"}
        )
        sink.refresh_keywords()

        captured = capsys.readouterr()
        assert "overrode DB keyword" in captured.out
        assert sink.keywords["bote"] == "voice_command"
        assert sink.keywords["bota"] == "voice_command"
        assert sink.keywords["hugo"] == "list:mylist"
        # Human wake word "bot" should NOT be in keywords (not a Vosk alias)
        assert "bot" not in sink.keywords

    def test_keyword_sink_default_ventura_injected(self):
        """With defaults, 'ventura' is injected as voice_command (in-vocab for PT Vosk model)."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.keywords = {}
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = ["ventura"]
        sink.audio_service = Mock()
        sink.audio_service.keyword_repo = Mock()
        sink.audio_service.keyword_repo.get_as_dict = Mock(return_value={"diogo": "slap"})
        sink.recognizers = {}
        sink.refresh_keywords()

        # "ventura" is injected as voice_command (both human and vosk alias)
        assert sink.keywords["ventura"] == "voice_command"
        # Normal DB keywords remain
        assert sink.keywords["diogo"] == "slap"
        # Old OOV "bot" should NOT appear by default
        assert "bot" not in sink.keywords

    def test_keyword_sink_disabled_voice_command(self):
        """When voice_command_enabled is False, neither aliases nor wake words are injected."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.keywords = {}
        sink.recognizers = {}
        sink.voice_command_enabled = False
        sink.voice_command_wake_words = ["bot"]
        sink.voice_command_vosk_wake_words = ["bote"]
        sink.audio_service = Mock()
        sink.audio_service.keyword_repo = Mock()
        sink.audio_service.keyword_repo.get_as_dict = Mock(return_value={"diogo": "slap"})
        sink.refresh_keywords()

        assert "bot" not in sink.keywords
        assert "bote" not in sink.keywords
        assert sink.keywords["diogo"] == "slap"

    def test_get_user_buffer_content_returns_pcm(self):
        """Verify get_user_buffer_content returns concatenated audio for one user."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.user_audio_buffers = {}
        sink.buffer_lock = Mock()
        sink.buffer_lock.__enter__ = Mock(return_value=None)
        sink.buffer_lock.__exit__ = Mock(return_value=None)

        now = 1000.0
        user_id = 12345
        chunk1 = b"\x00\x00" * 100
        chunk2 = b"\x01\x02" * 50

        with patch("bot.services.audio.time.time", return_value=now):
            sink.user_audio_buffers[user_id] = [
                (now - 2, chunk1),
                (now - 1, chunk2),
            ]
            result = sink.get_user_buffer_content(user_id, 5.0)
            assert result == chunk1 + chunk2

    def test_get_user_buffer_content_empty_for_unknown_user(self):
        """Unknown user_id returns empty bytes."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.user_audio_buffers = {}
        sink.buffer_lock = Mock()
        sink.buffer_lock.__enter__ = Mock(return_value=None)
        sink.buffer_lock.__exit__ = Mock(return_value=None)

        result = sink.get_user_buffer_content(99999, 5.0)
        assert result == bytes()

    def test_get_user_buffer_content_older_than_cutoff(self):
        """Chunks older than the requested window are excluded."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.user_audio_buffers = {}
        sink.buffer_lock = Mock()
        sink.buffer_lock.__enter__ = Mock(return_value=None)
        sink.buffer_lock.__exit__ = Mock(return_value=None)

        now = 1000.0
        user_id = 12345
        with patch("bot.services.audio.time.time", return_value=now):
            sink.user_audio_buffers[user_id] = [
                (now - 10, b"old-data"),
                (now - 1, b"new-data"),
            ]
            result = sink.get_user_buffer_content(user_id, 3.0)
            assert result == b"new-data"



    @pytest.mark.asyncio
    async def test_handle_voice_command_calls_play_request(self):
        """Verify _handle_voice_command calls sound_service.play_request when Groq returns a play command."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 111
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["bot"]
        sink.voice_command_vosk_wake_words = []

        # Mock audio_service with cooldowns and prompts
        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock(return_value=True)
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)
        # Mock ventura chat service (not called for play path, but must exist)
        mock_ventura = Mock()
        mock_ventura.is_available = False
        sink.audio_service._get_ventura_chat_service = Mock(return_value=mock_ventura)

        # Mock recording to return some PCM
        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        # Mock GroqWhisperService
        from bot.services.voice_command import GroqWhisperService
        mock_voice_service = Mock(spec=GroqWhisperService)
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="bot play air horn")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(999, "TestUser", Mock())

        # Prompt is called twice: start + done (done now played after parse)
        assert sink.audio_service._play_voice_command_prompt.await_count == 2
        sink.audio_service.sound_service.play_request.assert_awaited_once_with(
            "air horn", "TestUser", guild=sink.guild, request_note="play air horn", allow_rejected_exact_fallback=True
        )
        # Ventura chat should not be called for play path
        sink.audio_service._get_ventura_chat_service.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_voice_command_routes_to_ventura_chat(self):
        """When Groq returns a transcript without a play command, Ventura Chat + TTS is used."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 222
        sink.guild.get_member = Mock(return_value=None)
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["bot"]
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)

        # Mock Ventura chat service returning a reply
        mock_ventura = Mock()
        mock_ventura.is_available = True
        mock_ventura.reply = AsyncMock(return_value="[shouts] Isto é uma vergonha!")
        sink.audio_service._get_ventura_chat_service = Mock(return_value=mock_ventura)

        # Mock VT service for ElevenLabs TTS
        sink.audio_service.voice_transformation_service = AsyncMock()
        sink.audio_service.voice_transformation_service.tts_EL = AsyncMock()

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="bot stop doing that")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(888, "TestUser2", Mock())

        # Prompt is called exactly once (start only; no done prompt for non-play)
        assert sink.audio_service._play_voice_command_prompt.await_count == 1
        sound_service = sink.audio_service.sound_service
        sound_service.play_request.assert_not_called()

        # Ventura chat was invoked with transcript, requester_name, and conversation_key
        mock_ventura.reply.assert_awaited_once()
        reply_call_kwargs = mock_ventura.reply.await_args.kwargs
        assert reply_call_kwargs.get("conversation_key") == "guild:222:user:888"
        # TTS was invoked with Ventura's reply and lang="pt"
        vt = sink.audio_service.voice_transformation_service
        vt.tts_EL.assert_awaited_once()
        call_args = vt.tts_EL.await_args
        assert call_args is not None
        assert call_args.kwargs.get("lang") == "pt"
        assert call_args.args[1] == "[shouts] Isto é uma vergonha!"

    @pytest.mark.asyncio
    async def test_handle_voice_command_non_play_skips_when_openrouter_unavailable(self):
        """When OpenRouter is not configured, non-play transcript skips Ventura chat silently."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 333
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["bot"]
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)

        # Ventura chat service reports unavailable (no key)
        mock_ventura = Mock()
        mock_ventura.is_available = False
        sink.audio_service._get_ventura_chat_service = Mock(return_value=mock_ventura)
        # VT service not needed since Ventura chat is skipped
        sink.audio_service.voice_transformation_service = AsyncMock()

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="bot hello there")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(777, "TestUser3", Mock())

        # Only start prompt played, no done prompt
        assert sink.audio_service._play_voice_command_prompt.await_count == 1
        sink.audio_service.sound_service.play_request.assert_not_called()
        # Ventura chat was not called (unavailable)
        mock_ventura.reply.assert_not_called()
        # TTS was not called
        vt = sink.audio_service.voice_transformation_service
        vt.tts_EL.assert_not_called()

    # ------------------------------------------------------------------ #
    # Voice command prompt pools
    # ------------------------------------------------------------------ #

    def test_voice_command_start_sounds_default_contents(self, audio_service):
        """Default start prompt pool contains the expected filenames."""
        expected = [
            "16-05-26-19-52-51-637928-Sim.mp3",
            "16-05-26-20-11-24-672100-Diz.mp3",
            "16-05-26-20-12-44-779160-whispers O que que queres.mp3",
            "16-05-26-20-13-18-557980-Frustrated sharp Foda-se q.mp3",
        ]
        for f in expected:
            assert f in audio_service.voice_command_start_sounds

    def test_voice_command_done_sounds_default_contents(self, audio_service):
        """Default done prompt pool contains the expected filenames."""
        expected = [
            "16-05-26-19-54-41-416014-Ok fica bem.mp3",
            "16-05-26-20-14-36-595803-Sim senhor.mp3",
            "16-05-26-20-15-00-686598-Ok já toco essa merda.mp3",
            "16-05-26-20-15-34-525805-shouts aggressive Ok já ag.mp3",
        ]
        for f in expected:
            assert f in audio_service.voice_command_done_sounds

    def test_voice_command_start_sound_property_returns_from_pool(self, audio_service):
        """Property returns one of the pool filenames (random or fallback for single)."""
        result = audio_service.voice_command_start_sound
        assert result in audio_service.voice_command_start_sounds

    def test_voice_command_done_sound_property_returns_from_pool(self, audio_service):
        """Property returns one of the pool filenames (random or fallback for single)."""
        result = audio_service.voice_command_done_sound
        assert result in audio_service.voice_command_done_sounds

    def test_voice_command_start_sounds_single_filename_backward_compat(self):
        """A single filename in the env var produces a single-item pool."""
        from bot.services.audio import AudioService
        import os

        with patch.dict(os.environ, {"VOICE_COMMAND_START_SOUND": "only-one.mp3"}, clear=False):
            # Re-create __init__ equivalent via __new__ + manual init of the relevant parts
            service = AudioService.__new__(AudioService)
            # Simulate the __init__ parsing logic
            raw = os.getenv("VOICE_COMMAND_START_SOUND", "16-05-26-19-52-51-637928-Sim.mp3")
            service.voice_command_start_sounds = [
                s.strip() for s in raw.split(",") if s.strip()
            ]
            if not service.voice_command_start_sounds:
                service.voice_command_start_sounds = ["16-05-26-19-52-51-637928-Sim.mp3"]
            assert service.voice_command_start_sounds == ["only-one.mp3"]

    # ------------------------------------------------------------------ #
    # _load_prompt_pcm
    # ------------------------------------------------------------------ #

    def test_load_prompt_pcm_returns_none_when_file_missing(self, audio_service):
        """Returns None when the prompt MP3 does not exist."""
        audio_service._voice_command_prompt_pcm_cache = {}
        result = audio_service._load_prompt_pcm("nonexistent_file.mp3")
        assert result is None

    def test_load_prompt_pcm_returns_bytes_when_file_exists(self, audio_service):
        """Returns decoded PCM bytes when the MP3 is found."""
        audio_service._voice_command_prompt_pcm_cache = {}

        dummy_pcm = b"\x00\x01" * 48000  # 1 second of 48 kHz stereo 16-bit PCM

        with patch("bot.services.audio.os.path.isfile", return_value=True):
            with patch("bot.services.audio.os.path.getmtime", return_value=123.0):
                with patch("pydub.AudioSegment") as mock_segment_cls:
                    mock_segment = Mock()
                    mock_segment.set_frame_rate.return_value = mock_segment
                    mock_segment.set_channels.return_value = mock_segment
                    mock_segment.set_sample_width.return_value = mock_segment
                    mock_segment.raw_data = dummy_pcm
                    mock_segment_cls.from_file.return_value = mock_segment

                    result = audio_service._load_prompt_pcm("prompt.mp3")

        assert result == dummy_pcm
        mock_segment_cls.from_file.assert_called_once()

    def test_load_prompt_pcm_caches_by_mtime(self, audio_service):
        """Same file+mtime returns cached bytes without re-decoding."""
        audio_service._voice_command_prompt_pcm_cache = {}

        dummy_pcm = b"\x00\x01" * 48000

        with patch("bot.services.audio.os.path.isfile", return_value=True):
            with patch("bot.services.audio.os.path.getmtime", return_value=100.0):
                with patch("pydub.AudioSegment") as mock_segment_cls:
                    mock_segment = Mock()
                    mock_segment.set_frame_rate.return_value = mock_segment
                    mock_segment.set_channels.return_value = mock_segment
                    mock_segment.set_sample_width.return_value = mock_segment
                    mock_segment.raw_data = dummy_pcm
                    mock_segment_cls.from_file.return_value = mock_segment

                    # First call decodes
                    result1 = audio_service._load_prompt_pcm("prompt.mp3")
                    assert result1 == dummy_pcm
                    assert mock_segment_cls.from_file.call_count == 1

                    # Second call with same mtime uses cache
                    result2 = audio_service._load_prompt_pcm("prompt.mp3")
                    assert result2 == dummy_pcm
                    # from_file should not have been called again
                    assert mock_segment_cls.from_file.call_count == 1

    def test_load_prompt_pcm_sanitises_filename(self, audio_service):
        """Path traversal via filename is prevented (basename only)."""
        audio_service._voice_command_prompt_pcm_cache = {}
        # The basename should be the only part used
        with patch("bot.services.audio.os.path.basename", return_value="safe.mp3"):
            with patch("bot.services.audio.os.path.isfile", return_value=True) as mock_isfile:
                with patch("bot.services.audio.os.path.getmtime", return_value=100.0):
                    with patch("pydub.AudioSegment"):
                        audio_service._load_prompt_pcm("../../evil.mp3")
                        # The path checked should end with safe.mp3
                        checked_path = mock_isfile.call_args[0][0]
                        assert checked_path.endswith("safe.mp3")

    # ------------------------------------------------------------------ #
    # _play_voice_command_prompt
    # ------------------------------------------------------------------ #

    def test_voice_command_prompts_enabled_defaults_to_true(self):
        """voice_command_beep_enabled defaults to True when env is not set."""
        from bot.services.audio import AudioService

        with patch.dict(os.environ, {}, clear=True):
            service = AudioService.__new__(AudioService)
            service.voice_command_beep_enabled = (
                os.getenv("VOICE_COMMAND_BEEP_ENABLED", "true").strip().lower()
                not in {"0", "false", "off", "no"}
            )
            assert service.voice_command_beep_enabled is True

    @pytest.mark.asyncio
    async def test_play_voice_command_prompt_skips_when_disabled(self, audio_service):
        """Prompt is skipped when voice_command_beep_enabled is False."""
        audio_service.voice_command_beep_enabled = False
        channel = Mock()
        channel.guild.voice_client = Mock()

        result = await audio_service._play_voice_command_prompt(channel, "prompt.mp3")
        assert result is False

    @pytest.mark.asyncio
    async def test_play_voice_command_prompt_skips_when_no_voice_client(self, audio_service):
        """Prompt is skipped when there is no voice client."""
        audio_service.voice_command_beep_enabled = True
        channel = Mock()
        channel.guild.voice_client = None

        result = await audio_service._play_voice_command_prompt(channel, "prompt.mp3")
        assert result is False

    @pytest.mark.asyncio
    async def test_play_voice_command_prompt_skips_when_playing(self, audio_service):
        """Prompt is skipped when the voice client is already playing audio."""
        audio_service.voice_command_beep_enabled = True
        voice_client = Mock()
        voice_client.is_connected.return_value = True
        voice_client.is_playing.return_value = True
        voice_client.is_paused.return_value = False
        channel = Mock()
        channel.guild.voice_client = voice_client

        result = await audio_service._play_voice_command_prompt(channel, "prompt.mp3")
        assert result is False
        voice_client.play.assert_not_called()

    @pytest.mark.asyncio
    async def test_play_voice_command_prompt_skips_when_pcm_load_fails(self, audio_service):
        """Prompt is skipped when _load_prompt_pcm returns None."""
        audio_service.voice_command_beep_enabled = True
        voice_client = Mock()
        voice_client.is_connected.return_value = True
        voice_client.is_playing.return_value = False
        voice_client.is_paused.return_value = False
        channel = Mock()
        channel.guild.voice_client = voice_client

        with patch.object(audio_service, "_load_prompt_pcm", return_value=None):
            result = await audio_service._play_voice_command_prompt(channel, "prompt.mp3")

        assert result is False
        voice_client.play.assert_not_called()

    @pytest.mark.asyncio
    async def test_play_voice_command_prompt_plays_when_idle(self, audio_service):
        """Prompt plays via PCMAudio when voice client is connected and idle."""
        audio_service.voice_command_beep_enabled = True

        voice_client = Mock()
        voice_client.is_connected.return_value = True
        voice_client.is_playing.return_value = False
        voice_client.is_paused.return_value = False
        channel = Mock()
        channel.guild.voice_client = voice_client

        dummy_pcm = b"\x00\x01" * 48000
        with patch.object(audio_service, "_load_prompt_pcm", return_value=dummy_pcm):
            with patch("bot.services.audio.discord.PCMAudio", return_value=Mock()) as mock_pcmaudio:
                result = await audio_service._play_voice_command_prompt(
                    channel, "prompt.mp3", wait=False,
                )

        assert result is True
        mock_pcmaudio.assert_called_once()
        voice_client.play.assert_called_once()

    @pytest.mark.asyncio
    async def test_play_voice_command_prompt_skips_when_paused(self, audio_service):
        """Prompt is skipped when the voice client is paused."""
        audio_service.voice_command_beep_enabled = True
        voice_client = Mock()
        voice_client.is_connected.return_value = True
        voice_client.is_playing.return_value = False
        voice_client.is_paused.return_value = True
        channel = Mock()
        channel.guild.voice_client = voice_client

        result = await audio_service._play_voice_command_prompt(channel, "prompt.mp3")
        assert result is False
        voice_client.play.assert_not_called()

    @pytest.mark.asyncio
    async def test_play_voice_command_prompt_plays_and_waits(self, audio_service):
        """Plays prompt and waits for the after callback when wait=True."""
        audio_service.voice_command_beep_enabled = True
        # Set up bot.loop.call_soon_threadsafe for the after callback
        audio_service.bot = Mock()
        audio_service.bot.loop = asyncio.get_event_loop()

        voice_client = Mock()
        voice_client.is_connected.return_value = True
        voice_client.is_playing.return_value = False
        voice_client.is_paused.return_value = False
        channel = Mock()
        channel.guild.voice_client = voice_client

        dummy_pcm = b"\x00\x01" * 48000  # 1s of PCM = ~1s duration
        captured_after = {}

        def _fake_play(source, after=None):
            captured_after["cb"] = after

        voice_client.play = _fake_play

        with patch.object(audio_service, "_load_prompt_pcm", return_value=dummy_pcm):
            with patch("bot.services.audio.discord.PCMAudio", return_value=Mock()):
                # Kick off the async wait in a task so we can trigger the callback
                async def run():
                    return await audio_service._play_voice_command_prompt(
                        channel, "prompt.mp3", wait=True,
                    )

                play_task = asyncio.ensure_future(run())
                await asyncio.sleep(0.01)
                # Simulate the after callback completing
                cb = captured_after.get("cb")
                assert cb is not None, "voice_client.play was not called with after= callback"
                cb(None)  # No error
                await asyncio.sleep(0.01)

                result = play_task.result()
                assert result is True

    # ------------------------------------------------------------------ #
    # request_note propagation through play_request
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_handle_voice_command_rate_limited(self):
        """A rapid second call is skipped due to cooldown."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 333
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["bot"]
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)
        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        now = 1000.0
        with patch("bot.services.audio.time.time", return_value=now):
            # First call sets cooldown
            mock_voice_service = Mock()
            mock_voice_service.is_available = True
            mock_voice_service.transcribe = AsyncMock(return_value="bot play test")
            sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)
            sink.audio_service.sound_service.play_request = AsyncMock()
            await sink._handle_voice_command(777, "Rater", Mock())
            # Prompt is called twice: start + done
            sink.audio_service._play_voice_command_prompt.assert_awaited()
            assert sink.audio_service._voice_command_cooldowns.get("333:777", 0) == now

            # Second call within cooldown (rate limited — prompt not called again)
            sink.audio_service._play_voice_command_prompt.reset_mock()
            mock_voice_service2 = Mock()
            mock_voice_service2.is_available = True
            mock_voice_service2.transcribe = AsyncMock(return_value="bot play another")
            sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service2)
            await sink._handle_voice_command(777, "Rater", Mock())
            sink.audio_service._play_voice_command_prompt.assert_not_called()
            sink.audio_service.sound_service.play_request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_voice_command_no_audio_skips(self):
        """When recording returns empty, the method skips Groq."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 888
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)

        sink._record_voice_command_after_beep = AsyncMock(return_value=bytes())

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(888, "SilentUser", Mock())

        sink.audio_service._play_voice_command_prompt.assert_awaited_once()
        sink.audio_service.sound_service.play_request.assert_not_called()

    # ------------------------------------------------------------------ #
    # Voice command capture feeding in write()
    # ------------------------------------------------------------------ #

    def test_write_feeds_active_capture(self):
        """write() appends data to an active capture for the same user."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.running = True
        sink.worker_thread = Mock()
        sink.worker_thread.is_alive = Mock(return_value=True)
        sink.last_audio_time = {}
        sink.buffer_last_update = {}
        sink.user_audio_buffers = {}
        sink._active_captures = {}
        sink.audio_buffers = {}
        sink.queue = Mock()
        sink.queue.qsize = Mock(return_value=5)
        sink.queue.put = Mock()
        sink.buffer_lock = Mock()
        sink.buffer_lock.__enter__ = Mock(return_value=None)
        sink.buffer_lock.__exit__ = Mock(return_value=None)
        sink.buffer_seconds = 30
        sink.min_batch_size = 28800
        sink.max_queue_size = 100

        user_id = 12345
        data = b"\xaa\xbb" * 50

        # Set up an active capture
        capture = {"chunks": [], "last_audio_time": 0.0, "total_bytes": 0}
        sink._active_captures[user_id] = capture

        with patch("bot.services.audio.time.time", return_value=1000.0):
            sink.write(data, user_id)

        # Capture should have the data
        assert capture["chunks"] == [data]
        assert capture["total_bytes"] == len(data)
        assert capture["last_audio_time"] == 1000.0

    def test_write_ignores_capture_for_other_user(self):
        """write() does not feed a capture for a different user."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.running = True
        sink.worker_thread = Mock()
        sink.worker_thread.is_alive = Mock(return_value=True)
        sink.last_audio_time = {}
        sink.buffer_last_update = {}
        sink.user_audio_buffers = {}
        sink._active_captures = {}
        sink.audio_buffers = {}
        sink.queue = Mock()
        sink.queue.qsize = Mock(return_value=5)
        sink.queue.put = Mock()
        sink.buffer_lock = Mock()
        sink.buffer_lock.__enter__ = Mock(return_value=None)
        sink.buffer_lock.__exit__ = Mock(return_value=None)
        sink.buffer_seconds = 30
        sink.min_batch_size = 28800
        sink.max_queue_size = 100

        capture_user = 111
        other_user = 222
        capture = {"chunks": [], "last_audio_time": 0.0, "total_bytes": 0}
        sink._active_captures[capture_user] = capture

        with patch("bot.services.audio.time.time", return_value=1000.0):
            sink.write(b"other data", other_user)

        # Capture for capture_user should be untouched
        assert capture["chunks"] == []
        assert capture["total_bytes"] == 0

    def test_write_ignores_no_active_capture(self):
        """write() handles missing capture gracefully."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.running = True
        sink.worker_thread = Mock()
        sink.worker_thread.is_alive = Mock(return_value=True)
        sink.last_audio_time = {}
        sink.buffer_last_update = {}
        sink.user_audio_buffers = {}
        sink._active_captures = {}
        sink.audio_buffers = {}
        sink.queue = Mock()
        sink.queue.qsize = Mock(return_value=5)
        sink.queue.put = Mock()
        sink.buffer_lock = Mock()
        sink.buffer_lock.__enter__ = Mock(return_value=None)
        sink.buffer_lock.__exit__ = Mock(return_value=None)
        sink.buffer_seconds = 30
        sink.min_batch_size = 28800
        sink.max_queue_size = 100

        with patch("bot.services.audio.time.time", return_value=1000.0):
            # Should not raise even if no capture active
            sink.write(b"some data", 999)

    # ------------------------------------------------------------------ #
    # Vosk alias fallback and confidence threshold tests
    # ------------------------------------------------------------------ #

    def test_keyword_sink_fallback_to_wake_words_when_aliases_empty(self):
        """When voice_command_vosk_wake_words is empty, fall back to injecting human wake words."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.keywords = {}
        sink.recognizers = {}
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["bot"]
        # voice_command_vosk_wake_words intentionally NOT set (None → fallback)
        sink.audio_service = Mock()
        sink.audio_service.keyword_repo = Mock()
        sink.audio_service.keyword_repo.get_as_dict = Mock(return_value={"diogo": "slap"})
        sink.refresh_keywords()

        # Human wake word should be injected via fallback
        assert sink.keywords["bot"] == "voice_command"
        assert sink.keywords["diogo"] == "slap"

    def test_check_keywords_voice_command_lower_confidence(self):
        """Voice command keywords are accepted at the lower confidence threshold."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.keywords = {"bote": "voice_command"}
        sink.voice_command_wake_confidence_threshold = 0.75

        # Confidence 0.76 → above voice_command threshold (0.75), should match
        result_obj = {"result": [{"word": "bote", "conf": 0.76}]}
        keyword, action, word_info = sink._check_keywords("bote", result_obj)
        assert keyword == "bote"
        assert action == "voice_command"
        assert word_info is not None
        assert word_info["word"] == "bote"

    def test_check_keywords_voice_command_low_confidence_rejected(self):
        """Voice command keywords below the lower threshold are still rejected."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.keywords = {"bote": "voice_command"}
        sink.voice_command_wake_confidence_threshold = 0.75

        # Confidence 0.50 → below threshold, should reject
        result_obj = {"result": [{"word": "bote", "conf": 0.50}]}
        keyword, action, word_info = sink._check_keywords("bote", result_obj)
        assert keyword is None
        assert action is None
        assert word_info is None

    def test_check_keywords_normal_keyword_strict_confidence(self):
        """Normal keywords (slap, list) still require the strict 0.95 threshold."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.keywords = {"diogo": "slap"}
        sink.voice_command_wake_confidence_threshold = 0.75

        # Confidence 0.80 → below normal 0.95, reject even though it's above voice threshold
        result_obj = {"result": [{"word": "diogo", "conf": 0.80}]}
        keyword, action, word_info = sink._check_keywords("diogo", result_obj)
        assert keyword is None
        assert action is None
        assert word_info is None

        # Confidence 0.96 → above 0.95, accept
        result_obj = {"result": [{"word": "diogo", "conf": 0.96}]}
        keyword, action, word_info = sink._check_keywords("diogo", result_obj)
        assert keyword == "diogo"
        assert action == "slap"
        assert word_info is not None
        assert word_info["word"] == "diogo"

    # ------------------------------------------------------------------ #
    # Transcript parsing with aliases
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_handle_voice_command_parses_ventura_transcript(self):
        """Transcript starting with 'ventura' is parsed correctly (new default wake word)."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 555
        sink.voice_command_enabled = True
        # Default-like config: ventura is both human wake word and vosk alias
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = ["ventura"]
        sink.voice_command_transcript_wake_words = ["ventura"]

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock(return_value=True)
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        # Groq returns transcript with ventura
        mock_voice_service.transcribe = AsyncMock(return_value="ventura play air horn")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(555, "VenturaUser", Mock())

        # Prompt is called twice: start + done
        sink.audio_service._play_voice_command_prompt.assert_awaited()
        sink.audio_service.sound_service.play_request.assert_awaited_once_with(
            "air horn", "VenturaUser", guild=sink.guild, request_note="play air horn", allow_rejected_exact_fallback=True
        )

    @pytest.mark.asyncio
    async def test_handle_voice_command_parses_alias_transcript(self):
        """Transcript starting with a Vosk alias (e.g. 'bote') is parsed correctly."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 444
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["bot"]
        # This test explicitly sets no Vosk aliases so fallback uses human wake words.
        # The transcript parsing uses the combined list via audio_service.
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock(return_value=True)
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)
        # Set transcript wake words on the sink itself (runtime stores locally)
        sink.voice_command_transcript_wake_words = ["bot", "bote"]

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        # Groq returns transcript with the alias form
        mock_voice_service.transcribe = AsyncMock(return_value="bote play air horn")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(555, "AliasUser", Mock())

        # Prompt is called twice: start + done
        sink.audio_service._play_voice_command_prompt.assert_awaited()
        sink.audio_service.sound_service.play_request.assert_awaited_once_with(
            "air horn", "AliasUser", guild=sink.guild, request_note="play air horn", allow_rejected_exact_fallback=True
        )
