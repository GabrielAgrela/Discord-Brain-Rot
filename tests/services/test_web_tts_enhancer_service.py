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
    assert captured["json"]["model"] == "x-ai/grok-4.1-fast"
    assert captured["json"]["messages"][1]["content"] == "hello there!"
    assert captured["timeout"] == 3


def test_web_tts_enhancer_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    service = WebTtsEnhancerService(api_key="")

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        service.enhance("hello")


def test_web_tts_enhancer_rejects_empty_text():
    service = WebTtsEnhancerService(api_key="test-key")

    with pytest.raises(ValueError, match="Missing TTS message"):
        service.enhance(" ")
