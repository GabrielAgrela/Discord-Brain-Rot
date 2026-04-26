import sqlite3
import io
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from WebPage import app


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
    db_path = tmp_path / "web.db"
    _create_web_tables(db_path)
    monkeypatch.delenv("DEFAULT_GUILD_ID", raising=False)

    original_db_path = app.config["DATABASE_PATH"]
    original_sounds_dir = app.config["SOUNDS_DIR"]
    sounds_dir = tmp_path / "Sounds"
    sounds_dir.mkdir()
    app.config.update(TESTING=True, DATABASE_PATH=str(db_path), SOUNDS_DIR=str(sounds_dir))

    try:
        with app.test_client() as client:
            yield client, db_path
    finally:
        app.config["DATABASE_PATH"] = original_db_path
        app.config["SOUNDS_DIR"] = original_sounds_dir


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
            "display_username": "bob",
            "action": "play_request",
            "timestamp": "2026-04-03 12:05:00",
        }
    ]
    assert all_sounds_response.status_code == 200
    assert all_sounds_response.get_json()["items"] == [
        {
            "sound_id": 2,
            "display_filename": "beta.mp3",
            "timestamp": "2026-04-02 12:00:00",
        }
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
    assert [upload["filename"] for upload in payload["uploads"]] == ["first.mp3"]


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


def test_tts_enhance_endpoint_requires_discord_login(web_client):
    client, _ = web_client

    response = client.post("/api/tts/enhance", json={"message": "hello"})

    assert response.status_code == 401


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
    assert "initialSoundboardData" in html
    assert "alpha" in html
    assert "gamma" in html
    assert "alice" in html
    assert "Played" in html
    assert 'id="pageInputActions"' in html
    assert 'id="pageInputFavorites"' in html
    assert 'id="pageInputAllSounds"' in html
    assert "setupPageInput" in html
    assert 'class="web-controls"' not in html
    assert 'id="controlRoomMuteButton"' in html
    assert 'id="controlRoomTtsButton"' in html
    assert 'id="controlRoomSlapButton"' in html
    assert 'id="webTtsDialog"' in html
    assert 'id="webTtsProfile"' in html
    assert 'id="webTtsMessage"' in html
    assert 'id="webTtsEnhanceButton"' in html
    assert "let ttsEnhancedMessageValue = ''" in html
    assert "This message has already been enhanced. Edit it to enhance again." in html
    assert "webTtsMessage.addEventListener('input'" in html
    assert 'id="soundRowContextMenu"' in html
    assert 'id="soundRowEditOption"' in html
    assert 'class="sound-options-row" data-sound-id="1"' in html
    assert "tablesGrid.addEventListener('contextmenu', openSoundRowContextMenu)" in html
    assert "/api/tts/enhance" in html
    assert "window.prompt" not in html
    assert 'id="controlRoomUpdated"' not in html
    assert '<span>Guild</span>' not in html
    assert 'id="webUploadOpenButton"' in html
    assert 'class="control-room-metric-button web-upload-control-button login-required"' in html
    assert '<span class="control-room-metric-label">Upload</span>' in html
    assert '<span class="control-room-metric-label">TTS</span>' in html
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
    assert "addUploadQueueItem" in html
    assert "renderUploadQueue" in html
    assert "webUploadForm.reset();" in html
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
    assert 'for="actions-action-filter">Action</label>' not in html
    assert 'for="actions-user-filter">User</label>' not in html
    assert 'for="favorites-user-filter">User</label>' not in html
    assert 'for="searchAllSounds">Search</label>' not in html
    assert 'for="all_sounds-list-filter">List</label>' not in html
    assert "hideLabel: true" in html
    assert "allLabel: 'All Users'" in html
    assert "allLabel: 'All Lists'" in html
    assert 'class="theme-toggle"' in html
    assert "brainrot-theme" in html
    assert "applyThemePreference" in html
    assert "🌙" in html
    assert "☀️" in html
    assert "hasRenderableFilterPayload(endpoint, data.filters)" in html
    assert "setEndpointLoading" in html
    assert "aria-busy" in html
    assert "touchend" in html
    assert "handlePlayButtonActivation" in html
    assert "handleWebControlActivation" in html
    assert "requestInFlight" in html
    assert "isButtonCooldown" not in html
    assert "fetchFunction();" not in html
    assert "pendingInitialRenderEndpoints" in html
    assert "🔒" in html
    assert "Login with Discord to use bot controls" in html
    assert "Play sound" in html
    assert "Queue sound" not in html
    assert "controlRoomQueue" not in html
    assert ">Queue<" not in html
    assert "Queued" not in html
    assert "Queue the right clip fast, without the generic dashboard look." not in html
    assert "What just happened, who triggered it, and how fresh it is." not in html
    assert "The shortlist for when you already know the bit you want." not in html
    assert "The full catalog, including older uploads and new arrivals." not in html


def test_analytics_page_renders_shared_redesign(web_client):
    client, _ = web_client

    response = client.get("/analytics")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "/static/web.css" in html
    assert 'class="theme-toggle"' in html
    assert "brainrot-theme" in html
    assert "🌙" in html
    assert "☀️" in html
    assert '<span class="nav-icon" aria-hidden="true">🎛️</span>' in html
    assert '<span class="nav-text">Soundboard</span>' in html
    assert '<span class="nav-icon" aria-hidden="true">📊</span>' in html
    assert '<span class="nav-text">Analytics</span>' in html
    assert 'nav-upload-button' not in html
    assert '<span class="nav-text">Upload</span>' not in html
    assert 'class="time-selector"' in html
    assert "Activity Heatmap" in html
    assert "🔒" in html
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
    assert "tableLoadingSweep" in stylesheet
    assert ".table-container.is-loading" in stylesheet
    assert ".theme-toggle" in stylesheet
    assert "html.theme-dark" in stylesheet
    assert 'border-radius: 999px' in stylesheet
    assert 'html.theme-dark .heatmap-cell[data-level="5"]' in stylesheet
    assert "html.theme-dark .play-button" in stylesheet
    assert "html.theme-dark .nav-brand-mark" in stylesheet
    assert "background: var(--error)" in stylesheet
    assert "animation: none" in stylesheet
    assert "body.page-soundboard .library-controls" in stylesheet
    assert "margin-bottom: 2.4rem" in stylesheet
    assert "min-height: 4.4rem" in stylesheet
    assert "top: calc(0.5rem + env(safe-area-inset-top, 0px))" in stylesheet
    assert ".control-room .card-kicker" in stylesheet
    assert ".play-button.sent" in stylesheet
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
            ("niggas young fly on the tra", "play_request", "1", "2026-04-01 12:01:00", "111"),
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
    }

    assert favorites_response.status_code == 200
    assert favorites_response.get_json()["items"][0] == {
        "sound_id": 1,
        "display_filename": "******",
    }

    assert all_sounds_response.status_code == 200
    assert all_sounds_response.get_json()["items"][0] == {
        "sound_id": 1,
        "display_filename": "******",
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
    }

    assert favorites_response.status_code == 200
    assert favorites_response.get_json()["items"][0] == {
        "sound_id": 1,
        "display_filename": "jews did 911.mp3",
    }

    assert all_sounds_response.status_code == 200
    assert all_sounds_response.get_json()["items"][0] == {
        "sound_id": 1,
        "display_filename": "jews did 911.mp3",
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
                "display_username": "alice",
                "action": "play_request",
                "timestamp": "2026-04-04 12:00:00",
            }
        ],
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
            }
        ],
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
                "timestamp": "2026-04-03 12:00:00",
            }
        ],
        "total_pages": 1,
        "filters": {
            "sound": ["alpha.mp3", "beta.mp3", "gamma.mp3"],
            "date": ["2026-04-03", "2026-04-02", "2026-04-01"],
            "list": [],
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
                "timestamp": "2026-04-02 12:00:00",
            }
        ],
        "total_pages": 1,
        "filters": {
            "sound": ["alpha.mp3", "beta.mp3"],
            "date": ["2026-04-02", "2026-04-01"],
            "list": [
                {"value": "10", "label": "Airhorns (alice)"},
                {"value": "11", "label": "Drops (bob)"},
            ],
        },
    }


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
    }
    assert payload["lists"] == [
        {"id": 10, "name": "Bits", "creator": "alice", "sound_count": 0, "label": "Bits (alice)"}
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
            }
        ],
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
                "display_username": "alice",
                "action": "play_request",
                "timestamp": "2026-04-04 12:00:00",
            }
        ],
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
            }
        ],
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
                "timestamp": "2026-04-04 12:00:00",
            }
        ],
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
    assert "const initialSoundboardData =" in html
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
            ("jews did 911", "play_request", "1", "2026-04-01 12:01:00", "111"),
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
