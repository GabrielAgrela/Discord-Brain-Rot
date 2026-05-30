"""
Repository for persisted host system status snapshots written by the bot background loop.

The singleton ``web_system_status`` table holds a single row (id=1) with a JSON
snapshot payload and an ``updated_at`` timestamp.  The bot writes this every 1 s
and the web control-room endpoint reads it.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

import sqlite3

from bot.repositories.base import BaseRepository


class WebSystemStatusRepository(BaseRepository[dict[str, Any]]):
    """
    Singleton-pattern repository for host system status snapshots.

    The bot background loop writes snapshots here every ~1 s.
    The web ``/api/system_monitor/status`` endpoint reads the latest snapshot.
    """

    def __init__(self, db_path: Optional[str] = None, use_shared: bool = True):
        super().__init__(db_path=db_path, use_shared=use_shared)
        self.ensure_schema()

    # ------------------------------------------------------------------
    # BaseRepository interface
    # ------------------------------------------------------------------

    def _row_to_entity(self, row: sqlite3.Row) -> dict[str, Any]:
        return dict(row) if row else {}

    def get_by_id(self, id: int) -> dict[str, Any] | None:
        return self.get_latest_snapshot()

    def get_all(self, limit: int = 100) -> list[dict[str, Any]]:
        row = self._execute_one("SELECT * FROM web_system_status WHERE id = 1")
        return [self._row_to_entity(row)] if row else []

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def ensure_schema(self) -> None:
        """Ensure the ``web_system_status`` singleton table exists."""
        self._execute_write(
            """
            CREATE TABLE IF NOT EXISTS web_system_status (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                snapshot_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._execute_write(
            """
            CREATE TABLE IF NOT EXISTS system_monitor_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_type TEXT NOT NULL,
                metric_key TEXT NOT NULL DEFAULT '',
                timestamp INTEGER NOT NULL,
                value REAL NOT NULL
            )
            """
        )
        self._execute_write(
            """
            CREATE INDEX IF NOT EXISTS idx_samples_metric_time
            ON system_monitor_samples(metric_type, metric_key, timestamp)
            """
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upsert_snapshot(
        self,
        snapshot: dict[str, Any],
        updated_at: Optional[str] = None,
    ) -> None:
        """
        Insert or replace the singleton host system status snapshot.

        Args:
            snapshot: JSON-serialisable system status payload.
            updated_at: ISO-8601 timestamp string. Defaults to ``datetime.now()``.
        """
        if updated_at is None:
            updated_at = datetime.now().isoformat()
        self._execute_write(
            """
            INSERT OR REPLACE INTO web_system_status (id, snapshot_json, updated_at)
            VALUES (1, ?, ?)
            """,
            (json.dumps(snapshot), updated_at),
        )

    def get_latest_snapshot(
        self,
        max_age_seconds: Optional[int] = 5,
    ) -> dict[str, Any] | None:
        """
        Return the latest persisted snapshot, or ``None`` when missing or stale.

        Args:
            max_age_seconds: Maximum allowed age in seconds.  ``None`` disables
                staleness checking.

        Returns:
            Parsed snapshot dict, or ``None``.
        """
        row = self._execute_one(
            "SELECT snapshot_json, updated_at FROM web_system_status WHERE id = 1"
        )
        if row is None:
            return None

        updated_at_str = row["updated_at"]
        if max_age_seconds is not None and updated_at_str:
            try:
                updated_at = datetime.fromisoformat(updated_at_str)
                age = (datetime.now() - updated_at).total_seconds()
                if age > max_age_seconds:
                    return None
            except (ValueError, TypeError):
                return None

        try:
            snapshot = json.loads(row["snapshot_json"]) if row["snapshot_json"] else None
        except (json.JSONDecodeError, TypeError):
            return None

        return snapshot

    def insert_sample(
        self,
        metric_type: str,
        metric_key: str,
        timestamp: int,
        value: float,
    ) -> None:
        """
        Insert a single time-series sample.

        Args:
            metric_type: One of 'cpu', 'ram', 'disk', 'temp', 'process'.
            metric_key: Identifier for the metric (e.g., process key for 'process').
            timestamp: Unix timestamp in seconds.
            value: Numeric sample value.
        """
        self._execute_write(
            """
            INSERT INTO system_monitor_samples (metric_type, metric_key, timestamp, value)
            VALUES (?, ?, ?, ?)
            """,
            (metric_type, metric_key, timestamp, value),
        )

    def insert_samples_batch(
        self,
        samples: list[tuple[str, str, int, float]],
    ) -> int:
        """
        Insert multiple samples in a single transaction.

        Args:
            samples: List of (metric_type, metric_key, timestamp, value) tuples.

        Returns:
            Number of rows inserted.
        """
        if not samples:
            return 0
        return self._execute_many(
            """
            INSERT INTO system_monitor_samples (metric_type, metric_key, timestamp, value)
            VALUES (?, ?, ?, ?)
            """,
            samples,
        )

    def get_samples(
        self,
        metric_type: str,
        metric_key: str,
        start_time: int,
        end_time: int,
        max_points: int = 500,
    ) -> list[dict[str, Any]]:
        """
        Query time-series samples for a metric within a time range.

        Returns at most ``max_points`` evenly-spaced samples to avoid overwhelming
        the frontend with data.

        Args:
            metric_type: One of 'cpu', 'ram', 'disk', 'temp', 'process'.
            metric_key: Identifier for the metric.
            start_time: Start of range (unix seconds, inclusive).
            end_time: End of range (unix seconds, inclusive).
            max_points: Maximum number of points to return.

        Returns:
            List of dicts with 'time' and 'value' keys, sorted by time.
        """
        rows = self._execute(
            """
            SELECT timestamp, value FROM system_monitor_samples
            WHERE metric_type = ? AND metric_key = ?
              AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
            """,
            (metric_type, metric_key, start_time, end_time),
        )
        if not rows:
            return []

        all_samples = [{"time": row["timestamp"], "value": row["value"]} for row in rows]

        if len(all_samples) <= max_points:
            return all_samples

        step = len(all_samples) / max_points
        return [all_samples[int(i * step)] for i in range(max_points)]

    def cleanup_old_samples(self, max_age_seconds: int = 86400) -> int:
        """
        Delete samples older than ``max_age_seconds``.

        Args:
            max_age_seconds: Maximum age in seconds (default: 1 day).

        Returns:
            Number of rows deleted.
        """
        cutoff = int(datetime.now().timestamp()) - max_age_seconds
        cursor = self._execute_write(
            "DELETE FROM system_monitor_samples WHERE timestamp < ?",
            (cutoff,),
        )
        return cursor.rowcount if cursor else 0

    def get_processes_at_time(
        self,
        timestamp: int,
        tolerance_seconds: int = 5,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """
        Query process samples near a specific timestamp.

        Args:
            timestamp: Target Unix timestamp in seconds.
            tolerance_seconds: Search window around the timestamp.
            limit: Maximum number of processes to return.

        Returns:
            List of dicts with 'key', 'value' (cpu percent), sorted by value desc.
        """
        start_time = timestamp - tolerance_seconds
        end_time = timestamp + tolerance_seconds

        rows = self._execute(
            """
            SELECT metric_key, value, timestamp FROM system_monitor_samples
            WHERE metric_type = 'process'
              AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp DESC, value DESC
            """,
            (start_time, end_time),
        )

        if not rows:
            return []

        seen_keys: set[str] = set()
        processes: list[dict[str, Any]] = []
        for row in rows:
            key = row["metric_key"]
            if key in seen_keys:
                continue
            seen_keys.add(key)
            processes.append({
                "key": key,
                "value": row["value"],
                "time": row["timestamp"],
            })
            if len(processes) >= limit:
                break

        processes.sort(key=lambda p: p["value"], reverse=True)
        return processes
