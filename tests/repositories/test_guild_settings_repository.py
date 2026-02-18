"""
Tests for bot/repositories/guild_settings.py - GuildSettingsRepository.
"""

from bot.repositories.base import BaseRepository
from bot.repositories.guild_settings import GuildSettingsRepository


def _repo_with_shared_db(db_connection):
    BaseRepository.set_shared_connection(db_connection, ":memory:")
    return GuildSettingsRepository(use_shared=True)


def _clear_shared_db():
    BaseRepository._shared_connection = None
    BaseRepository._shared_db_path = None


class TestGuildSettingsRepository:
    """Tests for guild settings persistence operations."""

    def test_upsert_defaults_and_get(self, db_connection):
        try:
            repo = _repo_with_shared_db(db_connection)
            repo.upsert_defaults("123", autojoin_enabled=False, periodic_enabled=True, stt_enabled=False, audio_policy="low_latency")

            settings = repo.get_by_guild_id("123")
            assert settings is not None
            assert settings.guild_id == "123"
            assert settings.autojoin_enabled is False
            assert settings.periodic_enabled is True
            assert settings.stt_enabled is False
            assert settings.audio_policy == "low_latency"
        finally:
            _clear_shared_db()

    def test_update_channels_features_and_policy(self, db_connection):
        try:
            repo = _repo_with_shared_db(db_connection)
            repo.upsert_defaults("456", autojoin_enabled=False, periodic_enabled=False, stt_enabled=False, audio_policy="low_latency")
            repo.update_channels("456", bot_text_channel_id="10", default_voice_channel_id="20")
            repo.update_features("456", autojoin_enabled=True, periodic_enabled=True, stt_enabled=True)
            repo.update_audio_policy("456", "high_quality")

            settings = repo.get_by_guild_id("456")
            assert settings is not None
            assert settings.bot_text_channel_id == "10"
            assert settings.default_voice_channel_id == "20"
            assert settings.autojoin_enabled is True
            assert settings.periodic_enabled is True
            assert settings.stt_enabled is True
            assert settings.audio_policy == "high_quality"
        finally:
            _clear_shared_db()

    def test_clear_channel(self, db_connection):
        try:
            repo = _repo_with_shared_db(db_connection)
            repo.upsert_defaults("789", autojoin_enabled=False, periodic_enabled=False, stt_enabled=False, audio_policy="low_latency")
            repo.update_channels("789", bot_text_channel_id="100", default_voice_channel_id="200")
            repo.clear_channel("789", "bot_text_channel_id")

            settings = repo.get_by_guild_id("789")
            assert settings is not None
            assert settings.bot_text_channel_id is None
            assert settings.default_voice_channel_id == "200"
        finally:
            _clear_shared_db()
