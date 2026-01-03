"""
Data models (DTOs) for the Discord Brain Rot bot.

These dataclasses provide type-safe representations of database entities
and enable cleaner interfaces between layers.
"""

from bot.models.sound import Sound, SoundEffect
from bot.models.user import User, UserEvent
from bot.models.action import Action

__all__ = [
    "Sound",
    "SoundEffect", 
    "User",
    "UserEvent",
    "Action",
]
