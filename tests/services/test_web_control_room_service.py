import sqlite3
from datetime import datetime

from bot.repositories.web_control_room import WebControlRoomRepository
from bot.services.web_control_room import WebControlRoomService


def test_web_control_room_service_combines_runtime_and_mute(tmp_path):
    db_path = tmp_path / "control_room_service.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE guild_settings (guild_id TEXT PRIMARY KEY)")
        conn.execute(
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
        conn.execute("INSERT INTO guild_settings (guild_id) VALUES (?)", ("123",))
        conn.commit()
    finally:
        conn.close()

    repository = WebControlRoomRepository(db_path=str(db_path), use_shared=False)
    repository.upsert_status(
        guild_id=123,
        guild_name="Guild",
        voice_connected=True,
        voice_channel_id=456,
        voice_channel_name="Voice",
        voice_member_count=4,
        is_playing=True,
        is_paused=False,
        current_sound="now.mp3",
        current_requester="web-user",
        muted=True,
        mute_remaining_seconds=90,
        updated_at=datetime(2026, 4, 23, 12, 1, 0),
    )

    service = WebControlRoomService(repository=repository, db_path=str(db_path))
    payload = service.get_status({})

    assert payload["guild_id"] == 123
    assert payload["status"]["voice_connected"] is True
    assert payload["status"]["current_sound"] == "now.mp3"
    assert "queue" not in payload
    assert payload["mute"]["is_muted"] is True
    assert payload["mute"]["remaining_seconds"] == 90
