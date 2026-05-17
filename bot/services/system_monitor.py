"""
Host system monitor service for the bot side (has ``pid: host`` in Docker).

Provides total CPU/RAM and top per-process CPU usage by reading ``/proc/stat``,
``/proc/meminfo``, ``/proc/[pid]/stat``, ``/proc/[pid]/status``, and
``/proc/[pid]/cmdline``.  Preserves two-sample semantics: the first call
warms and returns ``cpu_warming: true`` with an empty process list.

Process display names are improved by reading ``cmdline``: for Python processes
the script basename is used (e.g. ``PersonalGreeter.py``) instead of the generic
``python``; for other interpreters the script/module basename is preferred.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)


class HostSystemMonitorService:
    """
    Two-sample host system-resource monitor reading from ``/proc``.

    Stores previous aggregate CPU ticks and per-process (utime+stime) counters
    between calls so the second and subsequent calls can compute deltas.

    Usage::

        svc = HostSystemMonitorService()
        snap = svc.get_snapshot(top_limit=4)
    """

    def __init__(self, proc_root: str | None = None) -> None:
        """
        Args:
            proc_root: Override the ``/proc`` mount point (for testing).
                Defaults to the ``HOST_SYSTEM_MONITOR_PROCFS_ROOT`` env var
                or ``/proc``.
        """
        self._proc_root: str = proc_root or os.getenv(
            "HOST_SYSTEM_MONITOR_PROCFS_ROOT", "/proc"
        )
        # Previous aggregate CPU counters: {"total": int, "idle": int}
        self._prev_cpu: dict[str, int] | None = None
        # Previous per-process data: {pid: (comm, utime+stime)}
        self._prev_proc_info: dict[int, tuple[str, int]] = {}
        self._prev_timestamp: float | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_snapshot(self, top_limit: int = 4) -> dict[str, Any]:
        """
        Return a JSON-safe host system-resource snapshot.

        Args:
            top_limit: Number of top CPU-consuming processes to include
                (clamped 1–8).

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
            - ``error`` (*str*, only when ``available`` is *False*)
        """
        top_limit = max(1, min(8, top_limit))

        try:
            ts = time.time()
            mem = self._read_meminfo()
            cur_cpu = self._read_cpu_stats()

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
            processes = self._read_processes(cur_cpu, prev_cpu, top_limit)

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
            }

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
             "cpu_percent": float, "memory_rss_bytes": int,
             "memory_percent": float}

        Returns an empty list on the first call (warming).
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
        except OSError as exc:
            logger.debug("Can't enumerate /proc: %s", exc)
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
        processes: list[dict[str, Any]] = []

        # Cache for cmdline reads (lazy, per pid)
        cmdline_cache: dict[int, str | None] = {}

        for pid, (cur_name, cur_clk) in cur_proc.items():
            prev_data = self._prev_proc_info.get(pid)
            if prev_data is None:
                continue

            prev_name, prev_clk = prev_data
            clk_delta = cur_clk - prev_clk
            if clk_delta <= 0:
                continue

            cpu_pct = min(100.0, max(0.0, clk_delta / total_delta * 100.0))
            rss = self._read_proc_rss(pid)
            mem_pct = _pct(rss, ram_total)

            # Resolve a more descriptive display name via cmdline
            display_name = self._resolve_display_name(pid, cur_name, cmdline_cache)

            processes.append(
                {
                    "pid": pid,
                    "name": cur_name,
                    "display_name": display_name,
                    "cpu_percent": _r(cpu_pct),
                    "memory_rss_bytes": rss,
                    "memory_percent": _r(mem_pct),
                }
            )

        self._prev_proc_info = cur_proc
        processes.sort(key=lambda p: p["cpu_percent"], reverse=True)
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
        cache: dict[int, str | None],
    ) -> str:
        """
        Return a more descriptive display name for a process.

        For common interpreters (python, node, java, etc.) reads
        ``/proc/<pid>/cmdline`` to find the script or module being run.
        Falls back to the raw ``comm`` (process name from ``/proc/pid/stat``)
        if cmdline is unavailable or unhelpful.

        Handles the fact that some processes (e.g. Chrome subprocesses) write
        their cmdline with space separators instead of NUL bytes.
        """
        if pid in cache:
            return cache[pid] if cache[pid] else comm

        try:
            with open(f"{self._proc_root}/{pid}/cmdline", "rb") as f:
                raw = f.read()
        except OSError:
            cache[pid] = None
            return comm

        if not raw:
            cache[pid] = None
            return comm

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
            return comm

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
                    cache[pid] = self._truncate_display_name(script)
                    return cache[pid]

        # For non-interpreters, use the binary basename
        binary = os.path.basename(args[0])
        if binary:
            cache[pid] = self._truncate_display_name(binary)
            return cache[pid]

        cache[pid] = None
        return comm

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
