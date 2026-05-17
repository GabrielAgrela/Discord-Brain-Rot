"""
Tests for bot/services/voice_command.py – Groq Whisper helpers and parsing.
"""

import asyncio
import io
import json
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
#  build_voice_request_note
# ====================================================================

class TestBuildVoiceRequestNote:
    """Tests for the voice-command display-note helper."""

    def _build(self, transcript: str, wake_words=None):
        from bot.services.voice_command import build_voice_request_note
        return build_voice_request_note(transcript, wake_words=wake_words)

    def test_strips_wake_word(self):
        """``ventura stop doing that`` → ``stop doing that``."""
        result = self._build("ventura stop doing that", wake_words=["ventura"])
        assert result == "stop doing that"

    def test_strips_wake_word_with_comma(self):
        """``ventura, diz qualquer coisa`` → ``diz qualquer coisa``."""
        result = self._build("ventura, diz qualquer coisa", wake_words=["ventura"])
        assert result == "diz qualquer coisa"

    def test_strips_trailing_punctuation(self):
        """``ventura stop doing that.`` → ``stop doing that`` (period stripped)."""
        result = self._build("ventura stop doing that.", wake_words=["ventura"])
        assert result == "stop doing that"

    def test_strips_trailing_exclamation(self):
        """``ventura para!`` → ``para``."""
        result = self._build("ventura para!", wake_words=["ventura"])
        assert result == "para"

    def test_no_wake_word(self):
        """No wake words → original trimmed transcript."""
        result = self._build("hello world", wake_words=None)
        assert result == "hello world"

    def test_empty_wake_words_list(self):
        """Empty wake words list → original trimmed transcript."""
        result = self._build("hello world", wake_words=[])
        assert result == "hello world"

    def test_empty_transcript(self):
        """Empty transcript → empty string."""
        assert self._build("") == ""
        assert self._build("   ") == ""

    def test_wake_word_only(self):
        """Only wake word → fallback to raw trimmed transcript."""
        result = self._build("ventura", wake_words=["ventura"])
        assert result == "ventura"

    def test_no_wake_word_in_transcript(self):
        """Wake word not found → raw trimmed transcript."""
        result = self._build("hello world", wake_words=["ventura"])
        assert result == "hello world"

    def test_ventura_what_time_is_it(self):
        """Realistic: ``ventura what time is it`` → ``what time is it``."""
        result = self._build("ventura what time is it", wake_words=["ventura"])
        assert result == "what time is it"

    def test_multiple_wake_words_uses_last(self):
        """When multiple wake words appear, strip after the last one."""
        result = self._build("bot ventura do something", wake_words=["bot", "ventura"])
        assert result == "do something"


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

    def test_debug_save_defaults_to_false_when_env_unset(self, monkeypatch):
        """When GROQ_WHISPER_DEBUG_SAVE_AUDIO is unset, debug_save_enabled is False."""
        monkeypatch.delenv("GROQ_WHISPER_DEBUG_SAVE_AUDIO", raising=False)
        import importlib
        from bot.services import voice_command

        importlib.reload(voice_command)
        srv = voice_command.GroqWhisperService()
        assert srv.debug_save_enabled is False


# ====================================================================
#  VenturaChatService (unit, no real network)
# ====================================================================

