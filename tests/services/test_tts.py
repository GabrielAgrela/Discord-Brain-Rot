"""
Tests for bot/tts.py — ElevenLabs TTS optimization (streaming, direct-write, perf logging).

These tests use mocked aiohttp and file I/O to avoid real API calls and real Discord.
"""

import asyncio
import io
import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import bot.tts as bot_tts_module
from bot.tts import (
    TTS, _write_all_to_fd,
    ElevenLabsAPIError, ElevenLabsQuotaExceededError,
    _check_el_quota_exceeded, _build_el_error,
)


# ============================================================================
# Helper: build a TTS instance with minimal deps
# ============================================================================

def make_tts(**overrides):
    """Create a TTS instance with minimal mocked dependencies."""
    behavior = MagicMock()
    bot = MagicMock()
    tts = TTS(behavior, bot, filename="test.mp3", cooldown_seconds=0)
    for key, value in overrides.items():
        setattr(tts, key, value)
    tts.voice_id = overrides.get("voice_id", "test_voice_id")
    return tts


# ============================================================================
# Helper: build a mock aiohttp response
# ============================================================================

def mock_response(status=200, content_bytes=b"", content_chunks=None):
    """Return a MagicMock that acts as an async aiohttp response."""
    resp = MagicMock()
    resp.status = status
    resp.read = AsyncMock(return_value=content_bytes)
    resp.text = AsyncMock(return_value="fake error body")

    # The response must be an async context manager
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)

    # Content for streaming
    content = MagicMock()
    if content_chunks is not None:
        async def _iter():
            for c in content_chunks:
                yield c
        content.iter_chunked = MagicMock(return_value=_iter())
    else:
        async def _iter_one():
            yield content_bytes
        content.iter_chunked = MagicMock(return_value=_iter_one())

    resp.content = content
    return resp


def mock_session(post_response=None):
    """Return a MagicMock that acts as an async aiohttp session.

    Important: ``sess.post`` is a plain MagicMock (not AsyncMock) that returns
    the response object directly. The production code uses
    ``async with session.post(...) as response``, which expects the return
    value of ``post()`` (not a coroutine) to be an async context manager.
    """
    resp = post_response or mock_response()
    sess = MagicMock()
    sess.__aenter__ = AsyncMock(return_value=sess)
    sess.__aexit__ = AsyncMock(return_value=None)
    sess.post = MagicMock(return_value=resp)
    return sess


# ============================================================================
# _build_el_tts_url
# ============================================================================

