"""
Guild settings model for per-server configuration.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class GuildSettings:
    """Configuration for a Discord guild."""

    guild_id: str
    bot_text_channel_id: Optional[str] = None
    default_voice_channel_id: Optional[str] = None
    autojoin_enabled: bool = False
    periodic_enabled: bool = False
    stt_enabled: bool = False
    audio_policy: str = "low_latency"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
