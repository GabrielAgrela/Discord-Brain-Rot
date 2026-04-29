"""
Repository layer for data access.

Repositories provide an abstraction over the database, enabling:
- Single Responsibility: Each repository handles one entity type
- Testability: Can be mocked for unit tests
- Consistency: Standardized CRUD operations
"""

from bot.repositories.base import BaseRepository
from bot.repositories.sound import SoundRepository
from bot.repositories.action import ActionRepository
from bot.repositories.list import ListRepository
from bot.repositories.event import EventRepository
from bot.repositories.stats import StatsRepository
from bot.repositories.keyword import KeywordRepository
from bot.repositories.voice_activity import VoiceActivityRepository
from bot.repositories.guild_settings import GuildSettingsRepository
from bot.repositories.web_control_room import WebControlRoomRepository
from bot.repositories.favorite_watcher import FavoriteWatcherRepository

__all__ = [
    "BaseRepository",
    "SoundRepository",
    "ActionRepository",
    "ListRepository",
    "EventRepository",
    "StatsRepository",
    "KeywordRepository",
    "VoiceActivityRepository",
    "GuildSettingsRepository",
    "WebControlRoomRepository",
    "FavoriteWatcherRepository",
]