class TestBuildElTtsUrl:
    def test_non_streaming_no_latency(self):
        tts = make_tts(el_tts_streaming_enabled=False,
                       el_tts_optimize_streaming_latency=None,
                       el_tts_output_format="mp3_44100_128")
        url = tts._build_el_tts_url()
        assert "text-to-speech/test_voice_id" in url
        assert "/stream" not in url
        assert "output_format=mp3_44100_128" in url
        assert "optimize_streaming_latency" not in url

    def test_streaming_no_latency(self):
        tts = make_tts(el_tts_streaming_enabled=True,
                       el_tts_optimize_streaming_latency=None,
                       el_tts_output_format="mp3_44100_128")
        url = tts._build_el_tts_url()
        assert "/stream" in url
        assert "output_format=mp3_44100_128" in url
        assert "optimize_streaming_latency" not in url

    def test_v3_omits_latency_even_when_configured(self):
        """eleven_v3 should never receive optimize_streaming_latency."""
        tts = make_tts(el_tts_streaming_enabled=True,
                       el_tts_optimize_streaming_latency=3,
                       el_tts_output_format="mp3_44100_128",
                       el_tts_model_id="eleven_v3")
        url = tts._build_el_tts_url()
        assert "/stream" in url
        assert "output_format=mp3_44100_128" in url
        assert "optimize_streaming_latency" not in url

    def test_streaming_with_latency_non_v3(self):
        """Non-v3 model includes latency when configured."""
        tts = make_tts(el_tts_streaming_enabled=True,
                       el_tts_optimize_streaming_latency=3,
                       el_tts_output_format="mp3_44100_128",
                       el_tts_model_id="eleven_turbo_v2")
        url = tts._build_el_tts_url()
        assert "/stream" in url
        assert "output_format=mp3_44100_128" in url
        assert "optimize_streaming_latency=3" in url

    def test_streaming_with_latency_0_non_v3(self):
        tts = make_tts(el_tts_streaming_enabled=True,
                       el_tts_optimize_streaming_latency=0,
                       el_tts_output_format="mp3_44100_128",
                       el_tts_model_id="eleven_turbo_v2")
        url = tts._build_el_tts_url()
        assert "/stream" in url
        assert "optimize_streaming_latency=0" in url

    def test_non_streaming_with_latency_non_v3(self):
        """Latency param can be included for non-v3 models even when non-streaming."""
        tts = make_tts(el_tts_streaming_enabled=False,
                       el_tts_optimize_streaming_latency=2,
                       el_tts_output_format="mp3_44100_128",
                       el_tts_model_id="eleven_turbo_v2")
        url = tts._build_el_tts_url()
        assert "/stream" not in url
        assert "optimize_streaming_latency=2" in url
        assert "output_format=mp3_44100_128" in url

    def test_custom_output_format(self):
        tts = make_tts(el_tts_streaming_enabled=True,
                       el_tts_optimize_streaming_latency=3,
                       el_tts_output_format="mp3_44100_64",
                       el_tts_model_id="eleven_turbo_v2")
        url = tts._build_el_tts_url()
        assert "output_format=mp3_44100_64" in url

    def test_url_accepts_optional_model_id(self):
        """_build_el_tts_url should use provided model_id for latency logic."""
        tts = make_tts(el_tts_streaming_enabled=True,
                       el_tts_optimize_streaming_latency=3,
                       el_tts_output_format="mp3_44100_128",
                       el_tts_model_id="eleven_turbo_v2")
        # With v3 model_id passed explicitly, latency should be omitted.
        url = tts._build_el_tts_url(model_id="eleven_v3")
        assert "optimize_streaming_latency" not in url
        # With non-v3 model_id, latency should be included.
        url2 = tts._build_el_tts_url(model_id="eleven_turbo_v2")
        assert "optimize_streaming_latency=3" in url2


# ============================================================================
# _effective_el_tts_streaming_latency (optional model_id)
# ============================================================================


class TestEffectiveStreamingLatency:
    def test_uses_instance_model_by_default(self):
        tts = make_tts(el_tts_model_id="eleven_v3",
                       el_tts_optimize_streaming_latency=3)
        assert tts._effective_el_tts_streaming_latency() is None

    def test_accepts_override_model_id(self):
        tts = make_tts(el_tts_model_id="eleven_v3",
                       el_tts_optimize_streaming_latency=3)
        # Override with a non-v3 model should include latency.
        assert tts._effective_el_tts_streaming_latency(model_id="eleven_turbo_v2") == 3

    def test_v3_override_omits_latency(self):
        tts = make_tts(el_tts_model_id="eleven_turbo_v2",
                       el_tts_optimize_streaming_latency=3)
        # Even though instance model is non-v3, passing v3 should omit latency.
        assert tts._effective_el_tts_streaming_latency(model_id="eleven_v3") is None


# ============================================================================
# _log_el_tts_perf (smoke test — just ensures no crash and log output)
# ============================================================================

class TestLogElTtsPerf:
    def test_log_with_chunk_time(self, caplog):
        tts = make_tts()
        import logging
        caplog.set_level(logging.INFO)
        tts._log_el_tts_perf(
            start=100.0,
            first_chunk_time=101.5,
            write_end=102.0,
            url="https://api.test/stream",
            model_id="eleven_v3",
            output_format="mp3_44100_128",
            latency=3,
            text_len=500,
            file_size=12345,
        )
        assert "EL_TTS perf" in caplog.text
        assert "ttf_first=1.500" in caplog.text

    def test_log_without_chunk_time(self, caplog):
        tts = make_tts()
        import logging
        caplog.set_level(logging.INFO)
        tts._log_el_tts_perf(
            start=100.0,
            first_chunk_time=None,
            write_end=105.0,
            url="https://api.test",
            model_id="eleven_v3",
            output_format="mp3_44100_128",
            latency=None,
            text_len=100,
            file_size=None,
        )
        assert "EL_TTS perf" in caplog.text
        assert "total=5.000" in caplog.text


# ============================================================================
# save_as_mp3_EL — integration with fully mocked aiohttp and I/O
# ============================================================================

