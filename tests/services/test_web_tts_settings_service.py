"""
Tests for WebTtsSettingsService — DB-backed TTS enhancer LLM settings.
"""

from __future__ import annotations

import pytest

from bot.repositories.web_tts_settings import WebTtsSettingsRepository
from bot.services.web_tts_settings import WebTtsSettingsService


@pytest.fixture
def service(tmp_path):
    """Create a service backed by a temp SQLite database."""
    db_path = tmp_path / "test.db"
    repo = WebTtsSettingsRepository(db_path=str(db_path), use_shared=False)
    repo.ensure_schema()
    svc = WebTtsSettingsService(repo)
    return svc


# ------------------------------------------------------------------
# Defaults
# ------------------------------------------------------------------


def test_default_model_from_env(service, monkeypatch):
    """The default model should come from WEB_TTS_ENHANCER_MODEL env var."""
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "openai/gpt-4o")
    settings = service.get_enhancer_settings()
    assert settings["model"] == "openai/gpt-4o"
    assert settings["default_model"] == "openai/gpt-4o"
    assert settings["stored_model"] is None


def test_default_model_fallback(service, monkeypatch):
    """When env var is unset, fall back to deepseek/deepseek-v4-flash."""
    monkeypatch.delenv("WEB_TTS_ENHANCER_MODEL", raising=False)
    settings = service.get_enhancer_settings()
    assert settings["model"] == "deepseek/deepseek-v4-flash"
    assert settings["default_model"] == "deepseek/deepseek-v4-flash"


def test_default_provider_from_env(service, monkeypatch):
    """The default provider should come from WEB_TTS_ENHANCER_PROVIDER env var."""
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "crucible")
    settings = service.get_enhancer_settings()
    assert settings["provider"] == "crucible"
    assert settings["default_provider"] == "crucible"
    assert settings["stored_provider"] is None


def test_default_provider_fallback(service, monkeypatch):
    """When env var is unset, provider falls back to empty string."""
    monkeypatch.delenv("WEB_TTS_ENHANCER_PROVIDER", raising=False)
    settings = service.get_enhancer_settings()
    assert settings["provider"] == ""
    assert settings["default_provider"] == ""


# ------------------------------------------------------------------
# Set / Get / Clear
# ------------------------------------------------------------------


def test_set_model(service, monkeypatch):
    """Setting a model override should return it as stored."""
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "deepseek/deepseek-v4-flash")
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "")
    result = service.set_enhancer_settings(
        model="openai/gpt-4o", updated_by="test"
    )
    assert result["model"] == "openai/gpt-4o"
    assert result["stored_model"] == "openai/gpt-4o"
    assert result["provider"] == ""  # model doesn't touch provider


def test_set_provider(service, monkeypatch):
    """Setting a provider override should return it as stored."""
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "")
    result = service.set_enhancer_settings(
        provider="crucible", updated_by="test"
    )
    assert result["provider"] == "crucible"
    assert result["stored_provider"] == "crucible"


def test_set_both(service, monkeypatch):
    """Setting both model and provider should work."""
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "deepseek/deepseek-v4-flash")
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "")
    result = service.set_enhancer_settings(
        model="anthropic/claude-3.5-sonnet",
        provider="deepinfra",
        updated_by="test",
    )
    assert result["model"] == "anthropic/claude-3.5-sonnet"
    assert result["provider"] == "deepinfra"


def test_set_no_args_unchanged(service, monkeypatch):
    """Calling with no args should leave settings unchanged."""
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "default-model")
    result = service.set_enhancer_settings()
    assert result["model"] == "default-model"
    assert result["stored_model"] is None


def test_clear_model_via_empty_string(service, monkeypatch):
    """Passing empty string for model should clear the override."""
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "default-model")
    service.set_enhancer_settings(model="openai/gpt-4o")
    assert service.get_enhancer_settings()["stored_model"] == "openai/gpt-4o"
    result = service.set_enhancer_settings(model="")
    assert result["stored_model"] is None
    assert result["model"] == "default-model"


