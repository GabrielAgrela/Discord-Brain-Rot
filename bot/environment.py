"""
Environment configuration loader.

This module loads environment variables from .env file
for bot configuration.
"""

import os
from dotenv import load_dotenv


class Environment:
    """
    Environment configuration container.
    
    Loads and provides access to environment variables
    needed for bot operation.
    
    Attributes:
        bot_token: Discord bot authentication token.
        ffmpeg_path: Path to FFmpeg executable.
    """
    
    def __init__(self):
        """Load environment variables from .env file."""
        load_dotenv()
        self.bot_token: str = os.getenv('DISCORD_BOT_TOKEN', '')
        self.ffmpeg_path: str = os.getenv('FFMPEG_PATH', 'ffmpeg')
