"""
Data models for speech training clips.

Each clip represents a captured segment of Discord voice audio,
associated with a speaker and guild, ready for labeling.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class SpeechTrainingClip:
    """Metadata for a captured speech training audio segment."""

    id: int
    guild_id: Optional[str]
    user_id: str
    username: str
    display_name: Optional[str]
    folder_name: str
    filename: str
    relative_path: str
    duration_seconds: float
    byte_size: int
    sample_rate: int = 48000
    channels: int = 2
    sample_width: int = 2
    captured_at: Optional[str] = None
    label: Optional[str] = None
    transcript: Optional[str] = None
    notes: Optional[str] = None
    reviewed_by_user_id: Optional[str] = None
    reviewed_by_username: Optional[str] = None
    reviewed_at: Optional[str] = None