@patch("bot.tts.aiohttp.ClientSession")
@patch("bot.tts.Database")
@patch("bot.tts.os.path.getsize")
@patch("bot.tts.os.makedirs")
@patch("builtins.open", new_callable=MagicMock)
class TestSaveAsMp3EL:
    """Test that save_as_mp3_EL uses the correct code paths with mocked I/O."""

    def _setup_tts(self, resp, session_cls_mock, **tts_kwargs):
        """Wire mocks and TTS instance. Returns (tts, session, file_handle)."""
        sess = mock_session(post_response=resp)
        session_cls_mock.return_value = sess

        tts = make_tts(cooldown_seconds=0, **tts_kwargs)
        tts.voice_id_pt = tts.voice_id
        tts.behavior.send_message = AsyncMock()
        tts.behavior.play_audio = AsyncMock()
        tts.behavior.send_error_message = AsyncMock()
        return tts, sess

    def test_non_streaming_direct_write(self, mock_open, mock_makedirs,
                                         mock_getsize, mock_db, mock_session_cls):
        """Non-streaming: should read all bytes and write directly (no pydub)."""
        mock_getsize.return_value = 9999
        resp = mock_response(status=200, content_bytes=b"mp3data123")
        tts, sess = self._setup_tts(
            resp, mock_session_cls,
            el_tts_streaming_enabled=False,
            el_tts_optimize_streaming_latency=None,
            el_tts_timeout_seconds=30,
            voice_id="pt_voice",
        )

        asyncio.run(tts.save_as_mp3_EL("hello world", lang="pt"))

        # Posted to non-streaming URL
        posted_url = sess.post.call_args[0][0]
        assert "/stream" not in posted_url

        # Open is called for .env (load_dotenv) and for the sound output file.
        # Verify the sound write included the raw MP3 bytes (no pydub round-trip).
        # We use the mock open's file handle returned by __enter__.
        all_writes = mock_open.return_value.__enter__.return_value.write.call_args_list
        write_data = [args[0][0] for args in all_writes if args[0]]
        assert any(d == b"mp3data123" for d in write_data), (
            f"Raw mp3data123 not found in writes: {write_data}"
        )

        # DB inserted after successful write
        mock_db().insert_sound.assert_called_once()

    def test_streaming_direct_write(self, mock_open, mock_makedirs,
                                     mock_getsize, mock_db, mock_session_cls):
        """Streaming enabled: should write chunks directly to file."""
        mock_getsize.return_value = 9999
        resp = mock_response(
            status=200,
            content_chunks=[b"chunk_a", b"chunk_b", b"chunk_c"],
        )
        tts, sess = self._setup_tts(
            resp, mock_session_cls,
            el_tts_streaming_enabled=True,
            el_tts_optimize_streaming_latency=3,
            el_tts_model_id="eleven_turbo_v2",
            el_tts_timeout_seconds=30,
            voice_id="pt_voice",
        )

        asyncio.run(tts.save_as_mp3_EL("hello streaming", lang="pt"))

        # Posted to streaming URL with latency param (non-v3 model supports it)
        posted_url = sess.post.call_args[0][0]
        assert "/stream" in posted_url
        assert "optimize_streaming_latency=3" in posted_url

        # Each chunk written individually (3 writes)
        fh = mock_open.return_value.__enter__.return_value
        assert fh.write.call_count == 3
        calls = [call[0][0] for call in fh.write.call_args_list]
        assert calls == [b"chunk_a", b"chunk_b", b"chunk_c"]

        # DB inserted after successful write
        mock_db().insert_sound.assert_called_once()

    def test_http_error_no_db_insert(self, mock_open, mock_makedirs,
                                       mock_getsize, mock_db, mock_session_cls):
        """Non-200 response should raise ElevenLabsAPIError and not insert DB row."""
        resp = mock_response(status=400)
        tts, sess = self._setup_tts(
            resp, mock_session_cls,
            el_tts_streaming_enabled=True,
            el_tts_timeout_seconds=30,
            voice_id="pt_voice",
        )

        with pytest.raises(ElevenLabsAPIError, match="ElevenLabs API Error"):
            asyncio.run(tts.save_as_mp3_EL("hello error", lang="pt"))

        mock_db().insert_sound.assert_not_called()

    def test_cooldown_skips_api_call(self, mock_open, mock_makedirs,
                                      mock_getsize, mock_db, mock_session_cls):
        """When on cooldown, the API call is skipped and no DB insert occurs."""
        tts = make_tts(cooldown_seconds=999,
                       el_tts_streaming_enabled=True,
                       el_tts_timeout_seconds=30,
                       voice_id="pt_voice")
        tts.voice_id_pt = tts.voice_id
        tts.behavior.send_message = AsyncMock()
        tts.behavior.play_audio = AsyncMock()
        tts.behavior.send_error_message = AsyncMock()

        # Simulate that a previous request already happened recently
        tts.last_request_time = time.time()

        asyncio.run(tts.save_as_mp3_EL("hello cooldown", lang="pt"))

        # ClientSession should NOT have been created
        mock_session_cls.assert_not_called()
        mock_db().insert_sound.assert_not_called()

    def test_http_quota_exceeded_401_raises_quota_error(self, mock_open, mock_makedirs,
                                                         mock_getsize, mock_db, mock_session_cls):
        """401 with quota_exceeded detail raises ElevenLabsQuotaExceededError and sets block."""
        mock_getsize.return_value = 9999
        quota_body = json.dumps({
            "detail": {
                "type": "invalid_request",
                "code": "quota_exceeded",
                "message": "This request exceeds your quota",
                "status": "quota_exceeded",
            }
        })
        resp = mock_response(status=401, content_bytes=quota_body.encode())
        # Override resp.text to return the JSON body (mock_response returns static "fake error body")
        resp.text = AsyncMock(return_value=quota_body)

        tts, sess = self._setup_tts(
            resp, mock_session_cls,
            el_tts_streaming_enabled=True,
            el_tts_timeout_seconds=30,
            voice_id="pt_voice",
            el_tts_quota_cooldown_seconds=3600,
        )

        with pytest.raises(ElevenLabsQuotaExceededError, match="quota_exceeded"):
            asyncio.run(tts.save_as_mp3_EL("hello quota", lang="pt"))

        # Quota block should be set
        assert tts.is_elevenlabs_quota_blocked() is True
        mock_db().insert_sound.assert_not_called()

    def test_http_quota_exceeded_429_body_text_raises_quota(self, mock_open, mock_makedirs,
                                                            mock_getsize, mock_db, mock_session_cls):
        """429 with plain-text quota_exceeded raises quota error."""
        mock_getsize.return_value = 9999
        body_text = '{"detail":{"code":"quota_exceeded","message":"Quota exceeded"}}'
        resp = mock_response(status=429, content_bytes=body_text.encode())
        resp.text = AsyncMock(return_value=body_text)

        tts, sess = self._setup_tts(
            resp, mock_session_cls,
            el_tts_streaming_enabled=True,
            el_tts_timeout_seconds=30,
            voice_id="pt_voice",
            el_tts_quota_cooldown_seconds=3600,
        )

        with pytest.raises(ElevenLabsQuotaExceededError, match="quota_exceeded"):
            asyncio.run(tts.save_as_mp3_EL("hello quota 429", lang="pt"))

        assert tts.is_elevenlabs_quota_blocked() is True
        mock_db().insert_sound.assert_not_called()

    def test_quota_blocked_skips_http_call(self, mock_open, mock_makedirs,
                                            mock_getsize, mock_db, mock_session_cls):
        """When quota block is active, save_as_mp3_EL raises without making HTTP request."""
        tts, sess = self._setup_tts(
            None, mock_session_cls,  # No response needed - HTTP should not be called
            el_tts_streaming_enabled=True,
            el_tts_timeout_seconds=30,
            voice_id="pt_voice",
            el_tts_quota_cooldown_seconds=3600,
        )
        tts.behavior.send_message = AsyncMock()
        tts.behavior.play_audio = AsyncMock()
        tts.behavior.send_error_message = AsyncMock()

        # Activate quota block
        tts._set_elevenlabs_quota_blocked()
        assert tts.is_elevenlabs_quota_blocked() is True

        with pytest.raises(ElevenLabsQuotaExceededError, match="quota blocked"):
            asyncio.run(tts.save_as_mp3_EL("hello blocked", lang="pt"))

        # ClientSession should NOT have been created (no HTTP call)
        mock_session_cls.assert_not_called()
        mock_db().insert_sound.assert_not_called()