class TestVenturaChatService:
    """Tests for the OpenRouter Ventura chat client with mocked HTTP."""

    @pytest.fixture
    def service(self):
        from bot.services.voice_command import VenturaChatService

        srv = VenturaChatService()
        srv.api_key = "test-openrouter-key"
        return srv

    # ------------------------------------------------------------------
    # Payload construction with history
    # ------------------------------------------------------------------

    def test_payload_includes_system_and_current_transcript_only_when_no_history(self, service):
        """Payload contains system + current user transcript when there is no history."""
        payload = service._build_request_payload("hello ventura", None, "test-key")
        messages = payload["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "hello ventura"

    def test_payload_includes_prior_exchanges(self, service):
        """Prior exchanges appear as user/assistant pairs before the current transcript."""
        service._history["test-key"] = [
            ("first user", "first assistant"),
            ("second user", "second assistant"),
        ]
        payload = service._build_request_payload("third user", None, "test-key")
        messages = payload["messages"]
        # system + 2 pairs + current = 6
        assert len(messages) == 6
        assert messages[0]["role"] == "system"
        assert messages[1] == {"role": "user", "content": "first user"}
        assert messages[2] == {"role": "assistant", "content": "first assistant"}
        assert messages[3] == {"role": "user", "content": "second user"}
        assert messages[4] == {"role": "assistant", "content": "second assistant"}
        assert messages[5] == {"role": "user", "content": "third user"}

    def test_payload_appends_current_transcript_after_history(self, service):
        """Current user transcript is appended after historical exchanges."""
        service._history["test-key"] = [
            ("previous user", "previous assistant"),
        ]
        payload = service._build_request_payload("current query", None, "test-key")
        messages = payload["messages"]
        assert messages[-1] == {"role": "user", "content": "current query"}

    def test_history_capped_at_three_exchanges(self, service):
        """Only the last 3 exchanges are included in the payload."""
        for i in range(5):
            service._append_history("test-key", f"user {i}", f"assistant {i}")
        # History should now have the last 3: (user 2, asst 2), (user 3, asst 3), (user 4, asst 4)
        assert len(service._history["test-key"]) == 3
        assert service._history["test-key"][0] == ("user 2", "assistant 2")
        assert service._history["test-key"][1] == ("user 3", "assistant 3")
        assert service._history["test-key"][2] == ("user 4", "assistant 4")

    def test_payload_respects_cap(self, service):
        """Payload includes at most 3 prior exchanges."""
        for i in range(4):
            service._append_history("test-key", f"old user {i}", f"old assistant {i}")
        payload = service._build_request_payload("current", None, "test-key")
        messages = payload["messages"]
        # system + 3 pairs + current = 8
        assert len(messages) == 8
        # First pair should be old user 1, old assistant 1 (skipping the very first exchange)
        assert messages[1]["content"] == "old user 1"
        assert messages[2]["content"] == "old assistant 1"
        assert messages[3]["content"] == "old user 2"
        assert messages[4]["content"] == "old assistant 2"
        assert messages[5]["content"] == "old user 3"
        assert messages[6]["content"] == "old assistant 3"
        assert messages[7]["content"] == "current"

    # ------------------------------------------------------------------
    # _append_history behaviour
    # ------------------------------------------------------------------

    def test_append_history_creates_key(self, service):
        """_append_history creates the key when it doesn't exist."""
        service._append_history("new-key", "user text", "assistant text")
        assert "new-key" in service._history
        assert service._history["new-key"] == [("user text", "assistant text")]

    def test_append_history_appends_to_existing(self, service):
        """_append_history appends to an existing key."""
        service._history["test-key"] = [("first", "reply1")]
        service._append_history("test-key", "second", "reply2")
        assert service._history["test-key"] == [("first", "reply1"), ("second", "reply2")]

    def test_append_history_trims_to_max(self, service):
        """_append_history trims to _MAX_HISTORY_EXCHANGES when over capacity."""
        for i in range(5):
            service._append_history("test-key", f"user {i}", f"assistant {i}")
        assert len(service._history["test-key"]) == 3
        assert service._history["test-key"][0] == ("user 2", "assistant 2")

    # ------------------------------------------------------------------
    # reply() integration with mocked HTTP
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_reply_success_appends_history(self, service):
        """A successful reply appends to conversation history."""
        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={
                "choices": [{"message": {"content": "[shouts] Isto é uma vergonha!"}}]
            })
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

            result = await service.reply("hello ventura", requester_name="TestUser", conversation_key="test-key")
            assert result == "[shouts] Isto é uma vergonha!"
            assert "test-key" in service._history
            assert service._history["test-key"] == [("hello ventura", "[shouts] Isto é uma vergonha!")]

    @pytest.mark.asyncio
    async def test_reply_api_error_does_not_append(self, service):
        """An API error does not append to conversation history."""
        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 401
            mock_resp.text = AsyncMock(return_value="unauthorized")
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

            result = await service.reply("hello ventura", requester_name="TestUser", conversation_key="test-key")
            assert result is None
            assert "test-key" not in service._history

    @pytest.mark.asyncio
    async def test_reply_empty_response_does_not_append(self, service):
        """An empty response does not append to conversation history."""
        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={
                "choices": [{"message": {"content": "   "}}]
            })
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

            result = await service.reply("hello ventura", requester_name="TestUser", conversation_key="test-key")
            assert result is None
            assert "test-key" not in service._history

    @pytest.mark.asyncio
    async def test_reply_timeout_does_not_append(self, service):
        """A timeout does not append to conversation history."""
        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_post.side_effect = asyncio.TimeoutError()

            result = await service.reply("hello ventura", requester_name="TestUser", conversation_key="test-key")
            assert result is None
            assert "test-key" not in service._history

    @pytest.mark.asyncio
    async def test_reply_empty_api_key(self):
        """When API key is empty, reply returns None without network call."""
        from bot.services.voice_command import VenturaChatService

        srv = VenturaChatService()
        srv.api_key = ""
        assert srv.is_available is False

        result = await srv.reply("hello", requester_name="TestUser", conversation_key="test-key")
        assert result is None

    @pytest.mark.asyncio
    async def test_reply_logs_full_payload(self, service):
        """reply logs the full OpenRouter payload JSON at INFO level,
        including messages content, prior history, and no auth secrets."""
        # Seed some history to verify it appears in the log.
        service._history["test-key"] = [
            ("prior user text", "prior assistant reply"),
        ]
        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={
                "choices": [{"message": {"content": "OK"}}]
            })
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

            with patch("bot.services.voice_command.logger.info") as mock_logger_info:
                result = await service.reply(
                    "current transcript", requester_name="TestUser",
                    conversation_key="test-key",
                )
                assert result == "OK"
                # logger.info should be called exactly once
                mock_logger_info.assert_called_once()
                call_pos_args = mock_logger_info.call_args[0]
                assert "[VenturaChat] Request payload" in call_pos_args[0]
                # The last argument is the JSON payload string.
                payload_json = call_pos_args[-1]
                assert isinstance(payload_json, str)
                # Verify it can be parsed back to a dict.
                payload = json.loads(payload_json)
                assert "messages" in payload
                assert "model" in payload
                # Verify messages contain the system prompt.
                messages = payload["messages"]
                assert messages[0]["role"] == "system"
                # Verify prior history is included.
                assert messages[1] == {"role": "user", "content": "prior user text"}
                assert messages[2] == {"role": "assistant", "content": "prior assistant reply"}
                # Verify current transcript is included.
                assert messages[3] == {"role": "user", "content": "current transcript"}
                # Ensure no API key or Authorization header leaks into log.
                payload_str = json.dumps(payload_json)
                assert "OPENROUTER_API_KEY" not in payload_str
                assert "Authorization" not in payload_str
                assert "Bearer" not in payload_str
                assert "test-openrouter-key" not in payload_str
                # Verify metadata is also in the log format string.
                log_fmt = call_pos_args[0]
                assert "conversation_key" in log_fmt
                assert "context_exchanges" in log_fmt

    # ------------------------------------------------------------------
    # conversation_key fallback behaviour
    # ------------------------------------------------------------------

    def test_build_payload_default_key_when_no_key_given(self, service):
        """_build_request_payload uses 'default' as the fallback key."""
        payload = service._build_request_payload("hello", None)
        # No history for 'default', so only system + current
        assert len(payload["messages"]) == 2

    def test_build_payload_uses_key_to_lookup_history(self, service):
        """_build_request_payload uses conversation_key to look up history."""
        service._history["guild:1:user:42"] = [("prev", "resp")]
        payload = service._build_request_payload("now", None, conversation_key="guild:1:user:42")
        assert len(payload["messages"]) == 4  # system + pair + current

    def test_different_keys_have_independent_histories(self, service):
        """Two different conversation keys maintain separate histories."""
        service._append_history("key-a", "user a1", "asst a1")
        service._append_history("key-b", "user b1", "asst b1")
        assert len(service._history["key-a"]) == 1
        assert len(service._history["key-b"]) == 1
        assert service._history["key-a"] != service._history["key-b"]
