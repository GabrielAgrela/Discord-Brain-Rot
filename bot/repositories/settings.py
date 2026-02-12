"""
Settings repository for bot-wide settings database operations.
"""

from typing import Optional, List, Any
import sqlite3

from bot.repositories.base import BaseRepository


class SettingsRepository(BaseRepository[dict]):
    """
    Repository for bot settings.
    
    Handles persistent storage of bot-wide configuration.
    """
    
    def _row_to_entity(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a dict."""
        return {
            "key": row['key'],
            "value": row['value']
        }
    
    def get_by_id(self, id: str) -> Optional[dict]:
        """Get a setting by its key (ID)."""
        row = self._execute_one(
            "SELECT * FROM settings WHERE key = ?",
            (id,)
        )
        return self._row_to_entity(row) if row else None
    
    def get_all(self, limit: int = 100) -> List[dict]:
        """Get all settings."""
        rows = self._execute(
            "SELECT * FROM settings LIMIT ?",
            (limit,)
        )
        return [self._row_to_entity(row) for row in rows]
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Get a setting value by key.
        
        Args:
            key: Setting key
            default: Default value if not found
            
        Returns:
            Setting value or default
        """
        row = self._execute_one(
            "SELECT value FROM settings WHERE key = ?",
            (key,)
        )
        if row:
            value = row['value']
            # Simple type conversion
            if value.lower() == 'true': return True
            if value.lower() == 'false': return False
            try:
                if '.' in value: return float(value)
                return int(value)
            except ValueError:
                return value
        return default
    
    def set_setting(self, key: str, value: Any) -> bool:
        """
        Set a setting value.
        
        Args:
            key: Setting key
            value: Setting value
            
        Returns:
            True if set successfully
        """
        str_value = str(value)
        self._execute_write(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str_value)
        )
        return True
