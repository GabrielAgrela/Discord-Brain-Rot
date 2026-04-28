"""
Sound-related data models.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Sound:
    """
    Represents a sound file in the database.
    
    Attributes:
        id: Unique identifier for the sound
        original_filename: Original name when uploaded
        filename: Current filename (may differ if renamed)
        favorite: Whether the sound is marked as favorite
        blacklist: Whether the sound is blacklisted from random play
        slap: Whether this is a "slap" sound effect
        date: When the sound was added
        play_count: Total number of times played (computed, not stored)
    """
    id: int
    original_filename: str
    filename: str
    favorite: bool = False
    blacklist: bool = False
    slap: bool = False
    date: Optional[datetime] = None
    play_count: int = 0
    
    @classmethod
    def from_db_row(cls, row: tuple) -> "Sound":
        """Create a Sound instance from a database row tuple."""
        # DB schema: id, originalfilename, filename, date, favorite, blacklist, slap
        if len(row) >= 7:
            return cls(
                id=row[0],
                original_filename=row[1],
                filename=row[2],
                date=datetime.fromisoformat(row[3]) if row[3] else None,
                favorite=bool(row[4]),
                blacklist=bool(row[5]),
                slap=bool(row[6]) if len(row) > 6 else False,
            )
        elif len(row) >= 3:
            # Minimal row (id, original, filename)
            return cls(
                id=row[0],
                original_filename=row[1],
                filename=row[2],
            )
        else:
            raise ValueError(f"Invalid row length: {len(row)}")
    
    @property
    def name(self) -> str:
        """Return the display name (filename without .mp3 extension)."""
        return self.filename.replace(".mp3", "")
    
    def __str__(self) -> str:
        return self.name


@dataclass
class SoundEffect:
    """
    Audio effects to apply when playing a sound.
    
    Attributes:
        speed: Playback speed multiplier (0.5 to 3.0)
        volume: Volume multiplier (0.1 to 5.0)
        reverse: Whether to play in reverse
    """
    speed: float = 1.0
    volume: float = 1.0
    reverse: bool = False
    
    def __post_init__(self):
        """Validate and clamp effect values to valid ranges."""
        self.speed = max(0.5, min(self.speed, 3.0))
        self.volume = max(0.1, min(self.volume, 5.0))
    
    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "SoundEffect":
        """Create a SoundEffect from a dictionary (e.g., from command args)."""
        if not data:
            return cls()
        return cls(
            speed=data.get("speed", 1.0),
            volume=data.get("volume", 1.0),
            reverse=data.get("reverse", False),
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary for compatibility with existing code."""
        return {
            "speed": self.speed,
            "volume": self.volume,
            "reverse": self.reverse,
        }
    
    def has_effects(self) -> bool:
        """Check if any non-default effects are applied."""
        return self.speed != 1.0 or self.volume != 1.0 or self.reverse


@dataclass
class SoundList:
    """
    A user-created list of sounds.
    
    Attributes:
        id: Unique identifier
        name: Display name of the list
        creator: Username of the list creator
        created_at: When the list was created
        sound_count: Number of sounds in the list
    """
    id: int
    name: str
    creator: str
    created_at: Optional[datetime] = None
    sound_count: int = 0
    
    @classmethod
    def from_db_row(cls, row: tuple) -> "SoundList":
        """Create a SoundList from a database row."""
        return cls(
            id=row[0],
            name=row[1],
            creator=row[2],
            created_at=datetime.fromisoformat(row[3]) if row[3] else None,
            sound_count=row[4] if len(row) > 4 else 0,
        )
