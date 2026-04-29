"""
Repository for TikTok favorites collection watcher state.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from bot.repositories.base import BaseRepository


class FavoriteWatcherRepository(BaseRepository[sqlite3.Row]):
    """Persist watched collection URLs and videos already seen for each watcher."""

    def __init__(self, db_path: Optional[str] = None, use_shared: bool = True):
        """
        Initialize the repository and ensure watcher tables exist.

        Args:
            db_path: Optional database path override.
            use_shared: Whether to use the shared repository connection.
        """
        super().__init__(db_path=db_path, use_shared=use_shared)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        """Create watcher tables and indexes when they do not exist."""
        self._execute_write(
            """
            CREATE TABLE IF NOT EXISTS favorite_watchers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                guild_id TEXT,
                added_by_user_id TEXT,
                added_by_username TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_checked_at DATETIME,
                UNIQUE(url, guild_id)
            )
            """
        )
        self._execute_write(
            """
            CREATE TABLE IF NOT EXISTS favorite_watcher_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                watcher_id INTEGER NOT NULL,
                video_id TEXT NOT NULL,
                video_url TEXT NOT NULL,
                first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                imported_at DATETIME,
                sound_filename TEXT,
                UNIQUE(watcher_id, video_id),
                FOREIGN KEY (watcher_id) REFERENCES favorite_watchers(id)
            )
            """
        )
        self._execute_write(
            "CREATE INDEX IF NOT EXISTS idx_favorite_watchers_enabled ON favorite_watchers(enabled)"
        )
        self._execute_write(
            """
            CREATE INDEX IF NOT EXISTS idx_favorite_watcher_videos_watcher
            ON favorite_watcher_videos(watcher_id)
            """
        )

    def add_watcher(
        self,
        *,
        url: str,
        guild_id: int | str | None,
        added_by_user_id: int | str | None,
        added_by_username: str | None,
    ) -> int:
        """
        Add a watcher URL.

        Args:
            url: TikTok collection URL to watch.
            guild_id: Guild scope for imported sounds.
            added_by_user_id: Discord user ID that added the watcher.
            added_by_username: Discord username that added the watcher.

        Returns:
            New watcher ID.
        """
        return self._execute_write(
            """
            INSERT INTO favorite_watchers (
                url, guild_id, added_by_user_id, added_by_username
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                url,
                str(guild_id) if guild_id is not None else None,
                str(added_by_user_id) if added_by_user_id is not None else None,
                added_by_username,
            ),
        )

    def remove_watcher(self, watcher_id: int, guild_id: int | str | None) -> bool:
        """
        Disable a watcher for a guild.

        Args:
            watcher_id: Watcher row ID.
            guild_id: Guild scope to protect cross-guild settings.

        Returns:
            True when a watcher row was updated.
        """
        row = self._execute_one(
            """
            SELECT id FROM favorite_watchers
            WHERE id = ? AND (guild_id = ? OR (? IS NULL AND guild_id IS NULL))
            """,
            (
                watcher_id,
                str(guild_id) if guild_id is not None else None,
                str(guild_id) if guild_id is not None else None,
            ),
        )
        if row is None:
            return False
        self._execute_write(
            "UPDATE favorite_watchers SET enabled = 0 WHERE id = ?",
            (watcher_id,),
        )
        return True

    def list_watchers(self, guild_id: int | str | None) -> list[sqlite3.Row]:
        """Return enabled watchers for a guild."""
        return self._execute(
            """
            SELECT * FROM favorite_watchers
            WHERE enabled = 1 AND (guild_id = ? OR (? IS NULL AND guild_id IS NULL))
            ORDER BY id ASC
            """,
            (
                str(guild_id) if guild_id is not None else None,
                str(guild_id) if guild_id is not None else None,
            ),
        )

    def get_enabled_watchers(self) -> list[sqlite3.Row]:
        """Return all enabled watcher rows."""
        return self._execute(
            "SELECT * FROM favorite_watchers WHERE enabled = 1 ORDER BY id ASC"
        )

    def get_known_video_ids(self, watcher_id: int) -> set[str]:
        """Return video IDs already recorded for a watcher."""
        rows = self._execute(
            "SELECT video_id FROM favorite_watcher_videos WHERE watcher_id = ?",
            (watcher_id,),
        )
        return {str(row["video_id"]) for row in rows}

    def record_video_seen(
        self,
        *,
        watcher_id: int,
        video_id: str,
        video_url: str,
        imported_at: str | None = None,
        sound_filename: str | None = None,
    ) -> None:
        """Record a collection video as known, optionally with import metadata."""
        self._execute_write(
            """
            INSERT OR IGNORE INTO favorite_watcher_videos (
                watcher_id, video_id, video_url, imported_at, sound_filename
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (watcher_id, video_id, video_url, imported_at, sound_filename),
        )
        if imported_at is not None or sound_filename is not None:
            self._execute_write(
                """
                UPDATE favorite_watcher_videos
                SET imported_at = COALESCE(?, imported_at),
                    sound_filename = COALESCE(?, sound_filename)
                WHERE watcher_id = ? AND video_id = ?
                """,
                (imported_at, sound_filename, watcher_id, video_id),
            )

    def mark_checked(self, watcher_id: int) -> None:
        """Update the last checked timestamp for a watcher."""
        self._execute_write(
            "UPDATE favorite_watchers SET last_checked_at = CURRENT_TIMESTAMP WHERE id = ?",
            (watcher_id,),
        )

    def get_by_id(self, id: int) -> Optional[sqlite3.Row]:
        """Get a watcher by ID."""
        return self._execute_one("SELECT * FROM favorite_watchers WHERE id = ?", (id,))

    def get_all(self, limit: int = 100) -> list[sqlite3.Row]:
        """Get watcher rows."""
        return self._execute(
            "SELECT * FROM favorite_watchers ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    def _row_to_entity(self, row: sqlite3.Row) -> sqlite3.Row:
        """Return raw SQLite rows for watcher records."""
        return row
