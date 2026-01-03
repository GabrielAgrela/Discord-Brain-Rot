"""
Action-related data models for tracking bot usage.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Action:
    """
    Represents a logged action in the system.
    
    Actions track user interactions like playing sounds, joining voice,
    using TTS, etc.
    
    Attributes:
        id: Database ID
        username: Who performed the action
        action: Action type (e.g., 'play', 'join', 'tts')
        target: What the action was performed on (e.g., sound name)
        timestamp: When the action occurred
    """
    id: int
    username: str
    action: str
    target: str
    timestamp: Optional[datetime] = None
    
    @classmethod
    def from_db_row(cls, row: tuple) -> "Action":
        """Create an Action from a database row."""
        return cls(
            id=row[0],
            username=row[1],
            action=row[2],
            target=row[3] if len(row) > 3 else "",
            timestamp=datetime.fromisoformat(row[4]) if len(row) > 4 and row[4] else None,
        )
    
    # Common action type constants
    PLAY = "play"
    PLAY_RANDOM = "play_random"
    PLAY_FAVORITE = "play_favorite"
    JOIN = "join"
    LEAVE = "leave"
    TTS = "tts"
    STS = "sts"
    MUTE = "mute"
    UNMUTE = "unmute"
    FAVORITE = "favorite"
    UNFAVORITE = "unfavorite"
    UPLOAD = "upload"
    RENAME = "rename"
