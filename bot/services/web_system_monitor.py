"""
Web system monitor service — reads host snapshots persisted by the bot.

The bot container (which has ``pid: host`` in Docker) runs a background loop
that collects real host CPU/RAM and top processes and writes them to the
``web_system_status`` database table.  This service reads that table and
returns the latest snapshot to the Flask endpoint.

If the persisted snapshot is missing or stale (older than 5 s) the service
returns ``"available": false`` with ``"status_label": "Waiting for host monitor"``.

Dev fallback
~~~~~~~~~~~~
Set ``WEB_SYSTEM_MONITOR_ALLOW_WEB_PROC_FALLBACK=1`` to fall back to reading
``/proc`` from the web container directly.  This is only useful when the web
container also has ``pid: host`` and is not the recommended configuration.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from bot.repositories.web_system_status import WebSystemStatusRepository

logger = logging.getLogger(__name__)


class WebSystemMonitorService:
    """
    System-resource monitor for the web control room.

    Reads the latest host snapshot persisted by the bot background loop.

    Usage::

        svc = WebSystemMonitorService(repository=WebSystemStatusRepository(db_path=...))
        snap = svc.get_snapshot(top_limit=4)
    """

    def __init__(
        self,
        repository: Optional[WebSystemStatusRepository] = None,
        db_path: Optional[str] = None,
    ) -> None:
        """
        Args:
            repository: A ``WebSystemStatusRepository`` instance.  If not provided
                and *db_path* is given, one is created.
            db_path: Path to the SQLite database.  Used only when *repository* is
                not provided.
        """
        self._repo = repository or (
            WebSystemStatusRepository(db_path=db_path, use_shared=False)
            if db_path
            else None
        )

        # Two-sample state for the optional web /proc fallback.
        self._prev_cpu: dict[str, int] | None = None
        self._prev_proc_info: dict[int, tuple[str, int]] = {}
        self._prev_timestamp: float | None = None
        self._fallback_mode = os.getenv(
            "WEB_SYSTEM_MONITOR_ALLOW_WEB_PROC_FALLBACK", "0"
        ).strip().lower() in {"1", "true", "yes", "on"}
        if self._fallback_mode:
            logger.warning(
                "WebSystemMonitorService is in fallback /proc mode. "
                "Install pid: host on the web container for real host data."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_snapshot(self, top_limit: int = 4) -> dict[str, Any]:
        """
        Return a JSON-safe system-resource snapshot.

        First tries the persisted bot-side snapshot.  Falls back to reading
        ``/proc`` from the web container only when
        ``WEB_SYSTEM_MONITOR_ALLOW_WEB_PROC_FALLBACK=1``.

        Args:
            top_limit: Number of top CPU-consuming processes to include
                       (clamped 1–8).

        Returns:
            Dict with keys:

            - ``available`` (*bool*)
            - ``total_cpu_percent`` (*float* | *None*)
            - ``ram_total_bytes`` (*int*)
            - ``ram_available_bytes`` (*int*)
            - ``ram_used_bytes`` (*int*)
            - ``ram_percent`` (*float*)
            - ``cpu_warming`` (*bool*)
            - ``sample_interval_seconds`` (*float*)
            - ``updated_at_unix`` (*float*)
            - ``top_processes`` (*list*)
            - ``status_label`` (*str*, only when *available* is *False*)
            - ``error`` (*str*, only when *available* is *False*)
        """
        top_limit = max(1, min(8, top_limit))

        # Preferred path: read from the persisted bot-side snapshot.
        if self._repo is not None:
            snapshot = self._repo.get_latest_snapshot(max_age_seconds=5)
            if snapshot is not None:
                return {
                    **snapshot,
                    "top_processes": (snapshot.get("top_processes") or [])[:top_limit],
                }

            # Snapshot missing or stale.
            return {
                "available": False,
                "status_label": "Waiting for host monitor",
                "error": "Host snapshot unavailable",
                "total_cpu_percent": None,
                "ram_total_bytes": 0,
                "ram_available_bytes": 0,
                "ram_used_bytes": 0,
                "ram_percent": 0.0,
                "cpu_warming": True,
                "sample_interval_seconds": 0.0,
                "updated_at_unix": time.time(),
                "top_processes": [],
            }

        # No repository — try fallback /proc reading if enabled.
        if self._fallback_mode:
            return self._get_fallback_snapshot(top_limit)

        return {
            "available": False,
            "status_label": "No monitor backend",
            "error": "No database repository and fallback is disabled",
            "total_cpu_percent": None,
            "ram_total_bytes": 0,
            "ram_available_bytes": 0,
            "ram_used_bytes": 0,
            "ram_percent": 0.0,
            "cpu_warming": True,
            "sample_interval_seconds": 0.0,
            "updated_at_unix": time.time(),
            "top_processes": [],
        }

    # ------------------------------------------------------------------
    # Fallback /proc reader (only when env var allows)
    # ------------------------------------------------------------------

    @staticmethod
    def _proc_root() -> str:
        """Return the /proc filesystem root (overridable via env var)."""
        return os.getenv("WEB_SYSTEM_MONITOR_PROCFS_ROOT", "/proc")

    def _get_fallback_snapshot(self, top_limit: int) -> dict[str, Any]:
        """Read /proc from the web container (two-sample)."""
        try:
            ts = time.time()
            mem = self._read_meminfo_fallback()
            cur_cpu = self._read_cpu_stats_fallback()

            ram_total = mem.get("MemTotal", 0)
            ram_avail = mem.get("MemAvailable", ram_total)
            ram_used = max(0, ram_total - ram_avail)
            ram_pct = _pct(ram_used, ram_total)

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

            processes = self._read_processes_fallback(cur_cpu, prev_cpu, top_limit)

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
            }
        except Exception as exc:
            logger.warning("Web fallback system monitor unavailable: %s", exc)
            return {
                "available": False,
                "status_label": "Web fallback unavailable",
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
            }

    @staticmethod
    def _read_meminfo_fallback() -> dict[str, int]:
        """Read /proc/meminfo from the web container."""
        out: dict[str, int] = {}
        proc_root = WebSystemMonitorService._proc_root()
        try:
            with open(f"{proc_root}/meminfo", encoding="utf-8") as f:
                for line in f:
                    if ":" not in line:
                        continue
                    key, rest = line.split(":", 1)
                    tokens = rest.strip().split()
                    if not tokens:
                        continue
                    try:
                        out[key.strip()] = int(tokens[0]) * 1024
                    except ValueError:
                        continue
        except OSError as exc:
            logger.debug("Can't read /proc/meminfo: %s", exc)
        return out

    @staticmethod
    def _read_cpu_stats_fallback() -> dict[str, int]:
        """Read first line of /proc/stat from the web container."""
        result: dict[str, int] = {"total": 0, "idle": 0}
        proc_root = WebSystemMonitorService._proc_root()
        try:
            with open(f"{proc_root}/stat", encoding="utf-8") as f:
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
                result["total"] = sum(nums)
                result["idle"] = nums[3] if len(nums) > 3 else 0
        except OSError as exc:
            logger.debug("Can't read /proc/stat: %s", exc)
        return result

    @staticmethod
    def _read_proc_stat_fallback(pid: int) -> tuple[str | None, int, int]:
        """Read /proc/<pid>/stat from the web container."""
        proc_root = WebSystemMonitorService._proc_root()
        try:
            with open(f"{proc_root}/{pid}/stat", encoding="utf-8") as f:
                raw = f.read()
        except OSError:
            return None, 0, 0
        try:
            name_end = raw.rfind(")")
            if name_end == -1:
                return None, 0, 0
            name_start = raw.index("(") + 1
            name = raw[name_start:name_end]
            after = raw[name_end + 2 :].split()
            utime = int(after[11]) if len(after) > 11 else 0
            stime = int(after[12]) if len(after) > 12 else 0
            return name, utime, stime
        except (ValueError, IndexError):
            return None, 0, 0

    @staticmethod
    def _read_proc_rss_fallback(pid: int) -> int:
        """Return RSS in bytes from /proc/<pid>/status."""
        proc_root = WebSystemMonitorService._proc_root()
        try:
            with open(f"{proc_root}/{pid}/status", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            return int(parts[1]) * 1024
        except OSError:
            pass
        return 0

    def _read_processes_fallback(
        self,
        cur_cpu: dict[str, int],
        prev_cpu: dict[str, int] | None,
        top_limit: int,
    ) -> list[dict[str, Any]]:
        """Read per-process data from the web container /proc (two-sample)."""
        proc_root = self._proc_root()
        cur_proc: dict[int, tuple[str, int]] = {}
        try:
            for entry in os.listdir(proc_root):
                if not entry.isdigit():
                    continue
                pid = int(entry)
                name, utime, stime = self._read_proc_stat_fallback(pid)
                if name is None:
                    continue
                cur_proc[pid] = (name, utime + stime)
        except OSError as exc:
            logger.debug("Can't enumerate /proc: %s", exc)
            return []

        if not self._prev_proc_info:
            self._prev_proc_info = cur_proc
            return []

        total_delta = cur_cpu["total"] - (
            prev_cpu or self._prev_cpu or {}
        ).get("total", cur_cpu["total"])
        if total_delta <= 0:
            self._prev_proc_info = cur_proc
            return []

        ram_total = self._read_meminfo_fallback().get("MemTotal", 0)
        processes: list[dict[str, Any]] = []

        for pid, (cur_name, cur_clk) in cur_proc.items():
            prev_data = self._prev_proc_info.get(pid)
            if prev_data is None:
                continue

            _, prev_clk = prev_data
            clk_delta = cur_clk - prev_clk
            if clk_delta <= 0:
                continue

            cpu_pct = min(100.0, max(0.0, clk_delta / total_delta * 100.0))
            rss = self._read_proc_rss_fallback(pid)
            mem_pct = _pct(rss, ram_total)

            processes.append(
                {
                    "pid": pid,
                    "name": cur_name,
                    "display_name": None,
                    "cpu_percent": _r(cpu_pct),
                    "memory_rss_bytes": rss,
                    "memory_percent": _r(mem_pct),
                }
            )

        self._prev_proc_info = cur_proc
        processes.sort(key=lambda p: p["cpu_percent"], reverse=True)
        return processes[:top_limit]


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _pct(part: float, total: float) -> float:
    """``(part / total) * 100`` or 0."""
    return (part / total * 100.0) if total > 0 else 0.0


def _r(v: float | None) -> float | None:
    """Round to 1 decimal place or return None."""
    return round(v, 1) if v is not None else None
