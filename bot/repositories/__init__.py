"""
Repository layer for data access.

Repositories provide an abstraction over the database, enabling:
- Single Responsibility: Each repository handles one entity type
- Testability: Can be mocked for unit tests
- Consistency: Standardized CRUD operations
"""

from bot.repositories.base import BaseRepository
from bot.repositories.sound import SoundRepository

__all__ = [
    "BaseRepository",
    "SoundRepository",
]
