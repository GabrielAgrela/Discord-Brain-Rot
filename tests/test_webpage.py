import sqlite3
from pathlib import Path

import pytest

from WebPage import app


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
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def web_client(tmp_path, monkeypatch):
    db_path = tmp_path / "web.db"
    _create_web_tables(db_path)
    monkeypatch.delenv("DEFAULT_GUILD_ID", raising=False)

    original_db_path = app.config["DATABASE_PATH"]
    app.config.update(TESTING=True, DATABASE_PATH=str(db_path))

    try:
        with app.test_client() as client:
            yield client, db_path
    finally:
        app.config["DATABASE_PATH"] = original_db_path


def test_play_sound_endpoint_queues_request_with_inferred_single_guild(web_client):
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

    response = client.post("/api/play_sound", json={"sound_filename": "test.mp3"})

    assert response.status_code == 200
    assert response.get_json() == {"message": "Playback request queued"}

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT guild_id, sound_filename FROM playback_queue"
        ).fetchone()
    finally:
        conn.close()

    assert row == (359077662742020107, "test.mp3")


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

    response = client.post("/api/play_sound", json={"sound_id": 1})

    assert response.status_code == 200
    assert response.get_json() == {"message": "Playback request queued"}

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT guild_id, sound_filename FROM playback_queue"
        ).fetchone()
    finally:
        conn.close()

    assert row == (359077662742020107, "jews did 911.mp3")


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
        "display_filename": "[censored]",
        "display_username": "[censored]",
        "action": "play_request",
        "timestamp": "2026-04-01 12:01:00",
    }

    assert favorites_response.status_code == 200
    assert favorites_response.get_json()["items"][0] == {
        "sound_id": 1,
        "display_filename": "[censored]",
    }

    assert all_sounds_response.status_code == 200
    assert all_sounds_response.get_json()["items"][0] == {
        "sound_id": 1,
        "display_filename": "[censored]",
        "timestamp": "2026-04-01 12:00:00",
    }


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
        "display_username": "[censored]",
        "count": 1,
    }

    assert top_sounds_response.status_code == 200
    assert top_sounds_response.get_json()["sounds"][0] == {
        "sound_id": 1,
        "display_filename": "[censored]",
        "count": 1,
    }

    assert recent_activity_response.status_code == 200
    assert recent_activity_response.get_json()["activities"][0] == {
        "display_username": "[censored]",
        "action": "play_request",
        "timestamp": "2026-04-01 12:01:00",
        "display_sound": "[censored]",
    }
