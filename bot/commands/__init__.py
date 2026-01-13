"""
Discord command cogs for the Brain Rot bot.

Cogs are Discord.py's way of organizing commands into modular groups.
Each cog handles a specific category of functionality.
"""

# Cogs will be loaded dynamically by the bot
# from bot.commands.sound import SoundCog
# from bot.commands.tts import TTSCog
# etc.
# from bot.commands.stats import StatsCog
from bot.commands.debug import DebugCog

__all__ = [
    "SoundCog",
    "ListCog",
    "EventCog",
    "StatsCog",
    "KeywordCog",
    "DebugCog",
    "OnThisDayCog",
]