# ============================================================================
# ElevenLabs error parsing helpers
# ============================================================================


class TestElErrorParsing:
    """Tests for _check_el_quota_exceeded and _build_el_error."""

    def test_check_401_returns_true(self):
        assert _check_el_quota_exceeded(401, "") is True

    def test_check_402_returns_true(self):
        assert _check_el_quota_exceeded(402, "") is True

    def test_check_429_returns_true(self):
        assert _check_el_quota_exceeded(429, "") is True

    def test_check_400_normal_error_returns_false(self):
        assert _check_el_quota_exceeded(400, '{"detail":"bad request"}') is False

    def test_check_json_detail_code_quota_exceeded(self):
        body = '{"detail":{"code":"quota_exceeded"}}'
        assert _check_el_quota_exceeded(400, body) is True

    def test_check_json_detail_status_quota_exceeded(self):
        body = '{"detail":{"status":"quota_exceeded"}}'
        assert _check_el_quota_exceeded(400, body) is True

    def test_check_json_detail_string_quota(self):
        body = '{"detail":"quota_exceeded"}'
        assert _check_el_quota_exceeded(400, body) is True

    def test_check_body_text_fallback(self):
        body = "some error with quota_exceeded in it"
        assert _check_el_quota_exceeded(403, body) is True

    def test_build_el_error_quota_returns_specific(self):
        exc = _build_el_error(401, '{"detail":{"code":"quota_exceeded"}}')
        assert isinstance(exc, ElevenLabsQuotaExceededError)

    def test_build_el_error_generic_returns_base(self):
        exc = _build_el_error(400, '{"detail":"bad request"}')
        assert isinstance(exc, ElevenLabsAPIError)
        assert not isinstance(exc, ElevenLabsQuotaExceededError)


