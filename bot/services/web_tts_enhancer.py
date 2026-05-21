"""
Service for enhancing web TTS text with ElevenLabs audio tags.
"""

from __future__ import annotations

from collections.abc import Mapping
import os
from typing import Any

import requests


class WebTtsEnhancerService:
    """Enhance user-entered TTS text for ElevenLabs voices through OpenRouter."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        api_url: str | None = None,
        timeout_seconds: float = 20.0,
        max_tokens: int | None = None,
        reasoning_enabled: bool | None = None,
        settings_service: Any | None = None,
    ) -> None:
        """
        Initialize the enhancer service.

        When *settings_service* is provided, ``model`` and ``provider``
        constructor arguments become fallback defaults only; the effective
        values are read from the DB at request time.

        Args:
            api_key: OpenRouter API key. Defaults to OPENROUTER_API_KEY.
            model: Default model ID.  Used only when no *settings_service*
                provides a DB override.  Falls back to
                ``WEB_TTS_ENHANCER_MODEL`` env or ``deepseek/deepseek-v4-flash``.
            provider: Default provider name.  Used only when no
                *settings_service* provides a DB override.  Falls back to
                ``WEB_TTS_ENHANCER_PROVIDER`` env or empty (no provider routing).
            api_url: Chat completions endpoint URL.
            timeout_seconds: HTTP request timeout.
            max_tokens: Maximum tokens for the model response.
                Defaults to WEB_TTS_ENHANCER_MAX_TOKENS env var or 8192.
                Minimum enforced floor is 256.
            reasoning_enabled: Whether to enable OpenRouter model reasoning.
                Defaults to WEB_TTS_ENHANCER_REASONING_ENABLED env var (true).
            settings_service: Optional ``WebTtsSettingsService`` instance.
                When provided, model and provider are read from DB at
                request time, with constructor/env values as fallbacks.
        """
        self.api_key = api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY", "")
        self._default_model = model or os.getenv("WEB_TTS_ENHANCER_MODEL", "deepseek/deepseek-v4-flash")
        self._default_provider = provider or os.getenv("WEB_TTS_ENHANCER_PROVIDER", "")
        self.api_url = api_url or os.getenv(
            "OPENROUTER_API_URL",
            "https://openrouter.ai/api/v1/chat/completions",
        )
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max(
            256,
            max_tokens
            if max_tokens is not None
            else int(os.getenv("WEB_TTS_ENHANCER_MAX_TOKENS", "8192")),
        )
        if reasoning_enabled is not None:
            self.reasoning_enabled = reasoning_enabled
        else:
            self.reasoning_enabled = (
                os.getenv("WEB_TTS_ENHANCER_REASONING_ENABLED", "true").strip().lower()
                not in {"0", "false", "off", "no"}
            )
        self._settings_service = settings_service

    # -- Attributes kept for backward compat in tests that access them --
    @property
    def model(self) -> str:
        """Return the effective model (from DB settings or default)."""
        return self._get_effective_model()

    @model.setter
    def model(self, value: str) -> None:
        """Override the default model (used in tests)."""
        self._default_model = value

    @property
    def provider_sort(self) -> str:
        """Deprecated: return the effective provider for backward compat."""
        return self._get_effective_provider()

    @provider_sort.setter
    def provider_sort(self, value: str) -> None:
        """Deprecated: set the default provider (used in tests)."""
        self._default_provider = value

    # ------------------------------------------------------------------

    def _get_effective_model(self) -> str:
        """Return the effective model from DB settings or default."""
        if self._settings_service is not None:
            try:
                settings = self._settings_service.get_enhancer_settings()
                return settings["model"] or self._default_model
            except Exception:
                pass
        return self._default_model

    def _get_effective_provider(self) -> str:
        """Return the effective provider from DB settings or default."""
        if self._settings_service is not None:
            try:
                settings = self._settings_service.get_enhancer_settings()
                return settings["provider"] or self._default_provider
            except Exception:
                pass
        return self._default_provider

    def enhance(self, text: str) -> str:
        """
        Return text enhanced with ElevenLabs-style audio tags.

        Args:
            text: Raw user TTS message.

        Returns:
            Enhanced text ready to place back into the TTS message box.

        Raises:
            ValueError: If the input is empty, too long, or the service is not configured.
            RuntimeError: If OpenRouter returns an invalid or failed response.
        """
        normalized_text = str(text or "").strip()
        if not normalized_text:
            raise ValueError("Missing TTS message")
        if len(normalized_text) > 20000:
            raise ValueError("TTS message must be 20000 characters or fewer")
        if not self.api_key.strip():
            raise ValueError("OPENROUTER_API_KEY is not configured")

        response = requests.post(
            self.api_url,
            headers={
                "Authorization": f"Bearer {self.api_key.strip()}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/gabrielvicenteYT/Discord-Brain-Rot",
                "X-Title": "Discord Brain Rot Web TTS",
            },
            json=self._build_request_payload(normalized_text),
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"OpenRouter request failed with HTTP {response.status_code}")

        payload = response.json()
        enhanced_text = self._extract_response_text(payload)
        if not enhanced_text:
            raise RuntimeError("OpenRouter returned an empty enhancement")
        if self._is_output_truncated(normalized_text, enhanced_text):
            raise RuntimeError(
                "Enhancement appears truncated: the model returned a significantly "
                "shorter response than the input. Try a different model or reduce "
                "the input length."
            )
        enhanced_text = self._fix_wrapped_original_output(normalized_text, enhanced_text)
        if len(enhanced_text) > 20000:
            enhanced_text = enhanced_text[:20000].rstrip()
        return enhanced_text

    @staticmethod
    def _is_output_truncated(original: str, enhanced: str) -> bool:
        """
        Detect whether the model response was likely truncated/cut off.

        Returns True when a long input (>500 chars) has been reduced to
        less than 25% of its original length, which suggests the model
        output was cut short rather than intentionally concise.
        """
        return len(original) > 500 and len(enhanced) < len(original) * 0.25

    @staticmethod
    def _fix_wrapped_original_output(original: str, enhanced: str) -> str:
        """
        Detect and fix a model output that wraps the original text as a bracket tag.

        When the model returns *only* a bracketed segment whose inner text equals
        the normalized original (e.g. input ``hãn?`` -> output ``[hãn?]``),
        unwrap it to a safe tagged form such as ``[curious] hãn?``.

        Only applies when the entire output is a single bracketed segment with
        no spoken text outside the brackets. Leaves legitimate multi-tag or
        outside-text outputs unchanged.
        """
        stripped = enhanced.strip()
        # Match exactly one bracketed segment: [<content>] with optional leading/trailing space
        if stripped.startswith("[") and stripped.endswith("]"):
            inner = stripped[1:-1].strip()
            if inner and inner.lower() == original.strip().lower():
                return f"[curious] {original.strip()}"
        return enhanced

    def _build_request_payload(self, text: str) -> dict[str, Any]:
        """Build the OpenRouter chat completions payload."""
        payload: dict[str, Any] = {
            "model": self._get_effective_model(),
            "temperature": 0.35,
            "max_tokens": self.max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You enhance text for ElevenLabs Eleven v3 text-to-speech. "
                        "Add a few contextually appropriate square-bracket audio tags such "
                        "as [happy], [excited], [whispers], [shouts], [laughs], [sighs], "
                        "[sarcastic], [curious], or similar voice/performance tags.\n\n"
                        "CRITICAL: Preserve the user's original words and meaning completely. "
                        "Do not summarize, omit, truncate, or cut off any part of the text. "
                        "If the text is long, keep every single word. Add tags sparingly "
                        "— one or two per sentence at most.\n\n"
                        "IMPORTANT TAG RULES:\n"
                        "1. Square-bracket text MUST be a short performance tag, "
                        "never the user's spoken words.\n"
                        "2. Do NOT wrap the user's original message or parts of it "
                        "inside brackets. Original words must remain outside brackets "
                        "and be spoken.\n"
                        "3. Every original word must appear in the output, outside brackets.\n\n"
                        "Good: [confused] hãn?\n"
                        "Good: [curious] hãn?\n"
                        "Bad: [hãn?]\n"
                        "Bad: [hmm] [what's that]\n\n"
                        "Do not add new dialogue. Do not explain. "
                        "Return only the enhanced TTS text."
                    ),
                },
                {
                    "role": "user",
                    "content": text,
                },
            ],
        }
        if not self.reasoning_enabled:
            payload["reasoning"] = {"enabled": False}
        provider = self._get_effective_provider()
        if provider:
            payload["provider"] = {"order": [provider], "allow_fallbacks": False}
        return payload

    def _extract_response_text(self, payload: Mapping[str, Any]) -> str:
        """Extract assistant text from an OpenRouter chat completion response."""
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first_choice = choices[0]
        if not isinstance(first_choice, Mapping):
            return ""
        message = first_choice.get("message")
        if isinstance(message, Mapping):
            return str(message.get("content") or "").strip()
        return str(first_choice.get("text") or "").strip()
