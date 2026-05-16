"""
Tests for bot/services/voice_command.py – Groq Whisper helpers and parsing.
"""

import asyncio
import io
import os
import sys
import wave
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ====================================================================
#  parse_voice_command
# ====================================================================

class TestParseVoiceCommand:
    """Tests for the transcript command parser."""

    def _parse(self, transcript: str):
        """Shorthand that uses default wake words ``['bot']``."""
        from bot.services.voice_command import parse_voice_command
        return parse_voice_command(transcript, wake_words=["bot"])

    def test_wake_word_play(self):
        """``bot play air horn`` → (play, air horn)."""
        result = self._parse("bot play air horn")
        assert result == ("play", "air horn")

    def test_wake_word_with_comma(self):
        """``bot, play sad trombone`` → (play, sad trombone)."""
        result = self._parse("bot, play sad trombone")
        assert result == ("play", "sad trombone")

    def test_wake_word_with_punctuation(self):
        """``bot play music.`` → (play, music)."""
        result = self._parse("bot play music.")
        assert result == ("play", "music")

    def test_play_without_wake_word(self):
        """``play something`` → (play, something) even without wake word."""
        result = self._parse("play something")
        assert result == ("play", "something")

    def test_empty_transcript(self):
        """Empty / whitespace-only → None."""
        assert self._parse("") is None
        assert self._parse("   ") is None

    def test_no_play_command(self):
        """Transcript without ``play`` → None."""
        assert self._parse("bot stop") is None
        assert self._parse("hello world") is None

    def test_play_without_argument(self):
        """``bot play`` with nothing after → None."""
        assert self._parse("bot play") is None
        assert self._parse("play") is None

    def test_excessively_long_name(self):
        """Excessively long sound name → None."""
        long_name = "a" * 300
        assert self._parse(f"bot play {long_name}") is None

    def test_case_insensitive(self):
        """``Bot PLAY Air Horn`` → (play, Air Horn) — original case preserved in sound name."""
        result = self._parse("Bot PLAY Air Horn")
        # Sound-name casing is preserved (not lowercased) so actual filenames match.
        assert result == ("play", "Air Horn")

    def test_strips_quotes(self):
        """``bot play "my sound"`` → (play, my sound)."""
        result = self._parse('bot play "my sound"')
        assert result == ("play", "my sound")

    def test_strips_smart_quotes(self):
        """``bot play \u201cmy sound\u201d`` → (play, my sound)."""
        result = self._parse("bot play \u201cmy sound\u201d")
        assert result == ("play", "my sound")

    def test_wake_word_only(self):
        """Just the wake word with nothing else → None."""
        assert self._parse("bot") is None

    def test_alias_wake_word_parse(self):
        """Vosk alias ``bote play air horn`` → (play, air horn)."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("bote play air horn", wake_words=["bot", "bote"])
        assert result == ("play", "air horn")

    def test_alias_wake_word_with_comma(self):
        """``bote, play sad trombone`` → (play, sad trombone)."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("bote, play sad trombone", wake_words=["bot", "bote"])
        assert result == ("play", "sad trombone")

    def test_ventura_wake_word_parse(self):
        """``ventura play air horn`` → (play, air horn)."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura play air horn", wake_words=["ventura"])
        assert result == ("play", "air horn")

    def test_ventura_wake_word_with_comma(self):
        """``ventura, play sad trombone`` → (play, sad trombone)."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura, play sad trombone", wake_words=["ventura"])
        assert result == ("play", "sad trombone")


    # ------------------------------------------------------------------
    # Mixed-language / wake-word-anywhere parser tests
    # ------------------------------------------------------------------

    def test_wake_word_anywhere_with_preamble(self):
        """Exact user log sample: preamble before wake word is ignored.

        ``What the fuck was that? Ventura, play das páginas.``
        """
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command(
            "What the fuck was that? Ventura, play das páginas.",
            wake_words=["ventura"],
        )
        assert result == ("play", "das páginas")

    def test_portuguese_toca_verb(self):
        """``ventura toca das páginas`` → (play, das páginas)."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command(
            "ventura toca das páginas",
            wake_words=["ventura"],
        )
        assert result == ("play", "das páginas")

    def test_portuguese_toca_with_preamble(self):
        """``olha ventura, toca das páginas`` → (play, das páginas)."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command(
            "olha ventura, toca das páginas",
            wake_words=["ventura"],
        )
        assert result == ("play", "das páginas")

    def test_portuguese_poe_verb_with_accent(self):
        """``ventura põe páginas`` → (play, páginas) preserving accent."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command(
            "ventura põe páginas",
            wake_words=["ventura"],
        )
        assert result == ("play", "páginas")

    def test_uses_last_wake_word(self):
        """When multiple wake words appear, use text after the last one."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command(
            "ventura bot play air horn",
            wake_words=["ventura", "bot"],
        )
        # After last wake "bot" → "play air horn"
        assert result == ("play", "air horn")

    def test_all_portuguese_verbs(self):
        """All supported Portuguese verbs map to ``play``."""
        from bot.services.voice_command import parse_voice_command

        verbs = ["toca", "tocar", "mete", "meter", "põe", "poe", "reproduz", "reproduzir"]
        for verb in verbs:
            result = parse_voice_command(
                f"ventura {verb} alguma coisa",
                wake_words=["ventura"],
            )
            assert result == ("play", "alguma coisa"), f"Failed for verb '{verb}'"

    def test_play_without_wake_words_list(self):
        """``play something`` when wake_words=None still works."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("play something", wake_words=None)
        assert result == ("play", "something")

    def test_wake_word_not_found_falls_through(self):
        """When wake word is not in transcript, the full text is used.
        If the full text starts with a command verb, it should match."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command(
            "play something",
            wake_words=["ventura"],  # ventura not in transcript
        )
        assert result == ("play", "something")

    def test_wake_word_not_found_no_command(self):
        """When wake word is not in transcript and no command verb, return None."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command(
            "hello world",
            wake_words=["ventura"],
        )
        assert result is None


# ====================================================================
#  pcm_to_wav
# ====================================================================

class TestPcmToWav:
    """Tests for PCM-to-WAV conversion."""

    def test_valid_wav_header(self):
        """Ensure the output is a valid WAV with correct metadata."""
        from bot.services.voice_command import pcm_to_wav

        # Generate 1 second of silence (48 kHz, stereo, 16-bit)
        pcm = b"\x00\x00" * (48000 * 2)  # 48000 samples/sec * 2 channels * 2 bytes
        wav_bytes = pcm_to_wav(pcm)

        # Read back to verify
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wav:
            assert wav.getnchannels() == 2
            assert wav.getsampwidth() == 2
            assert wav.getframerate() == 48000
            # Allow small tolerance for the frame count (Discord may send slightly fewer)
            assert abs(wav.getnframes() - 48000) < 100

    def test_empty_input(self):
        """Zero-length PCM produces a zero-frame WAV."""
        from bot.services.voice_command import pcm_to_wav

        wav_bytes = pcm_to_wav(bytes())
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wav:
            assert wav.getnchannels() == 2
            assert wav.getnframes() == 0


# ====================================================================
#  GroqWhisperService (unit, no real network)
# ====================================================================

class TestGroqWhisperService:
    """Tests for the Groq Whisper client with mocked HTTP."""

    @pytest.fixture
    def service(self):
        from bot.services.voice_command import GroqWhisperService

        srv = GroqWhisperService()
        srv.api_key = "test-key-123"
        return srv

    @pytest.mark.asyncio
    async def test_transcribe_returns_text(self, service):
        """A successful API response returns the transcript text."""
        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={"text": "hello world"})
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

            result = await service.transcribe(b"fake-wav-data")
            assert result == "hello world"

    @pytest.mark.asyncio
    async def test_transcribe_api_error(self, service):
        """A non-200 response returns None."""
        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 401
            mock_resp.text = AsyncMock(return_value='{"error": "unauthorized"}')
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

            result = await service.transcribe(b"fake-wav-data")
            assert result is None

    @pytest.mark.asyncio
    async def test_transcribe_empty_key(self):
        """When API key is empty, transcribe returns None without network call."""
        from bot.services.voice_command import GroqWhisperService

        srv = GroqWhisperService()
        srv.api_key = ""
        assert srv.is_available is False

        result = await srv.transcribe(b"fake-wav-data")
        assert result is None

    @pytest.mark.asyncio
    async def test_transcribe_empty_response_text(self, service):
        """When response text is empty/whitespace, return None."""
        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={"text": "   "})
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

            result = await service.transcribe(b"fake-wav-data")
            assert result is None

    @pytest.mark.asyncio
    async def test_transcribe_timeout(self, service):
        """A timeout returns None."""
        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_post.side_effect = asyncio.TimeoutError()

            result = await service.transcribe(b"fake-wav-data")
            assert result is None

    # ------------------------------------------------------------------
    # Model default and prompt / language field behaviour
    # ------------------------------------------------------------------

    def test_default_model_is_large_v3_not_turbo(self):
        """Default GROQ_WHISPER_MODEL is ``whisper-large-v3`` (accuracy)."""
        from bot.services.voice_command import GROQ_WHISPER_MODEL
        assert GROQ_WHISPER_MODEL == "whisper-large-v3"

    def test_default_model_and_language_on_service(self, service):
        """Service instance uses the default model and Portuguese language hint."""
        assert service.model == "whisper-large-v3"
        assert service.language == "pt", (
            "Default language should be 'pt' to prevent Whisper translating "
            "Portuguese utterances to English"
        )

    def test_default_prompt_is_empty(self):
        """Default prompt is empty to avoid Whisper prompt hallucinations."""
        from bot.services.voice_command import GROQ_WHISPER_PROMPT
        assert GROQ_WHISPER_PROMPT == ""

    @pytest.mark.asyncio
    async def test_transcribe_sends_temperature_by_default(self, service):
        """By default, temperature ``0`` is sent for deterministic transcription."""
        form_add_field_calls: list[tuple] = []

        original_add_field = aiohttp.FormData.add_field

        def tracking_add_field(self, *args, **kwargs):
            form_add_field_calls.append((args, kwargs))
            return original_add_field(self, *args, **kwargs)

        with patch("bot.services.voice_command.aiohttp.FormData.add_field", tracking_add_field):
            with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
                mock_resp = AsyncMock()
                mock_resp.status = 200
                mock_resp.json = AsyncMock(return_value={"text": "test"})
                mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

                await service.transcribe(b"fake-wav-data")

        temperature_fields = [
            call for call in form_add_field_calls
            if call[0][0] == "temperature"
        ]
        assert len(temperature_fields) == 1
        assert temperature_fields[0][0][1] == "0"

    @pytest.mark.asyncio
    async def test_transcribe_sends_prompt_when_configured(self, service):
        """When ``service.prompt`` is set, it is included as a FormData field."""
        service.prompt = "Custom prompt text"
        # Track FormData.add_field calls to inspect the prompt field
        form_add_field_calls: list[tuple] = []

        original_add_field = aiohttp.FormData.add_field

        def tracking_add_field(self, *args, **kwargs):
            form_add_field_calls.append((args, kwargs))
            return original_add_field(self, *args, **kwargs)

        with patch("bot.services.voice_command.aiohttp.FormData.add_field", tracking_add_field):
            with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
                mock_resp = AsyncMock()
                mock_resp.status = 200
                mock_resp.json = AsyncMock(return_value={"text": "test"})
                mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

                await service.transcribe(b"fake-wav-data")

        prompt_fields = [
            call for call in form_add_field_calls
            if call[0][0] == "prompt"
        ]
        assert len(prompt_fields) == 1
        assert prompt_fields[0][0][1] == "Custom prompt text"

    @pytest.mark.asyncio
    async def test_transcribe_skips_prompt_when_empty(self, service):
        """When ``service.prompt`` is empty, no prompt field is sent."""
        service.prompt = ""
        form_add_field_calls: list[tuple] = []

        original_add_field = aiohttp.FormData.add_field

        def tracking_add_field(self, *args, **kwargs):
            form_add_field_calls.append((args, kwargs))
            return original_add_field(self, *args, **kwargs)

        with patch("bot.services.voice_command.aiohttp.FormData.add_field", tracking_add_field):
            with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
                mock_resp = AsyncMock()
                mock_resp.status = 200
                mock_resp.json = AsyncMock(return_value={"text": "test"})
                mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

                await service.transcribe(b"fake-wav-data")

        prompt_fields = [
            call for call in form_add_field_calls
            if call[0][0] == "prompt"
        ]
        assert len(prompt_fields) == 0

    @pytest.mark.asyncio
    async def test_transcribe_sends_language_by_default(self, service):
        """By default, language ``pt`` is sent as a FormData field."""
        form_add_field_calls: list[tuple] = []

        original_add_field = aiohttp.FormData.add_field

        def tracking_add_field(self, *args, **kwargs):
            form_add_field_calls.append((args, kwargs))
            return original_add_field(self, *args, **kwargs)

        with patch("bot.services.voice_command.aiohttp.FormData.add_field", tracking_add_field):
            with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
                mock_resp = AsyncMock()
                mock_resp.status = 200
                mock_resp.json = AsyncMock(return_value={"text": "test"})
                mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

                await service.transcribe(b"fake-wav-data")

        lang_fields = [
            call for call in form_add_field_calls
            if call[0][0] == "language"
        ]
        assert len(lang_fields) == 1
        assert lang_fields[0][0][1] == "pt"

    @pytest.mark.asyncio
    async def test_transcribe_sends_language_when_configured(self, service):
        """When ``service.language`` is explicitly set, it is included as a FormData field."""
        service.language = "pt"
        form_add_field_calls: list[tuple] = []

        original_add_field = aiohttp.FormData.add_field

        def tracking_add_field(self, *args, **kwargs):
            form_add_field_calls.append((args, kwargs))
            return original_add_field(self, *args, **kwargs)

        with patch("bot.services.voice_command.aiohttp.FormData.add_field", tracking_add_field):
            with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
                mock_resp = AsyncMock()
                mock_resp.status = 200
                mock_resp.json = AsyncMock(return_value={"text": "test"})
                mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

                await service.transcribe(b"fake-wav-data")

        lang_fields = [
            call for call in form_add_field_calls
            if call[0][0] == "language"
        ]
        assert len(lang_fields) == 1
        assert lang_fields[0][0][1] == "pt"

    @pytest.mark.asyncio
    async def test_transcribe_skips_language_when_empty(self, service):
        """When ``service.language`` is explicitly emptied, no language field is sent."""
        service.language = ""
        form_add_field_calls: list[tuple] = []

        original_add_field = aiohttp.FormData.add_field

        def tracking_add_field(self, *args, **kwargs):
            form_add_field_calls.append((args, kwargs))
            return original_add_field(self, *args, **kwargs)

        with patch("bot.services.voice_command.aiohttp.FormData.add_field", tracking_add_field):
            with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
                mock_resp = AsyncMock()
                mock_resp.status = 200
                mock_resp.json = AsyncMock(return_value={"text": "test"})
                mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

                await service.transcribe(b"fake-wav-data")

        lang_fields = [
            call for call in form_add_field_calls
            if call[0][0] == "language"
        ]
        assert len(lang_fields) == 0


# ====================================================================
#  GroqWhisperService debug save
# ====================================================================

class TestGroqWhisperServiceDebugSave:
    """Tests for debug audio file save behavior."""

    @pytest.fixture
    def service(self, tmp_path):
        from bot.services.voice_command import GroqWhisperService

        srv = GroqWhisperService()
        srv.api_key = "test-key-123"
        srv.debug_save_enabled = True
        srv.debug_audio_dir = str(tmp_path)
        srv.debug_audio_keep = 25
        return srv

    @pytest.fixture
    def mock_groq_ok(self):
        """Patch the aiohttp POST to return a 200 with a transcript."""
        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={"text": "hello world"})
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
            yield

    @pytest.mark.asyncio
    async def test_saves_timestamped_and_latest_wav(self, service, mock_groq_ok, tmp_path):
        """When debug save is enabled, a timestamped ``.wav`` and ``latest.wav`` are written."""
        await service.transcribe(b"fake-wav-data")

        latest = tmp_path / "latest.wav"
        assert latest.exists(), "latest.wav should exist"
        assert latest.read_bytes() == b"fake-wav-data"

        ts_files = sorted(tmp_path.glob("groq-whisper-*.wav"))
        assert len(ts_files) == 1, "one timestamped file should exist"
        assert ts_files[0].read_bytes() == b"fake-wav-data"

    @pytest.mark.asyncio
    async def test_disabled_skips_write(self, service, mock_groq_ok, tmp_path):
        """When ``debug_save_enabled`` is False, no debug files are created."""
        service.debug_save_enabled = False

        await service.transcribe(b"fake-wav-data")

        assert not (tmp_path / "latest.wav").exists()
        assert list(tmp_path.glob("groq-whisper-*.wav")) == []

    @pytest.mark.asyncio
    async def test_retention_prunes_old_files(self, service, mock_groq_ok, tmp_path):
        """Only ``debug_audio_keep`` timestamped files survive after prune."""
        service.debug_audio_keep = 3

        # Pre-populate with 5 pre-existing timestamped files (oldest first)
        for i in range(5):
            (tmp_path / f"groq-whisper-20260101T0000000{i}Z.wav").write_bytes(b"old")

        await service.transcribe(b"new-data")

        ts_files = sorted(tmp_path.glob("groq-whisper-*.wav"))
        # 2 oldest pruned + 1 new = 3
        assert len(ts_files) == 3

        filenames = [f.name for f in ts_files]
        # The two oldest should be gone
        assert "groq-whisper-20260101T00000000Z.wav" not in filenames
        assert "groq-whisper-20260101T00000001Z.wav" not in filenames

    @pytest.mark.asyncio
    async def test_retention_keeps_latest_wav(self, service, mock_groq_ok, tmp_path):
        """``latest.wav`` is never pruned by the retention counter."""
        service.debug_audio_keep = 1

        # Pre-populate with a couple old timestamped files
        for i in range(3):
            (tmp_path / f"groq-whisper-20260101T0000000{i}Z.wav").write_bytes(b"old")

        await service.transcribe(b"new-data")

        # latest.wav should still be there
        assert (tmp_path / "latest.wav").exists()
        assert (tmp_path / "latest.wav").read_bytes() == b"new-data"

    @pytest.mark.asyncio
    async def test_save_failure_does_not_block_transcription(self, service, tmp_path):
        """When debug save fails, transcription still returns the transcript."""
        # Point to a non-existent subdirectory that cannot be created
        service.debug_audio_dir = str(tmp_path / "nonexistent")
        # Chmod the tmp_path to read-only so os.makedirs fails
        import stat
        tmp_path.chmod(stat.S_IRUSR | stat.S_IXUSR)  # Remove write permission

        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={"text": "hello world"})
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

            result = await service.transcribe(b"fake-wav-data")
            assert result == "hello world", "transcription should succeed despite debug save failure"

        # Restore permissions for cleanup
        tmp_path.chmod(stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
