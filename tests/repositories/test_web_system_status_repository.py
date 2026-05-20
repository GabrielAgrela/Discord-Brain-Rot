"""
Tests for WebSystemStatusRepository — host system status persistence.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import pytest

from bot.repositories.web_system_status import WebSystemStatusRepository


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path):
    """Create a repository backed by a temp SQLite database."""
    db_path = tmp_path / "test.db"
    return WebSystemStatusRepository(db_path=str(db_path), use_shared=False)


# ------------------------------------------------------------------
# Schema
# ------------------------------------------------------------------


def test_ensure_schema_creates_table(repo):
    """Schema should be created on init and be queryable."""
    row = repo._execute_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='web_system_status'"
    )
    assert row is not None
    assert row["name"] == "web_system_status"


# ------------------------------------------------------------------
# Upsert and read
# ------------------------------------------------------------------


def test_upsert_and_read_latest(repo):
    """A snapshot written via upsert should be readable back."""
    snapshot = {"available": True, "total_cpu_percent": 42.5, "top_processes": []}
    repo.upsert_snapshot(snapshot)

    result = repo.get_latest_snapshot(max_age_seconds=None)
    assert result is not None
    assert result["available"] is True
    assert result["total_cpu_percent"] == 42.5


def test_upsert_replaces_existing(repo):
    """Only one snapshot row should exist (singleton id=1)."""
    repo.upsert_snapshot({"a": 1})
    repo.upsert_snapshot({"b": 2})

    rows = repo._execute("SELECT * FROM web_system_status")
    assert len(rows) == 1
    result = repo.get_latest_snapshot(max_age_seconds=None)
    assert result["b"] == 2


def test_missing_snapshot_returns_none(repo):
    """When no snapshot has been written, get_latest_snapshot returns None."""
    # Use a clean repo without ensure_schema writing data
    result = repo.get_latest_snapshot()
    assert result is None


def test_stale_snapshot_returns_none(repo):
    """A snapshot older than max_age_seconds should be treated as missing."""
    old_time = (datetime.now() - timedelta(seconds=60)).isoformat()
    repo.upsert_snapshot({"available": True}, updated_at=old_time)

    result = repo.get_latest_snapshot(max_age_seconds=5)
    assert result is None


def test_fresh_snapshot_within_age(repo):
    """A recent snapshot should be returned when within max_age_seconds."""
    repo.upsert_snapshot({"available": True})

    result = repo.get_latest_snapshot(max_age_seconds=30)
    assert result is not None
    assert result["available"] is True


def test_invalid_json_returns_none(repo):
    """Corrupted snapshot_json should return None, not crash."""
    repo._execute_write(
        "INSERT OR REPLACE INTO web_system_status (id, snapshot_json, updated_at) VALUES (1, ?, ?)",
        ("{invalid json}", datetime.now().isoformat()),
    )
    result = repo.get_latest_snapshot(max_age_seconds=None)
    assert result is None


# ------------------------------------------------------------------
# JSON round-trip
# ------------------------------------------------------------------


def test_snapshot_with_top_processes_round_trips(repo):
    """A snapshot containing top_processes should round-trip correctly."""
    snapshot = {
        "available": True,
        "total_cpu_percent": 23.5,
        "ram_total_bytes": 17179869184,
        "ram_available_bytes": 8589934592,
        "ram_used_bytes": 8589934592,
        "ram_percent": 50.0,
        "cpu_warming": False,
        "sample_interval_seconds": 1.0,
        "updated_at_unix": 1234567890.0,
        "top_processes": [
            {
                "pid": 101,
                "name": "python",
                "display_name": "web_page.py",
                "cpu_percent": 10.5,
                "memory_rss_bytes": 4194304,
                "memory_percent": 0.02,
            }
        ],
    }
    repo.upsert_snapshot(snapshot)
    result = repo.get_latest_snapshot(max_age_seconds=None)

    assert result is not None
    assert result["total_cpu_percent"] == 23.5
    assert len(result["top_processes"]) == 1
    assert result["top_processes"][0]["display_name"] == "web_page.py"
    assert result["top_processes"][0]["cpu_percent"] == 10.5


# ------------------------------------------------------------------
# BaseRepository interface
# ------------------------------------------------------------------


def test_get_by_id_returns_latest_snapshot(repo):
    """get_by_id should return the latest snapshot for any id."""
    repo.upsert_snapshot({"version": 1})
    result = repo.get_by_id(1)
    assert result is not None
    assert result["version"] == 1
    result = repo.get_by_id(999)
    assert result is not None
    assert result["version"] == 1


def test_get_all_returns_singleton(repo):
    """get_all should return a list with the singleton row."""
    assert repo.get_all() == []
    repo.upsert_snapshot({"version": 1})
    all_rows = repo.get_all()
    assert len(all_rows) == 1
