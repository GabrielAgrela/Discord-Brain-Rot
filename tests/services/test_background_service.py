"""
Tests for bot/services/background.py - BackgroundService.
"""

import os
import sys
from collections import namedtuple
from datetime import datetime, timezone
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

    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    def test_calculate_cpu_percentages_uses_delta_samples(
        self, _mock_sound_repo, _mock_action_repo
    ):
        """Ensure CPU percentages are derived from counter deltas, not absolute totals."""
        from bot.services.background import BackgroundService

        service = BackgroundService(
            bot=Mock(),
            audio_service=Mock(),
            sound_service=Mock(),
            behavior=Mock(),
        )
        service._perf_prev_sample_monotonic = 100.0
        service._perf_prev_cpu_counters = {
            "cpu": (1000, 500),
            "cpu0": (500, 250),
        }
        service._perf_prev_process_cpu_ticks = 100
        service._clock_ticks_per_second = 100
        service._cpu_core_count = 4

        metrics = service._calculate_cpu_percentages(
            cpu_counters={
                "cpu": (1100, 540),
                "cpu0": (560, 272),
            },
            process_cpu_ticks=120,
            sample_monotonic=101.0,
        )

        assert metrics["cpu_total_percent"] == 60.0
        assert metrics["cpu_per_core_percent"] == [63.33]
        assert metrics["process_cpu_percent_of_one_core"] == 20.0
        assert metrics["process_cpu_percent_of_total_capacity"] == 5.0

    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    def test_build_performance_snapshot_includes_high_detail_metrics(
        self, _mock_sound_repo, _mock_action_repo
    ):
        """Ensure high-frequency performance snapshot includes rich host/process/runtime fields."""
        from bot.services.background import BackgroundService

        connected_voice_client = Mock()
        connected_voice_client.is_connected.return_value = True
        disconnected_voice_client = Mock()
        disconnected_voice_client.is_connected.return_value = False

        bot = Mock(
            latency=0.321,
            guilds=[
                Mock(voice_client=connected_voice_client),
                Mock(voice_client=disconnected_voice_client),
                Mock(voice_client=None),
            ],
        )

        service = BackgroundService(
            bot=bot,
            audio_service=Mock(),
            sound_service=Mock(),
            behavior=Mock(),
        )
        service._perf_start_monotonic = 10.0
        service._perf_tick_rate_seconds = 0.5
        service._perf_expected_tick_monotonic = 19.9
        service._perf_prev_sample_monotonic = 19.5
        service._perf_prev_cpu_counters = {
            "cpu": (1000, 500),
            "cpu0": (500, 250),
        }
        service._perf_prev_process_cpu_ticks = 100
        service._clock_ticks_per_second = 100
        service._cpu_core_count = 8
        service._perf_prev_network_totals = (1000, 2000)
        service._perf_prev_network_sample_monotonic = 19.5

        disk_usage = namedtuple("disk_usage", ["total", "used", "free"])

        with patch.object(
            service,
            "_read_proc_cpu_counters",
            return_value={"cpu": (1100, 540), "cpu0": (560, 272)},
        ), patch.object(
            service, "_read_proc_process_cpu_ticks", return_value=140
        ), patch.object(
            service,
            "_read_proc_meminfo",
            return_value={"MemTotal": 10000, "MemAvailable": 2500},
        ), patch.object(
            service,
            "_read_proc_status",
            return_value={
                "VmRSS": "4 kB",
                "VmSize": "16 kB",
                "Threads": "7",
                "voluntary_ctxt_switches": "11",
                "nonvoluntary_ctxt_switches": "3",
            },
        ), patch.object(
            service, "_read_proc_network_totals", return_value=(1300, 2600)
        ), patch.object(
            service,
            "_collect_audio_service_metrics",
            return_value={
                "audio_keyword_sink_count": 2,
                "audio_pending_connection_count": 1,
                "audio_active_progress_task_count": 3,
            },
        ), patch(
            "bot.services.background.os.listdir", return_value=["1", "2", "3"]
        ), patch(
            "bot.services.background.resource.getrlimit", return_value=(1024, 4096)
        ), patch(
            "bot.services.background.shutil.disk_usage",
            return_value=disk_usage(1000, 400, 600),
        ), patch(
            "bot.services.background.os.getloadavg", return_value=(1.2, 0.9, 0.8)
        ), patch(
            "bot.services.background.gc.get_count", return_value=(10, 20, 30)
        ), patch(
            "bot.services.background.time.time", return_value=1700000000.0
        ):
            payload = service._build_performance_snapshot(sample_monotonic=20.0)

        assert payload["timestamp_unix"] == 1700000000.0
        assert payload["uptime_seconds"] == 10.0
        assert payload["tick_interval_seconds"] == 0.5
        assert payload["loop_lag_ms"] == 100.0
        assert payload["guild_count"] == 3
        assert payload["connected_voice_clients"] == 1
        assert payload["bot_latency_ms"] == 321.0
        assert payload["cpu_total_percent"] == 60.0
        assert payload["cpu_per_core_percent"] == [63.33]
        assert payload["process_cpu_percent_of_one_core"] == 80.0
        assert payload["process_cpu_percent_of_total_capacity"] == 10.0
        assert payload["memory_total_bytes"] == 10000
        assert payload["memory_available_bytes"] == 2500
        assert payload["memory_used_bytes"] == 7500
        assert payload["memory_used_percent"] == 75.0
        assert payload["process_memory_rss_bytes"] == 4096
        assert payload["process_memory_vms_bytes"] == 16384
        assert payload["process_threads"] == 7
        assert payload["process_voluntary_ctx_switches"] == 11
        assert payload["process_nonvoluntary_ctx_switches"] == 3
        assert payload["fd_open_count"] == 3
        assert payload["fd_limit_soft"] == 1024
        assert payload["fd_limit_hard"] == 4096
        assert payload["disk_total_bytes"] == 1000
        assert payload["disk_used_bytes"] == 400
        assert payload["disk_free_bytes"] == 600
        assert payload["disk_used_percent"] == 40.0
        assert payload["network_total_rx_bytes"] == 1300
        assert payload["network_total_tx_bytes"] == 2600
        assert payload["network_rx_bytes_per_second"] == 600.0
        assert payload["network_tx_bytes_per_second"] == 1200.0
        assert payload["load_avg_1m"] == 1.2
        assert payload["load_avg_5m"] == 0.9
        assert payload["load_avg_15m"] == 0.8
        assert payload["gc_gen0_count"] == 10
        assert payload["gc_gen1_count"] == 20
        assert payload["gc_gen2_count"] == 30
        assert payload["audio_keyword_sink_count"] == 2
        assert payload["audio_pending_connection_count"] == 1
        assert payload["audio_active_progress_task_count"] == 3

    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    def test_weekly_wrapped_default_schedule_is_friday_18_utc(
        self, _mock_sound_repo, _mock_action_repo
    ):
        """Ensure weekly wrapped defaults to Friday 18:00 UTC when env vars are unset."""
        from bot.services.background import BackgroundService

        with patch.dict(
            "os.environ",
            {
                "WEEKLY_WRAPPED_DAY_UTC": "",
                "WEEKLY_WRAPPED_HOUR_UTC": "",
                "WEEKLY_WRAPPED_MINUTE_UTC": "",
            },
            clear=False,
        ):
            service = BackgroundService(
                bot=Mock(),
                audio_service=Mock(),
                sound_service=Mock(),
                behavior=Mock(),
            )

        assert service._weekly_wrapped_day_utc == 4
        assert service._weekly_wrapped_hour_utc == 18
        assert service._weekly_wrapped_minute_utc == 0

    @pytest.mark.asyncio
    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    async def test_weekly_wrapped_scheduler_tick_sends_for_matching_window(
        self, _mock_sound_repo, _mock_action_repo
    ):
        """Ensure weekly scheduler dispatches digests when current UTC time matches the configured window."""
        from bot.services.background import BackgroundService

        guild_one = Mock(name="Guild One")
        guild_two = Mock(name="Guild Two")
        bot = Mock(guilds=[guild_one, guild_two])
        behavior = Mock()
        behavior._weekly_wrapped_service = Mock()
        behavior._weekly_wrapped_service.send_weekly_wrapped = AsyncMock(side_effect=[True, False])

        service = BackgroundService(
            bot=bot,
            audio_service=Mock(),
            sound_service=Mock(),
            behavior=behavior,
        )
        service._weekly_wrapped_enabled = True
        service._weekly_wrapped_day_utc = 5  # Saturday
        service._weekly_wrapped_hour_utc = 12
        service._weekly_wrapped_minute_utc = 0
        service._weekly_wrapped_days = 7

        now_utc = datetime(2026, 2, 21, 12, 10, tzinfo=timezone.utc)
        sent_count = await service._run_weekly_wrapped_scheduler_tick(now_utc=now_utc)

        assert sent_count == 1
        assert behavior._weekly_wrapped_service.send_weekly_wrapped.await_count == 2
        behavior._weekly_wrapped_service.send_weekly_wrapped.assert_any_await(
            guild=guild_one,
            days=7,
            force=False,
            record_delivery=True,
            now_utc=now_utc,
        )
        behavior._weekly_wrapped_service.send_weekly_wrapped.assert_any_await(
            guild=guild_two,
            days=7,
            force=False,
            record_delivery=True,
            now_utc=now_utc,
        )

    @pytest.mark.asyncio
    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    async def test_weekly_wrapped_scheduler_tick_skips_outside_window(
        self, _mock_sound_repo, _mock_action_repo
    ):
        """Ensure weekly scheduler does nothing outside the configured UTC window."""
        from bot.services.background import BackgroundService

        behavior = Mock()
        behavior._weekly_wrapped_service = Mock()
        behavior._weekly_wrapped_service.send_weekly_wrapped = AsyncMock()

        service = BackgroundService(
            bot=Mock(guilds=[Mock(name="Guild")]),
            audio_service=Mock(),
            sound_service=Mock(),
            behavior=behavior,
        )
        service._weekly_wrapped_enabled = True
        service._weekly_wrapped_day_utc = 5  # Saturday
        service._weekly_wrapped_hour_utc = 12
        service._weekly_wrapped_minute_utc = 15

        now_utc = datetime(2026, 2, 21, 12, 14, tzinfo=timezone.utc)
        sent_count = await service._run_weekly_wrapped_scheduler_tick(now_utc=now_utc)

        assert sent_count == 0
        behavior._weekly_wrapped_service.send_weekly_wrapped.assert_not_awaited()


