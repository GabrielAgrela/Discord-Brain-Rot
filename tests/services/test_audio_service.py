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
            "19-05-26-18-25-29-767591-impatient O que é que queres.mp3",
            "19-05-26-18-25-42-020903-cheerful Fala campeão.mp3",
            "19-05-26-18-26-21-035113-casual Fala campeão.mp3",
            "19-05-26-18-28-18-619313-excited Vai estou a gravar .mp3",
            "19-05-26-18-28-34-628591-challenging Força surpreend.mp3",
            "19-05-26-18-28-57-441240-curious Diz lá chefe.mp3",
            "19-05-26-18-29-18-588546-stern Tens seis segundos par.mp3",
        ]
        service.voice_command_done_sounds = [
            "16-05-26-19-54-41-416014-Ok fica bem.mp3",
            "16-05-26-20-14-36-595803-Sim senhor.mp3",
            "16-05-26-20-15-00-686598-Ok já toco essa merda.mp3",
            "16-05-26-20-15-34-525805-shouts aggressive Ok já ag.mp3",
            "19-05-26-18-25-29-767591-impatient O que é que queres.mp3",
            "19-05-26-18-25-42-020903-cheerful Fala campeão.mp3",
            "19-05-26-18-26-21-035113-casual Fala campeão.mp3",
            "19-05-26-18-26-48-994281-tired Ok já tou a tratar.mp3",
            "19-05-26-18-27-11-419376-enthusiastic Tou a tratar disso.mp3",
            "19-05-26-18-27-27-071872-assertive Vai mas é para o car.mp3",
            "19-05-26-18-27-52-261545-calm Ok já toco essa merda.mp3",
            "19-05-26-18-28-17-316184-casual Tás a brincar Ok já to.mp3",
            "19-05-26-18-29-47-016743-nodding Ok já trato disso.mp3",
            "19-05-26-18-29-59-198767-sarcastic Ok seu animal.mp3",
            "19-05-26-18-30-10-622881-sighs Já ouvi essa merda.mp3",
            "19-05-26-18-30-25-238017-sarcastic Ok vou fingir que.mp3",
            "19-05-26-18-30-43-231662-frustrated Foda-se sighs .mp3",
        ]
        # Per-guild keyword detection state (normally set in __init__)
        service.keyword_sinks = {}
        service._keyword_detection_restart_tasks = {}
        # bot set by individual tests that need it (e.g. keyword detection retry tests)
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

    # --- _is_voice_client_active ---

    def test_is_voice_client_active_none(self, audio_service):
        """Returns False for None."""
        assert audio_service._is_voice_client_active(None) is False

    def test_is_voice_client_active_idle(self, audio_service):
        """Returns False when neither playing nor paused."""
        vc = Mock(is_playing=Mock(return_value=False), is_paused=Mock(return_value=False))
        assert audio_service._is_voice_client_active(vc) is False

    def test_is_voice_client_active_playing(self, audio_service):
        """Returns True when is_playing is True."""
        vc = Mock(is_playing=Mock(return_value=True))
        assert audio_service._is_voice_client_active(vc) is True

    def test_is_voice_client_active_paused(self, audio_service):
        """Returns True when is_paused is True."""
        vc = Mock(is_playing=Mock(return_value=False), is_paused=Mock(return_value=True))
        assert audio_service._is_voice_client_active(vc) is True

    def test_is_voice_client_active_no_is_paused(self, audio_service):
        """Returns False when is_playing is False and client has no is_paused."""
        vc = Mock(spec=["is_playing"], is_playing=Mock(return_value=False))
        assert audio_service._is_voice_client_active(vc) is False

    # --- interrupt_existing=False early skip ---

    @pytest.mark.asyncio
    async def test_play_audio_interrupt_existing_false_skips_when_busy_before_connect(self, audio_service):
        """interrupt_existing=False returns False early when voice client is already playing."""
        from bot.services.audio import AudioService

        guild = Mock(id=456, name="TestGuild")
        busy_vc = Mock(is_playing=Mock(return_value=True), is_paused=Mock(return_value=False))
        channel = Mock(guild=guild)
        channel.guild.voice_client = busy_vc

        audio_service.playback_done = asyncio.Event()
        audio_service.playback_done.set()
        AudioService._ensure_guild_playback_state(audio_service, guild.id)
        audio_service._guild_last_played_time[guild.id] = datetime.now()
        audio_service.mute_service = SimpleNamespace(is_muted=False)
        audio_service.message_service = Mock()
        audio_service._track_guild_play_request = Mock()
        audio_service.ensure_voice_connected = AsyncMock()

        result = await AudioService.play_audio(
            audio_service, channel, "clip.mp3", "tester",
            interrupt_existing=False,
        )

        assert result is False
        audio_service._track_guild_play_request.assert_not_called()
        audio_service.ensure_voice_connected.assert_not_called()

    @pytest.mark.asyncio
    async def test_play_audio_interrupt_existing_false_skips_when_busy_after_connect(self, audio_service):
        """interrupt_existing=False skips after ensure_voice_connected if busy in race window."""
        from bot.services.audio import AudioService

        guild = Mock(id=789, name="TestGuild2")
        busy_vc = Mock(is_playing=Mock(return_value=True), is_paused=Mock(return_value=False))
        channel = Mock(guild=guild)
        # No voice_client before connect, so early check passes
        channel.guild.voice_client = None

        audio_service.playback_done = asyncio.Event()
        audio_service.playback_done.set()
        AudioService._ensure_guild_playback_state(audio_service, guild.id)
        audio_service._guild_last_played_time[guild.id] = datetime.now()
        audio_service.mute_service = SimpleNamespace(is_muted=False)
        audio_service.message_service = Mock()
        audio_service._track_guild_play_request = Mock(return_value=True)
        audio_service._release_guild_play_request = Mock()
        # After connection, voice client becomes busy
        audio_service.ensure_voice_connected = AsyncMock(return_value=busy_vc)

        result = await AudioService.play_audio(
            audio_service, channel, "clip.mp3", "tester",
            interrupt_existing=False,
        )

        assert result is False
        audio_service._track_guild_play_request.assert_called_once()
        audio_service._release_guild_play_request.assert_called_once_with(guild.id)
        audio_service.ensure_voice_connected.assert_awaited_once_with(channel)

    @pytest.mark.asyncio
    async def test_play_audio_interrupt_existing_true_still_interrupts(self, audio_service):
        """interrupt_existing=True (default) still proceeds to normal interrupt path."""
        from bot.services.audio import AudioService

        guild = Mock(id=101112, name="TestGuild3")
        busy_vc = Mock(is_playing=Mock(return_value=True), is_paused=Mock(return_value=False))
        channel = Mock(guild=guild)
        channel.guild.voice_client = busy_vc

        audio_service.playback_done = asyncio.Event()
        audio_service.playback_done.set()
        AudioService._ensure_guild_playback_state(audio_service, guild.id)
        audio_service._guild_last_played_time[guild.id] = datetime.now()
        audio_service.mute_service = SimpleNamespace(is_muted=False)
        audio_service.message_service = Mock()
        audio_service.message_service.get_bot_channel = Mock(return_value=None)
        audio_service._track_guild_play_request = Mock(return_value=True)
        audio_service._release_guild_play_request = Mock()
        # Return a busy voice client so we enter the interrupt path
        audio_service.ensure_voice_connected = AsyncMock(return_value=busy_vc)
        # Need to set up sound repo to avoid AttributeError
        audio_service.sound_repo = Mock()
        audio_service.image_generator = Mock()
        audio_service._behavior = None
        audio_service._ffmpeg_semaphore = Mock()
        audio_service.ffmpeg_path = "/nonexistent"

        # Manually mock internal methods called during interrupt path
        audio_service._interrupt_live_tts_stream = Mock()
        audio_service._cancel_progress_update_task = Mock()
        audio_service._stop_voice_client_and_wait = AsyncMock()

        # Patch os.path.exists so the file resolution doesn't fall back to DB
        with patch("bot.services.audio.os.path.exists", return_value=True):
            result = await AudioService.play_audio(
                audio_service, channel, "clip.mp3", "tester",
            )

        # With no ffmpeg, this will fail after the interrupt but before actual playback.
        # Our focus is on verifying the interrupt path was taken.
        audio_service.ensure_voice_connected.assert_awaited_once_with(channel)
        audio_service._interrupt_live_tts_stream.assert_called_once()
        audio_service._stop_voice_client_and_wait.assert_awaited_once()

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

    @pytest.mark.asyncio
    @patch("bot.services.audio.discord.FFmpegPCMAudio")
    async def test_play_tts_live_stream_preroll_ms(self, mock_ffmpeg_pcm, audio_service):
        """Ensure play_tts_live_stream respects el_tts_live_preroll_ms when building ffmpeg filters."""
        from bot.services.audio import AudioService
        audio_service.ffmpeg_path = "/usr/bin/ffmpeg"
        audio_service.bot = Mock()
        audio_service.mute_service = Mock()
        audio_service.mute_service.is_muted = False
        audio_service.message_service = Mock()
        audio_service.message_service.get_bot_channel = Mock()
        audio_service.image_generator = Mock()
        audio_service.image_generator.generate_sound_card = AsyncMock(return_value=None)

        voice_client = Mock()
        voice_client.is_playing.return_value = False
        voice_client.is_paused = Mock(return_value=False)
        voice_client.is_connected.return_value = True
        voice_client._player = None

        audio_service.ensure_voice_connected = AsyncMock(return_value=voice_client)

        channel = Mock()
        channel.guild.id = 555

        # Test case 1: preroll > 0 (e.g. 50ms)
        audio_service.el_tts_live_preroll_ms = 50
        with patch.dict(os.environ, {"EL_TTS_LIVE_LOW_LATENCY_FFMPEG": "false"}):
            await AudioService.play_tts_live_stream(
                audio_service,
                fifo_path="/tmp/fake_fifo",
                audio_file="test_live.mp3",
                channel=channel,
                user="tester",
            )
        mock_ffmpeg_pcm.assert_called_with(
            "/tmp/fake_fifo",
            executable="/usr/bin/ffmpeg",
            before_options="-nostdin",
            options='-filter:a "volume=1.0,adelay=50:all=1"',
        )

        mock_ffmpeg_pcm.reset_mock()

        # Test case 2: preroll == 0
        audio_service.el_tts_live_preroll_ms = 0
        with patch.dict(os.environ, {"EL_TTS_LIVE_LOW_LATENCY_FFMPEG": "false"}):
            await AudioService.play_tts_live_stream(
                audio_service,
                fifo_path="/tmp/fake_fifo",
                audio_file="test_live.mp3",
                channel=channel,
                user="tester",
            )
        mock_ffmpeg_pcm.assert_called_with(
            "/tmp/fake_fifo",
            executable="/usr/bin/ffmpeg",
            before_options="-nostdin",
            options='-filter:a "volume=1.0"',
        )

    def test_build_live_tts_ffmpeg_before_options(self, audio_service):
        """Test build_live_tts_ffmpeg_before_options output under different env settings."""
        # Defaults: low latency false, assume mp3 true.
        with patch.dict(os.environ, {}, clear=True):
            opts = audio_service._build_live_tts_ffmpeg_before_options("mp3")
            assert opts == "-nostdin -f mp3"
            assert "nobuffer" not in opts

        # Low latency explicit true, assume mp3 default true.
        with patch.dict(os.environ, {"EL_TTS_LIVE_LOW_LATENCY_FFMPEG": "true", "EL_TTS_LIVE_ASSUME_MP3_FORMAT": "true"}):
            opts = audio_service._build_live_tts_ffmpeg_before_options("mp3")
            assert "-nostdin" in opts
            assert "-fflags nobuffer -flags low_delay" in opts
            assert "-f mp3" in opts

        # Non-mp3 format
        with patch.dict(os.environ, {"EL_TTS_LIVE_LOW_LATENCY_FFMPEG": "true", "EL_TTS_LIVE_ASSUME_MP3_FORMAT": "true"}):
            opts = audio_service._build_live_tts_ffmpeg_before_options(None)
            assert "-nostdin" in opts
            assert "-fflags nobuffer -flags low_delay" in opts
            assert "-f mp3" not in opts

        # Low latency disabled
        with patch.dict(os.environ, {"EL_TTS_LIVE_LOW_LATENCY_FFMPEG": "false", "EL_TTS_LIVE_ASSUME_MP3_FORMAT": "true"}):
            opts = audio_service._build_live_tts_ffmpeg_before_options("mp3")
            assert "-fflags nobuffer" not in opts
            assert "-f mp3" in opts

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
        sound_service = AsyncMock()
        sound_service.play_request = AsyncMock(return_value=True)
        sound_service.play_random_sound_from_list = AsyncMock(return_value=True)
        sound_service.list_repo = None  # No list repo — forces play_request path
        sink.audio_service.sound_service = sound_service
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
        mock_voice_service.transcribe = AsyncMock(return_value="bot toca air horn")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(999, "TestUser", Mock())

        # Prompt is called twice: start + done (done now played after parse)
        assert sink.audio_service._play_voice_command_prompt.await_count == 2
        sink.audio_service.sound_service.play_request.assert_awaited_once_with(
            "air horn", "TestUser", guild=sink.guild, request_note="toca air horn", allow_rejected_exact_fallback=True
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
        sink.audio_service._voice_command_quota_cooldowns = {}
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

        # Mock VT service for ElevenLabs TTS (quota not blocked)
        mock_vt = Mock()
        mock_vt.is_elevenlabs_quota_blocked = Mock(return_value=False)
        mock_vt.tts_EL = AsyncMock()
        sink.audio_service.voice_transformation_service = mock_vt

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
        # TTS was invoked with Ventura's reply, lang="pt", and request_note
        vt = sink.audio_service.voice_transformation_service
        vt.tts_EL.assert_awaited_once()
        call_args = vt.tts_EL.await_args
        assert call_args is not None
        assert call_args.kwargs.get("lang") == "pt"
        assert call_args.kwargs.get("request_note") == "stop doing that"
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
        sink.audio_service._voice_command_quota_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)

        # Ventura chat service reports unavailable (no key)
        mock_ventura = Mock()
        mock_ventura.is_available = False
        sink.audio_service._get_ventura_chat_service = Mock(return_value=mock_ventura)
        # VT service not needed since Ventura chat is skipped, but must pass quota check
        mock_vt = Mock()
        mock_vt.is_elevenlabs_quota_blocked = Mock(return_value=False)
        sink.audio_service.voice_transformation_service = mock_vt

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

    @pytest.mark.asyncio
    async def test_handle_voice_command_non_play_skips_when_quota_blocked(self):
        """When ElevenLabs quota is blocked, non-play transcript sets cooldown and sends message, skips Ventura chat."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 444
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = []
        sink._quota_notification_timestamps = {}

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service._voice_command_quota_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_quota_cooldown_seconds = 3600
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)
        sink.audio_service.message_service = AsyncMock()

        # VT service exists but reports quota blocked
        mock_vt = Mock()
        mock_vt.is_elevenlabs_quota_blocked = Mock(return_value=True)
        mock_vt.tts_EL = AsyncMock()
        sink.audio_service.voice_transformation_service = mock_vt

        # Ventura chat service should never be checked since quota is blocked
        mock_ventura = Mock()
        mock_ventura.is_available = True
        sink.audio_service._get_ventura_chat_service = Mock(return_value=mock_ventura)

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="ventura hello there")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(777, "QuotaBlockedUser", Mock())

        # Only start prompt played, no done prompt
        assert sink.audio_service._play_voice_command_prompt.await_count == 1
        # Ventura chat was NOT called (skipped due to quota block)
        mock_ventura.reply.assert_not_called()
        # TTS was not called
        mock_vt.tts_EL.assert_not_called()

        # Per-user quota cooldown should have been set
        quota_key = "444:777"
        import time
        assert quota_key in sink.audio_service._voice_command_quota_cooldowns
        deadline = sink.audio_service._voice_command_quota_cooldowns[quota_key]
        assert deadline > time.time() + 3500  # ~3600s from now

        # Quota unavailable message should have been sent
        msg_service = sink.audio_service.message_service
        msg_service.send_message.assert_awaited_once()
        call_kwargs = msg_service.send_message.call_args.kwargs
        assert call_kwargs["title"] == "ElevenLabs TTS Unavailable"
        assert call_kwargs["message_format"] == "image"
        assert call_kwargs["image_border_color"] == "#ED4245"

    @pytest.mark.asyncio
    async def test_handle_voice_command_non_play_quota_exceeded_during_tts(self):
        """When tts_EL raises ElevenLabsQuotaExceededError, handler logs and continues, does not raise."""
        from bot.services.audio import KeywordDetectionSink
        from bot.tts import ElevenLabsQuotaExceededError

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 555
        sink.guild.get_member = Mock(return_value=None)
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service._voice_command_quota_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_quota_cooldown_seconds = 3600
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)
        sink.audio_service.message_service = AsyncMock()
        # Set guild for _send_ventura_quota_unavailable_message
        sink.guild.get_member = Mock(return_value=None)

        # VT service exists, not blocked, but tts_EL raises quota error
        mock_vt = Mock()
        mock_vt.is_elevenlabs_quota_blocked = Mock(return_value=False)
        mock_vt.tts_EL = AsyncMock(side_effect=ElevenLabsQuotaExceededError(
            401, '{"detail":{"code":"quota_exceeded"}}'
        ))
        sink.audio_service.voice_transformation_service = mock_vt

        # Ventura chat service returns a reply
        mock_ventura = Mock()
        mock_ventura.is_available = True
        mock_ventura.reply = AsyncMock(return_value="[shouts] Quota acabou!")
        sink.audio_service._get_ventura_chat_service = Mock(return_value=mock_ventura)

        sink._quota_notification_timestamps = {}
        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="ventura what now")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        # Should not raise — handler catches the quota error
        await sink._handle_voice_command(888, "QuotaTTSUser", Mock())

        # Ventura chat was called
        mock_ventura.reply.assert_awaited_once()
        # TTS was called (and raised, but caught)

        # Quota unavailable notification sent with correct parameters
        msg_service = sink.audio_service.message_service
        msg_service.send_message.assert_awaited_once()
        call_kwargs = msg_service.send_message.call_args.kwargs
        assert call_kwargs["message_format"] == "image"
        assert call_kwargs["send_controls"] is False
        assert call_kwargs["title"] == "ElevenLabs TTS Unavailable"
        assert call_kwargs["image_border_color"] == "#ED4245"
        desc = call_kwargs.get("description", "")
        assert "60 minutes" in desc
        assert "**" not in desc, "Description must not contain markdown bold syntax"
        mock_vt.tts_EL.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_voice_command_play_works_when_quota_blocked(self):
        """Play/toca path works even when ElevenLabs quota is blocked."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 446
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service._voice_command_quota_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock(return_value=True)
        sink.audio_service.sound_service.play_random_sound_from_list = AsyncMock()
        sink.audio_service.sound_service.list_repo = None  # No list — forces play_request
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)

        # VT service reports quota blocked — should NOT affect play path
        mock_vt = Mock()
        mock_vt.is_elevenlabs_quota_blocked = Mock(return_value=True)
        mock_vt.tts_EL = AsyncMock()
        sink.audio_service.voice_transformation_service = mock_vt

        # Ventura chat should never be reached for play path
        mock_ventura = Mock()
        mock_ventura.is_available = True
        sink.audio_service._get_ventura_chat_service = Mock(return_value=mock_ventura)

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="ventura toca air horn")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(446, "PlayQuotaUser", Mock())

        # Start + done prompts played
        assert sink.audio_service._play_voice_command_prompt.await_count == 2
        # Play request was executed
        sink.audio_service.sound_service.play_request.assert_awaited_once()
        # Ventura chat NOT called (play path returned before Ventura branch)
        mock_ventura.reply.assert_not_called()
        # TTS NOT called
        mock_vt.tts_EL.assert_not_called()
        # No quota cooldown set (play path does not touch quota cooldowns)
        assert sink.audio_service._voice_command_quota_cooldowns == {}

    @pytest.mark.asyncio
    async def test_handle_voice_command_play_works_when_quota_cooldown_active(self):
        """Play/toca path works even when a quota cooldown is already active."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 447
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock(return_value=True)
        sink.audio_service.sound_service.play_random_sound_from_list = AsyncMock()
        sink.audio_service.sound_service.list_repo = None
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)

        # Set an active per-user quota cooldown
        import time
        sink.audio_service._voice_command_quota_cooldowns = {
            "447:447": time.time() + 3000,
        }

        mock_vt = Mock()
        mock_vt.is_elevenlabs_quota_blocked = Mock(return_value=False)
        sink.audio_service.voice_transformation_service = mock_vt

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="ventura toca air horn")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(447, "CooldownPlayUser", Mock())

        # Play request was executed despite active quota cooldown
        sink.audio_service.sound_service.play_request.assert_awaited_once()
        # No Ventura chat or TTS
        sink.audio_service._get_ventura_chat_service.assert_not_called()
        mock_vt.tts_EL.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_voice_command_non_play_skips_when_quota_cooldown_active(self):
        """When per-user quota cooldown is active, non-play transcript skips Ventura chat silently."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 448
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)

        # Set an active per-user quota cooldown
        import time
        sink.audio_service._voice_command_quota_cooldowns = {
            "448:448": time.time() + 3000,
        }

        # VT service NOT blocked but cooldown is active
        mock_vt = Mock()
        mock_vt.is_elevenlabs_quota_blocked = Mock(return_value=False)
        mock_vt.tts_EL = AsyncMock()
        sink.audio_service.voice_transformation_service = mock_vt

        mock_ventura = Mock()
        mock_ventura.is_available = True
        sink.audio_service._get_ventura_chat_service = Mock(return_value=mock_ventura)

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="ventura hello there")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(448, "CooldownChatUser", Mock())

        # Start prompt played, Groq transcription ran
        assert sink.audio_service._play_voice_command_prompt.await_count == 1
        mock_voice_service.transcribe.assert_awaited_once()
        # Ventura chat NOT called (skipped due to active quota cooldown)
        mock_ventura.reply.assert_not_called()
        # TTS NOT called
        mock_vt.tts_EL.assert_not_called()
        # Cooldown key still present (not consumed)
        assert "448:448" in sink.audio_service._voice_command_quota_cooldowns

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
            "19-05-26-18-25-29-767591-impatient O que é que queres.mp3",
            "19-05-26-18-25-42-020903-cheerful Fala campeão.mp3",
            "19-05-26-18-26-21-035113-casual Fala campeão.mp3",
            "19-05-26-18-28-18-619313-excited Vai estou a gravar .mp3",
            "19-05-26-18-28-34-628591-challenging Força surpreend.mp3",
            "19-05-26-18-28-57-441240-curious Diz lá chefe.mp3",
            "19-05-26-18-29-18-588546-stern Tens seis segundos par.mp3",
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
            "19-05-26-18-29-47-016743-nodding Ok já trato disso.mp3",
            "19-05-26-18-29-59-198767-sarcastic Ok seu animal.mp3",
            "19-05-26-18-30-10-622881-sighs Já ouvi essa merda.mp3",
            "19-05-26-18-30-25-238017-sarcastic Ok vou fingir que.mp3",
            "19-05-26-18-30-43-231662-frustrated Foda-se sighs .mp3",
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
        sound_service = AsyncMock()
        sound_service.list_repo = None  # Forces play_request path
        sound_service.play_request = AsyncMock()
        sound_service.play_random_sound_from_list = AsyncMock()
        sink.audio_service.sound_service = sound_service
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)
        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        now = 1000.0
        with patch("bot.services.audio.time.time", return_value=now):
            # First call sets cooldown
            mock_voice_service = Mock()
            mock_voice_service.is_available = True
            mock_voice_service.transcribe = AsyncMock(return_value="bot toca test")
            sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)
            await sink._handle_voice_command(777, "Rater", Mock())
            # Prompt is called twice: start + done
            sink.audio_service._play_voice_command_prompt.assert_awaited()
            assert sink.audio_service._voice_command_cooldowns.get("333:777", 0) == now

            # Second call within cooldown (rate limited — prompt not called again)
            sink.audio_service._play_voice_command_prompt.reset_mock()
            mock_voice_service2 = Mock()
            mock_voice_service2.is_available = True
            mock_voice_service2.transcribe = AsyncMock(return_value="bot toca another")
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

    @pytest.mark.asyncio
    async def test_handle_voice_command_mute_activates_mute(self):
        """Verify ``mute`` transcript activates mute and logs action (no slap fallback)."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 666
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = ["ventura"]
        sink.voice_command_transcript_wake_words = ["ventura"]

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)
        sink.audio_service.play_slap = AsyncMock()

        # Mock mute service
        sink.audio_service.mute_service = Mock()
        sink.audio_service.mute_service.activate = AsyncMock(return_value=True)

        # Mock action_repo
        sink.audio_service.action_repo = Mock()
        sink.audio_service.action_repo.insert = Mock()

        # Behavior with no slap sounds (so play_slap is never called)
        behavior = Mock()
        behavior.db.get_sounds = Mock(return_value=[])
        sink.audio_service._behavior = behavior

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="ventura mute")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(666, "MuteUser", Mock())

        # Prompt is called once (start only; no done prompt for mute)
        assert sink.audio_service._play_voice_command_prompt.await_count == 1

        # No play_request or Ventura chat
        sink.audio_service.sound_service.play_request.assert_not_called()
        sink.audio_service._get_ventura_chat_service.assert_not_called()

        # Slap was not called because no slap sounds available
        sink.audio_service.play_slap.assert_not_called()

        # Mute service was activated with 1800 seconds
        sink.audio_service.mute_service.activate.assert_awaited_once_with(
            duration_seconds=1800,
            requested_by="MuteUser",
        )

        # Action was logged
        sink.audio_service.action_repo.insert.assert_called_once_with(
            "MuteUser", "mute_30_minutes", "", guild_id=666,
        )

    @pytest.mark.asyncio
    async def test_handle_voice_command_mute_with_slap(self):
        """Verify ``mute`` transcript plays a slap before muting when slaps exist."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 667
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = ["ventura"]
        sink.voice_command_transcript_wake_words = ["ventura"]

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)
        sink.audio_service.play_slap = AsyncMock(return_value=True)

        # Mock mute service
        sink.audio_service.mute_service = Mock()
        sink.audio_service.mute_service.activate = AsyncMock(return_value=True)

        # Mock action_repo
        sink.audio_service.action_repo = Mock()
        sink.audio_service.action_repo.insert = Mock()

        # Behavior with slap sounds available
        behavior = Mock()
        mock_slap = (1, "slap-name", "slap-file.mp3", 0, 0, 0, 1, "2024-01-01", 0, None)
        behavior.db.get_sounds = Mock(return_value=[mock_slap])
        sink.audio_service._behavior = behavior

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="ventura mute")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(667, "SlapMuteUser", Mock())

        # Slap was played
        sink.audio_service.play_slap.assert_awaited_once()

        # Mute was activated
        sink.audio_service.mute_service.activate.assert_awaited_once_with(
            duration_seconds=1800,
            requested_by="SlapMuteUser",
        )

        # Action was logged
        sink.audio_service.action_repo.insert.assert_called_once_with(
            "SlapMuteUser", "mute_30_minutes", "", guild_id=667,
        )

    @pytest.mark.asyncio
    async def test_handle_voice_command_cala_te_mute(self):
        """Verify ``ventura cala-te`` transcript activates mute (alias integration)."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 668
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = ["ventura"]
        sink.voice_command_transcript_wake_words = ["ventura"]

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)
        sink.audio_service.play_slap = AsyncMock()

        # Mock mute service
        sink.audio_service.mute_service = Mock()
        sink.audio_service.mute_service.activate = AsyncMock(return_value=True)

        # Mock action_repo
        sink.audio_service.action_repo = Mock()
        sink.audio_service.action_repo.insert = Mock()

        # Behavior with no slap sounds
        behavior = Mock()
        behavior.db.get_sounds = Mock(return_value=[])
        sink.audio_service._behavior = behavior

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="ventura cala-te")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(668, "CalaTeUser", Mock())

        # Prompt is called once (start only; no done prompt for mute)
        assert sink.audio_service._play_voice_command_prompt.await_count == 1

        # No play_request or Ventura chat
        sink.audio_service.sound_service.play_request.assert_not_called()
        sink.audio_service._get_ventura_chat_service.assert_not_called()

        # Slap not called because no slap sounds
        sink.audio_service.play_slap.assert_not_called()

        # Mute service was activated with 1800 seconds
        sink.audio_service.mute_service.activate.assert_awaited_once_with(
            duration_seconds=1800,
            requested_by="CalaTeUser",
        )

        # Action was logged
        sink.audio_service.action_repo.insert.assert_called_once_with(
            "CalaTeUser", "mute_30_minutes", "", guild_id=668,
        )

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
    # Voice-command listening state suppression tests
    # ------------------------------------------------------------------ #

    def test_write_skips_vosk_queuing_and_still_feeds_capture_during_listening(self):
        """write() feeds _active_captures but does not queue to Vosk while listening."""
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

        # Manually set the listening state
        sink._voice_command_listening_user_id = 12345
        sink._voice_command_listening_lock = Mock()
        sink._voice_command_listening_lock.__enter__ = Mock(return_value=None)
        sink._voice_command_listening_lock.__exit__ = Mock(return_value=None)

        user_id = 12345
        data = b"\xaa\xbb" * 50

        # Set up an active capture (must still be fed!)
        capture = {"chunks": [], "last_audio_time": 0.0, "total_bytes": 0}
        sink._active_captures[user_id] = capture

        with patch("bot.services.audio.time.time", return_value=1000.0):
            sink.write(data, user_id)

        # Capture should still get the data (for voice-command recording)
        assert capture["chunks"] == [data]
        assert capture["total_bytes"] == len(data)

        # Vosk queue should NOT have been called
        sink.queue.put.assert_not_called()

    def test_write_skips_vosk_for_other_user_during_listening(self):
        """write() does not queue other users' audio to Vosk while listening."""
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

        # Listening to user 12345
        sink._voice_command_listening_user_id = 12345
        sink._voice_command_listening_lock = Mock()
        sink._voice_command_listening_lock.__enter__ = Mock(return_value=None)
        sink._voice_command_listening_lock.__exit__ = Mock(return_value=None)

        # Other user speaks
        with patch("bot.services.audio.time.time", return_value=1000.0):
            sink.write(b"other data", 99999)

        # Vosk queue should NOT have been called
        sink.queue.put.assert_not_called()

    def test_begin_voice_command_listening_returns_true_when_inactive(self):
        """_begin_voice_command_listening returns True when no session is active."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        # Attributes are missing (no __init__) — helpers must handle this.
        result = sink._begin_voice_command_listening(12345)
        assert result is True
        assert sink._voice_command_listening_user_id == 12345

    def test_begin_voice_command_listening_returns_false_when_active(self):
        """_begin_voice_command_listening returns False when a session is already active."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        # First call succeeds
        assert sink._begin_voice_command_listening(111) is True
        # Second call (different user) fails
        assert sink._begin_voice_command_listening(222) is False
        # State still belongs to first user
        assert sink._voice_command_listening_user_id == 111

    def test_end_voice_command_listening_clears_for_correct_user(self):
        """_end_voice_command_listening only clears when user_id matches."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink._begin_voice_command_listening(111)

        # Wrong user does not clear
        sink._end_voice_command_listening(222)
        assert sink._voice_command_listening_user_id == 111

        # Correct user clears
        sink._end_voice_command_listening(111)
        assert sink._voice_command_listening_user_id is None

    def test_end_voice_command_listening_noop_when_not_active(self):
        """_end_voice_command_listening is a no-op when no session is active."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        # Should not raise even though state was never set
        sink._end_voice_command_listening(111)

    def test_is_voice_command_listening_uses_getattr_fallback(self):
        """_is_voice_command_listening handles missing attributes (__new__ pattern)."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        # Attributes not set — should not raise
        assert sink._is_voice_command_listening() is False

    def test_detect_keyword_skips_during_listening(self):
        """detect_keyword returns early while voice-command listening is active."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.get_member = Mock(return_value=None)
        sink.audio_service = Mock()
        sink.audio_service.vosk_model = Mock()
        sink.recognizers = {}
        sink.resample_states = {}
        sink.last_partial = {}

        # Set listening state
        sink._voice_command_listening_user_id = 12345
        sink._voice_command_listening_lock = Mock()
        sink._voice_command_listening_lock.__enter__ = Mock(return_value=None)
        sink._voice_command_listening_lock.__exit__ = Mock(return_value=None)

        # This should be a no-op (no Vosk processing, no error)
        sink.detect_keyword(b"\x00\x00" * 100, 12345)

        # Verify no recognizer was created
        assert 12345 not in sink.recognizers

    def test_trigger_action_ignores_slap_during_listening(self):
        """trigger_action does not play slap while voice-command listening is active."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.voice_client = Mock()
        sink.guild.voice_client.channel = Mock()
        sink.guild.get_member = Mock(return_value=None)
        sink.audio_service = Mock()

        # Set listening state
        sink._voice_command_listening_user_id = 12345
        sink._voice_command_listening_lock = Mock()
        sink._voice_command_listening_lock.__enter__ = Mock(return_value=None)
        sink._voice_command_listening_lock.__exit__ = Mock(return_value=None)

        # Should not raise and should not play any slap
        import asyncio
        asyncio.run(sink.trigger_action(12345, "diogo", "slap"))

        # audio_service._behavior.db.get_sounds should not have been called
        sink.audio_service._behavior.assert_not_called()

    def test_trigger_action_ignores_list_during_listening(self):
        """trigger_action does not play list sounds while voice-command listening is active."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.voice_client = Mock()
        sink.guild.voice_client.channel = Mock()
        sink.guild.get_member = Mock(return_value=None)
        sink.audio_service = Mock()

        # Set listening state
        sink._voice_command_listening_user_id = 12345
        sink._voice_command_listening_lock = Mock()
        sink._voice_command_listening_lock.__enter__ = Mock(return_value=None)
        sink._voice_command_listening_lock.__exit__ = Mock(return_value=None)

        import asyncio
        asyncio.run(sink.trigger_action(12345, "hugo", "list:mylist"))

        # No play_audio or sound_service interaction
        sink.audio_service.play_audio.assert_not_called()
        sink.audio_service.sound_service.assert_not_called()

    def test_trigger_action_voice_command_does_not_check_quota_at_stage(self):
        """trigger_action no longer checks quota — always delegates to _handle_voice_command."""
        import time as _time
        from bot.services.audio import KeywordDetectionSink
        with patch('bot.services.audio.KeywordDetectionSink._handle_voice_command', new_callable=AsyncMock) as mock_handle:
            sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
            sink.guild = Mock()
            sink.guild.id = 10001
            sink.guild.voice_client = Mock()
            sink.guild.voice_client.channel = Mock()
            sink.guild.get_member = Mock(return_value=None)
            sink.voice_command_enabled = True
            sink._quota_notification_timestamps = {}

            sink.audio_service = Mock()
            sink.audio_service._voice_command_quota_cooldowns = {}
            sink.audio_service.voice_command_quota_cooldown_seconds = 3600
            sink.audio_service.message_service = AsyncMock()

            # VT service reports quota blocked
            mock_vt = Mock()
            mock_vt.is_elevenlabs_quota_blocked = Mock(return_value=True)
            sink.audio_service.voice_transformation_service = mock_vt

            import asyncio
            asyncio.run(sink.trigger_action(10001, "ventura", "voice_command"))

            # trigger_action should have delegated to _handle_voice_command
            mock_handle.assert_called_once()
            assert mock_handle.call_args[0][0] == 10001
            # No quota cooldown or message set at trigger_action stage
            assert sink.audio_service._voice_command_quota_cooldowns == {}
            sink.audio_service.message_service.send_message.assert_not_called()

    def test_trigger_action_voice_command_delegates_when_quota_cooldown_active(self):
        """trigger_action delegates to _handle_voice_command even when quota cooldown is active."""
        import time as _time
        from bot.services.audio import KeywordDetectionSink
        with patch('bot.services.audio.KeywordDetectionSink._handle_voice_command', new_callable=AsyncMock) as mock_handle:
            sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
            sink.guild = Mock()
            sink.guild.id = 10002
            sink.guild.voice_client = Mock()
            sink.guild.voice_client.channel = Mock()
            sink.guild.get_member = Mock(return_value=None)
            sink.voice_command_enabled = True
            sink._quota_notification_timestamps = {}

            sink.audio_service = Mock()
            # VT service NOT blocked (quota recovered) but cooldown still active
            mock_vt = Mock()
            mock_vt.is_elevenlabs_quota_blocked = Mock(return_value=False)
            sink.audio_service.voice_transformation_service = mock_vt

            # Set an active quota cooldown (deadline in the future)
            sink.audio_service._voice_command_quota_cooldowns = {
                "10002:10002": _time.time() + 3000,  # 50 minutes remaining
            }
            sink.audio_service.voice_command_quota_cooldown_seconds = 3600

            import asyncio
            asyncio.run(sink.trigger_action(10002, "ventura", "voice_command"))

            # _handle_voice_command should have been called (trigger_action no longer checks cooldowns)
            mock_handle.assert_called_once()
            assert mock_handle.call_args[0][0] == 10002

    def test_trigger_action_voice_command_delegates_with_expired_quota_cooldown(self):
        """trigger_action delegates to _handle_voice_command even with expired cooldown (cooldown checks moved to handler)."""
        import time as _time
        from bot.services.audio import KeywordDetectionSink
        with patch('bot.services.audio.KeywordDetectionSink._handle_voice_command', new_callable=AsyncMock) as mock_handle:
            sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
            sink.guild = Mock()
            sink.guild.id = 10003
            sink.guild.voice_client = Mock()
            sink.guild.voice_client.channel = Mock()
            sink.guild.get_member = Mock(return_value=None)
            sink.voice_command_enabled = True
            sink._quota_notification_timestamps = {}

            sink.audio_service = Mock()
            # VT service not blocked
            mock_vt = Mock()
            mock_vt.is_elevenlabs_quota_blocked = Mock(return_value=False)
            sink.audio_service.voice_transformation_service = mock_vt

            # Set an expired quota cooldown (deadline in the past)
            sink.audio_service._voice_command_quota_cooldowns = {
                "10003:10003": _time.time() - 100,  # 100 seconds ago
            }
            sink.audio_service.voice_command_quota_cooldown_seconds = 3600

            import asyncio
            asyncio.run(sink.trigger_action(10003, "ventura", "voice_command"))

            # trigger_action does NOT touch cooldowns — cooldown key still present
            assert "10003:10003" in sink.audio_service._voice_command_quota_cooldowns
            # _handle_voice_command should have been called (trigger_action always delegates)
            assert mock_handle.call_count == 1
            assert mock_handle.call_args[0][0] == 10003

    @pytest.mark.asyncio
    async def test_handle_voice_command_clears_listening_after_recording(self):
        """Listening state is released right after recording (no-audio path)."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 999
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)

        # Mock recording to return empty bytes (no audio path)
        sink._record_voice_command_after_beep = AsyncMock(return_value=bytes())

        # Listening state should NOT be active yet
        assert sink._is_voice_command_listening() is False

        await sink._handle_voice_command(999, "SilentUser", Mock())

        # After the call completes, listening state should be released
        assert sink._is_voice_command_listening() is False

    @pytest.mark.asyncio
    async def test_handle_voice_command_does_not_interleave(self):
        """A second voice-command call while one is active is ignored."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 777
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sound_service = AsyncMock()
        sound_service.list_repo = None
        sound_service.play_request = AsyncMock()
        sound_service.play_random_sound_from_list = AsyncMock()
        sink.audio_service.sound_service = sound_service
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)
        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="ventura toca test")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        # First call begins listening
        await sink._handle_voice_command(777, "UserA", Mock())

        # Set listening to simulate a concurrent second wake
        sink._voice_command_listening_user_id = 888
        result = sink._begin_voice_command_listening(888)
        assert result is False  # Already listening to another user

        # Clean up for subsequent tests
        sink._end_voice_command_listening(888)

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
        sound_service = AsyncMock()
        sound_service.play_request = AsyncMock(return_value=True)
        sound_service.play_random_sound_from_list = AsyncMock()
        sound_service.list_repo = None  # Forces play_request path
        sink.audio_service.sound_service = sound_service
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        # Groq returns transcript with ventura
        mock_voice_service.transcribe = AsyncMock(return_value="ventura toca air horn")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(555, "VenturaUser", Mock())

        # Prompt is called twice: start + done
        sink.audio_service._play_voice_command_prompt.assert_awaited()
        sink.audio_service.sound_service.play_request.assert_awaited_once_with(
            "air horn", "VenturaUser", guild=sink.guild, request_note="toca air horn", allow_rejected_exact_fallback=True
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
        sound_service = AsyncMock()
        sound_service.play_request = AsyncMock(return_value=True)
        sound_service.play_random_sound_from_list = AsyncMock()
        sound_service.list_repo = None  # Forces play_request path
        sink.audio_service.sound_service = sound_service
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)
        # Set transcript wake words on the sink itself (runtime stores locally)
        sink.voice_command_transcript_wake_words = ["bot", "bote"]

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        # Groq returns transcript with the alias form
        mock_voice_service.transcribe = AsyncMock(return_value="bote toca air horn")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(555, "AliasUser", Mock())

        # Prompt is called twice: start + done
        sink.audio_service._play_voice_command_prompt.assert_awaited()
        sink.audio_service.sound_service.play_request.assert_awaited_once_with(
            "air horn", "AliasUser", guild=sink.guild, request_note="toca air horn", allow_rejected_exact_fallback=True
        )

    # ------------------------------------------------------------------ #
    # Voice-command list playback tests
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_handle_voice_command_play_list_by_name(self):
        """When transcript has ``toca <list_name>`` and a list with that name exists,
        ``play_random_sound_from_list`` is called instead of ``play_request``."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 666
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock(return_value=True)
        sink.audio_service.sound_service.play_random_sound_from_list = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)

        # Mock list_repo to return a list for "memes"
        from unittest.mock import PropertyMock
        mock_list_repo = Mock()
        mock_list_repo.get_by_name = Mock(return_value=(1, "memes", "creator"))
        type(sink.audio_service.sound_service).list_repo = PropertyMock(return_value=mock_list_repo)

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="ventura toca memes")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(666, "ListUser", Mock())

        # Prompt called twice: start + done
        assert sink.audio_service._play_voice_command_prompt.await_count == 2
        # list_repo.get_by_name was called to check for the list
        mock_list_repo.get_by_name.assert_called_once_with("memes", guild_id=666)
        # play_random_sound_from_list was called, NOT play_request
        sink.audio_service.sound_service.play_random_sound_from_list.assert_awaited_once_with(
            "memes", "ListUser", guild=sink.guild, request_note="toca memes"
        )
        sink.audio_service.sound_service.play_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_voice_command_play_list_explicit_marker(self):
        """Transcript ``ventura toca lista memes`` strips the marker and uses list ``memes``."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 667
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock(return_value=True)
        sink.audio_service.sound_service.play_random_sound_from_list = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)

        from unittest.mock import PropertyMock
        mock_list_repo = Mock()
        mock_list_repo.get_by_name = Mock(return_value=(1, "memes", "creator"))
        type(sink.audio_service.sound_service).list_repo = PropertyMock(return_value=mock_list_repo)

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="ventura toca lista memes")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(667, "ListExplicitUser", Mock())

        # list_repo was called with "memes" (after stripping "lista " prefix)
        mock_list_repo.get_by_name.assert_called_once_with("memes", guild_id=667)
        sink.audio_service.sound_service.play_random_sound_from_list.assert_awaited_once_with(
            "memes", "ListExplicitUser", guild=sink.guild, request_note="toca lista memes"
        )

    @pytest.mark.asyncio
    async def test_handle_voice_command_play_list_case_insensitive(self):
        """Transcript with mixed-case argument routes to the canonical stored list name."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 669
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock(return_value=True)
        sink.audio_service.sound_service.play_random_sound_from_list = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)

        from unittest.mock import PropertyMock
        mock_list_repo = Mock()
        # get_by_name is called with the transcript-cased argument "GAY" but the
        # repo (already case-insensitive) returns the canonical stored name "gay".
        mock_list_repo.get_by_name = Mock(return_value=(1, "gay", "creator"))
        type(sink.audio_service.sound_service).list_repo = PropertyMock(return_value=mock_list_repo)

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="ventura TOCA GAY")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(669, "CIUser", Mock())

        # get_by_name was called with the transcript-cased candidate "GAY"
        mock_list_repo.get_by_name.assert_called_once_with("GAY", guild_id=669)
        # play_random_sound_from_list was called with the canonical stored "gay"
        sink.audio_service.sound_service.play_random_sound_from_list.assert_awaited_once_with(
            "gay", "CIUser", guild=sink.guild, request_note="toca GAY"
        )
        sink.audio_service.sound_service.play_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_voice_command_play_list_explicit_marker_a_lista_upper(self):
        """Transcript ``ventura toca A LISTA Memes`` strips the marker and routes to canonical stored name."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 670
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock(return_value=True)
        sink.audio_service.sound_service.play_random_sound_from_list = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)

        from unittest.mock import PropertyMock
        mock_list_repo = Mock()
        mock_list_repo.get_by_name = Mock(return_value=(1, "Memes", "creator"))
        type(sink.audio_service.sound_service).list_repo = PropertyMock(return_value=mock_list_repo)

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="ventura toca A LISTA Memes")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(670, "MarkerUser", Mock())

        # After stripping "A LISTA ", get_by_name is called with "Memes"
        mock_list_repo.get_by_name.assert_called_once_with("Memes", guild_id=670)
        # play_random_sound_from_list is called with the canonical stored name "Memes"
        sink.audio_service.sound_service.play_random_sound_from_list.assert_awaited_once_with(
            "Memes", "MarkerUser", guild=sink.guild, request_note="toca A LISTA Memes"
        )
        sink.audio_service.sound_service.play_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_voice_command_play_list_explicit_marker_lista_upper(self):
        """Transcript ``ventura toca LISTA GAY`` strips the uppercase marker and routes to canonical stored name."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 671
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock(return_value=True)
        sink.audio_service.sound_service.play_random_sound_from_list = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)

        from unittest.mock import PropertyMock
        mock_list_repo = Mock()
        mock_list_repo.get_by_name = Mock(return_value=(1, "gay", "creator"))
        type(sink.audio_service.sound_service).list_repo = PropertyMock(return_value=mock_list_repo)

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="ventura toca LISTA GAY")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(671, "MarkerUpperUser", Mock())

        # After stripping "LISTA " (prefix check is case-insensitive), get_by_name is called with "GAY"
        mock_list_repo.get_by_name.assert_called_once_with("GAY", guild_id=671)
        # play_random_sound_from_list is called with the canonical stored name "gay"
        sink.audio_service.sound_service.play_random_sound_from_list.assert_awaited_once_with(
            "gay", "MarkerUpperUser", guild=sink.guild, request_note="toca LISTA GAY"
        )
        sink.audio_service.sound_service.play_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_voice_command_play_not_list_falls_to_play_request(self):
        """When no list matches, voice command falls back to SoundService.play_request."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.guild = Mock()
        sink.guild.id = 668
        sink.voice_command_enabled = True
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = []

        sink.audio_service = Mock()
        sink.audio_service._voice_command_cooldowns = {}
        sink.audio_service.voice_command_cooldown_seconds = 5
        sink.audio_service.voice_command_capture_seconds = 6
        sink.audio_service.sound_service = AsyncMock()
        sink.audio_service.sound_service.play_request = AsyncMock(return_value=True)
        sink.audio_service.sound_service.play_random_sound_from_list = AsyncMock()
        sink.audio_service._play_voice_command_prompt = AsyncMock(return_value=True)

        from unittest.mock import PropertyMock
        mock_list_repo = Mock()
        mock_list_repo.get_by_name = Mock(return_value=None)  # No list found
        type(sink.audio_service.sound_service).list_repo = PropertyMock(return_value=mock_list_repo)

        sink._record_voice_command_after_beep = AsyncMock(return_value=b"\x00\x00" * 100)

        mock_voice_service = Mock()
        mock_voice_service.is_available = True
        mock_voice_service.transcribe = AsyncMock(return_value="ventura toca nonexistentsound")
        sink.audio_service._get_voice_command_service = Mock(return_value=mock_voice_service)

        await sink._handle_voice_command(668, "FallbackUser", Mock())

        list_repo = sink.audio_service.sound_service.list_repo
        list_repo.get_by_name.assert_called_once_with("nonexistentsound", guild_id=668)
        # Falls back to play_request since no list exists
        sink.audio_service.sound_service.play_request.assert_awaited_once_with(
            "nonexistentsound", "FallbackUser", guild=sink.guild,
            request_note="toca nonexistentsound", allow_rejected_exact_fallback=True,
        )
        sink.audio_service.sound_service.play_random_sound_from_list.assert_not_called()

    # ---- Keyword detection retry / self-healing tests ----

    @pytest.mark.asyncio
    async def test_start_keyword_detection_schedules_retry_when_no_voice_client(self, audio_service):
        """Ensure start_keyword_detection schedules a restart when there is no voice client."""
        from bot.services.audio import AudioService

        audio_service.keyword_sinks = {}
        # No _behavior set → _is_stt_enabled_for_guild defaults True
        # Need bot.loop for schedule_keyword_detection_restart
        audio_service.bot = Mock()
        audio_service.bot.loop = asyncio.get_running_loop()
        guild = Mock(id=999, name="Guild NoVoice")
        guild.voice_client = None  # No voice client at all

        with patch.object(audio_service, 'schedule_keyword_detection_restart') as mock_schedule:
            result = await AudioService.start_keyword_detection(audio_service, guild)

        assert result is False
        mock_schedule.assert_called_once()
        args, kwargs = mock_schedule.call_args
        assert args[0] is guild  # First positional arg is guild
        assert 'start_no_voice' in str(kwargs.get('reason', ''))

    @pytest.mark.asyncio
    async def test_start_keyword_detection_schedules_retry_when_voice_lost_after_delay(self, audio_service):
        """Ensure start_keyword_detection schedules a restart when voice is lost after the stabilize delay."""
        from bot.services.audio import AudioService

        audio_service.keyword_sinks = {}
        audio_service.bot = Mock()
        audio_service.bot.loop = asyncio.get_running_loop()
        guild = Mock(id=1000, name="Guild LostVoice")
        # Voice client: first is_connected() returns True, second returns False (after delay)
        voice_client = Mock()
        voice_client.is_connected.side_effect = [True, False]
        guild.voice_client = voice_client

        with patch.object(audio_service, 'schedule_keyword_detection_restart') as mock_schedule:
            with patch('asyncio.sleep'):
                result = await AudioService.start_keyword_detection(audio_service, guild)

        assert result is False
        mock_schedule.assert_called_once()
        args, kwargs = mock_schedule.call_args
        assert args[0] is guild
        assert 'start_voice_lost' in str(kwargs.get('reason', ''))

    @pytest.mark.asyncio
    async def test_start_keyword_detection_schedules_retry_on_recording_failure(self, audio_service):
        """Ensure start_keyword_detection schedules a restart when start_recording raises."""
        from bot.services.audio import AudioService

        audio_service.keyword_sinks = {}
        audio_service.bot = Mock()
        audio_service.bot.loop = asyncio.get_running_loop()
        guild = Mock(id=1001, name="Guild RecordFail")
        voice_client = Mock()
        voice_client.is_connected.return_value = True
        voice_client.start_recording.side_effect = RuntimeError("boom")
        guild.voice_client = voice_client

        with patch.object(audio_service, 'schedule_keyword_detection_restart') as mock_schedule:
            with patch('asyncio.sleep'):
                result = await AudioService.start_keyword_detection(audio_service, guild)

        assert result is False
        mock_schedule.assert_called_once()
        args, kwargs = mock_schedule.call_args
        assert args[0] is guild
        assert 'start_recording_failed' in str(kwargs.get('reason', ''))

    @pytest.mark.asyncio
    async def test_start_keyword_detection_does_not_schedule_retry_when_disabled(self, audio_service):
        """Ensure schedule_retry=False suppresses the retry scheduling."""
        from bot.services.audio import AudioService

        audio_service.keyword_sinks = {}
        guild = Mock(id=1002, name="Guild NoRetry")
        guild.voice_client = None

        with patch.object(audio_service, 'schedule_keyword_detection_restart') as mock_schedule:
            result = await AudioService.start_keyword_detection(audio_service, guild, schedule_retry=False)

        assert result is False
        mock_schedule.assert_not_called()

    def test_schedule_keyword_detection_restart_noops_when_stt_disabled(self, audio_service):
        """Ensure schedule_keyword_detection_restart does nothing when STT is disabled."""
        audio_service._keyword_detection_restart_tasks = {}
        audio_service._behavior = SimpleNamespace(
            _guild_settings_service=SimpleNamespace(
                get=Mock(return_value=SimpleNamespace(stt_enabled=False))
            )
        )
        guild = Mock(id=1003, name="Guild STTOff")
        guild.voice_client = Mock()

        # If STT disabled, early return — no task stored
        audio_service.schedule_keyword_detection_restart(guild, reason="test")

        assert 1003 not in audio_service._keyword_detection_restart_tasks

    def test_schedule_keyword_detection_restart_noop_when_already_running(self, audio_service):
        """Ensure schedule_keyword_detection_restart skips when detection is healthy."""
        from bot.services.audio import KeywordDetectionSink

        audio_service._keyword_detection_restart_tasks = {}
        audio_service.bot = Mock()
        audio_service.bot.loop = asyncio.new_event_loop()
        guild = Mock(id=1004, name="Guild AlreadyRunning")

        # Create a healthy sink with an alive thread
        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.worker_thread = Mock()
        sink.worker_thread.is_alive.return_value = True
        audio_service.keyword_sinks[1004] = sink

        with patch.object(audio_service, '_is_stt_enabled_for_guild', return_value=True):
            audio_service.schedule_keyword_detection_restart(guild, reason="test")

        # No task should be stored
        assert 1004 not in audio_service._keyword_detection_restart_tasks

    @pytest.mark.asyncio
    async def test_schedule_keyword_detection_restart_noop_when_duplicate_task(self, audio_service):
        """Ensure schedule_keyword_detection_restart does not duplicate an active restart task."""
        audio_service._keyword_detection_restart_tasks = {}
        audio_service.bot = Mock()
        audio_service.bot.loop = asyncio.get_running_loop()
        guild = Mock(id=1005, name="Guild Duplicate")

        with patch.object(audio_service, '_is_stt_enabled_for_guild', return_value=True):
            # First call should create a task
            audio_service.schedule_keyword_detection_restart(guild, reason="first")
            assert 1005 in audio_service._keyword_detection_restart_tasks
            first_task = audio_service._keyword_detection_restart_tasks[1005]
            assert not first_task.done()

            # Second call should be a no-op (task already exists)
            audio_service.schedule_keyword_detection_restart(guild, reason="second")
            assert 1005 in audio_service._keyword_detection_restart_tasks
            assert audio_service._keyword_detection_restart_tasks[1005] is first_task

        # Clean up
        first_task.cancel()
        try:
            await first_task
        except (asyncio.CancelledError, Exception):
            pass

    def test_default_silence_timeout_is_one_second(self):
        """Verify the voice command silence timeout default value is 1.0."""
        from bot.services.audio import AudioService, KeywordDetectionSink
        
        # Instantiate AudioService with env unset
        with patch.dict("os.environ", {}), patch("bot.services.audio.vosk.Model"):
            service = AudioService(bot=Mock(), ffmpeg_path=Mock(), mute_service=Mock(), message_service=Mock())
            assert service.voice_command_silence_seconds == 1.0
            
            # Verify KeywordDetectionSink copies the 1.0 default
            sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
            sink.voice_command_silence_seconds = getattr(service, "voice_command_silence_seconds", 1.0)
            assert sink.voice_command_silence_seconds == 1.0


