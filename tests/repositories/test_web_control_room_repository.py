from datetime import datetime

from bot.repositories.web_control_room import WebControlRoomRepository


def test_upsert_status_and_get_status(tmp_path):
    db_path = tmp_path / "control_room.db"

    repository = WebControlRoomRepository(db_path=str(db_path), use_shared=False)
    repository.upsert_status(
        guild_id=123,
        guild_name="Guild",
        voice_connected=True,
        voice_channel_id=456,
        voice_channel_name="Voice",
        voice_member_count=2,
        voice_members=[
            {"id": "1", "name": "Gabi", "avatar_url": "https://cdn.example/gabi.png"},
            {"id": "2", "name": "Diogo", "avatar_url": ""},
        ],
        is_playing=True,
        is_paused=False,
        current_sound="now.mp3",
        current_requester="gabi",
        current_duration_seconds=12.5,
        current_elapsed_seconds=4.0,
        muted=False,
        mute_remaining_seconds=0,
        updated_at=datetime(2026, 4, 23, 12, 1, 0),
    )

    status = repository.get_status(123)

    assert status["guild_name"] == "Guild"
    assert status["voice_connected"] == 1
    assert status["current_sound"] == "now.mp3"
    assert status["current_duration_seconds"] == 12.5
    assert status["current_elapsed_seconds"] == 4.0
    assert "Gabi" in status["voice_members"]
