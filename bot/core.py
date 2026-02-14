"""
Core Bot class - Main Discord bot instance.

This module provides the Bot class which extends commands.Bot
with additional attributes for bot configuration.
"""

import discord
from discord.ext import commands


class Bot(commands.Bot):
    """
    Main Discord bot class with custom attributes.
    
    Attributes:
        token: Discord bot token for authentication.
        ffmpeg_path: Path to FFmpeg executable for audio processing.
        startup_sound_played: Flag to track if startup sound has been played.
        startup_announcement_sent: Flag to prevent duplicate startup messages.
    """
    
    def __init__(self, command_prefix: str, intents: discord.Intents, 
                 token: str, ffmpeg_path: str):
        """
        Initialize the bot.
        
        Args:
            command_prefix: Prefix for text commands.
            intents: Discord intents configuration.
            token: Bot authentication token.
            ffmpeg_path: Path to FFmpeg executable.
        """
        super().__init__(command_prefix=command_prefix, intents=intents)
        self.token = token
        self.ffmpeg_path = ffmpeg_path
        self.startup_sound_played = False
        self.startup_announcement_sent = False

    def run_bot(self) -> None:
        """Start the bot using the configured token."""
        self.run(self.token)
