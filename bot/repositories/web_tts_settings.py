"""
Repository for web TTS settings stored in the database.

Provides a simple key-value store for app-level settings such as the
Ventura TTS model override.  The table is created via ``ensure_schema()``
and also in ``Database._run_schema_migrations()`` so both the Flask web
process and the bot process can read/write settings.
"""

from __future__ import annotations

import re
from typing import Any

import sqlite3

from bot.repositories.base import BaseRepository

APP_SETTINGS_TABLE = "app_settings"

# Valid OpenRouter model ID pattern: alphanumeric, dot, underscore,
# colon, hyphen, forward-slash, 1-128 characters.
_VALID_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9._:\/\-]{1,128}$")

# Valid provider name pattern: alphanumeric, dot, underscore, colon, hyphen, forward-slash.
_VALID_PROVIDER_RE = re.compile(r"^[A-Za-z0-9._:\/\-]{1,128}$")


class WebTtsSettingsRepository(BaseRepository[dict[str, Any]]):
    """
    Repository for app-level settings key-value store.

    Used to persist debug/admin overrides like the TTS enhancer LLM
    model ID and provider.
    """

    def _row_to_entity(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a row to a plain dictionary."""
        return dict(row)

    def get_by_id(self, id: int) -> dict[str, Any] | None:
        """Not used for this key-value repository."""
        return None

    def get_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """Not used for this key-value repository."""
        return []

    def ensure_schema(self) -> None:
        """Create the ``app_settings`` table if it does not exist."""
        self._execute(
            f"""
            CREATE TABLE IF NOT EXISTS {APP_SETTINGS_TABLE} (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_by TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def get_setting(self, key: str) -> str | None:
        """
        Return the value for *key*, or ``None`` if not set.

        Args:
            key: Setting key name.

        Returns:
            Stored value string or ``None``.
        """
        row = self._execute_one(
            f"SELECT value FROM {APP_SETTINGS_TABLE} WHERE key = ?",
            (key,),
        )
        return row["value"] if row else None

    def set_setting(
        self, key: str, value: str, updated_by: str | None = None
    ) -> None:
        """
        Upsert *value* for *key*.

        Args:
            key: Setting key name.
            value: Value string to persist.
            updated_by: Optional identifier of who made the change.
        """
        self._execute_write(
            f"""
            INSERT INTO {APP_SETTINGS_TABLE} (key, value, updated_by, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, value, updated_by),
        )

    def delete_setting(self, key: str) -> None:
        """
        Delete *key* from the settings table.

        Args:
            key: Setting key name to remove.
        """
        self._execute_write(
            f"DELETE FROM {APP_SETTINGS_TABLE} WHERE key = ?",
            (key,),
        )

    @staticmethod
    def validate_model_id(model_id: str) -> str | None:
        """
        Validate and normalize an OpenRouter model ID.

        Returns the cleaned model ID on success, or ``None`` if the value
        is empty, too long, or contains disallowed characters.

        Allowed characters: ``[A-Za-z0-9._/:-]``, length 1-128.
        """
        cleaned = model_id.strip()
        if not cleaned:
            return None
        if len(cleaned) > 128:
            return None
        if not _VALID_MODEL_ID_RE.match(cleaned):
            return None
        return cleaned

    @staticmethod
    def validate_provider_name(provider: str) -> str | None:
        """
        Validate and normalize an OpenRouter provider name/ID.

        Returns the cleaned provider name on success, or ``None`` if
        the value is empty, too long, or contains disallowed characters.

        Allowed characters: ``[A-Za-z0-9._/:-]``, length 1-128.
        """
        cleaned = provider.strip()
        if not cleaned:
            return None
        if len(cleaned) > 128:
            return None
        if not _VALID_PROVIDER_RE.match(cleaned):
            return None
        return cleaned
