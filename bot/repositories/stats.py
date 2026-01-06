"""
Stats repository for statistics and analytics database operations.
"""

from typing import Optional, List, Dict, Any
import sqlite3
from datetime import datetime

from bot.repositories.base import BaseRepository


class StatsRepository(BaseRepository):
    """
    Repository for statistics and analytics.
    
    Handles all database operations related to:
    - User year stats (for /yearreview)
    - Sound metadata (download dates, favorites)
    """
    
    def _row_to_entity(self, row):
        """Convert a database row."""
        return tuple(row) if row else None
    
    def get_by_id(self, id: int):
        """Not applicable for stats repository."""
        return None
    
    def get_all(self, limit: int = 100):
        """Not applicable for stats repository."""
        return []
    
    def get_sound_download_date(self, sound_id: int) -> Optional[str]:
        """Get the date when a sound was downloaded/added to the database."""
        try:
            # First check if the sound has a timestamp in the sounds table
            row = self._execute_one(
                "SELECT timestamp FROM sounds WHERE id = ?",
                (sound_id,)
            )
            
            if row and row['timestamp']:
                # Check if it's close to the hardcoded date
                if isinstance(row['timestamp'], str) and row['timestamp'].startswith("2023-10-30"):
                    return "2023-10-30 11:04:46"
                return row['timestamp']
            
            # Fallback: Check earliest action for this sound
            row = self._execute_one(
                "SELECT MIN(timestamp) as min_ts FROM actions WHERE target = ?",
                (str(sound_id),)
            )
            
            if row and row['min_ts']:
                if isinstance(row['min_ts'], str) and row['min_ts'].startswith("2023-10-30"):
                    return "2023-10-30 11:04:46"
                return row['min_ts']
            
            return None
        except Exception as e:
            # Column may not exist
            return None
    
    def get_users_who_favorited_sound(self, sound_id: int) -> List[str]:
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
    
    def get_user_year_stats(self, username: str, year: int) -> Dict[str, Any]:
        """
        Get comprehensive yearly stats for a user.
        
        This method performs multiple queries to aggregate user statistics
        for the year review feature.
        
        Returns:
            Dictionary with all stats for the year
        """
        stats = {
            'total_plays': 0,
            'random_plays': 0,
            'requested_plays': 0,
            'favorite_plays': 0,
            'top_sounds': [],
            'sounds_favorited': 0,
            'sounds_uploaded': 0,
            'tts_messages': 0,
            'voice_joins': 0,
            'voice_leaves': 0,
            'mute_actions': 0,
            'unique_sounds': 0,
            'most_active_day': None,
            'most_active_day_count': 0,
            'most_active_hour': None,
            'most_active_hour_count': 0,
            'first_sound': None,
            'first_sound_date': None,
            'last_sound': None,
            'last_sound_date': None,
            'user_rank': None,
            'total_users': 0,
            'total_voice_hours': 0,
            'longest_session_hours': 0,
            'longest_session_minutes': 0,
            'longest_streak': 0,
            'total_active_days': 0,
        }
        
        year_start = f"{year}-01-01 00:00:00"
        year_end = f"{year}-12-31 23:59:59"
        
        play_actions = "('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 'play_request', 'play_from_list', 'play_similar_sound')"
        
        # Total plays and breakdown
        rows = self._execute(
            f"""
            SELECT action, COUNT(*) as count
            FROM actions
            WHERE username = ? 
            AND timestamp BETWEEN ? AND ?
            AND action IN {play_actions}
            GROUP BY action
            """,
            (username, year_start, year_end)
        )
        
        for row in rows:
            action, count = row['action'], row['count']
            stats['total_plays'] += count
            if action == 'play_random_sound':
                stats['random_plays'] += count
            elif action in ['play_request', 'replay_sound', 'play_from_list', 'play_similar_sound']:
                stats['requested_plays'] += count
            elif action == 'play_random_favorite_sound':
                stats['favorite_plays'] += count
        
        # Top 5 sounds
        rows = self._execute(
            f"""
            SELECT s.Filename, COUNT(*) as play_count
            FROM actions a
            JOIN sounds s ON a.target = s.id
            WHERE a.username = ?
            AND a.timestamp BETWEEN ? AND ?
            AND a.action IN {play_actions}
            AND s.slap = 0
            GROUP BY s.Filename
            ORDER BY play_count DESC
            LIMIT 5
            """,
            (username, year_start, year_end)
        )
        stats['top_sounds'] = [(row['Filename'], row['play_count']) for row in rows]
        
        # Unique sounds
        row = self._execute_one(
            f"""
            SELECT COUNT(DISTINCT a.target) as count
            FROM actions a
            JOIN sounds s ON a.target = s.id
            WHERE a.username = ?
            AND a.timestamp BETWEEN ? AND ?
            AND a.action IN {play_actions}
            AND s.slap = 0
            """,
            (username, year_start, year_end)
        )
        stats['unique_sounds'] = row['count'] if row else 0
        
        # Most active day
        row = self._execute_one(
            f"""
            SELECT strftime('%w', timestamp) as day_of_week, COUNT(*) as count
            FROM actions
            WHERE username = ?
            AND timestamp BETWEEN ? AND ?
            AND action IN {play_actions}
            GROUP BY day_of_week
            ORDER BY count DESC
            LIMIT 1
            """,
            (username, year_start, year_end)
        )
        if row and row['day_of_week'] is not None:
            day_names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
            stats['most_active_day'] = day_names[int(row['day_of_week'])]
            stats['most_active_day_count'] = row['count']
        
        # Most active hour
        row = self._execute_one(
            f"""
            SELECT strftime('%H', timestamp) as hour, COUNT(*) as count
            FROM actions
            WHERE username = ?
            AND timestamp BETWEEN ? AND ?
            AND action IN {play_actions}
            GROUP BY hour
            ORDER BY count DESC
            LIMIT 1
            """,
            (username, year_start, year_end)
        )
        if row and row['hour'] is not None:
            stats['most_active_hour'] = int(row['hour'])
            stats['most_active_hour_count'] = row['count']
        
        # First sound of year
        row = self._execute_one(
            f"""
            SELECT s.Filename, a.timestamp
            FROM actions a
            JOIN sounds s ON a.target = s.id
            WHERE a.username = ?
            AND a.timestamp BETWEEN ? AND ?
            AND a.action IN {play_actions}
            AND s.slap = 0
            ORDER BY a.timestamp ASC
            LIMIT 1
            """,
            (username, year_start, year_end)
        )
        if row:
            stats['first_sound'] = row['Filename']
            stats['first_sound_date'] = row['timestamp']
        
        # Last sound of year
        row = self._execute_one(
            f"""
            SELECT s.Filename, a.timestamp
            FROM actions a
            JOIN sounds s ON a.target = s.id
            WHERE a.username = ?
            AND a.timestamp BETWEEN ? AND ?
            AND a.action IN {play_actions}
            AND s.slap = 0
            ORDER BY a.timestamp DESC
            LIMIT 1
            """,
            (username, year_start, year_end)
        )
        if row:
            stats['last_sound'] = row['Filename']
            stats['last_sound_date'] = row['timestamp']
        
        # User rank
        rows = self._execute(
            f"""
            SELECT username, COUNT(*) as play_count
            FROM actions
            WHERE timestamp BETWEEN ? AND ?
            AND action IN {play_actions}
            GROUP BY username
            ORDER BY play_count DESC
            """,
            (year_start, year_end)
        )
        all_users = list(rows)
        stats['total_users'] = len(all_users)
        for i, row in enumerate(all_users, 1):
            if row['username'] == username:
                stats['user_rank'] = i
                break
        
        # Active days and streak
        rows = self._execute(
            f"""
            SELECT DISTINCT date(timestamp) as play_date
            FROM actions
            WHERE username = ?
            AND timestamp BETWEEN ? AND ?
            AND action IN {play_actions}
            ORDER BY play_date ASC
            """,
            (username, year_start, year_end)
        )
        active_dates = [row['play_date'] for row in rows]
        stats['total_active_days'] = len(active_dates)
        
        # Calculate longest streak
        if active_dates:
            longest_streak = current_streak = 1
            prev_date = None
            for date_str in active_dates:
                current_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                if prev_date and (current_date - prev_date).days == 1:
                    current_streak += 1
                else:
                    current_streak = 1
                longest_streak = max(longest_streak, current_streak)
                prev_date = current_date
        stats['longest_streak'] = longest_streak
        
        return stats
    
    # ===== Analytics Dashboard Methods =====
    
    def get_activity_heatmap(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get activity counts grouped by day of week and hour for heatmap visualization.
        
        Args:
            days: Number of days to look back (0 = all time)
            
        Returns:
            List of dicts with day_of_week (0-6), hour (0-23), and count
        """
        conditions = ["action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 'play_request', 'play_from_list', 'play_similar_sound', 'play_sound_periodically')"]
        params = []
        
        if days > 0:
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            conditions.append("timestamp >= ?")
            params.append(cutoff)
        
        where_clause = " AND ".join(conditions)
        
        rows = self._execute(
            f"""
            SELECT 
                CAST(strftime('%w', timestamp) AS INTEGER) as day_of_week,
                CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                COUNT(*) as count
            FROM actions
            WHERE {where_clause}
            GROUP BY day_of_week, hour
            ORDER BY day_of_week, hour
            """,
            tuple(params)
        )
        
        return [{'day': row['day_of_week'], 'hour': row['hour'], 'count': row['count']} for row in rows]
    
    def get_activity_timeline(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get daily activity counts for timeline/line chart visualization.
        
        Args:
            days: Number of days to look back
            
        Returns:
            List of dicts with date and count
        """
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        rows = self._execute(
            """
            SELECT 
                date(timestamp) as date,
                COUNT(*) as count
            FROM actions
            WHERE action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                           'play_request', 'play_from_list', 'play_similar_sound', 'play_sound_periodically')
            AND date(timestamp) >= ?
            GROUP BY date(timestamp)
            ORDER BY date(timestamp) ASC
            """,
            (cutoff,)
        )
        
        return [{'date': row['date'], 'count': row['count']} for row in rows]
    
    def get_summary_stats(self, days: int = 0) -> Dict[str, Any]:
        """
        Get aggregated summary statistics for the analytics dashboard.
        
        Args:
            days: Number of days to look back (0 = all time)
            
        Returns:
            Dict with total_sounds, total_plays, active_users, sounds_this_week
        """
        from datetime import timedelta
        
        stats = {
            'total_sounds': 0,
            'total_plays': 0,
            'active_users': 0,
            'sounds_this_week': 0
        }
        
        # Total sounds
        row = self._execute_one("SELECT COUNT(*) as count FROM sounds")
        stats['total_sounds'] = row['count'] if row else 0
        
        # Build time filter
        time_filter = ""
        params = []
        if days > 0:
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            time_filter = "AND timestamp >= ?"
            params.append(cutoff)
        
        # Total plays
        row = self._execute_one(
            f"""
            SELECT COUNT(*) as count FROM actions 
            WHERE action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                           'play_request', 'play_from_list', 'play_similar_sound', 'play_sound_periodically')
            {time_filter}
            """,
            tuple(params)
        )
        stats['total_plays'] = row['count'] if row else 0
        
        # Active users
        row = self._execute_one(
            f"""
            SELECT COUNT(DISTINCT username) as count FROM actions 
            WHERE action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                           'play_request', 'play_from_list', 'play_similar_sound')
            {time_filter}
            """,
            tuple(params)
        )
        stats['active_users'] = row['count'] if row else 0
        
        # Sounds added this week
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        row = self._execute_one(
            "SELECT COUNT(*) as count FROM sounds WHERE timestamp >= ?",
            (week_ago,)
        )
        stats['sounds_this_week'] = row['count'] if row else 0
        
        return stats

