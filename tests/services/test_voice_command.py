"""
Tests for bot/services/voice_command.py – Groq Whisper helpers and parsing.
"""

import asyncio
import io
import json
import os
import sys
import time
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
        """``bot toca air horn`` → (play, air horn)."""
        result = self._parse("bot toca air horn")
        assert result == ("play", "air horn")

    def test_wake_word_with_comma(self):
        """``bot, toca sad trombone`` → (play, sad trombone)."""
        result = self._parse("bot, toca sad trombone")
        assert result == ("play", "sad trombone")

    def test_wake_word_with_punctuation(self):
        """``bot toca music.`` → (play, music)."""
        result = self._parse("bot toca music.")
        assert result == ("play", "music")

    def test_play_without_wake_word(self):
        """``toca something`` → (play, something) even without wake word."""
        result = self._parse("toca something")
        assert result == ("play", "something")

    def test_english_play_recognised(self):
        """English ``play`` is recognised as a Ventura voice command verb."""
        from bot.services.voice_command import parse_voice_command
        # Without wake word
        assert self._parse("play something") == ("play", "something")
        # With wake word
        assert parse_voice_command("ventura play air horn", wake_words=["ventura"]) == ("play", "air horn")
        # With wake word and comma
        assert parse_voice_command("ventura, play air horn", wake_words=["ventura"]) == ("play", "air horn")

    def test_empty_transcript(self):
        """Empty / whitespace-only → None."""
        assert self._parse("") is None
        assert self._parse("   ") is None

    def test_no_play_command(self):
        """Transcript without ``play`` → None."""
        assert self._parse("bot stop") is None
        assert self._parse("hello world") is None

    def test_play_without_argument(self):
        """``bot toca`` with nothing after → None."""
        assert self._parse("bot toca") is None
        assert self._parse("toca") is None

    def test_excessively_long_name(self):
        """Excessively long sound name → None."""
        long_name = "a" * 300
        assert self._parse(f"bot toca {long_name}") is None

    def test_case_insensitive(self):
        """``Bot TOCA Air Horn`` → (play, Air Horn) — original case preserved in sound name."""
        result = self._parse("Bot TOCA Air Horn")
        # Sound-name casing is preserved (not lowercased) so actual filenames match.
        assert result == ("play", "Air Horn")

    def test_strips_quotes(self):
        """``bot toca "my sound"`` → (play, my sound)."""
        result = self._parse('bot toca "my sound"')
        assert result == ("play", "my sound")

    def test_strips_smart_quotes(self):
        """``bot toca \u201cmy sound\u201d`` → (play, my sound)."""
        result = self._parse("bot toca \u201cmy sound\u201d")
        assert result == ("play", "my sound")

    def test_wake_word_only(self):
        """Just the wake word with nothing else → None."""
        assert self._parse("bot") is None

    def test_alias_wake_word_parse(self):
        """Vosk alias ``bote toca air horn`` → (play, air horn)."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("bote toca air horn", wake_words=["bot", "bote"])
        assert result == ("play", "air horn")

    def test_alias_wake_word_with_comma(self):
        """``bote, toca sad trombone`` → (play, sad trombone)."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("bote, toca sad trombone", wake_words=["bot", "bote"])
        assert result == ("play", "sad trombone")

    def test_ventura_wake_word_parse(self):
        """``ventura toca air horn`` → (play, air horn)."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura toca air horn", wake_words=["ventura"])
        assert result == ("play", "air horn")

    def test_ventura_wake_word_with_comma(self):
        """``ventura, toca sad trombone`` → (play, sad trombone)."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura, toca sad trombone", wake_words=["ventura"])
        assert result == ("play", "sad trombone")


    # ------------------------------------------------------------------
    # Mixed-language / wake-word-anywhere parser tests
    # ------------------------------------------------------------------

    def test_wake_word_anywhere_with_preamble(self):
        """Preamble before wake word is ignored.

        ``What the fuck was that? Ventura, toca das páginas.``
        """
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command(
            "What the fuck was that? Ventura, toca das páginas.",
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
            "ventura bot toca air horn",
            wake_words=["ventura", "bot"],
        )
        # After last wake "bot" → "toca air horn"
        assert result == ("play", "air horn")

    def test_all_portuguese_verbs(self):
        """All supported Portuguese verbs map to ``play``."""
        from bot.services.voice_command import parse_voice_command

        verbs = ["toca", "tocar", "toque", "mete", "meter", "põe", "poe", "reproduz", "reproduzir"]
        for verb in verbs:
            result = parse_voice_command(
                f"ventura {verb} alguma coisa",
                wake_words=["ventura"],
            )
            assert result == ("play", "alguma coisa"), f"Failed for verb '{verb}'"

    def test_play_without_wake_words_list(self):
        """``toca something`` when wake_words=None still works."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("toca something", wake_words=None)
        assert result == ("play", "something")

    def test_wake_word_not_found_falls_through(self):
        """When wake word is not in transcript, the full text is used.
        If the full text starts with a command verb, it should match."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command(
            "toca something",
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

    # ------------------------------------------------------------------
    #  Mute command parsing
    # ------------------------------------------------------------------

    def test_wake_word_mute(self):
        """``bot mute`` → (mute, '')."""
        result = self._parse("bot mute")
        assert result == ("mute", "")

    def test_wake_word_mute_punctuation(self):
        """``bot mute.`` → (mute, '')."""
        result = self._parse("bot mute.")
        assert result == ("mute", "")

    def test_mute_without_wake_word(self):
        """``mute`` → (mute, '') even without wake word."""
        result = self._parse("mute")
        assert result == ("mute", "")

    def test_mute_case_insensitive(self):
        """``Bot MUTE`` → (mute, '')."""
        result = self._parse("Bot MUTE")
        assert result == ("mute", "")

    def test_ventura_mute(self):
        """``ventura mute`` → (mute, '')."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura mute", wake_words=["ventura"])
        assert result == ("mute", "")

    def test_ventura_mute_punctuation(self):
        """``ventura mute.`` → (mute, '')."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura mute.", wake_words=["ventura"])
        assert result == ("mute", "")

    def test_ventura_mute_with_comma(self):
        """``ventura, mute.`` → (mute, '')."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura, mute.", wake_words=["ventura"])
        assert result == ("mute", "")

    def test_play_still_requires_argument(self):
        """``play`` (without mute) should still return None (no argument)."""
        assert self._parse("play") is None

    # ------------------------------------------------------------------
    #  Mute aliases (cala-te, silêncio, shut up, etc.)
    # ------------------------------------------------------------------

    def test_wake_word_cala_te_hyphen(self):
        """``bot cala-te`` → (mute, '')."""
        result = self._parse("bot cala-te")
        assert result == ("mute", "")

    def test_wake_word_cala_te_space(self):
        """``bot cala te`` → (mute, '')."""
        result = self._parse("bot cala te")
        assert result == ("mute", "")

    def test_wake_word_calate_fused(self):
        """``bot calate`` → (mute, '')."""
        result = self._parse("bot calate")
        assert result == ("mute", "")

    def test_wake_word_silencio_accent(self):
        """``bot silêncio`` → (mute, '')."""
        result = self._parse("bot silêncio")
        assert result == ("mute", "")

    def test_wake_word_silencio_no_accent(self):
        """``bot silencio`` → (mute, '')."""
        result = self._parse("bot silencio")
        assert result == ("mute", "")

    def test_wake_word_shut_up(self):
        """``bot shut up`` → (mute, '')."""
        result = self._parse("bot shut up")
        assert result == ("mute", "")

    def test_wake_word_shutup_fused(self):
        """``bot shutup`` → (mute, '')."""
        result = self._parse("bot shutup")
        assert result == ("mute", "")

    def test_wake_word_quiet(self):
        """``bot quiet`` → (mute, '')."""
        result = self._parse("bot quiet")
        assert result == ("mute", "")

    def test_ventura_cala_te(self):
        """``ventura cala-te`` → (mute, '')."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura cala-te", wake_words=["ventura"])
        assert result == ("mute", "")

    def test_ventura_cala_te_punctuation(self):
        """``ventura cala-te.`` → (mute, '')."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura cala-te.", wake_words=["ventura"])
        assert result == ("mute", "")

    def test_ventura_silencio(self):
        """``ventura silêncio`` → (mute, '')."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura silêncio", wake_words=["ventura"])
        assert result == ("mute", "")

    def test_ventura_quiet(self):
        """``ventura quiet`` → (mute, '')."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura quiet", wake_words=["ventura"])
        assert result == ("mute", "")

    def test_play_still_works_with_mute_alias_sound_name(self):
        """``ventura toca cala-te`` → (play, cala-te), not mute."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura toca cala-te", wake_words=["ventura"])
        assert result == ("play", "cala-te")

    def test_play_still_works_with_silencio_sound_name(self):
        """``ventura toca silêncio`` → (play, silêncio), not mute."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura toca silêncio", wake_words=["ventura"])
        assert result == ("play", "silêncio")

    def test_english_play_works_with_mute_alias_sound_name(self):
        """``ventura play cala-te`` → (play, cala-te), not mute."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura play cala-te", wake_words=["ventura"])
        assert result == ("play", "cala-te")

    # ------------------------------------------------------------------
    #  toque (Whisper variant of toca)
    # ------------------------------------------------------------------

    def test_toque_verb(self):
        """``ventura toque farts`` → (play, farts) — Whisper variant."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura toque farts", wake_words=["ventura"])
        assert result == ("play", "farts")

    def test_toque_punctuation(self):
        """``ventura toque farts.`` → (play, farts)."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura toque farts.", wake_words=["ventura"])
        assert result == ("play", "farts")

    def test_toque_case_insensitive(self):
        """``ventura Toque Farts`` → (play, Farts)."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("ventura Toque Farts", wake_words=["ventura"])
        assert result == ("play", "Farts")

    def test_toque_without_wake_word(self):
        """``toque something`` → (play, something) even without wake word."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("toque something", wake_words=None)
        assert result == ("play", "something")

    def test_toque_with_wake_word_not_present(self):
        """``toque something`` with a non-present wake word still works."""
        from bot.services.voice_command import parse_voice_command
        result = parse_voice_command("toque something", wake_words=["ventura"])
        assert result == ("play", "something")

    def test_english_play_recognised_with_toque(self):
        """English ``play`` remains recognised alongside ``toque``."""
        from bot.services.voice_command import parse_voice_command
        assert parse_voice_command("ventura play air horn", wake_words=["ventura"]) == ("play", "air horn")


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


