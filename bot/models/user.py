"""
User-related data models.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List


@dataclass
class User:
    """
    Represents a Discord user in the system.
    
    Attributes:
        id: Database ID
        username: Discord username (may include discriminator)
        discord_id: Discord snowflake ID (if stored)
    """
    id: int
    username: str
    discord_id: Optional[int] = None
    
    @classmethod
    def from_db_row(cls, row: tuple) -> "User":
        """Create a User from a database row."""
        return cls(
            id=row[0],
            username=row[1],
            discord_id=row[2] if len(row) > 2 else None,
        )


@dataclass
class UserEvent:
    """
    Represents a user's configured event sound (join/leave).
    
    Attributes:
        id: Database ID
        user_id: Username string (legacy format)
        event: Event type ('join' or 'leave')
        sound: Sound filename to play
    """
    id: int
    user_id: str
    event: str  # 'join' or 'leave'
    sound: str
    
    @classmethod
    def from_db_row(cls, row: tuple) -> "UserEvent":
        """Create a UserEvent from a database row."""
        return cls(
            id=row[0],
            user_id=row[1],
            event=row[2],
            sound=row[3] if len(row) > 3 else "",
        )
    
    @property
    def is_join(self) -> bool:
        """Check if this is a join event."""
        return self.event == "join"
    
    @property
    def is_leave(self) -> bool:
        """Check if this is a leave event."""
        return self.event == "leave"


@dataclass
class UserStats:
    """
    Aggregated user statistics for year review.
    
    This is a DTO for the /yearreview command data.
    """
    username: str
    year: int
    
    # Play counts
    total_plays: int = 0
    requested_plays: int = 0
    random_plays: int = 0
    favorite_plays: int = 0
    unique_sounds: int = 0
    
    # Top sounds
    top_sounds: List[tuple] = None  # List of (filename, count)
    
    # Activity
    sounds_favorited: int = 0
    sounds_uploaded: int = 0
    tts_messages: int = 0
    voice_joins: int = 0
    mute_actions: int = 0
    
    # Time stats
    most_active_day: Optional[str] = None
    most_active_day_count: int = 0
    most_active_hour: Optional[int] = None
    most_active_hour_count: int = 0
    
    # Voice time
    total_voice_hours: int = 0
    longest_session_minutes: int = 0
    longest_session_hours: int = 0
    longest_streak: int = 0
    total_active_days: int = 0
    
    # First/last sounds
    first_sound: Optional[str] = None
    first_sound_date: Optional[str] = None
    last_sound: Optional[str] = None
    last_sound_date: Optional[str] = None
    
    # Rank
    user_rank: Optional[int] = None
    total_users: Optional[int] = None
    
    # Brain rot activities
    brain_rot: Optional[dict] = None
    
    def __post_init__(self):
        if self.top_sounds is None:
            self.top_sounds = []
        if self.brain_rot is None:
            self.brain_rot = {}
