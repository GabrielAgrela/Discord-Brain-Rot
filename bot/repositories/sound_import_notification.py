"""
Repository for the sound import notification outbox.

Cross-process notifications (e.g. from the Flask web upload background worker)
cannot use BotBehavior directly. This repository provides a simple queue table
that the bot process drains in its own background loop.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlite3

from bot.repositories.base import BaseRepository


class SoundImportNotificationRepository(BaseRepository[dict[str, Any]]):
    """
    Store pending Discord notifications for sound imports.

    The Flask web upload background worker inserts rows here.
    The bot's BackgroundService drains them and sends Discord messages.
    """

    def __init__(self, db_path: str | None = None, use_shared: bool = True):
        """Initialize repository and ensure its table exists."""
        super().__init__(db_path=db_path, use_shared=use_shared)
        self.ensure_schema()

    def _row_to_entity(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a SQLite row into a dictionary."""
        return dict(row)

    def get_by_id(self, id: int) -> dict[str, Any] | None:
        """Return one notification record by ID."""
        row = self._execute_one(
            "SELECT * FROM sound_import_notifications WHERE id = ?", (id,)
        )
        return self._row_to_entity(row) if row else None

    def get_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent notification records."""
        return self.get_pending(limit=limit)

    def ensure_schema(self) -> None:
        """Create the notification outbox table when needed."""
        self._execute_write(
            """
            CREATE TABLE IF NOT EXISTS sound_import_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT,
                filename TEXT NOT NULL,
                source TEXT NOT NULL,
                requester_username TEXT NOT NULL,
                title TEXT,
                accent_color TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                sent_at DATETIME,
                last_error TEXT,
                attempts INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._execute_write(
            """
            CREATE INDEX IF NOT EXISTS idx_sound_import_notifications_pending
            ON sound_import_notifications(sent_at, attempts, created_at)
            """
        )

    def enqueue(
        self,
        *,
        guild_id: int | str | None,
        filename: str,
        source: str,
        requester_username: str,
        title: str | None = None,
        accent_color: str | None = None,
    ) -> int:
        """
        Insert a pending import notification row.

        Args:
            guild_id: Target guild ID.
            filename: Imported sound filename.
            source: Origin label (e.g. ``web_upload``, ``favorite_watcher``, …).
            requester_username: User-facing requester name shown on the card.
            title: Optional custom title; a default is built if omitted.
            accent_color: Hex border color for the image card (e.g. ``#5865F2``).

        Returns:
            Inserted row ID.
        """
        return self._execute_write(
            """
            INSERT INTO sound_import_notifications (
                guild_id, filename, source, requester_username,
                title, accent_color
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(guild_id) if guild_id is not None else None,
                filename,
                source,
                requester_username,
                title,
                accent_color,
            ),
        )

    def get_pending(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        Return notifications that have not been sent yet.

        Excludes rows that have failed too many times (``attempts >= 5``).
        Orders by oldest first.

        Args:
            limit: Maximum rows to fetch.

        Returns:
            List of notification dicts.
        """
        rows = self._execute(
            """
            SELECT * FROM sound_import_notifications
            WHERE sent_at IS NULL AND attempts < 5
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_entity(row) for row in rows]

    def mark_sent(self, notification_id: int) -> None:
        """Mark a notification as sent and increment attempt count."""
        self._execute_write(
            """
            UPDATE sound_import_notifications
            SET sent_at = ?, attempts = attempts + 1
            WHERE id = ?
            """,
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                notification_id,
            ),
        )

    def mark_failed(self, notification_id: int, error: str) -> None:
        """
        Record a delivery failure and increment attempt count.

        Args:
            notification_id: Row ID to mark.
            error: Truncated error message (max 500 chars).
        """
        self._execute_write(
            """
            UPDATE sound_import_notifications
            SET last_error = ?, attempts = attempts + 1
            WHERE id = ?
            """,
            (error[:500], notification_id),
        )
