"""
Generic key-value repository for the ``app_settings`` table.

This repository provides simple get/set/delete operations for
application-level settings persisted in the shared ``app_settings``
table.  It is deliberately generic so that any subsystem (keyword
scan metadata, feature flags, admin overrides, etc.) can use it
without coupling to a domain-specific repository.

The table schema is guaranteed by ``Database._run_schema_migrations()``
and also by ``ensure_schema()`` below so both the bot process and the
Flask web process can read/write settings.
"""

from __future__ import annotations

from typing import Any

import sqlite3

from bot.repositories.base import BaseRepository

APP_SETTINGS_TABLE = "app_settings"


class AppSettingsRepository(BaseRepository[dict[str, Any]]):
    """
    Repository for the app-level settings key-value store.

    Each row is a simple (key, value, updated_by, created_at, updated_at)
    tuple.  Callers are responsible for serialising complex values (e.g.
    JSON) before writing.
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

    def get_settings(self, keys: list[str]) -> dict[str, str | None]:
        """
        Return values for multiple keys in a single query.

        Args:
            keys: List of setting key names.

        Returns:
            Dict mapping each requested key to its value (or ``None``).
        """
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        rows = self._execute(
            f"SELECT key, value FROM {APP_SETTINGS_TABLE} "
            f"WHERE key IN ({placeholders})",
            keys,
        )
        values: dict[str, str | None] = {k: None for k in keys}
        for row in rows:
            values[row["key"]] = row["value"]
        return values

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

    def set_settings(self, settings: dict[str, str], updated_by: str | None = None) -> None:
        """
        Upsert multiple settings in a single transaction.

        Args:
            settings: Dict of key-value pairs to persist.
            updated_by: Optional identifier of who made the change.
        """
        for key, value in settings.items():
            self.set_setting(key, value, updated_by=updated_by)

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
