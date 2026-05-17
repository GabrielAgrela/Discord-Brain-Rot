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
