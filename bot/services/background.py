import asyncio
import gc
import json
import logging
import os
import random
import resource
import shutil
import time
from typing import Any, Dict, Optional, Tuple
import discord
from discord.ext import tasks
from bot.repositories import SoundRepository, ActionRepository
from bot.downloaders.sound import SoundDownloader
from bot.services.guild_settings import GuildSettingsService

logger = logging.getLogger(__name__)


class BackgroundService:
    """
    Service for background tasks like status updates, periodic sound playback,
    and MyInstants scraping.
    """
    
    def __init__(self, bot, audio_service, sound_service, behavior=None):
        self.bot = bot
        self.audio_service = audio_service
        self.sound_service = sound_service
        self.behavior = behavior # BotBehavior instance
        
        # Repositories
        self.sound_repo = SoundRepository()
        self.action_repo = ActionRepository()
        self.guild_settings_service = GuildSettingsService()
        
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
        self._clock_ticks_per_second = self._resolve_clock_ticks_per_second()
        self._cpu_core_count = max(1, os.cpu_count() or 1)

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
            print("[BackgroundService] Background tasks started.")

    @staticmethod
    def _resolve_clock_ticks_per_second() -> int:
        """Return platform clock ticks/second used in `/proc/self/stat`."""
        try:
            return int(os.sysconf("SC_CLK_TCK"))
        except (AttributeError, ValueError):
            return 100

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
            self._perf_expected_tick_monotonic = (
                sample_monotonic + self._perf_tick_rate_seconds
            )
            return 0.0

        lag = max(
            0.0, sample_monotonic - self._perf_expected_tick_monotonic
        )
        self._perf_expected_tick_monotonic += self._perf_tick_rate_seconds
        if sample_monotonic - self._perf_expected_tick_monotonic > (
            self._perf_tick_rate_seconds * 3
        ):
            # If we missed multiple intervals, reset expectation to avoid runaway lag.
            self._perf_expected_tick_monotonic = (
                sample_monotonic + self._perf_tick_rate_seconds
            )
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

    @tasks.loop(seconds=0.5)
    async def performance_telemetry_loop(self):
        """Log high-frequency process and host performance telemetry."""
        try:
            sample_monotonic = time.monotonic()
            payload = self._build_performance_snapshot(sample_monotonic)
            logger.info("[PerformanceMonitor] %s", json.dumps(payload, sort_keys=True))
        except Exception as e:
            logger.error(
                "[BackgroundService] Error in performance telemetry loop: %s",
                e,
                exc_info=True,
            )

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
                                print(f"[BackgroundService] Health check: Reconnected to {channel.name} after zombie cleanup")
                        except Exception as e:
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

    @tasks.loop(seconds=60)
    async def update_bot_status_loop(self):
        """Continuously update the bot's status based on next explosion time and AI cooldown."""
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
            
            # 2. AI Commentary (Ventura) status
            if self.behavior and hasattr(self.behavior, '_ai_commentary_service'):
                ai_service = self.behavior._ai_commentary_service
                if not ai_service.enabled:
                    status_parts.append('👂🏻 ❌')
                else:
                    ai_cooldown_seconds = ai_service.get_cooldown_remaining()
                    ai_minutes = round(ai_cooldown_seconds / 60)
                    if ai_cooldown_seconds > 0:
                        if ai_minutes >= 60:
                            ai_hours = round(ai_minutes / 60)
                            status_parts.append(f'👂🏻 in ~{ai_hours}h')
                        else:
                            status_parts.append(f'👂🏻 in ~{ai_minutes}m')
                    else:
                        status_parts.append('👂🏻')

            # 3. Scraper status
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

            if status_parts:
                status_text = " | ".join(status_parts)
                activity = discord.Activity(name=status_text, type=discord.ActivityType.playing)
                await self.bot.change_presence(activity=activity)
        except Exception as e:
            print(f"[BackgroundService] Error updating status: {e}")

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
                    settings = self.guild_settings_service.get(guild.id)
                    if not settings.periodic_enabled:
                        continue
                    channel = self.audio_service.get_largest_voice_channel(guild)
                    if channel:
                        # Skip if channel is empty (no non-bot members)
                        non_bot_members = [m for m in channel.members if not m.bot]
                        if not non_bot_members:
                            print(f"[BackgroundService] Skipping periodic sound in {guild.name} - no users in channel")
                            continue
                        
                        random_sounds = self.sound_repo.get_random_sounds(num_sounds=1, guild_id=guild.id)
                        if random_sounds:
                            sound = random_sounds[0]
                            print(f"[BackgroundService] Playing periodic sound: {sound[2]} in {guild.name}")
                            await self.audio_service.play_audio(channel, sound[2], "periodic function")
                            self.action_repo.insert("admin", "play_sound_periodically", sound[0], guild_id=guild.id)
                            
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
