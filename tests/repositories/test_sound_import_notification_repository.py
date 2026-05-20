"""
Tests for bot/repositories/sound_import_notification.py -
SoundImportNotificationRepository.
"""

import pytest
from datetime import datetime


class TestSoundImportNotificationRepository:
    """Tests for the notification outbox repository."""

    def test_ensure_schema_creates_table(self, db_connection):
        """Schema creation should result in a usable sound_import_notifications table."""
        from bot.repositories.sound_import_notification import (
            SoundImportNotificationRepository,
        )
        from bot.repositories.base import BaseRepository

        BaseRepository.set_shared_connection(db_connection, ":memory:")
        try:
            repo = SoundImportNotificationRepository(use_shared=True)
            # Table should exist after ensure_schema()
            cursor = db_connection.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sound_import_notifications'"
            )
            assert cursor.fetchone() is not None
        finally:
            BaseRepository._shared_connection = None
            BaseRepository._shared_db_path = None

    def test_enqueue_and_get_pending(self, db_connection):
        """Enqueued notifications should appear as pending rows."""
        from bot.repositories.sound_import_notification import (
            SoundImportNotificationRepository,
        )
        from bot.repositories.base import BaseRepository

        BaseRepository.set_shared_connection(db_connection, ":memory:")
        try:
            repo = SoundImportNotificationRepository(use_shared=True)

            nid = repo.enqueue(
                guild_id=42,
                filename="test.mp3",
                source="web_upload",
                requester_username="TestUser",
                accent_color="#5865F2",
            )
            assert nid > 0

            pending = repo.get_pending()
            assert len(pending) == 1
            row = pending[0]
            assert row["filename"] == "test.mp3"
            assert row["source"] == "web_upload"
            assert row["requester_username"] == "TestUser"
            assert row["accent_color"] == "#5865F2"
            assert str(row["guild_id"]) == "42"
            assert row["sent_at"] is None
            assert row["attempts"] == 0
        finally:
            BaseRepository._shared_connection = None
            BaseRepository._shared_db_path = None

    def test_get_pending_excludes_sent(self, db_connection):
        """Marked-sent notifications should no longer appear as pending."""
        from bot.repositories.sound_import_notification import (
            SoundImportNotificationRepository,
        )
        from bot.repositories.base import BaseRepository

        BaseRepository.set_shared_connection(db_connection, ":memory:")
        try:
            repo = SoundImportNotificationRepository(use_shared=True)

            nid = repo.enqueue(
                guild_id=None,
                filename="a.mp3",
                source="scraper",
                requester_username="Bot",
            )
            repo.mark_sent(nid)

            pending = repo.get_pending()
            assert len(pending) == 0
        finally:
            BaseRepository._shared_connection = None
            BaseRepository._shared_db_path = None

    def test_get_pending_excludes_exhausted_attempts(self, db_connection):
        """Notifications with attempts >= 5 should be excluded from pending."""
        from bot.repositories.sound_import_notification import (
            SoundImportNotificationRepository,
        )
        from bot.repositories.base import BaseRepository

        BaseRepository.set_shared_connection(db_connection, ":memory:")
        try:
            repo = SoundImportNotificationRepository(use_shared=True)

            nid = repo.enqueue(
                guild_id=None,
                filename="b.mp3",
                source="web_upload",
                requester_username="User",
            )
            # Simulate 5 failed delivery attempts.
            for _ in range(5):
                repo.mark_failed(nid, "test error")

            pending = repo.get_pending()
            assert len(pending) == 0

            # Verify attempts counter and last_error
            row = repo.get_by_id(nid)
            assert row["attempts"] == 5
            assert row["last_error"] == "test error"
        finally:
            BaseRepository._shared_connection = None
            BaseRepository._shared_db_path = None

    def test_mark_failed_increments_attempts(self, db_connection):
        """mark_failed should increment attempts and record the error."""
        from bot.repositories.sound_import_notification import (
            SoundImportNotificationRepository,
        )
        from bot.repositories.base import BaseRepository

        BaseRepository.set_shared_connection(db_connection, ":memory:")
        try:
            repo = SoundImportNotificationRepository(use_shared=True)

            nid = repo.enqueue(
                guild_id=7,
                filename="c.mp3",
                source="favorite_watcher",
                requester_username="Watcher",
            )
            repo.mark_failed(nid, "connection timeout")

            row = repo.get_by_id(nid)
            assert row["attempts"] == 1
            assert row["last_error"] == "connection timeout"
            assert row["sent_at"] is None  # Not marked as sent
        finally:
            BaseRepository._shared_connection = None
            BaseRepository._shared_db_path = None

    def test_get_pending_orders_by_oldest_first(self, db_connection):
        """Pending rows should be ordered by created_at ASC."""
        from bot.repositories.sound_import_notification import (
            SoundImportNotificationRepository,
        )
        from bot.repositories.base import BaseRepository

        BaseRepository.set_shared_connection(db_connection, ":memory:")
        try:
            repo = SoundImportNotificationRepository(use_shared=True)

            nid1 = repo.enqueue(
                guild_id=None,
                filename="first.mp3",
                source="web_upload",
                requester_username="A",
            )
            nid2 = repo.enqueue(
                guild_id=None,
                filename="second.mp3",
                source="web_upload",
                requester_username="B",
            )

            pending = repo.get_pending(limit=10)
            assert len(pending) == 2
            assert pending[0]["id"] <= pending[1]["id"]
        finally:
            BaseRepository._shared_connection = None
            BaseRepository._shared_db_path = None
