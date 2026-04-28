import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest

from bot.models.web import DiscordWebUser
from bot.services.web_playback import (
    WebPlaybackService,
    get_web_control_state,
    process_playback_queue_request,
    queue_control_request,
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


def test_web_playback_service_resolves_sound_id_via_repository(tmp_path):
    sound_repository = Mock()
    sound_repository.get_by_id.return_value = SimpleNamespace(filename="alpha.mp3")

    service = WebPlaybackService(
        sound_repository=sound_repository,
        db_path=str(tmp_path / "web.db"),
        env={"DEFAULT_GUILD_ID": "359077662742020107"},
    )

    sound_filename = service.resolve_sound_filename({"sound_id": 7})

    assert sound_filename == "alpha.mp3"
    sound_repository.get_by_id.assert_called_once_with(7)


def test_web_playback_service_queues_authenticated_user_request(tmp_path):
    db_path = tmp_path / "web.db"
    _create_web_tables(db_path)

    service = WebPlaybackService(
        sound_repository=Mock(),
        db_path=str(db_path),
        env={"DEFAULT_GUILD_ID": "359077662742020107"},
    )

    row_id = service.queue_request(
        {"sound_filename": "test.mp3"},
        DiscordWebUser(
            id="123",
            username="discord-user",
            global_name="Discord User",
            avatar="",
        ),
    )

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT guild_id, sound_filename, request_username, request_user_id FROM playback_queue WHERE id = ?",
            (row_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row == (359077662742020107, "test.mp3", "Discord User", "123")


def test_web_playback_service_queues_similar_play_action(tmp_path):
    db_path = tmp_path / "web.db"
    _create_web_tables(db_path)

    service = WebPlaybackService(
        sound_repository=Mock(),
        db_path=str(db_path),
        env={"DEFAULT_GUILD_ID": "359077662742020107"},
    )

    row_id = service.queue_request(
        {"sound_filename": "test.mp3", "play_action": "play_similar_sound"},
        DiscordWebUser(
            id="123",
            username="discord-user",
            global_name="Discord User",
            avatar="",
        ),
    )

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT request_type, play_action FROM playback_queue WHERE id = ?",
            (row_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row == ("play_sound", "play_similar_sound")


def test_queue_control_request_adds_control_columns_and_queues_action(tmp_path):
    db_path = tmp_path / "web.db"
    _create_web_tables(db_path)

    row_id = queue_control_request(
        control_action="slap",
        requested_guild_id="359077662742020107",
        db_path=str(db_path),
        request_username="Discord User",
        request_user_id="123",
        env={},
    )

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT
                guild_id,
                sound_filename,
                request_username,
                request_user_id,
                request_type,
                control_action
            FROM playback_queue
            WHERE id = ?
            """,
            (row_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row == (
        359077662742020107,
        "__web_control__",
        "Discord User",
        "123",
        "slap",
        "slap",
    )


def test_queue_control_request_queues_tts_message_payload(tmp_path):
    db_path = tmp_path / "web.db"
    _create_web_tables(db_path)

    row_id = queue_control_request(
        control_action="tts",
        control_payload={"message": "hello from web", "profile": "pt"},
        requested_guild_id="359077662742020107",
        db_path=str(db_path),
        request_username="Discord User",
        request_user_id="123",
        env={},
    )

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT sound_filename, request_type, control_action
            FROM playback_queue
            WHERE id = ?
            """,
            (row_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row == ('{"message":"hello from web","profile":"pt"}', "tts", "tts")


def test_queue_control_request_rejects_empty_tts_message(tmp_path):
    db_path = tmp_path / "web.db"
    _create_web_tables(db_path)

    with pytest.raises(ValueError, match="Missing TTS message"):
        queue_control_request(
            control_action="tts",
            control_payload=" ",
            requested_guild_id="359077662742020107",
            db_path=str(db_path),
            request_username="Discord User",
            request_user_id="123",
            env={},
        )


def test_queue_control_request_rejects_unknown_action(tmp_path):
    db_path = tmp_path / "web.db"
    _create_web_tables(db_path)

    with pytest.raises(ValueError, match="Invalid web control action"):
        queue_control_request(
            control_action="restart_server",
            requested_guild_id="359077662742020107",
            db_path=str(db_path),
            request_username="Discord User",
            request_user_id="123",
            env={},
        )


def test_get_web_control_state_reports_active_mute_from_latest_action(tmp_path):
    db_path = tmp_path / "web.db"
    _create_web_tables(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO guild_settings (guild_id) VALUES (?)",
            ("359077662742020107",),
        )
        conn.execute(
            "INSERT INTO actions (username, action, target, timestamp, guild_id) VALUES (?, ?, ?, ?, ?)",
            (
                "Discord User",
                "mute_30_minutes",
                "",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "359077662742020107",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    state = get_web_control_state(
        requested_guild_id=None,
        db_path=str(db_path),
        env={},
    )

    assert state["mute"]["is_muted"] is True
    assert 0 < state["mute"]["remaining_seconds"] <= 1800


def test_get_web_control_state_reports_unmuted_after_unmute_action(tmp_path):
    db_path = tmp_path / "web.db"
    _create_web_tables(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO guild_settings (guild_id) VALUES (?)",
            ("359077662742020107",),
        )
        conn.executemany(
            "INSERT INTO actions (username, action, target, timestamp, guild_id) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    "Discord User",
                    "mute_30_minutes",
                    "",
                    (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"),
                    "359077662742020107",
                ),
                (
                    "Discord User",
                    "unmute",
                    "",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "359077662742020107",
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    state = get_web_control_state(
        requested_guild_id=None,
        db_path=str(db_path),
        env={},
    )

    assert state["mute"]["is_muted"] is False
    assert state["mute"]["remaining_seconds"] == 0


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

    sound_file = tmp_path / "test.mp3"
    sound_file.write_bytes(b"fake mp3 data")

    result = await process_playback_queue_request(
        (1, 42, "test.mp3", "Discord User", "123"),
        bot=SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == 42 else None),
        behavior=behavior,
        db=FakeDatabase(conn),
        sound_folder=tmp_path,
        action_logger_factory=lambda: action_logger,
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
    assert conn.execute(
        "SELECT played_at FROM playback_queue WHERE id = 1"
    ).fetchone()[0] is not None


@pytest.mark.asyncio
async def test_process_playback_queue_request_logs_similar_play_action(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE playback_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            sound_filename TEXT NOT NULL,
            request_username TEXT,
            request_user_id TEXT,
            play_action TEXT,
            requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            played_at DATETIME
        )
        """
    )
    conn.execute(
        "INSERT INTO playback_queue (id, guild_id, sound_filename, request_username, request_user_id, play_action) VALUES (?, ?, ?, ?, ?, ?)",
        (1, 42, "similar.mp3", "Discord User", "123", "play_similar_sound"),
    )
    conn.commit()

    class FakeDatabase:
        def __init__(self, connection):
            self.conn = connection
            self.cursor = connection.cursor()

        def get_sound(self, sound_filename, guild_id=None):
            return (321, sound_filename, sound_filename)

    guild = SimpleNamespace(id=42)
    channel = object()
    behavior = SimpleNamespace(
        get_largest_voice_channel=Mock(return_value=channel),
        play_audio=AsyncMock(),
    )
    action_logger = Mock()
    sound_file = tmp_path / "similar.mp3"
    sound_file.write_bytes(b"fake mp3 data")

    result = await process_playback_queue_request(
        (1, 42, "similar.mp3", "Discord User", "123", "play_sound", None, "play_similar_sound"),
        bot=SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == 42 else None),
        behavior=behavior,
        db=FakeDatabase(conn),
        sound_folder=tmp_path,
        action_logger_factory=lambda: action_logger,
        logger=lambda _: None,
    )

    assert result is True
    action_logger.insert.assert_called_once_with(
        "Discord User",
        "play_similar_sound",
        321,
        guild_id=42,
    )


@pytest.mark.asyncio
async def test_process_playback_queue_request_falls_back_to_original_filename(tmp_path):
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
        (1, 42, "renamed.mp3", "Discord User", "123"),
    )
    conn.commit()

    class FakeDatabase:
        def __init__(self, connection):
            self.conn = connection
            self.cursor = connection.cursor()

        def get_sound(self, sound_filename, guild_id=None):
            return (777, "original.mp3", sound_filename)

    guild = SimpleNamespace(id=42)
    channel = object()
    behavior = SimpleNamespace(
        get_largest_voice_channel=Mock(return_value=channel),
        play_audio=AsyncMock(),
    )
    action_logger = Mock()

    original_file = tmp_path / "original.mp3"
    original_file.write_bytes(b"fake mp3 data")

    result = await process_playback_queue_request(
        (1, 42, "renamed.mp3", "Discord User", "123"),
        bot=SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == 42 else None),
        behavior=behavior,
        db=FakeDatabase(conn),
        sound_folder=tmp_path,
        action_logger_factory=lambda: action_logger,
        logger=lambda _: None,
    )

    assert result is True
    behavior.play_audio.assert_awaited_once_with(channel, "original.mp3", "Discord User")
    action_logger.insert.assert_called_once_with(
        "Discord User",
        "play_request",
        777,
        guild_id=42,
    )
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
        logger=lambda _: None,
    )

    assert result is False
    behavior.play_audio.assert_not_awaited()
    assert conn.execute(
        "SELECT played_at FROM playback_queue WHERE id = 1"
    ).fetchone()[0] is not None


@pytest.mark.asyncio
async def test_process_playback_queue_request_executes_slap_control(tmp_path, monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE playback_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            sound_filename TEXT NOT NULL,
            request_username TEXT,
            request_user_id TEXT,
            request_type TEXT,
            control_action TEXT,
            requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            played_at DATETIME
        )
        """
    )
    conn.execute(
        """
        INSERT INTO playback_queue (
            id,
            guild_id,
            sound_filename,
            request_username,
            request_user_id,
            request_type,
            control_action
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (1, 42, "__web_control__", "Discord User", "123", "slap", "slap"),
    )
    conn.commit()

    class FakeDatabase:
        def __init__(self, connection):
            self.conn = connection
            self.cursor = connection.cursor()

        def get_sounds(self, slap=None, num_sounds=25, guild_id=None):
            return [(456, "slap-original.mp3", "slap.mp3")]

    guild = SimpleNamespace(id=42)
    channel = object()
    audio_service = SimpleNamespace(
        get_user_voice_channel=Mock(return_value=None),
        get_largest_voice_channel=Mock(return_value=channel),
        play_slap=AsyncMock(),
    )
    behavior = SimpleNamespace(_audio_service=audio_service)
    action_logger = Mock()
    monkeypatch.setattr("bot.services.web_playback.random.choice", lambda items: items[0])

    result = await process_playback_queue_request(
        (1, 42, "__web_control__", "Discord User", "123", "slap", "slap"),
        bot=SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == 42 else None),
        behavior=behavior,
        db=FakeDatabase(conn),
        sound_folder=tmp_path,
        action_logger_factory=lambda: action_logger,
        logger=lambda _: None,
    )

    assert result is True
    audio_service.play_slap.assert_awaited_once_with(channel, "slap.mp3", "Discord User")
    action_logger.insert.assert_called_once_with(
        "Discord User",
        "play_slap",
        456,
        guild_id=42,
    )
    assert conn.execute(
        "SELECT played_at FROM playback_queue WHERE id = 1"
    ).fetchone()[0] is not None


@pytest.mark.asyncio
async def test_process_playback_queue_request_executes_tts_control():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE playback_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            sound_filename TEXT NOT NULL,
            request_username TEXT,
            request_user_id TEXT,
            request_type TEXT,
            control_action TEXT,
            requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            played_at DATETIME
        )
        """
    )
    conn.execute(
        """
        INSERT INTO playback_queue (
            id,
            guild_id,
            sound_filename,
            request_username,
            request_user_id,
            request_type,
            control_action
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (1, 42, "hello from web", "Discord User", "123", "tts", "tts"),
    )
    conn.commit()

    class FakeDatabase:
        def __init__(self, connection):
            self.conn = connection
            self.cursor = connection.cursor()

    guild = SimpleNamespace(id=42)
    loading_message = object()
    bot_channel = SimpleNamespace(send=AsyncMock(return_value=loading_message))
    voice_transformation_service = SimpleNamespace(tts=AsyncMock(), tts_EL=AsyncMock())
    behavior = SimpleNamespace(
        _voice_transformation_service=voice_transformation_service,
        _message_service=SimpleNamespace(get_bot_channel=Mock(return_value=bot_channel)),
        _audio_service=SimpleNamespace(
            image_generator=SimpleNamespace(generate_loading_gif=Mock(return_value=b"gif"))
        ),
    )

    result = await process_playback_queue_request(
        (1, 42, "hello from web", "Discord User", "123", "tts", "tts"),
        bot=SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == 42 else None),
        behavior=behavior,
        db=FakeDatabase(conn),
        sound_folder=".",
        logger=lambda _: None,
    )

    assert result is True
    voice_transformation_service.tts.assert_awaited_once()
    user, speech, lang, region = voice_transformation_service.tts.await_args.args
    assert user.name == "Discord User"
    assert user.display_name == "Discord User"
    assert user.guild is guild
    assert speech == "hello from web"
    assert lang == "en"
    assert region == ""
    voice_transformation_service.tts_EL.assert_not_awaited()
    assert conn.execute(
        "SELECT played_at FROM playback_queue WHERE id = 1"
    ).fetchone()[0] is not None


@pytest.mark.asyncio
async def test_process_playback_queue_request_executes_tts_character_control():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE playback_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            sound_filename TEXT NOT NULL,
            request_username TEXT,
            request_user_id TEXT,
            request_type TEXT,
            control_action TEXT,
            requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            played_at DATETIME
        )
        """
    )
    conn.execute(
        """
        INSERT INTO playback_queue (
            id,
            guild_id,
            sound_filename,
            request_username,
            request_user_id,
            request_type,
            control_action
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            42,
            '{"message":"hello from web","profile":"ventura"}',
            "Discord User",
            "123",
            "tts",
            "tts",
        ),
    )
    conn.commit()

    class FakeDatabase:
        def __init__(self, connection):
            self.conn = connection
            self.cursor = connection.cursor()

    guild = SimpleNamespace(id=42)
    loading_message = object()
    bot_channel = SimpleNamespace(send=AsyncMock(return_value=loading_message))
    voice_transformation_service = SimpleNamespace(tts=AsyncMock(), tts_EL=AsyncMock())
    behavior = SimpleNamespace(
        _voice_transformation_service=voice_transformation_service,
        _message_service=SimpleNamespace(get_bot_channel=Mock(return_value=bot_channel)),
        _audio_service=SimpleNamespace(
            image_generator=SimpleNamespace(generate_loading_gif=Mock(return_value=b"gif"))
        ),
    )

    result = await process_playback_queue_request(
        (
            1,
            42,
            '{"message":"hello from web","profile":"ventura"}',
            "Discord User",
            "123",
            "tts",
            "tts",
        ),
        bot=SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == 42 else None),
        behavior=behavior,
        db=FakeDatabase(conn),
        sound_folder=".",
        logger=lambda _: None,
    )

    assert result is True
    voice_transformation_service.tts.assert_not_awaited()
    voice_transformation_service.tts_EL.assert_awaited_once()
    user, speech, voice = voice_transformation_service.tts_EL.await_args.args
    kwargs = voice_transformation_service.tts_EL.await_args.kwargs
    assert user.name == "Discord User"
    assert user.guild is guild
    assert speech == "hello from web"
    assert voice == "pt"
    assert kwargs["loading_message"] is loading_message
    assert kwargs["sts_thumbnail_url"]
    bot_channel.send.assert_awaited_once()
    assert conn.execute(
        "SELECT played_at FROM playback_queue WHERE id = 1"
    ).fetchone()[0] is not None


@pytest.mark.asyncio
async def test_process_playback_queue_request_executes_mute_control(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE playback_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            sound_filename TEXT NOT NULL,
            request_username TEXT,
            request_user_id TEXT,
            request_type TEXT,
            control_action TEXT,
            requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            played_at DATETIME
        )
        """
    )
    conn.execute(
        """
        INSERT INTO playback_queue (
            id,
            guild_id,
            sound_filename,
            request_username,
            request_user_id,
            request_type,
            control_action
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (1, 42, "__web_control__", "Discord User", "123", "mute_30_minutes", "mute_30_minutes"),
    )
    conn.commit()

    class FakeDatabase:
        def __init__(self, connection):
            self.conn = connection
            self.cursor = connection.cursor()

        def get_sounds(self, slap=None, num_sounds=25, guild_id=None):
            return [(456, "slap-original.mp3", "slap.mp3")]

    guild = SimpleNamespace(id=42)
    channel = object()
    audio_service = SimpleNamespace(
        get_user_voice_channel=Mock(return_value=channel),
        get_largest_voice_channel=Mock(),
        play_slap=AsyncMock(),
    )
    behavior = SimpleNamespace(_audio_service=audio_service, activate_mute=AsyncMock())
    action_logger = Mock()
    monkeypatch.setattr("bot.services.web_playback.random.choice", lambda items: items[0])

    result = await process_playback_queue_request(
        (
            1,
            42,
            "__web_control__",
            "Discord User",
            "123",
            "mute_30_minutes",
            "mute_30_minutes",
        ),
        bot=SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == 42 else None),
        behavior=behavior,
        db=FakeDatabase(conn),
        sound_folder=".",
        action_logger_factory=lambda: action_logger,
        logger=lambda _: None,
    )

    assert result is True
    audio_service.play_slap.assert_awaited_once_with(channel, "slap.mp3", "Discord User")
    behavior.activate_mute.assert_awaited_once_with(
        duration_seconds=1800,
        requested_by="Discord User",
    )
    action_logger.insert.assert_has_calls(
        [
            call("Discord User", "play_slap", 456, guild_id=42),
            call("Discord User", "mute_30_minutes", "", guild_id=42),
        ]
    )
    assert conn.execute(
        "SELECT played_at FROM playback_queue WHERE id = 1"
    ).fetchone()[0] is not None


@pytest.mark.asyncio
async def test_process_playback_queue_request_toggles_mute_on_when_unmuted(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE playback_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            sound_filename TEXT NOT NULL,
            request_username TEXT,
            request_user_id TEXT,
            request_type TEXT,
            control_action TEXT,
            requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            played_at DATETIME
        )
        """
    )
    conn.execute(
        "INSERT INTO playback_queue (id, guild_id, sound_filename, request_username, request_user_id, request_type, control_action) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, 42, "__web_control__", "Discord User", "123", "toggle_mute", "toggle_mute"),
    )
    conn.commit()

    class FakeDatabase:
        def __init__(self, connection):
            self.conn = connection
            self.cursor = connection.cursor()

        def get_sounds(self, slap=None, num_sounds=25, guild_id=None):
            return [(456, "slap-original.mp3", "slap.mp3")]

    guild = SimpleNamespace(id=42)
    channel = object()
    audio_service = SimpleNamespace(
        get_user_voice_channel=Mock(return_value=channel),
        get_largest_voice_channel=Mock(),
        play_slap=AsyncMock(),
    )
    behavior = SimpleNamespace(
        _audio_service=audio_service,
        get_mute_remaining=Mock(return_value=0),
        activate_mute=AsyncMock(),
        deactivate_mute=AsyncMock(),
    )
    action_logger = Mock()
    monkeypatch.setattr("bot.services.web_playback.random.choice", lambda items: items[0])

    result = await process_playback_queue_request(
        (1, 42, "__web_control__", "Discord User", "123", "toggle_mute", "toggle_mute"),
        bot=SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == 42 else None),
        behavior=behavior,
        db=FakeDatabase(conn),
        sound_folder=".",
        action_logger_factory=lambda: action_logger,
        logger=lambda _: None,
    )

    assert result is True
    audio_service.play_slap.assert_awaited_once_with(channel, "slap.mp3", "Discord User")
    behavior.activate_mute.assert_awaited_once_with(
        duration_seconds=1800,
        requested_by="Discord User",
    )
    behavior.deactivate_mute.assert_not_awaited()
    action_logger.insert.assert_has_calls(
        [
            call("Discord User", "play_slap", 456, guild_id=42),
            call("Discord User", "mute_30_minutes", "", guild_id=42),
        ]
    )


@pytest.mark.asyncio
async def test_process_playback_queue_request_toggles_mute_off_when_muted():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE playback_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            sound_filename TEXT NOT NULL,
            request_username TEXT,
            request_user_id TEXT,
            request_type TEXT,
            control_action TEXT,
            requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            played_at DATETIME
        )
        """
    )
    conn.execute(
        "INSERT INTO playback_queue (id, guild_id, sound_filename, request_username, request_user_id, request_type, control_action) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, 42, "__web_control__", "Discord User", "123", "toggle_mute", "toggle_mute"),
    )
    conn.commit()

    class FakeDatabase:
        def __init__(self, connection):
            self.conn = connection
            self.cursor = connection.cursor()

    guild = SimpleNamespace(id=42)
    behavior = SimpleNamespace(
        get_mute_remaining=Mock(return_value=120),
        activate_mute=AsyncMock(),
        deactivate_mute=AsyncMock(),
    )
    action_logger = Mock()

    result = await process_playback_queue_request(
        (1, 42, "__web_control__", "Discord User", "123", "toggle_mute", "toggle_mute"),
        bot=SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == 42 else None),
        behavior=behavior,
        db=FakeDatabase(conn),
        sound_folder=".",
        action_logger_factory=lambda: action_logger,
        logger=lambda _: None,
    )

    assert result is True
    behavior.deactivate_mute.assert_awaited_once_with(requested_by="Discord User")
    behavior.activate_mute.assert_not_awaited()
    action_logger.insert.assert_called_once_with(
        "Discord User",
        "unmute",
        "",
        guild_id=42,
    )