# ------------------------------------------------------------------
#  GroqWhisperService transcribe_detailed — rate-limit handling
# ------------------------------------------------------------------

class TestGroqWhisperServiceDetailed:
    """Tests for ``GroqWhisperService.transcribe_detailed()``."""

    @pytest.fixture
    def service(self):
        from bot.services.voice_command import GroqWhisperService

        srv = GroqWhisperService()
        srv.api_key = "test-key-123"
        return srv

    @pytest.mark.asyncio
    async def test_detailed_429_with_retry_after(self, service):
        """429 response with Retry-After header returns status_code + retry_after."""
        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 429
            mock_resp.text = AsyncMock(return_value='{"error": "rate limited"}')
            mock_resp.headers = {"Retry-After": "30"}
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

            result = await service.transcribe_detailed(b"fake-wav-data")

        assert result.is_available is True
        assert result.status_code == 429
        assert result.retry_after_seconds == 30.0
        assert "rate limited" in result.error

    @pytest.mark.asyncio
    async def test_detailed_429_without_retry_after(self, service):
        """429 response without Retry-After header returns None retry_after."""
        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 429
            mock_resp.text = AsyncMock(return_value="{}")
            mock_resp.headers = {}
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

            result = await service.transcribe_detailed(b"fake-wav-data")

        assert result.status_code == 429
        assert result.retry_after_seconds is None
        assert "rate limited" in result.error

    @pytest.mark.asyncio
    async def test_detailed_non_429_error(self, service):
        """Non-429 error (e.g. 500) returns status_code but no retry_after."""
        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 500
            mock_resp.text = AsyncMock(return_value="internal error")
            mock_resp.headers = {}
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

            result = await service.transcribe_detailed(b"fake-wav-data")

        assert result.is_available is True
        assert result.status_code == 500
        assert result.retry_after_seconds is None
        assert "API error 500" in result.error

    @pytest.mark.asyncio
    async def test_detailed_empty_key(self, service):
        """No API key → no status_code (no request made)."""
        service.api_key = ""
        result = await service.transcribe_detailed(b"fake-wav-data")
        assert result.is_available is False
        assert result.status_code is None
        assert result.error == "GROQ_API_KEY not set"

    @pytest.mark.asyncio
    async def test_detailed_429_unparseable_retry_after(self, service):
        """Unparseable Retry-After string does not crash, returns None."""
        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 429
            mock_resp.text = AsyncMock(return_value="{}")
            mock_resp.headers = {"Retry-After": "not-a-number"}
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

            result = await service.transcribe_detailed(b"fake-wav-data")

        assert result.status_code == 429
        assert result.retry_after_seconds is None


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
    """Tests for the Ventura chat LLM client with mocked HTTP."""

    @pytest.fixture
    def service(self):
        from bot.services.voice_command import VenturaChatService

        srv = VenturaChatService()
        srv.api_key = "test-llm-key"
        return srv

    def test_default_model_is_deepseek_v4_flash(self, service):
        """Default model is DeepSeek V4 Flash through DeepSeek's API."""
        assert service.llm_provider == "deepseek"
        assert service.model == "deepseek-v4-flash"
        assert service.temperature == 0.95
        assert service.reasoning_effort == "none"

    def test_default_speed_settings(self, service):
        """Verify new defaults tailored for fast responses."""
        assert service.max_tokens == 250
        assert service.provider_sort == ""
        assert service.log_payload is False

    def test_openrouter_payload_includes_provider_sort_when_no_db_settings(self, service):
        """OpenRouter payload includes sort when provider_sort is set but no DB settings."""
        service.llm_provider = "openrouter"
        service.provider_sort = "throughput"
        payload = service._build_request_payload("hello", None)
        assert "provider" in payload
        assert payload["provider"] == {"sort": "throughput"}

    def test_payload_has_no_provider_when_no_settings(self, service):
        """Payload has no provider field when no DB provider and no provider_sort."""
        service.provider_sort = ""
        payload = service._build_request_payload("hello", None)
        assert "provider" not in payload

    def test_deepseek_payload_ignores_openrouter_provider_sort(self, service):
        """DeepSeek payload does not include OpenRouter provider routing."""
        service.provider_sort = "throughput"
        payload = service._build_request_payload("hello", None)
        assert "provider" not in payload

    def test_payload_includes_provider_order_from_settings_service(self):
        """When settings_service provides a provider, use order + allow_fallbacks."""
        from bot.services.voice_command import VenturaChatService

        class FakeSettingsService:
            def get_ventura_chat_settings(self):
                return {
                    "model": "deepseek-v4-flash",
                    "provider": "crucible",
                    "stored_model": None,
                    "stored_provider": "crucible",
                    "default_model": "deepseek-v4-flash",
                    "default_provider": "",
                }

        srv = VenturaChatService(settings_service=FakeSettingsService())
        srv.llm_provider = "openrouter"
        srv.api_key = "test-openrouter-key"
        payload = srv._build_request_payload("hello", None)
        assert payload["provider"] == {"order": ["crucible"], "allow_fallbacks": False}

    def test_payload_includes_model_from_settings_service(self):
        """OpenRouter uses the model override from settings_service."""
        from bot.services.voice_command import VenturaChatService

        class FakeSettingsService:
            def get_ventura_chat_settings(self):
                return {
                    "model": "override-model",
                    "provider": "",
                    "stored_model": "override-model",
                    "stored_provider": None,
                    "default_model": "deepseek-v4-flash",
                    "default_provider": "",
                }

        srv = VenturaChatService(settings_service=FakeSettingsService())
        srv.llm_provider = "openrouter"
        srv.api_key = "test-llm-key"
        payload = srv._build_request_payload("hello", None)
        assert payload["model"] == "override-model"
        assert "provider" not in payload

    def test_deepseek_payload_ignores_stale_openrouter_model_from_settings_service(self):
        """DeepSeek keeps its configured model even when DB settings contain OpenRouter data."""
        from bot.services.voice_command import VenturaChatService

        class FakeSettingsService:
            def get_ventura_chat_settings(self):
                return {
                    "model": "qwen/qwen3-32b",
                    "provider": "deepinfra",
                    "stored_model": "qwen/qwen3-32b",
                    "stored_provider": "deepinfra",
                    "default_model": "deepseek-v4-flash",
                    "default_provider": "",
                }

        srv = VenturaChatService(settings_service=FakeSettingsService())
        srv.api_key = "test-llm-key"
        payload = srv._build_request_payload("hello", None)
        assert payload["model"] == "deepseek-v4-flash"
        assert payload["thinking"] == {"type": "disabled"}
        assert "reasoning_effort" not in payload
        assert "provider" not in payload

    def test_payload_settings_service_provider_takes_precedence_over_sort(self):
        """When settings_service provides a provider, sort is not used even if set."""
        from bot.services.voice_command import VenturaChatService

        class FakeSettingsService:
            def get_ventura_chat_settings(self):
                return {
                    "model": "some-model",
                    "provider": "deepinfra",
                    "stored_model": None,
                    "stored_provider": "deepinfra",
                    "default_model": "deepseek-v4-flash",
                    "default_provider": "",
                }

        srv = VenturaChatService(settings_service=FakeSettingsService())
        srv.llm_provider = "openrouter"
        srv.api_key = "test-openrouter-key"
        srv.provider_sort = "throughput"  # legacy sort also set
        payload = srv._build_request_payload("hello", None)
        # provider order must be used, not sort
        assert "sort" not in payload.get("provider", {})
        assert payload["provider"] == {"order": ["deepinfra"], "allow_fallbacks": False}

    def test_payload_settings_service_error_falls_back(self, service):
        """When settings_service raises, fall back to constructor defaults."""
        class BrokenSettingsService:
            def get_ventura_chat_settings(self):
                raise RuntimeError("DB error")

        from bot.services.voice_command import VenturaChatService
        srv = VenturaChatService(settings_service=BrokenSettingsService())
        srv.api_key = "test-llm-key"
        # No sort by default (provider_sort is "")
        payload = srv._build_request_payload("hello", None)
        assert "provider" not in payload

    @pytest.mark.asyncio
    async def test_compact_logging(self, service):
        """When log_payload is False, only a compact summary is logged."""
        service.log_payload = False
        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={
                "choices": [{"message": {"content": "OK"}}]
            })
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

            with patch("bot.services.voice_command.logger.info") as mock_logger_info:
                await service.reply("test transcript")
                # Should log request summary and completion time
                assert mock_logger_info.call_count == 2
                summary_call = None
                for call_args in mock_logger_info.call_args_list:
                    if "[VenturaChat] Request summary" in call_args[0][0]:
                        summary_call = call_args
                        break
                assert summary_call is not None
                # Assert summary contains metadata but not full messages
                log_fmt = summary_call[0][0]
                assert "Request summary" in log_fmt
                assert "max_tokens" in log_fmt
                assert "provider" in log_fmt
                assert "provider_sort" not in log_fmt

    def test_payload_includes_no_reasoning_when_disabled(self, service):
        """OpenRouter payload includes reasoning={"enabled": False} when disabled."""
        service.llm_provider = "openrouter"
        service.reasoning_enabled = False
        payload = service._build_request_payload("hello", None)
        assert "reasoning" in payload
        assert payload["reasoning"] == {"enabled": False}

    def test_payload_excludes_no_reasoning_when_enabled(self, service):
        """OpenRouter payload does not contain reasoning field when reasoning is enabled."""
        service.llm_provider = "openrouter"
        service.reasoning_enabled = True
        payload = service._build_request_payload("hello", None)
        assert "reasoning" not in payload

    def test_deepseek_payload_disables_thinking_by_default(self, service):
        """DeepSeek payload disables thinking by default."""
        payload = service._build_request_payload("hello", None)
        assert payload["thinking"] == {"type": "disabled"}
        assert "reasoning_effort" not in payload
        assert "reasoning" not in payload

    def test_deepseek_payload_includes_reasoning_effort_when_enabled(self, service):
        """DeepSeek payload can enable thinking with supported effort values."""
        service.reasoning_enabled = True
        service.reasoning_effort = "high"
        payload = service._build_request_payload("hello", None)
        assert payload["thinking"] == {"type": "enabled"}
        assert payload["reasoning_effort"] == "high"

    def test_openrouter_headers_include_app_metadata(self, service):
        """OpenRouter requests include app metadata headers."""
        service.llm_provider = "openrouter"
        headers = service._build_headers()
        assert headers["Authorization"] == "Bearer test-llm-key"
        assert "HTTP-Referer" in headers
        assert "X-Title" in headers

    def test_deepseek_headers_omit_openrouter_metadata(self, service):
        """DeepSeek requests only include generic OpenAI-compatible headers."""
        headers = service._build_headers()
        assert headers["Authorization"] == "Bearer test-llm-key"
        assert "HTTP-Referer" not in headers
        assert "X-Title" not in headers

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
        now = time.monotonic()
        service._history["test-key"] = [
            (now, "first user", "first assistant"),
            (now, "second user", "second assistant"),
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
            (time.monotonic(), "previous user", "previous assistant"),
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
        assert service._history["test-key"][0][1] == "user 2"
        assert service._history["test-key"][0][2] == "assistant 2"
        assert service._history["test-key"][1][1] == "user 3"
        assert service._history["test-key"][1][2] == "assistant 3"
        assert service._history["test-key"][2][1] == "user 4"
        assert service._history["test-key"][2][2] == "assistant 4"

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
    # History retention (TTL) behaviour
    # ------------------------------------------------------------------

    def test_payload_includes_fresh_history_within_retention(self, service):
        """Unexpired entries (age < retention) appear in the payload."""
        service._history["test-key"] = [
            (time.monotonic(), "user msg", "asst reply"),
        ]
        payload = service._build_request_payload("current", None, "test-key")
        messages = payload["messages"]
        assert len(messages) == 4  # system + pair + current
        assert messages[1]["content"] == "user msg"
        assert messages[2]["content"] == "asst reply"

    def test_payload_excludes_expired_history(self, service):
        """Entries older than retention_seconds are excluded from the payload."""
        old_ts = time.monotonic() - service.history_retention_seconds - 1
        service._history["test-key"] = [
            (old_ts, "old user", "old asst"),
        ]
        payload = service._build_request_payload("current", None, "test-key")
        messages = payload["messages"]
        # Only system + current (history was pruned)
        assert len(messages) == 2

    def test_prune_history_removes_expired_before_append(self, service):
        """_append_history prunes expired entries before adding the new one."""
        old_ts = time.monotonic() - service.history_retention_seconds - 1
        service._history["test-key"] = [
            (old_ts, "old user", "old asst"),
            (old_ts, "old user 2", "old asst 2"),
        ]
        service._append_history("test-key", "new user", "new asst")
        assert len(service._history["test-key"]) == 1
        entry = service._history["test-key"][0]
        assert entry[1] == "new user"
        assert entry[2] == "new asst"

    def test_empty_key_deleted_after_prune(self, service):
        """A conversation key is removed when all its entries expire."""
        old_ts = time.monotonic() - service.history_retention_seconds - 1
        service._history["test-key"] = [(old_ts, "old", "old")]
        service._prune_history("test-key")
        assert "test-key" not in service._history

    def test_retention_zero_clears_history(self, service):
        """Setting retention_seconds to 0 effectively disables history."""
        now = time.monotonic()
        service._history["test-key"] = [(now, "fresh", "still fresh")]
        service.history_retention_seconds = 0
        payload = service._build_request_payload("current", None, "test-key")
        messages = payload["messages"]
        assert len(messages) == 2  # Only system + current

    def test_payload_cap_still_applies_among_unexpired(self, service):
        """Only the last 3 unexpired exchanges are included when more exist."""
        now = time.monotonic()
        for i in range(5):
            service._append_history("test-key", f"user {i}", f"asst {i}")
        # All entries are fresh, so only last 3 remain after cap + prune.
        assert len(service._history["test-key"]) == 3
        # Confirm they are the most recent 3.
        entries = service._history["test-key"]
        assert entries[0][1] == "user 2"
        assert entries[1][1] == "user 3"
        assert entries[2][1] == "user 4"

    # ------------------------------------------------------------------
    # _append_history behaviour
    # ------------------------------------------------------------------

    def test_append_history_creates_key(self, service):
        """_append_history creates the key when it doesn't exist."""
        service._append_history("new-key", "user text", "assistant text")
        assert "new-key" in service._history
        assert len(service._history["new-key"]) == 1
        entry = service._history["new-key"][0]
        assert isinstance(entry[0], float)  # timestamp
        assert entry[1] == "user text"
        assert entry[2] == "assistant text"

    def test_append_history_appends_to_existing(self, service):
        """_append_history appends to an existing key."""
        now = time.monotonic()
        service._history["test-key"] = [(now, "first", "reply1")]
        service._append_history("test-key", "second", "reply2")
        assert len(service._history["test-key"]) == 2
        assert service._history["test-key"][0][1] == "first"
        assert service._history["test-key"][0][2] == "reply1"
        assert service._history["test-key"][1][1] == "second"
        assert service._history["test-key"][1][2] == "reply2"

    def test_append_history_trims_to_max(self, service):
        """_append_history trims to _MAX_HISTORY_EXCHANGES when over capacity."""
        for i in range(5):
            service._append_history("test-key", f"user {i}", f"assistant {i}")
        assert len(service._history["test-key"]) == 3
        assert service._history["test-key"][0][1] == "user 2"
        assert service._history["test-key"][0][2] == "assistant 2"

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
            assert len(service._history["test-key"]) == 1
            entry = service._history["test-key"][0]
            assert isinstance(entry[0], float)  # timestamp
            assert entry[1] == "TestUser: hello ventura"
            assert entry[2] == "[shouts] Isto é uma vergonha!"

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
        """reply logs the full LLM payload JSON at INFO level,
        including messages content, prior history, and no auth secrets."""
        # Seed some history to verify it appears in the log.
        service.log_payload = True
        service._history["test-key"] = [
            (time.monotonic(), "prior user text", "prior assistant reply"),
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
                # logger.info should be called twice (payload log + timing log)
                assert mock_logger_info.call_count == 2
                
                # Check payload log call
                payload_call = None
                for call_args in mock_logger_info.call_args_list:
                    if "[VenturaChat] Request payload" in call_args[0][0]:
                        payload_call = call_args
                        break
                
                assert payload_call is not None
                call_pos_args = payload_call[0]
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
                assert messages[3] == {"role": "user", "content": "TestUser: current transcript"}
                # Ensure no API key or Authorization header leaks into log.
                payload_str = json.dumps(payload_json)
                assert "OPENROUTER_API_KEY" not in payload_str
                assert "Authorization" not in payload_str
                assert "Bearer" not in payload_str
                assert "test-llm-key" not in payload_str
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
        service._history["guild:1:user:42"] = [(time.monotonic(), "prev", "resp")]
        payload = service._build_request_payload("now", None, conversation_key="guild:1:user:42")
        assert len(payload["messages"]) == 4  # system + pair + current

    def test_different_keys_have_independent_histories(self, service):
        """Two different conversation keys maintain separate histories."""
        service._append_history("key-a", "user a1", "asst a1")
        service._append_history("key-b", "user b1", "asst b1")
        assert len(service._history["key-a"]) == 1
        assert len(service._history["key-b"]) == 1
        assert service._history["key-a"] != service._history["key-b"]

    def test_format_user_transcript_with_requester_name(self, service):
        """_format_user_transcript adds username prefix when provided."""
        res = service._format_user_transcript("hello", "sopustos")
        assert res == "sopustos: hello"

    def test_format_user_transcript_without_requester_name(self, service):
        """_format_user_transcript returns transcript only when username is empty/None."""
        assert service._format_user_transcript("hello", None) == "hello"
        assert service._format_user_transcript("hello", "") == "hello"
        assert service._format_user_transcript("hello", "   ") == "hello"

    def test_payload_includes_requester_name_in_user_message(self, service):
        """_build_request_payload prefixes the current user message if requester_name is provided."""
        payload = service._build_request_payload("hello ventura", "sopustos", "test-key")
        messages = payload["messages"]
        assert messages[-1]["content"] == "sopustos: hello ventura"

    @pytest.mark.asyncio
    async def test_reply_appends_prefixed_transcript_to_history(self, service):
        """A successful reply appends the username-prefixed transcript to the conversation history."""
        with patch("bot.services.voice_command.aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={
                "choices": [{"message": {"content": "Olá"}}]
            })
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

            await service.reply("how are you", requester_name="sopustos", conversation_key="test-key")
            assert len(service._history["test-key"]) == 1
            entry = service._history["test-key"][0]
            assert isinstance(entry[0], float)  # timestamp
            assert entry[1] == "sopustos: how are you"
            assert entry[2] == "Olá"
