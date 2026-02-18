"""
Guild settings repository for per-guild configuration persistence.
"""

from datetime import datetime
from typing import Optional
import sqlite3

from bot.models.guild_settings import GuildSettings
from bot.repositories.base import BaseRepository


class GuildSettingsRepository(BaseRepository[GuildSettings]):
    """Repository for guild-level settings."""

    def _row_to_entity(self, row: sqlite3.Row) -> GuildSettings:
        """Convert a database row to a GuildSettings entity."""
        created_at = None
        updated_at = None
        try:
            if "created_at" in row.keys() and row["created_at"]:
                created_at = datetime.fromisoformat(str(row["created_at"]).replace(" ", "T"))
            if "updated_at" in row.keys() and row["updated_at"]:
                updated_at = datetime.fromisoformat(str(row["updated_at"]).replace(" ", "T"))
        except Exception:
            created_at = None
            updated_at = None

        return GuildSettings(
            guild_id=str(row["guild_id"]),
            bot_text_channel_id=str(row["bot_text_channel_id"]) if row["bot_text_channel_id"] else None,
            default_voice_channel_id=str(row["default_voice_channel_id"]) if row["default_voice_channel_id"] else None,
            autojoin_enabled=bool(row["autojoin_enabled"]),
            periodic_enabled=bool(row["periodic_enabled"]),
            stt_enabled=bool(row["stt_enabled"]),
            audio_policy=row["audio_policy"] or "low_latency",
            created_at=created_at,
            updated_at=updated_at,
        )

    def get_by_id(self, id: int) -> Optional[GuildSettings]:
        """Get settings by integer guild ID."""
        return self.get_by_guild_id(str(id))

    def get_all(self, limit: int = 100):
        """Get all guild settings."""
        rows = self._execute(
            "SELECT * FROM guild_settings ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_entity(row) for row in rows]

    def get_by_guild_id(self, guild_id: str) -> Optional[GuildSettings]:
        """Get settings for a specific guild."""
        row = self._execute_one(
            "SELECT * FROM guild_settings WHERE guild_id = ?",
            (str(guild_id),),
        )
        return self._row_to_entity(row) if row else None

    def upsert_defaults(
        self,
        guild_id: str,
        autojoin_enabled: bool,
        periodic_enabled: bool,
        stt_enabled: bool,
        audio_policy: str = "low_latency",
    ) -> int:
        """Create guild settings with defaults if not already present."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return self._execute_write(
            """
            INSERT INTO guild_settings (
                guild_id, autojoin_enabled, periodic_enabled, stt_enabled, audio_policy, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                updated_at = excluded.updated_at
            """,
            (
                str(guild_id),
                1 if autojoin_enabled else 0,
                1 if periodic_enabled else 0,
                1 if stt_enabled else 0,
                audio_policy or "low_latency",
                now,
                now,
            ),
        )

    def update_channels(
        self,
        guild_id: str,
        bot_text_channel_id: Optional[str] = None,
        default_voice_channel_id: Optional[str] = None,
    ) -> int:
        """Update channel settings for a guild."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return self._execute_write(
            """
            UPDATE guild_settings
            SET
                bot_text_channel_id = COALESCE(?, bot_text_channel_id),
                default_voice_channel_id = COALESCE(?, default_voice_channel_id),
                updated_at = ?
            WHERE guild_id = ?
            """,
            (
                str(bot_text_channel_id) if bot_text_channel_id else None,
                str(default_voice_channel_id) if default_voice_channel_id else None,
                now,
                str(guild_id),
            ),
        )

    def clear_channel(self, guild_id: str, field_name: str) -> int:
        """Clear one nullable channel field for a guild."""
        if field_name not in {"bot_text_channel_id", "default_voice_channel_id"}:
            raise ValueError(f"Unsupported field: {field_name}")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return self._execute_write(
            f"UPDATE guild_settings SET {field_name} = NULL, updated_at = ? WHERE guild_id = ?",
            (now, str(guild_id)),
        )

    def update_features(
        self,
        guild_id: str,
        autojoin_enabled: Optional[bool] = None,
        periodic_enabled: Optional[bool] = None,
        stt_enabled: Optional[bool] = None,
    ) -> int:
        """Update feature toggles for a guild."""
        current = self.get_by_guild_id(str(guild_id))
        if not current:
            return 0

        new_autojoin = current.autojoin_enabled if autojoin_enabled is None else autojoin_enabled
        new_periodic = current.periodic_enabled if periodic_enabled is None else periodic_enabled
        new_stt = current.stt_enabled if stt_enabled is None else stt_enabled
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return self._execute_write(
            """
            UPDATE guild_settings
            SET autojoin_enabled = ?, periodic_enabled = ?, stt_enabled = ?, updated_at = ?
            WHERE guild_id = ?
            """,
            (
                1 if new_autojoin else 0,
                1 if new_periodic else 0,
                1 if new_stt else 0,
                now,
                str(guild_id),
            ),
        )

    def update_audio_policy(self, guild_id: str, audio_policy: str) -> int:
        """Update the guild audio policy string."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return self._execute_write(
            """
            UPDATE guild_settings
            SET audio_policy = ?, updated_at = ?
            WHERE guild_id = ?
            """,
            (audio_policy, now, str(guild_id)),
        )