# ============================================================================
# Live streaming (FIFO) tests
# ============================================================================

class TestSaveAsMp3ELLive:
    """
    Test that save_as_mp3_EL uses the live FIFO streaming path when
    eligible, and falls back to normal play_audio otherwise.
    """

    def _make_tts(self, **tts_kwargs):
        """Create a TTS instance with minimal deps and mocked behavior."""
        behavior = MagicMock()
        behavior.send_message = AsyncMock()
        behavior.play_audio = AsyncMock()
        behavior.play_tts_live_stream = AsyncMock()
        behavior.send_error_message = AsyncMock()
        bot = MagicMock()
        tts = TTS(behavior, bot, filename="test.mp3", cooldown_seconds=0)
        for key, value in tts_kwargs.items():
            setattr(tts, key, value)
        tts.voice_id = tts_kwargs.get("voice_id", "test_voice_id")
        return tts

    @pytest.mark.asyncio
    @patch("bot.tts.aiohttp.ClientSession")
    @patch("bot.tts.Database")
    @patch("bot.tts.os.path.getsize")
    @patch("bot.tts.os.makedirs")
    @patch("builtins.open", new_callable=MagicMock)
    @patch("bot.tts.tempfile.mkdtemp")
    @patch("bot.tts.os.mkfifo")
    @patch("bot.tts.os.open")
    @patch("bot.tts.os.close")
    @patch("bot.tts.os.unlink")
    @patch("bot.tts.os.rmdir")
    async def test_live_path_calls_play_tts_live_stream(
        self,
        mock_rmdir,
        mock_unlink,
        mock_close,
        mock_os_open,
        mock_mkfifo,
        mock_mkdtemp,
        mock_open,
        mock_makedirs,
        mock_getsize,
        mock_db,
        mock_session_cls,
    ):
        """
        When all live conditions are met, play_tts_live_stream should be
        called and play_audio should NOT be called.
        """
        mock_getsize.return_value = 9999
        mock_mkdtemp.return_value = "/tmp/el_tts_live_abc123"
        mock_os_open.return_value = 42

        resp = mock_response(
            status=200,
            content_chunks=[b"chunk_a", b"chunk_b", b"chunk_c"],
        )
        sess = mock_session(post_response=resp)
        mock_session_cls.return_value = sess

        fake_channel = MagicMock()
        fake_channel.guild.id = 12345

        tts = self._make_tts(
            el_tts_live_playback_enabled=True,
            el_tts_streaming_enabled=True,
            el_tts_timeout_seconds=30,
            loudnorm_mode="off",
            voice_id="pt_voice",
        )
        tts._get_default_voice_channel = MagicMock(return_value=fake_channel)

        # play_tts_live_stream mock: set ready_event and return True
        play_tts_live_kwargs = {}

        async def _fake_play_live(fifo_path, audio_file, channel, user, **kwargs):
            play_tts_live_kwargs.update(kwargs)
            play_tts_live_kwargs["fifo_path"] = fifo_path
            play_tts_live_kwargs["audio_file"] = audio_file
            play_tts_live_kwargs["channel"] = channel
            play_tts_live_kwargs["user"] = user
            re = kwargs.get("ready_event")
            if re is not None:
                re.set()
            return True

        tts.behavior.play_tts_live_stream = _fake_play_live

        await tts.save_as_mp3_EL("hello live", lang="pt")

        mock_db().insert_sound.assert_called_once()
        tts.behavior.play_audio.assert_not_called()
        assert play_tts_live_kwargs.get("input_format") == "mp3"

        # request_note should be forwarded through to play_tts_live_stream
        assert play_tts_live_kwargs.get("request_note") is None

    @pytest.mark.asyncio
    @patch("bot.tts.aiohttp.ClientSession")
    @patch("bot.tts.Database")
    @patch("bot.tts.os.path.getsize")
    @patch("bot.tts.os.makedirs")
    @patch("builtins.open", new_callable=MagicMock)
    @patch("bot.tts.tempfile.mkdtemp")
    @patch("bot.tts.os.mkfifo")
    @patch("bot.tts.os.open")
    @patch("bot.tts.os.close")
    @patch("bot.tts.os.unlink")
    @patch("bot.tts.os.rmdir")
    async def test_live_setup_starts_after_http_200(
        self,
        mock_rmdir,
        mock_unlink,
        mock_close,
        mock_os_open,
        mock_mkfifo,
        mock_mkdtemp,
        mock_open,
        mock_makedirs,
        mock_getsize,
        mock_db,
        mock_session_cls,
    ):
        """Verify that play_tts_live_stream is started AFTER the aiohttp ClientSession post call (status 200) occurs."""
        mock_getsize.return_value = 9999
        mock_mkdtemp.return_value = "/tmp/el_tts_live_abc123"
        mock_os_open.return_value = 42

        call_order = []

        resp = mock_response(
            status=200,
            content_chunks=[b"chunk_a"],
        )

        def _fake_post(*args, **kwargs):
            call_order.append("http_post")
            return resp

        sess = MagicMock()
        sess.__aenter__ = AsyncMock(return_value=sess)
        sess.__aexit__ = AsyncMock()
        sess.post = _fake_post
        mock_session_cls.return_value = sess

        fake_channel = MagicMock()
        fake_channel.guild.id = 12345

        tts = self._make_tts(
            el_tts_live_playback_enabled=True,
            el_tts_streaming_enabled=True,
            el_tts_timeout_seconds=30,
            loudnorm_mode="off",
            voice_id="pt_voice",
        )
        tts._get_default_voice_channel = MagicMock(return_value=fake_channel)

        async def _fake_play_live(**kwargs):
            call_order.append("play_live")
            re = kwargs.get("ready_event")
            if re is not None:
                re.set()
            return True

        tts.behavior.play_tts_live_stream = _fake_play_live

        await tts.save_as_mp3_EL("hello early", lang="pt")

        # "http_post" should happen before "play_live" (FIFO setup is now gated behind 200 response)
        assert "play_live" in call_order
        assert "http_post" in call_order
        assert call_order.index("http_post") < call_order.index("play_live")

    @pytest.mark.asyncio
    @patch("bot.tts.aiohttp.ClientSession")
    @patch("bot.tts.Database")
    @patch("bot.tts.os.path.getsize")
    @patch("bot.tts.os.makedirs")
    @patch("builtins.open", new_callable=MagicMock)
    @patch("bot.tts.tempfile.mkdtemp")
    @patch("bot.tts.os.mkfifo")
    @patch("bot.tts.os.open")
    @patch("bot.tts.os.close")
    @patch("bot.tts.os.unlink")
    @patch("bot.tts.os.rmdir")
    async def test_early_live_setup_fallback_to_save_then_play(
        self,
        mock_rmdir,
        mock_unlink,
        mock_close,
        mock_os_open,
        mock_mkfifo,
        mock_mkdtemp,
        mock_open,
        mock_makedirs,
        mock_getsize,
        mock_db,
        mock_session_cls,
    ):
        """When the early live stream setup fails, it should clean up the FIFO and fallback to play_audio."""
        mock_getsize.return_value = 9999
        mock_mkdtemp.return_value = "/tmp/el_tts_live_abc123"

        resp = mock_response(
            status=200,
            content_chunks=[b"chunk_a", b"chunk_b"],
        )
        sess = mock_session(post_response=resp)
        mock_session_cls.return_value = sess

        fake_channel = MagicMock()
        fake_channel.guild.id = 12345

        tts = self._make_tts(
            el_tts_live_playback_enabled=True,
            el_tts_streaming_enabled=True,
            el_tts_timeout_seconds=30,
            loudnorm_mode="off",
            voice_id="pt_voice",
        )
        tts._get_default_voice_channel = MagicMock(return_value=fake_channel)

        async def _fake_play_live_fail(**kwargs):
            # return False to indicate setup failure
            return False

        tts.behavior.play_tts_live_stream = _fake_play_live_fail

        await tts.save_as_mp3_EL("hello fallback", lang="pt")

        # Must fall back to play_audio
        tts.behavior.play_audio.assert_called_once()
        # Should have attempted cleanup of directory and FIFO
        mock_unlink.assert_called()

    @pytest.mark.asyncio
    @patch("bot.tts.aiohttp.ClientSession")
    @patch("bot.tts.Database")
    @patch("bot.tts.os.path.getsize")
    @patch("bot.tts.os.makedirs")
    @patch("builtins.open", new_callable=MagicMock)
    @patch("bot.tts.tempfile.mkdtemp")
    @patch("bot.tts.os.mkfifo")
    @patch("bot.tts.os.open")
    @patch("bot.tts.os.close")
    @patch("bot.tts.os.unlink")
    @patch("bot.tts.os.rmdir")
    async def test_quota_401_no_live_setup(
        self,
        mock_rmdir,
        mock_unlink,
        mock_close,
        mock_os_open,
        mock_mkfifo,
        mock_mkdtemp,
        mock_open,
        mock_makedirs,
        mock_getsize,
        mock_db,
        mock_session_cls,
    ):
        """Quota 401 with live enabled should NOT create FIFO or start live playback."""
        mock_getsize.return_value = 9999

        quota_body = json.dumps({
            "detail": {"code": "quota_exceeded", "status": "quota_exceeded"}
        })
        resp = mock_response(status=401, content_bytes=quota_body.encode())
        resp.text = AsyncMock(return_value=quota_body)
        sess = mock_session(post_response=resp)
        mock_session_cls.return_value = sess

        fake_channel = MagicMock()
        fake_channel.guild.id = 12345

        tts = self._make_tts(
            el_tts_live_playback_enabled=True,
            el_tts_streaming_enabled=True,
            el_tts_timeout_seconds=30,
            loudnorm_mode="off",
            voice_id="pt_voice",
        )
        tts._get_default_voice_channel = MagicMock(return_value=fake_channel)

        live_called = False

        async def _fake_play_live(**kwargs):
            nonlocal live_called
            live_called = True
            return True

        tts.behavior.play_tts_live_stream = _fake_play_live
        tts.behavior.play_audio = AsyncMock()

        with pytest.raises(ElevenLabsQuotaExceededError, match="quota_exceeded"):
            await tts.save_as_mp3_EL("hello quota no live", lang="pt")

        # Live playback should NOT have been started
        assert live_called is False, "play_tts_live_stream should not be called on quota error"
        # No FIFO should have been created
        mock_mkfifo.assert_not_called()
        # No DB insert
        mock_db().insert_sound.assert_not_called()
        # Quota block should be set
        assert tts.is_elevenlabs_quota_blocked() is True


