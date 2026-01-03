"""
Bot package - Core bot components and utilities.

This package contains the main bot behavior, database access,
TTS functionality, UI components, and various downloaders.
"""

from bot.core import Bot
from bot.environment import Environment
from bot.database import Database
from bot.behavior import BotBehavior

__all__ = [
    'Bot',
    'Environment', 
    'Database',
    'BotBehavior',
]
