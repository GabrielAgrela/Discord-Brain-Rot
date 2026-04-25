"""
Repository for web control-room runtime status.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

import sqlite3

from bot.repositories.base import BaseRepository


class WebControlRoomRepository(BaseRepository[dict[str, Any]]):
    """
    Repository for bot runtime status shown by the web soundboard.
    """

    def __init__(self, db_path: Optional[str] = None, use_shared: bool = True):
        """
        Initialize the repository and ensure its lightweight schema exists.

        Args:
            db_path: Optional SQLite database path.
            use_shared: Whether to use the shared application connection.
        """
        super().__init__(db_path=db_path, use_shared=use_shared)
        self.ensure_schema()

    def _row_to_entity(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a SQLite row into a dictionary."""
        return dict(row) if row else {}

    def get_by_id(self, id: int) -> dict[str, Any] | None:
        """Get a status row by integer guild ID."""
        return self.get_status(id)

    def get_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent guild status rows."""
        rows = self._execute(
            """
            SELECT *
            FROM web_bot_status
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_entity(row) for row in rows]

    def ensure_schema(self) -> None:
        """Ensure the web control-room status table exists."""
        self._execute_write(
            """
            CREATE TABLE IF NOT EXISTS web_bot_status (
                guild_id TEXT PRIMARY KEY,
                guild_name TEXT,
                voice_connected INTEGER NOT NULL DEFAULT 0,
                voice_channel_id TEXT,
                voice_channel_name TEXT,
                voice_member_count INTEGER NOT NULL DEFAULT 0,
                voice_members TEXT,
                is_playing INTEGER NOT NULL DEFAULT 0,
                is_paused INTEGER NOT NULL DEFAULT 0,
                current_sound TEXT,
                current_requester TEXT,
                muted INTEGER NOT NULL DEFAULT 0,
                mute_remaining_seconds INTEGER NOT NULL DEFAULT 0,
                updated_at DATETIME NOT NULL
            )
            """
        )
        self._ensure_column("voice_members TEXT", "voice_members")

    def _ensure_column(self, column_def: str, column_name: str) -> None:
        """Add a missing status-table column for existing deployments."""
        rows = self._execute("PRAGMA table_info(web_bot_status)")
        if any(row["name"] == column_name for row in rows):
            return
        self._execute_write(f"ALTER TABLE web_bot_status ADD COLUMN {column_def}")

    def upsert_status(
        self,
        *,
        guild_id: int | str,
        guild_name: str,
        voice_connected: bool,
        voice_channel_id: int | str | None,
        voice_channel_name: str | None,
        voice_member_count: int,
        voice_members: list[dict[str, Any]] | None,
        is_playing: bool,
        is_paused: bool,
        current_sound: str | None,
        current_requester: str | None,
        muted: bool,
        mute_remaining_seconds: int,
        updated_at: datetime | None = None,
    ) -> int:
        """
        Insert or update one guild's runtime status.

        Args:
            guild_id: Discord guild ID.
            guild_name: Current Discord guild name.
            voice_connected: Whether the bot has a connected voice client.
            voice_channel_id: Connected voice channel ID, when present.
            voice_channel_name: Connected voice channel name, when present.
            voice_member_count: Non-bot member count in the connected voice channel.
            voice_members: Non-bot members in the connected voice channel.
            is_playing: Whether the bot is currently playing audio.
            is_paused: Whether playback is paused.
            current_sound: Current sound filename, when known.
            current_requester: User/requester label for the current sound.
            muted: Whether runtime mute is active.
            mute_remaining_seconds: Runtime mute remaining seconds.
            updated_at: Optional timestamp for deterministic tests.

        Returns:
            SQLite row ID or status code from the write operation.
        """
        timestamp = (updated_at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
        voice_members_json = json.dumps(voice_members or [])
        return self._execute_write(
            """
            INSERT INTO web_bot_status (
                guild_id,
                guild_name,
                voice_connected,
                voice_channel_id,
                voice_channel_name,
                voice_member_count,
                voice_members,
                is_playing,
                is_paused,
                current_sound,
                current_requester,
                muted,
                mute_remaining_seconds,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                guild_name = excluded.guild_name,
                voice_connected = excluded.voice_connected,
                voice_channel_id = excluded.voice_channel_id,
                voice_channel_name = excluded.voice_channel_name,
                voice_member_count = excluded.voice_member_count,
                voice_members = excluded.voice_members,
                is_playing = excluded.is_playing,
                is_paused = excluded.is_paused,
                current_sound = excluded.current_sound,
                current_requester = excluded.current_requester,
                muted = excluded.muted,
                mute_remaining_seconds = excluded.mute_remaining_seconds,
                updated_at = excluded.updated_at
            """,
            (
                str(guild_id),
                guild_name,
                1 if voice_connected else 0,
                str(voice_channel_id) if voice_channel_id is not None else None,
                voice_channel_name,
                max(0, int(voice_member_count)),
                voice_members_json,
                1 if is_playing else 0,
                1 if is_paused else 0,
                current_sound,
                current_requester,
                1 if muted else 0,
                max(0, int(mute_remaining_seconds)),
                timestamp,
            ),
        )

    def get_status(self, guild_id: int | str) -> dict[str, Any] | None:
        """
        Get one guild's latest runtime status.

        Args:
            guild_id: Discord guild ID.

        Returns:
            Status dictionary or None.
        """
        row = self._execute_one(
            "SELECT * FROM web_bot_status WHERE guild_id = ?",
            (str(guild_id),),
        )
        return self._row_to_entity(row) if row else None
