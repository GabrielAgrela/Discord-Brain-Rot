"""
Host system monitor service for the bot side (has ``pid: host`` in Docker).

Provides total CPU/RAM and top per-process CPU usage by reading ``/proc/stat``,
``/proc/meminfo``, ``/proc/[pid]/stat``, ``/proc/[pid]/status``, and
``/proc/[pid]/cmdline``.  Preserves two-sample semantics: the first call
warms and returns ``cpu_warming: true`` with an empty process list.

Process display names are improved by reading ``cmdline``: for Python processes
the script basename is used (e.g. ``personal_greeter.py``) instead of the generic
``python``; for other interpreters the script/module basename is preferred.
Chrome-family processes (chrome, chromium, google-chrome, brave, msedge, etc.)
get role-specific labels such as ``chrome renderer``, ``chrome GPU``,
``chrome browser``, or ``chrome utility (Network)``.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

# Chrome-family browser binary basenames → display prefix
_CHROME_DISPLAY_PREFIX: dict[str, str] = {
    "chrome": "chrome",
    "chromium": "chromium",
    "chromium-browser": "chromium",
    "google-chrome": "chrome",
    "google-chrome-stable": "chrome",
    "google-chrome-unstable": "chrome",
    "brave": "brave",
    "brave-browser": "brave",
    "msedge": "edge",
    "microsoft-edge": "edge",
    "microsoft-edge-stable": "edge",
    "vivaldi": "vivaldi",
    "opera": "opera",
}

# Role labels for Chrome --type= values
_CHROME_TYPE_LABEL: dict[str, str] = {
    "renderer": "renderer",
    "gpu-process": "GPU",
    "utility": "utility",
    "zygote": "zygote",
    "broker": "broker",
    "crashpad-handler": "crashpad",
    "ppapi": "PPAPI",
    "ppapi-broker": "PPAPI broker",
    "sandbox-linux-namespace": "sandbox",
    "extension": "extension",
}


def _classify_chrome_process(args: list[str]) -> str | None:
    """Return a role-specific process label for a Chrome-family browser.

    Examines command-line args for ``--type=`` and ``--utility-sub-type=``
    switches to produce labels such as ``chrome renderer``, ``chrome GPU``,
    ``chrome browser``, or ``chrome utility (Network)``.

    Args:
        args: Decoded command-line argument list (argv).

    Returns:
        A human-readable label (e.g. ``chrome renderer``) or *None* if the
        process is not a Chrome-family browser.
    """
    if not args:
        return None

    binary = os.path.basename(args[0]).lower()
    prefix = _CHROME_DISPLAY_PREFIX.get(binary)
    if prefix is None:
        return None

    type_val: str | None = None
    utility_subtype: str | None = None
    is_extension = False

    for arg in args[1:]:
        if arg.startswith("--type="):
            type_val = arg.split("=", 1)[1]
        elif arg.startswith("--utility-sub-type="):
            utility_subtype = arg.split("=", 1)[1]
        elif arg == "--extension-process":
            is_extension = True
        # Also detect extension URLs (chrome-extension://) as a hint
        if "chrome-extension://" in arg:
            is_extension = True

    if type_val is None:
        return f"{prefix} browser"

    if type_val == "renderer" and is_extension:
        return f"{prefix} extension"

    label = _CHROME_TYPE_LABEL.get(type_val, type_val)

    if type_val == "utility" and utility_subtype:
        # Extract concise subtype from dotted path, e.g. "NetworkService" from
        # "network.mojom.NetworkService" or "Audio" from "audio.mojom.AudioService".
        short = utility_subtype.rsplit(".", 1)[-1] if "." in utility_subtype else utility_subtype
        # Drop common suffixes.
        for suffix in ("Service", "Impl", "Manager", "Handler"):
            if short.endswith(suffix) and len(short) > len(suffix):
                short = short[: -len(suffix)]
                break
        return f"{prefix} {label} ({short})"

    return f"{prefix} {label}"


class HostSystemMonitorService:
    """
    Two-sample host system-resource monitor reading from ``/proc``.

    Stores previous aggregate CPU ticks and per-process (utime+stime) counters
    between calls so the second and subsequent calls can compute deltas.

    Usage::

        svc = HostSystemMonitorService()
        snap = svc.get_snapshot(top_limit=4)
    """

    def __init__(
        self,
        proc_root: str | None = None,
        sys_root: str | None = None,
    ) -> None:
        """
        Args:
            proc_root: Override the ``/proc`` mount point (for testing).
                Defaults to the ``HOST_SYSTEM_MONITOR_PROCFS_ROOT`` env var
                or ``/proc``.
            sys_root: Override the ``/sys`` mount point (for testing CPU temp).
                Defaults to ``/sys``.
        """
        self._proc_root: str = proc_root or os.getenv(
            "HOST_SYSTEM_MONITOR_PROCFS_ROOT", "/proc"
        )
        self._sys_root: str = sys_root or "/sys"
        # Previous aggregate CPU counters: {"total": int, "idle": int}
        self._prev_cpu: dict[str, int] | None = None
        # Previous per-process data: {pid: (comm, utime+stime)}
        self._prev_proc_info: dict[int, tuple[str, int]] = {}
        # Previous aggregate disk counters.
        self._prev_disk_stats: dict[str, int] | None = None
        self._prev_timestamp: float | None = None
        self._slow_log_seconds = max(
            0.0, float(os.getenv("HOST_SYSTEM_MONITOR_SLOW_LOG_SECONDS", "2.0"))
        )
        self._last_process_scan_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_snapshot(
        self,
        top_limit: int = 4,
        *,
        include_sensors: bool = True,
    ) -> dict[str, Any]:
        """
        Return a JSON-safe host system-resource snapshot.

        Args:
            top_limit: Number of top CPU-consuming processes to include
                (clamped 0–8). Use 0 to skip the expensive per-process scan.
            include_sensors: Whether to read slower sysfs sensors such as CPU
                temperature, fan RPM, and battery percentage.

        Returns:
            Dict with keys:

            - ``available`` (*bool*)
            - ``total_cpu_percent`` (*float* | *None*) — ``None`` when warming
            - ``ram_total_bytes`` (*int*)
            - ``ram_available_bytes`` (*int*)
            - ``ram_used_bytes`` (*int*)
            - ``ram_percent`` (*float*)
            - ``cpu_warming`` (*bool*)
            - ``sample_interval_seconds`` (*float*)
            - ``updated_at_unix`` (*float*)
            - ``top_processes`` (*list* of *dict*)
            - ``battery_percent`` (*float* | *None*)
            - ``disk_active_percent`` (*float* | *None*)
            - ``disk_read_bytes_per_second`` (*float*)
            - ``disk_write_bytes_per_second`` (*float*)
            - ``error`` (*str*, only when ``available`` is *False*)
        """
        top_limit = max(0, min(8, top_limit))

        timings: dict[str, float] = {}
        total_started = time.monotonic()

        def _mark(section: str, started: float) -> None:
            timings[section] = time.monotonic() - started

        try:
            ts = time.time()
            section_started = time.monotonic()
            mem = self._read_meminfo()
            _mark("meminfo", section_started)
            section_started = time.monotonic()
            cur_cpu = self._read_cpu_stats()
            _mark("cpu_stats", section_started)

            ram_total = mem.get("MemTotal", 0)
            ram_avail = mem.get("MemAvailable", ram_total)
            ram_used = max(0, ram_total - ram_avail)
            ram_pct = _pct(ram_used, ram_total)

            # -- aggregate CPU delta -------------------------------------------
            prev_cpu = self._prev_cpu
            prev_ts = self._prev_timestamp
            self._prev_cpu = cur_cpu
            self._prev_timestamp = ts

            total_cpu_pct: float | None = None
            interval = 0.0
            warming = True

            if prev_cpu is not None and prev_ts is not None and prev_ts < ts:
                interval = ts - prev_ts
                total_delta = cur_cpu["total"] - prev_cpu["total"]
                idle_delta = cur_cpu["idle"] - prev_cpu["idle"]
                if total_delta > 0:
                    total_cpu_pct = max(
                        0.0,
                        min(100.0, (total_delta - idle_delta) / total_delta * 100.0),
                    )
                    warming = False

            # -- per-process CPU -----------------------------------------------
            section_started = time.monotonic()
            if top_limit > 0:
                processes = self._read_processes(cur_cpu, prev_cpu, top_limit)
            else:
                processes = []
                self._last_process_scan_count = 0
                self._prev_proc_info = {}
            _mark("processes", section_started)
            section_started = time.monotonic()
            disk = self._read_disk_io(interval)
            _mark("disk_io", section_started)
            if include_sensors:
                section_started = time.monotonic()
                cpu_temperature_celsius = self._read_cpu_temperature()
                _mark("cpu_temperature", section_started)
                section_started = time.monotonic()
                cpu_fan_rpm = self._read_cpu_fan_rpm()
                _mark("cpu_fan", section_started)
                section_started = time.monotonic()
                battery_percent = self._read_battery_percent()
                _mark("battery", section_started)
            else:
                cpu_temperature_celsius = None
                cpu_fan_rpm = None
                battery_percent = None
                timings["sensors_skipped"] = 0.0

            total_elapsed = time.monotonic() - total_started
            if self._slow_log_seconds and total_elapsed >= self._slow_log_seconds:
                logger.warning(
                    "Host system monitor slow snapshot total=%.2fs sections=%s "
                    "proc_count=%d top_count=%d top_limit=%d include_sensors=%s",
                    total_elapsed,
                    ", ".join(
                        f"{name}={duration:.3f}s"
                        for name, duration in sorted(
                            timings.items(), key=lambda item: item[1], reverse=True
                        )
                    ),
                    self._last_process_scan_count,
                    len(processes),
                    top_limit,
                    include_sensors,
                )

            return {
                "available": True,
                "total_cpu_percent": _r(total_cpu_pct),
                "ram_total_bytes": ram_total,
                "ram_available_bytes": ram_avail,
                "ram_used_bytes": ram_used,
                "ram_percent": _r(ram_pct),
                "cpu_warming": warming,
                "sample_interval_seconds": _r(interval),
                "updated_at_unix": ts,
                "top_processes": processes,
                "cpu_temperature_celsius": cpu_temperature_celsius,
                "cpu_fan_rpm": cpu_fan_rpm,
                "battery_percent": battery_percent,
                **disk,
            }

        except Exception as exc:
            logger.warning("Host system monitor unavailable: %s", exc)
            return {
                "available": False,
                "error": str(exc),
                "total_cpu_percent": None,
                "ram_total_bytes": 0,
                "ram_available_bytes": 0,
                "ram_used_bytes": 0,
                "ram_percent": 0.0,
                "cpu_warming": True,
                "sample_interval_seconds": 0.0,
                "updated_at_unix": time.time(),
                "top_processes": [],
                "cpu_temperature_celsius": None,
                "cpu_fan_rpm": None,
                "battery_percent": None,
                "disk_active_percent": None,
                "disk_read_bytes_per_second": 0.0,
                "disk_write_bytes_per_second": 0.0,
            }

    # ------------------------------------------------------------------
    # sysfs readers (CPU temperature)
    # ------------------------------------------------------------------

    def _read_cpu_temperature(self) -> float | None:
        """Read CPU temperature from sysfs, return Celsius or ``None``.

        Tries ``/sys/class/thermal/thermal_zone*/`` zones first (preferring
        CPU-related type labels such as ``x86_pkg_temp``, ``coretemp``,
        ``cpu-thermal``), then ``/sys/class/hwmon/hwmon*/`` devices (matching
        by device name or sensor labels).

        Returns:
            Temperature in °C rounded to 1 decimal place, or ``None`` when
            no CPU sensor is available or readable.
        """
        _CPU_KEYWORDS = (
            "cpu", "package", "core", "soc",
            "x86_pkg_temp", "k10temp", "tctl", "tdie",
        )

        def _parse_temp(raw: str) -> float | None:
            try:
                val = int(raw.strip())
                # sysfs values are usually millidegrees (42000 → 42.0 °C)
                celsius = val / 1000.0 if val > 1000 else float(val)
                return round(celsius, 1) if 0 < celsius < 150 else None
            except (ValueError, TypeError):
                return None

        # -- Thermal zones ---------------------------------------------------
        try:
            tz_dir = f"{self._sys_root}/class/thermal"
            if os.path.isdir(tz_dir):
                for entry in sorted(os.listdir(tz_dir)):
                    if not entry.startswith("thermal_zone"):
                        continue
                    type_path = f"{tz_dir}/{entry}/type"
                    temp_path = f"{tz_dir}/{entry}/temp"
                    if not (os.path.isfile(type_path) and os.path.isfile(temp_path)):
                        continue
                    try:
                        with open(type_path, encoding="utf-8") as f:
                            zone_type = f.read().strip().lower()
                        if not any(kw in zone_type for kw in _CPU_KEYWORDS):
                            continue
                        with open(temp_path, encoding="utf-8") as f:
                            temp = _parse_temp(f.read())
                        if temp is not None:
                            return temp
                    except OSError:
                        continue
        except OSError:
            pass

        # -- hwmon devices ---------------------------------------------------
        try:
            hw_dir = f"{self._sys_root}/class/hwmon"
            if os.path.isdir(hw_dir):
                for device in sorted(os.listdir(hw_dir)):
                    if not device.startswith("hwmon"):
                        continue
                    dev_path = f"{hw_dir}/{device}"

                    # Read device name (e.g. "coretemp", "k10temp")
                    dev_name = ""
                    name_path = f"{dev_path}/name"
                    try:
                        with open(name_path, encoding="utf-8") as f:
                            dev_name = f.read().strip().lower()
                    except OSError:
                        pass

                    is_cpu_dev = any(kw in dev_name for kw in _CPU_KEYWORDS) if dev_name else False

                    # Collect temperature labels
                    labels: dict[str, str] = {}
                    try:
                        for entry in os.listdir(dev_path):
                            if entry.startswith("temp") and entry.endswith("_label"):
                                idx = entry[4:-6]  # "temp" + idx + "_label"
                                try:
                                    with open(f"{dev_path}/{entry}", encoding="utf-8") as f:
                                        labels[idx] = f.read().strip().lower()
                                except OSError:
                                    pass
                    except OSError:
                        continue

                    # Scan temperature inputs
                    cpu_candidates: list[float] = []
                    all_candidates: list[float] = []

                    try:
                        for entry in os.listdir(dev_path):
                            if entry.startswith("temp") and entry.endswith("_input"):
                                idx = entry[4:-6]  # "temp" + idx + "_input"
                                try:
                                    with open(f"{dev_path}/{entry}", encoding="utf-8") as f:
                                        temp = _parse_temp(f.read())
                                    if temp is not None:
                                        label = labels.get(idx, "")
                                        if is_cpu_dev or any(kw in label for kw in _CPU_KEYWORDS):
                                            cpu_candidates.append(temp)
                                        all_candidates.append(temp)
                                except OSError:
                                    continue
                    except OSError:
                        continue

                    if cpu_candidates:
                        return round(cpu_candidates[0], 1)
                    if all_candidates and is_cpu_dev:
                        return round(all_candidates[0], 1)
        except OSError:
            pass

        return None

    # ------------------------------------------------------------------
    # sysfs readers (battery)
    # ------------------------------------------------------------------

    def _read_battery_percent(self) -> float | None:
        """Read laptop battery charge from sysfs, return percent or ``None``.

        Scans ``/sys/class/power_supply/*`` entries whose ``type`` is
        ``Battery`` and reads their ``capacity`` value. Multiple batteries are
        averaged because Linux exposes some laptops as BAT0/BAT1.

        Returns:
            Battery charge percentage rounded to 1 decimal place, or ``None``
            when no battery is available or readable.
        """
        power_dir = f"{self._sys_root}/class/power_supply"
        values: list[float] = []

        try:
            if not os.path.isdir(power_dir):
                return None

            for entry in sorted(os.listdir(power_dir)):
                supply_path = f"{power_dir}/{entry}"
                if not os.path.isdir(supply_path):
                    continue

                supply_type = ""
                try:
                    with open(f"{supply_path}/type", encoding="utf-8") as f:
                        supply_type = f.read().strip().lower()
                except OSError:
                    pass

                if supply_type != "battery" and not entry.upper().startswith("BAT"):
                    continue

                try:
                    with open(f"{supply_path}/capacity", encoding="utf-8") as f:
                        value = float(f.read().strip())
                    if 0.0 <= value <= 100.0:
                        values.append(value)
                except (OSError, ValueError):
                    continue
        except OSError:
            return None

        if not values:
            return None
        return _r(sum(values) / len(values))

    # ------------------------------------------------------------------
    # sysfs readers (CPU fan)
    # ------------------------------------------------------------------

    def _read_cpu_fan_rpm(self) -> int | None:
        """Read CPU fan speed from sysfs, return RPM or ``None``.

        Tries ``/sys/class/hwmon/hwmon*/`` devices, preferring fan inputs
        whose ``fan*_label`` contains CPU-related keywords.  Falls back to
        the first valid fan input from a known hwmon device (common
        motherboard/sensor chip names) or the first valid fan overall.

        Returns:
            Fan speed in RPM, or ``None`` when no fan sensor is available
            or readable.
        """
        _FAN_CPU_KEYWORDS = (
            "cpu", "processor", "package", "core", "soc", "tctl", "tdie",
        )
        _FAN_KNOWN_NAMES = (
            "nct", "it87", "asus", "gigabyte", "thinkpad", "dell", "hp",
            "amdgpu",
        )
        _MAX_RPM = 99999

        def _parse_fan(raw: str) -> int | None:
            """Parse a fan RPM value from sysfs.

            Returns the RPM value when it is a valid, readable sensor output
            in the range ``[0, _MAX_RPM)``.  A value of ``0`` is valid and
            indicates a stopped or idle fan.  Returns ``None`` for negative,
            outlandish, or unreadable values.
            """
            try:
                val = int(raw.strip())
                return val if 0 <= val < _MAX_RPM else None
            except (ValueError, TypeError):
                return None

        try:
            hw_dir = f"{self._sys_root}/class/hwmon"
            if not os.path.isdir(hw_dir):
                return None

            for device in sorted(os.listdir(hw_dir)):
                if not device.startswith("hwmon"):
                    continue
                dev_path = f"{hw_dir}/{device}"

                # Read device name (e.g. "nct6797", "coretemp")
                dev_name = ""
                name_path = f"{dev_path}/name"
                try:
                    with open(name_path, encoding="utf-8") as f:
                        dev_name = f.read().strip().lower()
                except OSError:
                    pass

                is_cpu_dev = (
                    any(kw in dev_name for kw in _FAN_CPU_KEYWORDS)
                    if dev_name else False
                )
                is_known_dev = (
                    any(kw in dev_name for kw in _FAN_KNOWN_NAMES)
                    if dev_name else False
                )

                # Collect fan labels
                labels: dict[str, str] = {}
                try:
                    for entry in os.listdir(dev_path):
                        if entry.startswith("fan") and entry.endswith("_label"):
                            idx = entry[3:-6]  # "fan" + idx + "_label"
                            try:
                                with open(
                                    f"{dev_path}/{entry}", encoding="utf-8"
                                ) as f:
                                    labels[idx] = f.read().strip().lower()
                            except OSError:
                                pass
                except OSError:
                    continue

                # Scan fan inputs
                cpu_candidates: list[int] = []
                known_candidates: list[int] = []
                all_candidates: list[int] = []

                try:
                    for entry in os.listdir(dev_path):
                        if entry.startswith("fan") and entry.endswith("_input"):
                            idx = entry[3:-6]  # "fan" + idx + "_input"
                            try:
                                with open(
                                    f"{dev_path}/{entry}", encoding="utf-8"
                                ) as f:
                                    rpm = _parse_fan(f.read())
                                if rpm is not None:
                                    label = labels.get(idx, "")
                                    if is_cpu_dev or any(
                                        kw in label
                                        for kw in _FAN_CPU_KEYWORDS
                                    ):
                                        cpu_candidates.append(rpm)
                                    elif is_known_dev:
                                        known_candidates.append(rpm)
                                    all_candidates.append(rpm)
                            except OSError:
                                continue
                except OSError:
                    continue

                if cpu_candidates:
                    return cpu_candidates[0]
                if known_candidates:
                    return known_candidates[0]
                if all_candidates and is_cpu_dev:
                    return all_candidates[0]

        except OSError:
            pass

        return None

    # ------------------------------------------------------------------
    # /proc disk I/O reader
    # ------------------------------------------------------------------

    def _read_disk_io(self, interval_seconds: float) -> dict[str, float | None]:
        """Return aggregate disk active percentage and read/write byte rates.

        Uses ``/proc/diskstats`` deltas over the same sample interval as CPU.
        The active percentage is based on ``io_ms`` (field 13 in Linux
        diskstats), matching the "active time" style signal users expect from
        desktop task managers.  Read/write speeds are derived from sector
        deltas, using the Linux default 512-byte sector accounting.
        """
        cur = self._read_disk_stats()
        prev = self._prev_disk_stats
        self._prev_disk_stats = cur

        if prev is None or interval_seconds <= 0 or not cur:
            return {
                "disk_active_percent": None,
                "disk_read_bytes_per_second": 0.0,
                "disk_write_bytes_per_second": 0.0,
            }

        read_sector_delta = max(
            0, cur["read_sectors"] - prev.get("read_sectors", cur["read_sectors"])
        )
        write_sector_delta = max(
            0, cur["write_sectors"] - prev.get("write_sectors", cur["write_sectors"])
        )
        io_ms_delta = max(0, cur["io_ms"] - prev.get("io_ms", cur["io_ms"]))

        return {
            "disk_active_percent": _r(min(100.0, io_ms_delta / (interval_seconds * 10.0))),
            "disk_read_bytes_per_second": _r(read_sector_delta * 512 / interval_seconds),
            "disk_write_bytes_per_second": _r(write_sector_delta * 512 / interval_seconds),
        }

    def _read_disk_stats(self) -> dict[str, int]:
        """Read aggregate whole-disk counters from ``/proc/diskstats``."""
        totals = {"read_sectors": 0, "write_sectors": 0, "io_ms": 0}
        devices = self._read_whole_disk_names()
        try:
            with open(f"{self._proc_root}/diskstats", encoding="utf-8") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 14:
                        continue
                    name = parts[2]
                    if devices is not None:
                        if name not in devices:
                            continue
                    elif not self._looks_like_whole_disk(name):
                        continue
                    try:
                        totals["read_sectors"] += int(parts[5])
                        totals["write_sectors"] += int(parts[9])
                        totals["io_ms"] += int(parts[12])
                    except ValueError:
                        continue
        except OSError as exc:
            logger.debug("Can't read /proc/diskstats: %s", exc)
        return totals

    def _read_whole_disk_names(self) -> set[str] | None:
        """Return whole block-device names from sysfs, or ``None`` if unavailable."""
        block_dir = f"{self._sys_root}/class/block"
        try:
            if not os.path.isdir(block_dir):
                return None
            devices: set[str] = set()
            for name in os.listdir(block_dir):
                if not self._looks_like_whole_disk(name):
                    continue
                if os.path.exists(f"{block_dir}/{name}/partition"):
                    continue
                devices.add(name)
            return devices
        except OSError:
            return None

    @staticmethod
    def _looks_like_whole_disk(name: str) -> bool:
        """Best-effort filter for real whole disks, excluding partitions."""
        if name.startswith(("loop", "ram", "zram", "fd")):
            return False
        if re.fullmatch(r"nvme\d+n\d+", name):
            return True
        if re.fullmatch(r"mmcblk\d+", name):
            return True
        if re.fullmatch(r"(sd|vd|xvd|hd)[a-z]+", name):
            return True
        if re.fullmatch(r"dm-\d+", name):
            return True
        return bool(name) and not name[-1].isdigit()

    # ------------------------------------------------------------------
    # /proc readers
    # ------------------------------------------------------------------

    def _read_meminfo(self) -> dict[str, int]:
        """Read ``/proc/meminfo`` → ``{field: bytes}``."""
        out: dict[str, int] = {}
        try:
            with open(f"{self._proc_root}/meminfo", encoding="utf-8") as f:
                for line in f:
                    if ":" not in line:
                        continue
                    key, rest = line.split(":", 1)
                    tokens = rest.strip().split()
                    if not tokens:
                        continue
                    try:
                        out[key.strip()] = int(tokens[0]) * 1024  # kB → bytes
                    except ValueError:
                        continue
        except OSError as exc:
            logger.debug("Can't read /proc/meminfo: %s", exc)
        return out

    def _read_cpu_stats(self) -> dict[str, int]:
        """Read first line of ``/proc/stat`` → ``{total, idle}`` ticks."""
        result: dict[str, int] = {"total": 0, "idle": 0}
        try:
            with open(f"{self._proc_root}/stat", encoding="utf-8") as f:
                line = f.readline()
            if not line.startswith("cpu "):
                return result
            parts = line.split()
            nums = []
            for p in parts[1:]:
                try:
                    nums.append(int(p))
                except ValueError:
                    continue
            if nums:
                # fields: user nice system idle iowait irq softirq steal guest guest_nice
                result["total"] = sum(nums)
                result["idle"] = nums[3] if len(nums) > 3 else 0
        except OSError as exc:
            logger.debug("Can't read /proc/stat: %s", exc)
        return result

    def _read_processes(
        self,
        cur_cpu: dict[str, int],
        prev_cpu: dict[str, int] | None,
        top_limit: int,
    ) -> list[dict[str, Any]]:
        """
        Return top *top_limit* processes sorted by CPU percent of total capacity.

        Uses the delta between previously-stored per-process ticks and the
        current ticks.  The denominator is the total-system CPU tick delta.

        Each entry::

            {"pid": int, "name": str, "display_name": str | None,
             "detail": str | None,
             "cpu_percent": float, "memory_rss_bytes": int,
             "memory_percent": float}

        ``detail`` is an optional longer description (e.g. full command line)
        suitable for tooltips.  Returns an empty list on the first call
        (warming).
        """
        # Read current per-process data
        cur_proc: dict[int, tuple[str, int]] = {}
        try:
            for entry in os.listdir(self._proc_root):
                if not entry.isdigit():
                    continue
                pid = int(entry)
                name, utime, stime = self._read_proc_stat(pid)
                if name is None:
                    continue
                cur_proc[pid] = (name, utime + stime)
            self._last_process_scan_count = len(cur_proc)
        except OSError as exc:
            logger.debug("Can't enumerate /proc: %s", exc)
            self._last_process_scan_count = 0
            return []

        # First call – store as baseline and return nothing.
        if not self._prev_proc_info:
            self._prev_proc_info = cur_proc
            return []

        total_delta = cur_cpu["total"] - (
            prev_cpu or self._prev_cpu or {}
        ).get("total", cur_cpu["total"])
        if total_delta <= 0:
            self._prev_proc_info = cur_proc
            return []

        ram_total = self._read_meminfo().get("MemTotal", 0)
        candidates: list[tuple[float, int, str]] = []

        # Cache for cmdline reads (lazy, per pid).
        # Values are (display_name, detail_or_None) or None for unresolvable.
        cmdline_cache: dict[int, tuple[str, str | None] | None] = {}

        for pid, (cur_name, cur_clk) in cur_proc.items():
            prev_data = self._prev_proc_info.get(pid)
            if prev_data is None:
                continue

            prev_name, prev_clk = prev_data
            clk_delta = cur_clk - prev_clk
            if clk_delta <= 0:
                continue

            cpu_pct = min(100.0, max(0.0, clk_delta / total_delta * 100.0))
            candidates.append((cpu_pct, pid, cur_name))

        candidates.sort(key=lambda item: item[0], reverse=True)
        detail_limit = max(top_limit, min(len(candidates), top_limit * 4))
        processes: list[dict[str, Any]] = []

        for cpu_pct, pid, cur_name in candidates[:detail_limit]:
            rss = self._read_proc_rss(pid)
            mem_pct = _pct(rss, ram_total)

            # Resolve a more descriptive display name via cmdline
            display_name, detail = self._resolve_display_name(
                pid, cur_name, cmdline_cache
            )

            processes.append(
                {
                    "pid": pid,
                    "name": cur_name,
                    "display_name": display_name,
                    "detail": detail,
                    "cpu_percent": _r(cpu_pct),
                    "memory_rss_bytes": rss,
                    "memory_percent": _r(mem_pct),
                }
            )

        self._prev_proc_info = cur_proc
        return processes[:top_limit]

    @staticmethod
    def _truncate_display_name(name: str, max_len: int = 64) -> str:
        """Truncate an overly long display name, preserving the end suffix if helpful."""
        if len(name) <= max_len:
            return name
        return f"{name[: max_len - 3]}..."

    def _resolve_display_name(
        self,
        pid: int,
        comm: str,
        cache: dict[int, tuple[str, str | None] | None],
    ) -> tuple[str, str | None]:
        """
        Return ``(display_name, detail)`` for a process.

        ``display_name`` is a human-readable process name (e.g. ``chrome
        renderer``, ``WebPage.py``).  ``detail`` is an optional longer string
        (truncated full command line) for tooltips.

        For common interpreters (python, node, java, etc.) reads
        ``/proc/<pid>/cmdline`` to find the script or module being run.
        Chrome-family processes are classified by ``--type=`` switch.

        Falls back to ``(comm, None)`` if cmdline is unavailable or unhelpful.

        Handles the fact that some processes (e.g. Chrome subprocesses) write
        their cmdline with space separators instead of NUL bytes.
        """
        if pid in cache:
            cached = cache[pid]
            if cached is not None:
                return cached
            return comm, None

        try:
            with open(f"{self._proc_root}/{pid}/cmdline", "rb") as f:
                raw = f.read()
        except OSError:
            cache[pid] = None
            return comm, None

        if not raw:
            cache[pid] = None
            return comm, None

        # Try NUL-separated first.
        # Some processes (e.g. Chrome subprocesses) write space-separated
        # cmdline with NUL padding, so when NUL-split yields a single arg
        # containing spaces we re-split by spaces.
        if b"\x00" in raw:
            args = [
                a.decode("utf-8", errors="replace")
                for a in raw.split(b"\x00")
                if a
            ]
            if len(args) == 1 and " " in args[0]:
                args = args[0].split()
        else:
            args = raw.decode("utf-8", errors="replace").split()

        if not args:
            cache[pid] = None
            return comm, None

        # Build a compact command-line detail for tooltips
        detail = self._truncate_display_name(" ".join(args), max_len=120)

        interpreter_bin = os.path.basename(args[0]).lower() if args[0] else ""
        interpreters = {
            "python", "python3", "node", "java", "ruby",
            "perl", "bash", "sh", "zsh",
        }

        if interpreter_bin in interpreters and len(args) > 1:
            for arg in args[1:]:
                if arg.startswith("-"):
                    continue
                script = os.path.basename(arg)
                if script:
                    display = self._truncate_display_name(script)
                    cache[pid] = (display, detail)
                    return display, detail

        # Check Chrome-family browser – returns role label such as
        # "chrome renderer" or None if not a browser process.
        chrome_label = _classify_chrome_process(args)
        if chrome_label:
            cache[pid] = (chrome_label, detail)
            return chrome_label, detail

        # For non-interpreters, use the binary basename
        binary = os.path.basename(args[0])
        if binary:
            display = self._truncate_display_name(binary)
            cache[pid] = (display, detail)
            return display, detail

        cache[pid] = None
        return comm, None

    # ------------------------------------------------------------------
    # Single-process readers
    # ------------------------------------------------------------------

    def _read_proc_stat(self, pid: int) -> tuple[str | None, int, int]:
        """
        Read ``/proc/<pid>/stat`` → ``(name, utime, stime)``.

        Returns ``(None, 0, 0)`` on any error (missing PID, permission).
        """
        try:
            with open(f"{self._proc_root}/{pid}/stat", encoding="utf-8") as f:
                raw = f.read()
        except OSError:
            return None, 0, 0

        try:
            name_end = raw.rfind(")")
            if name_end == -1:
                return None, 0, 0
            name_start = raw.index("(") + 1
            name = raw[name_start:name_end]
            after = raw[name_end + 2 :].split()  # skip ") "
            utime = int(after[11]) if len(after) > 11 else 0
            stime = int(after[12]) if len(after) > 12 else 0
            return name, utime, stime
        except (ValueError, IndexError):
            return None, 0, 0

    def _read_proc_rss(self, pid: int) -> int:
        """Return RSS in bytes from ``/proc/<pid>/status``, or 0."""
        try:
            with open(f"{self._proc_root}/{pid}/status", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            return int(parts[1]) * 1024  # kB → bytes
        except OSError:
            pass
        return 0


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _pct(part: float, total: float) -> float:
    """``(part / total) * 100`` or 0."""
    return (part / total * 100.0) if total > 0 else 0.0


def _r(v: float | None) -> float | None:
    """Round to 1 decimal place or return None."""
    return round(v, 1) if v is not None else None
