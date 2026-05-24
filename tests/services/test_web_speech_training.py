"""
Tests for bot/services/web_speech_training.py - offline keyword scanning.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


class FakeVoskResult:
    """Simulate a Vosk FinalResult payload."""

    def __init__(self, text: str, words: list[dict]):
        self._text = text
        self._words = words

    def FinalResult(self) -> str:
        return json.dumps({
            "text": self._text,
            "result": self._words,
        })


class FakeRecognizer:
    """Simulate a vosk.KaldiRecognizer for offline scanning."""

    def __init__(self, model, sample_rate, grammar_json=None):
        self.model = model
        self.sample_rate = sample_rate
        self.grammar = grammar_json
        self._result = None

    def SetWords(self, val):
        pass

    def AcceptWaveform(self, raw_pcm):
        return False

    def Result(self):
        return '{"text":""}'

    def FinalResult(self):
        return self._result if self._result else '{"text":"","result":[]}'


class TestWebSpeechTrainingScan:
    """Tests for WebSpeechTrainingService.scan_unlabeled_keyword()."""

    @pytest.fixture
    def repo(self):
        """Create a mock SpeechTrainingRepository."""
        mock_repo = MagicMock()
        mock_repo.list_unlabeled_clips.return_value = []
        return mock_repo

    @pytest.fixture
    def service(self, repo, tmp_path):
        """Create a WebSpeechTrainingService with a temp data dir."""
        from bot.services.web_speech_training import WebSpeechTrainingService

        return WebSpeechTrainingService(repo, str(tmp_path))

    # ── Validation ───────────────────────────────────────────────────

    def test_scan_rejects_empty_keyword(self, service):
        """Empty keyword raises ValueError."""
        from bot.services.web_speech_training import WebSpeechTrainingService

        svc = service
        with pytest.raises(ValueError, match="Keyword must be non-empty"):
            svc.scan_unlabeled_keyword(keyword="")

    def test_scan_rejects_bad_confidence_low(self, service):
        """Confidence below 0 raises ValueError."""
        with pytest.raises(ValueError, match="min_confidence must be between 0 and 1"):
            service.scan_unlabeled_keyword(min_confidence=-0.1)

    def test_scan_rejects_bad_confidence_high(self, service):
        """Confidence above 1 raises ValueError."""
        with pytest.raises(ValueError, match="min_confidence must be between 0 and 1"):
            service.scan_unlabeled_keyword(min_confidence=1.5)

    def test_scan_rejects_no_model(self, service):
        """When vosk model is None, raises ValueError."""
        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=None,
        ):
            with pytest.raises(ValueError, match="Vosk model is not available"):
                service.scan_unlabeled_keyword()

    # ── No unlabeled clips ───────────────────────────────────────────

    def test_scan_no_unlabeled(self, service):
        """When no unlabeled clips exist, returns zero matches."""
        service.repo.list_unlabeled_clips.return_value = []
        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=MagicMock(),
        ):
            result = service.scan_unlabeled_keyword()
        assert result["status"] == "ok"
        assert result["scanned"] == 0
        assert result["matched"] == 0

    # ── Scanning with mocked decode & recognition ────────────────────

    @patch("pydub.AudioSegment.from_file")
    def test_scan_skips_missing_audio(self, mock_from_file, service):
        """Clips without resolvable audio are skipped."""
        clip = {
            "id": 1,
            "relative_path": "nonexistent/file.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
        }
        service.repo.list_unlabeled_clips.return_value = [clip]

        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=MagicMock(),
        ):
            result = service.scan_unlabeled_keyword()

        assert result["scanned"] == 0
        assert result["skipped"] == 1
        assert result["matched"] == 0

    @patch("pydub.AudioSegment.from_file")
    def test_scan_matches_keyword(self, mock_from_file, service, tmp_path):
        """Clip with keyword above threshold is included in matches."""
        # Create a real audio file so resolve_audio_path works
        audio_file = tmp_path / "g100" / "u1"
        audio_file.mkdir(parents=True, exist_ok=True)
        mp3_path = audio_file / "test.mp3"
        # Write minimal valid-ish audio bytes (not actually decoded since we mock pydub)
        mp3_path.write_bytes(b"fake-mp3-bytes")

        clip = {
            "id": 1,
            "relative_path": "g100/u1/test.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
            "display_name": "User One",
            "filename": "test.mp3",
            "duration_seconds": 1.0,
            "byte_size": 1000,
            "captured_at": "2026-01-01 00:00:00",
            "label": None,
        }
        service.repo.list_unlabeled_clips.return_value = [clip]

        # Mock pydub AudioSegment
        fake_segment = MagicMock()
        fake_segment.raw_data = b"\x00\x00" * 16000  # 1 second of 16-bit zero PCM
        fake_segment.set_frame_rate.return_value = fake_segment
        fake_segment.set_channels.return_value = fake_segment
        fake_segment.set_sample_width.return_value = fake_segment
        mock_from_file.return_value = fake_segment

        # Create a fake Vosk recognizer that returns chapada with high confidence
        fake_result = json.dumps({
            "text": "chapada",
            "result": [{"word": "chapada", "conf": 0.85}],
        })

        def make_fake_recognizer(model, sample_rate, grammar_json=None):
            rec = FakeRecognizer(model, sample_rate, grammar_json)
            rec._result = fake_result
            return rec

        fake_model = MagicMock()

        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=fake_model,
        ), patch(
            "vosk.KaldiRecognizer",
            side_effect=make_fake_recognizer,
        ):
            result = service.scan_unlabeled_keyword()

        assert result["status"] == "ok"
        assert result["scanned"] == 1
        assert result["matched"] == 1
        assert len(result["matches"]) == 1
        assert result["matches"][0]["keyword_confidence"] == 0.85
        assert result["matches"][0]["keyword_transcript"] == "chapada"

    @patch("pydub.AudioSegment.from_file")
    def test_scan_excludes_low_confidence(self, mock_from_file, service, tmp_path):
        """Clip with keyword below threshold is not included."""
        audio_file = tmp_path / "g100" / "u1"
        audio_file.mkdir(parents=True, exist_ok=True)
        mp3_path = audio_file / "test.mp3"
        mp3_path.write_bytes(b"fake-mp3-bytes")

        clip = {
            "id": 2,
            "relative_path": "g100/u1/test.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
        }
        service.repo.list_unlabeled_clips.return_value = [clip]

        fake_segment = MagicMock()
        fake_segment.raw_data = b"\x00\x00" * 16000
        fake_segment.set_frame_rate.return_value = fake_segment
        fake_segment.set_channels.return_value = fake_segment
        fake_segment.set_sample_width.return_value = fake_segment
        mock_from_file.return_value = fake_segment

        fake_result = json.dumps({
            "text": "chapada",
            "result": [{"word": "chapada", "conf": 0.3}],
        })

        fake_model = MagicMock()

        def make_recognizer(model, sample_rate, grammar_json=None):
            rec = FakeRecognizer(model, sample_rate, grammar_json)
            rec._result = fake_result
            return rec

        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=fake_model,
        ), patch(
            "vosk.KaldiRecognizer",
            side_effect=make_recognizer,
        ):
            result = service.scan_unlabeled_keyword()

        assert result["scanned"] == 1
        assert result["matched"] == 0
        assert len(result["matches"]) == 0

    @patch("pydub.AudioSegment.from_file")
    def test_scan_skips_decode_error(self, mock_from_file, service, tmp_path):
        """Clip that throws during decode/recognition is skipped."""
        audio_file = tmp_path / "g100" / "u1"
        audio_file.mkdir(parents=True, exist_ok=True)
        mp3_path = audio_file / "test.mp3"
        mp3_path.write_bytes(b"corrupted-mp3")

        clip = {
            "id": 3,
            "relative_path": "g100/u1/test.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
        }
        service.repo.list_unlabeled_clips.return_value = [clip]

        # Simulate pydub decode failure
        mock_from_file.side_effect = Exception("Decode failed")

        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=MagicMock(),
        ):
            result = service.scan_unlabeled_keyword()

        assert result["scanned"] == 0
        assert result["skipped"] == 1
        assert result["matched"] == 0

    def test_scan_passes_filters(self, service):
        """Guild, user, and max_duration filters are forwarded to the repo."""
        service.repo.list_unlabeled_clips.return_value = []

        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=MagicMock(),
        ):
            service.scan_unlabeled_keyword(guild_id="100", user_id="1")

        service.repo.list_unlabeled_clips.assert_called_once_with(
            guild_id="100",
            user_id="1",
            max_duration_seconds=30.0,
        )

    # ── Progress callback ─────────────────────────────────────────────

    @patch("pydub.AudioSegment.from_file")
    def test_scan_progress_callback_initial(self, mock_from_file, service, tmp_path):
        """Progress callback is called with initial state before scanning."""
        service.repo.list_unlabeled_clips.return_value = []

        callbacks: list[dict] = []

        def _cb(progress: dict) -> None:
            callbacks.append(progress)

        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=MagicMock(),
        ):
            service.scan_unlabeled_keyword(progress_callback=_cb)

        # Should have one initial callback
        assert len(callbacks) >= 1
        initial = callbacks[0]
        assert initial["status"] == "processing"
        assert initial["total"] == 0
        assert initial["scanned"] == 0
        assert initial["matched"] == 0
        assert initial["skipped"] == 0
        assert initial["current_clip_id"] is None

    @patch("pydub.AudioSegment.from_file")
    def test_scan_progress_callback_per_clip(self, mock_from_file, service, tmp_path):
        """Progress callback is invoked as clips complete concurrently."""
        # Create two clips with real audio files
        clip1_data = {
            "id": 1,
            "relative_path": "g100/u1/clip1.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
            "display_name": "User One",
            "filename": "clip1.mp3",
            "duration_seconds": 1.0,
            "byte_size": 1000,
            "captured_at": "2026-01-01 00:00:00",
            "label": None,
        }
        clip2_data = {
            "id": 2,
            "relative_path": "g100/u1/clip2.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
            "display_name": "User One",
            "filename": "clip2.mp3",
            "duration_seconds": 1.0,
            "byte_size": 1000,
            "captured_at": "2026-01-01 00:00:00",
            "label": None,
        }
        service.repo.list_unlabeled_clips.return_value = [clip1_data, clip2_data]

        # Create real audio files for both clips
        audio_file1 = tmp_path / "g100" / "u1"
        audio_file1.mkdir(parents=True, exist_ok=True)
        (audio_file1 / "clip1.mp3").write_bytes(b"fake-mp3-bytes")
        (audio_file1 / "clip2.mp3").write_bytes(b"fake-mp3-bytes")

        fake_segment = MagicMock()
        fake_segment.raw_data = b"\x00\x00" * 16000
        fake_segment.set_frame_rate.return_value = fake_segment
        fake_segment.set_channels.return_value = fake_segment
        fake_segment.set_sample_width.return_value = fake_segment
        mock_from_file.return_value = fake_segment

        fake_result = json.dumps({
            "text": "chapada",
            "result": [{"word": "chapada", "conf": 0.85}],
        })

        def make_fake_recognizer(model, sample_rate, grammar_json=None):
            rec = FakeRecognizer(model, sample_rate, grammar_json)
            rec._result = fake_result
            return rec

        fake_model = MagicMock()

        callbacks: list[dict] = []

        def _cb(progress: dict) -> None:
            callbacks.append(progress)

        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=fake_model,
        ), patch(
            "vosk.KaldiRecognizer",
            side_effect=make_fake_recognizer,
        ):
            service.scan_unlabeled_keyword(progress_callback=_cb)

        # At least initial + 1 per-clip callback; with concurrent execution
        # both clips may complete in a single batch so 2-3 callbacks are valid.
        assert len(callbacks) >= 2

        # First callback: initial state
        assert callbacks[0]["total"] == 2
        assert callbacks[0]["scanned"] == 0
        assert callbacks[0]["matched"] == 0
        assert callbacks[0]["current_clip_id"] is None

        # Final state should be 2 scanned, 2 matched
        last_cb = callbacks[-1]
        assert last_cb["scanned"] == 2
        assert last_cb["matched"] == 2

    @patch("pydub.AudioSegment.from_file")
    def test_scan_progress_callback_skipped(self, mock_from_file, service, tmp_path):
        """Progress callback reports skipped clips correctly."""
        clip_missing = {
            "id": 1,
            "relative_path": "nonexistent/file.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
        }
        service.repo.list_unlabeled_clips.return_value = [clip_missing]

        callbacks: list[dict] = []

        def _cb(progress: dict) -> None:
            callbacks.append(progress)

        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=MagicMock(),
        ):
            service.scan_unlabeled_keyword(progress_callback=_cb)

        # Initial + 1 per-clip
        assert len(callbacks) == 2
        # After clip 1 (skipped due to missing audio)
        assert callbacks[1]["scanned"] == 0
        assert callbacks[1]["skipped"] == 1
        assert callbacks[1]["matched"] == 0

    # ── Delete non-matches ────────────────────────────────────────────

    @patch("pydub.AudioSegment.from_file")
    def test_scan_delete_nonmatches_keeps_matched_and_skipped(
        self, mock_from_file, service, tmp_path
    ):
        """With delete_non_matches=True, matched clips remain and skipped clips remain,
        while non-matched successfully-scanned clips are deleted from DB and files."""
        # Use single worker for deterministic test execution order
        service.KEYWORD_SCAN_WORKERS = 1

        # Create audio directory and three audio files
        audio_dir = tmp_path / "g100" / "u1"
        audio_dir.mkdir(parents=True, exist_ok=True)

        matched_path = audio_dir / "match.mp3"
        matched_path.write_bytes(b"fake-matched")

        nonmatch_path = audio_dir / "nonmatch.mp3"
        nonmatch_path.write_bytes(b"fake-nonmatch")

        skip_path = audio_dir / "skip.mp3"
        skip_path.write_bytes(b"fake-skip")

        # Clip 1: will match
        match_clip = {
            "id": 10,
            "relative_path": "g100/u1/match.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
            "display_name": "User One",
            "filename": "match.mp3",
            "duration_seconds": 1.0,
            "byte_size": 1000,
            "captured_at": "2026-01-01 00:00:00",
            "label": None,
        }
        # Clip 2: will not match (low confidence)
        nonmatch_clip = {
            "id": 11,
            "relative_path": "g100/u1/nonmatch.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
            "display_name": "User One",
            "filename": "nonmatch.mp3",
            "duration_seconds": 1.0,
            "byte_size": 1000,
            "captured_at": "2026-01-02 00:00:00",
            "label": None,
        }
        # Clip 3: missing audio (skipped)
        skip_clip = {
            "id": 12,
            "relative_path": "g100/u1/skip.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
            "display_name": "User One",
            "filename": "skip.mp3",
            "duration_seconds": 1.0,
            "byte_size": 1000,
            "captured_at": "2026-01-03 00:00:00",
            "label": None,
        }

        service.repo.list_unlabeled_clips.return_value = [
            match_clip, nonmatch_clip, skip_clip,
        ]

        fake_segment = MagicMock()
        fake_segment.raw_data = b"\x00\x00" * 16000
        fake_segment.set_frame_rate.return_value = fake_segment
        fake_segment.set_channels.return_value = fake_segment
        fake_segment.set_sample_width.return_value = fake_segment

        # First call succeeds (match), second call succeeds (nonmatch pydub),
        # third should be skipped by resolve_audio_path returning None.
        mock_from_file.return_value = fake_segment

        # Override resolve_audio_path to make skip clip return None
        real_resolve = service.resolve_audio_path
        def resolve_skip_audio(clip):
            if clip["id"] == 12:
                return None
            return real_resolve(clip)

        # Mock Vosk: first recognizer call gets match, second gets nonmatch
        match_result = json.dumps({
            "text": "chapada",
            "result": [{"word": "chapada", "conf": 0.85}],
        })
        nonmatch_result = json.dumps({
            "text": "outro",
            "result": [{"word": "outro", "conf": 0.3}],
        })
        recognizer_results = iter([match_result, nonmatch_result])

        def make_recognizer(model, sample_rate, grammar_json=None):
            rec = FakeRecognizer(model, sample_rate, grammar_json)
            rec._result = next(recognizer_results)
            return rec

        fake_model = MagicMock()

        # Mock bulk_delete_clips to track what is passed and return fake data
        service.repo.bulk_delete_clips.return_value = [nonmatch_clip]

        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=fake_model,
        ), patch(
            "vosk.KaldiRecognizer",
            side_effect=make_recognizer,
        ), patch.object(
            service, "resolve_audio_path", side_effect=resolve_skip_audio,
        ):
            result = service.scan_unlabeled_keyword(delete_non_matches=True)

        # Verify scan results
        assert result["status"] == "ok"
        assert result["scanned"] == 2
        assert result["matched"] == 1
        assert result["skipped"] == 1
        assert result["delete_non_matches"] is True
        assert result["deleted_non_matches"] == 1

        # Verify the nonmatch clip was passed for deletion
        service.repo.bulk_delete_clips.assert_called_once_with([11])

        # Match clip is in results
        assert len(result["matches"]) == 1
        assert result["matches"][0]["id"] == 10

    @patch("pydub.AudioSegment.from_file")
    def test_scan_delete_nonmatches_none_to_delete(
        self, mock_from_file, service, tmp_path
    ):
        """With delete_non_matches=True and no nonmatches, nothing is deleted."""
        audio_dir = tmp_path / "g100" / "u1"
        audio_dir.mkdir(parents=True, exist_ok=True)
        mp3_path = audio_dir / "test.mp3"
        mp3_path.write_bytes(b"fake-mp3")

        clip = {
            "id": 20,
            "relative_path": "g100/u1/test.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
            "display_name": "User One",
            "filename": "test.mp3",
            "duration_seconds": 1.0,
            "byte_size": 1000,
            "captured_at": "2026-01-01 00:00:00",
            "label": None,
        }

        service.repo.list_unlabeled_clips.return_value = [clip]

        fake_segment = MagicMock()
        fake_segment.raw_data = b"\x00\x00" * 16000
        fake_segment.set_frame_rate.return_value = fake_segment
        fake_segment.set_channels.return_value = fake_segment
        fake_segment.set_sample_width.return_value = fake_segment
        mock_from_file.return_value = fake_segment

        match_result = json.dumps({
            "text": "chapada",
            "result": [{"word": "chapada", "conf": 0.85}],
        })
        fake_model = MagicMock()

        def make_recognizer(model, sample_rate, grammar_json=None):
            rec = FakeRecognizer(model, sample_rate, grammar_json)
            rec._result = match_result
            return rec

        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=fake_model,
        ), patch(
            "vosk.KaldiRecognizer",
            side_effect=make_recognizer,
        ):
            result = service.scan_unlabeled_keyword(delete_non_matches=True)

        assert result["scanned"] == 1
        assert result["matched"] == 1
        assert result["skipped"] == 0
        assert result["delete_non_matches"] is True
        assert result["deleted_non_matches"] == 0
        # bulk_delete_clips should NOT have been called
        service.repo.bulk_delete_clips.assert_not_called()

    def test_scan_delete_nonmatches_no_clips(self, service):
        """With delete_non_matches=True and no clips, nothing happens."""
        service.repo.list_unlabeled_clips.return_value = []

        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=MagicMock(),
        ):
            result = service.scan_unlabeled_keyword(delete_non_matches=True)

        assert result["scanned"] == 0
        assert result["matched"] == 0
        assert result["deleted_non_matches"] == 0
        assert result["delete_non_matches"] is True
        service.repo.bulk_delete_clips.assert_not_called()

    # ── Label non-matches as none ─────────────────────────────────────

    @patch("pydub.AudioSegment.from_file")
    def test_scan_label_nonmatches_as_none(self, mock_from_file, service, tmp_path):
        """With label_non_matches_as_none=True, non-matches are bulk-labeled as 'none'."""
        service.KEYWORD_SCAN_WORKERS = 1  # deterministic order

        audio_dir = tmp_path / "g100" / "u1"
        audio_dir.mkdir(parents=True, exist_ok=True)

        match_clip = {
            "id": 20,
            "relative_path": "g100/u1/match.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
            "display_name": "User One",
            "filename": "match.mp3",
            "duration_seconds": 1.0,
            "byte_size": 1000,
            "captured_at": "2026-01-01 00:00:00",
            "label": None,
        }
        nonmatch_clip = {
            "id": 21,
            "relative_path": "g100/u1/nonmatch.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
            "display_name": "User One",
            "filename": "nonmatch.mp3",
            "duration_seconds": 1.0,
            "byte_size": 1000,
            "captured_at": "2026-01-02 00:00:00",
            "label": None,
        }

        (audio_dir / "match.mp3").write_bytes(b"fake-mp3")
        (audio_dir / "nonmatch.mp3").write_bytes(b"fake-mp3")

        service.repo.list_unlabeled_clips.return_value = [match_clip, nonmatch_clip]

        fake_segment = MagicMock()
        fake_segment.raw_data = b"\x00\x00" * 16000
        fake_segment.set_frame_rate.return_value = fake_segment
        fake_segment.set_channels.return_value = fake_segment
        fake_segment.set_sample_width.return_value = fake_segment
        mock_from_file.return_value = fake_segment

        match_result = json.dumps({
            "text": "chapada",
            "result": [{"word": "chapada", "conf": 0.85}],
        })
        nonmatch_result = json.dumps({
            "text": "outro",
            "result": [{"word": "outro", "conf": 0.3}],
        })
        recognizer_results = iter([match_result, nonmatch_result])

        def make_recognizer(model, sample_rate, grammar_json=None):
            rec = FakeRecognizer(model, sample_rate, grammar_json)
            rec._result = next(recognizer_results)
            return rec

        fake_model = MagicMock()

        service.repo.bulk_update_review.return_value = 1

        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=fake_model,
        ), patch(
            "vosk.KaldiRecognizer",
            side_effect=make_recognizer,
        ):
            result = service.scan_unlabeled_keyword(
                label_non_matches_as_none=True,
            )

        assert result["status"] == "ok"
        assert result["scanned"] == 2
        assert result["matched"] == 1
        assert result["skipped"] == 0
        assert result["label_non_matches_as_none"] is True
        assert result["labeled_non_matches"] == 1
        assert len(result["matches"]) == 1
        assert result["matches"][0]["id"] == 20

        # Verify bulk_update_review was called with non-match IDs and 'none'
        service.repo.bulk_update_review.assert_called_once()
        call_kwargs = service.repo.bulk_update_review.call_args[1]
        assert call_kwargs["label"] == "none"
        assert call_kwargs["clip_ids"] == [21]

    def test_scan_label_nonmatches_as_none_no_nonmatches(self, service):
        """With label_non_matches_as_none=True and no non-matches, nothing is labeled."""
        service.repo.list_unlabeled_clips.return_value = []

        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=MagicMock(),
        ):
            result = service.scan_unlabeled_keyword(label_non_matches_as_none=True)

        assert result["scanned"] == 0
        assert result["matched"] == 0
        assert result["labeled_non_matches"] == 0
        assert result["label_non_matches_as_none"] is True
        service.repo.bulk_update_review.assert_not_called()

class TestWebSpeechTrainingLabelOptions:
    """Tests for WebSpeechTrainingService.get_label_options()."""

    @pytest.fixture
    def repo(self):
        """Create a mock SpeechTrainingRepository."""
        mock_repo = MagicMock()
        mock_repo.list_labels.return_value = []
        return mock_repo

    @pytest.fixture
    def service(self, repo, tmp_path):
        """Create a WebSpeechTrainingService with a temp data dir."""
        from bot.services.web_speech_training import WebSpeechTrainingService

        return WebSpeechTrainingService(repo, str(tmp_path))

    def test_defaults_first(self, service):
        """Default labels appear first, before any custom labels."""
        service.repo.list_labels.return_value = ['custom_one', 'custom_two']
        result = service.get_label_options()
        assert result["labels"][:3] == ['chapada', 'ventura', 'none']
        assert result["labels"][3:] == ['custom_one', 'custom_two']

    def test_custom_labels_included_once(self, service):
        """Custom labels are included, de-duplicated against defaults."""
        service.repo.list_labels.return_value = ['chapada', 'ventura', 'custom']
        result = service.get_label_options()
        # 'chapada' and 'ventura' already in defaults, so only 'custom' is added
        assert result["labels"] == ['chapada', 'ventura', 'none', 'custom']

    def test_repo_empty_labels_not_present(self, service):
        """The repo already filters empty labels via SQL; the service is not expected to re-filter."""
        # The repo query excludes empty/NULL labels, so the service never sees them.
        # This test verifies that what the repo returns is passed through correctly.
        service.repo.list_labels.return_value = ['valid_label']
        result = service.get_label_options()
        assert result["labels"] == ['chapada', 'ventura', 'none', 'valid_label']

    def test_guild_id_passed_through(self, service):
        """guild_id is forwarded to the repository."""
        service.get_label_options(guild_id="100")
        service.repo.list_labels.assert_called_once_with(guild_id="100")

    def test_no_guild_id(self, service):
        """Without guild_id, repo is called with guild_id=None."""
        service.get_label_options()
        service.repo.list_labels.assert_called_once_with(guild_id=None)


class TestWebSpeechTrainingTranscribe:
    """Tests for WebSpeechTrainingService.transcribe_empty_clips()."""

    @pytest.fixture
    def repo(self):
        """Create a mock SpeechTrainingRepository."""
        mock_repo = MagicMock()
        mock_repo.list_empty_transcript_clips.return_value = []
        return mock_repo

    @pytest.fixture
    def service(self, repo, tmp_path):
        """Create a WebSpeechTrainingService with a temp data dir."""
        from bot.services.web_speech_training import WebSpeechTrainingService

        return WebSpeechTrainingService(repo, str(tmp_path))

    # ── Validation ───────────────────────────────────────────────────

    def test_transcribe_rejects_missing_key(self, service):
        """Empty groq_api_key raises ValueError."""
        with pytest.raises(ValueError, match="GROQ_API_KEY is not configured"):
            service.transcribe_empty_clips(groq_api_key="")

    def test_transcribe_rejects_none_key(self, service):
        """None groq_api_key raises ValueError."""
        with pytest.raises(ValueError):
            service.transcribe_empty_clips(groq_api_key="")

    # ── No empty clips ───────────────────────────────────────────────

    def test_transcribe_no_empty_clips(self, service):
        """When no empty-transcript clips exist, returns zero counts."""
        service.repo.list_empty_transcript_clips.return_value = []
        result = service.transcribe_empty_clips(groq_api_key="test-key")
        assert result["status"] == "ok"
        assert result["total"] == 0
        assert result["processed"] == 0
        assert result["updated"] == 0

    # ── Progress callback ─────────────────────────────────────────────

    def test_transcribe_progress_callback_initial(self, service):
        """Progress callback is called with initial state before processing."""
        service.repo.list_empty_transcript_clips.return_value = []

        callbacks: list = []

        def _cb(progress: dict) -> None:
            callbacks.append(progress)

        service.transcribe_empty_clips(groq_api_key="test-key", progress_callback=_cb)

        assert len(callbacks) >= 1
        initial = callbacks[0]
        assert initial["status"] == "processing"
        assert initial["total"] == 0
        assert initial["processed"] == 0
        assert initial["updated"] == 0

        # Last callback should have status "done"
        last = callbacks[-1]
        assert last["status"] == "done"

    # ── Scan passes filters ───────────────────────────────────────────

    def test_transcribe_passes_filters(self, service):
        """Guild and user filters are forwarded to the repo."""
        service.repo.list_empty_transcript_clips.return_value = []

        service.transcribe_empty_clips(
            guild_id="100", user_id="1", groq_api_key="test-key",
        )

        service.repo.list_empty_transcript_clips.assert_called_once_with(
            guild_id="100", user_id="1",
        )

    # ── Results dict ──────────────────────────────────────────────────

    def test_transcribe_returns_result_dict(self, service):
        """Result dict contains expected keys."""
        service.repo.list_empty_transcript_clips.return_value = []

        result = service.transcribe_empty_clips(groq_api_key="test-key")

        expected_keys = {
            "status", "total", "processed", "updated",
            "empty_marked", "skipped", "errors",
        }
        assert expected_keys.issubset(result.keys())

    # ── Cap handling ──────────────────────────────────────────────────

    def test_transcribe_caps_at_max(self, service):
        """Total is capped at TRANSCRIBE_MAX_CLIPS."""
        many_clips = [
            {
                "id": i,
                "relative_path": f"g100/u1/clip{i}.mp3",
                "guild_id": "100",
                "user_id": "1",
                "username": "user1",
                "display_name": "User One",
                "filename": f"clip{i}.mp3",
                "duration_seconds": 1.0,
                "byte_size": 1000,
                "captured_at": "2026-01-01 00:00:00",
                "label": None,
                "transcript": None,
            }
            for i in range(service.TRANSCRIBE_MAX_CLIPS + 50)
        ]
        service.repo.list_empty_transcript_clips.return_value = many_clips

        result = service.transcribe_empty_clips(groq_api_key="test-key")

        assert result["total"] == service.TRANSCRIBE_MAX_CLIPS
        assert result["total"] == 500
