"""Tests for runtime voice compatibility patching."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from discord import utils
from discord.enums import SpeakingState
from discord.gateway import DiscordVoiceWebSocket

import bot.voice_compat as voice_compat


@pytest.fixture(autouse=True)
def reset_voice_compat_patches():
    """Ensure monkey patches do not leak between tests."""
    yield
    voice_compat._reset_voice_protocol_compat_patches_for_tests()


@pytest.mark.asyncio
async def test_apply_voice_protocol_compat_patches_adds_identify_field(monkeypatch):
    """Patch should inject max_dave_protocol_version into voice IDENTIFY payload."""
    monkeypatch.setenv("VOICE_MAX_DAVE_PROTOCOL_VERSION", "2")
    module = importlib.reload(voice_compat)
    module.apply_voice_protocol_compat_patches()
    module.apply_voice_protocol_compat_patches()  # idempotent call

    sent = {}

    async def send_as_json(payload):
        sent["payload"] = payload

    ws = SimpleNamespace(
        IDENTIFY=DiscordVoiceWebSocket.IDENTIFY,
        _connection=SimpleNamespace(
            server_id=123,
            user=SimpleNamespace(id=456),
            session_id="sess",
            token="tok",
            max_dave_protocol_version=7,
        ),
        send_as_json=send_as_json,
    )

    await DiscordVoiceWebSocket.identify(ws)  # type: ignore[arg-type]
    payload = sent["payload"]

    assert payload["op"] == DiscordVoiceWebSocket.IDENTIFY
    assert payload["d"]["max_dave_protocol_version"] == 7
    assert payload["d"]["server_id"] == "123"
    assert payload["d"]["user_id"] == "456"


@pytest.mark.asyncio
async def test_speak_payload_includes_ssrc(monkeypatch):
    """Patched SPEAK payload should include SSRC when available."""
    monkeypatch.setenv("VOICE_MAX_DAVE_PROTOCOL_VERSION", "1")
    module = importlib.reload(voice_compat)
    module.apply_voice_protocol_compat_patches()

    sent = {}

    async def send_as_json(payload):
        sent["payload"] = payload

    ws = SimpleNamespace(
        SPEAKING=DiscordVoiceWebSocket.SPEAKING,
        _connection=SimpleNamespace(ssrc=9999),
        send_as_json=send_as_json,
    )

    await DiscordVoiceWebSocket.speak(ws, SpeakingState.none)  # type: ignore[arg-type]
    payload = sent["payload"]

    assert payload["op"] == DiscordVoiceWebSocket.SPEAKING
    assert payload["d"]["speaking"] == int(SpeakingState.none)
    assert payload["d"]["ssrc"] == 9999


@pytest.mark.asyncio
async def test_session_description_updates_dave_and_reinitializes(monkeypatch):
    """SESSION_DESCRIPTION should set dave_protocol_version and reinit DAVE session."""
    monkeypatch.setenv("VOICE_MAX_DAVE_PROTOCOL_VERSION", "1")
    module = importlib.reload(voice_compat)
    module.apply_voice_protocol_compat_patches()

    reinit_calls = []
    load_calls = []

    async def reinit_dave_session():
        reinit_calls.append(True)

    async def load_secret_key(data):
        load_calls.append(data)

    async def hook(*_args):
        return None

    connection = SimpleNamespace(
        mode=None,
        dave_protocol_version=0,
        dave_session=None,
        dave_pending_transitions={},
        dave_downgraded=False,
        reinit_dave_session=reinit_dave_session,
    )

    ws = SimpleNamespace(
        READY=DiscordVoiceWebSocket.READY,
        HEARTBEAT_ACK=DiscordVoiceWebSocket.HEARTBEAT_ACK,
        RESUMED=DiscordVoiceWebSocket.RESUMED,
        SESSION_DESCRIPTION=DiscordVoiceWebSocket.SESSION_DESCRIPTION,
        HELLO=DiscordVoiceWebSocket.HELLO,
        SPEAKING=DiscordVoiceWebSocket.SPEAKING,
        DAVE_PREPARE_TRANSITION=DiscordVoiceWebSocket.DAVE_PREPARE_TRANSITION,
        DAVE_EXECUTE_TRANSITION=DiscordVoiceWebSocket.DAVE_EXECUTE_TRANSITION,
        DAVE_PREPARE_EPOCH=DiscordVoiceWebSocket.DAVE_PREPARE_EPOCH,
        _connection=connection,
        _hook=hook,
        seq_ack=-1,
        load_secret_key=load_secret_key,
        ssrc_map={},
        _keep_alive=None,
        initial_connection=None,
    )

    msg = {
        "op": DiscordVoiceWebSocket.SESSION_DESCRIPTION,
        "d": {
            "mode": "aead_xchacha20_poly1305_rtpsize",
            "secret_key": [1, 2, 3],
            "dave_protocol_version": 1,
        },
        "seq": 42,
    }

    await DiscordVoiceWebSocket.received_message(ws, msg)  # type: ignore[arg-type]

    assert connection.mode == "aead_xchacha20_poly1305_rtpsize"
    assert connection.dave_protocol_version == 1
    assert reinit_calls == [True]
    assert len(load_calls) == 1
    assert ws.seq_ack == 42


@pytest.mark.asyncio
async def test_reinit_dave_session_uses_active_ws_fallback(monkeypatch):
    """Reinit should use active websocket fallback when VoiceClient.ws is MISSING."""
    monkeypatch.setenv("VOICE_MAX_DAVE_PROTOCOL_VERSION", "1")
    module = importlib.reload(voice_compat)
    module.apply_voice_protocol_compat_patches()

    sent = []

    async def send_binary(opcode, payload):
        sent.append((opcode, payload))

    class FakeSession:
        def reinit(self, *_args):
            return None

        def get_serialized_key_package(self):
            return b"kp"

    fake_client = SimpleNamespace(
        dave_protocol_version=1,
        dave_session=FakeSession(),
        user=SimpleNamespace(id=111),
        channel=SimpleNamespace(id=222),
        ws=utils.MISSING,
        _voicecompat_active_ws=SimpleNamespace(send_binary=send_binary),
    )

    await module._voiceclient_reinit_dave_session(fake_client)

    assert sent == [(DiscordVoiceWebSocket.MLS_KEY_PACKAGE, b"kp")]
