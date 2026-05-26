"""
Tests for AppSettingsRepository — generic key-value app settings store.
"""

from __future__ import annotations

import pytest

from bot.repositories.app_settings import (
    AppSettingsRepository,
    APP_SETTINGS_TABLE,
)


@pytest.fixture
def repo(tmp_path):
    """Create a repository backed by a temp SQLite database."""
    db_path = tmp_path / "test.db"
    r = AppSettingsRepository(db_path=str(db_path), use_shared=False)
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
# Multi-get / bulk set
# ------------------------------------------------------------------


def test_get_settings_returns_all_keys(repo):
    """get_settings should return values for all requested keys."""
    repo.set_setting("alpha", "a")
    repo.set_setting("beta", "b")
    repo.set_setting("gamma", "c")
    values = repo.get_settings(["alpha", "beta", "gamma"])
    assert values == {"alpha": "a", "beta": "b", "gamma": "c"}


def test_get_settings_returns_none_for_missing(repo):
    """Missing keys should be None in the returned dict."""
    repo.set_setting("exists", "yep")
    values = repo.get_settings(["exists", "missing"])
    assert values == {"exists": "yep", "missing": None}


def test_get_settings_empty_list(repo):
    """Empty key list should return empty dict."""
    assert repo.get_settings([]) == {}


def test_set_settings_bulk(repo):
    """set_settings should upsert multiple keys."""
    repo.set_settings({"k1": "v1", "k2": "v2"}, updated_by="bulk")
    assert repo.get_setting("k1") == "v1"
    assert repo.get_setting("k2") == "v2"


def test_set_settings_overwrites(repo):
    """set_settings should overwrite existing keys."""
    repo.set_setting("k1", "old")
    repo.set_settings({"k1": "new"})
    assert repo.get_setting("k1") == "new"


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------


def test_setting_with_empty_value(repo):
    """Empty string values should be storable."""
    repo.set_setting("empty", "")
    assert repo.get_setting("empty") == ""


def test_setting_with_none_value_roundtrip(repo):
    """"None" string should be stored as-is (not confused with missing)."""
    repo.set_setting("none_str", "None")
    assert repo.get_setting("none_str") == "None"