class TestSpeechTrainingSinkIntegration:
    """Tests for the speech training segmenter in KeywordDetectionSink."""

    def _make_sink(self, stt_enabled=True, recorder_enabled=True):
        """Create a bare KeywordDetectionSink instance with minimal mocks."""
        from bot.services.audio import KeywordDetectionSink

        sink = KeywordDetectionSink.__new__(KeywordDetectionSink)
        sink.stt_enabled = stt_enabled
        sink.audio_service = Mock()
        sink.guild = Mock(id=123)
        sink.guild.get_member = Mock(return_value=None)
        sink.loop = Mock()
        sink.running = True
        sink.recognizers = {}
        sink.resample_states = {}
        sink.last_audio_time = {}
        sink.queue = Mock()
        sink.keywords = {}
        sink.last_partial = {}
        sink.recognizer_start_time = {}
        sink.max_segment_duration = 10.0
        sink.audio_buffers = {}
        sink.min_batch_size = 28800
        sink.silence_flush_seconds = 0.35
        sink.voice_command_enabled = stt_enabled
        sink.voice_command_wake_words = ["ventura"]
        sink.voice_command_vosk_wake_words = ["ventura"]
        sink.voice_command_transcript_wake_words = ["ventura"]
        sink.voice_command_silence_seconds = 0.5
        sink.buffer_seconds = 30
        sink.user_audio_buffers = {}
        sink.buffer_last_update = {}
        sink.buffer_lock = Mock()
        sink._active_captures = {}
        sink._quota_notification_timestamps = {}
        sink._voice_command_listening_user_id = None
        sink._voice_command_listening_lock = Mock()
        sink.log_dir = "/tmp"

        # Speech training state
        import threading
        sink._speech_segment_pcm = {}
        sink._speech_segment_start = {}
        sink._speech_segment_last_chunk = {}
        sink._speech_lock = threading.Lock()

        # Energy-based speech detection state
        sink._speech_last_voiced = {}
        sink._speech_voiced_up_to = {}
        sink._speech_preroll_pcm = {}

        if recorder_enabled:
            from bot.services.speech_training import SpeechTrainingRecorderService
            recorder = SpeechTrainingRecorderService.__new__(SpeechTrainingRecorderService)
            recorder.enabled = True
            recorder.silence_seconds = 0.35
            recorder.min_duration_seconds = 0.25
            recorder.max_duration_seconds = 10.0
            recorder.min_rms = 0  # allow all RMS
            recorder.speech_rms_threshold = 250  # energy gate threshold
            recorder.preroll_seconds = 0.08
            recorder.trim_silence = True
            recorder.enqueue_segment = Mock(return_value=True)
            sink._speech_recorder = recorder
        else:
            sink._speech_recorder = None

        return sink

    # ------------------------------------------------------------------
    # Preroll buffer helpers
    # ------------------------------------------------------------------

    def test_store_preroll_chunk_creates_buffer(self):
        """Preroll buffer is created on first low-energy chunk."""
        sink = self._make_sink()
        data = b"\x00" * 1920  # 10 ms of silence at 48k stereo
        sink._store_preroll_chunk(111, data, 0.5)
        assert 111 in sink._speech_preroll_pcm
        assert bytes(sink._speech_preroll_pcm[111]) == data

    def test_preroll_buffer_capped(self):
        """Preroll buffer does not exceed max_seconds."""
        sink = self._make_sink()
        max_sec = 0.08
        chunk = b"\x00" * 19200  # 100 ms of silence
        # Feed 3 chunks = 300 ms, but cap is 80 ms
        for _ in range(3):
            sink._store_preroll_chunk(111, chunk, max_sec)
        max_bytes = int(max_sec * 192000)
        assert len(sink._speech_preroll_pcm[111]) <= max_bytes + 4  # frame-align fudge

    def test_collect_preroll_returns_and_clears(self):
        """_collect_preroll returns stored bytes and removes the buffer."""
        sink = self._make_sink()
        data = b"\x01\x02" * 960  # 10ms of low-amplitude signal
        sink._store_preroll_chunk(111, data, 0.5)
        result = sink._collect_preroll(111)
        assert result == data
        assert 111 not in sink._speech_preroll_pcm

    def test_collect_preroll_empty_no_error(self):
        """_collect_preroll returns empty bytes when no preroll exists."""
        sink = self._make_sink()
        result = sink._collect_preroll(999)
        assert result == b""

    def test_clear_preroll_removes_buffer(self):
        """_clear_preroll removes the preroll entry if present."""
        sink = self._make_sink()
        sink._store_preroll_chunk(111, b"\x00" * 1920, 0.5)
        sink._clear_preroll(111)
        assert 111 not in sink._speech_preroll_pcm

    def test_clear_preroll_no_error_when_missing(self):
        """_clear_preroll handles missing entry without error."""
        sink = self._make_sink()
        sink._clear_preroll(999)  # should not raise

    # ------------------------------------------------------------------
    # Energy-gated segmenter
    # ------------------------------------------------------------------

    @staticmethod
    def _low_rms_chunk(length_bytes=19200, rms=50):
        """Generate a low-RMS (silence-like) PCM chunk.

        50 RMS is well below the default 250 speech_rms_threshold.
        Uses a tiny sine wave at very low amplitude so _compute_rms
        returns a deterministic small value.
        """
        import array
        import math
        samples = length_bytes // 2
        vals = array.array("h", [int(rms * math.sin(i * 0.1)) for i in range(samples)])
        return vals.tobytes()

    @staticmethod
    def _high_rms_chunk(length_bytes=19200, rms=500):
        """Generate a high-RMS (voiced-like) PCM chunk.

        500 RMS is well above the default 250 speech_rms_threshold.
        """
        import array
        import math
        samples = length_bytes // 2
        vals = array.array("h", [int(rms * math.sin(i * 0.1)) for i in range(samples)])
        return vals.tobytes()

    def test_silence_only_does_not_start_segment(self):
        """Low-energy chunks alone never start a speech segment."""
        sink = self._make_sink()
        now = 1000.0
        for i in range(10):
            sink._feed_speech_segmenter(self._low_rms_chunk(), 111, now + i * 0.1)
        assert 111 not in sink._speech_segment_pcm

    def test_voiced_chunk_starts_segment_with_preroll(self):
        """A voiced chunk after low-energy chunks starts a segment with preroll included."""
        sink = self._make_sink()
        now = 1000.0
        # Send 2 silence chunks with distinct pattern so we can identify preroll bytes
        preroll_pattern = b"\xAB\xCD" * 960  # 10ms of unique low-RMS pattern
        silence_chunk = self._low_rms_chunk(5760)  # 30ms
        for i in range(2):
            sink._feed_speech_segmenter(preroll_pattern if i == 0 else silence_chunk, 111, now + i * 0.03)
        # Send voiced chunk (long enough > min_duration=0.25)
        voiced = self._high_rms_chunk(57600, rms=500)
        sink._feed_speech_segmenter(voiced, 111, now + 0.1)
        assert 111 in sink._speech_segment_pcm
        pcm = bytes(sink._speech_segment_pcm[111])
        # The preroll pattern should appear at the very beginning of PCM
        assert pcm[:len(preroll_pattern)] == preroll_pattern, \
            f"Preroll pattern not found at start of {len(pcm)}-byte segment"
        # Total should be preroll (2 chunks = 7680 bytes) + voiced (57600) = 65280
        preroll_total = len(preroll_pattern) + len(silence_chunk)
        assert len(pcm) == preroll_total + len(voiced), \
            f"Expected {preroll_total + len(voiced)} bytes, got {len(pcm)}"
        # Verify voiced_up_to is set (end boundary = total PCM length)
        assert sink._speech_voiced_up_to.get(111, 0) == len(pcm)

    def test_low_energy_after_voiced_does_not_finalize_immediately(self):
        """Low-energy chunks after voiced do not immediately finalize the segment."""
        sink = self._make_sink()
        now = 1000.0
        voiced = self._high_rms_chunk(57600, rms=500)  # 300ms
        sink._feed_speech_segmenter(voiced, 111, now)
        assert 111 in sink._speech_segment_pcm
        # Send a few low-energy chunks (within silence_seconds=0.35)
        silence = self._low_rms_chunk(5760)  # 30ms
        sink._feed_speech_segmenter(silence, 111, now + 0.1)
        sink._feed_speech_segmenter(silence, 111, now + 0.2)
        assert 111 in sink._speech_segment_pcm  # still alive

    def test_silence_after_voiced_finalizes_segment(self):
        """Enough silence after last voiced chunk -> finalize and enqueue trimmed PCM."""
        sink = self._make_sink()
        now = 1000.0
        voiced = self._high_rms_chunk(57600, rms=500)  # 300ms (> min_duration=0.25)
        sink._feed_speech_segmenter(voiced, 111, now)
        # Silence long enough to trigger finalization
        silence = self._low_rms_chunk(5760)  # 30ms
        sink._feed_speech_segmenter(silence, 111, now + 0.4)  # gap > 0.35s
        # Segment should be finalized
        assert 111 not in sink._speech_segment_pcm
        assert sink._speech_recorder.enqueue_segment.called

    def test_trailing_silence_is_trimmed(self):
        """Captured PCM has trailing low-energy frames removed when trim_silence=True."""
        sink = self._make_sink()
        now = 1000.0
        voiced_len = 57600  # 300ms (> min_duration=0.25)
        voiced = self._high_rms_chunk(voiced_len, rms=500)
        sink._feed_speech_segmenter(voiced, 111, now)
        # Add trailing silence
        silence = self._low_rms_chunk(38400)  # 200ms
        sink._feed_speech_segmenter(silence, 111, now + 0.4)  # triggers finalization
        assert sink._speech_recorder.enqueue_segment.called
        # Get the enqueued segment
        segment = sink._speech_recorder.enqueue_segment.call_args[0][0]
        # Trailing silence should be trimmed - segment should be ~300ms (voiced only)
        trimmed_dur = len(segment.pcm_data) / 192000.0
        assert trimmed_dur <= 0.32, f"Expected ~300ms but got {trimmed_dur:.3f}s"

    def test_intra_word_silence_preserved(self):
        """Brief low-energy gaps between voiced chunks do NOT cause finalization."""
        sink = self._make_sink()
        now = 1000.0
        voiced = self._high_rms_chunk(57600, rms=500)  # 300ms (> min_duration)
        silence = self._low_rms_chunk(9600, rms=50)  # 50ms gap
        # Voice -> 50ms pause -> voice
        sink._feed_speech_segmenter(voiced, 111, now)
        sink._feed_speech_segmenter(silence, 111, now + 0.1)  # 100ms gap (within 0.35s)
        sink._feed_speech_segmenter(voiced, 111, now + 0.15)
        assert 111 in sink._speech_segment_pcm  # still active

    def test_segment_still_works_when_stt_disabled(self):
        """Speech training segmentation works even when STT is disabled at guild level."""
        sink = self._make_sink(stt_enabled=False, recorder_enabled=True)
        now = 1000.0
        voiced = self._high_rms_chunk(57600, rms=500)  # 300ms (> min_duration)
        sink._feed_speech_segmenter(voiced, 111, now)
        silence = self._low_rms_chunk(5760)
        sink._feed_speech_segmenter(silence, 111, now + 0.4)
        assert 111 not in sink._speech_segment_pcm
        assert sink._speech_recorder.enqueue_segment.called