# ============================================================================
# Environment variable defaults
# ============================================================================

def test_el_tts_env_defaults():
    """Verify that default env values match expectations (no env overrides)."""
    behavior = MagicMock()
    bot = MagicMock()
    tts = TTS(behavior, bot)

    assert tts.el_tts_streaming_enabled is True
    assert tts.el_tts_live_playback_enabled is True
    assert tts.el_tts_optimize_streaming_latency == 3
    assert tts.el_tts_model_id == "eleven_v3"
    assert tts.el_tts_output_format == "mp3_44100_128"
    assert tts.el_tts_timeout_seconds == 30
    # effective latency is None for eleven_v3 even when configured
    assert tts._effective_el_tts_streaming_latency() is None


# ============================================================================
# _parse_optimize_latency — env value validation
# ============================================================================

class TestParseOptimizeLatency:
    def test_valid_int(self):
        assert TTS._parse_optimize_latency("3") == 3
        assert TTS._parse_optimize_latency("0") == 0
        assert TTS._parse_optimize_latency("4") == 4

    def test_empty_or_none(self):
        assert TTS._parse_optimize_latency("") is None
        assert TTS._parse_optimize_latency("   ") is None
        assert TTS._parse_optimize_latency(None) is None

    def test_out_of_range(self):
        assert TTS._parse_optimize_latency("-1") is None
        assert TTS._parse_optimize_latency("5") is None

    def test_not_an_int(self):
        assert TTS._parse_optimize_latency("abc") is None
        assert TTS._parse_optimize_latency("3.5") is None


