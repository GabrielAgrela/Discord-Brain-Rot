import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bot.services.web_playback import (
    process_playback_queue_request,
    queue_playback_request,
)


def _create_web_tables(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE playback_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                sound_filename TEXT NOT NULL,
                requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                played_at DATETIME
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE guild_settings (
                guild_id TEXT PRIMARY KEY,
                bot_text_channel_id TEXT,
                default_voice_channel_id TEXT,
                autojoin_enabled INTEGER NOT NULL DEFAULT 0,
                periodic_enabled INTEGER NOT NULL DEFAULT 0,
                stt_enabled INTEGER NOT NULL DEFAULT 0,
                audio_policy TEXT NOT NULL DEFAULT 'low_latency',
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE sounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                originalfilename TEXT NOT NULL,
                Filename TEXT NOT NULL,
                guild_id TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT,
                timestamp TEXT,
                guild_id TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_queue_playback_request_infers_single_guild_from_saved_data(tmp_path):
    db_path = tmp_path / "web.db"
    _create_web_tables(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sounds (originalfilename, Filename, guild_id) VALUES (?, ?, ?)",
            ("test.mp3", "test.mp3", "359077662742020107"),
        )
        conn.commit()
    finally:
        conn.close()

    row_id = queue_playback_request(
        sound_filename="test.mp3",
        requested_guild_id=None,
        db_path=str(db_path),
        request_username="Discord User",
        request_user_id="123",
        env={},
    )

    conn = sqlite3.connect(db_path)
    try:
        guild_id, filename, request_username, request_user_id = conn.execute(
            "SELECT guild_id, sound_filename, request_username, request_user_id FROM playback_queue WHERE id = ?",
            (row_id,),
        ).fetchone()
    finally:
        conn.close()

    assert guild_id == 359077662742020107
    assert filename == "test.mp3"
    assert request_username == "Discord User"
    assert request_user_id == "123"


def test_queue_playback_request_rejects_ambiguous_guild_resolution(tmp_path):
    db_path = tmp_path / "web.db"
    _create_web_tables(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO guild_settings (guild_id) VALUES (?)",
            [("111",), ("222",)],
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="multiple guilds are configured"):
        queue_playback_request(
            sound_filename="test.mp3",
            requested_guild_id=None,
            db_path=str(db_path),
            request_username="Discord User",
            request_user_id="123",
            env={},
        )


def test_queue_playback_request_ignores_stale_queue_guilds_when_stable_data_exists(tmp_path):
    db_path = tmp_path / "web.db"
    _create_web_tables(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO guild_settings (guild_id) VALUES (?)",
            ("359077662742020107",),
        )
        conn.execute(
            "INSERT INTO playback_queue (guild_id, sound_filename) VALUES (?, ?)",
            (123456789012345678, "old.mp3"),
        )
        conn.commit()
    finally:
        conn.close()

    row_id = queue_playback_request(
        sound_filename="test.mp3",
        requested_guild_id=None,
        db_path=str(db_path),
        request_username="Discord User",
        request_user_id="123",
        env={},
    )

    conn = sqlite3.connect(db_path)
    try:
        guild_id = conn.execute(
            "SELECT guild_id FROM playback_queue WHERE id = ?",
            (row_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert guild_id == 359077662742020107


@pytest.mark.asyncio
async def test_process_playback_queue_request_marks_played_and_starts_audio(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE playback_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            sound_filename TEXT NOT NULL,
            request_username TEXT,
            request_user_id TEXT,
            requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            played_at DATETIME
        )
        """
    )
    conn.execute(
        "INSERT INTO playback_queue (id, guild_id, sound_filename, request_username, request_user_id) VALUES (?, ?, ?, ?, ?)",
        (1, 42, "test.mp3", "Discord User", "123"),
    )
    conn.commit()

    class FakeDatabase:
        def __init__(self, connection):
            self.conn = connection
            self.cursor = connection.cursor()

        def get_sound(self, sound_filename, guild_id=None):
            return (123, sound_filename, sound_filename)

    guild = SimpleNamespace(id=42)
    channel = object()
    behavior = SimpleNamespace(
        get_largest_voice_channel=Mock(return_value=channel),
        play_audio=AsyncMock(),
    )
    action_logger = Mock()
    sleep_fn = AsyncMock()

    sound_file = tmp_path / "test.mp3"
    sound_file.write_bytes(b"fake mp3 data")

    result = await process_playback_queue_request(
        (1, 42, "test.mp3", "Discord User", "123"),
        bot=SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == 42 else None),
        behavior=behavior,
        db=FakeDatabase(conn),
        sound_folder=tmp_path,
        action_logger_factory=lambda: action_logger,
        sleep_fn=sleep_fn,
        logger=lambda _: None,
    )

    assert result is True
    behavior.play_audio.assert_awaited_once_with(channel, "test.mp3", "Discord User")
    action_logger.insert.assert_called_once_with(
        "Discord User",
        "play_request",
        123,
        guild_id=42,
    )
    sleep_fn.assert_awaited_once_with(1)
    assert conn.execute(
        "SELECT played_at FROM playback_queue WHERE id = 1"
    ).fetchone()[0] is not None


@pytest.mark.asyncio
async def test_process_playback_queue_request_marks_played_when_sound_is_missing():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE playback_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            sound_filename TEXT NOT NULL,
            request_username TEXT,
            request_user_id TEXT,
            requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            played_at DATETIME
        )
        """
    )
    conn.execute(
        "INSERT INTO playback_queue (id, guild_id, sound_filename, request_username, request_user_id) VALUES (?, ?, ?, ?, ?)",
        (1, 42, "missing.mp3", "Discord User", "123"),
    )
    conn.commit()

    class FakeDatabase:
        def __init__(self, connection):
            self.conn = connection
            self.cursor = connection.cursor()

        def get_sound(self, sound_filename, guild_id=None):
            return None

    behavior = SimpleNamespace(
        get_largest_voice_channel=Mock(),
        play_audio=AsyncMock(),
    )

    result = await process_playback_queue_request(
        (1, 42, "missing.mp3", "Discord User", "123"),
        bot=SimpleNamespace(get_guild=lambda guild_id: SimpleNamespace(id=guild_id)),
        behavior=behavior,
        db=FakeDatabase(conn),
        sound_folder=".",
        action_logger_factory=None,
        sleep_fn=AsyncMock(),
        logger=lambda _: None,
    )

    assert result is False
    behavior.play_audio.assert_not_awaited()
    assert conn.execute(
        "SELECT played_at FROM playback_queue WHERE id = 1"
    ).fetchone()[0] is not None
