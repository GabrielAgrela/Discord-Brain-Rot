"""
Service for guild-level bot configuration and feature flags.
"""

import os
from typing import Optional

from bot.models.guild_settings import GuildSettings
from bot.repositories.guild_settings import GuildSettingsRepository


class GuildSettingsService:
    """Business logic wrapper for guild settings operations."""

    def __init__(self):
        self.repo = GuildSettingsRepository()
        self.default_autojoin = os.getenv("AUTOJOIN_DEFAULT", "false").lower() == "true"
        self.default_periodic = os.getenv("PERIODIC_DEFAULT", "false").lower() == "true"
        self.default_stt = os.getenv("STT_DEFAULT", "false").lower() == "true"
        self.default_audio_policy = os.getenv("AUDIO_LATENCY_MODE", "low_latency")

    def ensure_guild(self, guild_id: int | str) -> GuildSettings:
        """Ensure a guild has a settings row and return it."""
        gid = str(guild_id)
        try:
            self.repo.upsert_defaults(
                guild_id=gid,
                autojoin_enabled=self.default_autojoin,
                periodic_enabled=self.default_periodic,
                stt_enabled=self.default_stt,
                audio_policy=self.default_audio_policy,
            )
            settings = self.repo.get_by_guild_id(gid)
            if not settings:
                # Defensive fallback; should not happen after upsert.
                return GuildSettings(guild_id=gid)
            return settings
        except Exception:
            # Keep service resilient in tests or early startup when schema is not ready.
            return GuildSettings(
                guild_id=gid,
                autojoin_enabled=self.default_autojoin,
                periodic_enabled=self.default_periodic,
                stt_enabled=self.default_stt,
                audio_policy=self.default_audio_policy,
            )

    def get(self, guild_id: int | str) -> GuildSettings:
        """Get guild settings, creating defaults when missing."""
        return self.ensure_guild(guild_id)

    def set_channels(
        self,
        guild_id: int | str,
        bot_text_channel_id: Optional[int | str] = None,
        default_voice_channel_id: Optional[int | str] = None,
    ) -> GuildSettings:
        """Set one or more channel IDs for a guild."""
        gid = str(guild_id)
        self.ensure_guild(gid)
        try:
            self.repo.update_channels(
                guild_id=gid,
                bot_text_channel_id=str(bot_text_channel_id) if bot_text_channel_id else None,
                default_voice_channel_id=str(default_voice_channel_id) if default_voice_channel_id else None,
            )
        except Exception:
            pass
        return self.get(gid)

    def clear_channel(self, guild_id: int | str, field_name: str) -> GuildSettings:
        """Clear one configured channel field."""
        gid = str(guild_id)
        self.ensure_guild(gid)
        try:
            self.repo.clear_channel(gid, field_name)
        except Exception:
            pass
        return self.get(gid)

    def set_feature(
        self,
        guild_id: int | str,
        feature: str,
        enabled: bool,
    ) -> GuildSettings:
        """Toggle a single feature flag for a guild."""
        gid = str(guild_id)
        self.ensure_guild(gid)

        kwargs = {
            "autojoin_enabled": None,
            "periodic_enabled": None,
            "stt_enabled": None,
        }
        if feature not in kwargs:
            raise ValueError(f"Unsupported feature: {feature}")

        kwargs[feature] = enabled
        try:
            self.repo.update_features(guild_id=gid, **kwargs)
        except Exception:
            pass
        return self.get(gid)

    def set_audio_policy(self, guild_id: int | str, policy: str) -> GuildSettings:
        """Set audio policy for a guild."""
        gid = str(guild_id)
        self.ensure_guild(gid)
        try:
            self.repo.update_audio_policy(gid, policy)
        except Exception:
            pass
        return self.get(gid)

    def is_feature_enabled(self, guild_id: int | str, feature: str) -> bool:
        """Return whether a feature flag is enabled for a guild."""
        settings = self.get(guild_id)
        return bool(getattr(settings, feature))
