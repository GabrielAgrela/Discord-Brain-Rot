from types import SimpleNamespace

import pytest

from bot.services.web_tts_enhancer import WebTtsEnhancerService


def test_web_tts_enhancer_uses_openrouter_chat_completion(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "choices": [
                    {"message": {"content": "[excited] hello there!"}},
                ],
            },
        )

    monkeypatch.setattr("bot.services.web_tts_enhancer.requests.post", fake_post)
    service = WebTtsEnhancerService(api_key="test-key", timeout_seconds=3)

    result = service.enhance("hello there!")

    assert result == "[excited] hello there!"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["model"] == "qwen/qwen3-coder-next"
    assert captured["json"]["max_tokens"] == 8192
    assert captured["json"]["messages"][1]["content"] == "hello there!"
    assert captured["timeout"] == 3

    system_content = captured["json"]["messages"][0]["content"]
    assert "short text" not in system_content
    assert "CRITICAL: Preserve" in system_content
    assert "Do not summarize" in system_content
    assert "omit" in system_content


def test_web_tts_enhancer_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    service = WebTtsEnhancerService(api_key="")

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        service.enhance("hello")


def test_web_tts_enhancer_rejects_empty_text():
    service = WebTtsEnhancerService(api_key="test-key")

    with pytest.raises(ValueError, match="Missing TTS message"):
        service.enhance(" ")


def test_web_tts_enhancer_accepts_up_to_20000_chars():
    service = WebTtsEnhancerService(api_key="test-key")

    with pytest.raises(ValueError, match="20000 characters or fewer"):
        service.enhance("x" * 20001)


def test_web_tts_enhancer_truncates_output_to_20000(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "choices": [
                    {"message": {"content": "x" * 25000}},
                ],
            },
        )

    monkeypatch.setattr("bot.services.web_tts_enhancer.requests.post", fake_post)
    service = WebTtsEnhancerService(api_key="test-key", timeout_seconds=3)

    result = service.enhance("hello")

    assert len(result) == 20000
    assert result == "x" * 20000


def test_web_tts_enhancer_is_output_truncated_short_input():
    """Short input (<500 chars) is never flagged as truncated."""
    assert not WebTtsEnhancerService._is_output_truncated("short", "s")


def test_web_tts_enhancer_is_output_truncated_long_input_ok():
    """Long input preserved reasonably is not flagged."""
    original = "x" * 1000
    enhanced = "x" * 300  # 30% — above 25% threshold
    assert not WebTtsEnhancerService._is_output_truncated(original, enhanced)


def test_web_tts_enhancer_is_output_truncated_long_input_cut():
    """Long input reduced below 25% is flagged as truncated."""
    original = "x" * 1000
    enhanced = "x" * 200  # 20% — below 25% threshold
    assert WebTtsEnhancerService._is_output_truncated(original, enhanced)


def test_web_tts_enhancer_rejects_truncated_long_output(monkeypatch):
    """A response much shorter than a long input raises RuntimeError."""

    def fake_post(url, headers, json, timeout):
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "choices": [
                    {"message": {"content": "short"}},
                ],
            },
        )

    monkeypatch.setattr("bot.services.web_tts_enhancer.requests.post", fake_post)
    service = WebTtsEnhancerService(api_key="test-key", timeout_seconds=3)

    with pytest.raises(RuntimeError, match="appears truncated"):
        service.enhance("x" * 600)


def test_web_tts_enhancer_custom_max_tokens(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["json"] = json
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "choices": [
                    {"message": {"content": "hi"}},
                ],
            },
        )

    monkeypatch.setattr("bot.services.web_tts_enhancer.requests.post", fake_post)
    service = WebTtsEnhancerService(
        api_key="test-key", timeout_seconds=3, max_tokens=4096
    )
    service.enhance("hi")
    assert captured["json"]["max_tokens"] == 4096


def test_web_tts_enhancer_max_tokens_floor(monkeypatch):
    """max_tokens below 256 is clamped to 256."""

    def fake_post(url, headers, json, timeout):
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "choices": [
                    {"message": {"content": "hi"}},
                ],
            },
        )

    monkeypatch.setattr("bot.services.web_tts_enhancer.requests.post", fake_post)
    service = WebTtsEnhancerService(
        api_key="test-key", timeout_seconds=3, max_tokens=50
    )
    assert service.max_tokens == 256