def test_clear_provider_via_empty_string(service, monkeypatch):
    """Passing empty string for provider should clear the override."""
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "default-provider")
    service.set_enhancer_settings(provider="crucible")
    assert service.get_enhancer_settings()["stored_provider"] == "crucible"
    result = service.set_enhancer_settings(provider="")
    assert result["stored_provider"] is None
    assert result["provider"] == "default-provider"


def test_clear_all(service, monkeypatch):
    """clear_enhancer_settings should remove both overrides."""
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "default-model")
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "default-provider")
    service.set_enhancer_settings(model="m1", provider="p1")
    result = service.clear_enhancer_settings()
    assert result["stored_model"] is None
    assert result["stored_provider"] is None
    assert result["model"] == "default-model"
    assert result["provider"] == "default-provider"


# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------


def test_set_model_rejects_invalid(service, monkeypatch):
    """Setting an invalid model ID should raise ValueError."""
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "default-model")
    with pytest.raises(ValueError, match="Invalid model ID"):
        service.set_enhancer_settings(model="invalid model id!")


def test_set_provider_rejects_invalid(service, monkeypatch):
    """Setting an invalid provider name should raise ValueError."""
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "")
    with pytest.raises(ValueError, match="Invalid provider name"):
        service.set_enhancer_settings(provider="my provider")


def test_set_provider_accepts_slash(service, monkeypatch):
    """Provider names with forward slashes (e.g. parasail/fp8) should be accepted."""
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "")
    result = service.set_enhancer_settings(
        provider="parasail/fp8", updated_by="test"
    )
    assert result["provider"] == "parasail/fp8"
    assert result["stored_provider"] == "parasail/fp8"


# ============================================================================
# Ventura Chat LLM settings
# ============================================================================


def test_ventura_chat_defaults_from_env(service, monkeypatch):
    """Ventura chat settings should respect VENTURA_CHAT_MODEL env var."""
    monkeypatch.setenv("VENTURA_CHAT_MODEL", "openai/gpt-4o")
    monkeypatch.delenv("VENTURA_CHAT_PROVIDER", raising=False)
    settings = service.get_ventura_chat_settings()
    assert settings["model"] == "openai/gpt-4o"
    assert settings["default_model"] == "openai/gpt-4o"
    assert settings["stored_model"] is None
    assert settings["provider"] == ""
    assert settings["default_provider"] == ""


def test_ventura_chat_defaults_fallback(service, monkeypatch):
    """When VENTURA_CHAT_MODEL env is unset, fall back to hardcoded default."""
    monkeypatch.delenv("VENTURA_CHAT_MODEL", raising=False)
    monkeypatch.delenv("VENTURA_CHAT_PROVIDER", raising=False)
    settings = service.get_ventura_chat_settings()
    assert settings["model"] == "deepseek-v4-flash"
    assert settings["provider"] == ""


def test_ventura_chat_falls_back_to_old_enhancer_keys(service, monkeypatch):
    """When no ventura_chat_* keys exist, fall back to web_tts_enhancer_* keys."""
    monkeypatch.delenv("VENTURA_CHAT_MODEL", raising=False)
    monkeypatch.delenv("VENTURA_CHAT_PROVIDER", raising=False)
    service.repository.set_setting("web_tts_enhancer_model", "old-model")
    service.repository.set_setting("web_tts_enhancer_provider", "old-provider")
    settings = service.get_ventura_chat_settings()
    assert settings["model"] == "old-model"
    assert settings["provider"] == "old-provider"
    assert settings["stored_model"] == "old-model"
    assert settings["stored_provider"] == "old-provider"