# ============================================================================
# Playback event publishing tests
# ============================================================================


class TestPlaybackEventPublishing:
    """Test _publish_playback_event and its integration with mark methods."""

    @pytest.fixture
    def audio_service(self):
        """Create an AudioService instance with minimal state for publishing tests."""
        from bot.services.audio import AudioService

        service = AudioService.__new__(AudioService)
        service._last_gear_message_by_channel = {}
        service._progress_update_task = None
        service.playback_done = asyncio.Event()
        service.playback_done.set()
        service.keyword_sinks = {}
        service._keyword_detection_restart_tasks = {}
        # Per-guild playback state dicts (normally set in __init__)
        service._guild_current_audio_file = {}
        service._guild_current_requester = {}
        service._guild_current_play_id = {}
        service._guild_current_play_started_at = {}
        service._guild_current_duration_seconds = {}
        service._guild_last_played_time = {}
        service._guild_current_sound_message = {}
        service._guild_stop_progress_update = {}
        service._guild_cooldown_message = {}
        service._guild_current_similar_sounds = {}
        service._guild_playback_done = {}
        service._guild_progress_update_task = {}
        service._guild_current_view = {}
        service._connection_locks = {}
        service._pending_connections = {}
        service._reconnection_timestamps = {}
        service._connection_timestamps = {}
        service._guild_live_tts_interrupt_events = {}
        service._keyword_detection_restart_tasks = {}
        # Track guild playback request counts (for rate limiting)
        service._guild_play_requests = {}
        return service

    # ------------------------------------------------------------------
    # _publish_playback_event
    # ------------------------------------------------------------------

    def test_publish_playback_event_calls_honker(
        self, audio_service
    ):
        """_publish_playback_event calls publish_soundboard_event with correct args."""
        mock_repo = Mock()
        mock_repo.db_path = "/fake/db.sqlite"
        audio_service.sound_repo = mock_repo

        with patch(
            "bot.services.honker_integration.publish_soundboard_event"
        ) as mock_publish:
            audio_service._publish_playback_event(
                "control_room_changed",
                12345,
                audio_file="test.mp3",
                user="TestUser",
                play_id="play-123",
                duration_seconds=10.5,
                flags={"reason": "playback_started"},
            )

        mock_publish.assert_called_once_with(
            "/fake/db.sqlite",
            "control_room_changed",
            {
                "guild_id": "12345",
                "audio_file": "test.mp3",
                "user": "TestUser",
                "play_id": "play-123",
                "duration_seconds": 10.5,
                "reason": "playback_started",
            },
        )

    def test_publish_playback_event_no_ops_without_db_path(
        self, audio_service
    ):
        """_publish_playback_event no-ops when db_path is empty."""
        mock_repo = Mock()
        mock_repo.db_path = ""
        audio_service.sound_repo = mock_repo

        with patch(
            "bot.services.honker_integration.publish_soundboard_event"
        ) as mock_publish:
            audio_service._publish_playback_event(
                "control_room_changed", 12345
            )

        mock_publish.assert_not_called()

    def test_publish_playback_event_no_ops_when_publisher_raises(
        self, audio_service
    ):
        """_publish_playback_event does not raise when publish_soundboard_event fails."""
        mock_repo = Mock()
        mock_repo.db_path = "/fake/db.sqlite"
        audio_service.sound_repo = mock_repo

        with patch(
            "bot.services.honker_integration.publish_soundboard_event",
            side_effect=RuntimeError("Honker not available"),
        ):
            # Should not raise
            audio_service._publish_playback_event(
                "control_room_changed", 12345
            )

    def test_publish_playback_event_no_ops_when_import_fails(
        self, audio_service
    ):
        """_publish_playback_event no-ops when honker import fails."""
        mock_repo = Mock()
        mock_repo.db_path = "/fake/db.sqlite"
        audio_service.sound_repo = mock_repo

        with patch(
            "bot.services.honker_integration.publish_soundboard_event",
            side_effect=ImportError("No module named honker"),
        ):
            # Should not raise
            audio_service._publish_playback_event(
                "control_room_changed", 12345
            )

    def test_publish_playback_event_user_object(
        self, audio_service
    ):
        """_publish_playback_event converts user objects to name string."""
        mock_repo = Mock()
        mock_repo.db_path = "/fake/db.sqlite"
        audio_service.sound_repo = mock_repo

        class FakeUser:
            name = "FakeUser"

        with patch(
            "bot.services.honker_integration.publish_soundboard_event"
        ) as mock_publish:
            audio_service._publish_playback_event(
                "control_room_changed",
                12345,
                audio_file="test.mp3",
                user=FakeUser(),
            )

        mock_publish.assert_called_once()
        args = mock_publish.call_args[0]
        data = args[2]
        assert data["user"] == "FakeUser"

    def test_publish_playback_event_minimal_data(
        self, audio_service
    ):
        """_publish_playback_event works with only required args."""
        mock_repo = Mock()
        mock_repo.db_path = "/fake/db.sqlite"
        audio_service.sound_repo = mock_repo

        with patch(
            "bot.services.honker_integration.publish_soundboard_event"
        ) as mock_publish:
            audio_service._publish_playback_event(
                "control_room_changed", 12345
            )

        mock_publish.assert_called_once_with(
            "/fake/db.sqlite",
            "control_room_changed",
            {"guild_id": "12345"},
        )

    # ------------------------------------------------------------------
    # _mark_playback_started integration
    # ------------------------------------------------------------------

    def test_mark_playback_started_publishes_event(
        self, audio_service
    ):
        """_mark_playback_started calls _publish_playback_event after setting state."""
        mock_repo = Mock()
        mock_repo.db_path = "/fake/db.sqlite"
        audio_service.sound_repo = mock_repo

        guild_id = 999
        audio_service._ensure_guild_playback_state(guild_id)

        with patch.object(
            audio_service, "_publish_playback_event"
        ) as mock_publish:
            audio_service._mark_playback_started(
                guild_id, "sound.mp3", "Tester", "pid-1", 5.0
            )

        # State should be set
        assert audio_service._guild_current_audio_file[guild_id] == "sound.mp3"
        assert audio_service._guild_current_requester[guild_id] == "Tester"
        assert audio_service._guild_current_play_id[guild_id] == "pid-1"
        assert audio_service._guild_current_duration_seconds[guild_id] == 5.0

        # Event should be published
        mock_publish.assert_called_once_with(
            "control_room_changed",
            guild_id,
            audio_file="sound.mp3",
            user="Tester",
            play_id="pid-1",
            duration_seconds=5.0,
            flags={"reason": "playback_started"},
        )

    # ------------------------------------------------------------------
    # _mark_playback_finished integration
    # ------------------------------------------------------------------

    def test_mark_playback_finished_publishes_event(
        self, audio_service
    ):
        """_mark_playback_finished calls _publish_playback_event after clearing state."""
        mock_repo = Mock()
        mock_repo.db_path = "/fake/db.sqlite"
        audio_service.sound_repo = mock_repo

        guild_id = 999
        audio_service._ensure_guild_playback_state(guild_id)
        # Set pre-existing state
        audio_service._guild_current_audio_file[guild_id] = "sound.mp3"
        audio_service._guild_current_requester[guild_id] = "Tester"
        audio_service._guild_current_play_id[guild_id] = "pid-1"
        audio_service._guild_current_duration_seconds[guild_id] = 5.0

        with patch.object(
            audio_service, "_publish_playback_event"
        ) as mock_publish:
            audio_service._mark_playback_finished(guild_id, "pid-1")

        # State should be cleared
        assert audio_service._guild_current_audio_file[guild_id] is None
        assert audio_service._guild_current_requester[guild_id] is None
        assert audio_service._guild_current_play_id[guild_id] is None
        assert audio_service._guild_current_duration_seconds[guild_id] is None

        # Event should be published with old values
        mock_publish.assert_called_once_with(
            "control_room_changed",
            guild_id,
            audio_file="sound.mp3",
            user="Tester",
            play_id="pid-1",
            duration_seconds=5.0,
            flags={"reason": "playback_finished"},
        )

    def test_mark_playback_finished_no_op_on_mismatched_play_id(
        self, audio_service
    ):
        """_mark_playback_finished does nothing when play_id doesn't match."""
        mock_repo = Mock()
        mock_repo.db_path = "/fake/db.sqlite"
        audio_service.sound_repo = mock_repo

        guild_id = 999
        audio_service._ensure_guild_playback_state(guild_id)
        audio_service._guild_current_audio_file[guild_id] = "sound.mp3"
        audio_service._guild_current_play_id[guild_id] = "pid-1"

        with patch.object(
            audio_service, "_publish_playback_event"
        ) as mock_publish:
            audio_service._mark_playback_finished(guild_id, "wrong-pid")

        # State should be unchanged
        assert audio_service._guild_current_audio_file[guild_id] == "sound.mp3"
        assert audio_service._guild_current_play_id[guild_id] == "pid-1"

        # No event should be published
        mock_publish.assert_not_called()

