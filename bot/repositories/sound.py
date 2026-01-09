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
        # Check if date column exists (not all databases have it)
        date_value = None
        if 'date' in row.keys():
            try:
                date_value = datetime.fromisoformat(row['date']) if row['date'] else None
            except:
                date_value = None
        
        return Sound(
            id=row['id'],
            original_filename=row['originalfilename'],
            filename=row['filename'],
            date=date_value,
            favorite=bool(row['favorite']),
            slap=bool(row['slap']) if 'slap' in row.keys() else False,
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
    
    def get_sound(self, sound_name: str, original_filename: bool = False) -> Optional[tuple]:
        """
        Get a sound by name, returning a tuple for backwards compatibility.
        
        This matches the old Database.get_sound() return format:
        (id, originalfilename, filename, date, favorite, blacklist, slap)
        
        Args:
            sound_name: Sound filename to search for
            original_filename: If True, search by originalfilename first
            
        Returns:
            Tuple with sound data or None
        """
        if not sound_name.endswith('.mp3'):
            sound_name = f"{sound_name}.mp3"
        
        if original_filename:
            # First try originalfilename
            row = self._execute_one(
                "SELECT * FROM sounds WHERE originalfilename = ?",
                (sound_name,)
            )
            if row:
                return tuple(row)
            
            # Fall back to Filename match
            row = self._execute_one(
                "SELECT * FROM sounds WHERE Filename = ?",
                (sound_name,)
            )
            if row:
                return tuple(row)
        else:
            # First try Filename
            row = self._execute_one(
                "SELECT * FROM sounds WHERE Filename = ?",
                (sound_name,)
            )
            if row:
                return tuple(row)
            
            # Fall back to originalfilename
            row = self._execute_one(
                "SELECT * FROM sounds WHERE originalfilename = ?",
                (sound_name,)
            )
            if row:
                return tuple(row)
        
        # Final fallback: LIKE search
        sound_name_pattern = f"%{sound_name.replace('.mp3', '')}%"
        row = self._execute_one(
            "SELECT * FROM sounds WHERE Filename LIKE ? OR originalfilename LIKE ?",
            (sound_name_pattern, sound_name_pattern)
        )
        if row:
            return tuple(row)
        
        return None
    
    def get_all(self, limit: int = 100) -> List[Sound]:
        """Get all sounds, ordered by date descending."""
        rows = self._execute(
            "SELECT * FROM sounds ORDER BY id DESC LIMIT ?",
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
    
    def get_random_sounds(self, favorite: bool = None, num_sounds: int = 1) -> List[tuple]:
        """
        Get random sounds, returning tuples for backwards compatibility.
        
        Args:
            favorite: Filter by favorite status (True = favorites only)
            num_sounds: Number of sounds to return
            
        Returns:
            List of sound tuples
        """
        conditions = ["slap = 0"]  # Exclude slap sounds from random
        if favorite:
            conditions.append("favorite = 1")
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        
        rows = self._execute(
            f"SELECT * FROM sounds {where_clause} ORDER BY RANDOM() LIMIT ?",
            (num_sounds,)
        )
        return [tuple(row) for row in rows]
    
    def get_sounds(self, favorite: bool = None, slap: bool = None, num_sounds: int = 25, 
                   sort: str = "DESC", favorite_by_user: bool = False, user: str = None) -> List[tuple]:
        """
        Get sounds with filtering, returning tuples for backwards compatibility.
        """
        conditions = []
        if favorite is not None:
            conditions.append(f"favorite = {1 if favorite else 0}")
        if slap is not None:
            conditions.append(f"slap = {1 if slap else 0}")
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        
        rows = self._execute(
            f"SELECT * FROM sounds {where_clause} ORDER BY id {sort} LIMIT ?",
            (num_sounds,)
        )
        return [tuple(row) for row in rows]
    
    def get_sound_by_name(self, sound_name: str) -> Optional[tuple]:
        """
        Get a sound by its name (with or without .mp3 extension).
        Returns tuple for backwards compatibility.
        """
        # Try with .mp3
        if not sound_name.endswith('.mp3'):
            search_name = f"{sound_name}.mp3"
        else:
            search_name = sound_name
        
        # Try filename first
        row = self._execute_one(
            "SELECT * FROM sounds WHERE filename = ?",
            (search_name,)
        )
        if row:
            return tuple(row)
        
        # Try original filename
        row = self._execute_one(
            "SELECT * FROM sounds WHERE originalfilename = ?",
            (search_name,)
        )
        if row:
            return tuple(row)
        
        # Try without .mp3
        base_name = sound_name.replace('.mp3', '')
        row = self._execute_one(
            "SELECT * FROM sounds WHERE filename LIKE ? OR originalfilename LIKE ?",
            (f"%{base_name}%", f"%{base_name}%")
        )
        if row:
            return tuple(row)
        
        return None
    
    def insert_sound(self, original_filename: str, filename: str, 
                     favorite: int = 0, date=None) -> int:
        """Insert a new sound and queue embedding generation (backwards compatibility signature)."""
        from datetime import datetime
        if date is None:
            date = datetime.now()
        
        sound_id = self._execute_write(
            """
            INSERT INTO sounds (originalfilename, filename, favorite, blacklist, date, slap)
            VALUES (?, ?, ?, 0, ?, 0)
            """,
            (original_filename, filename, favorite, date.strftime("%Y-%m-%d %H:%M:%S") if hasattr(date, 'strftime') else str(date))
        )
        
        # Trigger background embedding generation
        self._generate_embedding_async(sound_id, filename)
        
        return sound_id
    
    def _generate_embedding_async(self, sound_id: int, filename: str):
        """Generate embedding in background thread (non-blocking)."""
        import threading
        import os
        
        def _do_generate():
            try:
                from bot.services.embedding_service import EmbeddingService
                from bot.repositories.embedding_repository import EmbeddingRepository
                
                service = EmbeddingService()
                repo = EmbeddingRepository()
                
                file_path = os.path.join(service.sounds_dir, filename)
                if not os.path.exists(file_path):
                    print(f"[SoundRepository] Embedding skipped - file not found: {filename}")
                    return
                
                embedding = service.generate_embedding(file_path)
                if embedding is not None:
                    emb_bytes = service.embedding_to_bytes(embedding)
                    repo.save_embedding(sound_id, filename, emb_bytes, 'openl3', service.embedding_dim)
                    print(f"[SoundRepository] Embedding generated for: {filename}")
                else:
                    print(f"[SoundRepository] Embedding failed for: {filename}")
            except Exception as e:
                print(f"[SoundRepository] Embedding error for {filename}: {e}")
        
        thread = threading.Thread(target=_do_generate, daemon=True)
        thread.start()
    
    def update_sound(self, filename: str, new_filename: str = None, 
                     favorite: int = None, slap: int = None) -> bool:
        """Update a sound's properties (backwards compatibility signature)."""
        updates = []
        params = []
        
        if new_filename is not None:
            updates.append("filename = ?")
            params.append(new_filename)
        if favorite is not None:
            updates.append("favorite = ?")
            params.append(favorite)
        if slap is not None:
            updates.append("slap = ?")
            params.append(slap)
        
        if not updates:
            return False
        
        params.append(filename if not filename.endswith('.mp3') else filename)
        if not filename.endswith('.mp3'):
            filename = f"{filename}.mp3"
        params[-1] = filename
        
        self._execute_write(
            f"UPDATE sounds SET {', '.join(updates)} WHERE filename = ?",
            tuple(params)
        )
        return True
    
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
            "SELECT * FROM sounds WHERE favorite = 1 ORDER BY id DESC LIMIT ?",
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
