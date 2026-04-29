"""
Tests for TikTok favorite collection watcher service behavior.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from bot.services.favorite_watcher import FavoriteCollectionVideo, FavoriteWatcherService


class FakeFavoriteWatcherRepository:
    """In-memory watcher repository for service tests."""

    def __init__(self) -> None:
        self.watchers = []
        self.known: dict[int, dict[str, dict]] = {}
        self.next_id = 1
        self.marked_checked = []

    def add_watcher(self, *, url, guild_id, added_by_user_id, added_by_username):
        """Add a fake watcher."""
        watcher_id = self.next_id
        self.next_id += 1
        self.watchers.append(
            {
                "id": watcher_id,
                "url": url,
                "guild_id": str(guild_id) if guild_id is not None else None,
                "added_by_user_id": str(added_by_user_id) if added_by_user_id is not None else None,
                "added_by_username": added_by_username,
            }
        )
        self.known[watcher_id] = {}
        return watcher_id

    def list_watchers(self, guild_id):
        """List fake watchers."""
        return self.watchers

    def remove_watcher(self, watcher_id, guild_id):
        """Remove a fake watcher."""
        return True

    def get_enabled_watchers(self):
        """Return fake enabled watchers."""
        return self.watchers

    def get_known_video_ids(self, watcher_id):
        """Return fake known video IDs."""
        return set(self.known[watcher_id].keys())

    def record_video_seen(
        self,
        *,
        watcher_id,
        video_id,
        video_url,
        imported_at=None,
        sound_filename=None,
    ):
        """Record a fake seen video."""
        self.known.setdefault(watcher_id, {})[video_id] = {
            "video_url": video_url,
            "imported_at": imported_at,
            "sound_filename": sound_filename,
        }

    def mark_checked(self, watcher_id):
        """Record that a fake watcher was checked."""
        self.marked_checked.append(watcher_id)


@pytest.mark.asyncio
async def test_add_watcher_seeds_current_collection_without_importing():
    """Adding a watcher should baseline existing videos and avoid importing them."""
    repo = FakeFavoriteWatcherRepository()
    sound_service = Mock()
    sound_service.import_sound_from_video = AsyncMock()
    service = FavoriteWatcherService(sound_service, watcher_repo=repo, action_repo=Mock())
    service.fetch_collection_videos = AsyncMock(
        return_value=[
            FavoriteCollectionVideo("111", "https://www.tiktok.com/@u/video/111"),
            FavoriteCollectionVideo("222", "https://www.tiktok.com/@u/video/222"),
        ]
    )

    watcher_id, seeded_count = await service.add_watcher(
        url="https://www.tiktok.com/@u/collection/bot-123",
        guild_id=42,
        added_by_user_id=7,
        added_by_username="Admin",
    )

    assert watcher_id == 1
    assert seeded_count == 2
    assert repo.get_known_video_ids(watcher_id) == {"111", "222"}
    assert repo.marked_checked == [1]
    sound_service.import_sound_from_video.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_once_imports_only_videos_missing_from_baseline():
    """Polling should import new collection entries and leave known baseline videos alone."""
    repo = FakeFavoriteWatcherRepository()
    watcher_id = repo.add_watcher(
        url="https://www.tiktok.com/@u/collection/bot-123",
        guild_id=42,
        added_by_user_id=7,
        added_by_username="Admin",
    )
    repo.record_video_seen(
        watcher_id=watcher_id,
        video_id="111",
        video_url="https://www.tiktok.com/@u/video/111",
    )
    sound_service = Mock()
    sound_service.import_sound_from_video = AsyncMock(return_value="/sounds/new sound.mp3")
    action_repo = Mock()
    behavior = Mock()
    behavior.send_message = AsyncMock()
    service = FavoriteWatcherService(
        sound_service,
        behavior=behavior,
        watcher_repo=repo,
        action_repo=action_repo,
    )
    service.fetch_collection_videos = AsyncMock(
        return_value=[
            FavoriteCollectionVideo("222", "https://www.tiktok.com/@u/video/222"),
            FavoriteCollectionVideo("111", "https://www.tiktok.com/@u/video/111"),
        ]
    )

    imported_count = await service.poll_once()

    assert imported_count == 1
    sound_service.import_sound_from_video.assert_awaited_once_with(
        "https://www.tiktok.com/@u/video/222",
        guild_id=42,
    )
    assert repo.get_known_video_ids(watcher_id) == {"111", "222"}
    assert repo.known[watcher_id]["222"]["sound_filename"] == "new sound.mp3"
    action_repo.insert.assert_called_once_with(
        "favorite_watcher",
        "favorite_watcher_import",
        "new sound.mp3",
        guild_id=42,
    )
    behavior.send_message.assert_awaited_once()
    _, kwargs = behavior.send_message.await_args
    assert kwargs["title"] == "🎵 New favorite sound imported: new sound.mp3"
    assert kwargs["message_format"] == "image"
    assert kwargs["image_requester"] == "Favorite Watcher"
    assert kwargs["image_border_color"] == "#ED4245"
    assert kwargs["view"].children


def test_fetch_collection_videos_reconstructs_flat_tiktok_entry_urls():
    """Flat yt-dlp entries should become usable TikTok video URLs."""
    service = FavoriteWatcherService(Mock(), watcher_repo=Mock(), action_repo=Mock())

    with patch("bot.services.favorite_watcher.yt_dlp.YoutubeDL") as mock_ydl:
        mock_ydl.return_value.__enter__.return_value.extract_info.return_value = {
            "entries": [{"id": "745", "url": "745"}]
        }

        videos = service._fetch_collection_videos_sync(
            "https://www.tiktok.com/@hablala2/collection/bot-123"
        )

    assert videos == [
        FavoriteCollectionVideo(
            video_id="745",
            url="https://www.tiktok.com/@hablala2/video/745",
        )
    ]
