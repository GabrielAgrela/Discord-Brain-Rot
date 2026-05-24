"""
Tests for bot/repositories/speech_training.py - SpeechTrainingRepository.
"""

import sqlite3

import pytest


class TestSpeechTrainingRepository:
    """Tests for the SpeechTrainingRepository class."""

    @pytest.fixture
    def db_connection(self):
        """Create an in-memory SQLite database."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        yield conn
        conn.close()

    @pytest.fixture
    def repo(self, db_connection):
        """Create a SpeechTrainingRepository with the test DB."""
        from bot.repositories.base import BaseRepository
        from bot.repositories.speech_training import SpeechTrainingRepository

        BaseRepository.set_shared_connection(db_connection, ":memory:")
        repo = SpeechTrainingRepository(use_shared=True)
        repo.ensure_schema()
        yield repo
        BaseRepository._shared_connection = None
        BaseRepository._shared_db_path = None

    def _insert_sample_clips(self, repo):
        ids = []
        id1 = repo.insert_clip(
            guild_id="100", user_id="1", username="user1",
            display_name="User One", folder_name="user1_1",
            filename="clip1.mp3", relative_path="100/user1_1/clip1.mp3",
            duration_seconds=1.5, byte_size=30000,
        )
        ids.append(id1)
        id2 = repo.insert_clip(
            guild_id="100", user_id="1", username="user1",
            display_name="User One", folder_name="user1_1",
            filename="clip2.mp3", relative_path="100/user1_1/clip2.mp3",
            duration_seconds=2.0, byte_size=40000,
        )
        ids.append(id2)
        id3 = repo.insert_clip(
            guild_id="100", user_id="2", username="user2",
            display_name="User Two", folder_name="user2_2",
            filename="clip3.mp3", relative_path="100/user2_2/clip3.mp3",
            duration_seconds=0.8, byte_size=16000,
        )
        ids.append(id3)
        id4 = repo.insert_clip(
            guild_id="200", user_id="3", username="user3",
            display_name="User Three", folder_name="user3_3",
            filename="clip4.mp3", relative_path="200/user3_3/clip4.mp3",
            duration_seconds=3.0, byte_size=60000,
        )
        ids.append(id4)
        return ids

    # ── ensure_schema ─────────────────────────────────────────────────

    def test_ensure_schema_creates_table(self):
        """Test that ensure_schema creates the table and indexes."""
        from bot.repositories.base import BaseRepository
        # Clear any shared connection state
        BaseRepository._shared_connection = None
        BaseRepository._shared_db_path = None

        from bot.repositories.speech_training import SpeechTrainingRepository
        import tempfile, os
        # Use a temp file so ensure_schema persists across connections
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            repo = SpeechTrainingRepository(db_path=tmp_path, use_shared=False)
            repo.ensure_schema()

            # Verify via its own connection
            row = repo._execute_one(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='speech_training_clips'"
            )
            assert row is not None, "speech_training_clips table should exist"
        finally:
            os.unlink(tmp_path)

    # ── insert_clip ───────────────────────────────────────────────────

    def test_insert_clip(self, repo):
        """Test inserting a clip returns an ID."""
        cid = repo.insert_clip(
            guild_id="100", user_id="1", username="testuser",
            display_name="Test User", folder_name="testuser_1",
            filename="test.mp3", relative_path="100/testuser_1/test.mp3",
            duration_seconds=1.0, byte_size=20000,
        )
        assert cid > 0

    def test_insert_clip_unique_relative_path(self, repo):
        """Test that duplicate relative_path raises integrity error."""
        repo.insert_clip(
            guild_id="100", user_id="1", username="testuser",
            display_name="Test User", folder_name="testuser_1",
            filename="test.mp3", relative_path="path/test.mp3",
            duration_seconds=1.0, byte_size=20000,
        )
        with pytest.raises(sqlite3.IntegrityError):
            repo.insert_clip(
                guild_id="100", user_id="1", username="testuser",
                display_name="Test User", folder_name="testuser_1",
                filename="test.mp3", relative_path="path/test.mp3",
                duration_seconds=1.0, byte_size=20000,
            )

    # ── list_users ────────────────────────────────────────────────────

    def test_list_users(self, repo):
        """Test listing users with aggregation."""
        ids = self._insert_sample_clips(repo)
        users = repo.list_users()
        # user1: 2 clips, user2: 1 clip, user3: 1 clip (different guild)
        assert len(users) == 3
        u1 = [u for u in users if u["user_id"] == "1"][0]
        assert u1["total_count"] == 2
        assert u1["unlabeled_count"] == 2

    def test_list_users_guild_filter(self, repo):
        """Test filtering users by guild."""
        ids = self._insert_sample_clips(repo)
        users = repo.list_users(guild_id="100")
        assert len(users) == 2
        users = repo.list_users(guild_id="200")
        assert len(users) == 1
        users = repo.list_users(guild_id="999")
        assert len(users) == 0

    # ── list_clips ────────────────────────────────────────────────────

    def test_list_clips(self, repo):
        """Test listing clips with pagination."""
        ids = self._insert_sample_clips(repo)
        items, total = repo.list_clips(page=1, per_page=2)
        assert total == 4
        assert len(items) <= 2

    def test_list_clips_guild_filter(self, repo):
        """Test filtering clips by guild."""
        ids = self._insert_sample_clips(repo)
        items, total = repo.list_clips(guild_id="100")
        assert total == 3

    def test_list_clips_user_filter(self, repo):
        """Test filtering clips by user."""
        ids = self._insert_sample_clips(repo)
        items, total = repo.list_clips(user_id="1")
        assert total == 2

    def test_list_clips_label_filter_unlabeled(self, repo):
        """Test filtering clips by unlabeled (label is NULL)."""
        ids = self._insert_sample_clips(repo)
        items, total = repo.list_clips(label="unlabeled")
        assert total == 4

    def test_list_clips_label_filter_specific(self, repo):
        """Test filtering clips by specific label."""
        ids = self._insert_sample_clips(repo)
        # Update one clip's label
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'chapada' WHERE id = ?",
            (ids[0],),
        )
        items, total = repo.list_clips(label="chapada")
        assert total == 1

    def test_list_clips_search(self, repo):
        """Test searching clips by filename."""
        ids = self._insert_sample_clips(repo)
        items, total = repo.list_clips(search="clip1")
        assert total == 1

    def test_list_clips_sort_newest(self, repo):
        """Test sorting by newest first (default)."""
        ids = self._insert_sample_clips(repo)
        items, total = repo.list_clips(sort_by="captured_at", sort_dir="desc")
        assert total == 4
        # IDs are inserted in order, newest first (same captured_at default)
        # But they all use the same default CURRENT_TIMESTAMP, so order by id desc
        timestamps = [item["captured_at"] for item in items]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_list_clips_sort_duration(self, repo):
        """Test sorting by duration."""
        ids = self._insert_sample_clips(repo)
        items, total = repo.list_clips(sort_by="duration_seconds", sort_dir="asc")
        assert total == 4
        durations = [item["duration_seconds"] for item in items]
        assert durations == sorted(durations)

    def test_list_clips_sort_label_asc(self, repo):
        """Test sorting by label ascending (unlabeled last)."""
        ids = self._insert_sample_clips(repo)
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'chapada' WHERE id = ?",
            (ids[0],),
        )
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'ventura' WHERE id = ?",
            (ids[1],),
        )
        items, total = repo.list_clips(sort_by="label", sort_dir="asc")
        assert total == 4
        # First items should be labeled (CASE gives labeled=0, unlabeled=1; 0 < 1)
        labeled = [item["label"] for item in items if item["label"]]
        assert labeled == sorted(labeled)
        # Last items should be unlabeled
        unlabeled = [item for item in items if not item["label"]]
        assert len(unlabeled) == 2

    # ── list_clip_ids ─────────────────────────────────────────────────

    def test_list_clip_ids_all(self, repo):
        """Test listing all clip IDs without pagination."""
        ids = self._insert_sample_clips(repo)
        result = repo.list_clip_ids()
        assert sorted(result) == sorted(ids)
        assert len(result) == len(ids)

    def test_list_clip_ids_guild_filter(self, repo):
        """Test filtering clip IDs by guild."""
        ids = self._insert_sample_clips(repo)
        result = repo.list_clip_ids(guild_id="100")
        # ids[0], ids[1], ids[2] are guild 100
        assert sorted(result) == sorted(ids[:3])
        assert len(result) == 3

    def test_list_clip_ids_user_filter(self, repo):
        """Test filtering clip IDs by user."""
        ids = self._insert_sample_clips(repo)
        result = repo.list_clip_ids(user_id="1")
        # ids[0], ids[1] are user 1
        assert sorted(result) == sorted(ids[:2])
        assert len(result) == 2

    def test_list_clip_ids_unpaginated(self, repo):
        """Test that list_clip_ids returns all matching IDs regardless of page size."""
        ids = self._insert_sample_clips(repo)
        # Add more clips to exceed any reasonable per_page boundary
        extra_ids = []
        for i in range(5):
            cid = repo.insert_clip(
                guild_id="100", user_id="1", username="user1",
                display_name="User One", folder_name="user1_1",
                filename=f"extra_{i}.mp3",
                relative_path=f"100/user1_1/extra_{i}.mp3",
                duration_seconds=1.0, byte_size=10000,
            )
            extra_ids.append(cid)
        all_ids = ids + extra_ids
        result = repo.list_clip_ids(guild_id="100")
        assert len(result) == len(all_ids) - 1  # minus guild 200 clip
        assert sorted(result) == sorted(all_ids[:3] + extra_ids)

    def test_list_clip_ids_search(self, repo):
        """Test searching clip IDs by filename."""
        ids = self._insert_sample_clips(repo)
        result = repo.list_clip_ids(search="clip1")
        assert result == [ids[0]]

    def test_list_clip_ids_no_match(self, repo):
        """Test clip IDs returns empty list when no clips match."""
        result = repo.list_clip_ids(search="nonexistent")
        assert result == []

    def test_list_clip_ids_sort(self, repo):
        """Test that clip IDs respect sort order."""
        ids = self._insert_sample_clips(repo)
        result = repo.list_clip_ids(sort_by="duration_seconds", sort_dir="asc")
        # durations: ids[0]=1.5, ids[1]=2.0, ids[2]=0.8, ids[3]=3.0
        # sorted asc by duration -> ids[2], ids[0], ids[1], ids[3]
        expected_order = [ids[2], ids[0], ids[1], ids[3]]
        assert result == expected_order

    def test_list_clip_ids_sort_label_desc(self, repo):
        """Test sorting by label descending (unlabeled first)."""
        ids = self._insert_sample_clips(repo)
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'chapada' WHERE id = ?",
            (ids[0],),
        )
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'ventura' WHERE id = ?",
            (ids[1],),
        )
        items, total = repo.list_clips(sort_by="label", sort_dir="desc")
        assert total == 4
        # First items should be unlabeled (CASE gives unlabeled=1, labeled=0; 1 > 0 with desc)
        unlabeled = [item for item in items if not item["label"]]
        assert len(unlabeled) == 2
        # First two should be unlabeled
        assert items[0]["label"] is None or items[0]["label"] == ""
        assert items[1]["label"] is None or items[1]["label"] == ""

    # ── get_clip ──────────────────────────────────────────────────────

    def test_get_clip(self, repo):
        """Test getting a single clip."""
        ids = self._insert_sample_clips(repo)
        clip = repo.get_clip(ids[0])
        assert clip is not None
        assert clip["user_id"] == "1"
        assert clip["filename"] == "clip1.mp3"

    def test_get_clip_not_found(self, repo):
        """Test getting a non-existent clip."""
        clip = repo.get_clip(99999)
        assert clip is None

    # ── update_review ─────────────────────────────────────────────────

    def test_update_review(self, repo):
        """Test updating the review of a clip."""
        ids = self._insert_sample_clips(repo)
        ok = repo.update_review(
            clip_id=ids[0],
            label="chapada",
            transcript="chapada test",
            notes="good clip",
            reviewer_user_id="99",
            reviewer_username="reviewer",
        )
        assert ok is True
        clip = repo.get_clip(ids[0])
        assert clip["label"] == "chapada"
        assert clip["transcript"] == "chapada test"
        assert clip["reviewed_by_user_id"] == "99"

    def test_update_review_clear_label(self, repo):
        """Test clearing the label."""
        ids = self._insert_sample_clips(repo)
        repo.update_review(
            clip_id=ids[0], label="chapada", transcript="",
            notes="", reviewer_user_id="99", reviewer_username="reviewer",
        )
        clip = repo.get_clip(ids[0])
        assert clip["label"] == "chapada"

        # Clear it
        repo.update_review(
            clip_id=ids[0], label="", transcript="",
            notes="", reviewer_user_id="99", reviewer_username="reviewer",
        )
        clip = repo.get_clip(ids[0])
        assert clip["label"] is None

    def test_update_review_not_found(self, repo):
        """Test updating a non-existent clip."""
        ok = repo.update_review(
            clip_id=99999, label="chapada", transcript="",
            notes="", reviewer_user_id="99", reviewer_username="reviewer",
        )
        assert ok is False

    # ── delete_clip ───────────────────────────────────────────────────

    def test_delete_clip(self, repo):
        """Test deleting a clip returns its metadata."""
        ids = self._insert_sample_clips(repo)
        deleted = repo.delete_clip(ids[0])
        assert deleted is not None
        assert deleted["id"] == ids[0]
        assert deleted["filename"] == "clip1.mp3"
        # Verify it's gone
        clip = repo.get_clip(ids[0])
        assert clip is None

    def test_delete_clip_not_found(self, repo):
        """Test deleting a non-existent clip returns None."""
        result = repo.delete_clip(99999)
        assert result is None

    # ── bulk_update_review ────────────────────────────────────────────

    def test_bulk_update_review(self, repo):
        """Test bulk label update."""
        ids = self._insert_sample_clips(repo)
        updated = repo.bulk_update_review(
            clip_ids=[ids[0], ids[1]],
            label="chapada",
            reviewer_user_id="99",
            reviewer_username="reviewer",
        )
        assert updated == 2
        clip1 = repo.get_clip(ids[0])
        clip2 = repo.get_clip(ids[1])
        assert clip1["label"] == "chapada"
        assert clip2["label"] == "chapada"
        # Third clip should be unchanged
        clip3 = repo.get_clip(ids[2])
        assert clip3["label"] is None

    def test_bulk_update_review_empty_ids(self, repo):
        """Test bulk update with empty ids returns 0."""
        updated = repo.bulk_update_review(
            clip_ids=[], label="chapada",
            reviewer_user_id="99", reviewer_username="reviewer",
        )
        assert updated == 0

    # ── bulk_delete_clips ─────────────────────────────────────────────

    def test_bulk_delete_clips(self, repo):
        """Test bulk delete returns deleted row metadata."""
        ids = self._insert_sample_clips(repo)
        deleted = repo.bulk_delete_clips([ids[0], ids[2]])
        assert len(deleted) == 2
        assert {d["id"] for d in deleted} == {ids[0], ids[2]}
        # Verify they are gone
        assert repo.get_clip(ids[0]) is None
        assert repo.get_clip(ids[1]) is not None
        assert repo.get_clip(ids[2]) is None

    def test_bulk_delete_clips_empty_ids(self, repo):
        """Test bulk delete with empty ids returns empty list."""
        result = repo.bulk_delete_clips([])
        assert result == []

    def test_bulk_delete_clips_not_found(self, repo):
        """Test bulk delete with non-existent ids returns empty."""
        result = repo.bulk_delete_clips([99999, 99998])
        assert result == []

    # ── get_storage_summary ───────────────────────────────────────────

    def test_get_storage_summary_all(self, repo):
        """Test storage summary across all guilds."""
        ids = self._insert_sample_clips(repo)
        summary = repo.get_storage_summary()
        # 4 clips: 30000 + 40000 + 16000 + 60000 = 146000 bytes
        assert summary["total_bytes"] == 146000
        assert summary["clip_count"] == 4

    def test_get_storage_summary_guild_filter(self, repo):
        """Test storage summary scoped to a guild."""
        ids = self._insert_sample_clips(repo)
        summary = repo.get_storage_summary(guild_id="100")
        # 3 clips: 30000 + 40000 + 16000 = 86000 bytes
        assert summary["total_bytes"] == 86000
        assert summary["clip_count"] == 3

        summary = repo.get_storage_summary(guild_id="200")
        assert summary["total_bytes"] == 60000
        assert summary["clip_count"] == 1

    def test_get_storage_summary_empty(self, repo):
        """Test storage summary with no clips returns zeros."""
        summary = repo.get_storage_summary()
        assert summary["total_bytes"] == 0
        assert summary["clip_count"] == 0

    def test_get_storage_summary_no_match(self, repo):
        """Test storage summary for non-existent guild returns zeros."""
        ids = self._insert_sample_clips(repo)
        summary = repo.get_storage_summary(guild_id="999")
        assert summary["total_bytes"] == 0
        assert summary["clip_count"] == 0

    # ── list_unlabeled_clips ──────────────────────────────────────────

    def test_list_unlabeled_clips_all(self, repo):
        """Return all unlabeled clips across guilds."""
        ids = self._insert_sample_clips(repo)
        clips = repo.list_unlabeled_clips()
        # All 4 clips are inserted without labels
        assert len(clips) == 4

    def test_list_unlabeled_clips_guild_filter(self, repo):
        """Filter unlabeled clips by guild."""
        ids = self._insert_sample_clips(repo)
        clips = repo.list_unlabeled_clips(guild_id="100")
        assert len(clips) == 3
        clips = repo.list_unlabeled_clips(guild_id="200")
        assert len(clips) == 1

    def test_list_unlabeled_clips_user_filter(self, repo):
        """Filter unlabeled clips by user."""
        ids = self._insert_sample_clips(repo)
        clips = repo.list_unlabeled_clips(user_id="1")
        assert len(clips) == 2
        clips = repo.list_unlabeled_clips(user_id="2")
        assert len(clips) == 1

    def test_list_unlabeled_clips_excludes_labeled(self, repo):
        """Labeled clips should not appear in unlabeled results."""
        ids = self._insert_sample_clips(repo)
        # Label one clip
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'chapada' WHERE id = ?",
            (ids[0],),
        )
        clips = repo.list_unlabeled_clips()
        assert len(clips) == 3

    def test_list_unlabeled_clips_guild_and_user(self, repo):
        """Combine guild and user filter."""
        ids = self._insert_sample_clips(repo)
        clips = repo.list_unlabeled_clips(guild_id="100", user_id="1")
        assert len(clips) == 2
        for c in clips:
            assert c["guild_id"] == "100"
            assert c["user_id"] == "1"

    def test_list_unlabeled_clips_max_duration_inclusive(self, repo):
        """max_duration_seconds includes clips exactly at the boundary."""
        self._insert_sample_clips(repo)
        # Clip durations: 1.5, 2.0, 0.8, 3.0
        clips = repo.list_unlabeled_clips(max_duration_seconds=2.0)
        assert len(clips) == 3  # 1.5, 2.0, 0.8
        for c in clips:
            assert c["duration_seconds"] <= 2.0

    def test_list_unlabeled_clips_max_duration_excludes_long(self, repo):
        """max_duration_seconds excludes clips longer than the boundary."""
        self._insert_sample_clips(repo)
        clips = repo.list_unlabeled_clips(max_duration_seconds=1.0)
        assert len(clips) == 1  # only 0.8
        assert clips[0]["duration_seconds"] == 0.8

    def test_list_unlabeled_clips_max_duration_combined_with_filters(self, repo):
        """max_duration_seconds works together with guild/user filters."""
        self._insert_sample_clips(repo)
        clips = repo.list_unlabeled_clips(
            guild_id="100",
            max_duration_seconds=2.0,
        )
        # Guild 100 clips: 1.5, 2.0, 0.8 → all ≤2.0
        assert len(clips) == 3

        clips = repo.list_unlabeled_clips(
            guild_id="100",
            max_duration_seconds=1.0,
        )
        # Guild 100 clips ≤1.0: only 0.8
        assert len(clips) == 1
        assert clips[0]["duration_seconds"] == 0.8

    # ── 'unclear' treated as unlabeled ───────────────────────────────

    def test_list_users_unlabeled_count_includes_unclear(self, repo):
        """Unlabeled count includes clips with label='unclear'."""
        ids = self._insert_sample_clips(repo)
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'unclear' WHERE id = ?",
            (ids[0],),
        )
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'chapada' WHERE id = ?",
            (ids[1],),
        )
        users = repo.list_users()
        u1 = [u for u in users if u["user_id"] == "1"][0]
        # user1 has ids[0] (unclear), ids[1] (chapada). unlabeled_count should be 1 (unclear)
        assert u1["unlabeled_count"] == 1

    def test_list_clips_unlabeled_includes_unclear(self, repo):
        """label='unlabeled' filter includes clips with label='unclear'."""
        ids = self._insert_sample_clips(repo)
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'unclear' WHERE id = ?",
            (ids[0],),
        )
        items, total = repo.list_clips(label="unlabeled")
        assert total >= 1
        # id[0] should appear in results
        clip_ids = [c["id"] for c in items]
        assert ids[0] in clip_ids

    def test_list_unlabeled_clips_includes_unclear(self, repo):
        """list_unlabeled_clips() returns clips with label='unclear'."""
        ids = self._insert_sample_clips(repo)
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'unclear' WHERE id = ?",
            (ids[0],),
        )
        clips = repo.list_unlabeled_clips()
        clip_ids = [c["id"] for c in clips]
        assert ids[0] in clip_ids

    def test_list_labels_excludes_unclear(self, repo):
        """list_labels() does not return 'unclear'."""
        ids = self._insert_sample_clips(repo)
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'unclear' WHERE id = ?",
            (ids[0],),
        )
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'chapada' WHERE id = ?",
            (ids[1],),
        )
        labels = repo.list_labels()
        assert 'unclear' not in labels
        assert 'chapada' in labels

    # ── list_labels ──────────────────────────────────────────────────

    def test_list_labels_empty(self, repo):
        """No labels returns empty list."""
        labels = repo.list_labels()
        assert labels == []

    def test_list_labels_distinct(self, repo):
        """Returns distinct non-empty labels."""
        ids = self._insert_sample_clips(repo)
        # Assign labels
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'chapada' WHERE id = ?",
            (ids[0],),
        )
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'ventura' WHERE id = ?",
            (ids[1],),
        )
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'chapada' WHERE id = ?",
            (ids[2],),
        )
        labels = repo.list_labels()
        assert len(labels) == 2
        assert 'chapada' in labels
        assert 'ventura' in labels

    def test_list_labels_excludes_empty_and_null(self, repo):
        """Empty string and NULL labels are excluded."""
        ids = self._insert_sample_clips(repo)
        # Leave some labels null/empty, set one to a real value
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'test_label' WHERE id = ?",
            (ids[0],),
        )
        labels = repo.list_labels()
        assert labels == ['test_label']

    def test_list_labels_guild_filter(self, repo):
        """Labels are scoped to guild when filter is provided."""
        ids = self._insert_sample_clips(repo)
        # ids[0] = guild 100, ids[3] = guild 200
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'chapada' WHERE id = ?",
            (ids[0],),
        )
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'ventura' WHERE id = ?",
            (ids[3],),
        )
        labels_g100 = repo.list_labels(guild_id="100")
        assert labels_g100 == ['chapada']
        labels_g200 = repo.list_labels(guild_id="200")
        assert labels_g200 == ['ventura']
        labels_all = repo.list_labels()
        assert len(labels_all) == 2

    def test_list_labels_case_insensitive_order(self, repo):
        """Labels are ordered case-insensitively."""
        ids = self._insert_sample_clips(repo)
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'Zebra' WHERE id = ?",
            (ids[0],),
        )
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'alpha' WHERE id = ?",
            (ids[1],),
        )
        repo._execute_write(
            "UPDATE speech_training_clips SET label = 'Beta' WHERE id = ?",
            (ids[2],),
        )
        labels = repo.list_labels()
        assert labels == ['alpha', 'Beta', 'Zebra']

    # ── list_empty_transcript_clips ───────────────────────────────────

    def test_list_empty_transcript_clips_all(self, repo):
        """Return all clips with empty transcript across guilds."""
        ids = self._insert_sample_clips(repo)
        clips = repo.list_empty_transcript_clips()
        # All 4 clips start without transcript
        assert len(clips) == 4

    def test_list_empty_transcript_clips_guild_filter(self, repo):
        """Filter empty-transcript clips by guild."""
        ids = self._insert_sample_clips(repo)
        clips = repo.list_empty_transcript_clips(guild_id="100")
        assert len(clips) == 3
        clips = repo.list_empty_transcript_clips(guild_id="200")
        assert len(clips) == 1

    def test_list_empty_transcript_clips_user_filter(self, repo):
        """Filter empty-transcript clips by user."""
        ids = self._insert_sample_clips(repo)
        clips = repo.list_empty_transcript_clips(user_id="1")
        assert len(clips) == 2
        clips = repo.list_empty_transcript_clips(user_id="2")
        assert len(clips) == 1

    def test_list_empty_transcript_clips_excludes_filled(self, repo):
        """Clips with non-empty transcript should not appear."""
        ids = self._insert_sample_clips(repo)
        repo._execute_write(
            "UPDATE speech_training_clips SET transcript = 'hello' WHERE id = ?",
            (ids[0],),
        )
        clips = repo.list_empty_transcript_clips()
        clip_ids = [c["id"] for c in clips]
        assert ids[0] not in clip_ids
        assert len(clips) == 3

    def test_list_empty_transcript_clips_guild_and_user(self, repo):
        """Combine guild and user filter."""
        ids = self._insert_sample_clips(repo)
        clips = repo.list_empty_transcript_clips(guild_id="100", user_id="1")
        assert len(clips) == 2
        for c in clips:
            assert c["guild_id"] == "100"
            assert c["user_id"] == "1"

    # ── update_transcript ─────────────────────────────────────────────

    def test_update_transcript(self, repo):
        """Test updating only the transcript."""
        ids = self._insert_sample_clips(repo)
        ok = repo.update_transcript(
            clip_id=ids[0],
            transcript="hello world",
        )
        assert ok is True
        clip = repo.get_clip(ids[0])
        assert clip["transcript"] == "hello world"
        assert clip["reviewed_by_username"] == "(auto-transcript)"

    def test_update_transcript_preserves_label_and_notes(self, repo):
        """Transcript-only update does not clear label or notes."""
        ids = self._insert_sample_clips(repo)
        # Set a label and notes
        repo.update_review(
            clip_id=ids[0],
            label="chapada",
            transcript="original",
            notes="original notes",
            reviewer_user_id="99",
            reviewer_username="reviewer",
        )
        # Now update only transcript
        ok = repo.update_transcript(
            clip_id=ids[0],
            transcript="new transcript",
        )
        assert ok is True
        clip = repo.get_clip(ids[0])
        assert clip["transcript"] == "new transcript"
        assert clip["label"] == "chapada"
        assert clip["notes"] == "original notes"

    def test_update_transcript_not_found(self, repo):
        """Update for non-existent clip returns False."""
        ok = repo.update_transcript(clip_id=99999, transcript="test")
        assert ok is False

    def test_update_transcript_dash_value(self, repo):
        """Store '-' as a transcript value (empty Whisper marker)."""
        ids = self._insert_sample_clips(repo)
        ok = repo.update_transcript(
            clip_id=ids[0],
            transcript="-",
        )
        assert ok is True
        clip = repo.get_clip(ids[0])
        assert clip["transcript"] == "-"
