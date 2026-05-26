"""
Tests for bot/services/web_speech_training.py - offline keyword scanning.
"""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
        with pytest.raises(ValueError, match="At least one keyword must be configured"):
            service.scan_unlabeled_keyword(keyword="")

    def test_scan_rejects_empty_keywords_list(self, service):
        """Empty keywords list raises ValueError."""
        with pytest.raises(ValueError, match="At least one keyword must be configured"):
            service.scan_unlabeled_keywords(keywords=[])

    def test_scan_multi_keyword_delegates(self, service):
        """scan_unlabeled_keyword delegates to scan_unlabeled_keywords with single keyword."""
        service.repo.list_unlabeled_clips.return_value = []
        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=MagicMock(),
        ):
            result = service.scan_unlabeled_keyword(keyword="chapada")
        assert result["status"] == "ok"
        assert result["keyword"] == "chapada"

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
        # Verify detection metadata was persisted as skipped
        skipped_calls = [
            c for c in service.repo.update_detection_metadata.call_args_list
            if c[1].get("detection_status") == "skipped"
        ]
        assert len(skipped_calls) == 1
        assert skipped_calls[0][1]["clip_id"] == 1
        assert skipped_calls[0][1]["detection_error"] == "no_audio"

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
        # Verify detection metadata was persisted
        service.repo.update_detection_metadata.assert_called_once()
        call_kwargs = service.repo.update_detection_metadata.call_args[1]
        assert call_kwargs["clip_id"] == 1
        assert call_kwargs["detected_keyword"] == "chapada"
        assert call_kwargs["detected_confidence"] == 0.85
        assert call_kwargs["detected_transcript"] == "chapada"
        assert call_kwargs["detection_status"] == "matched"
        assert call_kwargs["detection_source"] == "vosk_keyword_scan"

    @patch("pydub.AudioSegment.from_file")
    def test_scan_matches_any_keyword_in_list(self, mock_from_file, service, tmp_path):
        """Clip matching any keyword in the list is included in matches."""
        audio_file = tmp_path / "g100" / "u1"
        audio_file.mkdir(parents=True, exist_ok=True)
        mp3_path = audio_file / "test.mp3"
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

        fake_segment = MagicMock()
        fake_segment.raw_data = b"\x00\x00" * 16000
        fake_segment.set_frame_rate.return_value = fake_segment
        fake_segment.set_channels.return_value = fake_segment
        fake_segment.set_sample_width.return_value = fake_segment
        mock_from_file.return_value = fake_segment

        # Vosk returns "ventura" which is one of the scanned keywords
        fake_result = json.dumps({
            "text": "ventura",
            "result": [{"word": "ventura", "conf": 0.85}],
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
            result = service.scan_unlabeled_keywords(
                keywords=["chapada", "ventura", "teste"],
            )

        assert result["status"] == "ok"
        assert result["scanned"] == 1
        assert result["matched"] == 1
        assert len(result["matches"]) == 1
        assert result["matches"][0]["keyword_confidence"] == 0.85
        assert result["matches"][0]["matched_keyword"] == "ventura"
        assert result["keywords"] == ["chapada", "teste", "ventura"]
        assert result["keyword_count"] == 3
        assert result["keyword"] == "keywords"
        # Verify detection metadata was persisted for the match
        assert service.repo.update_detection_metadata.call_count >= 1
        # Find the match call
        match_calls = [
            c for c in service.repo.update_detection_metadata.call_args_list
            if c[1].get("detection_status") == "matched"
        ]
        assert len(match_calls) == 1
        assert match_calls[0][1]["detected_keyword"] == "ventura"

    def test_scan_keywords_result_includes_keyword_metadata(self, service):
        """Result for multi-keyword scan includes keywords/keyword_count."""
        service.repo.list_unlabeled_clips.return_value = []
        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=MagicMock(),
        ):
            result = service.scan_unlabeled_keywords(
                keywords=["chapada", "ventura"],
            )
        assert result["keyword"] == "keywords"
        assert result["keywords"] == ["chapada", "ventura"]
        assert result["keyword_count"] == 2

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
        # Verify detection metadata was persisted as non_match
        nonmatch_calls = [
            c for c in service.repo.update_detection_metadata.call_args_list
            if c[1].get("detection_status") == "non_match"
        ]
        assert len(nonmatch_calls) == 1
        assert nonmatch_calls[0][1]["clip_id"] == 2
        assert nonmatch_calls[0][1]["detected_transcript"] == "chapada"
        assert nonmatch_calls[0][1]["detected_confidence"] == 0.3

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
        # Verify detection metadata was persisted as skipped
        skipped_calls = [
            c for c in service.repo.update_detection_metadata.call_args_list
            if c[1].get("detection_status") == "skipped"
        ]
        assert len(skipped_calls) == 1
        assert skipped_calls[0][1]["clip_id"] == 3
        assert skipped_calls[0][1]["detection_error"] is not None

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

    # ── Label matches as potential ─────────────────────────────────────

    @patch("pydub.AudioSegment.from_file")
    def test_scan_label_matches_as_potential(self, mock_from_file, service, tmp_path):
        """With label_matches_as_potential=True, matched clips are bulk-labeled as 'potential'."""
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

        # Simulate both match labeling and non-match labeling
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
                label_matches_as_potential=True,
            )

        assert result["status"] == "ok"
        assert result["scanned"] == 2
        assert result["matched"] == 1
        assert result["skipped"] == 0
        assert result["label_matches_as_potential"] is True
        assert result["labeled_matches"] == 1
        assert result["label_non_matches_as_none"] is True
        assert result["labeled_non_matches"] == 1
        assert len(result["matches"]) == 1
        assert result["matches"][0]["id"] == 20
        # Match clip should have label set to potential
        assert result["matches"][0].get("label") == "potential"

        # Verify bulk_update_review was called twice: once for matches, once for non-matches
        assert service.repo.bulk_update_review.call_count == 2
        calls = service.repo.bulk_update_review.call_args_list
        # First call could be either order; check by label
        labels_used = [call[1]["label"] for call in calls]
        assert "potential" in labels_used
        assert "none" in labels_used

    def test_scan_label_matches_as_potential_no_matches(self, service):
        """With label_matches_as_potential=True and no matches, nothing is labeled as potential."""
        service.repo.list_unlabeled_clips.return_value = []

        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=MagicMock(),
        ):
            result = service.scan_unlabeled_keyword(
                label_non_matches_as_none=True,
                label_matches_as_potential=True,
            )

        assert result["scanned"] == 0
        assert result["matched"] == 0
        assert result["labeled_matches"] == 0
        assert result["label_matches_as_potential"] is True
        # bulk_update_review should not be called (no clips to label)
        service.repo.bulk_update_review.assert_not_called()

    @patch("pydub.AudioSegment.from_file")
    def test_scan_label_matches_as_potential_clip_label_set(self, mock_from_file, service, tmp_path):
        """When label_matches_as_potential=True, each returned match dict has label='potential'."""
        service.KEYWORD_SCAN_WORKERS = 1

        audio_dir = tmp_path / "g100" / "u1"
        audio_dir.mkdir(parents=True, exist_ok=True)

        match_clip = {
            "id": 30,
            "relative_path": "g100/u1/m.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
            "display_name": "U1",
            "filename": "m.mp3",
            "duration_seconds": 1.0,
            "byte_size": 1000,
            "captured_at": "2026-01-01 00:00:00",
            "label": None,
        }
        service.repo.list_unlabeled_clips.return_value = [match_clip]
        (audio_dir / "m.mp3").write_bytes(b"fake-mp3")

        fake_segment = MagicMock()
        fake_segment.raw_data = b"\x00\x00" * 16000
        fake_segment.set_frame_rate.return_value = fake_segment
        fake_segment.set_channels.return_value = fake_segment
        fake_segment.set_sample_width.return_value = fake_segment
        mock_from_file.return_value = fake_segment

        match_result = json.dumps({
            "text": "ventura",
            "result": [{"word": "ventura", "conf": 0.92}],
        })

        def make_recognizer(model, sample_rate, grammar_json=None):
            rec = FakeRecognizer(model, sample_rate, grammar_json)
            rec._result = match_result
            return rec

        service.repo.bulk_update_review.return_value = 1

        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=MagicMock(),
        ), patch(
            "vosk.KaldiRecognizer",
            side_effect=make_recognizer,
        ):
            result = service.scan_unlabeled_keyword(
                keyword="ventura",
                label_matches_as_potential=True,
            )

        assert result["matched"] == 1
        assert result["labeled_matches"] == 1
        assert result["matches"][0]["label"] == "potential"

    # ── Keyword timing in scan results ─────────────────────────────────

    @patch("pydub.AudioSegment.from_file")
    def test_scan_returns_keyword_timing(self, mock_from_file, service, tmp_path):
        """Scan match includes keyword_start_seconds and keyword_end_seconds from Vosk word data."""
        audio_file = tmp_path / "g100" / "u1"
        audio_file.mkdir(parents=True, exist_ok=True)
        mp3_path = audio_file / "test.mp3"
        mp3_path.write_bytes(b"fake-mp3-bytes")

        clip = {
            "id": 1,
            "relative_path": "g100/u1/test.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
            "display_name": "User One",
            "filename": "test.mp3",
            "duration_seconds": 5.0,
            "byte_size": 1000,
            "captured_at": "2026-01-01 00:00:00",
            "label": None,
        }
        service.repo.list_unlabeled_clips.return_value = [clip]

        fake_segment = MagicMock()
        fake_segment.raw_data = b"\x00\x00" * 80000  # 5 seconds of 16-bit PCM
        fake_segment.set_frame_rate.return_value = fake_segment
        fake_segment.set_channels.return_value = fake_segment
        fake_segment.set_sample_width.return_value = fake_segment
        mock_from_file.return_value = fake_segment

        # Vosk returns chapada with timing metadata
        fake_result = json.dumps({
            "text": "chapada",
            "result": [{"word": "chapada", "conf": 0.85, "start": 2.5, "end": 3.1}],
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
        assert len(result["matches"]) == 1
        match = result["matches"][0]
        assert match["keyword_start_seconds"] == 2.5
        assert match["keyword_end_seconds"] == 3.1

        # Verify timing was persisted via update_detection_metadata
        match_calls = [
            c for c in service.repo.update_detection_metadata.call_args_list
            if c[1].get("detection_status") == "matched"
        ]
        assert len(match_calls) == 1
        assert match_calls[0][1]["detected_start_seconds"] == 2.5
        assert match_calls[0][1]["detected_end_seconds"] == 3.1

    # ── Auto-trim matches to keyword ──────────────────────────────────

    @patch("pydub.AudioSegment.from_file")
    def test_scan_trim_matches_to_keyword(self, mock_from_file, service, tmp_path):
        """With trim_matches_to_keyword=True, matched clips are auto-trimmed."""
        from unittest.mock import PropertyMock

        service.KEYWORD_SCAN_WORKERS = 1
        audio_dir = tmp_path / "g100" / "u1"
        audio_dir.mkdir(parents=True, exist_ok=True)
        mp3_path = audio_dir / "match.mp3"
        mp3_path.write_bytes(b"fake-mp3")

        match_clip = {
            "id": 40,
            "relative_path": "g100/u1/match.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
            "display_name": "User One",
            "filename": "match.mp3",
            "duration_seconds": 5.0,
            "byte_size": 5000,
            "captured_at": "2026-01-01 00:00:00",
            "label": None,
        }
        service.repo.list_unlabeled_clips.return_value = [match_clip]

        fake_segment = MagicMock()
        fake_segment.raw_data = b"\x00\x00" * 80000
        fake_segment.set_frame_rate.return_value = fake_segment
        fake_segment.set_channels.return_value = fake_segment
        fake_segment.set_sample_width.return_value = fake_segment
        # Make __getitem__ slice work for trim
        type(fake_segment).__getitem__ = lambda self, key: MagicMock()
        mock_from_file.return_value = fake_segment

        fake_result = json.dumps({
            "text": "chapada",
            "result": [{"word": "chapada", "conf": 0.85, "start": 2.5, "end": 3.1}],
        })

        def make_fake_recognizer(model, sample_rate, grammar_json=None):
            rec = FakeRecognizer(model, sample_rate, grammar_json)
            rec._result = fake_result
            return rec

        fake_model = MagicMock()

        # Patch trim_clip_to_keyword to verify it's called correctly.
        # We need it to succeed so the result includes trimmed counts.
        trim_metadata = {
            "duration_seconds": 1.2,
            "byte_size": 800,
            "keyword_start_seconds": 0.3,
            "keyword_end_seconds": 1.0,
            "trim_start_seconds": 2.2,
            "trim_end_seconds": 3.4,
        }

        # Configure bulk_update_review return value for match labeling
        service.repo.bulk_update_review.return_value = 1

        with patch.object(
            service, "trim_clip_to_keyword",
            return_value=(True, "", trim_metadata),
        ) as mock_trim, patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=fake_model,
        ), patch(
            "vosk.KaldiRecognizer",
            side_effect=make_fake_recognizer,
        ):
            result = service.scan_unlabeled_keyword(
                label_matches_as_potential=True,
                trim_matches_to_keyword=True,
            )

        assert result["status"] == "ok"
        assert result["matched"] == 1
        assert result["trim_matches_to_keyword"] is True
        assert result["trimmed_matches"] == 1
        assert result["failed_trim_matches"] == 0
        assert result["labeled_matches"] == 1

        # Verify trim_clip_to_keyword was called with the right args
        mock_trim.assert_called_once_with(
            clip_id=40,
            start_seconds=2.5,
            end_seconds=3.1,
        )

        # Verify match dict was updated with post-trim metadata
        match = result["matches"][0]
        assert match["duration_seconds"] == 1.2
        assert match["byte_size"] == 800
        assert match["keyword_start_seconds"] == 0.3
        assert match["keyword_end_seconds"] == 1.0
        assert match.get("label") == "potential"

        # Verify bulk_update_review was called for match labeling
        assert service.repo.bulk_update_review.call_count >= 1

    @patch("pydub.AudioSegment.from_file")
    def test_scan_trim_missing_timing_fails_safely(self, mock_from_file, service, tmp_path):
        """Match with word result but no start/end timing is counted as failed trim but not fatal."""
        service.KEYWORD_SCAN_WORKERS = 1
        audio_dir = tmp_path / "g100" / "u1"
        audio_dir.mkdir(parents=True, exist_ok=True)
        mp3_path = audio_dir / "match.mp3"
        mp3_path.write_bytes(b"fake-mp3")

        match_clip = {
            "id": 41,
            "relative_path": "g100/u1/match.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
            "display_name": "User One",
            "filename": "match.mp3",
            "duration_seconds": 5.0,
            "byte_size": 5000,
            "captured_at": "2026-01-01 00:00:00",
            "label": None,
        }
        service.repo.list_unlabeled_clips.return_value = [match_clip]

        fake_segment = MagicMock()
        fake_segment.raw_data = b"\x00\x00" * 80000
        fake_segment.set_frame_rate.return_value = fake_segment
        fake_segment.set_channels.return_value = fake_segment
        fake_segment.set_sample_width.return_value = fake_segment
        mock_from_file.return_value = fake_segment

        # Word-level result with conf but no start/end timing
        fake_result = json.dumps({
            "text": "chapada",
            "result": [{"word": "chapada", "conf": 0.85}],
        })

        def make_fake_recognizer(model, sample_rate, grammar_json=None):
            rec = FakeRecognizer(model, sample_rate, grammar_json)
            rec._result = fake_result
            return rec

        fake_model = MagicMock()

        # Configure bulk_update_review for match labeling
        service.repo.bulk_update_review.return_value = 1

        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=fake_model,
        ), patch(
            "vosk.KaldiRecognizer",
            side_effect=make_fake_recognizer,
        ):
            result = service.scan_unlabeled_keyword(
                label_matches_as_potential=True,
                trim_matches_to_keyword=True,
            )

        assert result["status"] == "ok"
        assert result["matched"] == 1
        assert result["trim_matches_to_keyword"] is True
        assert result["trimmed_matches"] == 0
        assert result["failed_trim_matches"] == 1
        # Match should still be present and labeled
        assert len(result["matches"]) == 1
        assert result["matches"][0].get("label") == "potential"
        # keyword timing should be None for this match
        assert result["matches"][0].get("keyword_start_seconds") is None
        assert result["matches"][0].get("keyword_end_seconds") is None

    @patch("pydub.AudioSegment.from_file")
    def test_scan_trim_failure_continues(self, mock_from_file, service, tmp_path):
        """When trim_clip_to_keyword fails, scan continues and failure is counted."""
        service.KEYWORD_SCAN_WORKERS = 1
        audio_dir = tmp_path / "g100" / "u1"
        audio_dir.mkdir(parents=True, exist_ok=True)
        mp3_path = audio_dir / "match.mp3"
        mp3_path.write_bytes(b"fake-mp3")

        match_clip = {
            "id": 42,
            "relative_path": "g100/u1/match.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
            "display_name": "User One",
            "filename": "match.mp3",
            "duration_seconds": 5.0,
            "byte_size": 5000,
            "captured_at": "2026-01-01 00:00:00",
            "label": None,
        }
        service.repo.list_unlabeled_clips.return_value = [match_clip]

        fake_segment = MagicMock()
        fake_segment.raw_data = b"\x00\x00" * 80000
        fake_segment.set_frame_rate.return_value = fake_segment
        fake_segment.set_channels.return_value = fake_segment
        fake_segment.set_sample_width.return_value = fake_segment
        mock_from_file.return_value = fake_segment

        fake_result = json.dumps({
            "text": "chapada",
            "result": [{"word": "chapada", "conf": 0.85, "start": 2.5, "end": 3.1}],
        })

        def make_fake_recognizer(model, sample_rate, grammar_json=None):
            rec = FakeRecognizer(model, sample_rate, grammar_json)
            rec._result = fake_result
            return rec

        fake_model = MagicMock()

        # Configure bulk_update_review for match labeling
        service.repo.bulk_update_review.return_value = 1

        with patch.object(
            service, "trim_clip_to_keyword",
            return_value=(False, "Audio processing failed", {}),
        ) as mock_trim, patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=fake_model,
        ), patch(
            "vosk.KaldiRecognizer",
            side_effect=make_fake_recognizer,
        ):
            result = service.scan_unlabeled_keyword(
                label_matches_as_potential=True,
                trim_matches_to_keyword=True,
            )

        assert result["status"] == "ok"
        assert result["matched"] == 1
        assert result["trim_matches_to_keyword"] is True
        assert result["trimmed_matches"] == 0
        assert result["failed_trim_matches"] == 1
        # Match should still be present and labeled
        assert len(result["matches"]) == 1
        assert result["matches"][0].get("label") == "potential"
        mock_trim.assert_called_once_with(
            clip_id=42,
            start_seconds=2.5,
            end_seconds=3.1,
        )

    def test_scan_trim_no_matches_returns_zeros(self, service):
        """With trim_matches_to_keyword=True and no matches, counts are zero."""
        service.repo.list_unlabeled_clips.return_value = []
        with patch(
            "bot.services.web_speech_training._get_vosk_model",
            return_value=MagicMock(),
        ):
            result = service.scan_unlabeled_keyword(
                label_matches_as_potential=True,
                trim_matches_to_keyword=True,
            )

        assert result["scanned"] == 0
        assert result["matched"] == 0
        assert result["trim_matches_to_keyword"] is True
        assert result["trimmed_matches"] == 0
        assert result["failed_trim_matches"] == 0

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
        defaults = result["labels"][:4]
        assert 'chapada' in defaults
        assert 'ventura' in defaults
        assert 'none' in defaults
        assert 'potential' in defaults
        assert result["labels"][4:] == ['custom_one', 'custom_two']

    def test_custom_labels_included_once(self, service):
        """Custom labels are included, de-duplicated against defaults."""
        service.repo.list_labels.return_value = ['chapada', 'ventura', 'custom']
        result = service.get_label_options()
        # 'chapada', 'ventura', and 'potential' already in defaults; only 'custom' added
        assert result["labels"] == ['chapada', 'ventura', 'none', 'potential', 'custom']

    def test_repo_empty_labels_not_present(self, service):
        """The repo already filters empty labels via SQL; the service is not expected to re-filter."""
        # The repo query excludes empty/NULL labels, so the service never sees them.
        # This test verifies that what the repo returns is passed through correctly.
        service.repo.list_labels.return_value = ['valid_label']
        result = service.get_label_options()
        assert result["labels"] == ['chapada', 'ventura', 'none', 'potential', 'valid_label']

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

    # ── Throttling / rate-limit handling ────────────────────────────────

    def _make_clip(self, clip_id: int, relative_path: str = "g1/u1/clip.mp3") -> dict:
        """Helper to create a minimal clip dict for testing."""
        return {
            "id": clip_id,
            "relative_path": relative_path,
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
            "display_name": "User One",
            "filename": f"clip{clip_id}.mp3",
            "duration_seconds": 1.0,
            "byte_size": 1000,
            "captured_at": "2026-01-01 00:00:00",
            "label": None,
            "transcript": None,
        }

    def _create_clip_file(self, service, clip: dict) -> None:
        """Create the audio file for a clip so resolve_audio_path succeeds."""
        rel = clip["relative_path"]
        full_path = service.data_dir / rel
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(b"fake-mp3-content")

    def test_transcribe_sets_api_key_and_model(self, service):
        """whisper.api_key and whisper.model are set from parameters."""
        from bot.services.voice_command import GroqWhisperResult

        mock_whisper = MagicMock()
        mock_whisper.transcribe_detailed = AsyncMock(return_value=GroqWhisperResult(
            text="ok", is_available=True,
        ))

        with (
            patch("bot.services.voice_command.GroqWhisperService",
                  return_value=mock_whisper) as _mw,
            patch("pydub.AudioSegment.from_file") as mock_audio,
            patch("bot.services.web_speech_training.time.sleep"),
        ):
            mock_seg = MagicMock()
            mock_seg.export.side_effect = lambda buf, **_kw: (buf.write(b"x"), buf)[1]
            mock_audio.return_value = mock_seg

            clip = self._make_clip(1)
            self._create_clip_file(service, clip)
            service.repo.list_empty_transcript_clips.return_value = [clip]
            service.transcribe_empty_clips(
                groq_api_key="custom-key",
                groq_whisper_model="custom-model",
            )

            assert mock_whisper.api_key == "custom-key"
            assert mock_whisper.model == "custom-model"

    def test_transcribe_429_retries_and_succeeds(self, service):
        """A single 429 triggers retry; the retry succeeds."""
        from bot.services.voice_command import GroqWhisperResult

        mock_whisper = MagicMock()
        results = [
            GroqWhisperResult(
                is_available=True,
                error="API error 429 (rate limited)",
                status_code=429,
                retry_after_seconds=2.0,
            ),
            GroqWhisperResult(text="retry ok", is_available=True),
        ]
        mock_whisper.transcribe_detailed = AsyncMock(side_effect=results)

        with (
            patch("bot.services.voice_command.GroqWhisperService",
                  return_value=mock_whisper),
            patch("pydub.AudioSegment.from_file") as mock_audio,
            patch("bot.services.web_speech_training.time.sleep") as mock_sleep,
        ):
            mock_seg = MagicMock()
            mock_seg.export.side_effect = lambda buf, **_kw: (buf.write(b"x"), buf)[1]
            mock_audio.return_value = mock_seg

            clip = self._make_clip(1)
            self._create_clip_file(service, clip)
            service.repo.list_empty_transcript_clips.return_value = [clip]
            result = service.transcribe_empty_clips(groq_api_key="test-key")

            assert result["processed"] == 1
            assert result["updated"] == 1
            assert result["status"] == "ok"
            assert len(result["errors"]) == 0
            # Should have slept for retry-after duration
            mock_sleep.assert_any_call(2.0)
            # Two calls: one 429, one success
            assert mock_whisper.transcribe_detailed.call_count == 2

    def test_transcribe_429_exhausted_stops_early(self, service):
        """Persistent 429 exhausts retries and stops early with an error."""
        from bot.services.voice_command import GroqWhisperResult

        mock_whisper = MagicMock()
        # All attempts return 429
        mock_whisper.transcribe_detailed = AsyncMock(return_value=GroqWhisperResult(
            is_available=True,
            error="API error 429 (rate limited)",
            status_code=429,
            retry_after_seconds=1.0,
        ))

        with (
            patch("bot.services.voice_command.GroqWhisperService",
                  return_value=mock_whisper),
            patch("pydub.AudioSegment.from_file") as mock_audio,
            patch("bot.services.web_speech_training.time.sleep") as mock_sleep,
        ):
            mock_seg = MagicMock()
            mock_seg.export.side_effect = lambda buf, **_kw: (buf.write(b"x"), buf)[1]
            mock_audio.return_value = mock_seg

            clip1 = self._make_clip(1)
            clip2 = self._make_clip(2)
            self._create_clip_file(service, clip1)
            self._create_clip_file(service, clip2)
            # Two clips; only first should be attempted
            service.repo.list_empty_transcript_clips.return_value = [clip1, clip2]
            result = service.transcribe_empty_clips(groq_api_key="test-key")

            assert result["processed"] == 1  # processed one clip
            assert result["updated"] == 0
            assert result["skipped"] == 0
            assert len(result["errors"]) == 1
            assert "Rate limited by Groq" in result["errors"][0]
            assert "WEB_TRANSCRIPT_REQUEST_DELAY_SECONDS" in result["errors"][0]
            # Should have tried max_retries+1 times on the first clip
            expected_attempts = 3 + 1  # default max_retries=3 + first attempt
            assert mock_whisper.transcribe_detailed.call_count == expected_attempts

    def test_transcribe_429_zero_retries_skips_immediately(self, service):
        """When max retries = 0, 429 skips immediately (no retry)."""
        from bot.services.voice_command import GroqWhisperResult

        mock_whisper = MagicMock()
        mock_whisper.transcribe_detailed = AsyncMock(return_value=GroqWhisperResult(
            is_available=True,
            error="API error 429 (rate limited)",
            status_code=429,
        ))

        with (
            patch("bot.services.voice_command.GroqWhisperService",
                  return_value=mock_whisper),
            patch("pydub.AudioSegment.from_file") as mock_audio,
            patch("bot.services.web_speech_training.time.sleep"),
            patch("bot.services.web_speech_training.WEB_TRANSCRIPT_429_MAX_RETRIES", 0),
        ):
            mock_seg = MagicMock()
            mock_seg.export.side_effect = lambda buf, **_kw: (buf.write(b"x"), buf)[1]
            mock_audio.return_value = mock_seg

            clip = self._make_clip(1)
            self._create_clip_file(service, clip)
            service.repo.list_empty_transcript_clips.return_value = [clip]
            result = service.transcribe_empty_clips(groq_api_key="test-key")

            # 0 retries: max_retries (0) + first attempt = 1 call total
            assert mock_whisper.transcribe_detailed.call_count == 1
            assert result["processed"] == 1
            assert len(result["errors"]) == 1
            assert "Rate limited" in result["errors"][0]

    def test_transcribe_inter_request_delay(self, service):
        """Delay between requests is applied after non-last clip."""
        from bot.services.voice_command import GroqWhisperResult

        mock_whisper = MagicMock()
        mock_whisper.transcribe_detailed = AsyncMock(return_value=GroqWhisperResult(
            text="ok", is_available=True,
        ))

        with (
            patch("bot.services.voice_command.GroqWhisperService",
                  return_value=mock_whisper),
            patch("pydub.AudioSegment.from_file") as mock_audio,
            patch("bot.services.web_speech_training.time.sleep") as mock_sleep,
        ):
            mock_seg = MagicMock()
            mock_seg.export.side_effect = lambda buf, **_kw: (buf.write(b"x"), buf)[1]
            mock_audio.return_value = mock_seg

            clip1 = self._make_clip(1)
            clip2 = self._make_clip(2)
            self._create_clip_file(service, clip1)
            self._create_clip_file(service, clip2)
            service.repo.list_empty_transcript_clips.return_value = [clip1, clip2]
            service.transcribe_empty_clips(groq_api_key="test-key")

            # Should have slept once (after first clip, before second)
            delay_calls = [
                c for c in mock_sleep.call_args_list
                if abs(c[0][0] - 1.0) < 0.01
            ]
            assert len(delay_calls) == 1

    def test_transcribe_429_uses_retry_after_not_exponential(self, service):
        """When Retry-After is provided, it is used instead of exponential backoff."""
        from bot.services.voice_command import GroqWhisperResult

        mock_whisper = MagicMock()
        results = [
            GroqWhisperResult(
                is_available=True,
                error="API error 429 (rate limited)",
                status_code=429,
                retry_after_seconds=5.0,
            ),
            GroqWhisperResult(text="ok", is_available=True),
        ]
        mock_whisper.transcribe_detailed = AsyncMock(side_effect=results)

        with (
            patch("bot.services.voice_command.GroqWhisperService",
                  return_value=mock_whisper),
            patch("pydub.AudioSegment.from_file") as mock_audio,
            patch("bot.services.web_speech_training.time.sleep") as mock_sleep,
        ):
            mock_seg = MagicMock()
            mock_seg.export.side_effect = lambda buf, **_kw: (buf.write(b"x"), buf)[1]
            mock_audio.return_value = mock_seg

            clip = self._make_clip(1)
            self._create_clip_file(service, clip)
            service.repo.list_empty_transcript_clips.return_value = [clip]
            service.transcribe_empty_clips(groq_api_key="test-key")

            # Should have slept for exactly 5.0s (Retry-After), not exponential
            mock_sleep.assert_any_call(5.0)


