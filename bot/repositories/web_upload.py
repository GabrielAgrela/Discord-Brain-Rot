"""
Repository for web upload inbox records.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlite3

from bot.repositories.base import BaseRepository


class WebUploadRepository(BaseRepository[dict[str, Any]]):
    """
    Store web upload audit/moderation records.
    """

    def __init__(self, db_path: str | None = None, use_shared: bool = True):
        """Initialize repository and ensure its table exists."""
        super().__init__(db_path=db_path, use_shared=use_shared)
        self.ensure_schema()

    def _row_to_entity(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a SQLite row into a dictionary."""
        return dict(row)

    def get_by_id(self, id: int) -> dict[str, Any] | None:
        """Return one upload record by ID."""
        row = self._execute_one("SELECT * FROM web_uploads WHERE id = ?", (id,))
        return self._row_to_entity(row) if row else None

    def get_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent upload records."""
        return self.get_recent(limit=limit)

    def ensure_schema(self) -> None:
        """Create the web upload inbox table when needed."""
        self._execute_write(
            """
            CREATE TABLE IF NOT EXISTS web_uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT,
                sound_id INTEGER,
                filename TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                uploaded_by_username TEXT NOT NULL,
                uploaded_by_user_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'approved',
                moderator_username TEXT,
                moderated_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def insert_upload(
        self,
        *,
        guild_id: int | str | None,
        sound_id: int,
        filename: str,
        original_filename: str,
        uploaded_by_username: str,
        uploaded_by_user_id: str,
        status: str = "approved",
    ) -> int:
        """
        Insert a web upload audit record.

        Returns:
            Inserted record ID.
        """
        return self._execute_write(
            """
            INSERT INTO web_uploads (
                guild_id,
                sound_id,
                filename,
                original_filename,
                uploaded_by_username,
                uploaded_by_user_id,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(guild_id) if guild_id is not None else None,
                int(sound_id),
                filename,
                original_filename,
                uploaded_by_username,
                uploaded_by_user_id,
                status,
            ),
        )

    def get_recent(
        self,
        *,
        limit: int = 50,
        guild_id: int | str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return recent upload records.

        Args:
            limit: Maximum records to return.
            guild_id: Optional guild scope.
        """
        if guild_id is None:
            rows = self._execute(
                """
                SELECT * FROM web_uploads
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
        else:
            rows = self._execute(
                """
                SELECT * FROM web_uploads
                WHERE guild_id = ? OR guild_id IS NULL
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (str(guild_id), limit),
            )
        return [self._row_to_entity(row) for row in rows]

    def moderate(
        self,
        upload_id: int,
        *,
        status: str,
        moderator_username: str,
    ) -> bool:
        """
        Update moderation status for an upload record.

        Args:
            upload_id: Upload record ID.
            status: New status.
            moderator_username: Admin performing the moderation action.

        Returns:
            True when the update was executed.
        """
        if status not in {"approved", "rejected"}:
            raise ValueError("Invalid upload moderation status")

        self._execute_write(
            """
            UPDATE web_uploads
            SET status = ?, moderator_username = ?, moderated_at = ?
            WHERE id = ?
            """,
            (
                status,
                moderator_username,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                upload_id,
            ),
        )
        return True

    def set_sound_blacklist(self, sound_id: int, blacklist: bool) -> None:
        """
        Best-effort update for sound blacklist state.

        Args:
            sound_id: Sound row ID.
            blacklist: Whether the sound should be blacklisted.
        """
        try:
            self._execute_write(
                "UPDATE sounds SET blacklist = ? WHERE id = ?",
                (1 if blacklist else 0, int(sound_id)),
            )
        except sqlite3.OperationalError:
            # Some legacy/test schemas do not include blacklist; upload record
            # status still preserves moderation state.
            return
