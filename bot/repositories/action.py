"""
Action repository for action-related database operations.
"""

from typing import Optional, List, Tuple
import sqlite3
from datetime import datetime, timedelta

from bot.repositories.base import BaseRepository


class ActionRepository(BaseRepository):
    """
    Repository for action logging and retrieval.
    
    Handles all database operations related to user actions, including:
    - Logging actions (play, favorite, etc.)
    - Getting top users/sounds statistics
    - Play count tracking
    """
    
    def _row_to_entity(self, row):
        """Convert a database row to an action tuple."""
        return tuple(row) if row else None
    
    def get_by_id(self, id: int):
        """Get an action by its ID (not commonly used for actions)."""
        row = self._execute_one("SELECT * FROM actions WHERE id = ?", (id,))
        return self._row_to_entity(row)
    
    def get_all(self, limit: int = 100):
        """Get all actions (not commonly used)."""
        rows = self._execute("SELECT * FROM actions ORDER BY timestamp DESC LIMIT ?", (limit,))
        return [self._row_to_entity(row) for row in rows]
    
    def insert(self, username: str, action: str, target) -> int:
        """
        Log a user action.
        
        Args:
            username: The user performing the action
            action: Action type (e.g., 'play_random_sound', 'favorite_sound')
            target: Target of the action (usually sound ID or filename)
            
        Returns:
            ID of the inserted action
        """
        return self._execute_write(
            "INSERT INTO actions (username, action, target, timestamp) VALUES (?, ?, ?, ?)",
            (username, action, str(target), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
    
    def get_top_users(self, days: int = 0, limit: int = 5, by: str = "plays") -> List[Tuple[str, int]]:
        """
        Get users with most activity.
        
        Args:
            days: Only count actions from last N days (0 = all time)
            limit: Number of results
            by: Sort by 'plays' or other metric
            
        Returns:
            List of (username, count) tuples
        """
        date_filter = ""
        params = []
        
        if days > 0:
            date_filter = "AND timestamp >= ?"
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            params.append(cutoff)
        
        params.append(limit)
        
        rows = self._execute(
            f"""
            SELECT username, COUNT(*) as count
            FROM actions
            WHERE action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                            'play_request', 'play_from_list', 'play_similar_sound')
            {date_filter}
            GROUP BY username
            ORDER BY count DESC
            LIMIT ?
            """,
            tuple(params)
        )
        return [(row['username'], row['count']) for row in rows]
    
    def get_top_sounds(self, days: int = 0, limit: int = 5, user: str = None) -> Tuple[List[Tuple[str, int]], int]:
        """
        Get most played sounds.
        
        Args:
            days: Only count plays from last N days (0 = all time)
            limit: Number of results
            user: Filter by specific user (optional)
            
        Returns:
            Tuple of (list of (filename, count) tuples, total plays)
        """
        conditions = ["a.action IN ('play_sound_periodically','play_random_sound', 'replay_sound', 'play_random_favorite_sound', 'play_request')"]
        params = []
        
        if days > 0:
            conditions.append("a.timestamp >= ?")
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            params.append(cutoff)
        
        if user:
            conditions.append("a.username = ?")
            params.append(user)
        
        where_clause = " AND ".join(conditions)
        params.append(limit)
        
        rows = self._execute(
            f"""
            SELECT s.Filename, COUNT(*) as count
            FROM actions a
            JOIN sounds s ON a.target = s.id
            WHERE {where_clause}
            GROUP BY s.Filename
            ORDER BY count DESC
            LIMIT ?
            """,
            tuple(params)
        )
        
        # Get total
        total_row = self._execute_one(
            f"""
            SELECT COUNT(*) as total
            FROM actions a
            WHERE {where_clause.replace('LIMIT ?', '')}
            """,
            tuple(params[:-1])
        )
        total = total_row['total'] if total_row else 0
        
        return [(row['Filename'], row['count']) for row in rows], total
    
    def get_sound_play_count(self, sound_id: int) -> int:
        """Get the total play count for a specific sound."""
        row = self._execute_one(
            """
            SELECT COUNT(*) as count 
            FROM actions 
            WHERE target = ?
            AND action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                          'play_request', 'play_from_list', 'play_similar_sound', 'play_sound_periodically')
            """,
            (str(sound_id),)
        )
        return row['count'] if row else 0
    
    def get_users_who_favorited(self, sound_id: int) -> List[str]:
        """Get all users who have favorited a specific sound."""
        rows = self._execute(
            """
            WITH UserActions AS (
                SELECT 
                    username,
                    action,
                    timestamp,
                    ROW_NUMBER() OVER (PARTITION BY username ORDER BY timestamp DESC) as rn
                FROM actions
                WHERE target = ?
                AND action IN ('favorite_sound', 'unfavorite_sound')
            )
            SELECT username
            FROM UserActions
            WHERE rn = 1 AND action = 'favorite_sound'
            ORDER BY username
            """,
            (str(sound_id),)
        )
        return [row['username'] for row in rows]
    
    def get_sounds_on_this_day(self, months_ago: int = 12, limit: int = 10) -> List[Tuple[str, int]]:
        """
        Get sounds that were popular on this day in the past.
        
        Args:
            months_ago: How many months to look back (12 = 1 year, 1 = 1 month)
            limit: Maximum number of sounds to return
            
        Returns:
            List of (filename, play_count) tuples for sounds played on that date
        """
        # Calculate the target date range (same day/month in the past)
        target_date = datetime.now() - timedelta(days=months_ago * 30)
        
        # Use a 3-day window around the target date to capture more data
        start_date = (target_date - timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
        end_date = (target_date + timedelta(days=1)).strftime("%Y-%m-%d 23:59:59")
        
        rows = self._execute(
            """
            SELECT s.Filename, COUNT(*) as count
            FROM actions a
            JOIN sounds s ON CAST(a.target AS INTEGER) = s.id
            WHERE a.action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                              'play_request', 'play_from_list', 'play_similar_sound', 'play_sound_periodically')
            AND a.timestamp BETWEEN ? AND ?
            AND s.slap = 0
            GROUP BY s.Filename
            ORDER BY count DESC
            LIMIT ?
            """,
            (start_date, end_date, limit)
        )
        
        return [(row['Filename'], row['count']) for row in rows]
