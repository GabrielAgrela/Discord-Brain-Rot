"""
Tests for legacy Database action logging used by older runtime paths.
"""

from unittest.mock import MagicMock

from bot import database as database_module
from bot.database import Database


def _database_with_connection(db_connection):
    db = object.__new__(Database)
    db.conn = db_connection
    db.cursor = db_connection.cursor()
    db.db_path = ":memory:"
    return db


def test_database_insert_action_publishes_actions_changed(db_connection):
    """Database.insert_action publishes the live-web actions_changed event."""
    db = _database_with_connection(db_connection)
    original_publish = database_module._publish_soundboard_event
    mock_publish = MagicMock(return_value=True)
    database_module._publish_soundboard_event = mock_publish
    try:
        db.insert_action("sopustos#0", "join", 5988, guild_id=359077662742020107)
    finally:
        database_module._publish_soundboard_event = original_publish

    row = db_connection.execute(
        "SELECT username, action, target, guild_id FROM actions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["username"] == "sopustos"
    assert row["action"] == "join"
    assert row["target"] == "5988"
    assert row["guild_id"] == "359077662742020107"

    mock_publish.assert_called_once()
    args, _kwargs = mock_publish.call_args
    assert args[0] == ":memory:"
    assert args[1] == "actions_changed"
    assert args[2] == {
        "action": "join",
        "target": "5988",
        "guild_id": "359077662742020107",
    }


def test_database_insert_action_publish_failure_is_nonfatal(db_connection):
    """Database.insert_action keeps the action row when live-web publish fails."""
    db = _database_with_connection(db_connection)
    original_publish = database_module._publish_soundboard_event
    database_module._publish_soundboard_event = MagicMock(
        side_effect=RuntimeError("Honker unavailable")
    )
    try:
        db.insert_action("user", "leave", 123, guild_id=456)
    finally:
        database_module._publish_soundboard_event = original_publish

    row_count = db_connection.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
    assert row_count == 1
