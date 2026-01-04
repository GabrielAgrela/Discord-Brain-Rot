"""
Sound repository for sound-related database operations.
"""

from typing import Optional, List, Tuple
import sqlite3
from datetime import datetime

from bot.repositories.base import BaseRepository
from bot.models.sound import Sound, SoundList


class SoundRepository(BaseRepository[Sound]):
    """
    Repository for Sound entities.
    
    Handles all database operations related to sounds, including:
    - Basic CRUD operations
    - Similarity search
    - Filtering by favorite/blacklist status
    - Sound lists management
    """
    
    def _row_to_entity(self, row: sqlite3.Row) -> Sound:
        """Convert a database row to a Sound entity."""
        return Sound(
            id=row['id'],
            original_filename=row['originalfilename'],
            filename=row['filename'],
            date=datetime.fromisoformat(row['date']) if row['date'] else None,
            favorite=bool(row['favorite']),
            favorite=bool(row['favorite']),
            slap=bool(row.get('slap', 0)) if 'slap' in row.keys() else False,
        )
    
    def get_by_id(self, id: int) -> Optional[Sound]:
        """Get a sound by its database ID."""
        row = self._execute_one(
            "SELECT * FROM sounds WHERE id = ?",
            (id,)
        )
        return self._row_to_entity(row) if row else None
    
    def get_by_filename(self, filename: str) -> Optional[Sound]:
        """
        Get a sound by its filename.
        
        Args:
            filename: The sound filename (with or without .mp3)
            
        Returns:
            Sound entity or None
        """
        # Normalize filename
        if not filename.endswith('.mp3'):
            filename = f"{filename}.mp3"
        
        row = self._execute_one(
            "SELECT * FROM sounds WHERE filename = ?",
            (filename,)
        )
        return self._row_to_entity(row) if row else None
    
    def get_all(self, limit: int = 100) -> List[Sound]:
        """Get all sounds, ordered by date descending."""
        rows = self._execute(
            "SELECT * FROM sounds ORDER BY date DESC LIMIT ?",
            (limit,)
        )
        return [self._row_to_entity(row) for row in rows]
    
    def get_random(self, count: int = 1, favorite_only: bool = False) -> List[Sound]:
        """
        Get random sound(s).
        
        Args:
            count: Number of random sounds to return
            favorite_only: Only return favorites
            
        Returns:
            List of random Sound entities
        """
        conditions = []
        if favorite_only:
            conditions.append("favorite = 1")
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        
        rows = self._execute(
            f"SELECT * FROM sounds {where_clause} ORDER BY RANDOM() LIMIT ?",
            (count,)
        )
        return [self._row_to_entity(row) for row in rows]
    
    def search(self, query: str, limit: int = 25) -> List[Tuple[Sound, int]]:
        """
        Search sounds by name similarity.
        
        This is a simplified version - for production, use the optimized
        fuzzy matching from the original Database class.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of (Sound, score) tuples ordered by relevance
        """
        # Simple LIKE search - the full fuzzy search is more complex
        rows = self._execute(
            """
            SELECT * FROM sounds 
            WHERE filename LIKE ? OR originalfilename LIKE ?
            ORDER BY 
                CASE 
                    WHEN filename LIKE ? THEN 1
                    WHEN filename LIKE ? THEN 2
                    ELSE 3
                END
            LIMIT ?
            """,
            (f"%{query}%", f"%{query}%", f"{query}%", f"%{query}%", limit)
        )
        # Return with placeholder scores (full implementation would use fuzzywuzzy)
        return [(self._row_to_entity(row), 100) for row in rows]
    
    def insert(self, original_filename: str, filename: str,
               favorite: bool = False, date: Optional[datetime] = None) -> int:
        """
        Insert a new sound.
        
        Args:
            original_filename: Original filename when uploaded
            filename: Current filename
            favorite: Whether to mark as favorite
            date: Date added (defaults to now)
            
        Returns:
            ID of the inserted sound
        """
        if date is None:
            date = datetime.now()
        
        return self._execute_write(
            """
            INSERT INTO sounds (originalfilename, filename, favorite, blacklist, date)
            VALUES (?, ?, ?, 0, ?)
            """,
            (original_filename, filename, int(favorite), date.isoformat())
        )
    
    def update(self, sound_id: int, filename: Optional[str] = None,
               favorite: Optional[bool] = None, 
               slap: Optional[bool] = None) -> bool:
        """
        Update a sound's properties.
        
        Only provided (non-None) fields are updated.
        
        Returns:
            True if update was successful
        """
        updates = []
        params = []
        
        if filename is not None:
            updates.append("filename = ?")
            params.append(filename)
        if favorite is not None:
            updates.append("favorite = ?")
            params.append(int(favorite))
        if slap is not None:
            updates.append("slap = ?")
            params.append(int(slap))
        
        if not updates:
            return False
        
        params.append(sound_id)
        self._execute_write(
            f"UPDATE sounds SET {', '.join(updates)} WHERE id = ?",
            tuple(params)
        )
        return True
    
    def delete(self, sound_id: int) -> bool:
        """Delete a sound by ID."""
        self._execute_write("DELETE FROM sounds WHERE id = ?", (sound_id,))
        return True
    
    def get_favorites(self, limit: int = 100) -> List[Sound]:
        """Get all favorite sounds."""
        rows = self._execute(
            "SELECT * FROM sounds WHERE favorite = 1 ORDER BY date DESC LIMIT ?",
            (limit,)
        )
        return [self._row_to_entity(row) for row in rows]
    
    def get_play_count(self, sound_id: int) -> int:
        """Get the total play count for a sound."""
        row = self._execute_one(
            """
            SELECT COUNT(*) as count FROM actions 
            WHERE target = (SELECT id FROM sounds WHERE id = ?)
            AND action IN ('play', 'play_random', 'play_favorite')
            """,
            (sound_id,)
        )
        return row['count'] if row else 0
    
    def get_top_played(self, days: int = 0, limit: int = 10) -> List[Tuple[Sound, int]]:
        """
        Get most played sounds.
        
        Args:
            days: Only count plays from last N days (0 = all time)
            limit: Number of results
            
        Returns:
            List of (Sound, play_count) tuples
        """
        date_filter = ""
        if days > 0:
            date_filter = f"AND a.date >= datetime('now', '-{days} days')"
        
        rows = self._execute(
            f"""
            SELECT s.*, COUNT(a.id) as play_count
            FROM sounds s
            LEFT JOIN actions a ON a.target = s.id 
                AND a.action IN ('play', 'play_random', 'play_favorite')
                {date_filter}
            GROUP BY s.id
            ORDER BY play_count DESC
            LIMIT ?
            """,
            (limit,)
        )
        return [(self._row_to_entity(row), row['play_count']) for row in rows]