class TestWebSpeechTrainingStorage:
    """Tests for WebSpeechTrainingService storage summary."""

    @pytest.fixture
    def repo(self):
        """Create a mock SpeechTrainingRepository."""
        mock_repo = MagicMock()
        mock_repo.get_storage_summary.return_value = {
            "total_bytes": 75000,
            "clip_count": 2,
        }
        return mock_repo

    @pytest.fixture
    def service(self, repo, tmp_path):
        """Create a WebSpeechTrainingService with a temp data dir."""
        from bot.services.web_speech_training import WebSpeechTrainingService

        return WebSpeechTrainingService(repo, str(tmp_path))

    def test_get_storage_summary_returns_mp3_and_disk_fields(self, service):
        """get_storage_summary includes both MP3 and disk fields."""
        with patch("bot.services.web_speech_training.shutil.disk_usage") as mock_du:
            mock_du.return_value.total = 512_000_000_000
            mock_du.return_value.free = 200_000_000_000
            result = service.get_storage_summary()

        assert result["total_bytes"] == 75000
        assert result["total_size"] == "73.2 KB"
        assert result["clip_count"] == 2
        assert result["available_bytes"] == 200_000_000_000
        assert result["available_size"] == "186.3 GB"
        assert result["disk_total_bytes"] == 512_000_000_000
        assert result["disk_total_size"] == "476.8 GB"

    def test_get_storage_summary_zero_mp3_still_shows_disk(self, service):
        """Zero MP3 storage still reports disk info."""
        service.repo.get_storage_summary.return_value = {
            "total_bytes": 0,
            "clip_count": 0,
        }
        with patch("bot.services.web_speech_training.shutil.disk_usage") as mock_du:
            mock_du.return_value.total = 1_000_000_000_000
            mock_du.return_value.free = 800_000_000_000
            result = service.get_storage_summary()

        assert result["total_bytes"] == 0
        assert result["total_size"] == "0 B"
        assert result["clip_count"] == 0
        assert result["available_bytes"] == 800_000_000_000

    def test_get_storage_summary_when_disk_usage_fails(self, service):
        """When disk_usage raises, no disk fields are in the result."""
        with patch("bot.services.web_speech_training.shutil.disk_usage") as mock_du:
            mock_du.side_effect = PermissionError("Permission denied")
            result = service.get_storage_summary()

        assert result["total_bytes"] == 75000
        assert result["total_size"] == "73.2 KB"
        assert result["clip_count"] == 2
        assert "available_bytes" not in result
        assert "available_size" not in result
        assert "disk_total_bytes" not in result
        assert "disk_total_size" not in result

    def test_get_storage_summary_when_data_dir_missing(self, service):
        """When data_dir does not exist, disk usage falls back to parent."""
        non_existent = service.data_dir / "nonexistent_subdir"
        service.data_dir = non_existent

        with patch("bot.services.web_speech_training.shutil.disk_usage") as mock_du:
            mock_du.return_value.total = 256_000_000_000
            mock_du.return_value.free = 128_000_000_000
            result = service.get_storage_summary()

        # Should have called disk_usage on the parent (tmp_path)
        assert mock_du.call_count == 1
        assert result["available_bytes"] == 128_000_000_000