def test_ventura_chat_new_keys_take_precedence_over_old(service, monkeypatch):
    """When both new and old keys exist, new keys take precedence."""
    monkeypatch.delenv("VENTURA_CHAT_MODEL", raising=False)
    monkeypatch.delenv("VENTURA_CHAT_PROVIDER", raising=False)
    service.repository.set_setting("ventura_chat_model", "new-model")
    service.repository.set_setting("ventura_chat_provider", "new-provider")
    service.repository.set_setting("web_tts_enhancer_model", "old-model")
    service.repository.set_setting("web_tts_enhancer_provider", "old-provider")
    settings = service.get_ventura_chat_settings()
    assert settings["model"] == "new-model"
    assert settings["provider"] == "new-provider"
    assert settings["stored_model"] == "new-model"
    assert settings["stored_provider"] == "new-provider"


def test_set_ventura_chat_settings(service, monkeypatch):
    """set_ventura_chat_settings should write to both new and old keys."""
    monkeypatch.setenv("VENTURA_CHAT_MODEL", "default-model")
    monkeypatch.setenv("VENTURA_CHAT_PROVIDER", "")
    result = service.set_ventura_chat_settings(
        model="anthropic/claude-3.5-sonnet",
        provider="deepinfra",
        updated_by="test",
    )
    assert result["model"] == "anthropic/claude-3.5-sonnet"
    assert result["provider"] == "deepinfra"
    assert result["stored_model"] == "anthropic/claude-3.5-sonnet"
    assert result["stored_provider"] == "deepinfra"

    # Verify both key sets were written
    assert service.repository.get_setting("ventura_chat_model") == "anthropic/claude-3.5-sonnet"
    assert service.repository.get_setting("ventura_chat_provider") == "deepinfra"
    assert service.repository.get_setting("web_tts_enhancer_model") == "anthropic/claude-3.5-sonnet"
    assert service.repository.get_setting("web_tts_enhancer_provider") == "deepinfra"


def test_clear_ventura_chat_settings_clears_both_keysets(service, monkeypatch):
    """clear_ventura_chat_settings should delete both new and old keys."""
    monkeypatch.setenv("VENTURA_CHAT_MODEL", "default-model")
    monkeypatch.setenv("VENTURA_CHAT_PROVIDER", "")
    service.set_ventura_chat_settings(model="m1", provider="p1")
    result = service.clear_ventura_chat_settings()
    assert result["stored_model"] is None
    assert result["stored_provider"] is None
    # Verify all keys are gone
    assert service.repository.get_setting("ventura_chat_model") is None
    assert service.repository.get_setting("ventura_chat_provider") is None
    assert service.repository.get_setting("web_tts_enhancer_model") is None
    assert service.repository.get_setting("web_tts_enhancer_provider") is None


def test_ventura_chat_clear_model_via_empty_string(service, monkeypatch):
    """Passing empty string for model should clear both new and old keys."""
    monkeypatch.setenv("VENTURA_CHAT_MODEL", "default-model")
    service.set_ventura_chat_settings(model="m1")
    assert service.get_ventura_chat_settings()["stored_model"] == "m1"
    # Also verify old key was set
    assert service.repository.get_setting("web_tts_enhancer_model") == "m1"
    result = service.set_ventura_chat_settings(model="")
    assert result["stored_model"] is None
    assert result["model"] == "default-model"
    assert service.repository.get_setting("ventura_chat_model") is None
    assert service.repository.get_setting("web_tts_enhancer_model") is None


def test_ventura_chat_set_rejects_invalid_model(service, monkeypatch):
    """Setting an invalid model ID via ventura chat should raise ValueError."""
    monkeypatch.setenv("VENTURA_CHAT_MODEL", "default-model")
    with pytest.raises(ValueError, match="Invalid model ID"):
        service.set_ventura_chat_settings(model="invalid model id!")


def test_ventura_chat_set_rejects_invalid_provider(service, monkeypatch):
    """Setting an invalid provider name via ventura chat should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid provider name"):
        service.set_ventura_chat_settings(provider="my provider")
