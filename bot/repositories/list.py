"""
List repository for sound list database operations.
"""

from typing import Optional, List, Tuple
import sqlite3
from datetime import datetime

from bot.repositories.base import BaseRepository


class ListRepository(BaseRepository):
    """
    Repository for sound list management.
    
    Handles all database operations related to sound lists, including:
    - List CRUD operations
    - Adding/removing sounds from lists
    - Querying list contents
    """
    
    def _row_to_entity(self, row):
        """Convert a database row to a list tuple."""
        return tuple(row) if row else None
    
    def get_by_id(self, list_id: int) -> Optional[Tuple]:
        """Get a list by ID."""
        row = self._execute_one(
            "SELECT * FROM sound_lists WHERE id = ?",
            (list_id,)
        )
        return (row['id'], row['list_name'], row['creator']) if row else None
    
    def create(self, name: str, creator: str) -> int:
        """
        Create a new sound list.
        
        Args:
            name: The list name
            creator: Username of the creator
            
        Returns:
            ID of the created list
        """
        return self._execute_write(
            "INSERT INTO sound_lists (list_name, creator) VALUES (?, ?)",
            (name, creator)
        )
    
    def delete(self, list_id: int) -> bool:
        """Delete a sound list and its items."""
        self._execute_write("DELETE FROM sound_list_items WHERE list_id = ?", (list_id,))
        self._execute_write("DELETE FROM sound_lists WHERE id = ?", (list_id,))
        return True
    
    def get_by_name(self, name: str, creator: str = None) -> Optional[Tuple]:
        """Get a list by name and optionally creator."""
        if creator:
            row = self._execute_one(
                "SELECT * FROM sound_lists WHERE list_name = ? AND creator = ?",
                (name, creator)
            )
        else:
            row = self._execute_one(
                "SELECT * FROM sound_lists WHERE list_name = ?",
                (name,)
            )
        return (row['id'], row['list_name'], row['creator']) if row else None
    
    def get_all(self, creator: str = None, limit: int = 100) -> List[Tuple]:
        """
        Get all sound lists, optionally filtered by creator.
        
        Args:
            creator: Optional filter by creator username
            limit: Maximum number of lists to return
        
        Returns:
            List of (id, list_name, creator, sound_count) tuples
        """
        if creator:
            rows = self._execute(
                """
                SELECT sl.id, sl.list_name, sl.creator, COUNT(sli.id) as sound_count
                FROM sound_lists sl
                LEFT JOIN sound_list_items sli ON sl.id = sli.list_id
                WHERE sl.creator = ?
                GROUP BY sl.id
                ORDER BY sl.list_name
                LIMIT ?
                """,
                (creator, limit)
            )
        else:
            rows = self._execute(
                """
                SELECT sl.id, sl.list_name, sl.creator, COUNT(sli.id) as sound_count
                FROM sound_lists sl
                LEFT JOIN sound_list_items sli ON sl.id = sli.list_id
                GROUP BY sl.id
                ORDER BY sl.list_name
                LIMIT ?
                """,
                (limit,)
            )
        return [(row['id'], row['list_name'], row['creator'], row['sound_count']) for row in rows]
    
    def add_sound(self, list_id: int, sound_filename: str) -> bool:
        """
        Add a sound to a list.
        
        Returns:
            True if added, False if already exists
        """
        # Check if already exists
        existing = self._execute_one(
            "SELECT id FROM sound_list_items WHERE list_id = ? AND sound_filename = ?",
            (list_id, sound_filename)
        )
        if existing:
            return False
        
        self._execute_write(
            "INSERT INTO sound_list_items (list_id, sound_filename, added_at) VALUES (?, ?, ?)",
            (list_id, sound_filename, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        return True
    
    def remove_sound(self, list_id: int, sound_filename: str) -> bool:
        """Remove a sound from a list."""
        self._execute_write(
            "DELETE FROM sound_list_items WHERE list_id = ? AND sound_filename = ?",
            (list_id, sound_filename)
        )
        return True
    
    def get_sounds_in_list(self, list_id: int) -> List[Tuple]:
        """
        Get all sounds in a list.
        
        Returns:
            List of sound data tuples
        """
        rows = self._execute(
            """
            SELECT s.* 
            FROM sounds s
            JOIN sound_list_items sli ON s.Filename = sli.sound_filename
            WHERE sli.list_id = ?
            ORDER BY sli.added_at DESC
            """,
            (list_id,)
        )
        return [tuple(row) for row in rows]
    
    def get_lists_containing_sound(self, sound_filename: str) -> List[Tuple]:
        """
        Get all lists that contain a specific sound.
        
        Returns:
            List of (id, list_name, creator) tuples
        """
        rows = self._execute(
            """
            SELECT sl.id, sl.list_name, sl.creator
            FROM sound_lists sl
            JOIN sound_list_items sli ON sl.id = sli.list_id
            WHERE sli.sound_filename = ?
            ORDER BY sl.list_name
            """,
            (sound_filename,)
        )
        return [(row['id'], row['list_name'], row['creator']) for row in rows]
    
    def get_random_sound_from_list(self, list_name: str) -> Optional[Tuple]:
        """Get a random sound from a list by name."""
        row = self._execute_one(
            """
            SELECT s.*
            FROM sounds s
            JOIN sound_list_items sli ON s.Filename = sli.sound_filename
            JOIN sound_lists sl ON sli.list_id = sl.id
            WHERE sl.list_name = ?
            ORDER BY RANDOM()
            LIMIT 1
            """,
            (list_name,)
        )
        return tuple(row) if row else None
