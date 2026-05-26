import os
import sqlite3
import io
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from web_page import app


def _wait_for_upload_job(client, job_id: str) -> dict:
    """Poll a queued upload job until it reaches a terminal state."""
    deadline = time.time() + 5
    payload = {}
    while time.time() < deadline:
        response = client.get(f"/api/upload_sound/{job_id}")
        assert response.status_code == 200
        payload = response.get_json()
        if payload.get("status") in {"approved", "error"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"Upload job did not finish: {payload}")


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
                guild_id TEXT,
                favorite INTEGER DEFAULT 0,
                blacklist INTEGER DEFAULT 0,
                slap INTEGER DEFAULT 0,
                is_elevenlabs INTEGER DEFAULT 0,
                timestamp TEXT
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
        cursor.execute(
            """
            CREATE TABLE sound_lists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                list_name TEXT NOT NULL,
                creator TEXT NOT NULL,
                guild_id TEXT,
                created_at TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE sound_list_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                list_id INTEGER NOT NULL,
                sound_filename TEXT NOT NULL,
                added_at TEXT,
                FOREIGN KEY (list_id) REFERENCES sound_lists(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE users (
                id TEXT NOT NULL,
                event TEXT NOT NULL,
                sound TEXT NOT NULL,
                guild_id TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE voice_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                join_time TEXT NOT NULL,
                leave_time TEXT,
                guild_id TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE web_bot_status (
                guild_id TEXT PRIMARY KEY,
                guild_name TEXT,
                voice_connected INTEGER NOT NULL DEFAULT 0,
                voice_channel_id TEXT,
                voice_channel_name TEXT,
                voice_member_count INTEGER NOT NULL DEFAULT 0,
                is_playing INTEGER NOT NULL DEFAULT 0,
                is_paused INTEGER NOT NULL DEFAULT 0,
                current_sound TEXT,
                current_requester TEXT,
                muted INTEGER NOT NULL DEFAULT 0,
                mute_remaining_seconds INTEGER NOT NULL DEFAULT 0,
                updated_at DATETIME NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE speech_training_clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL,
                display_name TEXT,
                folder_name TEXT NOT NULL,
                filename TEXT NOT NULL,
                relative_path TEXT NOT NULL UNIQUE,
                duration_seconds REAL NOT NULL,
                byte_size INTEGER NOT NULL DEFAULT 0,
                sample_rate INTEGER NOT NULL DEFAULT 48000,
                channels INTEGER NOT NULL DEFAULT 2,
                sample_width INTEGER NOT NULL DEFAULT 2,
                captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                label TEXT,
                transcript TEXT,
                notes TEXT,
                reviewed_by_user_id TEXT,
                reviewed_by_username TEXT,
                reviewed_at DATETIME
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _login_web_user(
    client,
    username: str = "trusted-user",
    global_name: str = "Trusted User",
    admin_guild_ids: list[str] | None = None,
) -> None:
    """Store a Discord user in the Flask test session."""
    with client.session_transaction() as flask_session:
        flask_session["discord_user"] = {
            "id": "123",
            "username": username,
            "global_name": global_name,
            "avatar": "",
            "admin_guild_ids": admin_guild_ids or [],
        }


@pytest.fixture
def web_client(tmp_path, monkeypatch):
    # Clear any residual response cache from previous tests to prevent
    # stale payloads from affecting this test.
    stale = app.extensions.get("web_response_cache")
    if stale is not None:
        stale.invalidate()

    db_path = tmp_path / "web.db"
    _create_web_tables(db_path)
    monkeypatch.delenv("DEFAULT_GUILD_ID", raising=False)

    original_db_path = app.config["DATABASE_PATH"]
    original_sounds_dir = app.config["SOUNDS_DIR"]
    original_debug = app.debug
    sounds_dir = tmp_path / "sounds"
    sounds_dir.mkdir()
    app.config.update(TESTING=True, DATABASE_PATH=str(db_path), SOUNDS_DIR=str(sounds_dir))
    app.debug = True  # auto_reload for Jinja test isolation

    try:
        with app.test_client() as client:
            yield client, db_path
    finally:
        app.config["DATABASE_PATH"] = original_db_path
        app.config["SOUNDS_DIR"] = original_sounds_dir
        app.debug = original_debug


def test_play_sound_endpoint_sends_request_with_inferred_single_guild(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO guild_settings (guild_id) VALUES (?)",
            ("359077662742020107",),
        )
        conn.commit()
    finally:
        conn.close()

    with client.session_transaction() as flask_session:
        flask_session["discord_user"] = {
            "id": "123",
            "username": "discord-user",
            "global_name": "Discord User",
            "avatar": "",
        }

    response = client.post("/api/play_sound", json={"sound_filename": "test.mp3"})

    assert response.status_code == 200
    assert response.get_json() == {"message": "Playback request sent"}

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT guild_id, sound_filename, request_username, request_user_id FROM playback_queue"
        ).fetchone()
    finally:
        conn.close()

    assert row == (359077662742020107, "test.mp3", "Discord User", "123")


def test_play_sound_endpoint_returns_400_for_ambiguous_guilds(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO actions (username, action, target, timestamp, guild_id) VALUES (?, ?, ?, ?, ?)",
            [
                ("one", "play_request", "1", "2026-04-01 12:00:00", "111"),
                ("two", "play_request", "2", "2026-04-01 12:01:00", "222"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    with client.session_transaction() as flask_session:
        flask_session["discord_user"] = {
            "id": "123",
            "username": "discord-user",
            "global_name": "Discord User",
            "avatar": "",
        }

    response = client.post("/api/play_sound", json={"sound_filename": "test.mp3"})

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "Missing guild_id and unable to infer one automatically because multiple guilds are configured"
    }


def test_play_sound_endpoint_accepts_sound_id_payload(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO guild_settings (guild_id) VALUES (?)",
            ("359077662742020107",),
        )
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "jews did 911.mp3", "jews did 911.mp3", 1, 0, 0, "2026-04-01 12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    with client.session_transaction() as flask_session:
        flask_session["discord_user"] = {
            "id": "123",
            "username": "discord-user",
            "global_name": "Discord User",
            "avatar": "",
        }

    response = client.post("/api/play_sound", json={"sound_id": 1})

    assert response.status_code == 200
    assert response.get_json() == {"message": "Playback request sent"}

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT guild_id, sound_filename, request_username, request_user_id FROM playback_queue"
        ).fetchone()
    finally:
        conn.close()

    assert row == (359077662742020107, "jews did 911.mp3", "Discord User", "123")


def test_play_sound_endpoint_rejects_blacklisted_sound_id(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO guild_settings (guild_id) VALUES (?)",
            ("359077662742020107",),
        )
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, blacklist, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "rejected.mp3", "rejected.mp3", 0, 1, 0, 0, "2026-04-01 12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    _login_web_user(client, username="discord-user", global_name="Discord User")

    response = client.post("/api/play_sound", json={"sound_id": 1})

    assert response.status_code == 400
    assert response.get_json() == {"error": "Sound is rejected"}

    conn = sqlite3.connect(db_path)
    try:
        queue_count = conn.execute("SELECT COUNT(*) FROM playback_queue").fetchone()[0]
    finally:
        conn.close()

    assert queue_count == 0


def test_play_sound_endpoint_accepts_similar_play_action(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO guild_settings (guild_id) VALUES (?)",
            ("359077662742020107",),
        )
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "alpha.mp3", "alpha.mp3", 0, 0, 0, "2026-04-01 12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    _login_web_user(client, username="discord-user", global_name="Discord User")

    response = client.post(
        "/api/play_sound",
        json={"sound_id": 1, "play_action": "play_similar_sound"},
    )

    assert response.status_code == 200

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT sound_filename, request_type, play_action FROM playback_queue"
        ).fetchone()
    finally:
        conn.close()

    assert row == ("alpha.mp3", "play_sound", "play_similar_sound")


def test_guild_selector_endpoint_returns_known_guilds(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO guild_settings (guild_id) VALUES (?)",
            [("111",), ("222",)],
        )
        conn.execute(
            """
            INSERT INTO web_bot_status (
                guild_id,
                guild_name,
                updated_at
            )
            VALUES (?, ?, ?)
            """,
            ("222", "Second Guild", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/api/guilds?guild_id=222")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["selected_guild_id"] == 222
    assert {"guild_id": 222, "name": "Second Guild", "is_default": True} in payload["guilds"]
    assert {"guild_id": 111, "name": "Guild 111", "is_default": False} in payload["guilds"]


def test_web_table_endpoints_scope_to_selected_guild(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            """
            INSERT INTO sounds (id, originalfilename, Filename, guild_id, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "alpha.mp3", "alpha.mp3", "111", 1, 0, 0, "2026-04-01 12:00:00"),
                (2, "beta.mp3", "beta.mp3", "222", 1, 0, 0, "2026-04-02 12:00:00"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO actions (username, action, target, timestamp, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("alice", "play_request", "1", "2026-04-03 12:00:00", "111"),
                ("bob", "play_request", "2", "2026-04-03 12:05:00", "222"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    actions_response = client.get("/api/actions?guild_id=222")
    all_sounds_response = client.get("/api/all_sounds?guild_id=222")

    assert actions_response.status_code == 200
    assert actions_response.get_json()["items"] == [
        {
            "display_filename": "beta.mp3",
            "display_username": "******",
            "action": "play_request",
            "timestamp": "2026-04-03 12:05:00",
            "sound_id": 2,
            "favorite": True,
            "slap": False,
        }
    ]
    assert all_sounds_response.status_code == 200
    assert all_sounds_response.get_json()["items"] == [
        {
            "sound_id": 2,
            "display_filename": "beta.mp3",
            "favorite": True,
            "slap": False,
            "timestamp": "2026-04-02 12:00:00",
        }
    ]


def test_web_sound_tables_hide_blacklisted_sounds(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            """
            INSERT INTO sounds (
                id, originalfilename, Filename, guild_id, favorite, blacklist,
                slap, is_elevenlabs, timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "visible.mp3", "visible.mp3", "111", 1, 0, 0, 0, "2026-04-01 12:00:00"),
                (2, "rejected.mp3", "rejected.mp3", "111", 1, 1, 0, 0, "2026-04-02 12:00:00"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    favorites_response = client.get("/api/favorites?guild_id=111")
    all_sounds_response = client.get("/api/all_sounds?guild_id=111")

    assert favorites_response.status_code == 200
    assert all_sounds_response.status_code == 200
    assert [item["display_filename"] for item in favorites_response.get_json()["items"]] == [
        "visible.mp3"
    ]
    assert [item["display_filename"] for item in all_sounds_response.get_json()["items"]] == [
        "visible.mp3"
    ]


def test_web_upload_approves_by_default_and_records_inbox(web_client, monkeypatch):
    client, db_path = web_client
    _login_web_user(client, username="discord-user", global_name="Discord User")
    monkeypatch.setattr("bot.services.web_upload.MP3", lambda path: object())

    response = client.post(
        "/api/upload_sound",
        data={
            "guild_id": "359077662742020107",
            "custom_name": "web drop",
            "sound_file": (io.BytesIO(b"fake mp3"), "source.mp3"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 202
    queued_payload = response.get_json()
    assert queued_payload["message"] == "Upload queued"
    payload = _wait_for_upload_job(client, queued_payload["job_id"])
    assert payload["filename"] == "web drop.mp3"
    assert payload["status"] == "approved"

    conn = sqlite3.connect(db_path)
    try:
        sound = conn.execute(
            "SELECT id, Filename, guild_id FROM sounds"
        ).fetchone()
        upload = conn.execute(
            """
            SELECT sound_id, filename, original_filename, uploaded_by_username, uploaded_by_user_id, status, guild_id
            FROM web_uploads
            """
        ).fetchone()
        action = conn.execute(
            "SELECT username, action, target, guild_id FROM actions"
        ).fetchone()
    finally:
        conn.close()

    assert sound[1:] == ("web drop.mp3", "359077662742020107")
    assert upload == (
        sound[0],
        "web drop.mp3",
        "source.mp3",
        "Discord User",
        "123",
        "approved",
        "359077662742020107",
    )
    assert action == ("Discord User", "upload_sound", "web drop.mp3", "359077662742020107")

    # A cross-process import notification should be queued for the bot to drain.
    conn = sqlite3.connect(db_path)
    try:
        notification = conn.execute(
            """
            SELECT filename, source, requester_username, accent_color, guild_id,
                   sent_at, attempts
            FROM sound_import_notifications
            """
        ).fetchone()
    finally:
        conn.close()
    assert notification is not None
    assert notification[0] == "web drop.mp3"
    assert notification[1] == "web_upload"
    assert notification[2] == "Discord User"
    assert notification[3] == "#5865F2"
    assert notification[4] == "359077662742020107"
    assert notification[5] is None  # sent_at must be null (pending)
    assert notification[6] == 0  # attempts


def test_web_upload_accepts_bot_modal_url_fields(web_client, monkeypatch):
    client, db_path = web_client
    _login_web_user(client, username="discord-user", global_name="Discord User")
    monkeypatch.setattr("bot.services.web_upload.MP3", lambda path: object())

    class FakeResponse:
        status_code = 200

        def iter_content(self, chunk_size):
            return iter([b"fake ", b"mp3"])

        def close(self):
            return None

    monkeypatch.setattr(
        "bot.services.web_upload.requests.get",
        lambda *args, **kwargs: FakeResponse(),
    )

    response = client.post(
        "/api/upload_sound",
        data={
            "guild_id": "359077662742020107",
            "source_url": "https://example.com/source.mp3",
            "custom_name": "url drop",
            "time_limit": "30",
        },
    )

    assert response.status_code == 202
    payload = _wait_for_upload_job(client, response.get_json()["job_id"])
    assert payload["filename"] == "url drop.mp3"
    assert payload["status"] == "approved"

    conn = sqlite3.connect(db_path)
    try:
        sound = conn.execute(
            "SELECT id, Filename, guild_id FROM sounds"
        ).fetchone()
        upload = conn.execute(
            "SELECT filename, original_filename, status, guild_id FROM web_uploads"
        ).fetchone()
        action = conn.execute(
            "SELECT username, action, target, guild_id FROM actions"
        ).fetchone()
    finally:
        conn.close()

    assert sound[1:] == ("url drop.mp3", "359077662742020107")
    assert upload == ("url drop.mp3", "source.mp3", "approved", "359077662742020107")
    assert action == ("Discord User", "upload_sound", "url drop.mp3", "359077662742020107")

    conn = sqlite3.connect(db_path)
    try:
        notification = conn.execute(
            """
            SELECT filename, source, requester_username, accent_color, guild_id
            FROM sound_import_notifications
            """
        ).fetchone()
    finally:
        conn.close()
    assert notification is not None
    assert notification[0] == "url drop.mp3"
    assert notification[1] == "web_upload"
    assert notification[2] == "Discord User"
    assert notification[3] == "#5865F2"
    assert notification[4] == "359077662742020107"


def test_web_upload_inbox_is_admin_only(web_client, monkeypatch):
    client, db_path = web_client
    _login_web_user(client, username="discord-user", global_name="Discord User")

    response = client.get("/api/uploads?guild_id=359077662742020107")
    assert response.status_code == 403

    _login_web_user(
        client,
        username="discord-user",
        global_name="Discord User",
        admin_guild_ids=["359077662742020107"],
    )
    response = client.get("/api/uploads?guild_id=359077662742020107")

    assert response.status_code == 200
    assert response.get_json() == {
        "uploads": [],
        "page": 1,
        "per_page": 50,
        "total": 0,
        "total_pages": 1,
        "unreviewed_count": 0,
    }


def test_web_upload_inbox_supports_pagination(web_client):
    client, db_path = web_client
    _login_web_user(
        client,
        username="discord-user",
        global_name="Discord User",
        admin_guild_ids=["111"],
    )

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT,
                sound_id INTEGER,
                filename TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                uploaded_by_username TEXT NOT NULL,
                uploaded_by_user_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'approved',
                moderator_username TEXT,
                moderated_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO web_uploads (
                guild_id, sound_id, filename, original_filename,
                uploaded_by_username, uploaded_by_user_id, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("111", 1, "first.mp3", "first.mp3", "User", "1", "approved", "2026-04-01 10:00:00"),
                ("111", 2, "second.mp3", "second.mp3", "User", "1", "approved", "2026-04-01 11:00:00"),
                ("111", 3, "third.mp3", "third.mp3", "User", "1", "approved", "2026-04-01 12:00:00"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/api/uploads?guild_id=111&limit=2&page=2")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["page"] == 2
    assert payload["per_page"] == 2
    assert payload["total"] == 3
    assert payload["total_pages"] == 2
    assert payload["unreviewed_count"] == 3
    assert [upload["filename"] for upload in payload["uploads"]] == ["first.mp3"]


def test_web_upload_inbox_counts_only_unreviewed_uploads(web_client):
    client, db_path = web_client
    _login_web_user(
        client,
        username="discord-user",
        global_name="Discord User",
        admin_guild_ids=["111"],
    )

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT,
                sound_id INTEGER,
                filename TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                uploaded_by_username TEXT NOT NULL,
                uploaded_by_user_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'approved',
                moderator_username TEXT,
                moderated_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO web_uploads (
                guild_id, sound_id, filename, original_filename,
                uploaded_by_username, uploaded_by_user_id, status,
                moderator_username, moderated_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("111", 1, "needs-review.mp3", "needs-review.mp3", "User", "1", "approved", None, None, "2026-04-01 10:00:00"),
                ("111", 2, "approved.mp3", "approved.mp3", "User", "1", "approved", "Mod", "2026-04-01 11:00:00", "2026-04-01 11:00:00"),
                ("111", 3, "rejected.mp3", "rejected.mp3", "User", "1", "rejected", "Mod", "2026-04-01 12:00:00", "2026-04-01 12:00:00"),
                ("222", 4, "other-guild.mp3", "other-guild.mp3", "User", "1", "approved", None, None, "2026-04-01 13:00:00"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/api/uploads?guild_id=111")

    assert response.status_code == 200
    assert response.get_json()["unreviewed_count"] == 1


def test_web_upload_moderation_rejects_and_blacklists_sound_for_admin(web_client, monkeypatch):
    client, db_path = web_client
    _login_web_user(
        client,
        username="discord-user",
        global_name="Discord User",
        admin_guild_ids=["111"],
    )

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, guild_id, favorite, blacklist, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (9, "bad.mp3", "bad.mp3", "111", 0, 0, 0, 0, "2026-04-01 12:00:00"),
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT,
                sound_id INTEGER,
                filename TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                uploaded_by_username TEXT NOT NULL,
                uploaded_by_user_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'approved',
                moderator_username TEXT,
                moderated_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO web_uploads (
                id, guild_id, sound_id, filename, original_filename,
                uploaded_by_username, uploaded_by_user_id, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (4, "111", 9, "bad.mp3", "bad.mp3", "Discord User", "123", "approved"),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.post("/api/uploads/4/moderation", json={"status": "rejected"})

    assert response.status_code == 200
    assert response.get_json() == {"upload_id": 4, "status": "rejected"}

    conn = sqlite3.connect(db_path)
    try:
        upload_status, moderator = conn.execute(
            "SELECT status, moderator_username FROM web_uploads WHERE id = 4"
        ).fetchone()
        blacklist = conn.execute("SELECT blacklist FROM sounds WHERE id = 9").fetchone()[0]
    finally:
        conn.close()

    assert upload_status == "rejected"
    assert moderator == "Discord User"
    assert blacklist == 1


def test_play_sound_endpoint_requires_discord_login(web_client):
    client, _ = web_client

    response = client.post("/api/play_sound", json={"sound_filename": "test.mp3"})

    assert response.status_code == 401
    assert response.get_json() == {
        "error": "Discord login required",
        "login_url": "/login?next=/api/play_sound",
    }


def test_web_control_endpoint_sends_toggle_mute_request(web_client):
    client, db_path = web_client
    _login_web_user(client, username="discord-user", global_name="Discord User")

    response = client.post("/api/web_control", json={"action": "toggle_mute", "guild_id": "359077662742020107"})

    assert response.status_code == 200
    assert response.get_json() == {"message": "Control request sent"}

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT guild_id, sound_filename, request_username, request_user_id, request_type, control_action
            FROM playback_queue
            """
        ).fetchone()
    finally:
        conn.close()

    assert row == (
        359077662742020107,
        "__web_control__",
        "Discord User",
        "123",
        "toggle_mute",
        "toggle_mute",
    )


def test_web_control_endpoint_sends_tts_request(web_client):
    client, db_path = web_client
    _login_web_user(client, username="discord-user", global_name="Discord User")

    response = client.post(
        "/api/web_control",
        json={
            "action": "tts",
            "message": "hello from the soundboard",
            "profile": "ventura",
            "guild_id": "359077662742020107",
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"message": "Control request sent"}

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT guild_id, sound_filename, request_username, request_user_id, request_type, control_action
            FROM playback_queue
            """
        ).fetchone()
    finally:
        conn.close()

    assert row == (
        359077662742020107,
        '{"message":"hello from the soundboard","profile":"ventura"}',
        "Discord User",
        "123",
        "tts",
        "tts",
    )


def test_tts_enhance_endpoint_returns_enhanced_message(web_client):
    client, _ = web_client
    _login_web_user(client, username="discord-user", global_name="Discord User")

    class FakeEnhancer:
        def enhance(self, message: str) -> str:
            assert message == "hello from the soundboard"
            return "[excited] hello from the soundboard"

    original_service = app.extensions.get("web_tts_enhancer_service")
    app.extensions["web_tts_enhancer_service"] = FakeEnhancer()
    try:
        response = client.post(
            "/api/tts/enhance",
            json={"message": "hello from the soundboard"},
        )
    finally:
        if original_service is None:
            app.extensions.pop("web_tts_enhancer_service", None)
        else:
            app.extensions["web_tts_enhancer_service"] = original_service

    assert response.status_code == 200
    assert response.get_json() == {"message": "[excited] hello from the soundboard"}


def test_tts_enhance_endpoint_uses_db_provider_override(web_client, monkeypatch):
    """Provider set through the admin settings API is used in the enhance payload."""
    from types import SimpleNamespace

    client, _ = web_client
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "default-model")
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _login_web_user(client, username="admin", admin_guild_ids=["111"])

    # 1. Set provider through admin settings
    resp = client.post(
        "/api/tts/enhancer-settings",
        json={"provider": "parasail/fp8"},
    )
    assert resp.status_code == 200

    # 2. Monkey-patch requests.post to capture the payload
    captured: dict = {}

    def fake_post(url, headers, json, timeout):
        captured["json"] = json
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "choices": [{"message": {"content": "[excited] hello there!"}}],
            },
        )

    monkeypatch.setattr("bot.services.web_tts_enhancer.requests.post", fake_post)

    # 3. Call the enhance endpoint
    response = client.post(
        "/api/tts/enhance",
        json={"message": "hello there!"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"message": "[excited] hello there!"}

    # 4. Verify the DB provider override is used and no sort is present
    provider = captured["json"].get("provider")
    assert provider == {"order": ["parasail/fp8"], "allow_fallbacks": False}
    assert "sort" not in provider


def test_tts_enhance_endpoint_requires_discord_login(web_client):
    client, _ = web_client

    response = client.post("/api/tts/enhance", json={"message": "hello"})

    assert response.status_code == 401


# ============================================================================
# TTS Enhancer LLM Settings admin API
# ============================================================================


def test_enhancer_settings_get_requires_discord_login(web_client):
    """Unauthenticated users should be rejected with 401."""
    client, _ = web_client
    response = client.get("/api/tts/enhancer-settings")
    assert response.status_code == 401


def test_enhancer_settings_get_requires_admin(web_client):
    """Authenticated non-admin users should be rejected with 403."""
    client, _ = web_client
    _login_web_user(client, username="regular-user", global_name="Regular User")
    response = client.get("/api/tts/enhancer-settings")
    assert response.status_code == 403


def test_enhancer_settings_get_returns_defaults(web_client, monkeypatch):
    """Admin user should get the current settings with default values."""
    client, _ = web_client
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "deepseek/deepseek-v4-flash")
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "crucible")
    _login_web_user(client, username="admin", admin_guild_ids=["111"])
    response = client.get("/api/tts/enhancer-settings")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["model"] == "deepseek/deepseek-v4-flash"
    assert payload["provider"] == "crucible"
    assert payload["stored_model"] is None
    assert payload["stored_provider"] is None
    assert payload["default_model"] == "deepseek/deepseek-v4-flash"
    assert payload["default_provider"] == "crucible"


def test_enhancer_settings_get_returns_stored_override(web_client, monkeypatch):
    """When an override is stored, GET should return it."""
    client, _ = web_client
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "default-model")
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _login_web_user(client, username="admin", admin_guild_ids=["111"])

    # Set overrides first
    client.post(
        "/api/tts/enhancer-settings",
        json={"model": "anthropic/claude-3.5-sonnet", "provider": "deepinfra"},
    )

    response = client.get("/api/tts/enhancer-settings")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["model"] == "anthropic/claude-3.5-sonnet"
    assert payload["stored_model"] == "anthropic/claude-3.5-sonnet"
    assert payload["provider"] == "deepinfra"
    assert payload["stored_provider"] == "deepinfra"


def test_enhancer_settings_post_requires_discord_login(web_client):
    """Unauthenticated POST should be rejected."""
    client, _ = web_client
    response = client.post(
        "/api/tts/enhancer-settings",
        json={"model": "openai/gpt-4o"},
    )
    assert response.status_code == 401


def test_enhancer_settings_post_requires_admin(web_client):
    """Non-admin POST should be rejected."""
    client, _ = web_client
    _login_web_user(client, username="regular-user")
    response = client.post(
        "/api/tts/enhancer-settings",
        json={"model": "openai/gpt-4o"},
    )
    assert response.status_code == 403


def test_enhancer_settings_post_sets_model(web_client, monkeypatch):
    """Admin POST with valid model should store the model override."""
    client, _ = web_client
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "default-model")
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _login_web_user(client, username="admin", admin_guild_ids=["111"])

    response = client.post(
        "/api/tts/enhancer-settings",
        json={"model": "anthropic/claude-3.5-sonnet"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["model"] == "anthropic/claude-3.5-sonnet"
    assert payload["stored_model"] == "anthropic/claude-3.5-sonnet"


def test_enhancer_settings_post_sets_provider(web_client, monkeypatch):
    """Admin POST with valid provider should store the provider override."""
    client, _ = web_client
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "default-model")
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _login_web_user(client, username="admin", admin_guild_ids=["111"])

    response = client.post(
        "/api/tts/enhancer-settings",
        json={"provider": "crucible"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["provider"] == "crucible"
    assert payload["stored_provider"] == "crucible"


def test_enhancer_settings_post_sets_both(web_client, monkeypatch):
    """Admin POST with both fields should store both overrides."""
    client, _ = web_client
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "default-model")
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _login_web_user(client, username="admin", admin_guild_ids=["111"])

    response = client.post(
        "/api/tts/enhancer-settings",
        json={"model": "o3-mini", "provider": "together"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["model"] == "o3-mini"
    assert payload["provider"] == "together"
    assert payload["stored_model"] == "o3-mini"
    assert payload["stored_provider"] == "together"


def test_enhancer_settings_post_empty_resets_both(web_client, monkeypatch):
    """Admin POST with both fields empty should clear both overrides."""
    client, _ = web_client
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "default-model")
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "default-provider")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _login_web_user(client, username="admin", admin_guild_ids=["111"])

    # Set overrides first
    client.post(
        "/api/tts/enhancer-settings",
        json={"model": "o3-mini", "provider": "together"},
    )
    # Reset both
    response = client.post(
        "/api/tts/enhancer-settings",
        json={"model": "", "provider": ""},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["model"] == "default-model"
    assert payload["stored_model"] is None
    assert payload["provider"] == "default-provider"
    assert payload["stored_provider"] is None


def test_enhancer_settings_post_empty_model_resets_model_only(web_client, monkeypatch):
    """Admin POST with empty model should clear only model override."""
    client, _ = web_client
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "default-model")
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "default-provider")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _login_web_user(client, username="admin", admin_guild_ids=["111"])

    client.post(
        "/api/tts/enhancer-settings",
        json={"model": "o3-mini", "provider": "together"},
    )
    response = client.post(
        "/api/tts/enhancer-settings",
        json={"model": ""},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["model"] == "default-model"
    assert payload["stored_model"] is None
    assert payload["provider"] == "together"
    assert payload["stored_provider"] == "together"


def test_enhancer_settings_post_rejects_invalid_model(web_client, monkeypatch):
    """Admin POST with invalid model should return 400."""
    client, _ = web_client
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "default-model")
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "")
    _login_web_user(client, username="admin", admin_guild_ids=["111"])

    response = client.post(
        "/api/tts/enhancer-settings",
        json={"model": "invalid model!"},
    )
    assert response.status_code == 400
    assert "Invalid model ID" in response.get_json()["error"]


def test_enhancer_settings_post_rejects_invalid_provider(web_client, monkeypatch):
    """Admin POST with invalid provider should return 400."""
    client, _ = web_client
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "default-model")
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "")
    _login_web_user(client, username="admin", admin_guild_ids=["111"])

    response = client.post(
        "/api/tts/enhancer-settings",
        json={"provider": "my provider"},
    )
    assert response.status_code == 400
    assert "Invalid provider name" in response.get_json()["error"]


def test_enhancer_settings_post_accepts_slash_in_provider(web_client, monkeypatch):
    """Admin POST with provider containing forward slash (e.g. parasail/fp8) should succeed."""
    client, _ = web_client
    monkeypatch.setenv("WEB_TTS_ENHANCER_MODEL", "default-model")
    monkeypatch.setenv("WEB_TTS_ENHANCER_PROVIDER", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _login_web_user(client, username="admin", admin_guild_ids=["111"])

    response = client.post(
        "/api/tts/enhancer-settings",
        json={"provider": "parasail/fp8"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["provider"] == "parasail/fp8"
    assert payload["stored_provider"] == "parasail/fp8"


def test_web_control_endpoint_requires_discord_login(web_client):
    client, _ = web_client

    response = client.post("/api/web_control", json={"action": "mute_30_minutes"})

    assert response.status_code == 401
    assert response.get_json() == {
        "error": "Discord login required",
        "login_url": "/login?next=/api/web_control",
    }


def test_web_control_state_endpoint_reports_current_mute_state(web_client):
    client, db_path = web_client
    _login_web_user(client, username="discord-user", global_name="Discord User")

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

    response = client.get("/api/web_control_state?guild_id=359077662742020107")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["guild_id"] == 359077662742020107
    assert payload["mute"]["is_muted"] is True
    assert 0 < payload["mute"]["remaining_seconds"] <= 1800
    assert payload["mute"]["toggle_action"] == "toggle_mute"


def test_control_room_status_endpoint_reports_runtime(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO guild_settings (guild_id) VALUES (?)",
            ("359077662742020107",),
        )
        conn.execute(
            """
            INSERT INTO web_bot_status (
                guild_id,
                guild_name,
                voice_connected,
                voice_channel_id,
                voice_channel_name,
                voice_member_count,
                is_playing,
                is_paused,
                current_sound,
                current_requester,
                muted,
                mute_remaining_seconds,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "359077662742020107",
                "Test Guild",
                1,
                "99",
                "General",
                3,
                1,
                0,
                "clip.mp3",
                "Trusted User",
                1,
                120,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/api/control_room/status")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["guild_id"] == 359077662742020107
    assert payload["status"]["online"] is True
    assert payload["status"]["voice_channel_name"] == "General"
    assert payload["status"]["current_sound"] == "clip.mp3"
    assert "queue" not in payload
    assert payload["mute"]["is_muted"] is True
    assert payload["mute"]["remaining_seconds"] == 120


def test_login_route_marks_session_permanent(web_client, monkeypatch):
    client, _ = web_client

    monkeypatch.setenv("DISCORD_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("DISCORD_OAUTH_CLIENT_SECRET", "client-secret")
    app.config["SERVER_NAME"] = "brainrot.example"

    response = client.get("/login?next=/analytics")

    assert response.status_code == 302
    with client.session_transaction() as flask_session:
        assert flask_session.permanent is True
        assert flask_session["oauth_next_path"] == "/analytics"
        assert flask_session["discord_oauth_state"]

    app.config["SERVER_NAME"] = None


def test_discord_callback_persists_user_in_permanent_session(web_client, monkeypatch):
    client, _ = web_client

    monkeypatch.setenv("DISCORD_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("DISCORD_OAUTH_CLIENT_SECRET", "client-secret")

    fake_user = {
        "id": "123",
        "username": "discord-user",
        "global_name": "Discord User",
        "avatar": "avatar-hash",
    }

    class _FakeResponse:
        def __init__(self, payload):
            self._payload = payload
            self.ok = True

        def json(self):
            return self._payload

    class _FakeRequestsSession:
        @staticmethod
        def post(*args, **kwargs):
            return _FakeResponse({"access_token": "token"})

        @staticmethod
        def get(url, *args, **kwargs):
            if url.endswith("/users/@me/guilds"):
                return _FakeResponse([{"id": "359077662742020107", "permissions": "8"}])
            return _FakeResponse(fake_user)

    original_auth_service = app.extensions["web_auth_service"]
    app.extensions["web_auth_service"] = original_auth_service.__class__(
        requests_session=_FakeRequestsSession()
    )
    try:
        with client.session_transaction() as flask_session:
            flask_session["discord_oauth_state"] = "expected-state"
            flask_session["oauth_next_path"] = "/analytics"

        response = client.get("/auth/discord/callback?state=expected-state&code=test-code")

        assert response.status_code == 302
        assert response.headers["Location"].endswith("/analytics")
        with client.session_transaction() as flask_session:
            assert flask_session.permanent is True
            assert flask_session["discord_user"] == {
                **fake_user,
                "admin_guild_ids": ["359077662742020107"],
            }
    finally:
        app.extensions["web_auth_service"] = original_auth_service


def test_web_app_configures_persistent_session_defaults():
    assert app.config["SESSION_PERMANENT"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(days=30)


def test_soundboard_admin_upload_inbox_uses_envelope_when_no_review_needed(web_client):
    client, _ = web_client
    _login_web_user(client, admin_guild_ids=["359077662742020107"])

    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="webUploadInboxOpenButton" class="auth-inbox-button"' in html
    assert 'aria-label="Open moderation inbox" title="Moderation inbox">&#9993;&#65038;</button>' in html
    script = client.get("/static/soundboard.js").get_data(as_text=True)
    assert "webUploadInboxOpenButton.textContent = hasUnreviewed ? '!' : '\\u2709\\uFE0E';" in script


def test_soundboard_page_renders_shared_redesign(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "alpha.mp3", "alpha.mp3", 1, 0, 0, "2026-04-01 12:00:00"),
                (2, "gamma.mp3", "gamma.mp3", 0, 0, 0, "2026-04-03 12:00:00"),
            ],
        )
        conn.execute(
            """
            INSERT INTO actions (username, action, target, timestamp, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("alice", "play_request", "1", "2026-04-04 12:00:00", "111"),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "/static/web.css" in html
    assert "Recent Actions" in html
    assert "Favorites" in html
    assert "All Sounds" in html
    assert 'class="placeholder-row"' not in html
    assert 'class="filter-group placeholder-filter"' not in html
    assert 'id="soundboard-config"' in html
    assert "/static/soundboard.js" in html
    assert "alpha" in html
    assert "gamma" in html
    assert "alice" in html
    assert "Played" in html
    assert 'id="pageInputActions"' in html
    assert 'id="pageInputFavorites"' in html
    assert 'id="pageInputAllSounds"' in html
    script = client.get("/static/soundboard.js").get_data(as_text=True)
    assert "setupPageInput" in script
    assert 'class="web-controls"' not in html
    assert 'id="controlRoomMuteButton"' in html
    assert 'id="controlRoomTtsButton"' in html
    assert 'id="controlRoomSlapButton"' in html
    assert 'id="webTtsDialog"' in html
    assert 'id="webTtsProfile"' in html
    assert 'id="webTtsMessage"' in html
    assert 'id="webTtsEnhanceButton"' in html
    assert "let ttsEnhancedMessageValue = ''" in script
    assert "This message has already been enhanced. Edit it to enhance again." in script
    assert "webTtsMessage.addEventListener('input'" in script
    assert 'id="soundRowContextMenu"' in html
    assert 'id="soundHoverCard"' in html
    assert 'title="gamma.mp3&#10;Added: Apr 03, 2026 by unknown"' in html
    assert 'id="soundRowRenameOption"' in html
    assert 'id="soundRowAddToListOption"' in html
    assert 'id="soundRowSimilarOption"' in html
    assert 'id="soundRowEventOption"' in html
    assert 'id="soundRowFavoriteOption"' in html
    assert 'id="soundRowSlapOption"' in html
    assert 'id="soundRenameDialog"' in html
    assert 'id="soundListDialog"' in html
    assert 'id="soundSimilarDialog"' in html
    assert 'id="soundEventDialog"' in html
    assert "play_similar_sound" in script
    assert 'id="soundEventTypeSelect"' in html
    assert 'id="soundEventUserInput"' in html
    assert "Add Event" in html
    assert "Remove Event" in script
    assert "Existing events:" in script
    assert 'class="favorite-button' not in html
    assert 'class="sound-options-row" data-sound-id="1" data-favorite="true" data-slap="false"' in html
    assert 'data-favorite="false"' in html
    assert '<th class="sound-options-column">More</th>' in html
    assert '<td class="sound-options-column">\n                                    <button type="button" class="sound-options-button"' in html
    assert '<td class="sound-options-column">\n                                    <button class="play-button' not in html
    assert "Unmake slap" in script
    assert "tablesGrid.addEventListener('contextmenu', openSoundRowContextMenu)" in script
    assert "showSoundHoverCard" in script
    assert "closeSoundHoverCard();" in script
    assert "openSoundRowContextMenuForRow(row, clientX, clientY, event)" in script
    assert "tablesGrid.addEventListener('touchstart', handleSoundOptionsPressStart" in script
    assert "/api/tts/enhance" in script
    assert "window.prompt" not in script
    assert 'class="control-room-equalizer"' in html
    assert 'id="controlRoomUpdated"' not in html
    assert '<span>Guild</span>' not in html
    assert 'id="controlRoomActionDock"' in html
    assert 'id="controlRoomActionsButton"' in html
    assert 'id="controlRoomActionMenu"' in html
    assert 'aria-haspopup="true"' in html
    assert 'id="webUploadOpenButton"' in html
    assert 'class="control-room-metric-button web-upload-control-button login-required"' in html
    assert '<option value="ventura" selected>' in html
    assert '<option value="en"' in html
    assert "Login with Discord to upload sounds" in html
    assert '<span class="nav-icon" aria-hidden="true">🎛️</span>' in html
    assert '<span class="nav-text">Soundboard</span>' in html
    assert '<span class="nav-icon" aria-hidden="true">📊</span>' in html
    assert '<span class="nav-text">Analytics</span>' in html
    assert 'class="web-upload-submit play-button' not in html
    assert 'class="web-upload-submit' in html
    assert 'class="web-upload-queue"' in html
    assert 'id="webUploadQueueList"' in html
    assert 'id="webUploadQueueCount"' in html
    assert "addUploadQueueItem" in script
    assert "renderUploadQueue" in script
    assert "webUploadForm.reset();" in script
    assert 'id="actions-action-filter"' in html
    assert 'aria-label="Filter recent actions by action"' in html
    assert 'aria-label="Filter recent actions by user"' in html
    assert 'id="favorites-user-filter"' in html
    assert 'id="all_sounds-list-filter"' in html
    assert 'class="library-controls"' in html
    assert 'class="select-shell"' in html
    assert 'aria-label="Search favorites"' in html
    assert 'aria-label="Filter favorites by user"' in html
    assert 'aria-label="Search all sounds"' in html
    assert 'aria-label="Filter all sounds by list"' in html
    assert 'class="soundboard-ambient"' in html
    assert 'for="actions-action-filter">Action</label>' not in html
    assert 'for="actions-user-filter">User</label>' not in html
    assert 'for="favorites-user-filter">User</label>' not in html
    assert 'for="searchAllSounds">Search</label>' not in html
    assert 'for="all_sounds-list-filter">List</label>' not in html
    assert "hideLabel: true" in script
    assert "allLabel: 'All Users'" in script
    assert "allLabel: 'All Lists'" in script
    assert 'class="theme-toggle"' in html
    assert "brainrot-theme" in html
    assert "applyThemePreference" in script
    assert "🌙" in html
    assert "☀️" in script
    assert "hasRenderableFilterPayload(endpoint, data.filters)" in script
    assert "setEndpointLoading" in script
    assert "aria-busy" in script
    assert "touchend" in script
    assert "handlePlayButtonActivation" in script
    assert "handleWebControlActivation" in script
    assert "requestInFlight" in script
    assert "isButtonCooldown" not in script
    assert "fetchFunction();" not in script
    assert "pendingInitialRenderEndpoints" in script
    assert "previousNowPlayingText" in script
    assert "status-flip" in script
    assert "row-reveal" in script
    assert "motion.init" in script
    assert "updatePointerPosition" in script
    assert "motion.burst" in script
    assert "prefers-reduced-motion" in script
    assert "🔒" in script
    assert "Login with Discord to use bot controls" in html
    assert "Play sound" in script
    assert "Queue sound" not in html
    assert "controlRoomQueue" not in html
    assert ">Queue<" not in html
    assert "Queued" not in html
    assert "Queue the right clip fast, without the generic dashboard look." not in html
    assert "What just happened, who triggered it, and how fresh it is." not in html
    assert "The shortlist for when you already know the bit you want." not in html
    assert "The full catalog, including older uploads and new arrivals." not in html


def test_favorite_watcher_import_uses_concise_badge_label(web_client):
    """favorite_watcher_import must render as 'Imported' badge, not the
    verbose fallback 'favorite watcher import' (the original bug)."""
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "tiktok_clip.mp3", "tiktok_clip.mp3", 0, 0, 0, "2026-05-01 12:00:00"),
        )
        conn.execute(
            """
            INSERT INTO actions (username, action, target, timestamp, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("alice", "favorite_watcher_import", "1", "2026-05-01 12:01:00", "111"),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # The badge's visible label must be "Imported" (not the fallback)
    assert ">Imported<" in html, "Expected 'Imported' as the badge visible text"

    # Filter dropdown option must also use the concise label
    assert (
        '<option value="favorite_watcher_import">Imported</option>' in html
    ), "Filter dropdown should use 'Imported' label"

    # The raw action value should still appear in the title attribute (preserved for detail)
    assert 'title="favorite_watcher_import"' in html, "Raw action value preserved in title"

    # Verify the JS formatAction map also includes the concise label
    script = client.get("/static/soundboard.js").get_data(as_text=True)
    assert "'favorite_watcher_import': 'Imported'" in script, "JS actionMap must include the concise label"


def test_analytics_page_renders_shared_redesign(web_client):
    client, _ = web_client

    response = client.get("/analytics")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "/static/web.css" in html
    assert "/static/analytics.js" in html
    assert 'class="theme-toggle"' in html
    assert "brainrot-theme" in html
    assert "🌙" in html
    script = client.get("/static/analytics.js").get_data(as_text=True)
    assert "☀️" in script
    assert '<span class="nav-icon" aria-hidden="true">🎛️</span>' in html
    assert '<span class="nav-text">Soundboard</span>' in html
    assert '<span class="nav-icon" aria-hidden="true">📊</span>' in html
    assert '<span class="nav-text">Analytics</span>' in html
    assert 'nav-upload-button' not in html
    assert '<span class="nav-text">Upload</span>' not in html
    assert 'class="time-selector"' in html
    assert "Activity Heatmap" in html
    assert "🔒" in script
    assert "Watch the server’s taste evolve in real time." not in html


def test_web_static_stylesheet_is_served(web_client):
    client, _ = web_client

    response = client.get("/static/web.css")

    assert response.status_code == 200
    stylesheet = response.get_data(as_text=True)
    assert ".page-title" in stylesheet
    assert "--accent:" in stylesheet
    assert "--soundboard-table-height" in stylesheet
    assert ".pagination-page-input" in stylesheet
    assert "body.page-soundboard .tables-grid > .card" in stylesheet
    assert "border: 1px solid var(--ink)" in stylesheet
    assert ".play-button.login-required" in stylesheet
    assert "tableLoadingWave" in stylesheet
    assert ".table-container.is-loading" in stylesheet
    assert ".theme-toggle" in stylesheet
    assert "html.theme-dark" in stylesheet
    assert 'border-radius: 999px' in stylesheet
    assert 'html.theme-dark .heatmap-cell[data-level="5"]' in stylesheet
    assert "html.theme-dark .play-button" in stylesheet
    assert "html.theme-dark .favorite-button" not in stylesheet
    assert ".sound-action-cell" not in stylesheet
    assert "#favoritesTable .sound-options-column,\n#allSoundsTable .sound-options-column {\n    display: none;" in stylesheet
    assert "#favoritesTable .sound-options-column,\n    #allSoundsTable .sound-options-column {\n        display: table-cell;" in stylesheet
    assert "html.theme-dark .nav-brand-mark" in stylesheet
    assert "html.theme-dark .auth-inbox-button" in stylesheet
    assert "background: var(--error)" in stylesheet
    assert "cardEntrance" in stylesheet
    assert "nowPlayingSpark" in stylesheet
    assert "rowReveal" in stylesheet
    assert "sentRing" in stylesheet
    assert "errorShake" in stylesheet
    assert "eqBar" in stylesheet
    assert "navGlint" in stylesheet
    assert "ambientScan" in stylesheet
    assert "dialogEnter" in stylesheet
    assert "buttonFlash" in stylesheet
    assert "queueEnter" in stylesheet
    assert "progressShimmer" in stylesheet
    assert "dotPulse" in stylesheet
    assert "backdropEnter" in stylesheet
    assert "body.page-soundboard .library-controls" in stylesheet
    assert "margin-bottom: 0.45rem" in stylesheet
    assert "min-height: 2.62rem" in stylesheet
    assert ".sound-options-button" in stylesheet
    assert ".result-meta" in stylesheet
    assert "top: calc(0.5rem + env(safe-area-inset-top, 0px))" in stylesheet
    assert ".control-room .card-kicker" in stylesheet
    assert ".play-button.sent" in stylesheet
    assert ".play-button.warn" in stylesheet
    assert ".play-button.queued" not in stylesheet


def test_web_content_endpoints_censor_hateful_strings(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "jews did 911.mp3", "jews did 911.mp3", 1, 0, 0, "2026-04-01 12:00:00"),
        )
        conn.execute(
            """
            INSERT INTO actions (username, action, target, timestamp, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("bob", "play_request", "1", "2026-04-01 12:01:00", "111"),
        )
        conn.commit()
    finally:
        conn.close()

    actions_response = client.get("/api/actions")
    favorites_response = client.get("/api/favorites")
    all_sounds_response = client.get("/api/all_sounds")

    assert actions_response.status_code == 200
    assert actions_response.get_json()["items"][0] == {
        "display_filename": "******",
        "display_username": "******",
        "action": "play_request",
        "timestamp": "2026-04-01 12:01:00",
        "sound_id": 1,
        "favorite": True,
        "slap": False,
    }

    assert favorites_response.status_code == 200
    assert favorites_response.get_json()["items"][0] == {
        "sound_id": 1,
        "display_filename": "******",
        "favorite": True,
        "slap": False,
        "timestamp": "2026-04-01 12:00:00",
    }

    assert all_sounds_response.status_code == 200
    assert all_sounds_response.get_json()["items"][0] == {
        "sound_id": 1,
        "display_filename": "******",
        "favorite": True,
        "slap": False,
        "timestamp": "2026-04-01 12:00:00",
    }


def test_web_content_endpoints_do_not_censor_logged_in_voice_user(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "jews did 911.mp3", "jews did 911.mp3", 1, 0, 0, "2026-04-01 12:00:00"),
        )
        conn.execute(
            """
            INSERT INTO actions (username, action, target, timestamp, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("niggas young fly on the tra", "play_request", "1", "2026-04-01 12:01:00", "111"),
        )
        conn.execute(
            """
            INSERT INTO voice_activity (username, channel_id, join_time, leave_time, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("trusted-user", "222", "2026-04-01 11:00:00", None, "111"),
        )
        conn.commit()
    finally:
        conn.close()

    _login_web_user(client, username="trusted-user", global_name="Trusted User")

    actions_response = client.get("/api/actions")
    favorites_response = client.get("/api/favorites")
    all_sounds_response = client.get("/api/all_sounds")

    assert actions_response.status_code == 200
    assert actions_response.get_json()["items"][0] == {
        "display_filename": "jews did 911.mp3",
        "display_username": "niggas young fly on the tra",
        "action": "play_request",
        "timestamp": "2026-04-01 12:01:00",
        "sound_id": 1,
        "favorite": True,
        "slap": False,
    }

    assert favorites_response.status_code == 200
    assert favorites_response.get_json()["items"][0] == {
        "sound_id": 1,
        "display_filename": "jews did 911.mp3",
        "favorite": True,
        "slap": False,
        "timestamp": "2026-04-01 12:00:00",
    }

    assert all_sounds_response.status_code == 200
    assert all_sounds_response.get_json()["items"][0] == {
        "sound_id": 1,
        "display_filename": "jews did 911.mp3",
        "favorite": True,
        "slap": False,
        "timestamp": "2026-04-01 12:00:00",
    }


def test_web_sound_tables_include_mp3_duration_when_file_exists(web_client, monkeypatch):
    client, db_path = web_client
    sounds_dir = Path(app.config["SOUNDS_DIR"])
    (sounds_dir / "alpha.mp3").write_bytes(b"fake mp3")

    class FakeAudioInfo:
        length = 72.2

    class FakeMp3:
        info = FakeAudioInfo()

        def __init__(self, path: str):
            assert path.endswith("alpha.mp3")

    monkeypatch.setattr("bot.services.web_content.MP3", FakeMp3)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "alpha.mp3", "alpha.mp3", 1, 0, 0, "2026-04-01 12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    favorites_response = client.get("/api/favorites")
    all_sounds_response = client.get("/api/all_sounds")

    assert favorites_response.status_code == 200
    assert favorites_response.get_json()["items"][0]["display_duration"] == "1:12"
    assert all_sounds_response.status_code == 200
    assert all_sounds_response.get_json()["items"][0]["display_duration"] == "1:12"


def test_web_sound_tables_use_original_file_duration_after_rename(web_client, monkeypatch):
    client, db_path = web_client
    sounds_dir = Path(app.config["SOUNDS_DIR"])
    (sounds_dir / "original.mp3").write_bytes(b"fake mp3")

    class FakeAudioInfo:
        length = 15.4

    class FakeMp3:
        info = FakeAudioInfo()

        def __init__(self, path: str):
            assert path.endswith("original.mp3")

    monkeypatch.setattr("bot.services.web_content.MP3", FakeMp3)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "original.mp3", "renamed.mp3", 1, 0, 0, "2026-04-01 12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    favorites_response = client.get("/api/favorites")
    all_sounds_response = client.get("/api/all_sounds")

    assert favorites_response.status_code == 200
    assert favorites_response.get_json()["items"][0]["display_filename"] == "renamed.mp3"
    assert favorites_response.get_json()["items"][0]["display_duration"] == "0:15"
    assert all_sounds_response.status_code == 200
    assert all_sounds_response.get_json()["items"][0]["display_filename"] == "renamed.mp3"
    assert all_sounds_response.get_json()["items"][0]["display_duration"] == "0:15"


def test_soundboard_index_does_not_read_mp3_durations(web_client, monkeypatch):
    client, db_path = web_client
    sounds_dir = Path(app.config["SOUNDS_DIR"])
    (sounds_dir / "alpha.mp3").write_bytes(b"fake mp3")

    def fail_if_mp3_is_read(path: str):
        raise AssertionError(f"Index route should not read MP3 metadata: {path}")

    monkeypatch.setattr("bot.services.web_content.MP3", fail_if_mp3_is_read)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "alpha.mp3", "alpha.mp3", 1, 0, 0, "2026-04-01 12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/")

    assert response.status_code == 200
    assert "alpha" in response.get_data(as_text=True)


def test_web_sound_rows_include_upload_hover_metadata(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "alpha.mp3", "alpha.mp3", 1, 0, 0, "2026-04-01 12:00:00"),
        )
        conn.execute(
            """
            INSERT INTO actions (username, action, target, timestamp, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("alice", "upload_sound", "alpha.mp3", "2026-04-01 12:00:00", "111"),
        )
        conn.execute(
            """
            INSERT INTO voice_activity (username, channel_id, join_time, leave_time, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("trusted-user", "222", "2026-04-01 11:00:00", None, "111"),
        )
        conn.commit()
    finally:
        conn.close()

    _login_web_user(client, username="trusted-user", global_name="Trusted User")

    favorites_response = client.get("/api/favorites")
    all_sounds_response = client.get("/api/all_sounds")
    html_response = client.get("/")

    assert favorites_response.status_code == 200
    assert favorites_response.get_json()["items"][0]["uploaded_by"] == "alice"
    assert favorites_response.get_json()["items"][0]["uploaded_at"] == "2026-04-01 12:00:00"
    assert all_sounds_response.status_code == 200
    assert all_sounds_response.get_json()["items"][0]["uploaded_by"] == "alice"
    assert html_response.status_code == 200
    assert 'title="alpha.mp3&#10;Added: Apr 01, 2026 by alice"' in html_response.get_data(as_text=True)


def test_web_sound_hover_uses_first_seen_date_when_upload_time_is_missing(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "legacy.mp3", "legacy.mp3", 1, 0, 0, None),
        )
        conn.execute(
            """
            INSERT INTO actions (username, action, target, timestamp, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("alice", "play_request", "1", "2026-03-01 08:00:00", "111"),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/")

    assert response.status_code == 200
    assert 'title="legacy.mp3&#10;Added: Mar 01, 2026 by unknown"' in response.get_data(as_text=True)


def test_web_sound_hover_uses_discord_legacy_before_date(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "legacy.mp3", "legacy.mp3", 1, 0, 0, "2023-10-30 11:04:46"),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/")

    assert response.status_code == 200
    assert 'title="legacy.mp3&#10;Added: Before Oct 30, 2023 by unknown"' in response.get_data(as_text=True)


def test_web_table_endpoints_return_filter_options_and_apply_column_filters(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "alpha.mp3", "alpha.mp3", 1, 0, 0, "2026-04-01 12:00:00"),
                (2, "beta.mp3", "beta.mp3", 1, 0, 0, "2026-04-02 12:00:00"),
                (3, "gamma.mp3", "gamma.mp3", 0, 0, 0, "2026-04-03 12:00:00"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO actions (username, action, target, timestamp, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("alice", "play_request", "1", "2026-04-04 12:00:00", "111"),
                ("bob", "favorite_sound", "2", "2026-04-04 12:05:00", "111"),
                ("alice", "play_from_list", "3", "2026-04-04 12:10:00", "111"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    actions_response = client.get(
        "/api/actions?action=play_request&user=alice&sound=alpha.mp3"
    )
    favorites_response = client.get("/api/favorites?sound=beta.mp3&user=bob")
    all_sounds_response = client.get("/api/all_sounds?sound=gamma.mp3&date=2026-04-03")

    assert actions_response.status_code == 200
    assert actions_response.get_json() == {
        "items": [
            {
                "display_filename": "alpha.mp3",
                "display_username": "******",
                "action": "play_request",
                "timestamp": "2026-04-04 12:00:00",
                "sound_id": 1,
                "favorite": True,
                "slap": False,
            }
        ],
        "total_count": 1,
        "total_pages": 1,
        "filters": {
            "action": ["favorite_sound", "play_from_list", "play_request"],
            "user": ["alice", "bob"],
            "sound": ["alpha.mp3", "beta.mp3", "gamma.mp3"],
        },
    }

    assert favorites_response.status_code == 200
    assert favorites_response.get_json() == {
        "items": [
            {
                "sound_id": 2,
                "display_filename": "beta.mp3",
                "favorite": True,
                "slap": False,
                "timestamp": "2026-04-02 12:00:00",
            }
        ],
        "total_count": 1,
        "total_pages": 1,
        "filters": {
            "sound": ["alpha.mp3", "beta.mp3"],
            "user": ["bob"],
        },
    }

    assert all_sounds_response.status_code == 200
    assert all_sounds_response.get_json() == {
        "items": [
            {
                "sound_id": 3,
                "display_filename": "gamma.mp3",
                "favorite": False,
                "slap": False,
                "timestamp": "2026-04-03 12:00:00",
            }
        ],
        "total_count": 1,
        "total_pages": 1,
        "filters": {
            "sound": ["alpha.mp3", "beta.mp3", "gamma.mp3"],
            "date": ["2026-04-03", "2026-04-02", "2026-04-01"],
            "list": [{"value": "__slap_sounds__", "label": "Slap Sounds"}],
        },
    }


def test_all_sounds_endpoint_returns_and_applies_sound_list_filter(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "alpha.mp3", "alpha.mp3", 0, 0, 0, "2026-04-01 12:00:00"),
                (2, "beta.mp3", "beta.mp3", 0, 0, 0, "2026-04-02 12:00:00"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO sound_lists (id, list_name, creator, guild_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (10, "Airhorns", "alice", "111", "2026-04-01 12:05:00"),
                (11, "Drops", "bob", "111", "2026-04-01 12:06:00"),
            ],
        )
        conn.execute(
            """
            INSERT INTO sound_list_items (list_id, sound_filename, added_at)
            VALUES (?, ?, ?)
            """,
            (10, "beta.mp3", "2026-04-01 12:10:00"),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/api/all_sounds?list=10")

    assert response.status_code == 200
    assert response.get_json() == {
        "items": [
            {
                "sound_id": 2,
                "display_filename": "beta.mp3",
                "favorite": False,
                "slap": False,
                "timestamp": "2026-04-02 12:00:00",
            }
        ],
        "total_count": 1,
        "total_pages": 1,
        "filters": {
            "sound": ["alpha.mp3", "beta.mp3"],
            "date": ["2026-04-02", "2026-04-01"],
            "list": [
                {"value": "__slap_sounds__", "label": "Slap Sounds"},
                {"value": "10", "label": "Airhorns (alice)"},
                {"value": "11", "label": "Drops (bob)"},
            ],
        },
    }


def test_all_sounds_endpoint_filters_by_slap_sounds(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "normal.mp3", "normal.mp3", 0, 0, 0, "2026-04-01 12:00:00"),
                (2, "slap1.mp3", "slap1.mp3", 0, 1, 0, "2026-04-02 12:00:00"),
                (3, "slap2.mp3", "slap2.mp3", 0, 1, 0, "2026-04-03 12:00:00"),
                (4, "elevenlabs_slap.mp3", "elevenlabs_slap.mp3", 0, 1, 1, "2026-04-04 12:00:00"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/api/all_sounds?list=__slap_sounds__")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total_count"] == 2
    assert payload["total_pages"] == 1
    filenames = {item["display_filename"] for item in payload["items"]}
    assert filenames == {"slap1.mp3", "slap2.mp3"}


def test_sound_options_endpoint_returns_lists_and_similar_sounds(web_client):
    client, db_path = web_client
    _login_web_user(client)
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO sounds (id, originalfilename, Filename, guild_id, favorite, slap, is_elevenlabs, timestamp) VALUES (?, ?, ?, ?, ?, 0, 0, ?)",
            [
                (1, "alpha meme.mp3", "alpha meme.mp3", "111", 0, "2026-04-04 12:00:00"),
                (2, "alpha remix.mp3", "alpha remix.mp3", "111", 0, "2026-04-04 12:01:00"),
                (3, "other.mp3", "other.mp3", "222", 0, "2026-04-04 12:02:00"),
            ],
        )
        conn.execute(
            "INSERT INTO sound_lists (id, list_name, creator, guild_id, created_at) VALUES (10, 'Bits', 'alice', '111', '2026-04-04 12:00:00')"
        )
        conn.execute(
            "INSERT INTO sound_list_items (list_id, sound_filename, added_at) VALUES (10, 'alpha meme.mp3', '2026-04-04 12:03:00')"
        )
        conn.execute(
            "INSERT INTO actions (username, action, target, timestamp, guild_id) VALUES ('bob', 'play_request', '1', '2026-04-04 12:00:00', '111')"
        )
        conn.execute(
            "INSERT INTO voice_activity (username, channel_id, join_time, leave_time, guild_id) VALUES ('carol', '5', '2026-04-04 12:00:00', '2026-04-04 12:05:00', '111')"
        )
        conn.execute(
            "INSERT INTO users (id, event, sound, guild_id) VALUES ('dave', 'join', 'alpha meme', '111')"
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/api/sounds/1/options?guild_id=111")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["sound"] == {
        "sound_id": 1,
        "display_filename": "alpha meme.mp3",
        "favorite": False,
        "slap": False,
    }
    assert payload["lists"] == [
        {
            "id": 10,
            "name": "Bits",
            "creator": "alice",
            "sound_count": 1,
            "label": "Bits (alice)",
            "contains_sound": True,
        }
    ]
    assert payload["events"] == [{"target_user": "dave", "event": "join"}]
    assert payload["users"] == [
        {"value": "trusted-user", "label": "trusted-user"},
        {"value": "bob", "label": "bob"},
        {"value": "carol", "label": "carol"},
        {"value": "dave", "label": "dave"},
    ]
    assert payload["similar_sounds"][0]["sound_id"] == 2
    assert all(item["sound_id"] != 3 for item in payload["similar_sounds"])


def test_sound_options_can_rename_and_toggle_favorite(web_client):
    client, db_path = web_client
    _login_web_user(client, username="web-user")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sounds (id, originalfilename, Filename, guild_id, favorite, slap, is_elevenlabs, timestamp) VALUES (1, 'old.mp3', 'old.mp3', '111', 0, 0, 0, '2026-04-04 12:00:00')"
        )
        conn.commit()
    finally:
        conn.close()

    rename_response = client.post(
        "/api/sounds/1/rename",
        json={"new_name": "new name", "guild_id": "111"},
    )
    favorite_response = client.post(
        "/api/sounds/1/favorite",
        json={"guild_id": "111"},
    )

    assert rename_response.status_code == 200
    assert rename_response.get_json()["sound"]["display_filename"] == "new name.mp3"
    assert favorite_response.status_code == 200
    assert favorite_response.get_json()["favorite"] is True
    conn = sqlite3.connect(db_path)
    try:
        sound_row = conn.execute(
            "SELECT Filename, favorite FROM sounds WHERE id = 1"
        ).fetchone()
        actions = conn.execute(
            "SELECT username, action, target, guild_id FROM actions ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert sound_row == ("new name.mp3", 1)
    assert actions == [
        ("web-user", "change_filename", "old.mp3 to new name.mp3", "111"),
        ("web-user", "favorite_sound", "1", "111"),
    ]


def test_sound_options_can_toggle_slap_for_admin(web_client):
    client, db_path = web_client
    _login_web_user(client, username="web-user", admin_guild_ids=["111"])
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sounds (id, originalfilename, Filename, guild_id, favorite, slap, is_elevenlabs, timestamp) VALUES (1, 'clip.mp3', 'clip.mp3', '111', 0, 0, 0, '2026-04-04 12:00:00')"
        )
        conn.commit()
    finally:
        conn.close()

    add_response = client.post("/api/sounds/1/slap", json={"guild_id": "111"})
    remove_response = client.post("/api/sounds/1/slap", json={"guild_id": "111"})

    assert add_response.status_code == 200
    assert add_response.get_json()["slap"] is True
    assert remove_response.status_code == 200
    assert remove_response.get_json()["slap"] is False
    conn = sqlite3.connect(db_path)
    try:
        sound_row = conn.execute("SELECT slap FROM sounds WHERE id = 1").fetchone()
        actions = conn.execute(
            "SELECT username, action, target, guild_id FROM actions ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert sound_row == (0,)
    assert actions == [
        ("web-user", "slap_sound", "1", "111"),
        ("web-user", "slap_sound", "1", "111"),
    ]


def test_sound_options_rejects_slap_toggle_for_non_admin(web_client):
    client, db_path = web_client
    _login_web_user(client, username="web-user")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sounds (id, originalfilename, Filename, guild_id, favorite, slap, is_elevenlabs, timestamp) VALUES (1, 'clip.mp3', 'clip.mp3', '111', 0, 0, 0, '2026-04-04 12:00:00')"
        )
        conn.commit()
    finally:
        conn.close()

    response = client.post("/api/sounds/1/slap", json={"guild_id": "111"})

    assert response.status_code == 403
    assert response.get_json()["error"] == "Only admins and moderators can manage slap sounds."


def test_sound_options_can_add_sound_to_list(web_client):
    client, db_path = web_client
    _login_web_user(client, username="web-user")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sounds (id, originalfilename, Filename, guild_id, favorite, slap, is_elevenlabs, timestamp) VALUES (1, 'clip.mp3', 'clip.mp3', '111', 0, 0, 0, '2026-04-04 12:00:00')"
        )
        conn.execute(
            "INSERT INTO sound_lists (id, list_name, creator, guild_id, created_at) VALUES (10, 'Bits', 'alice', '111', '2026-04-04 12:00:00')"
        )
        conn.commit()
    finally:
        conn.close()

    response = client.post(
        "/api/sounds/1/lists",
        json={"list_id": 10, "guild_id": "111"},
    )

    assert response.status_code == 200
    assert response.get_json()["added"] is True
    conn = sqlite3.connect(db_path)
    try:
        list_item = conn.execute(
            "SELECT list_id, sound_filename FROM sound_list_items"
        ).fetchone()
        action = conn.execute(
            "SELECT username, action, target, guild_id FROM actions"
        ).fetchone()
    finally:
        conn.close()
    assert list_item == (10, "clip.mp3")
    assert action == ("web-user", "add_sound_to_list", "Bits:clip.mp3", "111")


def test_sound_options_can_toggle_self_event_sound(web_client):
    client, db_path = web_client
    _login_web_user(client, username="web-user")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sounds (id, originalfilename, Filename, guild_id, favorite, slap, is_elevenlabs, timestamp) VALUES (1, 'clip.mp3', 'clip.mp3', '111', 0, 0, 0, '2026-04-04 12:00:00')"
        )
        conn.commit()
    finally:
        conn.close()

    add_response = client.post(
        "/api/sounds/1/events",
        json={"event": "join", "target_user": "web-user", "guild_id": "111"},
    )
    remove_response = client.post(
        "/api/sounds/1/events",
        json={"event": "join", "target_user": "web-user", "guild_id": "111"},
    )

    assert add_response.status_code == 200
    assert add_response.get_json()["added"] is True
    assert remove_response.status_code == 200
    assert remove_response.get_json()["added"] is False
    conn = sqlite3.connect(db_path)
    try:
        users = conn.execute(
            "SELECT id, event, sound, guild_id FROM users ORDER BY id"
        ).fetchall()
        actions = conn.execute(
            "SELECT username, action, target, guild_id FROM actions ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert users == []
    assert actions == [
        ("web-user", "add_join_sound", "web-user:clip", "111"),
        ("web-user", "delete_join_event", "web-user:clip", "111"),
    ]


def test_sound_options_rejects_event_for_other_user_without_admin(web_client):
    client, db_path = web_client
    _login_web_user(client, username="web-user")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sounds (id, originalfilename, Filename, guild_id, favorite, slap, is_elevenlabs, timestamp) VALUES (1, 'clip.mp3', 'clip.mp3', '111', 0, 0, 0, '2026-04-04 12:00:00')"
        )
        conn.commit()
    finally:
        conn.close()

    response = client.post(
        "/api/sounds/1/events",
        json={"event": "leave", "target_user": "other-user", "guild_id": "111"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "You can only assign events for yourself."


def test_favorites_endpoint_returns_and_applies_user_filter(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "alpha.mp3", "alpha.mp3", 1, 0, 0, "2026-04-01 12:00:00"),
                (2, "beta.mp3", "beta.mp3", 1, 0, 0, "2026-04-02 12:00:00"),
                (3, "gamma.mp3", "gamma.mp3", 1, 0, 0, "2026-04-03 12:00:00"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO actions (username, action, target, timestamp, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("alice", "favorite_sound", "1", "2026-04-04 12:00:00", "111"),
                ("alice", "favorite_sound", "2", "2026-04-04 12:05:00", "111"),
                ("alice", "unfavorite_sound", "2", "2026-04-04 12:10:00", "111"),
                ("bob", "favorite_sound", "3", "2026-04-04 12:15:00", "111"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/api/favorites?user=alice")

    assert response.status_code == 200
    assert response.get_json() == {
        "items": [
            {
                "sound_id": 1,
                "display_filename": "alpha.mp3",
                "favorite": True,
                "slap": False,
                "timestamp": "2026-04-01 12:00:00",
            }
        ],
        "total_count": 1,
        "total_pages": 1,
        "filters": {
            "sound": ["alpha.mp3", "beta.mp3", "gamma.mp3"],
            "user": ["alice", "bob"],
        },
    }


def test_actions_endpoint_can_skip_filter_metadata(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO actions (username, action, target, timestamp, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("alice", "play_request", "alpha.mp3", "2026-04-04 12:00:00", "111"),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/api/actions?include_filters=0")

    assert response.status_code == 200
    assert response.get_json() == {
        "items": [
            {
                "display_filename": "alpha.mp3",
                "display_username": "******",
                "action": "play_request",
                "timestamp": "2026-04-04 12:00:00",
            }
        ],
        "total_count": 1,
        "total_pages": 1,
        "filters": {},
    }


def test_favorites_endpoint_can_skip_filter_metadata(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "alpha.mp3", "alpha.mp3", 1, 0, 0, "2026-04-04 12:00:00"),
        )
        conn.execute(
            """
            INSERT INTO actions (username, action, target, timestamp, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("alice", "favorite_sound", "1", "2026-04-04 12:05:00", "111"),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/api/favorites?include_filters=0")

    assert response.status_code == 200
    assert response.get_json() == {
        "items": [
            {
                "sound_id": 1,
                "display_filename": "alpha.mp3",
                "favorite": True,
                "slap": False,
                "timestamp": "2026-04-04 12:00:00",
            }
        ],
        "total_count": 1,
        "total_pages": 1,
        "filters": {},
    }


def test_all_sounds_endpoint_can_skip_filter_metadata(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "alpha.mp3", "alpha.mp3", 0, 0, 0, "2026-04-04 12:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/api/all_sounds?include_filters=0")

    assert response.status_code == 200
    assert response.get_json() == {
        "items": [
            {
                "sound_id": 1,
                "display_filename": "alpha.mp3",
                "favorite": False,
                "slap": False,
                "timestamp": "2026-04-04 12:00:00",
            }
        ],
        "total_count": 1,
        "total_pages": 1,
        "filters": {},
    }


def test_soundboard_initial_render_skips_unused_filter_payloads(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "alpha.mp3", "alpha.mp3", 1, 0, 0, "2026-04-01 12:00:00"),
                (2, "beta.mp3", "beta.mp3", 0, 0, 0, "2026-04-02 12:00:00"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO actions (username, action, target, timestamp, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("alice", "play_request", "1", "2026-04-03 12:00:00", "111"),
                ("bob", "favorite_sound", "2", "2026-04-03 12:05:00", "111"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="soundboard-config"' in html
    assert 'id="favorites-user-filter"' in html
    assert '"sound":["alpha.mp3","beta.mp3"]' not in html
    assert '"date":' not in html


def test_analytics_endpoints_censor_hateful_strings(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "nig-ventura-27-07-2.mp3", "nig-ventura-27-07-2.mp3", 0, 0, 0, "2026-04-01 12:00:00"),
        )
        conn.execute(
            """
            INSERT INTO actions (username, action, target, timestamp, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("alice", "play_request", "1", "2026-04-01 12:01:00", "111"),
        )
        conn.commit()
    finally:
        conn.close()

    top_users_response = client.get("/api/analytics/top_users?days=0&limit=8")
    top_sounds_response = client.get("/api/analytics/top_sounds?days=0&limit=8")
    recent_activity_response = client.get("/api/analytics/recent_activity?limit=15")

    assert top_users_response.status_code == 200
    assert top_users_response.get_json()["users"][0] == {
        "display_username": "******",
        "count": 1,
    }

    assert top_sounds_response.status_code == 200
    assert top_sounds_response.get_json()["sounds"][0] == {
        "sound_id": 1,
        "display_filename": "******",
        "count": 1,
    }

    assert recent_activity_response.status_code == 200
    assert recent_activity_response.get_json()["activities"][0] == {
        "display_username": "******",
        "action": "play_request",
        "timestamp": "2026-04-01 12:01:00",
        "display_sound": "******",
    }


def test_analytics_endpoints_do_not_censor_logged_in_voice_user(web_client):
    client, db_path = web_client

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sounds (id, originalfilename, Filename, favorite, slap, is_elevenlabs, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "nig-ventura-27-07-2.mp3", "nig-ventura-27-07-2.mp3", 0, 0, 0, "2026-04-01 12:00:00"),
        )
        conn.execute(
            """
            INSERT INTO actions (username, action, target, timestamp, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("jews did 911", "play_request", "1", "2026-04-01 12:01:00", "111"),
        )
        conn.execute(
            """
            INSERT INTO voice_activity (username, channel_id, join_time, leave_time, guild_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Trusted User", "222", "2026-04-01 11:00:00", None, "111"),
        )
        conn.commit()
    finally:
        conn.close()

    _login_web_user(client, username="trusted-user", global_name="Trusted User")

    top_users_response = client.get("/api/analytics/top_users?days=0&limit=8")
    top_sounds_response = client.get("/api/analytics/top_sounds?days=0&limit=8")
    recent_activity_response = client.get("/api/analytics/recent_activity?limit=15")

    assert top_users_response.status_code == 200
    assert top_users_response.get_json()["users"][0] == {
        "display_username": "jews did 911",
        "count": 1,
    }

    assert top_sounds_response.status_code == 200
    assert top_sounds_response.get_json()["sounds"][0] == {
        "sound_id": 1,
        "display_filename": "nig-ventura-27-07-2.mp3",
        "count": 1,
    }

    assert recent_activity_response.status_code == 200
    assert recent_activity_response.get_json()["activities"][0] == {
        "display_username": "jews did 911",
        "action": "play_request",
        "timestamp": "2026-04-01 12:01:00",
        "display_sound": "nig-ventura-27-07-2.mp3",
    }


# ======================================================================
# System Monitor Endpoint
# ======================================================================


def test_system_monitor_endpoint_returns_json_safely(web_client):
    """The system monitor endpoint returns a valid JSON payload."""
    client, _ = web_client

    response = client.get("/api/system_monitor/status")
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict)
    # Must be JSON-serializable regardless of backend
    assert "available" in payload
    assert "total_cpu_percent" in payload
    assert "ram_total_bytes" in payload
    assert "top_processes" in payload


def test_system_monitor_endpoint_clamps_limit(web_client):
    """The limit query parameter is clamped to 1-8."""
    client, _ = web_client

    # limit=0 → clamped to 1
    response = client.get("/api/system_monitor/status?limit=0")
    assert response.status_code == 200

    # limit=999 → clamped to 8
    response = client.get("/api/system_monitor/status?limit=999")
    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload.get("top_processes", [])) <= 8

    # limit=abc → defaults to 4
    response = client.get("/api/system_monitor/status?limit=abc")
    assert response.status_code == 200


def test_system_monitor_endpoint_handles_exception(web_client, monkeypatch):
    """When the underlying service raises, the endpoint returns 500."""
    client, _ = web_client

    class BrokenService:
        def get_snapshot(self, top_limit=4):
            raise RuntimeError("boom")

    original = app.extensions.get("web_system_monitor_service")
    app.extensions["web_system_monitor_service"] = BrokenService()
    try:
        response = client.get("/api/system_monitor/status")
        assert response.status_code == 500
        payload = response.get_json()
        assert payload["available"] is False
        assert payload["error"] == "System monitor unavailable"
    finally:
        if original is None:
            app.extensions.pop("web_system_monitor_service", None)
        else:
            app.extensions["web_system_monitor_service"] = original


def test_system_monitor_fake_service_returns_expected_payload(web_client):
    """Replace the real service with a fake and verify the endpoint passes it through."""
    client, _ = web_client

    class FakeService:
        def get_snapshot(self, top_limit=4):
            return {
                "available": True,
                "total_cpu_percent": 23.5,
                "ram_total_bytes": 17179869184,
                "ram_available_bytes": 8589934592,
                "ram_used_bytes": 8589934592,
                "ram_percent": 50.0,
                "cpu_warming": False,
                "sample_interval_seconds": 1.0,
                "updated_at_unix": 1234567890.0,
                "top_processes": [
                    {
                        "pid": 101,
                        "name": "test-proc",
                        "cpu_percent": 10.5,
                        "memory_rss_bytes": 4194304,
                        "memory_percent": 0.02,
                    }
                ],
                "cpu_temperature_celsius": 42.0,
                "cpu_fan_rpm": 1800,
            }

    original = app.extensions.get("web_system_monitor_service")
    app.extensions["web_system_monitor_service"] = FakeService()
    try:
        response = client.get("/api/system_monitor/status?limit=3")
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["total_cpu_percent"] == 23.5
        assert payload["cpu_temperature_celsius"] == 42.0
        assert len(payload["top_processes"]) == 1
        assert payload["top_processes"][0]["name"] == "test-proc"
    finally:
        if original is None:
            app.extensions.pop("web_system_monitor_service", None)
        else:
            app.extensions["web_system_monitor_service"] = original


# ============================================================================
# Server-side response cache (multi-client route caching) tests
# ============================================================================


def _clear_response_cache():
    """Remove the per-process response cache so tests start fresh."""
    cached = app.extensions.pop("web_response_cache", None)
    if cached is not None:
        cached.invalidate()


def test_actions_cache_returns_same_payload_for_duplicate_request(web_client):
    """Two identical calls within TTL produce the same payload and hit the
    service only once."""
    client, _ = web_client
    _clear_response_cache()

    from bot.services.web_content import WebContentService

    call_count = [0]

    original = WebContentService.get_actions

    def counting_get_actions(self, *args, **kwargs):
        call_count[0] += 1
        return original(self, *args, **kwargs)

    WebContentService.get_actions = counting_get_actions
    try:
        resp1 = client.get("/api/actions")
        assert resp1.status_code == 200
        first_count = call_count[0]
        assert first_count > 0, "service should have been called once"

        resp2 = client.get("/api/actions")
        assert resp2.status_code == 200
        # Service should NOT have been called again (within TTL).
        assert call_count[0] == first_count, (
            f"expected {first_count} calls, got {call_count[0]}"
        )

        # Both responses should be identical.
        assert resp1.get_json() == resp2.get_json()
    finally:
        WebContentService.get_actions = original


def test_favorites_cache_returns_same_payload_for_duplicate_request(web_client):
    """Two identical calls within TTL hit favorites service only once."""
    client, _ = web_client
    _clear_response_cache()

    from bot.services.web_content import WebContentService

    call_count = [0]

    original = WebContentService.get_favorites

    def counting_get_favorites(self, *args, **kwargs):
        call_count[0] += 1
        return original(self, *args, **kwargs)

    WebContentService.get_favorites = counting_get_favorites
    try:
        resp1 = client.get("/api/favorites")
        assert resp1.status_code == 200
        first_count = call_count[0]
        assert first_count > 0

        resp2 = client.get("/api/favorites")
        assert resp2.status_code == 200
        assert call_count[0] == first_count
        assert resp1.get_json() == resp2.get_json()
    finally:
        WebContentService.get_favorites = original


def test_all_sounds_cache_returns_same_payload_for_duplicate_request(web_client):
    """Two identical calls within TTL hit all_sounds service only once."""
    client, _ = web_client
    _clear_response_cache()

    from bot.services.web_content import WebContentService

    call_count = [0]

    original = WebContentService.get_all_sounds

    def counting_get_all_sounds(self, *args, **kwargs):
        call_count[0] += 1
        return original(self, *args, **kwargs)

    WebContentService.get_all_sounds = counting_get_all_sounds
    try:
        resp1 = client.get("/api/all_sounds")
        assert resp1.status_code == 200
        first_count = call_count[0]
        assert first_count > 0

        resp2 = client.get("/api/all_sounds")
        assert resp2.status_code == 200
        assert call_count[0] == first_count
        assert resp1.get_json() == resp2.get_json()
    finally:
        WebContentService.get_all_sounds = original


def test_control_room_status_cache_returns_same_payload(web_client):
    """Two identical calls within TTL hit control-room service only once."""
    client, db_path = web_client
    _clear_response_cache()

    # Insert minimal guild data so the endpoint does not 400.
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT INTO guild_settings (guild_id) VALUES (?)", ("111",))
        conn.commit()
    finally:
        conn.close()

    from bot.services.web_control_room import WebControlRoomService

    call_count = [0]

    original = WebControlRoomService.get_status

    def counting_get_status(self, *args, **kwargs):
        call_count[0] += 1
        return original(self, *args, **kwargs)

    WebControlRoomService.get_status = counting_get_status
    try:
        resp1 = client.get("/api/control_room/status")
        assert resp1.status_code == 200
        first_count = call_count[0]
        assert first_count > 0

        resp2 = client.get("/api/control_room/status")
        assert resp2.status_code == 200
        assert call_count[0] == first_count
        assert resp1.get_json() == resp2.get_json()
    finally:
        WebControlRoomService.get_status = original


def test_web_control_state_cache_returns_same_payload(web_client):
    """Two identical calls within TTL hit control-state service only once."""
    client, db_path = web_client
    _clear_response_cache()

    _login_web_user(client)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO guild_settings (guild_id) VALUES (?)",
            ("359077662742020107",),
        )
        conn.commit()
    finally:
        conn.close()

    from bot.services.web_playback import WebPlaybackService

    call_count = [0]

    original = WebPlaybackService.get_control_state

    def counting_get_control_state(self, *args, **kwargs):
        call_count[0] += 1
        return original(self, *args, **kwargs)

    WebPlaybackService.get_control_state = counting_get_control_state
    try:
        resp1 = client.get("/api/web_control_state?guild_id=359077662742020107")
        assert resp1.status_code == 200
        first_count = call_count[0]
        assert first_count > 0

        resp2 = client.get("/api/web_control_state?guild_id=359077662742020107")
        assert resp2.status_code == 200
        assert call_count[0] == first_count
        assert resp1.get_json() == resp2.get_json()
    finally:
        WebPlaybackService.get_control_state = original


def test_read_cache_separates_different_query_params(web_client):
    """Different query args for the same endpoint produce different cache entries."""
    client, _ = web_client
    _clear_response_cache()

    from bot.services.web_content import WebContentService

    call_count = [0]

    original = WebContentService.get_actions

    def counting_get_actions(self, *args, **kwargs):
        call_count[0] += 1
        return original(self, *args, **kwargs)

    WebContentService.get_actions = counting_get_actions
    try:
        resp1 = client.get("/api/actions?page=1")
        assert resp1.status_code == 200
        first_count = call_count[0]

        # Different page — different cache key.
        resp2 = client.get("/api/actions?page=2")
        assert resp2.status_code == 200
        # Service should have been called again because the cache key differs.
        assert call_count[0] == first_count + 1, (
            f"expected {first_count + 1} calls after page=2 request, got {call_count[0]}"
        )

        # First page should still be cached.
        resp3 = client.get("/api/actions?page=1")
        assert resp3.status_code == 200
        assert call_count[0] == first_count + 1  # no new call
        assert resp1.get_json() == resp3.get_json()
    finally:
        WebContentService.get_actions = original


def test_read_cache_separates_anon_vs_auth_content(web_client):
    """Anonymous and authenticated visibility scopes get separate cache entries."""
    client, db_path = web_client
    _clear_response_cache()

    from bot.services.web_content import WebContentService

    call_count = [0]

    original = WebContentService.get_actions

    def counting_get_actions(self, *args, **kwargs):
        call_count[0] += 1
        return original(self, *args, **kwargs)

    WebContentService.get_actions = counting_get_actions
    try:
        # Anonymous request.
        resp_anon = client.get("/api/actions")
        assert resp_anon.status_code == 200
        anon_count = call_count[0]

        # Authenticated request — should use a different cache scope.
        _login_web_user(client)
        resp_auth = client.get("/api/actions")
        assert resp_auth.status_code == 200
        assert call_count[0] == anon_count + 1

        # Third request as authenticated — cached.
        resp_auth2 = client.get("/api/actions")
        assert resp_auth2.status_code == 200
        assert call_count[0] == anon_count + 1
        assert resp_auth.get_json() == resp_auth2.get_json()
    finally:
        WebContentService.get_actions = original


def test_read_cache_invalidates_after_ttl_via_invalidate(web_client):
    """Forcing cache invalidation causes a fresh producer call."""
    client, _ = web_client
    _clear_response_cache()

    from bot.services.web_content import WebContentService

    call_count = [0]

    original = WebContentService.get_actions

    def counting_get_actions(self, *args, **kwargs):
        call_count[0] += 1
        return original(self, *args, **kwargs)

    WebContentService.get_actions = counting_get_actions
    try:
        resp1 = client.get("/api/actions")
        assert resp1.status_code == 200
        assert call_count[0] == 1

        # Invalidate cache directly.
        cache = app.extensions.get("web_response_cache")
        assert cache is not None
        cache.invalidate()

        resp2 = client.get("/api/actions")
        assert resp2.status_code == 200
        assert call_count[0] == 2  # fresh call after invalidation
    finally:
        WebContentService.get_actions = original


# ── Speech Training Dataset Tests ─────────────────────────────────────

class TestSpeechTrainingRoutes:
    """Tests for the speech training labeling routes."""

    def test_speech_training_page_redirects_when_not_logged_in(self, web_client):
        """Unauthenticated users get redirected to login."""
        client, db_path = web_client
        resp = client.get("/speech-training")
        assert resp.status_code in (302, 401)

    def test_speech_training_page_requires_admin(self, web_client):
        """Non-admin users get a 403 error page."""
        client, db_path = web_client
        resp = client.get("/speech-training")
        # Re-check as non-admin user
        _login_web_user(client, username="nonadmin", admin_guild_ids=[])
        resp = client.get("/speech-training")
        assert resp.status_code == 403

    def test_speech_training_page_renders_for_admin(self, web_client):
        """Admin users can see the speech training page."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        # Create a guild setting so guild_options works
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES ('111')")
            conn.commit()
        finally:
            conn.close()
        resp = client.get("/speech-training")
        assert resp.status_code == 200
        assert b"Dataset" in resp.data or b"dataset" in resp.data.lower()

    def test_api_users_requires_auth(self, web_client):
        """API /api/speech_training/users returns 401 when not logged in."""
        client, _ = web_client
        resp = client.get("/api/speech_training/users")
        assert resp.status_code == 401

    def test_api_users_requires_admin(self, web_client):
        """API /api/speech_training/users returns 403 for non-admin."""
        client, _ = web_client
        _login_web_user(client, username="nonadmin", admin_guild_ids=[])
        resp = client.get("/api/speech_training/users")
        assert resp.status_code == 403

    def test_api_users_returns_data(self, web_client):
        """Admin can fetch user aggregation."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])

        # Seed the speech_training_clips table
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS speech_training_clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    folder_name TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL UNIQUE,
                    duration_seconds REAL NOT NULL,
                    byte_size INTEGER NOT NULL DEFAULT 0,
                    sample_rate INTEGER NOT NULL DEFAULT 48000,
                    channels INTEGER NOT NULL DEFAULT 2,
                    sample_width INTEGER NOT NULL DEFAULT 2,
                    captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    label TEXT,
                    transcript TEXT,
                    notes TEXT,
                    reviewed_by_user_id TEXT,
                    reviewed_by_username TEXT,
                    reviewed_at DATETIME
                )
                """
            )
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "1", "user1", "User One", "user1_1",
                 "clip1.mp3", "111/user1_1/clip1.mp3", 1.5, 30000),
            )
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "1", "user1", "User One", "user1_1",
                 "clip2.mp3", "111/user1_1/clip2.mp3", 2.0, 40000),
            )
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "2", "user2", "User Two", "user2_2",
                 "clip3.mp3", "111/user2_2/clip3.mp3", 0.8, 16000),
            )
            conn.commit()
        finally:
            conn.close()

        resp = client.get("/api/speech_training/users?guild_id=111")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) == 2  # 2 users

    def test_api_clips_returns_paginated(self, web_client):
        """Admin can fetch paginated clips."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS speech_training_clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    folder_name TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL UNIQUE,
                    duration_seconds REAL NOT NULL,
                    byte_size INTEGER NOT NULL DEFAULT 0,
                    sample_rate INTEGER NOT NULL DEFAULT 48000,
                    channels INTEGER NOT NULL DEFAULT 2,
                    sample_width INTEGER NOT NULL DEFAULT 2,
                    captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    label TEXT,
                    transcript TEXT,
                    notes TEXT,
                    reviewed_by_user_id TEXT,
                    reviewed_by_username TEXT,
                    reviewed_at DATETIME
                )
                """
            )
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "1", "user1", "User One", "user1_1",
                 "clip1.mp3", "111/user1_1/clip1.mp3", 1.5, 30000),
            )
            conn.commit()
        finally:
            conn.close()

        resp = client.get("/api/speech_training/clips?guild_id=111")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["filename"] == "clip1.mp3"

    def test_api_clip_audio_returns_404_for_missing_file(self, web_client):
        """Audio route returns 404 when file doesn't exist on disk."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS speech_training_clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    folder_name TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL UNIQUE,
                    duration_seconds REAL NOT NULL,
                    byte_size INTEGER NOT NULL DEFAULT 0,
                    sample_rate INTEGER NOT NULL DEFAULT 48000,
                    channels INTEGER NOT NULL DEFAULT 2,
                    sample_width INTEGER NOT NULL DEFAULT 2,
                    captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    label TEXT,
                    transcript TEXT,
                    notes TEXT,
                    reviewed_by_user_id TEXT,
                    reviewed_by_username TEXT,
                    reviewed_at DATETIME
                )
                """
            )
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "1", "user1", "User One", "user1_1",
                 "nofile.mp3", "111/user1_1/nofile.mp3", 1.0, 20000),
            )
            conn.commit()
        finally:
            conn.close()

        resp = client.get("/api/speech_training/clips/1/audio")
        assert resp.status_code == 404

    def test_api_clip_label_update(self, web_client):
        """POST label updates the clip and reviewer metadata."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                 CREATE TABLE IF NOT EXISTS speech_training_clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    folder_name TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL UNIQUE,
                    duration_seconds REAL NOT NULL,
                    byte_size INTEGER NOT NULL DEFAULT 0,
                    sample_rate INTEGER NOT NULL DEFAULT 48000,
                    channels INTEGER NOT NULL DEFAULT 2,
                    sample_width INTEGER NOT NULL DEFAULT 2,
                    captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    label TEXT,
                    transcript TEXT,
                    notes TEXT,
                    reviewed_by_user_id TEXT,
                    reviewed_by_username TEXT,
                    reviewed_at DATETIME
                )
                """
            )
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "1", "user1", "User One", "user1_1",
                 "clip1.mp3", "111/user1_1/clip1.mp3", 1.5, 30000),
            )
            conn.commit()
        finally:
            conn.close()

        resp = client.post(
            "/api/speech_training/clips/1/label",
            json={"label": "chapada", "transcript": "test", "notes": "good"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

        # Verify DB was updated
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT label, transcript, reviewed_by_username FROM speech_training_clips WHERE id = 1"
            ).fetchone()
            assert row[0] == "chapada"
            assert row[1] == "test"
        finally:
            conn.close()

    def test_api_clips_supports_sort_param(self, web_client):
        """Clips endpoint accepts sort param and returns ordered results."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])

        conn = sqlite3.connect(db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS speech_training_clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT, user_id TEXT NOT NULL, username TEXT NOT NULL,
                    display_name TEXT, folder_name TEXT NOT NULL,
                    filename TEXT NOT NULL, relative_path TEXT NOT NULL UNIQUE,
                    duration_seconds REAL NOT NULL, byte_size INTEGER NOT NULL DEFAULT 0,
                    sample_rate INTEGER NOT NULL DEFAULT 48000,
                    channels INTEGER NOT NULL DEFAULT 2,
                    sample_width INTEGER NOT NULL DEFAULT 2,
                    captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    label TEXT, transcript TEXT, notes TEXT,
                    reviewed_by_user_id TEXT, reviewed_by_username TEXT, reviewed_at DATETIME
                )
            """)
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size, captured_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "1", "user1", "User One", "user1_1",
                 "short.mp3", "111/user1_1/short.mp3", 0.5, 10000, "2026-01-01 12:00:00"),
            )
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size, captured_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "2", "user2", "User Two", "user2_2",
                 "long.mp3", "111/user2_2/long.mp3", 5.0, 100000, "2026-01-02 12:00:00"),
            )
            conn.commit()
        finally:
            conn.close()

        resp = client.get("/api/speech_training/clips?guild_id=111&sort=longest")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["items"]) == 2
        assert data["items"][0]["duration_seconds"] == 5.0  # longest first

    def test_api_clip_delete(self, web_client):
        """DELETE clip removes the DB row."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])

        conn = sqlite3.connect(db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS speech_training_clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT, user_id TEXT NOT NULL, username TEXT NOT NULL,
                    display_name TEXT, folder_name TEXT NOT NULL,
                    filename TEXT NOT NULL, relative_path TEXT NOT NULL UNIQUE,
                    duration_seconds REAL NOT NULL, byte_size INTEGER NOT NULL DEFAULT 0,
                    sample_rate INTEGER NOT NULL DEFAULT 48000,
                    channels INTEGER NOT NULL DEFAULT 2,
                    sample_width INTEGER NOT NULL DEFAULT 2,
                    captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    label TEXT, transcript TEXT, notes TEXT,
                    reviewed_by_user_id TEXT, reviewed_by_username TEXT, reviewed_at DATETIME
                )
            """)
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "1", "user1", "User One", "user1_1",
                 "todelete.mp3", "111/user1_1/todelete.mp3", 1.0, 20000),
            )
            conn.commit()
        finally:
            conn.close()

        resp = client.delete("/api/speech_training/clips/1")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT id FROM speech_training_clips WHERE id = 1").fetchone()
            assert row is None
        finally:
            conn.close()

    def test_api_clip_delete_not_found(self, web_client):
        """DELETE missing clip returns 404."""
        client, _ = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        resp = client.delete("/api/speech_training/clips/99999")
        assert resp.status_code == 404

    def test_api_clip_delete_requires_admin(self, web_client):
        """DELETE clip requires admin."""
        client, _ = web_client
        resp = client.delete("/api/speech_training/clips/1")
        assert resp.status_code == 401

        _login_web_user(client, username="nonadmin", admin_guild_ids=[])
        resp = client.delete("/api/speech_training/clips/1")
        assert resp.status_code == 403

    def test_api_bulk_label(self, web_client):
        """POST bulk label updates multiple clips."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])

        conn = sqlite3.connect(db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS speech_training_clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT, user_id TEXT NOT NULL, username TEXT NOT NULL,
                    display_name TEXT, folder_name TEXT NOT NULL,
                    filename TEXT NOT NULL, relative_path TEXT NOT NULL UNIQUE,
                    duration_seconds REAL NOT NULL, byte_size INTEGER NOT NULL DEFAULT 0,
                    sample_rate INTEGER NOT NULL DEFAULT 48000,
                    channels INTEGER NOT NULL DEFAULT 2,
                    sample_width INTEGER NOT NULL DEFAULT 2,
                    captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    label TEXT, transcript TEXT, notes TEXT,
                    reviewed_by_user_id TEXT, reviewed_by_username TEXT, reviewed_at DATETIME
                )
            """)
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "1", "user1", "User One", "user1_1",
                 "a.mp3", "111/user1_1/a.mp3", 1.0, 20000),
            )
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "1", "user1", "User One", "user1_1",
                 "b.mp3", "111/user1_1/b.mp3", 1.0, 20000),
            )
            conn.commit()
        finally:
            conn.close()

        resp = client.post(
            "/api/speech_training/clips/bulk",
            json={"action": "label", "ids": [1, 2], "label": "chapada"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

        conn = sqlite3.connect(db_path)
        try:
            labels = conn.execute(
                "SELECT label FROM speech_training_clips ORDER BY id"
            ).fetchall()
            assert labels == [("chapada",), ("chapada",)]
        finally:
            conn.close()

    def test_api_bulk_delete(self, web_client):
        """POST bulk delete removes multiple clips."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])

        conn = sqlite3.connect(db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS speech_training_clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT, user_id TEXT NOT NULL, username TEXT NOT NULL,
                    display_name TEXT, folder_name TEXT NOT NULL,
                    filename TEXT NOT NULL, relative_path TEXT NOT NULL UNIQUE,
                    duration_seconds REAL NOT NULL, byte_size INTEGER NOT NULL DEFAULT 0,
                    sample_rate INTEGER NOT NULL DEFAULT 48000,
                    channels INTEGER NOT NULL DEFAULT 2,
                    sample_width INTEGER NOT NULL DEFAULT 2,
                    captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    label TEXT, transcript TEXT, notes TEXT,
                    reviewed_by_user_id TEXT, reviewed_by_username TEXT, reviewed_at DATETIME
                )
            """)
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "1", "user1", "User One", "user1_1",
                 "a.mp3", "111/user1_1/a.mp3", 1.0, 20000),
            )
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "1", "user1", "User One", "user1_1",
                 "b.mp3", "111/user1_1/b.mp3", 1.0, 20000),
            )
            conn.commit()
        finally:
            conn.close()

        resp = client.post(
            "/api/speech_training/clips/bulk",
            json={"action": "delete", "ids": [1, 2]},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

        conn = sqlite3.connect(db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM speech_training_clips").fetchone()[0]
            assert count == 0
        finally:
            conn.close()

    def test_api_bulk_invalid_action(self, web_client):
        """Bulk with unknown action returns 400."""
        client, _ = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        resp = client.post(
            "/api/speech_training/clips/bulk",
            json={"action": "unknown", "ids": [1]},
        )
        assert resp.status_code == 400

    def test_api_bulk_requires_admin(self, web_client):
        """Bulk endpoint requires admin."""
        client, _ = web_client
        resp = client.post(
            "/api/speech_training/clips/bulk",
            json={"action": "label", "ids": [1], "label": "chapada"},
        )
        assert resp.status_code == 401

    # ── Storage API ───────────────────────────────────────────────────

    def test_api_storage_requires_auth(self, web_client):
        """Storage API returns 401 when not logged in."""
        client, _ = web_client
        resp = client.get("/api/speech_training/storage")
        assert resp.status_code == 401

    def test_api_storage_requires_admin(self, web_client):
        """Storage API returns 403 for non-admin."""
        client, _ = web_client
        _login_web_user(client, username="nonadmin", admin_guild_ids=[])
        resp = client.get("/api/speech_training/storage")
        assert resp.status_code == 403

    def test_api_storage_returns_data(self, web_client):
        """Admin can fetch storage summary with disk info."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])

        conn = sqlite3.connect(db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS speech_training_clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT, user_id TEXT NOT NULL, username TEXT NOT NULL,
                    display_name TEXT, folder_name TEXT NOT NULL,
                    filename TEXT NOT NULL, relative_path TEXT NOT NULL UNIQUE,
                    duration_seconds REAL NOT NULL, byte_size INTEGER NOT NULL DEFAULT 0,
                    sample_rate INTEGER NOT NULL DEFAULT 48000,
                    channels INTEGER NOT NULL DEFAULT 2,
                    sample_width INTEGER NOT NULL DEFAULT 2,
                    captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    label TEXT, transcript TEXT, notes TEXT,
                    reviewed_by_user_id TEXT, reviewed_by_username TEXT, reviewed_at DATETIME
                )
            """)
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "1", "user1", "User One", "user1_1",
                 "a.mp3", "111/user1_1/a.mp3", 1.0, 30000),
            )
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "1", "user1", "User One", "user1_1",
                 "b.mp3", "111/user1_1/b.mp3", 2.0, 45000),
            )
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("222", "2", "user2", "User Two", "user2_2",
                 "c.mp3", "222/user2_2/c.mp3", 0.5, 12000),
            )
            conn.commit()
        finally:
            conn.close()

        with patch("bot.services.web_speech_training.shutil.disk_usage") as mock_du:
            mock_du.return_value.total = 512_000_000_000
            mock_du.return_value.free = 200_000_000_000

            # Fetch with guild filter
            resp = client.get("/api/speech_training/storage?guild_id=111")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["total_bytes"] == 75000  # 30000 + 45000
            assert data["clip_count"] == 2
            assert data["total_size"] == "73.2 KB"
            assert data["available_bytes"] == 200_000_000_000
            assert data["available_size"] == "186.3 GB"
            assert data["disk_total_bytes"] == 512_000_000_000
            assert data["disk_total_size"] == "476.8 GB"

            # Fetch without filter (all guilds)
            resp = client.get("/api/speech_training/storage")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["total_bytes"] == 87000  # 30000 + 45000 + 12000
            assert data["clip_count"] == 3
            assert data["available_bytes"] == 200_000_000_000
            assert data["available_size"] == "186.3 GB"

    def test_api_storage_no_data(self, web_client):
        """Storage API returns zeros when no clips exist, plus disk info."""
        client, _ = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        with patch("bot.services.web_speech_training.shutil.disk_usage") as mock_du:
            mock_du.return_value.total = 1_000_000_000_000
            mock_du.return_value.free = 800_000_000_000
            resp = client.get("/api/speech_training/storage")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["total_bytes"] == 0
            assert data["clip_count"] == 0
            assert data["total_size"] == "0 B"
            assert data["available_bytes"] == 800_000_000_000
            assert data["available_size"] == "745.1 GB"
            assert data["disk_total_bytes"] == 1_000_000_000_000
            assert data["disk_total_size"] == "931.3 GB"

    def test_api_storage_page_renders_with_element(self, web_client):
        """Speech training page includes the storage element."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES ('111')")
            conn.commit()
        finally:
            conn.close()
        resp = client.get("/speech-training")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'id="storageUsed"' in html
        assert 'MP3 storage:' in html
        assert 'Machine: —' in html

    def test_analytics_page_shows_dataset_link_for_admin(self, web_client):
        """Analytics page includes Dataset link in nav for admin users."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES ('111')")
            conn.commit()
        finally:
            conn.close()
        resp = client.get("/analytics")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert '/speech-training' in html
        assert 'Dataset' in html

    def test_analytics_page_hides_dataset_link_for_non_admin(self, web_client):
        """Analytics page should not include Dataset link for non-admin."""
        client, _ = web_client
        resp = client.get("/analytics")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # Dataset link should not appear for anonymous
        assert 'href="/speech-training"' not in html

    def test_speech_training_page_uses_shared_nav(self, web_client):
        """Speech training page has shared nav with Dataset active."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES ('111')")
            conn.commit()
        finally:
            conn.close()
        resp = client.get("/speech-training")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # Should have shared nav content
        assert 'href="/speech-training"' in html
        assert 'nav-link' in html
        assert 'nav-brand' in html

    # ── Keyword scan API (async) ────────────────────────────────────────

    def _wait_for_keyword_scan_job(self, client, job_id: str, deadline_seconds: int = 5) -> dict:
        """Poll a keyword scan job GET endpoint until terminal state."""
        deadline = time.time() + deadline_seconds
        payload = {}
        while time.time() < deadline:
            response = client.get(f"/api/speech_training/keyword_scan/{job_id}")
            assert response.status_code == 200
            payload = response.get_json()
            if payload.get("status") in {"done", "error"}:
                return payload
            time.sleep(0.05)
        raise AssertionError(f"Keyword scan job did not finish: {payload}")

    def test_api_keyword_scan_requires_auth(self, web_client):
        """Keyword scan POST returns 401 when not logged in."""
        client, _ = web_client
        resp = client.post("/api/speech_training/keyword_scan")
        assert resp.status_code == 401

    def test_api_keyword_scan_requires_admin(self, web_client):
        """Keyword scan POST returns 403 for non-admin."""
        client, _ = web_client
        _login_web_user(client, username="nonadmin", admin_guild_ids=[])
        resp = client.post("/api/speech_training/keyword_scan")
        assert resp.status_code == 403

    def test_api_keyword_scan_status_requires_auth(self, web_client):
        """Keyword scan GET status returns 401 when not logged in."""
        client, _ = web_client
        resp = client.get("/api/speech_training/keyword_scan/some-job-id")
        assert resp.status_code == 401

    def test_api_keyword_scan_status_requires_admin(self, web_client):
        """Keyword scan GET status returns 403 for non-admin."""
        client, _ = web_client
        _login_web_user(client, username="nonadmin", admin_guild_ids=[])
        resp = client.get("/api/speech_training/keyword_scan/some-job-id")
        assert resp.status_code == 403

    def test_api_keyword_scan_status_not_found(self, web_client):
        """GET returns 404 for unknown job id."""
        client, _ = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        resp = client.get("/api/speech_training/keyword_scan/nonexistent-job-id")
        assert resp.status_code == 404

    def test_api_keyword_scan_invalid_confidence(self, web_client):
        """POST with out-of-range confidence returns JSON 400."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES ('111')")
            conn.commit()
        finally:
            conn.close()
        resp = client.post(
            "/api/speech_training/keyword_scan",
            json={"keyword": "chapada", "min_confidence": 1.5},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    def test_api_keyword_scan_empty_keyword_defaults(self, web_client):
        """POST with empty keyword defaults to 'chapada' and succeeds."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES ('111')")
            conn.commit()
        finally:
            conn.close()
        resp = client.post(
            "/api/speech_training/keyword_scan",
            json={"keyword": "", "min_confidence": 0.5},
        )
        # Empty keyword defaults to "chapada", so POST succeeds
        assert resp.status_code == 202
        data = resp.get_json()
        assert "job_id" in data

    @patch("bot.services.web_speech_training._get_vosk_model")
    def test_api_keyword_scan_no_model(self, mock_get_model, web_client):
        """POST queues job, GET returns error when Vosk model unavailable."""
        mock_get_model.return_value = None
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES ('111')")
            conn.commit()
        finally:
            conn.close()
        # Start scan (returns 202 with job_id)
        resp = client.post("/api/speech_training/keyword_scan", json={})
        assert resp.status_code == 202
        data = resp.get_json()
        assert "job_id" in data
        assert data["status"] == "queued"

        job_id = data["job_id"]
        # Poll until error
        payload = self._wait_for_keyword_scan_job(client, job_id)
        assert payload["status"] == "error"
        assert "Vosk model" in payload["error"]

    @patch("bot.services.web_speech_training._get_vosk_model")
    def test_api_keyword_scan_async(self, mock_get_model, web_client):
        """POST starts async scan, GET polls status until done."""
        mock_get_model.return_value = MagicMock()
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES ('111')")
            conn.commit()
        finally:
            conn.close()

        resp = client.post(
            "/api/speech_training/keyword_scan",
            json={"keyword": "chapada", "min_confidence": 0.5},
        )
        assert resp.status_code == 202
        data = resp.get_json()
        assert "job_id" in data
        assert data["status"] == "queued"

        job_id = data["job_id"]
        payload = self._wait_for_keyword_scan_job(client, job_id)
        assert payload["status"] == "done"
        assert payload["keyword"] == "chapada"
        assert payload["min_confidence"] == 0.5
        assert payload["max_duration_seconds"] == 30.0
        assert "scanned" in payload
        assert "matched" in payload
        assert "matches" in payload
        assert payload["label_matches_as_potential"] is True
        assert "labeled_matches" in payload
        assert payload["trim_matches_to_keyword"] is True
        assert "trimmed_matches" in payload
        assert "failed_trim_matches" in payload

    @patch("bot.repositories.keyword.KeywordRepository.get_all")
    def test_api_keyword_scan_all_keywords_no_keywords(self, mock_get_all, web_client):
        """POST with all_keywords=true and no keywords in DB returns 400."""
        mock_get_all.return_value = []
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        resp = client.post(
            "/api/speech_training/keyword_scan",
            json={"all_keywords": True},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data
        assert "No trigger keywords configured" in data["error"]

    @patch("bot.repositories.keyword.KeywordRepository.get_all")
    @patch("bot.services.web_speech_training._get_vosk_model")
    def test_api_keyword_scan_all_keywords_with_keywords(
        self, mock_get_model, mock_get_all, web_client
    ):
        """POST with all_keywords=true uses trigger keywords from DB."""
        mock_get_model.return_value = MagicMock()
        mock_get_all.return_value = [
            {"keyword": "chapada", "action_type": "slap", "action_value": ""},
            {"keyword": "ventura", "action_type": "slap", "action_value": ""},
        ]
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES ('111')")
            conn.commit()
        finally:
            conn.close()

        resp = client.post(
            "/api/speech_training/keyword_scan",
            json={"all_keywords": True, "min_confidence": 0.5},
        )
        assert resp.status_code == 202
        data = resp.get_json()
        assert "job_id" in data
        assert data["status"] == "queued"

        job_id = data["job_id"]
        payload = self._wait_for_keyword_scan_job(client, job_id)
        assert payload["status"] == "done"
        assert payload["keyword"] == "keywords"
        assert "keywords" in payload
        assert payload["keyword_count"] == 2

    # ── Keyword scan schedule API ────────────────────────────────────

    def test_api_keyword_scan_schedule_requires_auth(self, web_client):
        """GET schedule returns 401 when not logged in."""
        client, _ = web_client
        resp = client.get("/api/speech_training/keyword_scan/schedule")
        assert resp.status_code == 401

    def test_api_keyword_scan_schedule_requires_admin(self, web_client):
        """GET schedule returns 403 for non-admin."""
        client, _ = web_client
        _login_web_user(client, username="nonadmin", admin_guild_ids=[])
        resp = client.get("/api/speech_training/keyword_scan/schedule")
        assert resp.status_code == 403

    def test_api_keyword_scan_schedule_defaults(self, web_client):
        """GET schedule returns defaults/None when no settings exist."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES ('111')")
            conn.commit()
        finally:
            conn.close()
        with patch.dict(os.environ, {
            "SPEECH_TRAINING_KEYWORD_SCAN_ENABLED": "false",
        }):
            resp = client.get("/api/speech_training/keyword_scan/schedule")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["enabled"] is False
        assert data["interval_seconds"] == 86400
        assert data["last_started_at"] is None
        assert data["last_finished_at"] is None
        assert data["last_status"] is None
        assert data["last_summary"] is None
        assert data["next_run_at"] is None
        assert data["updated_at"] is None

    def test_api_keyword_scan_schedule_returns_persisted(self, web_client):
        """GET schedule returns persisted timestamps/status/summary."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES ('111')")
            # Manually create app_settings table and insert test data
            conn.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_by TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.executemany(
                "INSERT OR REPLACE INTO app_settings (key, value, updated_by) VALUES (?, ?, 'test')",
                [
                    ("speech_training_keyword_scan.enabled", "1"),
                    ("speech_training_keyword_scan.interval_seconds", "3600"),
                    ("speech_training_keyword_scan.last_started_at", "2026-05-26T10:00:00"),
                    ("speech_training_keyword_scan.last_finished_at", "2026-05-26T10:30:00"),
                    ("speech_training_keyword_scan.last_status", "completed"),
                    ("speech_training_keyword_scan.last_summary", "3 guilds, 83 scanned, 5 matches"),
                    ("speech_training_keyword_scan.next_run_at", "2026-05-27T10:00:00"),
                    ("speech_training_keyword_scan.updated_at", "2026-05-26T10:30:00"),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        resp = client.get("/api/speech_training/keyword_scan/schedule")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["enabled"] is True
        assert data["interval_seconds"] == 3600
        assert data["last_started_at"] == "2026-05-26T10:00:00"
        assert data["last_finished_at"] == "2026-05-26T10:30:00"
        assert data["last_status"] == "completed"
        assert data["last_summary"] == "3 guilds, 83 scanned, 5 matches"
        assert data["next_run_at"] == "2026-05-27T10:00:00"
        assert data["updated_at"] == "2026-05-26T10:30:00"

    def test_speech_training_page_has_schedule_element(self, web_client):
        """Template should include the keywordScanSchedule span inside the Find Keywords button."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES ('111')")
            conn.commit()
        finally:
            conn.close()
        resp = client.get("/speech-training")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'id="keywordScanSchedule"' in html
        assert 'id="scanKeywordBtn"' in html
        # Verify the schedule span is inside the button
        btn_start = html.index('id="scanKeywordBtn"')
        btn_close = html.index('</button>', btn_start)
        schedule_section = html[btn_start:btn_close]
        assert 'id="keywordScanSchedule"' in schedule_section

    # ── clip IDs endpoint (unpaginated select-all) ─────────────────────

    def test_api_clip_ids_requires_auth(self, web_client):
        """GET /api/speech_training/clips/ids returns 401 when not logged in."""
        client, _ = web_client
        resp = client.get("/api/speech_training/clips/ids")
        assert resp.status_code == 401

    def test_api_clip_ids_requires_admin(self, web_client):
        """GET /api/speech_training/clips/ids returns 403 for non-admin."""
        client, _ = web_client
        _login_web_user(client, username="nonadmin", admin_guild_ids=[])
        resp = client.get("/api/speech_training/clips/ids")
        assert resp.status_code == 403

    def test_api_clip_ids_returns_all_ids(self, web_client):
        """Admin can fetch all clip IDs without pagination."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS speech_training_clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    folder_name TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL UNIQUE,
                    duration_seconds REAL NOT NULL,
                    byte_size INTEGER NOT NULL DEFAULT 0,
                    sample_rate INTEGER NOT NULL DEFAULT 48000,
                    channels INTEGER NOT NULL DEFAULT 2,
                    sample_width INTEGER NOT NULL DEFAULT 2,
                    captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    label TEXT,
                    transcript TEXT,
                    notes TEXT,
                    reviewed_by_user_id TEXT,
                    reviewed_by_username TEXT,
                    reviewed_at DATETIME
                )
                """
            )
            # Insert more than one page worth of clips to verify unpaginated
            for i in range(5):
                conn.execute(
                    "INSERT INTO speech_training_clips "
                    "(guild_id, user_id, username, display_name, folder_name, filename, "
                    "relative_path, duration_seconds, byte_size) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("111", "1", "user1", "User One", "user1_1",
                     f"clip{i}.mp3", f"111/user1_1/clip{i}.mp3", 1.0, 10000),
                )
            conn.commit()
        finally:
            conn.close()

        resp = client.get("/api/speech_training/clips/ids?guild_id=111")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "ids" in data
        assert "total" in data
        assert data["total"] == 5
        assert len(data["ids"]) == 5
        assert all(isinstance(i, int) for i in data["ids"])

    def test_api_clip_ids_honors_filters(self, web_client):
        """Clip IDs endpoint respects search, user_id, and label filters."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS speech_training_clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT,
                    folder_name TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL UNIQUE,
                    duration_seconds REAL NOT NULL,
                    byte_size INTEGER NOT NULL DEFAULT 0,
                    sample_rate INTEGER NOT NULL DEFAULT 48000,
                    channels INTEGER NOT NULL DEFAULT 2,
                    sample_width INTEGER NOT NULL DEFAULT 2,
                    captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    label TEXT,
                    transcript TEXT,
                    notes TEXT,
                    reviewed_by_user_id TEXT,
                    reviewed_by_username TEXT,
                    reviewed_at DATETIME
                )
                """
            )
            # Insert clips with different attributes
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size, label) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "1", "user1", "User One", "user1_1",
                 "labeled.mp3", "111/user1_1/labeled.mp3", 1.0, 10000, "chapada"),
            )
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "1", "user1", "User One", "user1_1",
                 "unlabeled.mp3", "111/user1_1/unlabeled.mp3", 1.0, 10000),
            )
            conn.execute(
                "INSERT INTO speech_training_clips "
                "(guild_id, user_id, username, display_name, folder_name, filename, "
                "relative_path, duration_seconds, byte_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("111", "2", "user2", "User Two", "user2_2",
                 "other_user.mp3", "111/user2_2/other_user.mp3", 1.0, 10000),
            )
            conn.commit()
        finally:
            conn.close()

        # All IDs for guild 111
        resp = client.get("/api/speech_training/clips/ids?guild_id=111")
        assert resp.status_code == 200
        assert resp.get_json()["total"] == 3

        # Filter by label "chapada"
        resp = client.get("/api/speech_training/clips/ids?guild_id=111&label=chapada")
        assert resp.status_code == 200
        assert resp.get_json()["total"] == 1

        # Filter by user
        resp = client.get("/api/speech_training/clips/ids?guild_id=111&user_id=2")
        assert resp.status_code == 200
        assert resp.get_json()["total"] == 1

        # Filter by search (match unique filename)
        resp = client.get("/api/speech_training/clips/ids?guild_id=111&search=other_user")
        assert resp.status_code == 200
        assert resp.get_json()["total"] == 1

        # No match filter
        resp = client.get("/api/speech_training/clips/ids?guild_id=111&search=nonexistent")
        assert resp.status_code == 200
        assert resp.get_json()["total"] == 0
        assert resp.get_json()["ids"] == []


    def test_transcribe_empty_requires_login_and_admin(self, web_client):
        """POST /api/speech_training/transcribe_empty requires auth and admin."""
        client, _ = web_client

        # No login → 401
        resp = client.post("/api/speech_training/transcribe_empty", json={})
        assert resp.status_code == 401

        # Login but not admin → 403
        _login_web_user(client, username="regular")
        resp = client.post("/api/speech_training/transcribe_empty", json={})
        assert resp.status_code == 403

        # Admin → 202 even though GROQ_API_KEY not set
        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        resp = client.post("/api/speech_training/transcribe_empty", json={})
        assert resp.status_code == 202
        payload = resp.get_json()
        assert payload["status"] == "queued"
        assert payload["job_id"]

    def test_transcribe_empty_status_requires_auth_and_admin(self, web_client):
        """GET transcribe_empty/<job_id> requires auth."""
        client, _ = web_client

        resp = client.get("/api/speech_training/transcribe_empty/fake-id")
        assert resp.status_code == 401

        _login_web_user(client, username="admin", admin_guild_ids=["111"])
        resp = client.get("/api/speech_training/transcribe_empty/fake-id")
        assert resp.status_code == 404

    def test_transcribe_empty_job_progresses_to_terminal(self, web_client):
        """A transcript job transitions through queued → done."""
        import time
        client, _ = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])

        resp = client.post("/api/speech_training/transcribe_empty", json={"guild_id": "111"})
        assert resp.status_code == 202
        job_id = resp.get_json()["job_id"]
        assert job_id

        # Poll until terminal
        deadline = time.time() + 10
        last_status = None
        while time.time() < deadline:
            poll_resp = client.get(f"/api/speech_training/transcribe_empty/{job_id}")
            assert poll_resp.status_code == 200
            payload = poll_resp.get_json()
            last_status = payload["status"]
            if last_status in ("done", "error"):
                break
            time.sleep(0.1)

        # Because GROQ_API_KEY is empty in test env, it should error
        assert last_status in ("done", "error")
        # The job should have produced a result
        if last_status == "done":
            assert "total" in payload
        elif last_status == "error":
            assert "GROQ_API_KEY" in (payload.get("error") or "")

    # ── Trim-to-keyword API ────────────────────────────────────────────

    def test_api_trim_to_keyword_requires_auth(self, web_client):
        """POST trim_to_keyword returns 401 when not logged in."""
        client, _ = web_client
        resp = client.post("/api/speech_training/clips/1/trim_to_keyword", json={})
        assert resp.status_code == 401

    def test_api_trim_to_keyword_requires_admin(self, web_client):
        """POST trim_to_keyword returns 403 for non-admin."""
        client, _ = web_client
        _login_web_user(client, username="nonadmin", admin_guild_ids=[])
        resp = client.post("/api/speech_training/clips/1/trim_to_keyword", json={})
        assert resp.status_code == 403

    def test_api_trim_to_keyword_success(self, web_client):
        """POST trim_to_keyword returns updated metadata on success."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])

        # Ensure guild settings exist
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES ('111')")
            conn.commit()
        finally:
            conn.close()

        mock_metadata = {
            "duration_seconds": 0.8,
            "byte_size": 12000,
            "keyword_start_seconds": 0.15,
            "keyword_end_seconds": 0.55,
            "trim_start_seconds": 1.7,
            "trim_end_seconds": 3.4,
        }

        with patch(
            "bot.services.web_speech_training.WebSpeechTrainingService.trim_clip_to_keyword",
            return_value=(True, "", mock_metadata),
        ):
            resp = client.post(
                "/api/speech_training/clips/1/trim_to_keyword",
                json={},
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["duration_seconds"] == 0.8
        assert data["byte_size"] == 12000
        assert data["keyword_start_seconds"] == 0.15
        assert data["keyword_end_seconds"] == 0.55

    def test_api_trim_to_keyword_clip_not_found(self, web_client):
        """POST trim_to_keyword returns 404 when clip not found."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])

        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES ('111')")
            conn.commit()
        finally:
            conn.close()

        with patch(
            "bot.services.web_speech_training.WebSpeechTrainingService.trim_clip_to_keyword",
            return_value=(False, "Clip not found", {}),
        ):
            resp = client.post(
                "/api/speech_training/clips/99999/trim_to_keyword",
                json={},
            )

        assert resp.status_code == 404
        assert "error" in resp.get_json()

    def test_api_trim_to_keyword_no_timing(self, web_client):
        """POST trim_to_keyword returns 400 when timing is missing."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])

        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES ('111')")
            conn.commit()
        finally:
            conn.close()

        with patch(
            "bot.services.web_speech_training.WebSpeechTrainingService.trim_clip_to_keyword",
            return_value=(False, "Keyword timing not available. Run a keyword scan first.", {}),
        ):
            resp = client.post(
                "/api/speech_training/clips/1/trim_to_keyword",
                json={},
            )

        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data
        assert "timing" in data["error"].lower()

    def test_api_trim_to_keyword_invalid_params(self, web_client):
        """POST trim_to_keyword with invalid start_seconds returns 400."""
        client, db_path = web_client
        _login_web_user(client, username="admin", admin_guild_ids=["111"])

        conn = sqlite3.connect(db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES ('111')")
            conn.commit()
        finally:
            conn.close()

        resp = client.post(
            "/api/speech_training/clips/1/trim_to_keyword",
            json={"start_seconds": "not-a-number"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data
        assert "start_seconds" in data["error"]
