"""
Tests for bot/repositories/favorite_watcher.py - FavoriteWatcherRepository.
"""

import pytest

from bot.repositories.favorite_watcher import FavoriteWatcherRepository


class TestClaimVideoSeen:
    """Tests for FavoriteWatcherRepository.claim_video_seen()."""

    def test_claim_returns_true_for_new_video(self, db_connection):
        """A first-time claim must return True."""
        from bot.repositories.base import BaseRepository

        BaseRepository.set_shared_connection(db_connection, ":memory:")
        try:
            repo = FavoriteWatcherRepository(use_shared=True)
            watcher_id = repo.add_watcher(
                url="https://www.tiktok.com/@u/collection/test-123",
                guild_id=42,
                added_by_user_id=7,
                added_by_username="Test",
            )

            result = repo.claim_video_seen(
                watcher_id=watcher_id,
                video_id="vid001",
                video_url="https://www.tiktok.com/@u/video/001",
            )

            assert result is True

            # Row must be in the database.
            rows = repo._execute(
                "SELECT video_id, imported_at, sound_filename FROM favorite_watcher_videos WHERE watcher_id = ?",
                (watcher_id,),
            )
            assert len(rows) == 1
            assert rows[0]["video_id"] == "vid001"
            assert rows[0]["imported_at"] is None
            assert rows[0]["sound_filename"] is None
        finally:
            BaseRepository._shared_connection = None
            BaseRepository._shared_db_path = None

    def test_claim_returns_false_for_duplicate(self, db_connection):
        """Claiming the same video_id again must return False."""
        from bot.repositories.base import BaseRepository

        BaseRepository.set_shared_connection(db_connection, ":memory:")
        try:
            repo = FavoriteWatcherRepository(use_shared=True)
            watcher_id = repo.add_watcher(
                url="https://www.tiktok.com/@u/collection/test-123",
                guild_id=42,
                added_by_user_id=7,
                added_by_username="Test",
            )

            # First claim — should succeed.
            first = repo.claim_video_seen(
                watcher_id=watcher_id,
                video_id="vid001",
                video_url="https://www.tiktok.com/@u/video/001",
            )
            assert first is True

            # Second claim — must return False (UNIQUE constraint hit).
            second = repo.claim_video_seen(
                watcher_id=watcher_id,
                video_id="vid001",
                video_url="https://www.tiktok.com/@u/video/001",
            )
            assert second is False

            # Only one row exists.
            rows = repo._execute(
                "SELECT COUNT(*) AS cnt FROM favorite_watcher_videos WHERE watcher_id = ?",
                (watcher_id,),
            )
            assert rows[0]["cnt"] == 1
        finally:
            BaseRepository._shared_connection = None
            BaseRepository._shared_db_path = None

    def test_claim_then_record_video_seen_updates_metadata(self, db_connection):
        """After a claim, record_video_seen should update imported_at/filename."""
        from bot.repositories.base import BaseRepository

        BaseRepository.set_shared_connection(db_connection, ":memory:")
        try:
            repo = FavoriteWatcherRepository(use_shared=True)
            watcher_id = repo.add_watcher(
                url="https://www.tiktok.com/@u/collection/test-123",
                guild_id=42,
                added_by_user_id=7,
                added_by_username="Test",
            )

            # Claim
            assert repo.claim_video_seen(
                watcher_id=watcher_id,
                video_id="vid001",
                video_url="https://www.tiktok.com/@u/video/001",
            ) is True

            # Then update metadata
            repo.record_video_seen(
                watcher_id=watcher_id,
                video_id="vid001",
                video_url="https://www.tiktok.com/@u/video/001",
                imported_at="2026-01-01 12:00:00",
                sound_filename="cool_sound.mp3",
            )

            rows = repo._execute(
                "SELECT imported_at, sound_filename FROM favorite_watcher_videos WHERE watcher_id = ? AND video_id = ?",
                (watcher_id, "vid001"),
            )
            assert len(rows) == 1
            assert rows[0]["imported_at"] == "2026-01-01 12:00:00"
            assert rows[0]["sound_filename"] == "cool_sound.mp3"
        finally:
            BaseRepository._shared_connection = None
            BaseRepository._shared_db_path = None

    def test_claim_separate_watchers_independent(self, db_connection):
        """Claims for different watchers with the same video_id must not interfere."""
        from bot.repositories.base import BaseRepository

        BaseRepository.set_shared_connection(db_connection, ":memory:")
        try:
            repo = FavoriteWatcherRepository(use_shared=True)
            w1 = repo.add_watcher(url="https://tiktok.com/@a/collection/x", guild_id=1, added_by_user_id=1, added_by_username="A")
            w2 = repo.add_watcher(url="https://tiktok.com/@b/collection/y", guild_id=2, added_by_user_id=2, added_by_username="B")

            assert repo.claim_video_seen(watcher_id=w1, video_id="same_vid", video_url="https://tiktok.com/@a/video/same_vid") is True
            assert repo.claim_video_seen(watcher_id=w2, video_id="same_vid", video_url="https://tiktok.com/@b/video/same_vid") is True

            rows = repo._execute(
                "SELECT watcher_id, video_id FROM favorite_watcher_videos ORDER BY watcher_id",
            )
            assert len(rows) == 2
        finally:
            BaseRepository._shared_connection = None
            BaseRepository._shared_db_path = None
