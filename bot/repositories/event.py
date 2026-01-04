"""
Event repository for user event sound database operations.
"""

from typing import Optional, List, Tuple
import sqlite3

from bot.repositories.base import BaseRepository


class EventRepository(BaseRepository):
    """
    Repository for user event sounds (join/leave sounds).
    
    Handles all database operations related to user event sounds.
    """
    
    def _row_to_entity(self, row):
        """Convert a database row to an event tuple."""
        return tuple(row) if row else None
    
    def get_by_id(self, id: int):
        """Get an event by ID (not commonly used)."""
        row = self._execute_one("SELECT * FROM users WHERE id = ?", (id,))
        return self._row_to_entity(row)
    
    def get_all(self, limit: int = 100):
        """Get all user events."""
        rows = self._execute("SELECT * FROM users LIMIT ?", (limit,))
        return [self._row_to_entity(row) for row in rows]
    
    def get_user_events(self, user_id: str, event_type: str) -> List[str]:
        """
        Get all sounds for a user's event type.
        
        Args:
            user_id: The user ID
            event_type: 'join' or 'leave'
            
        Returns:
            List of sound filenames
        """
        rows = self._execute(
            "SELECT * FROM users WHERE event = ? AND id = ?",
            (event_type, user_id)
        )
        return [tuple(row) for row in rows]
    
    def get_all_users_with_events(self) -> List[str]:
        """Get all unique user IDs who have event sounds configured."""
        rows = self._execute(
            "SELECT DISTINCT id FROM users"
        )
        return [row['id'] for row in rows]
    
    def get_event_sound(self, user_id: str, event_type: str, sound: str) -> Optional[Tuple]:
        """Check if a specific user event sound exists."""
        row = self._execute_one(
            "SELECT * FROM users WHERE id = ? AND event = ? AND sound = ?",
            (user_id, event_type, sound)
        )
        return tuple(row) if row else None
    
    def insert(self, user_id: str, event_type: str, sound: str) -> int:
        """Insert a new user event sound."""
        return self._execute_write(
            "INSERT INTO users (id, event, sound) VALUES (?, ?, ?)",
            (user_id, event_type, sound)
        )
    
    def remove(self, user_id: str, event_type: str, sound: str) -> bool:
        """Remove a user event sound."""
        self._execute_write(
            "DELETE FROM users WHERE id = ? AND event = ? AND sound = ?",
            (user_id, event_type, sound)
        )
        return True
    
    def toggle(self, user_id: str, event_type: str, sound: str) -> bool:
        """
        Toggle a user event sound (add if doesn't exist, remove if exists).
        
        Returns:
            True if sound was added, False if removed
        """
        existing = self.get_event_sound(user_id, event_type, sound)
        if existing:
            self.remove(user_id, event_type, sound)
            return False
        else:
            self.insert(user_id, event_type, sound)
            return True
