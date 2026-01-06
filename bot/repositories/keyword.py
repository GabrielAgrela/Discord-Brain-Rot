"""
Keyword repository for keyword detection database operations.
"""

from typing import Optional, List, Dict, Tuple
import sqlite3
from bot.repositories.base import BaseRepository


class KeywordRepository(BaseRepository):
    """
    Repository for keyword management.
    
    Handles CRUD operations for trigger keywords.
    """
    
    def _row_to_entity(self, row: sqlite3.Row) -> Dict:
        """Convert a database row to a dictionary."""
        return dict(row) if row else None

    def get_by_id(self, keyword_id: int) -> Optional[Dict]:
        """Get a keyword by ID."""
        row = self._execute_one("SELECT * FROM keywords WHERE id = ?", (keyword_id,))
        return self._row_to_entity(row)
    
    def get_all(self, limit: int = 100) -> List[Dict]:
        """Get all keywords and their actions."""
        rows = self._execute("SELECT * FROM keywords ORDER BY keyword LIMIT ?", (limit,))
        return [self._row_to_entity(row) for row in rows]
    
    def get_as_dict(self) -> Dict[str, str]:
        """Get keywords as a dictionary mapping keyword -> action (e.g. 'slap' or 'list:name')."""
        rows = self.get_all()
        result = {}
        for row in rows:
            if row['action_type'] == "slap":
                result[row['keyword']] = "slap"
            else:
                result[row['keyword']] = f"{row['action_type']}:{row['action_value']}"
        return result

    def get_by_keyword(self, keyword: str) -> Optional[Dict]:
        """Get a specific keyword entry."""
        row = self._execute_one("SELECT * FROM keywords WHERE keyword = ?", (keyword.lower(),))
        return dict(row) if row else None

    def add(self, keyword: str, action_type: str, action_value: str = "") -> bool:
        """Add or update a keyword."""
        try:
            self._execute_write(
                "INSERT OR REPLACE INTO keywords (keyword, action_type, action_value) VALUES (?, ?, ?)",
                (keyword.lower(), action_type, action_value)
            )
            return True
        except Exception as e:
            print(f"[KeywordRepository] Error adding keyword: {e}")
            return False

    def remove(self, keyword: str) -> bool:
        """Remove a keyword."""
        try:
            self._execute_write("DELETE FROM keywords WHERE keyword = ?", (keyword.lower(),))
            return True
        except Exception as e:
            print(f"[KeywordRepository] Error removing keyword: {e}")
            return False
