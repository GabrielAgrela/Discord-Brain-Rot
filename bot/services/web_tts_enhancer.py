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
        api_url: str | None = None,
        timeout_seconds: float = 20.0,
        max_tokens: int | None = None,
    ) -> None:
        """
        Initialize the enhancer service.

        Args:
            api_key: OpenRouter API key. Defaults to OPENROUTER_API_KEY.
            model: OpenRouter model ID to use.
            api_url: Chat completions endpoint URL.
            timeout_seconds: HTTP request timeout.
            max_tokens: Maximum tokens for the model response.
                Defaults to WEB_TTS_ENHANCER_MAX_TOKENS env var or 8192.
                Minimum enforced floor is 256.
        """
        self.api_key = api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY", "")
        self.model = model or os.getenv("WEB_TTS_ENHANCER_MODEL", "qwen/qwen3-coder-next")
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

    def _build_request_payload(self, text: str) -> dict[str, Any]:
        """Build the OpenRouter chat completions payload."""
        return {
            "model": self.model,
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
