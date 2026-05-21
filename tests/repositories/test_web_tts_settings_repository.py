"""
Tests for WebTtsSettingsRepository — key-value app settings store.
"""

from __future__ import annotations

import pytest

from bot.repositories.web_tts_settings import (
    WebTtsSettingsRepository,
    APP_SETTINGS_TABLE,
)


@pytest.fixture
def repo(tmp_path):
    """Create a repository backed by a temp SQLite database."""
    db_path = tmp_path / "test.db"
    r = WebTtsSettingsRepository(db_path=str(db_path), use_shared=False)
    r.ensure_schema()
    return r


# ------------------------------------------------------------------
# Schema
# ------------------------------------------------------------------


def test_ensure_schema_creates_table(repo):
    """Schema should be created and queryable."""
    row = repo._execute_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (APP_SETTINGS_TABLE,),
    )
    assert row is not None
    assert row["name"] == APP_SETTINGS_TABLE


# ------------------------------------------------------------------
# Get / Set / Delete
# ------------------------------------------------------------------


def test_get_setting_returns_none_for_missing_key(repo):
    """Missing key should return None."""
    assert repo.get_setting("nonexistent") is None


def test_set_and_get_setting(repo):
    """A value written via set_setting should be readable."""
    repo.set_setting("test_key", "test_value", updated_by="tester")
    value = repo.get_setting("test_key")
    assert value == "test_value"


def test_set_setting_upserts(repo):
    """Writing the same key again should update the value."""
    repo.set_setting("mykey", "old_value")
    repo.set_setting("mykey", "new_value", updated_by="admin")
    value = repo.get_setting("mykey")
    assert value == "new_value"


def test_delete_setting(repo):
    """A deleted setting should return None."""
    repo.set_setting("todelete", "some_value")
    repo.delete_setting("todelete")
    assert repo.get_setting("todelete") is None


def test_delete_setting_noop_for_missing_key(repo):
    """Deleting a nonexistent key should not raise."""
    repo.delete_setting("does_not_exist")  # should not raise


# ------------------------------------------------------------------
# Model ID Validation
# ------------------------------------------------------------------


def test_validate_model_id_accepts_valid(repo):
    """Valid OpenRouter model IDs should pass validation."""
    valid_ids = [
        "deepseek/deepseek-v4-flash",
        "openai/gpt-4o",
        "eleven_v3",
        "eleven_turbo_v2",
        "anthropic/claude-3.5-sonnet",
        "model-123",
        "MODEL.X:Y_Z",
    ]
    for mid in valid_ids:
        assert WebTtsSettingsRepository.validate_model_id(mid) == mid.strip()


def test_validate_model_id_rejects_empty(repo):
    """Empty or whitespace-only model IDs should be rejected."""
    assert WebTtsSettingsRepository.validate_model_id("") is None
    assert WebTtsSettingsRepository.validate_model_id("   ") is None


def test_validate_model_id_rejects_too_long(repo):
    """Model IDs longer than 128 characters should be rejected."""
    long_id = "a" * 129
    assert WebTtsSettingsRepository.validate_model_id(long_id) is None


def test_validate_model_id_rejects_special_chars(repo):
    """Model IDs with disallowed characters should be rejected."""
    invalid = [
        "model id",  # space
        "model$id",  # dollar
        "model@id",  # at
        "model!id",  # exclamation
        "model\\id",  # backslash
    ]
    for mid in invalid:
        assert WebTtsSettingsRepository.validate_model_id(mid) is None


def test_validate_model_id_trims_whitespace(repo):
    """Validation should trim and accept the cleaned value."""
    result = WebTtsSettingsRepository.validate_model_id("  deepseek/deepseek-v4-flash  ")
    assert result == "deepseek/deepseek-v4-flash"


# ------------------------------------------------------------------
# Provider Name Validation
# ------------------------------------------------------------------


def test_validate_provider_accepts_valid(repo):
    """Valid provider names should pass validation."""
    valid = [
        "crucible",
        "deepinfra",
        "together",
        "openai",
        "google-gemini",
        "provider123",
        "Provider.Name:Version",
        "parasail/fp8",
        "provider/model",
    ]
    for p in valid:
        assert WebTtsSettingsRepository.validate_provider_name(p) == p.strip()


def test_validate_provider_rejects_empty(repo):
    """Empty or whitespace-only provider names should be rejected."""
    assert WebTtsSettingsRepository.validate_provider_name("") is None
    assert WebTtsSettingsRepository.validate_provider_name("   ") is None


def test_validate_provider_rejects_too_long(repo):
    """Provider names longer than 128 characters should be rejected."""
    long_p = "p" * 129
    assert WebTtsSettingsRepository.validate_provider_name(long_p) is None


def test_validate_provider_accepts_slash(repo):
    """Provider names with forward slashes (e.g. parasail/fp8) should be accepted."""
    assert WebTtsSettingsRepository.validate_provider_name("parasail/fp8") == "parasail/fp8"
    assert WebTtsSettingsRepository.validate_provider_name("provider/model") == "provider/model"


def test_validate_provider_rejects_special_chars(repo):
    """Provider names with disallowed characters should be rejected."""
    invalid = [
        "my provider",  # space
        "provider$",  # dollar
        "provider@name",  # at
        "provider!",  # exclamation
        "provider\\name",  # backslash
    ]
    for p in invalid:
        assert WebTtsSettingsRepository.validate_provider_name(p) is None


def test_validate_provider_trims_whitespace(repo):
    """Validation should trim and accept the cleaned value."""
    result = WebTtsSettingsRepository.validate_provider_name("  crucible  ")
    assert result == "crucible"