# ============================================================================
# _write_all_to_fd — helper for thread-safe FIFO writes
# ============================================================================

class TestWriteAllToFd:
    """Verify ``_write_all_to_fd`` handles partial writes, errors, and
    the normal single-write case."""

    def test_writes_all_bytes_in_one_call(self):
        """When os.write returns full length, data is written in one go."""
        fd = 42
        data = b"hello fifo"
        with patch("bot.tts.os.write", return_value=len(data)) as mock_write:
            _write_all_to_fd(fd, data)
        mock_write.assert_called_once_with(fd, data)

    def test_writes_all_bytes_across_multiple_partial_writes(self):
        """When os.write returns less than full length, loop until done."""
        fd = 42
        data = b"abcde"
        # Return 2, then 2, then 1 (partial writes)
        returns = [2, 2, 1]
        with patch("bot.tts.os.write", side_effect=returns) as mock_write:
            _write_all_to_fd(fd, data)
        assert mock_write.call_count == 3
        assert mock_write.call_args_list[0] == call(fd, b"abcde")
        assert mock_write.call_args_list[1] == call(fd, b"cde")
        assert mock_write.call_args_list[2] == call(fd, b"e")

    def test_raises_broken_pipe_on_zero_return(self):
        """When os.write returns 0, raise BrokenPipeError."""
        fd = 42
        data = b"test"
        with patch("bot.tts.os.write", return_value=0), \
             pytest.raises(BrokenPipeError):
            _write_all_to_fd(fd, data)

    def test_raises_os_error(self):
        """When os.write raises OSError, propagate it."""
        fd = 42
        data = b"test"
        with patch("bot.tts.os.write", side_effect=OSError("disk error")), \
             pytest.raises(OSError, match="disk error"):
            _write_all_to_fd(fd, data)

    def test_blocking_io_error_without_interrupt_event_raises(self):
        """When interrupt_event is None, BlockingIOError is propagated."""
        fd = 42
        data = b"test"
        with patch("bot.tts.os.write", side_effect=BlockingIOError("would block")), \
             pytest.raises(BlockingIOError):
            _write_all_to_fd(fd, data)

    def test_blocking_io_error_with_interrupt_event_raises_broken_pipe(self):
        """When interrupt_event is set and os.write raises BlockingIOError,
        raise BrokenPipeError."""
        import threading
        fd = 42
        data = b"hello"
        event = threading.Event()
        event.set()  # already interrupted

        with patch("bot.tts.os.write", side_effect=BlockingIOError("would block")), \
             pytest.raises(BrokenPipeError, match="interrupted"):
            _write_all_to_fd(fd, data, interrupt_event=event)

    def test_blocking_io_error_with_interrupt_retries_when_not_set(self):
        """When interrupt_event exists but is NOT set, sleep and retry after
        BlockingIOError until success."""
        import threading
        fd = 42
        data = b"ok"
        event = threading.Event()  # not set

        # First call raises BlockingIOError, second succeeds
        write_attempts = [0]

        def mock_write(fd, data):
            write_attempts[0] += 1
            if write_attempts[0] == 1:
                raise BlockingIOError("would block")
            return len(data)

        with patch("bot.tts.os.write", side_effect=mock_write), \
             patch("bot.tts.time.sleep") as mock_sleep:
            _write_all_to_fd(fd, data, interrupt_event=event)

        assert write_attempts[0] == 2
        mock_sleep.assert_called_once_with(0.01)