class TestAutoJoinChannels:
    """Tests for BackgroundService._auto_join_channels startup logic."""

    @pytest.mark.asyncio
    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    @patch("bot.services.background.asyncio.sleep", new_callable=AsyncMock)
    async def test_auto_join_skipped_when_autojoin_disabled(
        self, _mock_sleep, _mock_sound_repo, _mock_action_repo
    ):
        """Ensure no voice connection is attempted when autojoin_enabled is False."""
        from bot.services.background import BackgroundService

        guild = Mock()
        guild.voice_client = None
        bot = Mock(guilds=[guild])
        audio_service = Mock()
        audio_service.ensure_voice_connected = AsyncMock()

        service = BackgroundService(
            bot=bot,
            audio_service=audio_service,
            sound_service=Mock(),
            behavior=Mock(),
        )

        settings = Mock(autojoin_enabled=False, default_voice_channel_id=None)
        service.guild_settings_service = Mock()
        service.guild_settings_service.get = Mock(return_value=settings)

        await service._auto_join_channels()

        audio_service.ensure_voice_connected.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    @patch("bot.services.background.asyncio.sleep", new_callable=AsyncMock)
    async def test_auto_join_uses_configured_default_channel(
        self, _mock_sleep, _mock_sound_repo, _mock_action_repo
    ):
        """Ensure bot joins the configured default_voice_channel_id when autojoin is on."""
        from bot.services.background import BackgroundService

        voice_channel = Mock()
        guild = Mock()
        guild.voice_client = None
        guild.get_channel = Mock(return_value=voice_channel)
        bot = Mock(guilds=[guild])
        audio_service = Mock()
        audio_service.ensure_voice_connected = AsyncMock()

        service = BackgroundService(
            bot=bot,
            audio_service=audio_service,
            sound_service=Mock(),
            behavior=Mock(),
        )

        settings = Mock(autojoin_enabled=True, default_voice_channel_id="111222333")
        service.guild_settings_service = Mock()
        service.guild_settings_service.get = Mock(return_value=settings)

        await service._auto_join_channels()

        guild.get_channel.assert_called_once_with(111222333)
        audio_service.ensure_voice_connected.assert_awaited_once_with(voice_channel)

    @pytest.mark.asyncio
    @patch("bot.services.background.ActionRepository")
    @patch("bot.services.background.SoundRepository")
    @patch("bot.services.background.asyncio.sleep", new_callable=AsyncMock)
    async def test_auto_join_falls_back_to_largest_channel_when_no_default(
        self, _mock_sleep, _mock_sound_repo, _mock_action_repo
    ):
        """Ensure bot falls back to largest voice channel when no default is configured."""
        from bot.services.background import BackgroundService

        fallback_channel = Mock()
        guild = Mock()
        guild.voice_client = None
        bot = Mock(guilds=[guild])
        audio_service = Mock()
        audio_service.ensure_voice_connected = AsyncMock()
        audio_service.get_largest_voice_channel = Mock(return_value=fallback_channel)

        service = BackgroundService(
            bot=bot,
            audio_service=audio_service,
            sound_service=Mock(),
            behavior=Mock(),
        )

        settings = Mock(autojoin_enabled=True, default_voice_channel_id=None)
        service.guild_settings_service = Mock()
        service.guild_settings_service.get = Mock(return_value=settings)

        await service._auto_join_channels()

        audio_service.get_largest_voice_channel.assert_called_once_with(guild)
        audio_service.ensure_voice_connected.assert_awaited_once_with(fallback_channel)
