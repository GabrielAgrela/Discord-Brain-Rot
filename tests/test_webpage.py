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
