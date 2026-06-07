import asyncio
import gc
import io
import json
import logging
import os
import random
import resource
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
import discord
from discord.ext import tasks
from bot.repositories import (
    SoundRepository,
    ActionRepository,
    WebControlRoomRepository,
    WebSystemStatusRepository,
    SoundImportNotificationRepository,
)
from bot.repositories.keyword import KeywordRepository
from bot.repositories.speech_training import SpeechTrainingRepository
from bot.repositories.app_settings import AppSettingsRepository
from bot.downloaders.sound import SoundDownloader
from bot.services.guild_settings import GuildSettingsService
from bot.services.system_monitor import HostSystemMonitorService
from bot.services.sound_import_notifications import SoundImportNotificationService

logger = logging.getLogger(__name__)


class BackgroundService:
    """
    Service for background tasks like status updates, periodic sound playback,
    and MyInstants scraping.
    """

    RLSTORE_NOTIFY_ACTION = "rlstore_daily_notification_sent"
    RLSTORE_CHANNEL_NAME = "botrl"
    BACKUP_SCHEDULER_ACTION = "scheduled_backup_created"
    # Discord allows 5 presence updates per 20 seconds, so 4s is the fastest safe cadence.
    STATUS_UPDATE_INTERVAL_SECONDS = 4
    
    def __init__(self, bot, audio_service, sound_service, behavior=None):
        self.bot = bot
        self.audio_service = audio_service
        self.sound_service = sound_service
        self.behavior = behavior # BotBehavior instance
        
        # Repositories
        self.sound_repo = SoundRepository()
        self.action_repo = ActionRepository()
        self.web_control_room_repo = WebControlRoomRepository()
        self.web_system_status_repo = WebSystemStatusRepository()
        self.guild_settings_service = GuildSettingsService()

        # Host system monitor (collects host CPU/RAM/top processes)
        # Notification outbox for cross-process import notifications.
        # Lazily initialized in the drain loop so that existing tests that
        # do not expect this dependency are not affected.
        self._sound_import_notification_repo: SoundImportNotificationRepository | None = None
        self._sound_import_notification_service = SoundImportNotificationService()

        self._host_system_monitor = HostSystemMonitorService()
        self._host_monitor_warmed = False
        self._host_monitor_cpu_history: list[dict[str, float]] = []
        self._host_monitor_temp_history: list[dict[str, float]] = []
        self._host_monitor_ram_history: list[dict[str, float]] = []
        self._host_monitor_disk_history: list[dict[str, float]] = []
        self._host_monitor_process_cpu_history: dict[str, list[dict[str, float]]] = {}
        self._host_monitor_process_labels: dict[str, str] = {}
        
        self._started = False
        self._perf_tick_rate_seconds = max(
            0.1, float(os.getenv("PERFORMANCE_MONITOR_TICK_SECONDS", "0.5"))
        )
        self._perf_start_monotonic = time.monotonic()
        self._perf_expected_tick_monotonic: Optional[float] = None
        self._perf_prev_sample_monotonic: Optional[float] = None
        self._perf_prev_cpu_counters: Dict[str, Tuple[int, int]] = {}
        self._perf_prev_process_cpu_ticks: Optional[int] = None
        self._perf_prev_network_totals: Optional[Tuple[int, int]] = None
        self._perf_prev_network_sample_monotonic: Optional[float] = None
        self._perf_loop_lag_warning_ms = max(
            0.0, float(os.getenv("PERFORMANCE_LOOP_LAG_WARNING_MS", "1000"))
        )
        self._perf_last_loop_lag_warning_monotonic = 0.0
        self._clock_ticks_per_second = self._resolve_clock_ticks_per_second()
        self._cpu_core_count = max(1, os.cpu_count() or 1)
        self._weekly_wrapped_enabled = self._env_flag("WEEKLY_WRAPPED_ENABLED", True)
        self._weekly_wrapped_day_utc = self._env_int("WEEKLY_WRAPPED_DAY_UTC", 4, 0, 6)
        self._weekly_wrapped_hour_utc = self._env_int("WEEKLY_WRAPPED_HOUR_UTC", 18, 0, 23)
        self._weekly_wrapped_minute_utc = self._env_int("WEEKLY_WRAPPED_MINUTE_UTC", 0, 0, 59)
        self._weekly_wrapped_days = self._env_int("WEEKLY_WRAPPED_LOOKBACK_DAYS", 7, 1, 30)
        self._rlstore_notify_enabled = self._env_flag("RLSTORE_NOTIFY_ENABLED", True)
        self._rlstore_notify_hour_utc = self._env_int("RLSTORE_NOTIFY_HOUR_UTC", 19, 0, 23)
        self._rlstore_notify_minute_utc = self._env_int("RLSTORE_NOTIFY_MINUTE_UTC", 5, 0, 59)
        self._rlstore_notify_target = (os.getenv("RLSTORE_NOTIFY_TARGET_USERNAME", "sopustos") or "").strip()
        self._backup_scheduler_enabled = self._env_flag("BACKUP_SCHEDULER_ENABLED", True)
        self._backup_scheduler_day_utc = self._env_int("BACKUP_SCHEDULER_DAY_UTC", 4, 0, 6)
        self._backup_scheduler_hour_utc = self._env_int("BACKUP_SCHEDULER_HOUR_UTC", 18, 0, 23)
        self._backup_scheduler_minute_utc = self._env_int("BACKUP_SCHEDULER_MINUTE_UTC", 0, 0, 59)
        self._backup_scheduler_running = False
        self._self_heal_enabled = self._env_flag("BOT_SELF_HEAL_RESTART_ENABLED", True)
        self._gateway_unready_restart_seconds = self._env_int(
            "BOT_GATEWAY_UNREADY_RESTART_SECONDS", 300, 60, 3600
        )
        self._voice_recovery_failure_limit = self._env_int(
            "BOT_VOICE_RECOVERY_FAILURE_RESTARTS", 3, 1, 20
        )
        self._gateway_unready_since: Optional[float] = None
        self._voice_recovery_failures: Dict[int, int] = {}
        self._restart_requested = False

        # Speech training keyword scan (daily/24h)
        self._keyword_scan_daily_enabled = self._env_flag(
            "SPEECH_TRAINING_KEYWORD_SCAN_ENABLED", True
        )
        self._keyword_scan_daily_interval = self._env_int(
            "SPEECH_TRAINING_KEYWORD_SCAN_INTERVAL_SECONDS", 86400, 300, 86400
        )
        self._keyword_scan_workers = self._env_int(
            "SPEECH_TRAINING_KEYWORD_SCAN_WORKERS", 4, 1, 8
        )
        self._keyword_scan_in_progress = False

        # Lazy app settings repository (same DB path as the scan loop).
        self._app_settings_repo: AppSettingsRepository | None = None
        self._app_settings_db_path: str | None = None

        # Control room signature cache for SSE event dedup.
        # Maps guild_id → tuple of significant fields; publish only on change.
        self._ctrl_room_signatures: dict[int, tuple] = {}

    # ── Keyword scan schedule metadata keys ─────────────────────────────

    KEYWORD_SCAN_SETTING_ENABLED = "speech_training_keyword_scan.enabled"
    KEYWORD_SCAN_SETTING_INTERVAL = "speech_training_keyword_scan.interval_seconds"
    KEYWORD_SCAN_SETTING_NEXT_RUN = "speech_training_keyword_scan.next_run_at"
    KEYWORD_SCAN_SETTING_LAST_STARTED = "speech_training_keyword_scan.last_started_at"
    KEYWORD_SCAN_SETTING_LAST_FINISHED = "speech_training_keyword_scan.last_finished_at"
    KEYWORD_SCAN_SETTING_LAST_STATUS = "speech_training_keyword_scan.last_status"
    KEYWORD_SCAN_SETTING_LAST_SUMMARY = "speech_training_keyword_scan.last_summary"
    KEYWORD_SCAN_SETTING_UPDATED_AT = "speech_training_keyword_scan.updated_at"

    def _init_app_settings_repo(self, db_path: str) -> None:
        """Ensure the app settings repo is created for *db_path*."""
        if self._app_settings_repo is not None and self._app_settings_db_path == db_path:
            return
        self._app_settings_db_path = db_path
        self._app_settings_repo = AppSettingsRepository(
            db_path=db_path, use_shared=False,
        )
        self._app_settings_repo.ensure_schema()

    def _persist_keyword_scan_schedule(
        self,
        *,
        enabled: bool | None = None,
        interval_seconds: int | None = None,
        next_run_at: str | None = None,
        last_started_at: str | None = None,
        last_finished_at: str | None = None,
        last_status: str | None = None,
        last_summary: str | None = None,
    ) -> None:
        """Write keyword scan schedule metadata to ``app_settings``.

        Only the provided keyword arguments are persisted; omitted keys
        are not touched.  All values are stored as ISO 8601 UTC strings
        for timestamps.
        """
        if self._app_settings_repo is None:
            return
        settings: dict[str, str] = {}
        now_iso = datetime.now(timezone.utc).isoformat()
        if enabled is not None:
            settings[self.KEYWORD_SCAN_SETTING_ENABLED] = "1" if enabled else "0"
        if interval_seconds is not None:
            settings[self.KEYWORD_SCAN_SETTING_INTERVAL] = str(interval_seconds)
        if next_run_at is not None:
            settings[self.KEYWORD_SCAN_SETTING_NEXT_RUN] = next_run_at
        if last_started_at is not None:
            settings[self.KEYWORD_SCAN_SETTING_LAST_STARTED] = last_started_at
        if last_finished_at is not None:
            settings[self.KEYWORD_SCAN_SETTING_LAST_FINISHED] = last_finished_at
        if last_status is not None:
            settings[self.KEYWORD_SCAN_SETTING_LAST_STATUS] = last_status
        if last_summary is not None:
            settings[self.KEYWORD_SCAN_SETTING_LAST_SUMMARY] = last_summary
        settings[self.KEYWORD_SCAN_SETTING_UPDATED_AT] = now_iso
        try:
            self._app_settings_repo.set_settings(
                settings, updated_by="BackgroundService",
            )
        except Exception as exc:
            logger.error(
                "[BackgroundService] Failed to persist keyword scan metadata: %s",
                exc,
            )

    def start_tasks(self):
        """Schedule tasks to start when the bot is ready."""
        if self._started:
            return
        self._started = True
        
        # Register with bot's on_ready event
        @self.bot.listen('on_ready')
        async def on_ready_start_tasks():
            if not self.update_bot_status_loop.is_running():
                self.update_bot_status_loop.start()
            if not self.play_sound_periodically_loop.is_running():
                self.play_sound_periodically_loop.start()
            if not self.scrape_sounds_loop.is_running():
                self.scrape_sounds_loop.start()
            if not self.keyword_detection_health_check.is_running():
                self.keyword_detection_health_check.start()
            if not self.check_voice_activity_loop.is_running():
                self.check_voice_activity_loop.start()
            if not self.ensure_last_message_controls_button_loop.is_running():
                self.ensure_last_message_controls_button_loop.start()
            if not self.performance_telemetry_loop.is_running():
                self.performance_telemetry_loop.change_interval(
                    seconds=self._perf_tick_rate_seconds
                )
                self.performance_telemetry_loop.start()
            if not self.web_control_room_status_loop.is_running():
                self.web_control_room_status_loop.start()
            if not self.web_system_monitor_status_loop.is_running():
                self.web_system_monitor_status_loop.start()
            if self._weekly_wrapped_enabled and not self.weekly_wrapped_scheduler_loop.is_running():
                self.weekly_wrapped_scheduler_loop.start()
            if self._rlstore_notify_enabled and not self.rlstore_notification_loop.is_running():
                self.rlstore_notification_loop.start()
            if self._backup_scheduler_enabled and not self.backup_scheduler_loop.is_running():
                self.backup_scheduler_loop.start()
            if not self.favorite_watcher_loop.is_running():
                self.favorite_watcher_loop.start()
            if self._self_heal_enabled and not self.bot_self_heal_watchdog_loop.is_running():
                self.bot_self_heal_watchdog_loop.start()
            if not self.sound_import_notification_drain_loop.is_running():
                self.sound_import_notification_drain_loop.start()
            if self._honker_sound_import_listener_task is None:
                loop = asyncio.get_event_loop()
                self._honker_sound_import_listener_task = loop.create_task(
                    self._start_honker_sound_import_listener()
                )
            if self._keyword_scan_daily_enabled and not self.speech_training_keyword_scan_loop.is_running():
                self.speech_training_keyword_scan_loop.change_interval(
                    seconds=self._keyword_scan_daily_interval
                )
                self.speech_training_keyword_scan_loop.start()

            # Persist initial keyword scan schedule metadata
            try:
                self._init_app_settings_repo(str(self._resolve_db_path()))
                if self._keyword_scan_daily_enabled:
                    next_run = datetime.now(timezone.utc).isoformat()
                    self._persist_keyword_scan_schedule(
                        enabled=True,
                        interval_seconds=self._keyword_scan_daily_interval,
                        next_run_at=next_run,
                    )
                else:
                    self._persist_keyword_scan_schedule(
                        enabled=False,
                        interval_seconds=self._keyword_scan_daily_interval,
                        next_run_at=None,
                    )
            except Exception as exc:
                logger.error(
                    "[BackgroundService] Failed to persist initial keyword scan metadata: %s",
                    exc,
                )
            
            asyncio.create_task(self._auto_join_channels())
            print("[BackgroundService] Background tasks started.")

    async def _auto_join_channels(self):
        """Auto-join configured voice channels on startup."""
        await asyncio.sleep(3)  # Give the bot a moment to settle before joining
        for guild in self.bot.guilds:
            try:
                settings = self.guild_settings_service.get(guild.id)
                if not settings or not settings.autojoin_enabled:
                    continue
                
                # Check if already connected
                if guild.voice_client and guild.voice_client.is_connected():
                    continue

                target_channel = None
                if settings.default_voice_channel_id:
                    target_channel = guild.get_channel(int(settings.default_voice_channel_id))
                
                if not target_channel:
                    # Fallback to largest channel
                    target_channel = self.audio_service.get_largest_voice_channel(guild)
                
                if target_channel:
                    print(f"[BackgroundService] Auto-joining '{target_channel.name}' in '{guild.name}'")
                    await self.audio_service.ensure_voice_connected(target_channel)
            except Exception as e:
                print(f"[BackgroundService] Failed to auto-join in '{guild.name}': {e}")


    @staticmethod
    def _resolve_clock_ticks_per_second() -> int:
        """Return platform clock ticks/second used in `/proc/self/stat`."""
        try:
            return int(os.sysconf("SC_CLK_TCK"))
        except (AttributeError, ValueError):
            return 100

    @staticmethod
    def _env_flag(name: str, default: bool) -> bool:
        """Parse a boolean environment variable with sane defaults."""
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
        """Parse a bounded integer environment variable."""
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            parsed = int(raw.strip())
        except ValueError:
            return default
        return max(minimum, min(parsed, maximum))

    def _request_self_restart(self, reason: str) -> None:
        """Terminate the bot process so Docker restart policy can recover cleanly."""
        if self._restart_requested:
            return
        self._restart_requested = True
        logger.critical("[BackgroundService] Self-heal restart requested: %s", reason)
        try:
            for handler in logging.getLogger().handlers:
                handler.flush()
        except Exception:
            pass
        os._exit(70)

    def _record_voice_recovery_failure(self, guild_id: int, guild_name: str, error: Exception) -> None:
        """Track repeated voice recovery failures and restart after the configured limit."""
        failures = self._voice_recovery_failures.get(guild_id, 0) + 1
        self._voice_recovery_failures[guild_id] = failures
        logger.warning(
            "[BackgroundService] Voice recovery failure %s/%s in %s: %s",
            failures,
            self._voice_recovery_failure_limit,
            guild_name,
            error,
        )
        if self._self_heal_enabled and failures >= self._voice_recovery_failure_limit:
            self._request_self_restart(
                f"voice recovery failed {failures} times in {guild_name}: {error}"
            )

    def _clear_voice_recovery_failures(self, guild_id: int) -> None:
        """Reset the voice recovery failure counter after successful recovery."""
        self._voice_recovery_failures.pop(guild_id, None)

    @staticmethod
    def _read_proc_cpu_counters() -> Dict[str, Tuple[int, int]]:
        """Read `/proc/stat` CPU counters as `{cpu_label: (total, idle)}`."""
        counters: Dict[str, Tuple[int, int]] = {}
        try:
            with open("/proc/stat", "r", encoding="utf-8") as proc_stat:
                for raw_line in proc_stat:
                    if not raw_line.startswith("cpu"):
                        break
                    parts = raw_line.split()
                    if len(parts) < 6:
                        continue
                    label = parts[0]
                    values = [int(value) for value in parts[1:] if value.isdigit()]
                    if not values:
                        continue
                    total = sum(values)
                    idle = values[3] + (values[4] if len(values) > 4 else 0)
                    counters[label] = (total, idle)
        except Exception:
            return {}
        return counters

    @staticmethod
    def _read_proc_process_cpu_ticks() -> Optional[int]:
        """Read process `(utime + stime)` clock ticks from `/proc/self/stat`."""
        try:
            with open("/proc/self/stat", "r", encoding="utf-8") as proc_stat:
                fields = proc_stat.read().split()
            if len(fields) <= 15:
                return None
            return int(fields[13]) + int(fields[14])
        except Exception:
            return None

    @staticmethod
    def _read_proc_meminfo() -> Dict[str, int]:
        """Read `/proc/meminfo` values in bytes keyed by field name."""
        meminfo: Dict[str, int] = {}
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as mem_file:
                for line in mem_file:
                    if ":" not in line:
                        continue
                    key, raw_value = line.split(":", 1)
                    tokens = raw_value.strip().split()
                    if not tokens:
                        continue
                    try:
                        value = int(tokens[0])
                    except ValueError:
                        continue
                    # meminfo values are usually kB, normalize to bytes.
                    meminfo[key] = value * 1024
        except Exception:
            return {}
        return meminfo

    @staticmethod
    def _read_proc_status() -> Dict[str, str]:
        """Read `/proc/self/status` values keyed by field name."""
        status_map: Dict[str, str] = {}
        try:
            with open("/proc/self/status", "r", encoding="utf-8") as status_file:
                for line in status_file:
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    status_map[key] = value.strip()
        except Exception:
            return {}
        return status_map

    @staticmethod
    def _read_proc_network_totals() -> Tuple[int, int]:
        """Read cumulative RX/TX bytes across all interfaces from `/proc/net/dev`."""
        total_rx = 0
        total_tx = 0
        try:
            with open("/proc/net/dev", "r", encoding="utf-8") as net_file:
                lines = net_file.readlines()[2:]
            for line in lines:
                if ":" not in line:
                    continue
                _, data = line.split(":", 1)
                values = data.split()
                if len(values) < 9:
                    continue
                total_rx += int(values[0])
                total_tx += int(values[8])
        except Exception:
            return 0, 0
        return total_rx, total_tx

    @staticmethod
    def _parse_kib_field(value: Optional[str]) -> Optional[int]:
        """Parse `/proc/*/status` memory values (e.g. `12345 kB`) into bytes."""
        if not value:
            return None
        parts = value.split()
        if not parts:
            return None
        try:
            return int(parts[0]) * 1024
        except ValueError:
            return None

    @staticmethod
    def _safe_float(value: Optional[float], decimals: int = 2) -> Optional[float]:
        """Round float values consistently while preserving None."""
        if value is None:
            return None
        return round(float(value), decimals)

    @staticmethod
    def _safe_percent(numerator: float, denominator: float) -> Optional[float]:
        """Return percentage or None when denominator is not positive."""
        if denominator <= 0:
            return None
        return (numerator / denominator) * 100.0

    def _calculate_cpu_percentages(
        self,
        cpu_counters: Dict[str, Tuple[int, int]],
        process_cpu_ticks: Optional[int],
        sample_monotonic: float,
    ) -> Dict[str, Any]:
        """Calculate system/process CPU percentages from `/proc` deltas."""
        elapsed = None
        if self._perf_prev_sample_monotonic is not None:
            elapsed = sample_monotonic - self._perf_prev_sample_monotonic

        cpu_total_percent = None
        cpu_per_core_percent: list[float] = []
        process_cpu_percent_of_one_core = None
        process_cpu_percent_of_total_capacity = None

        if elapsed and elapsed > 0:
            for label, counters in sorted(cpu_counters.items()):
                previous = self._perf_prev_cpu_counters.get(label)
                if previous is None:
                    continue
                delta_total = counters[0] - previous[0]
                delta_idle = counters[1] - previous[1]
                if delta_total <= 0:
                    continue
                percent = self._safe_percent(delta_total - delta_idle, delta_total)
                if percent is None:
                    continue
                if label == "cpu":
                    cpu_total_percent = percent
                elif label.startswith("cpu"):
                    cpu_per_core_percent.append(percent)

            if (
                process_cpu_ticks is not None
                and self._perf_prev_process_cpu_ticks is not None
                and self._clock_ticks_per_second > 0
            ):
                process_ticks_delta = process_cpu_ticks - self._perf_prev_process_cpu_ticks
                if process_ticks_delta >= 0:
                    process_cpu_seconds = process_ticks_delta / self._clock_ticks_per_second
                    process_cpu_percent_of_one_core = self._safe_percent(
                        process_cpu_seconds,
                        elapsed,
                    )
                    if process_cpu_percent_of_one_core is not None:
                        process_cpu_percent_of_total_capacity = (
                            process_cpu_percent_of_one_core / self._cpu_core_count
                        )

        self._perf_prev_cpu_counters = cpu_counters
        self._perf_prev_process_cpu_ticks = process_cpu_ticks
        self._perf_prev_sample_monotonic = sample_monotonic

        return {
            "cpu_total_percent": self._safe_float(cpu_total_percent),
            "cpu_per_core_percent": [
                round(value, 2) for value in cpu_per_core_percent
            ],
            "process_cpu_percent_of_one_core": self._safe_float(
                process_cpu_percent_of_one_core
            ),
            "process_cpu_percent_of_total_capacity": self._safe_float(
                process_cpu_percent_of_total_capacity
            ),
        }

    def _calculate_network_rates(
        self,
        total_rx_bytes: int,
        total_tx_bytes: int,
        sample_monotonic: float,
    ) -> Dict[str, Any]:
        """Calculate aggregate network throughput from cumulative byte counters."""
        rx_bytes_per_second = None
        tx_bytes_per_second = None
        if (
            self._perf_prev_network_totals is not None
            and self._perf_prev_network_sample_monotonic is not None
        ):
            elapsed = sample_monotonic - self._perf_prev_network_sample_monotonic
            if elapsed > 0:
                rx_bytes_per_second = (
                    total_rx_bytes - self._perf_prev_network_totals[0]
                ) / elapsed
                tx_bytes_per_second = (
                    total_tx_bytes - self._perf_prev_network_totals[1]
                ) / elapsed

        self._perf_prev_network_totals = (total_rx_bytes, total_tx_bytes)
        self._perf_prev_network_sample_monotonic = sample_monotonic

        return {
            "network_total_rx_bytes": total_rx_bytes,
            "network_total_tx_bytes": total_tx_bytes,
            "network_rx_bytes_per_second": self._safe_float(rx_bytes_per_second),
            "network_tx_bytes_per_second": self._safe_float(tx_bytes_per_second),
        }

    def _compute_loop_lag_ms(self, sample_monotonic: float) -> float:
        """Estimate event-loop lag by comparing expected and actual loop wakeup times."""
        if self._perf_expected_tick_monotonic is None:
            self._perf_expected_tick_monotonic = sample_monotonic
            return 0.0

        elapsed = sample_monotonic - self._perf_expected_tick_monotonic
        self._perf_expected_tick_monotonic = sample_monotonic
        lag = max(0.0, elapsed - self._perf_tick_rate_seconds)
        return lag * 1000.0

    def _collect_audio_service_metrics(self) -> Dict[str, Any]:
        """Collect runtime metrics from AudioService internals when available."""
        metrics: Dict[str, Any] = {}
        try:
            keyword_sinks = getattr(self.audio_service, "keyword_sinks", {})
            metrics["audio_keyword_sink_count"] = len(keyword_sinks)
        except Exception:
            metrics["audio_keyword_sink_count"] = None

        try:
            pending_connections = getattr(self.audio_service, "_pending_connections", {})
            metrics["audio_pending_connection_count"] = len(
                [task for task in pending_connections.values() if not task.done()]
            )
        except Exception:
            metrics["audio_pending_connection_count"] = None

        try:
            progress_tasks = getattr(
                self.audio_service, "_guild_progress_update_task", {}
            )
            metrics["audio_active_progress_task_count"] = len(
                [task for task in progress_tasks.values() if task and not task.done()]
            )
        except Exception:
            metrics["audio_active_progress_task_count"] = None

        return metrics

    def _build_performance_snapshot(self, sample_monotonic: float) -> Dict[str, Any]:
        """Build a high-detail telemetry payload for performance logging."""
        cpu_counters = self._read_proc_cpu_counters()
        process_cpu_ticks = self._read_proc_process_cpu_ticks()
        cpu_metrics = self._calculate_cpu_percentages(
            cpu_counters=cpu_counters,
            process_cpu_ticks=process_cpu_ticks,
            sample_monotonic=sample_monotonic,
        )

        meminfo = self._read_proc_meminfo()
        mem_total = meminfo.get("MemTotal")
        mem_available = meminfo.get("MemAvailable")
        mem_used = None
        mem_used_percent = None
        if mem_total is not None and mem_available is not None:
            mem_used = mem_total - mem_available
            mem_used_percent = self._safe_percent(mem_used, mem_total)

        process_status = self._read_proc_status()
        process_rss = self._parse_kib_field(process_status.get("VmRSS"))
        process_vms = self._parse_kib_field(process_status.get("VmSize"))
        process_threads = process_status.get("Threads")
        process_ctx_switches_voluntary = process_status.get("voluntary_ctxt_switches")
        process_ctx_switches_nonvoluntary = process_status.get(
            "nonvoluntary_ctxt_switches"
        )

        fd_open = None
        try:
            fd_open = len(os.listdir("/proc/self/fd"))
        except Exception:
            fd_open = None

        fd_limit_soft = None
        fd_limit_hard = None
        try:
            fd_limit_soft, fd_limit_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        except Exception:
            fd_limit_soft = None
            fd_limit_hard = None

        disk_total = None
        disk_used = None
        disk_free = None
        disk_used_percent = None
        try:
            disk_usage = shutil.disk_usage("/")
            disk_total = disk_usage.total
            disk_used = disk_usage.used
            disk_free = disk_usage.free
            disk_used_percent = self._safe_percent(disk_used, disk_total)
        except Exception:
            pass

        load_avg_1m = None
        load_avg_5m = None
        load_avg_15m = None
        try:
            load_avg_1m, load_avg_5m, load_avg_15m = os.getloadavg()
        except (AttributeError, OSError):
            pass

        network_rx_total, network_tx_total = self._read_proc_network_totals()
        network_metrics = self._calculate_network_rates(
            total_rx_bytes=network_rx_total,
            total_tx_bytes=network_tx_total,
            sample_monotonic=sample_monotonic,
        )

        guild_count = len(getattr(self.bot, "guilds", []))
        connected_voice_clients = 0
        for guild in getattr(self.bot, "guilds", []):
            voice_client = getattr(guild, "voice_client", None)
            if voice_client and voice_client.is_connected():
                connected_voice_clients += 1

        asyncio_task_total = None
        asyncio_task_pending = None
        try:
            loop = asyncio.get_running_loop()
            all_tasks = asyncio.all_tasks(loop=loop)
            asyncio_task_total = len(all_tasks)
            asyncio_task_pending = len([task for task in all_tasks if not task.done()])
        except Exception:
            pass

        gc_counts = gc.get_count()
        loop_lag_ms = self._compute_loop_lag_ms(sample_monotonic)

        payload: Dict[str, Any] = {
            "timestamp_unix": round(time.time(), 3),
            "uptime_seconds": self._safe_float(
                sample_monotonic - self._perf_start_monotonic, decimals=3
            ),
            "tick_interval_seconds": self._safe_float(
                self._perf_tick_rate_seconds, decimals=3
            ),
            "loop_lag_ms": self._safe_float(loop_lag_ms, decimals=3),
            "guild_count": guild_count,
            "connected_voice_clients": connected_voice_clients,
            "bot_latency_ms": self._safe_float(
                getattr(self.bot, "latency", 0.0) * 1000.0, decimals=3
            ),
            "cpu_core_count": self._cpu_core_count,
            "load_avg_1m": self._safe_float(load_avg_1m),
            "load_avg_5m": self._safe_float(load_avg_5m),
            "load_avg_15m": self._safe_float(load_avg_15m),
            "memory_total_bytes": mem_total,
            "memory_available_bytes": mem_available,
            "memory_used_bytes": mem_used,
            "memory_used_percent": self._safe_float(mem_used_percent),
            "process_memory_rss_bytes": process_rss,
            "process_memory_vms_bytes": process_vms,
            "process_threads": int(process_threads) if process_threads else None,
            "process_voluntary_ctx_switches": (
                int(process_ctx_switches_voluntary)
                if process_ctx_switches_voluntary
                else None
            ),
            "process_nonvoluntary_ctx_switches": (
                int(process_ctx_switches_nonvoluntary)
                if process_ctx_switches_nonvoluntary
                else None
            ),
            "fd_open_count": fd_open,
            "fd_limit_soft": fd_limit_soft,
            "fd_limit_hard": fd_limit_hard,
            "disk_total_bytes": disk_total,
            "disk_used_bytes": disk_used,
            "disk_free_bytes": disk_free,
            "disk_used_percent": self._safe_float(disk_used_percent),
            "asyncio_task_total": asyncio_task_total,
            "asyncio_task_pending": asyncio_task_pending,
            "gc_gen0_count": gc_counts[0],
            "gc_gen1_count": gc_counts[1],
            "gc_gen2_count": gc_counts[2],
        }
        payload.update(cpu_metrics)
        payload.update(network_metrics)
        payload.update(self._collect_audio_service_metrics())
        return payload

    @staticmethod
    def _is_message_from_bot(message: discord.Message, bot_user: Optional[discord.User]) -> bool:
        """Return True when a message was authored by this bot."""
        if not message or not bot_user:
            return False
        return message.author == bot_user

    @staticmethod
    def _find_available_component_row(
        message: discord.Message,
        view: discord.ui.View,
    ) -> Optional[int]:
        """Find an available row using live message component widths first."""
        rows = getattr(message, "components", None) or []
        if rows:
            for row_index, row in enumerate(rows):
                row_children = getattr(row, "children", None) or []
                if len(row_children) < 5:
                    return row_index
            if len(rows) < 5:
                return len(rows)
            return None

        # Fallback when message.components is unavailable.
        row_counts = {row: 0 for row in range(5)}
        for item in view.children:
            row = getattr(item, "row", None)
            if row is None:
                continue
            if row in row_counts:
                row_counts[row] += 1

        for row, count in row_counts.items():
            if count < 5:
                return row
        return None

    @staticmethod
    def _message_components_have_send_controls_button(message: discord.Message) -> bool:
        """Return True when raw message components include the inline controls button."""
        rows = getattr(message, "components", None) or []
        for row in rows:
            components = getattr(row, "children", None) or getattr(row, "components", None) or []
            for component in components:
                custom_id = getattr(component, "custom_id", None)
                if custom_id == "send_controls_button":
                    return True

                emoji = getattr(component, "emoji", None)
                if emoji is None:
                    continue
                emoji_name = getattr(emoji, "name", None) or str(emoji)
                emoji_normalized = emoji_name.replace("\ufe0f", "").replace("\ufe0e", "").strip()
                label = (getattr(component, "label", "") or "").strip()
                if "⚙" in emoji_normalized and label == "":
                    return True

        return False

    @staticmethod
    def _view_has_send_controls_button(view: discord.ui.View) -> bool:
        """Return True when a reconstructed view already contains a gear button."""
        for item in getattr(view, "children", []):
            custom_id = getattr(item, "custom_id", None)
            if isinstance(custom_id, str) and "send_controls_button" in custom_id:
                return True

            emoji = getattr(item, "emoji", None)
            if emoji is None:
                continue

            emoji_text = (getattr(emoji, "name", None) or str(emoji)).replace("\ufe0f", "").replace("\ufe0e", "").strip()
            label = (getattr(item, "label", "") or "").strip()
            if "⚙" in emoji_text and label == "":
                return True
        return False

    async def _add_controls_button_to_message(self, message: discord.Message) -> bool:
        """Attach an inline controls button to a message if component space allows."""
        if self._message_components_have_send_controls_button(message):
            return True

        try:
            view = discord.ui.View.from_message(message)
        except Exception:
            return False

        if self._view_has_send_controls_button(view):
            return True

        row = self._find_available_component_row(message, view)
        if row is None:
            return False

        style = discord.ButtonStyle.primary
        message_service = getattr(self.audio_service, "message_service", None)
        if message_service and hasattr(message_service, "_resolve_default_inline_controls_style"):
            message_format = "embed" if message.embeds else "image"
            embed_color = message.embeds[0].color if message.embeds else None
            style = message_service._resolve_default_inline_controls_style(
                message_format=message_format,
                color=embed_color,
                image_border_color=None,
            )

        from bot.ui.buttons.sounds import SendControlsButton
        try:
            view.add_item(SendControlsButton(style=style, row=row))
            await message.edit(view=view)
            return True
        except Exception as e:
            print(f"[BackgroundService] Failed to add controls button: {e}")
            return False

    async def _ensure_controls_button_on_last_bot_message_for_guild(self, guild: discord.Guild) -> None:
        """Keep exactly one recent inline controls button on eligible bot messages."""
        message_service = getattr(self.audio_service, "message_service", None)
        if not message_service:
            return

        channel = message_service.get_bot_channel(guild)
        if not channel:
            return

        recent_messages = []
        async for message in channel.history(limit=10):
            recent_messages.append(message)

        if not recent_messages:
            return

        bot_messages = [
            message
            for message in recent_messages
            if self._is_message_from_bot(message, self.bot.user)
        ]
        if not bot_messages:
            return

        def _message_has_controls(message: discord.Message) -> bool:
            if hasattr(self.audio_service, "_message_has_send_controls_button"):
                try:
                    return bool(self.audio_service._message_has_send_controls_button(message))
                except Exception:
                    return self._message_components_have_send_controls_button(message)
            return self._message_components_have_send_controls_button(message)

        # Pick the newest non-controls-menu bot message first.
        target_candidates = bot_messages
        if hasattr(self.audio_service, "_is_controls_menu_message"):
            target_candidates = [
                message for message in bot_messages
                if not self.audio_service._is_controls_menu_message(message)
            ]
        if not target_candidates:
            return

        keeper = None
        for candidate in target_candidates:
            if _message_has_controls(candidate):
                keeper = candidate
                break

        if keeper is None:
            for target_message in target_candidates:
                added = await self._add_controls_button_to_message(target_message)
                if added:
                    keeper = target_message
                    break

        if not keeper:
            return

        if hasattr(self.audio_service, "_remove_send_controls_button_from_message"):
            for candidate in target_candidates:
                if candidate.id == keeper.id:
                    continue
                if _message_has_controls(candidate):
                    await self.audio_service._remove_send_controls_button_from_message(candidate)

    async def _notify_scraper_start(self) -> None:
        """Send a scraper start notification to the bot channel."""
        if not self.behavior:
            return

        try:
            await self.behavior.send_message(
                title="🔍 MyInstants scraper started",
                message_format="image",
                image_requester="MyInstants Scraper",
                image_show_footer=False,
                image_show_sound_icon=False,
                image_border_color="#ED4245",
            )
        except Exception as e:
            print(f"[BackgroundService] Failed to send scraper start message: {e}")

    async def _notify_scraper_complete(self, summary: dict[str, Any] | None) -> None:
        """Send a short scraper completion summary to the bot channel."""
        if not self.behavior:
            return

        summary = summary or {}
        countries_scanned = summary.get("countries_scanned", 0)
        total_sounds_seen = summary.get("total_sounds_seen", 0)
        detected = summary.get("new_sounds_detected", 0)
        added = summary.get("sounds_added", 0)
        invalid = summary.get("sounds_invalid", 0)
        scrape_errors = summary.get("scrape_errors", 0)
        duration_seconds = summary.get("duration_seconds", 0)

        description = (
            f"{countries_scanned} sites checked in {duration_seconds}s | "
            f"{total_sounds_seen} sounds seen | "
            f"{detected} new sounds found ({added} downloaded) | "
            f"{invalid} skipped/invalid"
        )
        if scrape_errors:
            description += f" | {scrape_errors} site errors"

        try:
            await self.behavior.send_message(
                title="✅ MyInstants scraper finished",
                description=description,
                message_format="image",
                image_requester="MyInstants Scraper",
                image_show_footer=False,
                image_show_sound_icon=False,
                image_border_color="#ED4245",
            )
        except Exception as e:
            print(f"[BackgroundService] Failed to send scraper completion message: {e}")

    async def _notify_scraper_failure(self, error: Exception) -> None:
        """Send a short scraper failure summary to the bot channel."""
        if not self.behavior:
            return

        error_text = str(error).strip() or "Unknown error"
        if len(error_text) > 180:
            error_text = f"{error_text[:177]}..."

        try:
            await self.behavior.send_message(
                title="⚠️ MyInstants scraper failed",
                description=error_text,
                message_format="image",
                image_requester="MyInstants Scraper",
                image_show_footer=False,
                image_show_sound_icon=False,
                image_border_color="#ED4245",
            )
        except Exception as notify_error:
            print(f"[BackgroundService] Failed to send scraper failure message: {notify_error}")

    def _is_weekly_wrapped_window(self, now_utc: datetime) -> bool:
        """Return True when the current UTC time matches the configured send window."""
        if now_utc.weekday() != self._weekly_wrapped_day_utc:
            return False
        if now_utc.hour != self._weekly_wrapped_hour_utc:
            return False
        return now_utc.minute >= self._weekly_wrapped_minute_utc

    async def _run_weekly_wrapped_scheduler_tick(
        self,
        now_utc: Optional[datetime] = None,
    ) -> int:
        """
        Execute one scheduler tick for weekly wrapped delivery.

        Args:
            now_utc: Optional injected UTC time for deterministic tests.

        Returns:
            Number of guilds where a digest was sent.
        """
        if not self._weekly_wrapped_enabled or not self.behavior:
            return 0

        weekly_service = getattr(self.behavior, "_weekly_wrapped_service", None)
        if weekly_service is None:
            return 0

        now_utc = now_utc or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        if not self._is_weekly_wrapped_window(now_utc):
            return 0

        sent_count = 0
        for guild in self.bot.guilds:
            try:
                sent = await weekly_service.send_weekly_wrapped(
                    guild=guild,
                    days=self._weekly_wrapped_days,
                    force=False,
                    record_delivery=True,
                    now_utc=now_utc,
                )
                if sent:
                    sent_count += 1
            except Exception as e:
                print(f"[BackgroundService] Weekly wrapped failed for guild '{guild.name}': {e}")

        return sent_count

    def _is_rlstore_notify_window(self, now_utc: datetime) -> bool:
        """Return True when the current UTC time matches the daily rlstore send window."""
        if now_utc.hour != self._rlstore_notify_hour_utc:
            return False
        return now_utc.minute >= self._rlstore_notify_minute_utc

    @staticmethod
    def _rlstore_notify_key(now_utc: datetime) -> str:
        """Return a stable per-day key for rlstore scheduler dedupe."""
        return f"rlstore:{now_utc.date().isoformat()}"

    def _is_backup_window(self, now_utc: datetime) -> bool:
        """Return True when the current UTC time matches the configured weekly backup window."""
        if now_utc.weekday() != self._backup_scheduler_day_utc:
            return False
        if now_utc.hour != self._backup_scheduler_hour_utc:
            return False
        return now_utc.minute >= self._backup_scheduler_minute_utc

    @staticmethod
    def _backup_notify_key(now_utc: datetime) -> str:
        """Return a stable per-day key for backup scheduler dedupe."""
        return f"backup:{now_utc.date().isoformat()}"

    async def _run_backup_scheduler_tick(
        self,
        now_utc: Optional[datetime] = None,
    ) -> int:
        """
        Execute one scheduler tick for the weekly backup.

        Args:
            now_utc: Optional injected UTC time for deterministic tests.

        Returns:
            1 if a backup was created, 0 otherwise.
        """
        if not self._backup_scheduler_enabled or not self.behavior:
            return 0
        if self._backup_scheduler_running:
            return 0

        backup_service = getattr(self.behavior, "_backup_service", None)
        if backup_service is None:
            return 0

        now_utc = now_utc or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        if not self._is_backup_window(now_utc):
            return 0

        notify_key = self._backup_notify_key(now_utc)
        if self.action_repo.has_action_for_target(
            self.BACKUP_SCHEDULER_ACTION,
            notify_key,
        ):
            return 0

        guild = next(iter(self.bot.guilds), None)
        self._backup_scheduler_running = True
        try:
            await backup_service.perform_scheduled_backup(guild=guild)
            self.action_repo.insert(
                "scheduler",
                self.BACKUP_SCHEDULER_ACTION,
                notify_key,
            )
            return 1
        except Exception as exc:
            logger.error(
                "[BackgroundService] Scheduled backup failed: %s",
                exc,
                exc_info=True,
            )
            return 0
        finally:
            self._backup_scheduler_running = False

    def _resolve_rlstore_notify_member(self, guild: discord.Guild) -> Optional[discord.Member]:
        """Resolve the configured rlstore notification target to a guild member."""
        target = self._rlstore_notify_target.strip()
        if not target:
            return None

        if target.isdigit():
            return guild.get_member(int(target))

        target_lower = target.lower()
        for member in guild.members:
            candidates = {
                (member.name or "").lower(),
                (member.display_name or "").lower(),
                (getattr(member, "global_name", None) or "").lower(),
            }
            if target_lower in candidates:
                return member
        return None

    async def _run_rlstore_notification_tick(
        self,
        now_utc: Optional[datetime] = None,
    ) -> int:
        """
        Execute one scheduler tick for the daily rlstore notification.

        Args:
            now_utc: Optional injected UTC time for deterministic tests.

        Returns:
            Number of guilds where the notification was sent.
        """
        if not self._rlstore_notify_enabled or not self.behavior:
            return 0

        rlstore_service = getattr(self.behavior, "_rocket_league_store_service", None)
        message_service = getattr(self.behavior, "_message_service", None)
        image_generator = getattr(getattr(self.behavior, "_audio_service", None), "image_generator", None)
        if rlstore_service is None or message_service is None or image_generator is None:
            return 0

        now_utc = now_utc or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        if not self._is_rlstore_notify_window(now_utc):
            return 0

        try:
            snapshot = await rlstore_service.fetch_store_snapshot()
        except Exception as exc:
            logger.error("[BackgroundService] Failed to fetch rlstore snapshot: %s", exc, exc_info=True)
            return 0

        notify_key = self._rlstore_notify_key(now_utc)
        merc_status = rlstore_service.build_merc_status_text(snapshot)
        website_text = rlstore_service.build_source_url_text()
        from bot.ui import RocketLeagueStoreView

        sent_count = 0
        for guild in self.bot.guilds:
            try:
                if self.action_repo.has_action_for_target(
                    self.RLSTORE_NOTIFY_ACTION,
                    notify_key,
                    guild_id=guild.id,
                    include_global=False,
                ):
                    continue

                channel = self._get_rlstore_channel(guild, message_service)
                if channel is None:
                    continue

                target_member = self._resolve_rlstore_notify_member(guild)
                if target_member is not None:
                    content = (
                        f"{target_member.mention} Rocket League store refreshed. "
                        f"{merc_status} "
                        "Daily reset is at 19:00 UTC and this post runs at 19:05 UTC.\n"
                        f"{website_text}"
                    )
                    allowed_mentions = discord.AllowedMentions(users=True)
                elif self._rlstore_notify_target:
                    logger.warning(
                        "[BackgroundService] rlstore notify target '%s' was not found in guild '%s'",
                        self._rlstore_notify_target,
                        guild.name,
                    )
                    content = (
                        "Rocket League store refreshed. "
                        f"{merc_status} "
                        f"Configured notify target '{self._rlstore_notify_target}' was not found for a direct mention.\n"
                        f"{website_text}"
                    )
                    allowed_mentions = discord.AllowedMentions.none()
                else:
                    content = f"Rocket League store refreshed. {merc_status}\n{website_text}"
                    allowed_mentions = discord.AllowedMentions.none()

                view = RocketLeagueStoreView(
                    snapshot=snapshot,
                    owner_id=None,
                    image_generator=image_generator,
                )
                await view.prepare_all_pages()
                image_file = await view.create_file()
                if image_file is not None:
                    await channel.send(
                        content=content,
                        file=image_file,
                        view=view,
                        allowed_mentions=allowed_mentions,
                    )
                else:
                    await channel.send(
                        content=content,
                        embed=view.create_embed(),
                        view=view,
                        allowed_mentions=allowed_mentions,
                    )
                self.action_repo.insert("scheduler", self.RLSTORE_NOTIFY_ACTION, notify_key, guild_id=guild.id)
                sent_count += 1
            except Exception as exc:
                logger.error(
                    "[BackgroundService] rlstore notification failed for guild '%s': %s",
                    guild.name,
                    exc,
                    exc_info=True,
                )

        return sent_count

    def _get_rlstore_channel(
        self,
        guild: discord.Guild,
        message_service,
    ) -> Optional[discord.TextChannel]:
        """
        Resolve the preferred text channel for Rocket League store posts.

        Args:
            guild: Guild receiving the notification.
            message_service: Shared message service used for fallback channel lookup.

        Returns:
            The `#botrl` channel when present, otherwise the standard bot channel.
        """
        rlstore_channel = discord.utils.get(guild.text_channels, name=self.RLSTORE_CHANNEL_NAME)
        if rlstore_channel is not None:
            return rlstore_channel
        return message_service.get_bot_channel(guild)

    @tasks.loop(seconds=0.5)
    async def performance_telemetry_loop(self):
        """Log high-frequency process and host performance telemetry."""
        try:
            sample_monotonic = time.monotonic()
            payload = self._build_performance_snapshot(sample_monotonic)
            loop_lag_ms = payload.get("loop_lag_ms")
            if (
                self._perf_loop_lag_warning_ms
                and isinstance(loop_lag_ms, (int, float))
                and loop_lag_ms >= self._perf_loop_lag_warning_ms
                and sample_monotonic - self._perf_last_loop_lag_warning_monotonic >= 5.0
            ):
                self._perf_last_loop_lag_warning_monotonic = sample_monotonic
                logger.warning(
                    "[PerformanceMonitor] Event loop lag %.1fms | "
                    "process_cpu=%.1f%% host_cpu=%.1f%% rss=%s "
                    "threads=%s tasks=%s pending=%s load1=%s bot_latency=%.1fms",
                    loop_lag_ms,
                    payload.get("process_cpu_percent_of_one_core") or 0.0,
                    payload.get("cpu_total_percent") or 0.0,
                    payload.get("process_memory_rss_bytes"),
                    payload.get("process_threads"),
                    payload.get("asyncio_task_total"),
                    payload.get("asyncio_task_pending"),
                    payload.get("load_avg_1m"),
                    payload.get("bot_latency_ms") or 0.0,
                )
            #logger.info("[PerformanceMonitor] %s", json.dumps(payload, sort_keys=True))
        except Exception as e:
            logger.error(
                "[BackgroundService] Error in performance telemetry loop: %s",
                e,
                exc_info=True,
            )

    @tasks.loop(seconds=1)
    async def web_control_room_status_loop(self):
        """Persist live bot status for the optional web soundboard panel."""
        try:
            for guild in self.bot.guilds:
                snapshot = self.audio_service.get_guild_playback_snapshot(guild)
                mute_service = getattr(self.audio_service, "mute_service", None)
                muted = bool(getattr(mute_service, "is_muted", False))
                mute_remaining = (
                    mute_service.get_remaining_seconds()
                    if muted and hasattr(mute_service, "get_remaining_seconds")
                    else 0
                )
                self.web_control_room_repo.upsert_status(
                    guild_id=guild.id,
                    guild_name=guild.name,
                    voice_connected=snapshot["voice_connected"],
                    voice_channel_id=snapshot["voice_channel_id"],
                    voice_channel_name=snapshot["voice_channel_name"],
                    voice_member_count=snapshot["voice_member_count"],
                    voice_members=snapshot["voice_members"],
                    is_playing=snapshot["is_playing"],
                    is_paused=snapshot["is_paused"],
                    current_sound=snapshot["current_sound"],
                    current_requester=snapshot["current_requester"],
                    current_duration_seconds=snapshot["current_duration_seconds"],
                    current_elapsed_seconds=snapshot["current_elapsed_seconds"],
                    muted=muted,
                    mute_remaining_seconds=mute_remaining,
                )
                # Compute a signature of significant fields (excluding fast-changing
                # elapsed seconds and full voice_members list). Publish a Honker
                # event only when the signature changes.
                sig = (
                    snapshot["voice_connected"],
                    snapshot["voice_channel_id"],
                    snapshot["voice_member_count"],
                    snapshot["is_playing"],
                    snapshot["is_paused"],
                    snapshot["current_sound"],
                    snapshot["current_requester"],
                    muted,
                )
                if self._ctrl_room_signatures.get(guild.id) != sig:
                    self._ctrl_room_signatures[guild.id] = sig
                    try:
                        from bot.services.honker_integration import publish_soundboard_event as _pub
                        _pub(self.sound_repo.db_path, "control_room_changed", {"guild_id": guild.id})
                    except Exception:
                        pass
        except Exception as e:
            print(f"[BackgroundService] Error updating web control room status: {e}")

    @tasks.loop(seconds=1)
    async def web_system_monitor_status_loop(self):
        """Collect host CPU/RAM/top processes and persist to DB every 1 s."""
        try:
            started = time.monotonic()
            snapshot = await asyncio.to_thread(
                self._host_system_monitor.get_snapshot,
                top_limit=8,
            )
            elapsed = time.monotonic() - started
            if elapsed > 2.0:
                logger.warning(
                    "[BackgroundService] Host system monitor collection took %.2fs",
                    elapsed,
                )
            if snapshot.get("available"):
                self._host_monitor_warmed = True
            if self._host_monitor_warmed:
                snapshot = self._snapshot_with_cpu_history(snapshot)
                timeseries_samples = snapshot.pop("_timeseries_samples", [])
                self.web_system_status_repo.upsert_snapshot(snapshot)
                if timeseries_samples:
                    try:
                        self.web_system_status_repo.insert_samples_batch(timeseries_samples)
                    except Exception as e:
                        logger.warning(
                            "[BackgroundService] Failed to insert time-series samples: %s",
                            e,
                        )
        except Exception as e:
            logger.error(
                "[BackgroundService] Error in host system monitor loop: %s",
                e,
                exc_info=True,
            )

    def _snapshot_with_cpu_history(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Return *snapshot* with rolling 60-second CPU and temp history."""
        sample_time = self._monitor_sample_time(snapshot)

        if not snapshot.get("cpu_warming"):
            self._append_monitor_history_sample(
                self._host_monitor_cpu_history,
                sample_time=sample_time,
                value=snapshot.get("total_cpu_percent"),
                key="cpu",
                minimum=0.0,
                maximum=100.0,
            )

        self._append_monitor_history_sample(
            self._host_monitor_temp_history,
            sample_time=sample_time,
            value=snapshot.get("cpu_temperature_celsius"),
            key="temp",
            minimum=0.0,
            maximum=125.0,
        )
        self._append_monitor_history_sample(
            self._host_monitor_ram_history,
            sample_time=sample_time,
            value=snapshot.get("ram_percent"),
            key="ram",
            minimum=0.0,
            maximum=100.0,
        )
        self._append_monitor_history_sample(
            self._host_monitor_disk_history,
            sample_time=sample_time,
            value=snapshot.get("disk_active_percent"),
            key="disk",
            minimum=0.0,
            maximum=100.0,
        )
        top_processes = []
        for process in snapshot.get("top_processes") or []:
            if not isinstance(process, dict):
                continue
            process_copy = dict(process)
            process_key = self._monitor_process_history_key(process_copy)
            process_label = str(
                process_copy.get("display_name")
                or process_copy.get("name")
                or f"pid:{process_copy.get('pid', '')}"
            )
            process_copy["process_history_key"] = process_key
            top_processes.append(process_copy)
            self._host_monitor_process_labels[process_key] = process_label
            history = self._host_monitor_process_cpu_history.setdefault(process_key, [])
            self._append_monitor_history_sample(
                history,
                sample_time=sample_time,
                value=process_copy.get("cpu_percent"),
                key="cpu",
                minimum=0.0,
                maximum=100.0,
            )

        process_cutoff = sample_time - 59
        for process_key in list(self._host_monitor_process_cpu_history):
            history = self._host_monitor_process_cpu_history[process_key]
            history[:] = [
                sample for sample in history if int(sample["time"]) >= process_cutoff
            ]
            if not history:
                self._host_monitor_process_cpu_history.pop(process_key, None)
                self._host_monitor_process_labels.pop(process_key, None)

        return {
            **snapshot,
            "top_processes": top_processes,
            "cpu_history": list(self._host_monitor_cpu_history),
            "temp_history": list(self._host_monitor_temp_history),
            "ram_history": list(self._host_monitor_ram_history),
            "disk_history": list(self._host_monitor_disk_history),
            "process_cpu_history": [
                {
                    "key": process_key,
                    "label": self._host_monitor_process_labels.get(process_key, process_key),
                    "history": list(history),
                }
                for process_key, history in self._host_monitor_process_cpu_history.items()
            ],
            "_timeseries_samples": self._collect_timeseries_samples(
                sample_time, snapshot, top_processes
            ),
        }

    def _collect_timeseries_samples(
        self,
        sample_time: int,
        snapshot: dict[str, Any],
        top_processes: list[dict[str, Any]],
    ) -> list[tuple[str, str, int, float]]:
        """Collect current metric values for time-series database storage."""
        samples: list[tuple[str, str, int, float]] = []

        if not snapshot.get("cpu_warming"):
            cpu_val = snapshot.get("total_cpu_percent")
            if cpu_val is not None:
                try:
                    samples.append(("cpu", "", sample_time, float(cpu_val)))
                except (TypeError, ValueError):
                    pass

        temp_val = snapshot.get("cpu_temperature_celsius")
        if temp_val is not None:
            try:
                samples.append(("temp", "", sample_time, float(temp_val)))
            except (TypeError, ValueError):
                pass

        ram_val = snapshot.get("ram_percent")
        if ram_val is not None:
            try:
                samples.append(("ram", "", sample_time, float(ram_val)))
            except (TypeError, ValueError):
                pass

        disk_val = snapshot.get("disk_active_percent")
        if disk_val is not None:
            try:
                samples.append(("disk", "", sample_time, float(disk_val)))
            except (TypeError, ValueError):
                pass

        for process in top_processes:
            process_key = process.get("process_history_key", "")
            cpu_percent = process.get("cpu_percent")
            if process_key and cpu_percent is not None:
                try:
                    samples.append(("process", process_key, sample_time, float(cpu_percent)))
                except (TypeError, ValueError):
                    pass

        return samples

    @staticmethod
    def _monitor_process_history_key(process: dict[str, Any]) -> str:
        """Return a stable-enough key for one process history line."""
        pid = process.get("pid")
        name = process.get("display_name") or process.get("name") or "process"
        return f"{pid}:{name}" if pid is not None else str(name)

    @staticmethod
    def _monitor_sample_time(snapshot: dict[str, Any]) -> int:
        """Return the integer Unix second for a monitor snapshot."""
        try:
            return int(round(float(snapshot.get("updated_at_unix", time.time()))))
        except (TypeError, ValueError):
            return int(round(time.time()))

    @staticmethod
    def _append_monitor_history_sample(
        history: list[dict[str, float]],
        *,
        sample_time: int,
        value: Any,
        key: str,
        minimum: float,
        maximum: float,
    ) -> None:
        """Append or replace one bounded monitor history sample."""
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return
        if numeric_value != numeric_value:
            return

        numeric_value = max(minimum, min(maximum, numeric_value))
        sample = {"time": sample_time, key: round(numeric_value, 1)}
        if history and int(history[-1]["time"]) == sample_time:
            history[-1].update(sample)
        else:
            history.append(sample)

        cutoff = sample_time - 59
        history[:] = [
            existing
            for existing in history
            if int(existing["time"]) >= cutoff
        ]

    @tasks.loop(minutes=5)
    async def weekly_wrapped_scheduler_loop(self):
        """Send weekly wrapped summaries once per week at the configured UTC time."""
        try:
            sent_count = await self._run_with_honker_lock(
                "weekly_wrapped",
                self._run_weekly_wrapped_scheduler_tick,
            )
            if sent_count > 0:
                print(f"[BackgroundService] Weekly wrapped sent in {sent_count} guild(s)")
        except Exception as e:
            print(f"[BackgroundService] Error in weekly wrapped scheduler: {e}")

    @tasks.loop(minutes=5)
    async def rlstore_notification_loop(self):
        """Send the daily rlstore notification shortly after the store reset window."""
        try:
            sent_count = await self._run_with_honker_lock(
                "rlstore_notification",
                self._run_rlstore_notification_tick,
            )
            if sent_count > 0:
                print(f"[BackgroundService] rlstore notification sent in {sent_count} guild(s)")
        except Exception as e:
            print(f"[BackgroundService] Error in rlstore notification scheduler: {e}")

    @tasks.loop(minutes=5)
    async def backup_scheduler_loop(self):
        """Create a weekly backup at the configured UTC time."""
        try:
            result = await self._run_with_honker_lock(
                "backup_scheduler",
                self._run_backup_scheduler_tick,
            )
            if result > 0:
                logger.info("[BackgroundService] Scheduled backup created successfully")
        except Exception as e:
            logger.error(
                "[BackgroundService] Error in backup scheduler: %s",
                e,
                exc_info=True,
            )

    @tasks.loop(seconds=10)
    async def favorite_watcher_loop(self):
        """Poll watched TikTok collections and import newly added videos."""
        try:
            favorite_watcher_service = getattr(self.behavior, "_favorite_watcher_service", None)
            if favorite_watcher_service is None:
                return
            imported_count = await favorite_watcher_service.poll_once()
            if imported_count:
                logger.info(
                    "[BackgroundService] Favorite watcher imported %s sound(s)",
                    imported_count,
                )
        except Exception as e:
            logger.error(
                "[BackgroundService] Error in favorite watcher loop: %s",
                e,
                exc_info=True,
            )

    async def drain_sound_import_notifications_once(self, limit: int = 5) -> None:
        """
        Drain pending sound import notifications.

        This is the core drain logic shared by the polling loop and the
        optional Honker notification listener.

        Args:
            limit: Maximum pending notifications to process per call.
        """
        if self.behavior is None:
            return
        if self._sound_import_notification_repo is None:
            self._sound_import_notification_repo = SoundImportNotificationRepository()
        try:
            pending = self._sound_import_notification_repo.get_pending(limit=limit)
            for notification in pending:
                nid = int(notification["id"])
                try:
                    raw_title = notification.get("title")
                    raw_accent = notification.get("accent_color")
                    await self._sound_import_notification_service.send_notification(
                        behavior=self.behavior,
                        filename=str(notification["filename"]),
                        guild_id=self._parse_guild_id(notification.get("guild_id")),
                        source=str(notification["source"]),
                        requester=str(notification.get("requester_username") or None),
                        title=str(raw_title) if raw_title is not None else None,
                        accent_color=str(raw_accent) if raw_accent is not None else None,
                    )
                    self._sound_import_notification_repo.mark_sent(nid)
                    # Publish soundboard events for live SSE updates.
                    try:
                        from bot.services.honker_integration import publish_soundboard_event as _pub
                        _pub(
                            self.sound_repo.db_path,
                            "sound_imported",
                            {
                                "filename": str(notification["filename"]),
                                "guild_id": notification.get("guild_id"),
                                "source": str(notification.get("source", "")),
                            },
                        )
                        _pub(
                            self.sound_repo.db_path,
                            "sounds_changed",
                            {
                                "guild_id": notification.get("guild_id"),
                            },
                        )
                    except Exception:
                        pass
                except Exception as exc:
                    logger.error(
                        "[BackgroundService] Failed to send import notification %s: %s",
                        nid,
                        exc,
                        exc_info=True,
                    )
                    self._sound_import_notification_repo.mark_failed(
                        nid, str(exc)
                    )
        except Exception as exc:
            logger.error(
                "[BackgroundService] Error in import notification drain: %s",
                exc,
                exc_info=True,
            )

    _honker_sound_import_listener_task: Any = None

    async def _start_honker_sound_import_listener(self) -> None:
        """Start a Honker listener for sound_import_notifications."""
        try:
            from bot.services.honker_integration import (
                availability as _honker_available,
                listen_notifications as _honker_listen,
            )
        except ImportError:
            return

        if not _honker_available():
            return

        db_path = self._resolve_db_path()
        logger.info("[Honker] Starting sound_import_notifications listener...")
        try:
            async for _notification in _honker_listen(db_path, "sound_import_notifications", fallback_poll_s=1.0):
                await self.drain_sound_import_notifications_once(limit=5)
        except Exception as exc:
            logger.warning(
                "[Honker] Sound import notification listener stopped: %s", exc
            )

    @tasks.loop(seconds=3)
    async def sound_import_notification_drain_loop(self) -> None:
        """
        Drain the cross-process sound import notification outbox.

        Web upload background workers cannot use BotBehavior directly, so they
        insert rows into the ``sound_import_notifications`` table instead. This
        loop picks up pending rows and sends the Discord image-card notification
        using the shared notification service.
        """
        await self.drain_sound_import_notifications_once(limit=5)

    @tasks.loop(seconds=86400)
    async def speech_training_keyword_scan_loop(self):
        """Daily keyword scan of unlabeled speech training clips.

        For each guild with configured trigger keywords, scans unlabeled
        clips (≤30s) using offline Vosk and labels non-matches as ``none``.
        Progress is reported to the guild's bot channel with a self-editing
        message.  Schedule metadata (last run, next run, status, summary)
        is persisted to ``app_settings`` for display on the Dataset page.
        """
        if self._keyword_scan_in_progress:
            logger.debug(
                "[BackgroundService] Speech training keyword scan already in progress, skipping tick"
            )
            return
        if not self._keyword_scan_daily_enabled:
            return

        self._keyword_scan_in_progress = True
        now_utc = datetime.now(timezone.utc)
        now_iso = now_utc.isoformat()
        next_run_iso = (now_utc + timedelta(seconds=self._keyword_scan_daily_interval)).isoformat()

        try:
            db_path = self._resolve_db_path()
            self._init_app_settings_repo(db_path)

            # Persist start-of-scan metadata
            self._persist_keyword_scan_schedule(
                enabled=True,
                interval_seconds=self._keyword_scan_daily_interval,
                last_started_at=now_iso,
                next_run_at=next_run_iso,
                last_status="running",
                last_summary=None,
            )

            speech_training_data_dir = os.getenv(
                "SPEECH_TRAINING_DATA_DIR",
                os.path.abspath(
                    os.path.join(
                        os.path.dirname(__file__),
                        "..", "..", "data", "speech_training",
                    )
                ),
            )

            repo = SpeechTrainingRepository(
                db_path=db_path, use_shared=False
            )
            repo.ensure_schema()
            kw_repo = KeywordRepository(
                db_path=db_path, use_shared=False
            )
            kw_rows = kw_repo.get_all(limit=200)
            trigger_keywords = sorted({
                r["keyword"].strip().lower()
                for r in kw_rows
                if r.get("keyword") and r["keyword"].strip()
            })

            if not trigger_keywords:
                logger.info(
                    "[BackgroundService] No trigger keywords configured, skipping "
                    "speech training keyword scan"
                )
                self._persist_keyword_scan_schedule(
                    last_finished_at=now_iso,
                    last_status="skipped",
                    last_summary="No trigger keywords configured",
                )
                return

            from bot.services.web_speech_training import WebSpeechTrainingService

            svc = WebSpeechTrainingService(repo, speech_training_data_dir)
            svc.KEYWORD_SCAN_WORKERS = self._keyword_scan_workers
            guild_results: list[dict] = []
            loop_error: str | None = None

            for guild in self.bot.guilds:
                try:
                    result = await self._run_guild_keyword_scan(
                        guild=guild,
                        svc=svc,
                        keywords=trigger_keywords,
                    )
                    if result is not None:
                        guild_results.append(result)
                except Exception as exc:
                    logger.error(
                        "[BackgroundService] Speech training keyword scan failed "
                        "for guild '%s': %s",
                        guild.name,
                        exc,
                        exc_info=True,
                    )
                    guild_results.append({
                        "guild_id": str(guild.id),
                        "guild_name": guild.name,
                        "total": 0,
                        "scanned": 0,
                        "matched": 0,
                        "skipped": 0,
                        "labeled_non": 0,
                        "status": "error",
                    })

            # Build summary string from aggregated results
            total_clips = sum(r.get("total", 0) for r in guild_results)
            total_scanned = sum(r.get("scanned", 0) for r in guild_results)
            total_matched = sum(r.get("matched", 0) for r in guild_results)
            total_skipped = sum(r.get("skipped", 0) for r in guild_results)
            total_labeled_non = sum(r.get("labeled_non", 0) for r in guild_results)
            total_trimmed = sum(r.get("trimmed", 0) for r in guild_results)
            guilds_with_clips = sum(1 for r in guild_results if r.get("total", 0) > 0)
            guilds_scanned = sum(1 for r in guild_results if r.get("status") in ("completed", "timeout"))
            guilds_errored = sum(1 for r in guild_results if r.get("status") == "error")

            summary_parts: list[str] = []
            if guilds_scanned:
                summary_parts.append(f"{guilds_scanned} guild(s)")
            if total_scanned:
                summary_parts.append(f"{total_scanned} scanned")
            if total_matched:
                summary_parts.append(f"{total_matched} match{'es' if total_matched != 1 else ''}")
            if total_skipped:
                summary_parts.append(f"{total_skipped} skipped")
            if total_labeled_non:
                summary_parts.append(f"{total_labeled_non} labeled as none")
            if total_trimmed:
                summary_parts.append(f"{total_trimmed} trimmed")
            if guilds_errored:
                summary_parts.append(f"{guilds_errored} error{'s' if guilds_errored != 1 else ''}")
            if guilds_with_clips and not guilds_scanned:
                summary_parts.append("no guilds scanned")

            summary = " · ".join(summary_parts) if summary_parts else "No guilds processed"
            final_status = "completed"
            if guilds_errored and not guilds_scanned:
                final_status = "error"
            elif loop_error:
                final_status = "error"

            self._persist_keyword_scan_schedule(
                last_finished_at=now_iso,
                last_status=final_status,
                last_summary=summary,
            )

        except Exception as exc:
            logger.error(
                "[BackgroundService] Speech training keyword scan error: %s",
                exc,
                exc_info=True,
            )
            try:
                self._persist_keyword_scan_schedule(
                    last_finished_at=datetime.now(timezone.utc).isoformat(),
                    last_status="error",
                    last_summary=f"Scan error: {exc}",
                )
            except Exception:
                pass
        finally:
            self._keyword_scan_in_progress = False

    # ── Keyword scan image-card helpers ────────────────────────────────────────

    KEYWORD_SCAN_BORDER_COLOR = "#ED4245"
    KEYWORD_SCAN_REQUESTER = "Keyword Scan"

    @staticmethod
    def _format_keyword_scan_description(
        *,
        total: int,
        scanned: int,
        matched: int,
        skipped: int,
        labeled_non: int = 0,
        labeled_potential: int = 0,
        trimmed: int = 0,
        keywords: Optional[list[str]] = None,
    ) -> str:
        """Build a compact description line for keyword scan progress/completion cards.

        Args:
            total: Total number of eligible clips.
            scanned: Number of clips scanned so far.
            matched: Number of keyword matches found.
            skipped: Number of clips skipped.
            labeled_non: Number of clips labeled as ``none`` (completion only).
            labeled_potential: Number of clips labeled as ``potential`` (completion only).
            trimmed: Number of matches auto-trimmed to keyword (completion only).
            keywords: The keyword list used for the scan (included once at start).

        Returns:
            Compact summary string, e.g. ``"3 keyword(s) · 12/83 sounds · 4 matches · 2 skipped"``.
        """
        parts: list[str] = []
        if keywords is not None:
            parts.append(f"{len(keywords)} keyword(s)")
        if scanned == total:
            parts.append(f"{scanned} sound{'s' if scanned != 1 else ''} scanned")
        else:
            parts.append(f"{scanned}/{total} sounds")
        if matched:
            parts.append(f"{matched} match{'es' if matched != 1 else ''}")
        if skipped:
            parts.append(f"{skipped} skipped")
        if labeled_non:
            parts.append(f"{labeled_non} labeled as none")
        if labeled_potential:
            parts.append(f"{labeled_potential} labeled potential")
        if trimmed:
            parts.append(f"{trimmed} trimmed")
        return " · ".join(parts)

    async def _send_keyword_scan_card(
        self,
        channel: discord.TextChannel,
        guild: discord.Guild,
        title: str,
        description: str,
    ) -> Optional[discord.Message]:
        """Send an initial keyword scan progress/completion card.

        Uses the standard image-card notification style with fallback to embed,
        then plain text as a last resort.
        """
        if self.behavior:
            try:
                msg = await self.behavior.send_message(
                    title=title,
                    description=description,
                    channel=channel,
                    guild=guild,
                    message_format="image",
                    image_requester=self.KEYWORD_SCAN_REQUESTER,
                    image_show_footer=False,
                    image_show_sound_icon=False,
                    image_border_color=self.KEYWORD_SCAN_BORDER_COLOR,
                    send_controls=False,
                )
                if msg:
                    return msg
            except Exception:
                pass

        # Fallback: embed
        try:
            embed = discord.Embed(
                title=title,
                description=description,
                color=discord.Color(0xED4245),
            )
            return await channel.send(embed=embed)
        except Exception:
            pass

        # Last resort: plain text
        try:
            return await channel.send(f"**{title}**\n{description}")
        except Exception:
            return None

    async def _edit_keyword_scan_card(
        self,
        message: discord.Message,
        title: str,
        description: str,
        message_service,
    ) -> None:
        """Edit an existing keyword scan message with a new image card.

        Generates a fresh image card and replaces the attachment in-place.
        Falls back to embed edit, then plain-text content edit.
        """
        # Preferred path: regenerate image card and replace attachment
        try:
            image_bytes = await message_service._generate_message_image(
                title=title,
                description=description,
                thumbnail=None,
                requester=self.KEYWORD_SCAN_REQUESTER,
                show_footer=False,
                show_sound_icon=False,
                border_color=self.KEYWORD_SCAN_BORDER_COLOR,
            )
            if image_bytes:
                await message.edit(
                    content=None,
                    embed=None,
                    attachments=[],
                    file=discord.File(
                        io.BytesIO(image_bytes),
                        filename="message_card.png",
                    ),
                )
                return
        except Exception:
            pass

        # Fallback: embed edit
        try:
            embed = discord.Embed(
                title=title,
                description=description,
                color=discord.Color(0xED4245),
            )
            await message.edit(content=None, embed=embed, attachments=[])
            return
        except Exception:
            pass

        # Last resort: plain-text edit
        try:
            await message.edit(
                content=f"**{title}**\n{description}",
                embed=None,
                attachments=[],
            )
        except Exception:
            pass

    async def _run_guild_keyword_scan(
        self,
        guild: discord.Guild,
        svc: "WebSpeechTrainingService",
        keywords: list[str],
    ) -> None:
        """Run keyword scan for one guild and send progress to bot channel.

        Progress is reported with standard image-card notifications (editable
        in-place), not plain text.
        """
        message_service = getattr(self.audio_service, "message_service", None)
        if message_service is None:
            return

        channel = message_service.get_bot_channel(guild)
        if channel is None:
            logger.debug(
                "[BackgroundService] No bot channel for guild '%s', skipping keyword scan",
                guild.name,
            )
            return

        # Count eligible clips first
        eligible = svc.repo.list_unlabeled_clips(
            guild_id=str(guild.id),
            max_duration_seconds=svc.KEYWORD_SCAN_MAX_DURATION_SECONDS,
        )
        if not eligible:
            logger.debug(
                "[BackgroundService] No eligible unlabeled clips for guild '%s', "
                "skipping keyword scan",
                guild.name,
            )
            return

        total = len(eligible)
        logger.info(
            "[BackgroundService] Starting keyword scan for guild '%s': %d clips, "
            "%d keywords",
            guild.name,
            total,
            len(keywords),
        )

        # Send initial progress card
        initial_desc = self._format_keyword_scan_description(
            total=total, scanned=0, matched=0, skipped=0, keywords=keywords,
        )
        progress_msg = await self._send_keyword_scan_card(
            channel=channel,
            guild=guild,
            title="🔎 Keyword scan running",
            description=initial_desc,
        )
        if progress_msg is None:
            logger.error(
                "[BackgroundService] Failed to send initial keyword scan card for guild '%s'",
                guild.name,
            )
            return

        # Thread-safe progress state
        progress_state: dict[str, Any] = {
            "scanned": 0,
            "matched": 0,
            "skipped": 0,
            "total": total,
        }
        progress_lock = threading.Lock()

        async def _update_progress_message() -> None:
            """Edit the progress card with current state (throttled)."""
            with progress_lock:
                scanned = progress_state["scanned"]
                matched = progress_state["matched"]
                skipped = progress_state["skipped"]
                total = progress_state["total"]
            description = self._format_keyword_scan_description(
                total=total, scanned=scanned, matched=matched, skipped=skipped,
                keywords=keywords,
            )
            await self._edit_keyword_scan_card(
                message=progress_msg,
                title="🔎 Keyword scan running",
                description=description,
                message_service=message_service,
            )

        last_update_time = time.monotonic()
        min_update_interval = 3.0  # seconds between Discord edits

        def _on_progress(progress: dict[str, Any]) -> None:
            """Thread-safe progress callback from the Vosk scan."""
            nonlocal last_update_time
            with progress_lock:
                progress_state["scanned"] = progress.get("scanned", 0)
                progress_state["matched"] = progress.get("matched", 0)
                progress_state["skipped"] = progress.get("skipped", 0)
                progress_state["total"] = progress.get("total", 0)
                now = time.monotonic()
                if now - last_update_time >= min_update_interval:
                    last_update_time = now
                    # Schedule the async update on the event loop
                    asyncio.run_coroutine_threadsafe(
                        _update_progress_message(),
                        self.bot.loop,
                    )

        # Run the scan in a thread executor (Vosk is CPU-bound)
        loop = asyncio.get_event_loop()
        # Use a timeout so the task doesn't hang forever
        scan_future = loop.run_in_executor(
            None,
            lambda: svc.scan_unlabeled_keywords(
                keywords=keywords,
                min_confidence=0.5,
                guild_id=str(guild.id),
                label_non_matches_as_none=True,
                label_matches_as_potential=True,
                trim_matches_to_keyword=True,
                progress_callback=_on_progress,
            ),
        )

        try:
            result = await asyncio.wait_for(scan_future, timeout=1800)  # 30 min max
        except asyncio.TimeoutError:
            logger.error(
                "[BackgroundService] Keyword scan timed out for guild '%s'",
                guild.name,
            )
            await self._edit_keyword_scan_card(
                message=progress_msg,
                title="⚠️ Keyword scan timed out",
                description=self._format_keyword_scan_description(
                    total=total, scanned=progress_state["scanned"],
                    matched=progress_state["matched"],
                    skipped=progress_state["skipped"],
                ),
                message_service=message_service,
            )
            return {
                "guild_id": str(guild.id),
                "guild_name": guild.name,
                "total": total,
                "scanned": progress_state["scanned"],
                "matched": progress_state["matched"],
                "skipped": progress_state["skipped"],
                "labeled_non": 0,
                "status": "timeout",
            }

        # Final update
        scanned = result.get("scanned", 0)
        matched = result.get("matched", 0)
        skipped = result.get("skipped", 0)
        labeled_non = result.get("labeled_non_matches", 0)
        labeled_potential = result.get("labeled_matches", 0)
        trimmed = result.get("trimmed_matches", 0)

        await self._edit_keyword_scan_card(
            message=progress_msg,
            title="✅ Keyword scan complete",
            description=self._format_keyword_scan_description(
                total=total, scanned=scanned, matched=matched, skipped=skipped,
                labeled_non=labeled_non, labeled_potential=labeled_potential,
                trimmed=trimmed,
            ),
            message_service=message_service,
        )

        logger.info(
            "[BackgroundService] Keyword scan complete for guild '%s': "
            "scanned=%d matched=%d skipped=%d labeled_none=%d labeled_potential=%d trimmed=%d",
            guild.name,
            scanned,
            matched,
            skipped,
            labeled_non,
            labeled_potential,
            trimmed,
        )

        return {
            "guild_id": str(guild.id),
            "guild_name": guild.name,
            "total": total,
            "scanned": scanned,
            "matched": matched,
            "skipped": skipped,
            "labeled_non": labeled_non,
            "labeled_potential": labeled_potential,
            "trimmed": trimmed,
            "status": "completed",
        }

    @staticmethod
    def _parse_guild_id(raw: object) -> int | None:
        """Parse a guild_id value from a repository row, returning ``None`` when absent."""
        if raw is None:
            return None
        try:
            return int(str(raw).strip())
        except (ValueError, TypeError):
            return None

    async def _run_with_honker_lock(
        self,
        lock_name: str,
        callback: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute *callback* under a named Honker lock when available.

        When Honker is unavailable, the callback runs immediately (same
        behaviour as today).  When the lock is held by another process,
        the tick is skipped.
        """
        try:
            from bot.services.honker_integration import lock_acquire, lock_release
        except ImportError:
            return await callback(*args, **kwargs)

        db_path = self._resolve_db_path()
        if not lock_acquire(db_path, lock_name, ttl_seconds=60.0):
            logger.debug(
                "[BackgroundService] Lock '%s' held by another process — skipping tick",
                lock_name,
            )
            return
        try:
            return await callback(*args, **kwargs)
        finally:
            lock_release(db_path, lock_name)

    @staticmethod
    def _resolve_db_path() -> str:
        """Resolve the database path using the same priority as the scan loop."""
        db_path = os.getenv(
            "DATABASE_PATH",
            os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__),
                    "..", "..", "data", "database.db",
                )
            ),
        )
        try:
            from config import DATABASE_PATH
            db_path = DATABASE_PATH
        except Exception:
            pass
        return str(db_path)

    @tasks.loop(seconds=30)
    async def keyword_detection_health_check(self):
        """
        Periodically check if keyword detection is running when bot is connected.
        
        This handles the case where the bot disconnects randomly and the STT stops
        but never gets restarted. It also checks if the worker thread is alive,
        since Discord voice reconnections can stop the worker without removing the sink.
        
        Additionally detects and cleans up zombie voice connections (broken WebSocket
        state after shard reconnection) that cause 'Already connected' errors.
        """
        try:
            for guild in self.bot.guilds:
                settings = self.guild_settings_service.get(guild.id)
                voice_client = guild.voice_client
                
                # Check for zombie/broken voice client (e.g., after shard reconnect)
                if voice_client:
                    ws = getattr(voice_client, 'ws', None)
                    is_zombie = ws is None or str(type(ws)) == "<class 'discord.utils._MissingSentinel'>"
                    
                    if is_zombie:
                        if self.audio_service.is_voice_library_reconnect_pending(voice_client):
                            remaining = self.audio_service.get_voice_library_reconnect_remaining(voice_client)
                            print(f"[BackgroundService] Voice library reconnect in progress ({remaining:.1f}s remaining), skipping zombie cleanup for {guild.name}...")
                            continue

                        # Check if reconnection is already in progress (grace period)
                        if self.audio_service.is_reconnection_pending(guild.id):
                            remaining = self.audio_service.get_reconnection_remaining(guild.id)
                            print(f"[BackgroundService] Reconnection in progress ({remaining:.1f}s remaining), skipping zombie cleanup for {guild.name}...")
                            continue  # Skip this guild, let the ongoing reconnection complete
                        
                        print(f"[BackgroundService] Health check: Zombie voice client detected in {guild.name}, forcing cleanup...")
                        try:
                            await self.audio_service.stop_keyword_detection(guild)
                            await voice_client.disconnect(force=True)
                            await asyncio.sleep(1)
                            # Reconnect to largest populated channel
                            channel = self.audio_service.get_largest_voice_channel(guild)
                            if channel and len([m for m in channel.members if not m.bot]) > 0:
                                await self.audio_service.ensure_voice_connected(channel)
                                self._clear_voice_recovery_failures(guild.id)
                                print(f"[BackgroundService] Health check: Reconnected to {channel.name} after zombie cleanup")
                        except Exception as e:
                            self._record_voice_recovery_failure(guild.id, guild.name, e)
                            print(f"[BackgroundService] Error cleaning up zombie connection: {e}")
                        continue  # Skip normal checks for this guild since we just reconnected
                
                # Normal health checks - only if voice client is actually connected
                if voice_client and voice_client.is_connected():
                    if not settings.stt_enabled:
                        if guild.id in self.audio_service.keyword_sinks:
                            print(f"[BackgroundService] STT disabled in {guild.name}; stopping keyword detection")
                            await self.audio_service.stop_keyword_detection(guild)
                        continue
                    sink = self.audio_service.keyword_sinks.get(guild.id)
                    
                    if sink is None:
                        # No sink at all - start keyword detection
                        print(f"[BackgroundService] Health check: Keyword detection not running in {guild.name}, starting...")
                        await self.audio_service.start_keyword_detection(guild)
                    elif hasattr(sink, 'worker_thread') and not sink.worker_thread.is_alive():
                        # Sink exists but worker thread is dead - restart keyword detection
                        print(f"[BackgroundService] Health check: VoskWorker thread dead in {guild.name}, restarting keyword detection...")
                        await self.audio_service.stop_keyword_detection(guild)
                        await self.audio_service.start_keyword_detection(guild)
        except Exception as e:
            print(f"[BackgroundService] Error in keyword detection health check: {e}")

    @tasks.loop(seconds=30)
    async def bot_self_heal_watchdog_loop(self):
        """Restart the process when the Discord client remains unusable too long."""
        await self._run_bot_self_heal_watchdog_once()

    async def _run_bot_self_heal_watchdog_once(self) -> None:
        """Run one self-heal watchdog check."""
        if not self._self_heal_enabled:
            return

        try:
            now = time.monotonic()
            is_ready = bool(self.bot.is_ready()) if hasattr(self.bot, "is_ready") else True
            is_closed = bool(self.bot.is_closed()) if hasattr(self.bot, "is_closed") else False

            if is_closed:
                self._request_self_restart("Discord client is closed")
                return

            if is_ready:
                self._gateway_unready_since = None
                return

            if self._gateway_unready_since is None:
                self._gateway_unready_since = now
                logger.warning("[BackgroundService] Discord gateway is not ready; starting self-heal timer")
                return

            unready_seconds = now - self._gateway_unready_since
            if unready_seconds >= self._gateway_unready_restart_seconds:
                self._request_self_restart(
                    f"Discord gateway has been unready for {unready_seconds:.1f}s"
                )
        except Exception as e:
            logger.error("[BackgroundService] Error in self-heal watchdog: %s", e, exc_info=True)

    def _format_cpu_for_status(self) -> str | None:
        """
        Return a CPU usage string for the bot's presence status, or ``None``.

        Reads the latest warmed host system snapshot from the persisted repo
        and formats ``total_cpu_percent`` as ``"🖥️ 12.3%"``.

        Returns ``None`` when the snapshot is stale, warming, unavailable, or
        when ``total_cpu_percent`` is not a number, so the caller can skip it.
        """
        try:
            snapshot = self.web_system_status_repo.get_latest_snapshot(max_age_seconds=10)
            if snapshot is None:
                return None
            if not snapshot.get("available"):
                return None
            if snapshot.get("cpu_warming", True):
                return None
            cpu_pct = snapshot.get("total_cpu_percent")
            if cpu_pct is None:
                return None
            return f"🖥️ {cpu_pct}%"
        except Exception as e:
            logger.warning("[BackgroundService] Error reading CPU for status: %s", e)
            return None

    @tasks.loop(seconds=STATUS_UPDATE_INTERVAL_SECONDS)
    async def update_bot_status_loop(self):
        """Continuously update the bot's status based on scheduled background work."""
        try:
            status_parts = []
            
            # 1. Periodic sound (explosion) status
            if hasattr(self.bot, 'next_download_time'):
                time_left = self.bot.next_download_time - time.time()
                if time_left > 0:
                    minutes = round(time_left / 60)
                    if minutes < 1:
                        status_parts.append('🤯')
                    elif minutes >= 60:
                        hours = round(minutes / 60)
                        status_parts.append(f'🤯 in ~{hours}h')
                    else:
                        status_parts.append(f'🤯 in ~{minutes}m')
            
            # 2. Scraper status
            if hasattr(self.bot, 'next_scrape_time'):
                scrape_time_left = self.bot.next_scrape_time - time.time()
                if scrape_time_left > 0:
                    scrape_minutes = round(scrape_time_left / 60)
                    if scrape_minutes >= 60:
                        scrape_hours = round(scrape_minutes / 60)
                        status_parts.append(f'🔍 in ~{scrape_hours}h')
                    else:
                        status_parts.append(f'🔍 in ~{scrape_minutes}m')
                else:
                    status_parts.append('🔍')

            # 3. CPU usage (appended last as requested)
            cpu_part = self._format_cpu_for_status()
            if cpu_part is not None:
                status_parts.append(cpu_part)

            if status_parts:
                status_text = " | ".join(status_parts)
                activity = discord.Activity(name=status_text, type=discord.ActivityType.playing)
                await self.bot.change_presence(activity=activity)
        except Exception as e:
            print(f"[BackgroundService] Error updating status: {e}")

    async def _play_periodic_sound_for_guild(self, guild) -> None:
        """Attempt periodic sound playback in a single guild.

        Skips if periodic is disabled, no suitable channel, no users,
        no random sound available, or if ``play_audio`` returns ``False``
        (e.g. because ``interrupt_existing=False`` found audio already active).
        Only inserts the action record on successful playback.
        """
        settings = self.guild_settings_service.get(guild.id)
        if not settings.periodic_enabled:
            return
        channel = self.audio_service.get_largest_voice_channel(guild)
        if not channel:
            return
        # Skip if channel is empty (no non-bot members)
        non_bot_members = [m for m in channel.members if not m.bot]
        if not non_bot_members:
            print(f"[BackgroundService] Skipping periodic sound in {guild.name} - no users in channel")
            return

        random_sounds = self.sound_repo.get_random_sounds(num_sounds=1, guild_id=guild.id)
        if not random_sounds:
            return
        sound = random_sounds[0]
        result = await self.audio_service.play_audio(
            channel, sound[2], "periodic function",
            interrupt_existing=False,
        )
        if result:
            print(f"[BackgroundService] Playing periodic sound: {sound[2]} in {guild.name}")
            self.action_repo.insert("admin", "play_sound_periodically", sound[0], guild_id=guild.id)
        else:
            print(f"[BackgroundService] Skipped periodic sound in {guild.name} - audio already playing")

    @tasks.loop(count=1)
    async def play_sound_periodically_loop(self):
        """Randomly play sounds at random intervals (10-30 minutes)."""
        await self.bot.wait_until_ready()
        
        while not self.bot.is_closed():
            try:
                # Set random wait time (10-30 minutes)
                sleep_time = random.uniform(60*3, 60*15)
                self.bot.next_download_time = time.time() + sleep_time
                
                await asyncio.sleep(sleep_time)
                
                # Play sound in each guild
                for guild in self.bot.guilds:
                    await self._play_periodic_sound_for_guild(guild)
                            
            except Exception as e:
                print(f"[BackgroundService] Error in periodic playback: {e}")
                await asyncio.sleep(60)  # Wait a minute before retrying on error

    @tasks.loop(count=1)
    async def scrape_sounds_loop(self):
        """Periodically scrape new sounds from MyInstants."""
        await self.bot.wait_until_ready()
        
        first_run = True
        while not self.bot.is_closed():
            try:
                if not first_run:
                    # Wait 8h between scrapes
                    sleep_time = 60*60*8
                    self.bot.next_scrape_time = time.time() + sleep_time
                    print(f"[BackgroundService] Next MyInstants scrape in {int(sleep_time/60)} minutes")
                    await asyncio.sleep(sleep_time)
                else:
                    # Set initial scrape time to 0 so it shows "scraping..." on first run
                    self.bot.next_scrape_time = 0
                    #wait 1 minute first time
                    await asyncio.sleep(60)
                first_run = False
                
                # Run the scraper in a thread executor since it uses Selenium (blocking)
                print("[BackgroundService] Starting MyInstants scraper...")
                await self._notify_scraper_start()
                loop = asyncio.get_event_loop()
                
                # Create scraper instance - needs behavior reference for db
                # We'll use a fresh Database instance since the scraper does that internally
                from bot.database import Database
                db = Database()
                downloader = SoundDownloader(None, db, os.getenv("CHROMEDRIVER_PATH"))
                
                # Run blocking download_sound in executor
                summary = await loop.run_in_executor(None, downloader.download_sound)
                print("[BackgroundService] MyInstants scrape completed")
                await self._notify_scraper_complete(summary)
                
            except Exception as e:
                print(f"[BackgroundService] Error in scrape_sounds_loop: {e}")
                await self._notify_scraper_failure(e)
                await asyncio.sleep(60)  # Wait a minute before retrying on error


    @tasks.loop(seconds=60)
    async def check_voice_activity_loop(self):
        """
        Periodically check if the bot is alone in a voice channel and disconnect if so.
        This serves as a backup to the event-based auto-disconnect.
        """
        try:
            for guild in self.bot.guilds:
                if guild.voice_client and guild.voice_client.is_connected():
                    channel = guild.voice_client.channel
                    if not channel:
                        continue
                        
                    # Count non-bot members
                    non_bot_members = [m for m in channel.members if not m.bot]
                    
                    if len(non_bot_members) == 0:
                        print(f"[BackgroundService] Bot is alone in {channel.name} ({guild.name}), disconnecting...")
                        try:
                            # Stop keyword detection before disconnecting
                            if self.behavior and hasattr(self.behavior, '_audio_service'):
                                await self.behavior._audio_service.stop_keyword_detection(guild)
                            elif self.audio_service:
                                await self.audio_service.stop_keyword_detection(guild)
                                
                            await guild.voice_client.disconnect()
                            print(f"[BackgroundService] Disconnected from {channel.name}")
                        except Exception as e:
                            print(f"[BackgroundService] Error disconnecting from {channel.name}: {e}")

        except Exception as e:
            print(f"[BackgroundService] Error in voice activity check: {e}")

    @tasks.loop(seconds=60)
    async def ensure_last_message_controls_button_loop(self):
        """Every minute, ensure a recent eligible bot message still has inline controls."""
        try:
            for guild in self.bot.guilds:
                await self._ensure_controls_button_on_last_bot_message_for_guild(guild)
        except Exception as e:
            print(f"[BackgroundService] Error ensuring controls button on latest message: {e}")
