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
        """Progress callback is invoked after each clip with updated counts."""
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

        # Initial callback + 2 per-clip callbacks
        assert len(callbacks) == 3

        # First callback: initial state
        assert callbacks[0]["total"] == 2
        assert callbacks[0]["scanned"] == 0
        assert callbacks[0]["matched"] == 0
        assert callbacks[0]["current_clip_id"] is None

        # Second callback: after clip 1
        assert callbacks[1]["scanned"] == 1
        assert callbacks[1]["matched"] == 1  # matches chapada
        assert callbacks[1]["current_clip_id"] == 1

        # Third callback: after clip 2
        assert callbacks[2]["scanned"] == 2
        assert callbacks[2]["matched"] == 2
        assert callbacks[2]["current_clip_id"] == 2

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

    def test_scan_passes_filters_and_max_duration(self, service):
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
