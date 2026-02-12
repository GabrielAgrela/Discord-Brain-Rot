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
from bot.repositories.settings import SettingsRepository

__all__ = [
    "BaseRepository",
    "SoundRepository",
    "ActionRepository",
    "ListRepository",
    "EventRepository",
    "StatsRepository",
    "KeywordRepository",
    "SettingsRepository",
]
