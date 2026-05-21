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
    assert captured["json"]["model"] == "deepseek/deepseek-v4-flash"
    assert captured["json"]["max_tokens"] == 8192
    assert captured["json"]["messages"][1]["content"] == "hello there!"
    assert captured["timeout"] == 3

    system_content = captured["json"]["messages"][0]["content"]
    assert "short text" not in system_content
    assert "CRITICAL: Preserve" in system_content
    assert "Do not summarize" in system_content
    assert "omit" in system_content
    assert "Square-bracket text MUST be a short performance tag" in system_content
    assert "Good: [confused] hãn?" in system_content
    assert "Bad: [hãn?]" in system_content


def test_web_tts_enhancer_default_payload_no_provider(monkeypatch):
    """Default payload has no provider field when no provider configured."""
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
    monkeypatch.delenv("WEB_TTS_ENHANCER_PROVIDER", raising=False)
    service = WebTtsEnhancerService(api_key="test-key", timeout_seconds=3)
    service.enhance("hello")

    assert service.reasoning_enabled is True
    assert "reasoning" not in captured["json"]
    # No provider configured → no provider field in payload
    assert "provider" not in captured["json"]


def test_web_tts_enhancer_provider_in_payload_when_configured(monkeypatch):
    """When a provider is configured, payload includes order + allow_fallbacks."""
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
        api_key="test-key", timeout_seconds=3, provider="crucible"
    )
    service.enhance("hello")

    assert captured["json"].get("provider") == {
        "order": ["crucible"],
        "allow_fallbacks": False,
    }


def test_web_tts_enhancer_provider_omitted_when_empty(monkeypatch):
    """Provider field is excluded from payload when provider is empty."""
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
        api_key="test-key", timeout_seconds=3, provider=""
    )
    payload = service._build_request_payload("hello")
    assert "provider" not in payload


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


def test_web_tts_enhancer_reasoning_sent_when_explicitly_disabled(monkeypatch):
    """Explicit reasoning_enabled=False includes reasoning: {enabled: False}."""
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
        api_key="test-key", timeout_seconds=3, reasoning_enabled=False
    )
    assert service.reasoning_enabled is False
    payload = service._build_request_payload("hello")
    assert payload.get("reasoning") == {"enabled": False}


def test_web_tts_enhancer_reasoning_omitted_when_enabled(monkeypatch):
    """Reasoning field is excluded from payload when enabled."""

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
        api_key="test-key", timeout_seconds=3, reasoning_enabled=True
    )
    assert service.reasoning_enabled is True
    payload = service._build_request_payload("hello")
    assert "reasoning" not in payload


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


def test_web_tts_enhancer_fix_wrapped_output_unchanged_normal():
    """Normal enhanced output is left unchanged."""
    service = WebTtsEnhancerService(api_key="test-key")
    assert service._fix_wrapped_original_output("hãn?", "[confused] hãn?") == "[confused] hãn?"
    assert service._fix_wrapped_original_output("hello", "[happy] hello there!") == "[happy] hello there!"
    assert service._fix_wrapped_original_output("hi", "") == ""


def test_web_tts_enhancer_fix_wrapped_output_bracket_mismatch():
    """Output with different inner content than original is left unchanged."""
    service = WebTtsEnhancerService(api_key="test-key")
    assert service._fix_wrapped_original_output("hãn?", "[happy]") == "[happy]"
    assert service._fix_wrapped_original_output("hello", "[happy] hello [laughs]") == "[happy] hello [laughs]"


def test_web_tts_enhancer_fix_wrapped_output_detects_miswrapped():
    """Output that wraps the original text as a bracket tag is fixed."""
    service = WebTtsEnhancerService(api_key="test-key")
    result = service._fix_wrapped_original_output("hãn?", "[hãn?]")
    assert result == "[curious] hãn?"


def test_web_tts_enhancer_fix_wrapped_output_case_insensitive():
    """Fix is case-insensitive when matching inner text."""
    service = WebTtsEnhancerService(api_key="test-key")
    result = service._fix_wrapped_original_output("HÃN?", "[hãn?]")
    assert result == "[curious] HÃN?"


def test_web_tts_enhancer_system_prompt_includes_tag_rules(monkeypatch):
    """System prompt includes tag-rules guard language."""
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["json"] = json
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "choices": [
                    {"message": {"content": "[curious] hãn?"}},
                ],
            },
        )

    monkeypatch.setattr("bot.services.web_tts_enhancer.requests.post", fake_post)
    service = WebTtsEnhancerService(api_key="test-key", timeout_seconds=3)
    service.enhance("hãn?")

    system_content = captured["json"]["messages"][0]["content"]
    assert "Good: [confused] hãn?" in system_content
    assert "Bad: [hãn?]" in system_content
    assert "Square-bracket text MUST be a short performance tag" in system_content
    assert "Do NOT wrap the user's original message" in system_content


def test_web_tts_enhancer_mocked_wrapped_output_fixed(monkeypatch):
    """Mocked API returning [original] is fixed by the guard."""
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["json"] = json
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "choices": [
                    {"message": {"content": "[hãn?]"}},
                ],
            },
        )

    monkeypatch.setattr("bot.services.web_tts_enhancer.requests.post", fake_post)
    service = WebTtsEnhancerService(api_key="test-key", timeout_seconds=3)
    result = service.enhance("hãn?")
    assert result == "[curious] hãn?"


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


def test_web_tts_enhancer_effective_model_from_settings_service(monkeypatch):
    """When settings_service provides a model override, it should be used."""
    captured = {}

    class FakeSettingsService:
        def get_enhancer_settings(self):
            return {
                "model": "override-model",
                "provider": "",
                "stored_model": "override-model",
                "stored_provider": None,
                "default_model": "deepseek/deepseek-v4-flash",
                "default_provider": "",
            }

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
        api_key="test-key",
        timeout_seconds=3,
        settings_service=FakeSettingsService(),
    )
    service.enhance("hello")
    assert captured["json"]["model"] == "override-model"
    assert "provider" not in captured["json"]


def test_web_tts_enhancer_effective_provider_from_settings_service(monkeypatch):
    """When settings_service provides a provider override, payload uses it."""
    captured = {}

    class FakeSettingsService:
        def get_enhancer_settings(self):
            return {
                "model": "deepseek/deepseek-v4-flash",
                "provider": "crucible",
                "stored_model": None,
                "stored_provider": "crucible",
                "default_model": "deepseek/deepseek-v4-flash",
                "default_provider": "",
            }

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
        api_key="test-key",
        timeout_seconds=3,
        settings_service=FakeSettingsService(),
    )
    service.enhance("hello")
    assert captured["json"].get("provider") == {
        "order": ["crucible"],
        "allow_fallbacks": False,
    }


def test_web_tts_enhancer_settings_service_fallback_on_error(monkeypatch):
    """When settings_service raises, fall back to constructor defaults."""
    captured = {}

    class BrokenSettingsService:
        def get_enhancer_settings(self):
            raise RuntimeError("DB error")

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
        api_key="test-key",
        timeout_seconds=3,
        provider="fallback-provider",
        settings_service=BrokenSettingsService(),
    )
    service.enhance("hello")
    # Falls back to constructor-provided provider
    assert captured["json"].get("provider") == {
        "order": ["fallback-provider"],
        "allow_fallbacks": False,
    }
