"""
Centralized configuration for the Discord Brain Rot bot.

This module contains all configuration constants, TTS profiles, and paths
that were previously scattered across the codebase.
"""

import os
from pathlib import Path

# ============================================================================
# Paths
# ============================================================================

# Project root directory
PROJECT_ROOT = Path(__file__).parent.absolute()

# Sound files directory
SOUNDS_DIR = PROJECT_ROOT / "Sounds"

# Downloads directory (for temporary downloads)
DOWNLOADS_DIR = PROJECT_ROOT / "Downloads"

# Data directory
DATA_DIR = PROJECT_ROOT / "Data"

# Database path
DATABASE_PATH = PROJECT_ROOT / "database.db"

# Log file path
COMMAND_LOG_FILE = '/var/log/personalgreeter.log'


# ============================================================================
# Discord Configuration
# ============================================================================

# Bot command prefix (for text commands, if any)
COMMAND_PREFIX = "*"

# Role names for permission checks
DEVELOPER_ROLE = "DEVELOPER"
MODERATOR_ROLE = "MODERATOR"

# Default channels
BOT_CHANNEL_NAME = "bot"


# ============================================================================
# TTS Profiles
# ============================================================================

TTS_PROFILES = {
    "ventura": {
        "display": "Ventura (PT-PT)",
        "flag": ":flag_pt:",
        "thumbnail": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d2/Andr%C3%A9_Ventura_%28Agencia_LUSA%2C_Entrevista_Presidenciais_2021%29%2C_cropped.png/250px-Andr%C3%A9_Ventura_%28Agencia_LUSA%2C_Entrevista_Presidenciais_2021%29%2C_cropped.png",
        "provider": "elevenlabs",
        "voice": "pt",
    },
    "costa": {
        "display": "Costa (PT-PT)",
        "flag": ":flag_pt:",
        "thumbnail": "https://filipamoreno.com/wp-content/uploads/2015/09/18835373_7vzpq.png",
        "provider": "elevenlabs",
        "voice": "costa",
    },
    "tyson": {
        "display": "Tyson (EN)",
        "flag": ":flag_us:",
        "thumbnail": "https://static.wikia.nocookie.net/ippo/images/0/00/Mike_Tyson.png",
        "provider": "elevenlabs",
        "voice": "en",
    },
    "en": {
        "display": "English (Google)",
        "flag": ":flag_gb:",
        "provider": "gtts",
        "lang": "en",
    },
    "pt": {
        "display": "Portuguese (PT - Google)",
        "flag": ":flag_pt:",
        "provider": "gtts",
        "lang": "pt",
    },
    "br": {
        "display": "Portuguese (BR - Google)",
        "flag": ":flag_br:",
        "provider": "gtts",
        "lang": "pt",
        "region": "com.br",
    },
    "es": {
        "display": "Spanish",
        "flag": ":flag_es:",
        "provider": "gtts",
        "lang": "es",
    },
    "fr": {
        "display": "French",
        "flag": ":flag_fr:",
        "provider": "gtts",
        "lang": "fr",
    },
    "de": {
        "display": "German",
        "flag": ":flag_de:",
        "provider": "gtts",
        "lang": "de",
    },
    "ru": {
        "display": "Russian",
        "flag": ":flag_ru:",
        "provider": "gtts",
        "lang": "ru",
    },
    "ar": {
        "display": "Arabic",
        "flag": ":flag_sa:",
        "provider": "gtts",
        "lang": "ar",
    },
    "ch": {
        "display": "Chinese (Mandarin)",
        "flag": ":flag_cn:",
        "provider": "gtts",
        "lang": "zh-CN",
    },
    "ir": {
        "display": "Irish English",
        "flag": ":flag_ie:",
        "provider": "gtts",
        "lang": "en",
        "region": "ie",
    },
}

# Default TTS thumbnail when no profile-specific one is available
DEFAULT_TTS_THUMBNAIL = "https://cdn-icons-png.flaticon.com/512/4470/4470312.png"

# List of ElevenLabs voice choices (for STS command)
CHARACTER_CHOICES = [
    choice for choice, profile in TTS_PROFILES.items() 
    if profile.get("provider") == "elevenlabs"
]


# ============================================================================
# Playback Settings
# ============================================================================

# Default playback settings
DEFAULT_SPEED = 1.0
DEFAULT_VOLUME = 1.0

# Speed limits
MIN_SPEED = 0.5
MAX_SPEED = 3.0

# Volume limits
MIN_VOLUME = 0.1
MAX_VOLUME = 5.0

# Number of sound suggestions to show
DEFAULT_SUGGESTIONS = 5

# Progress bar update interval (seconds)
PROGRESS_UPDATE_INTERVAL = 2


# ============================================================================
# Periodic Task Settings
# ============================================================================

# Playback queue check interval (seconds)
PLAYBACK_QUEUE_INTERVAL = 5.0

# Mute duration default (seconds)
DEFAULT_MUTE_DURATION = 1800  # 30 minutes


# ============================================================================
# Web Interface Settings
# ============================================================================

# Default guild ID for web playback requests
DEFAULT_GUILD_ID = 359077662742020107

# Web server settings
WEB_HOST = '0.0.0.0'
WEB_PORT = 8080
