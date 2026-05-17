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
) -> None:
    """
    Populate a fake /proc directory under *root*.

    *processes* maps pid → (name, utime, stime, vm_rss_kb).
    """
    _write_proc(root, "meminfo", f"MemTotal:       {mem_total_kb} kB\nMemAvailable:    {mem_avail_kb} kB\n")
    field_str = " ".join(str(v) for v in cpu_fields)
    _write_proc(root, "stat", f"cpu  {field_str}\n")

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
    _write_proc_binary(tmp_path, "101/cmdline", b"python3\x00/tmp/WebPage.py\x00--port\x008080\x00")

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
    _write_proc_binary(tmp_path, "101/cmdline", b"python3\x00/tmp/WebPage.py\x00--port\x008080\x00")

    svc = HostSystemMonitorService(proc_root=str(tmp_path))
    svc.get_snapshot()  # warm-up

    cpu2 = (200, 100, 50, 1600, 20, 0, 0, 0, 0, 0)
    _write_proc(tmp_path, "stat", f"cpu  {' '.join(str(v) for v in cpu2)}\n")
    _write_proc(tmp_path, "101/stat", "101 (python) R 1 2 3 4 5 6 7 8 9 10 200 100\n")

    snap = svc.get_snapshot()

    assert snap["available"] is True
    assert len(snap["top_processes"]) == 1
    proc = snap["top_processes"][0]
    assert proc["display_name"] == "WebPage.py"
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
            {"pid": 101, "name": "python", "display_name": "WebPage.py", "cpu_percent": 10.5, "memory_rss_bytes": 4194304, "memory_percent": 0.02}
        ],
        "cpu_warming": False,
        "sample_interval_seconds": 1.0,
        "updated_at_unix": 1234567890.0,
    }
    repo.upsert_snapshot(snapshot)

    svc = WebSystemMonitorService(repository=repo)
    result = svc.get_snapshot(top_limit=4)

    assert result["available"] is True
    assert result["total_cpu_percent"] == 23.5
    assert len(result["top_processes"]) == 1
    assert result["top_processes"][0]["display_name"] == "WebPage.py"


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