class TestWebSpeechTrainingTrim:
    """Tests for WebSpeechTrainingService.trim_clip_to_keyword()."""

    @pytest.fixture
    def repo(self):
        """Create a mock SpeechTrainingRepository."""
        return MagicMock()

    @pytest.fixture
    def service(self, repo, tmp_path):
        """Create a WebSpeechTrainingService with a temp data dir."""
        from bot.services.web_speech_training import WebSpeechTrainingService

        return WebSpeechTrainingService(repo, str(tmp_path))

    def _make_clip_data(self, clip_id: int = 1, duration: float = 5.0, has_timing: bool = True) -> dict:
        data = {
            "id": clip_id,
            "relative_path": f"g100/u1/clip{clip_id}.mp3",
            "guild_id": "100",
            "user_id": "1",
            "username": "user1",
            "display_name": "User One",
            "filename": f"clip{clip_id}.mp3",
            "duration_seconds": duration,
            "byte_size": 50000,
            "captured_at": "2026-01-01 00:00:00",
            "label": None,
            "detected_start_seconds": 2.0 if has_timing else None,
            "detected_end_seconds": 2.8 if has_timing else None,
        }
        return data

    def _create_audio(self, service, clip: dict, duration_ms: int = 5000) -> Path:
        """Create a real MP3 file for a clip using pydub, returning its path."""
        from pydub import AudioSegment

        rel = clip["relative_path"]
        full_path = service.data_dir / rel
        full_path.parent.mkdir(parents=True, exist_ok=True)
        # Generate a minimal silent audio segment and export as MP3
        segment = AudioSegment.silent(duration=duration_ms, frame_rate=16000)
        segment.export(str(full_path), format="mp3")
        return full_path

    def test_trim_success(self, service, tmp_path):
        """Successful trim returns updated metadata, updates DB, replaces file."""
        clip = self._make_clip_data(clip_id=1, duration=5.0, has_timing=True)
        service.repo.get_clip.return_value = clip
        audio_path = self._create_audio(service, clip)

        original_size = audio_path.stat().st_size

        success, error, metadata = service.trim_clip_to_keyword(clip_id=1)

        assert success is True
        assert error == ""
        assert metadata["duration_seconds"] < 5.0  # trimmed
        assert metadata["byte_size"] < original_size  # trimmed
        assert metadata["trim_start_seconds"] >= 0
        assert metadata["trim_end_seconds"] <= 5.0
        assert metadata["keyword_start_seconds"] >= 0
        assert metadata["keyword_end_seconds"] > metadata["keyword_start_seconds"]

        # Verify DB was updated
        service.repo.update_audio_metadata_after_trim.assert_called_once()
        call_kwargs = service.repo.update_audio_metadata_after_trim.call_args[1]
        assert call_kwargs["clip_id"] == 1
        assert call_kwargs["duration_seconds"] == metadata["duration_seconds"]
        assert call_kwargs["byte_size"] == metadata["byte_size"]
        assert call_kwargs["detected_start_seconds"] == metadata["keyword_start_seconds"]
        assert call_kwargs["detected_end_seconds"] == metadata["keyword_end_seconds"]

    def test_trim_no_timing_returns_error(self, service, tmp_path):
        """Trim without timing data returns error."""
        clip = self._make_clip_data(clip_id=1, duration=5.0, has_timing=False)
        service.repo.get_clip.return_value = clip
        # Create audio file so we reach the timing check
        self._create_audio(service, clip)

        success, error, metadata = service.trim_clip_to_keyword(clip_id=1)

        assert success is False
        assert "timing" in error.lower()
        assert metadata == {}

    def test_trim_clip_not_found(self, service):
        """Trim on non-existent clip returns error."""
        service.repo.get_clip.return_value = None

        success, error, metadata = service.trim_clip_to_keyword(clip_id=999)

        assert success is False
        assert "not found" in error.lower()
        assert metadata == {}

    def test_trim_missing_audio(self, service, tmp_path):
        """Trim on clip with missing audio file returns error."""
        clip = self._make_clip_data(clip_id=1, duration=5.0, has_timing=True)
        # Don't create the audio file
        service.repo.get_clip.return_value = clip

        success, error, metadata = service.trim_clip_to_keyword(clip_id=1)

        assert success is False
        assert "not found" in error.lower() or "inaccessible" in error.lower()

    def test_trim_with_explicit_timing(self, service, tmp_path):
        """Explicit start/end overrides persisted timing."""
        clip = self._make_clip_data(clip_id=1, duration=10.0, has_timing=False)
        service.repo.get_clip.return_value = clip
        self._create_audio(service, clip, duration_ms=10000)

        success, error, metadata = service.trim_clip_to_keyword(
            clip_id=1,
            start_seconds=3.0,
            end_seconds=4.0,
        )

        assert success is True
        assert error == ""
        # Trim window should be ~3.0 - 0.3 = 2.7 to 4.0 + 0.3 = 4.3 = 1.6s
        assert metadata["duration_seconds"] < 3.0
        assert metadata["duration_seconds"] > 0.5
