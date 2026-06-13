"""
Tests for HostSystemMonitorService using a fake /proc tree.

Also tests WebSystemMonitorService with a mocked repository.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from bot.services.system_monitor import HostSystemMonitorService
from bot.services.web_system_monitor import WebSystemMonitorService


# ======================================================================
# Fake /proc helpers
# ======================================================================


def _write_proc(root: Path, path: str, content: str) -> None:
    """Write *content* to *path* under *root*, creating parent dirs."""
    full = root / path.lstrip("/")
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def _write_proc_binary(root: Path, path: str, content: bytes) -> None:
    """Write binary *content* to *path* under *root*."""
    full = root / path.lstrip("/")
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(content)


def _make_proc_tree(
    root: Path,
    *,
    mem_total_kb: int = 16777216,
    mem_avail_kb: int = 8388608,
    cpu_fields: tuple[int, ...] = (100, 50, 25, 800, 10, 0, 0, 0, 0, 0),
    processes: dict[int, tuple[str, int, int, int]] | None = None,
    diskstats: str | None = None,
) -> None:
    """
    Populate a fake /proc directory under *root*.

    *processes* maps pid → (name, utime, stime, vm_rss_kb).
    """
    _write_proc(root, "meminfo", f"MemTotal:       {mem_total_kb} kB\nMemAvailable:    {mem_avail_kb} kB\n")
    field_str = " ".join(str(v) for v in cpu_fields)
    _write_proc(root, "stat", f"cpu  {field_str}\n")
    if diskstats is not None:
        _write_proc(root, "diskstats", diskstats)

    if processes:
        for pid, (name, utime, stime, rss_kb) in processes.items():
            _write_proc(
                root,
                f"{pid}/stat",
                f"{pid} ({name}) R 1 2 3 4 5 6 7 8 9 10 {utime} {stime}\n",
            )
            _write_proc(
                root,
                f"{pid}/status",
                f"Name:\t{name}\nVmRSS:\t{rss_kb} kB\n",
            )
            # Write a minimal cmdline so display_name resolution works
            _write_proc(
                root,
                f"{pid}/cmdline",
                f"/usr/bin/{name}\x00",
            )


def _make_power_supply(root: Path, name: str, supply_type: str, capacity: str) -> None:
    """Create a fake sysfs power-supply entry."""
    supply_root = root / "class" / "power_supply" / name
    supply_root.mkdir(parents=True, exist_ok=True)
    (supply_root / "type").write_text(supply_type, encoding="utf-8")
    (supply_root / "capacity").write_text(capacity, encoding="utf-8")


# ======================================================================
# HostSystemMonitorService — RAM
# ======================================================================


def test_ram_totals_available(tmp_path):
    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    _make_proc_tree(tmp_path, mem_total_kb=16777216, mem_avail_kb=8388608)

    snap = svc.get_snapshot()

    assert snap["available"] is True
    assert snap["ram_total_bytes"] == 16777216 * 1024
    assert snap["ram_available_bytes"] == 8388608 * 1024
    assert snap["ram_used_bytes"] == (16777216 - 8388608) * 1024
    assert snap["ram_percent"] == 50.0


# ======================================================================
# HostSystemMonitorService — CPU
# ======================================================================


def test_first_cpu_call_warms(tmp_path):
    cpu = (200, 100, 50, 1600, 20, 0, 0, 0, 0, 0)
    _make_proc_tree(tmp_path, cpu_fields=cpu)

    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    snap = svc.get_snapshot()

    assert snap["cpu_warming"] is True
    assert snap["total_cpu_percent"] is None
    assert snap["top_processes"] == []


def test_second_cpu_call_computes_percent(tmp_path):
    cpu1 = (200, 100, 50, 1600, 20, 0, 0, 0, 0, 0)
    cpu2 = (400, 200, 100, 2400, 40, 0, 0, 0, 0, 0)
    _make_proc_tree(tmp_path, cpu_fields=cpu1)

    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()  # warm-up

    _make_proc_tree(tmp_path, cpu_fields=cpu2)
    snap = svc.get_snapshot()

    assert snap["cpu_warming"] is False
    assert snap["total_cpu_percent"] is not None
    assert 30.0 < snap["total_cpu_percent"] < 33.0


def test_disk_io_delta_reports_active_percent_and_speeds(tmp_path):
    cpu1 = (200, 100, 50, 1600, 20, 0, 0, 0, 0, 0)
    cpu2 = (400, 200, 100, 2400, 40, 0, 0, 0, 0, 0)
    disk1 = "   8       0 sda 10 0 1000 0 20 0 2000 0 0 100 0\n"
    disk2 = "   8       0 sda 15 0 3000 0 27 0 5000 0 0 350 0\n"
    _make_proc_tree(tmp_path, cpu_fields=cpu1, diskstats=disk1)

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    with patch("bot.services.system_monitor.time.time", side_effect=[1000.0, 1001.0]):
        warm = svc.get_snapshot()
        _make_proc_tree(tmp_path, cpu_fields=cpu2, diskstats=disk2)
        snap = svc.get_snapshot()

    assert warm["disk_active_percent"] is None
    assert snap["disk_active_percent"] == 25.0
    assert snap["disk_read_bytes_per_second"] == 1_024_000.0
    assert snap["disk_write_bytes_per_second"] == 1_536_000.0


# ======================================================================
# HostSystemMonitorService — Processes
# ======================================================================


def test_process_cpu_percent_sorted_descending(tmp_path):
    cpu1 = (1000, 500, 250, 8000, 50, 0, 0, 0, 0, 0)
    cpu2 = (2000, 1000, 500, 12000, 100, 0, 0, 0, 0, 0)

    procs = {
        101: ("nginx", 100, 50, 4096),
        102: ("python", 200, 100, 8192),
        103: ("bash", 10, 5, 512),
    }

    _make_proc_tree(tmp_path, cpu_fields=cpu1, processes=procs)
    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()  # warm-up

    procs2 = {
        101: ("nginx", 250, 125, 4096),
        102: ("python", 600, 300, 8192),
        103: ("bash", 15, 8, 512),
    }
    _make_proc_tree(tmp_path, cpu_fields=cpu2, processes=procs2)
    snap = svc.get_snapshot()

    assert snap["cpu_warming"] is False
    processes = snap["top_processes"]
    assert len(processes) == 3
    assert processes[0]["pid"] == 102  # python – highest delta
    assert processes[1]["pid"] == 101  # nginx
    assert processes[2]["pid"] == 103  # bash

    # Check values for processes[0] (python)
    assert processes[0]["name"] == "python"
    assert 10.0 <= processes[0]["cpu_percent"] <= 11.0
    assert processes[0]["memory_rss_bytes"] == 8192 * 1024

    assert 3.5 <= processes[1]["cpu_percent"] <= 4.5
    assert 0.0 < processes[2]["cpu_percent"] <= 0.3


def test_process_detail_reads_limited_to_top_candidates(tmp_path, monkeypatch):
    """RSS/cmdline detail reads are limited after CPU candidates are sorted."""
    cpu1 = (1000, 0, 0, 9000, 0, 0, 0, 0, 0, 0)
    cpu2 = (2000, 0, 0, 18000, 0, 0, 0, 0, 0, 0)
    procs1 = {
        pid: (f"proc{pid}", 10, 0, 1000)
        for pid in range(100, 140)
    }
    procs2 = {
        pid: (f"proc{pid}", 10 + (pid - 99), 0, 1000)
        for pid in range(100, 140)
    }

    _make_proc_tree(tmp_path, cpu_fields=cpu1, processes=procs1)
    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot(top_limit=4)

    _make_proc_tree(tmp_path, cpu_fields=cpu2, processes=procs2)
    rss_calls = []
    display_calls = []

    def fake_rss(pid):
        rss_calls.append(pid)
        return 1024

    def fake_display(pid, name, cache):
        display_calls.append(pid)
        return name, None

    monkeypatch.setattr(svc, "_read_proc_rss", fake_rss)
    monkeypatch.setattr(svc, "_resolve_display_name", fake_display)

    snap = svc.get_snapshot(top_limit=4)

    assert len(snap["top_processes"]) == 4
    assert len(rss_calls) == 16
    assert len(display_calls) == 16
    assert [proc["pid"] for proc in snap["top_processes"]] == [139, 138, 137, 136]


def test_top_limit_clamps(tmp_path):
    cpu1 = (100, 50, 25, 800, 10, 0, 0, 0, 0, 0)
    cpu2 = (200, 100, 50, 1200, 20, 0, 0, 0, 0, 0)

    procs = {i: (f"proc{i}", 10 * i, 5 * i, 1024) for i in range(101, 110)}
    _make_proc_tree(tmp_path, cpu_fields=cpu1, processes=procs)
    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()

    procs2 = {i: (f"proc{i}", 20 * i, 10 * i, 1024) for i in range(101, 110)}
    _make_proc_tree(tmp_path, cpu_fields=cpu2, processes=procs2)
    svc.get_snapshot()

    snap3 = svc.get_snapshot(top_limit=3)
    assert len(snap3["top_processes"]) <= 3


def test_top_limit_zero_skips_process_scan(tmp_path):
    """top_limit=0 avoids the expensive per-process /proc scan."""
    cpu1 = (100, 50, 25, 800, 10, 0, 0, 0, 0, 0)
    cpu2 = (200, 100, 50, 1200, 20, 0, 0, 0, 0, 0)
    procs = {101: ("python", 10, 5, 1024)}
    _make_proc_tree(tmp_path, cpu_fields=cpu1, processes=procs)

    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot(top_limit=4)

    _make_proc_tree(tmp_path, cpu_fields=cpu2, processes=procs)
    with patch.object(svc, "_read_processes") as read_processes:
        snap = svc.get_snapshot(top_limit=0)

    read_processes.assert_not_called()
    assert snap["top_processes"] == []
    assert snap["available"] is True


def test_include_sensors_false_skips_sensor_reads(tmp_path):
    """include_sensors=False avoids slower sysfs sensor probes."""
    _make_proc_tree(tmp_path)

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    with (
        patch.object(svc, "_read_cpu_temperature") as read_temp,
        patch.object(svc, "_read_cpu_fan_rpm") as read_fan,
        patch.object(svc, "_read_battery_percent") as read_battery,
    ):
        snap = svc.get_snapshot(include_sensors=False)

    read_temp.assert_not_called()
    read_fan.assert_not_called()
    read_battery.assert_not_called()
    assert snap["cpu_temperature_celsius"] is None
    assert snap["cpu_fan_rpm"] is None
    assert snap["battery_percent"] is None
    assert snap["available"] is True


def test_disappearing_pid_does_not_crash(tmp_path):
    import shutil

    cpu1 = (100, 50, 25, 800, 10, 0, 0, 0, 0, 0)
    cpu2 = (200, 100, 50, 1600, 20, 0, 0, 0, 0, 0)

    procs1 = {101: ("alpha", 100, 50, 2048), 102: ("beta", 50, 25, 1024)}
    _make_proc_tree(tmp_path, cpu_fields=cpu1, processes=procs1)
    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()

    procs2 = {102: ("beta", 150, 75, 1024)}
    shutil.rmtree(tmp_path / "101", ignore_errors=True)
    _make_proc_tree(tmp_path, cpu_fields=cpu2, processes=procs2)
    snap = svc.get_snapshot()

    assert snap["available"] is True
    assert len(snap["top_processes"]) == 1
    assert snap["top_processes"][0]["pid"] == 102


def test_bad_permissions_returns_available_zeros(tmp_path):
    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    snap = svc.get_snapshot()

    assert snap["available"] is True
    assert snap["ram_total_bytes"] == 0
    assert snap["cpu_warming"] is True


def test_get_snapshot_returns_json_safe_payload(tmp_path):
    _make_proc_tree(tmp_path)
    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    snap = svc.get_snapshot()
    json.dumps(snap)


def test_process_cpu_percent_of_total_capacity(tmp_path):
    cpu1 = (1000, 500, 250, 5000, 50, 0, 0, 0, 0, 0)
    cpu2 = (2000, 1000, 500, 8000, 100, 0, 0, 0, 0, 0)

    procs = {201: ("worker", 300, 150, 2048)}
    _make_proc_tree(tmp_path, cpu_fields=cpu1, processes=procs)
    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()

    procs2 = {201: ("worker", 2100, 1050, 2048)}
    _make_proc_tree(tmp_path, cpu_fields=cpu2, processes=procs2)
    snap = svc.get_snapshot()

    proc = snap["top_processes"][0]
    assert 55.0 <= proc["cpu_percent"] <= 58.0


# ======================================================================
# HostSystemMonitorService — cmdline display_name
# ======================================================================


def test_display_name_from_cmdline_python_script(tmp_path):
    """Python process should show the script basename from cmdline."""
    _write_proc(tmp_path, "meminfo", "MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n")
    _write_proc(tmp_path, "stat", "cpu  100 50 25 800 10 0 0 0 0 0\n")

    _write_proc(tmp_path, "101/stat", "101 (python) R 1 2 3 4 5 6 7 8 9 10 100 50\n")
    _write_proc(tmp_path, "101/status", "Name:\tpython\nVmRSS:\t4096 kB\n")
    _write_proc_binary(tmp_path, "101/cmdline", b"python3\x00/tmp/web_page.py\x00--port\x008080\x00")

    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    snap = svc.get_snapshot(top_limit=4)

    # First call warms
    assert snap["top_processes"] == []


def test_display_name_from_cmdline_second_call(tmp_path):
    """After warming, display_name should reflect the script basename."""
    _write_proc(tmp_path, "meminfo", "MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n")
    cpu1 = (100, 50, 25, 800, 10, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu1)}\n")
    _write_proc(tmp_path, "101/stat", "101 (python) R 1 2 3 4 5 6 7 8 9 10 100 50\n")
    _write_proc(tmp_path, "101/status", "Name:\tpython\nVmRSS:\t4096 kB\n")
    _write_proc_binary(tmp_path, "101/cmdline", b"python3\x00/tmp/web_page.py\x00--port\x008080\x00")

    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()  # warm-up

    cpu2 = (200, 100, 50, 1600, 20, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu2)}\n")
    _write_proc(tmp_path, "101/stat", "101 (python) R 1 2 3 4 5 6 7 8 9 10 200 100\n")

    snap = svc.get_snapshot()

    assert snap["available"] is True
    assert len(snap["top_processes"]) == 1
    proc = snap["top_processes"][0]
    assert proc["display_name"] == "web_page.py"
    assert proc["name"] == "python"


def test_display_name_falls_back_when_no_cmdline(tmp_path):
    """Process without readable cmdline should fall back to comm name."""
    _write_proc(tmp_path, "meminfo", "MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n")
    cpu1 = (100, 50, 25, 800, 10, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu1)}\n")
    _write_proc(tmp_path, "101/stat", "101 (nginx) R 1 2 3 4 5 6 7 8 9 10 100 50\n")
    _write_proc(tmp_path, "101/status", "Name:\tnginx\nVmRSS:\t2048 kB\n")
    # No cmdline file → fallback

    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()  # warm-up

    cpu2 = (200, 100, 50, 1600, 20, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu2)}\n")
    _write_proc(tmp_path, "101/stat", "101 (nginx) R 1 2 3 4 5 6 7 8 9 10 200 100\n")

    snap = svc.get_snapshot()

    assert snap["available"] is True
    proc = snap["top_processes"][0]
    # Without cmdline, display_name falls back to "nginx" (binary basename from stat)
    assert proc["name"] == "nginx"


def test_display_name_for_non_interpreter(tmp_path):
    """Non-interpreter processes should get the cmdline binary basename."""
    _write_proc(tmp_path, "meminfo", "MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n")
    cpu1 = (100, 50, 25, 800, 10, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu1)}\n")
    _write_proc(tmp_path, "101/stat", "101 (dockerd) R 1 2 3 4 5 6 7 8 9 10 100 50\n")
    _write_proc(tmp_path, "101/status", "Name:\tdockerd\nVmRSS:\t4096 kB\n")
    _write_proc_binary(tmp_path, "101/cmdline", b"/usr/bin/dockerd\x00-H\x00fd://\x00")

    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()  # warm-up

    cpu2 = (200, 100, 50, 1600, 20, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu2)}\n")
    _write_proc(tmp_path, "101/stat", "101 (dockerd) R 1 2 3 4 5 6 7 8 9 10 200 100\n")

    snap = svc.get_snapshot()
    proc = snap["top_processes"][0]
    assert proc["display_name"] == "dockerd"


# ======================================================================
# HostSystemMonitorService — Chrome process classification
# ======================================================================


def test_chrome_browser_process(tmp_path):
    """Chrome main process (no --type) → 'chrome browser'."""
    _write_proc(tmp_path, "meminfo", "MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n")
    cpu1 = (100, 50, 25, 800, 10, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu1)}\n")
    _write_proc(tmp_path, "101/stat", "101 (chrome) R 1 2 3 4 5 6 7 8 9 10 100 50\n")
    _write_proc(tmp_path, "101/status", "Name:\tchrome\nVmRSS:\t4096 kB\n")
    _write_proc_binary(
        tmp_path, "101/cmdline",
        b"/opt/google/chrome/chrome\x00--flag-switches-begin\x00",
    )

    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()  # warm-up

    cpu2 = (200, 100, 50, 1600, 20, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu2)}\n")
    _write_proc(tmp_path, "101/stat", "101 (chrome) R 1 2 3 4 5 6 7 8 9 10 200 100\n")

    snap = svc.get_snapshot()
    proc = snap["top_processes"][0]
    assert proc["display_name"] == "chrome browser"
    assert proc["name"] == "chrome"
    assert isinstance(proc["detail"], str)
    assert "chrome" in proc["detail"]


def test_chrome_renderer_process(tmp_path):
    """Chrome renderer → 'chrome renderer'."""
    _write_proc(tmp_path, "meminfo", "MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n")
    cpu1 = (100, 50, 25, 800, 10, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu1)}\n")
    _write_proc(tmp_path, "101/stat", "101 (chrome) R 1 2 3 4 5 6 7 8 9 10 100 50\n")
    _write_proc(tmp_path, "101/status", "Name:\tchrome\nVmRSS:\t4096 kB\n")
    _write_proc_binary(
        tmp_path, "101/cmdline",
        b"/opt/google/chrome/chrome\x00--type=renderer\x00--field-trial-handle=123\x00",
    )

    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()

    cpu2 = (200, 100, 50, 1600, 20, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu2)}\n")
    _write_proc(tmp_path, "101/stat", "101 (chrome) R 1 2 3 4 5 6 7 8 9 10 200 100\n")

    snap = svc.get_snapshot()
    proc = snap["top_processes"][0]
    assert proc["display_name"] == "chrome renderer"
    assert isinstance(proc["detail"], str)


def test_chrome_gpu_process(tmp_path):
    """Chrome GPU process → 'chrome GPU'."""
    _write_proc(tmp_path, "meminfo", "MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n")
    cpu1 = (100, 50, 25, 800, 10, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu1)}\n")
    _write_proc(tmp_path, "101/stat", "101 (chrome) R 1 2 3 4 5 6 7 8 9 10 100 50\n")
    _write_proc(tmp_path, "101/status", "Name:\tchrome\nVmRSS:\t4096 kB\n")
    _write_proc_binary(
        tmp_path, "101/cmdline",
        b"/opt/google/chrome/chrome\x00--type=gpu-process\x00",
    )

    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()

    cpu2 = (200, 100, 50, 1600, 20, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu2)}\n")
    _write_proc(tmp_path, "101/stat", "101 (chrome) R 1 2 3 4 5 6 7 8 9 10 200 100\n")

    snap = svc.get_snapshot()
    proc = snap["top_processes"][0]
    assert proc["display_name"] == "chrome GPU"


def test_chrome_utility_with_subtype(tmp_path):
    """Chrome utility with network subtype → 'chrome utility (Network)'."""
    _write_proc(tmp_path, "meminfo", "MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n")
    cpu1 = (100, 50, 25, 800, 10, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu1)}\n")
    _write_proc(tmp_path, "101/stat", "101 (chrome) R 1 2 3 4 5 6 7 8 9 10 100 50\n")
    _write_proc(tmp_path, "101/status", "Name:\tchrome\nVmRSS:\t4096 kB\n")
    _write_proc_binary(
        tmp_path, "101/cmdline",
        b"/opt/google/chrome/chrome\x00--type=utility\x00"
        b"--utility-sub-type=network.mojom.NetworkService\x00",
    )

    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()

    cpu2 = (200, 100, 50, 1600, 20, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu2)}\n")
    _write_proc(tmp_path, "101/stat", "101 (chrome) R 1 2 3 4 5 6 7 8 9 10 200 100\n")

    snap = svc.get_snapshot()
    proc = snap["top_processes"][0]
    assert proc["display_name"] == "chrome utility (Network)"


def test_chrome_renderer_extension(tmp_path):
    """Chrome extension renderer → 'chrome extension'."""
    _write_proc(tmp_path, "meminfo", "MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n")
    cpu1 = (100, 50, 25, 800, 10, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu1)}\n")
    _write_proc(tmp_path, "101/stat", "101 (chrome) R 1 2 3 4 5 6 7 8 9 10 100 50\n")
    _write_proc(tmp_path, "101/status", "Name:\tchrome\nVmRSS:\t4096 kB\n")
    _write_proc_binary(
        tmp_path, "101/cmdline",
        b"/opt/google/chrome/chrome\x00--type=renderer\x00"
        b"--extension-process\x00--extension-id=abc123\x00",
    )

    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()

    cpu2 = (200, 100, 50, 1600, 20, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu2)}\n")
    _write_proc(tmp_path, "101/stat", "101 (chrome) R 1 2 3 4 5 6 7 8 9 10 200 100\n")

    snap = svc.get_snapshot()
    proc = snap["top_processes"][0]
    assert proc["display_name"] == "chrome extension"


def test_chromium_browser_process(tmp_path):
    """Chromium browser (no --type) → 'chromium browser'."""
    _write_proc(tmp_path, "meminfo", "MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n")
    cpu1 = (100, 50, 25, 800, 10, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu1)}\n")
    _write_proc(tmp_path, "101/stat", "101 (chromium) R 1 2 3 4 5 6 7 8 9 10 100 50\n")
    _write_proc(tmp_path, "101/status", "Name:\tchromium\nVmRSS:\t4096 kB\n")
    _write_proc_binary(tmp_path, "101/cmdline", b"/usr/lib/chromium/chromium\x00")

    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()

    cpu2 = (200, 100, 50, 1600, 20, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu2)}\n")
    _write_proc(tmp_path, "101/stat", "101 (chromium) R 1 2 3 4 5 6 7 8 9 10 200 100\n")

    snap = svc.get_snapshot()
    proc = snap["top_processes"][0]
    assert proc["display_name"] == "chromium browser"


def test_brave_browser_gpu(tmp_path):
    """Brave GPU process → 'brave GPU'."""
    _write_proc(tmp_path, "meminfo", "MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n")
    cpu1 = (100, 50, 25, 800, 10, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu1)}\n")
    _write_proc(tmp_path, "101/stat", "101 (brave) R 1 2 3 4 5 6 7 8 9 10 100 50\n")
    _write_proc(tmp_path, "101/status", "Name:\tbrave\nVmRSS:\t4096 kB\n")
    _write_proc_binary(tmp_path, "101/cmdline", b"/usr/bin/brave-browser\x00--type=gpu-process\x00")

    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()

    cpu2 = (200, 100, 50, 1600, 20, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu2)}\n")
    _write_proc(tmp_path, "101/stat", "101 (brave) R 1 2 3 4 5 6 7 8 9 10 200 100\n")

    snap = svc.get_snapshot()
    proc = snap["top_processes"][0]
    assert proc["display_name"] == "brave GPU"


def test_chrome_process_detail_json_safe(tmp_path):
    """The detail field for chrome processes must be JSON-safe."""
    _write_proc(tmp_path, "meminfo", "MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n")
    cpu1 = (100, 50, 25, 800, 10, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu1)}\n")
    _write_proc(tmp_path, "101/stat", "101 (chrome) R 1 2 3 4 5 6 7 8 9 10 100 50\n")
    _write_proc(tmp_path, "101/status", "Name:\tchrome\nVmRSS:\t4096 kB\n")
    _write_proc_binary(
        tmp_path, "101/cmdline",
        b"/opt/google/chrome/chrome\x00--type=renderer\x00--some=flag\x00",
    )

    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()

    cpu2 = (200, 100, 50, 1600, 20, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu2)}\n")
    _write_proc(tmp_path, "101/stat", "101 (chrome) R 1 2 3 4 5 6 7 8 9 10 200 100\n")

    snap = svc.get_snapshot()
    # This will raise if any value is not serialisable.
    import json
    json.dumps(snap)


# ======================================================================
# HostSystemMonitorService — CPU temperature from sysfs
# ======================================================================


def _make_thermal_zone(root: Path, zone_num: int, zone_type: str, temp_millidegrees: int) -> None:
    """Create a thermal_zone directory under a fake sysfs tree."""
    tz_dir = root / "class" / "thermal" / f"thermal_zone{zone_num}"
    tz_dir.mkdir(parents=True, exist_ok=True)
    (tz_dir / "type").write_text(f"{zone_type}\n", encoding="utf-8")
    (tz_dir / "temp").write_text(f"{temp_millidegrees}\n", encoding="utf-8")


def _make_hwmon_device(
    root: Path,
    dev_num: int,
    name: str,
    temps: dict[str, tuple[int, str | None]],
) -> None:
    """Create a hwmon device under a fake sysfs tree.

    *temps* maps sensor index (e.g. ``"1"``) to ``(millidegrees, label_or_None)``.
    """
    dev_dir = root / "class" / "hwmon" / f"hwmon{dev_num}"
    dev_dir.mkdir(parents=True, exist_ok=True)
    (dev_dir / "name").write_text(f"{name}\n", encoding="utf-8")
    for idx, (millidegrees, label) in temps.items():
        (dev_dir / f"temp{idx}_input").write_text(f"{millidegrees}\n", encoding="utf-8")
        if label is not None:
            (dev_dir / f"temp{idx}_label").write_text(f"{label}\n", encoding="utf-8")


def _make_hwmon_fan_device(
    root: Path,
    dev_num: int,
    name: str,
    fans: dict[str, tuple[int, str | None]],
) -> None:
    """Create a hwmon device with fan inputs under a fake sysfs tree.

    *fans* maps sensor index (e.g. ``"1"``) to ``(rpm, label_or_None)``.
    """
    dev_dir = root / "class" / "hwmon" / f"hwmon{dev_num}"
    dev_dir.mkdir(parents=True, exist_ok=True)
    (dev_dir / "name").write_text(f"{name}\n", encoding="utf-8")
    for idx, (rpm, label) in fans.items():
        (dev_dir / f"fan{idx}_input").write_text(f"{rpm}\n", encoding="utf-8")
        if label is not None:
            (dev_dir / f"fan{idx}_label").write_text(f"{label}\n", encoding="utf-8")


def test_cpu_temperature_thermal_zone(tmp_path):
    """CPU temperature from a thermal_zone with CPU type is returned."""
    _make_proc_tree(tmp_path)
    _make_thermal_zone(tmp_path, 0, "x86_pkg_temp", 42000)

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    assert snap["cpu_temperature_celsius"] == 42.0


def test_cpu_temperature_hwmon_coretemp(tmp_path):
    """CPU temperature from a hwmon coretemp device."""
    _make_proc_tree(tmp_path)
    _make_hwmon_device(
        tmp_path, 0, "coretemp",
        {"1": (44000, "Package id 0"), "2": (41000, "Core 0"), "3": (39000, "Core 1")},
    )

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    assert snap["cpu_temperature_celsius"] == 44.0


def test_cpu_temperature_prefers_cpu_label(tmp_path):
    """When a hwmon device has non-CPU sensors, the CPU-labeled one is preferred."""
    _make_proc_tree(tmp_path)
    _make_hwmon_device(
        tmp_path, 0, "acpitz",
        {"1": (30000, None), "2": (65000, "CPU")},
    )

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    assert snap["cpu_temperature_celsius"] == 65.0


def test_cpu_temperature_thermal_zone_preferred_over_hwmon(tmp_path):
    """Thermal zone with CPU type takes priority over hwmon."""
    _make_proc_tree(tmp_path)
    _make_thermal_zone(tmp_path, 0, "x86_pkg_temp", 42000)
    _make_hwmon_device(tmp_path, 0, "coretemp", {"1": (50000, "Package id 0")})

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    assert snap["cpu_temperature_celsius"] == 42.0


def test_cpu_temperature_missing_returns_none(tmp_path):
    """When no sysfs CPU temperature is available, returns None."""
    _make_proc_tree(tmp_path)

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    assert snap["cpu_temperature_celsius"] is None


def test_cpu_temperature_json_safe(tmp_path):
    """Temperature value must survive JSON serialisation."""
    import json

    _make_proc_tree(tmp_path)
    _make_thermal_zone(tmp_path, 0, "x86_pkg_temp", 42000)

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    json.dumps(snap)


def test_cpu_temperature_in_all_returns(tmp_path):
    """cpu_temperature_celsius is present even when all /proc reads produce zeros."""
    # Point at a valid but empty temp dir - meminfo is missing, cpu_stats returns zeros
    svc = HostSystemMonitorService(proc_root=str(tmp_path / "inaccessible"), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    # Service gracefully returns available=True with zero/None values
    assert snap["available"] is True
    assert "cpu_temperature_celsius" in snap
    # Temperature should be None (no sysfs sensors set up)
    assert snap["cpu_temperature_celsius"] is None
    assert snap["total_cpu_percent"] is None  # warming
    assert snap["ram_total_bytes"] == 0


# ======================================================================
# HostSystemMonitorService — CPU fan from sysfs
# ======================================================================


def test_cpu_fan_from_label(tmp_path):
    """CPU-labeled fan input is returned as RPM."""
    _make_proc_tree(tmp_path)
    _make_hwmon_fan_device(
        tmp_path, 0, "nct6797",
        {"1": (1200, None), "2": (850, "CPU Fan"), "3": (0, None)},
    )

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    assert snap["cpu_fan_rpm"] == 850


def test_cpu_fan_from_device_name(tmp_path):
    """Fan from a CPU-named hwmon device (coretemp) is returned."""
    _make_proc_tree(tmp_path)
    _make_hwmon_fan_device(
        tmp_path, 0, "coretemp",
        {"1": (2200, None)},
    )

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    assert snap["cpu_fan_rpm"] == 2200


def test_cpu_fan_falls_back_to_known_device(tmp_path):
    """When no CPU-labeled fan exists, falls back to a known device fan."""
    _make_proc_tree(tmp_path)
    _make_hwmon_fan_device(
        tmp_path, 0, "nct6797",
        {"1": (1500, "Chassis Fan"), "2": (800, None)},
    )

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    assert snap["cpu_fan_rpm"] == 1500


def test_cpu_fan_prefers_cpu_label_over_known_device(tmp_path):
    """CPU-labeled fan is preferred over an unlabeled fan on a known device."""
    _make_proc_tree(tmp_path)
    _make_hwmon_fan_device(
        tmp_path, 0, "nct6797",
        {"1": (500, None), "2": (1800, "CPU Fan")},
    )

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    assert snap["cpu_fan_rpm"] == 1800


def test_cpu_fan_invalid_values_ignored(tmp_path):
    """Negative and outlandish RPM values are ignored; zero is valid."""
    _make_proc_tree(tmp_path)
    # Only invalid values: negative and exceeding MAX_RPM
    _make_hwmon_fan_device(
        tmp_path, 0, "nct6797",
        {"1": (-1, None), "2": (999999, None)},
    )

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    assert snap["cpu_fan_rpm"] is None


def test_cpu_fan_zero_rpm_is_reported(tmp_path):
    """Zero RPM from a readable CPU-labeled fan is reported as 0, not None."""
    _make_proc_tree(tmp_path)
    _make_hwmon_fan_device(
        tmp_path, 0, "thinkpad",
        {"1": (0, "CPU Fan"), "2": (0, None)},
    )

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    # Fan 1 has a CPU label → should be returned as 0
    assert snap["cpu_fan_rpm"] == 0

    # Also verify JSON serialisation works with int zero
    import json
    json.dumps(snap)


def test_cpu_fan_missing_returns_none(tmp_path):
    """When no sysfs fan sensor is available, returns None."""
    _make_proc_tree(tmp_path)

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    assert snap["cpu_fan_rpm"] is None


def test_cpu_fan_in_all_returns(tmp_path):
    """cpu_fan_rpm is present even when all /proc reads produce zeros."""
    svc = HostSystemMonitorService(
        proc_root=str(tmp_path / "inaccessible"),
        sys_root=str(tmp_path),
    )
    snap = svc.get_snapshot()

    assert snap["available"] is True
    assert "cpu_fan_rpm" in snap
    assert snap["cpu_fan_rpm"] is None


def test_cpu_fan_json_safe(tmp_path):
    """Fan RPM value must survive JSON serialisation."""
    import json

    _make_proc_tree(tmp_path)
    _make_hwmon_fan_device(
        tmp_path, 0, "nct6797",
        {"1": (1200, "CPU Fan")},
    )

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    json.dumps(snap)


# ======================================================================
# HostSystemMonitorService — battery from sysfs
# ======================================================================


def test_battery_percent_from_power_supply(tmp_path):
    """Battery capacity from sysfs is returned as a percentage."""
    _make_proc_tree(tmp_path)
    _make_power_supply(tmp_path, "BAT0", "Battery", "87")

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    assert snap["battery_percent"] == 87.0


def test_battery_percent_averages_multiple_batteries(tmp_path):
    """Multiple battery capacities are averaged when present."""
    _make_proc_tree(tmp_path)
    _make_power_supply(tmp_path, "BAT0", "Battery", "80")
    _make_power_supply(tmp_path, "BAT1", "Battery", "60")

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    assert snap["battery_percent"] == 70.0


def test_battery_percent_missing_or_invalid_returns_none(tmp_path):
    """Missing and invalid battery values do not break host snapshots."""
    _make_proc_tree(tmp_path)
    _make_power_supply(tmp_path, "AC", "Mains", "100")
    _make_power_supply(tmp_path, "BAT0", "Battery", "not-a-number")
    _make_power_supply(tmp_path, "BAT1", "Battery", "101")

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    assert snap["battery_percent"] is None


def test_battery_percent_json_safe(tmp_path):
    """Battery percent must survive JSON serialisation."""
    _make_proc_tree(tmp_path)
    _make_power_supply(tmp_path, "BAT0", "Battery", "52.5")

    svc = HostSystemMonitorService(proc_root=str(tmp_path), sys_root=str(tmp_path))
    snap = svc.get_snapshot()

    json.dumps(snap)


# ======================================================================
# WebSystemMonitorService — DB-backed mode
# ======================================================================


def test_web_service_returns_snapshot_from_repo(tmp_path):
    """WebSystemMonitorService should return the persisted snapshot."""
    from bot.repositories.web_system_status import WebSystemStatusRepository

    db_path = str(tmp_path / "test.db")
    repo = WebSystemStatusRepository(db_path=db_path, use_shared=False)

    snapshot = {
        "available": True,
        "total_cpu_percent": 23.5,
        "ram_total_bytes": 17179869184,
        "top_processes": [
            {"pid": 101, "name": "python", "display_name": "web_page.py", "cpu_percent": 10.5, "memory_rss_bytes": 4194304, "memory_percent": 0.02}
        ],
        "cpu_warming": False,
        "sample_interval_seconds": 1.0,
        "updated_at_unix": 1234567890.0,
        "cpu_fan_rpm": 1200,
        "battery_percent": 64.0,
    }
    repo.upsert_snapshot(snapshot)

    svc = WebSystemMonitorService(repository=repo)
    result = svc.get_snapshot(top_limit=4)

    assert result["available"] is True
    assert result["total_cpu_percent"] == 23.5
    assert len(result["top_processes"]) == 1
    assert result["top_processes"][0]["display_name"] == "web_page.py"
    assert result["cpu_fan_rpm"] == 1200
    assert result["battery_percent"] == 64.0


def test_web_service_returns_unavailable_when_no_snapshot(tmp_path):
    """When the DB has no snapshot, WebSystemMonitorService should return available: false."""
    from bot.repositories.web_system_status import WebSystemStatusRepository

    db_path = str(tmp_path / "test.db")
    repo = WebSystemStatusRepository(db_path=db_path, use_shared=False)

    svc = WebSystemMonitorService(repository=repo)
    result = svc.get_snapshot()

    assert result["available"] is False
    assert result["status_label"] == "Waiting for host monitor"


def test_web_service_without_repo_returns_unavailable(tmp_path):
    """Without a repository and without fallback, should return no monitor backend."""
    svc = WebSystemMonitorService(repository=None)
    result = svc.get_snapshot()

    assert result["available"] is False
    assert result["status_label"] == "No monitor backend"


def test_web_service_limits_top_processes(tmp_path):
    """The top_limit should be respected when reading from the repo."""
    from bot.repositories.web_system_status import WebSystemStatusRepository

    db_path = str(tmp_path / "test.db")
    repo = WebSystemStatusRepository(db_path=db_path, use_shared=False)

    snapshot = {
        "available": True,
        "total_cpu_percent": 42.0,
        "top_processes": [
            {"pid": i, "name": f"proc{i}", "display_name": None, "cpu_percent": float(i), "memory_rss_bytes": 1024, "memory_percent": 0.01}
            for i in range(10)
        ],
        "cpu_warming": False,
        "sample_interval_seconds": 1.0,
    }
    repo.upsert_snapshot(snapshot)

    svc = WebSystemMonitorService(repository=repo)
    result = svc.get_snapshot(top_limit=3)

    assert len(result["top_processes"]) <= 3


# ======================================================================
# WebSystemMonitorService — in-process cache
# ======================================================================


def _make_web_repo(tmp_path, data: dict | None = None):
    """Create a WebSystemStatusRepository with optional snapshot."""
    from bot.repositories.web_system_status import WebSystemStatusRepository

    db_path = str(tmp_path / "test.db")
    repo = WebSystemStatusRepository(db_path=db_path, use_shared=False)
    if data is not None:
        repo.upsert_snapshot(data)
    return repo


def test_web_cache_hit_returns_cached_snapshot(tmp_path):
    """Repeated calls within cache_ttl should return the cached snapshot."""
    snapshot = {
        "available": True,
        "total_cpu_percent": 23.5,
        "cpu_temperature_celsius": 42.0,
        "cpu_fan_rpm": 1200,
        "top_processes": [
            {"pid": 1, "name": "procA", "display_name": None, "cpu_percent": 10.0,
             "memory_rss_bytes": 1024, "memory_percent": 0.01}
        ],
        "cpu_warming": False,
        "sample_interval_seconds": 1.0,
    }
    repo = _make_web_repo(tmp_path, snapshot)
    svc = WebSystemMonitorService(repository=repo, cache_ttl=60)

    with patch("time.monotonic", side_effect=[100.0, 100.5]):
        first = svc.get_snapshot(top_limit=4)
        second = svc.get_snapshot(top_limit=4)

    assert first["total_cpu_percent"] == 23.5
    assert second["total_cpu_percent"] == 23.5

    # After cache, modify repo data — cache should still serve old value.
    repo.upsert_snapshot({**snapshot, "total_cpu_percent": 99.9})
    with patch("time.monotonic", side_effect=[101.0, 101.3]):
        cached = svc.get_snapshot()

    assert cached["total_cpu_percent"] == 23.5  # still from cache


def test_web_cache_respects_different_top_limit(tmp_path):
    """Cache should serve different ``top_limit`` values by re-slicing."""
    snapshot = {
        "available": True,
        "total_cpu_percent": 42.0,
        "top_processes": [
            {"pid": i, "name": f"proc{i}", "display_name": None,
             "cpu_percent": float(i), "memory_rss_bytes": 1024,
             "memory_percent": 0.01}
            for i in range(10)
        ],
        "cpu_warming": False,
        "sample_interval_seconds": 1.0,
    }
    repo = _make_web_repo(tmp_path, snapshot)
    svc = WebSystemMonitorService(repository=repo, cache_ttl=60)

    # Prime cache with one limit.
    with patch("time.monotonic", side_effect=[100.0]):
        svc.get_snapshot(top_limit=8)

    # Re-read with a different limit — should re-slice from cached full list.
    with patch("time.monotonic", side_effect=[101.0]):
        result = svc.get_snapshot(top_limit=3)

    assert len(result["top_processes"]) == 3
    assert result["total_cpu_percent"] == 42.0


def test_web_cache_miss_after_ttl(tmp_path):
    """After TTL expires, a fresh repo read should occur."""
    snapshot = {
        "available": True,
        "total_cpu_percent": 10.0,
        "top_processes": [],
        "cpu_warming": False,
        "sample_interval_seconds": 1.0,
    }
    repo = _make_web_repo(tmp_path, snapshot)
    svc = WebSystemMonitorService(repository=repo, cache_ttl=1.0)

    # First call — caches.
    with patch("time.monotonic", side_effect=[100.0]):
        svc.get_snapshot()

    # Update repo with new data.
    repo.upsert_snapshot({**snapshot, "total_cpu_percent": 50.0})

    # Second call after TTL — should fetch fresh.
    with patch("time.monotonic", side_effect=[102.0]):
        result = svc.get_snapshot()

    assert result["total_cpu_percent"] == 50.0


def test_web_cache_disabled_with_ttl_zero(tmp_path):
    """With cache_ttl=0, every call should go to the repository."""
    snapshot = {
        "available": True,
        "total_cpu_percent": 10.0,
        "top_processes": [],
        "cpu_warming": False,
        "sample_interval_seconds": 1.0,
    }
    repo = _make_web_repo(tmp_path, snapshot)
    svc = WebSystemMonitorService(repository=repo, cache_ttl=0)

    with patch("time.monotonic", side_effect=[100.0, 100.1]):
        first = svc.get_snapshot()
        second = svc.get_snapshot()

    # Both should be 10.0 because repo hasn't changed (but they should hit repo).
    assert first["total_cpu_percent"] == 10.0
    assert second["total_cpu_percent"] == 10.0

    # Update repo and verify next call picks it up immediately.
    repo.upsert_snapshot({**snapshot, "total_cpu_percent": 75.0})
    with patch("time.monotonic", side_effect=[100.2]):
        third = svc.get_snapshot()

    assert third["total_cpu_percent"] == 75.0


def test_web_cache_does_not_cache_unavailable(tmp_path):
    """Unavailable (no repo data) should not cache — next call re-queries."""
    repo = _make_web_repo(tmp_path)  # empty — no snapshot
    svc = WebSystemMonitorService(repository=repo, cache_ttl=60)

    with patch("time.monotonic", side_effect=[100.0, 100.5]):
        first = svc.get_snapshot()
        second = svc.get_snapshot()

    assert first["available"] is False
    assert second["available"] is False

    # Insert data after the unavailable calls — next call should pick it up.
    repo.upsert_snapshot({
        "available": True, "total_cpu_percent": 42.0, "top_processes": [],
        "cpu_warming": False, "sample_interval_seconds": 1.0,
    })
    with patch("time.monotonic", side_effect=[101.0]):
        third = svc.get_snapshot()

    assert third["available"] is True
    assert third["total_cpu_percent"] == 42.0
