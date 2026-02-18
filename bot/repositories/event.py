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
    
    def get_user_events(
        self,
        user_id: str,
        event_type: str,
        guild_id: Optional[int | str] = None,
    ) -> List[str]:
        """
        Get all sounds for a user's event type.
        
        Args:
            user_id: The user ID
            event_type: 'join' or 'leave'
            
        Returns:
            List of sound filenames
        """
        if guild_id is None:
            rows = self._execute(
                "SELECT * FROM users WHERE event = ? AND id = ?",
                (event_type, user_id)
            )
        else:
            rows = self._execute(
                "SELECT * FROM users WHERE event = ? AND id = ? AND (guild_id = ? OR guild_id IS NULL)",
                (event_type, user_id, str(guild_id))
            )
        return [tuple(row) for row in rows]
    
    def get_all_users_with_events(self, guild_id: Optional[int | str] = None) -> List[str]:
        """Get all unique user IDs who have event sounds configured."""
        if guild_id is None:
            rows = self._execute(
                "SELECT DISTINCT id FROM users"
            )
        else:
            rows = self._execute(
                "SELECT DISTINCT id FROM users WHERE guild_id = ? OR guild_id IS NULL",
                (str(guild_id),)
            )
        return [row['id'] for row in rows]
    
    def get_event_sound(
        self,
        user_id: str,
        event_type: str,
        sound: str,
        guild_id: Optional[int | str] = None,
    ) -> Optional[Tuple]:
        """Check if a specific user event sound exists."""
        if guild_id is None:
            row = self._execute_one(
                "SELECT * FROM users WHERE id = ? AND event = ? AND sound = ?",
                (user_id, event_type, sound)
            )
        else:
            row = self._execute_one(
                "SELECT * FROM users WHERE id = ? AND event = ? AND sound = ? AND (guild_id = ? OR guild_id IS NULL)",
                (user_id, event_type, sound, str(guild_id))
            )
        return tuple(row) if row else None
    
    def insert(
        self,
        user_id: str,
        event_type: str,
        sound: str,
        guild_id: Optional[int | str] = None,
    ) -> int:
        """Insert a new user event sound."""
        return self._execute_write(
            "INSERT INTO users (id, event, sound, guild_id) VALUES (?, ?, ?, ?)",
            (user_id, event_type, sound, str(guild_id) if guild_id is not None else None)
        )
    
    def remove(
        self,
        user_id: str,
        event_type: str,
        sound: str,
        guild_id: Optional[int | str] = None,
    ) -> bool:
        """Remove a user event sound."""
        if guild_id is None:
            self._execute_write(
                "DELETE FROM users WHERE id = ? AND event = ? AND sound = ?",
                (user_id, event_type, sound)
            )
        else:
            self._execute_write(
                "DELETE FROM users WHERE id = ? AND event = ? AND sound = ? AND (guild_id = ? OR guild_id IS NULL)",
                (user_id, event_type, sound, str(guild_id))
            )
        return True
    
    def toggle(
        self,
        user_id: str,
        event_type: str,
        sound: str,
        guild_id: Optional[int | str] = None,
    ) -> bool:
        """
        Toggle a user event sound (add if doesn't exist, remove if exists).
        
        Returns:
            True if sound was added, False if removed
        """
        existing = self.get_event_sound(user_id, event_type, sound, guild_id=guild_id)
        if existing:
            self.remove(user_id, event_type, sound, guild_id=guild_id)
            return False
        else:
            self.insert(user_id, event_type, sound, guild_id=guild_id)
            return True

    def get_events_for_sound(
        self,
        sound_filename: str,
        guild_id: Optional[int | str] = None,
    ) -> List[Tuple[str, str]]:
        """
        Get all (user_id, event_type) tuples for a specific sound.
        
        Args:
            sound_filename: The sound filename (e.g., 'sound.mp3')
            
        Returns:
            List of (user_id, event_type) tuples
        """
        # Search for both exact filename and filename without extension if needed,
        # but the DB stores 'sound' column. Usually it's the filename without extension or with?
        # Based on current usage in toggle:
        # self.insert(user_id, event_type, sound) where sound is `most_similar_sound` (no extension usually)
        # Let's check `add_user_event` in `user_event.py`:
        # most_similar_sound = exact_match.filename.replace('.mp3', '')
        # So it stores proper names without extensions.
        
        # We need to handle potential .mp3 mismatch
        clean_name = sound_filename.replace('.mp3', '')
        
        if guild_id is None:
            rows = self._execute(
                "SELECT id, event FROM users WHERE sound = ? OR sound = ?",
                (clean_name, sound_filename)
            )
        else:
            rows = self._execute(
                "SELECT id, event FROM users WHERE (sound = ? OR sound = ?) AND (guild_id = ? OR guild_id IS NULL)",
                (clean_name, sound_filename, str(guild_id))
            )
        return [(row['id'], row['event']) for row in rows]
