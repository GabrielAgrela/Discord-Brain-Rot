"""
Service for web TTS settings management.

Provides a thin business-logic layer over
:class:`bot.repositories.web_tts_settings.WebTtsSettingsRepository`,
handling validation and default fallback for the TTS enhancer LLM
model and provider overrides, as well as Ventura Chat LLM settings.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from bot.repositories.web_tts_settings import WebTtsSettingsRepository

logger = logging.getLogger(__name__)

# Keys used in ``app_settings`` for the TTS enhancer LLM overrides.
ENHANCER_MODEL_KEY = "web_tts_enhancer_model"
ENHANCER_PROVIDER_KEY = "web_tts_enhancer_provider"

# Keys used in ``app_settings`` for the Ventura Chat LLM overrides.
VENTURA_CHAT_MODEL_KEY = "ventura_chat_model"
VENTURA_CHAT_PROVIDER_KEY = "ventura_chat_provider"

# Environment variable that supplies the default model and provider.
WEB_TTS_ENHANCER_MODEL_ENV = "WEB_TTS_ENHANCER_MODEL"
WEB_TTS_ENHANCER_PROVIDER_ENV = "WEB_TTS_ENHANCER_PROVIDER"

# Ventura Chat-specific environment variable defaults.
VENTURA_CHAT_MODEL_ENV = "VENTURA_CHAT_MODEL"
VENTURA_CHAT_PROVIDER_ENV = "VENTURA_CHAT_PROVIDER"

# Fallback defaults when no env var is set.
FALLBACK_ENHANCER_MODEL = "deepseek/deepseek-v4-flash"
FALLBACK_ENHANCER_PROVIDER = ""
FALLBACK_VENTURA_MODEL = "deepseek/deepseek-v4-flash"
FALLBACK_VENTURA_PROVIDER = ""


class WebTtsSettingsService:
    """
    Service for managing DB-backed TTS enhancer LLM settings.

    Supports overriding the OpenRouter model ID and provider used by
    the web TTS enhancer for debug/admin purposes.  Falls back to env
    vars or hardcoded defaults when no override is stored.
    """

    def __init__(self, repository: WebTtsSettingsRepository) -> None:
        """
        Args:
            repository: Repository for the ``app_settings`` key-value store.
        """
        self.repository = repository

    def ensure_schema(self) -> None:
        """Ensure the underlying ``app_settings`` table exists."""
        self.repository.ensure_schema()

    def _default_model(self) -> str:
        """Return the env-var default enhancer model."""
        return os.getenv(WEB_TTS_ENHANCER_MODEL_ENV, FALLBACK_ENHANCER_MODEL)

    def _default_provider(self) -> str:
        """Return the env-var default enhancer provider."""
        return os.getenv(WEB_TTS_ENHANCER_PROVIDER_ENV, FALLBACK_ENHANCER_PROVIDER)

    def get_enhancer_settings(self) -> dict[str, Any]:
        """
        Return the current effective enhancer LLM settings and overrides.

        Returns:
            Dict with keys:

            - ``model`` – the effective model (stored override or default)
            - ``provider`` – the effective provider (stored override or default)
            - ``stored_model`` – the DB-stored model override, or ``None``
            - ``stored_provider`` – the DB-stored provider override, or ``None``
            - ``default_model`` – the fallback default model
            - ``default_provider`` – the fallback default provider
        """
        default_model = self._default_model()
        default_provider = self._default_provider()
        stored_model = self.repository.get_setting(ENHANCER_MODEL_KEY)
        stored_provider = self.repository.get_setting(ENHANCER_PROVIDER_KEY)
        effective_model = stored_model or default_model
        effective_provider = stored_provider or default_provider
        return {
            "model": effective_model,
            "provider": effective_provider,
            "stored_model": stored_model,
            "stored_provider": stored_provider,
            "default_model": default_model,
            "default_provider": default_provider,
        }

    def set_enhancer_settings(
        self,
        model: str | None = None,
        provider: str | None = None,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        """
        Set or clear the TTS enhancer LLM model and/or provider overrides.

        Args:
            model: The model ID to store.  ``None`` leaves it unchanged.
                Empty string clears the override (revert to default).
                Validated against ``[A-Za-z0-9._/:-]``, max 128 chars.
            provider: The provider name to store.  ``None`` leaves it
                unchanged.  Empty string clears the override (revert to
                default).  Validated against ``[A-Za-z0-9._/:-]``,
                max 128 chars.
            updated_by: Optional identifier of who made the change.

        Returns:
            Updated settings dict (see :meth:`get_enhancer_settings`).

        Raises:
            ValueError: If *model* or *provider* fail validation.
        """
        if model is not None:
            if model.strip() == "":
                self.repository.delete_setting(ENHANCER_MODEL_KEY)
            else:
                validated_model = WebTtsSettingsRepository.validate_model_id(model)
                if validated_model is None:
                    raise ValueError(
                        "Invalid model ID. Must be 1-128 characters matching: "
                        "[A-Za-z0-9._/:-]"
                    )
                self.repository.set_setting(
                    ENHANCER_MODEL_KEY, validated_model, updated_by
                )
        if provider is not None:
            if provider.strip() == "":
                self.repository.delete_setting(ENHANCER_PROVIDER_KEY)
            else:
                validated_provider = WebTtsSettingsRepository.validate_provider_name(
                    provider
                )
                if validated_provider is None:
                    raise ValueError(
                        "Invalid provider name. Must be 1-128 characters matching: "
                        "[A-Za-z0-9._/:-]"
                    )
                self.repository.set_setting(
                    ENHANCER_PROVIDER_KEY, validated_provider, updated_by
                )
        return self.get_enhancer_settings()

    def clear_enhancer_settings(
        self, updated_by: str | None = None
    ) -> dict[str, Any]:
        """
        Clear all TTS enhancer LLM overrides (revert to defaults).

        Args:
            updated_by: Optional identifier.

        Returns:
            Updated settings dict (see :meth:`get_enhancer_settings`).
        """
        self.repository.delete_setting(ENHANCER_MODEL_KEY)
        self.repository.delete_setting(ENHANCER_PROVIDER_KEY)
        return self.get_enhancer_settings()

    # ------------------------------------------------------------------
    # Ventura Chat LLM settings
    # ------------------------------------------------------------------

    def _default_ventura_chat_model(self) -> str:
        """Return the env-var default Ventura Chat model.

        Checks ``VENTURA_CHAT_MODEL`` first, then falls back to
        ``WEB_TTS_ENHANCER_MODEL`` for backward compatibility, then
        to the hardcoded default.
        """
        return (
            os.getenv(VENTURA_CHAT_MODEL_ENV)
            or os.getenv(WEB_TTS_ENHANCER_MODEL_ENV)
            or FALLBACK_VENTURA_MODEL
        )

    def _default_ventura_chat_provider(self) -> str:
        """Return the env-var default Ventura Chat provider.

        Checks ``VENTURA_CHAT_PROVIDER`` first, then falls back to
        ``WEB_TTS_ENHANCER_PROVIDER`` for backward compatibility, then
        to the hardcoded default (empty string).
        """
        return (
            os.getenv(VENTURA_CHAT_PROVIDER_ENV)
            or os.getenv(WEB_TTS_ENHANCER_PROVIDER_ENV)
            or FALLBACK_VENTURA_PROVIDER
        )

    def get_ventura_chat_settings(self) -> dict[str, Any]:
        """
        Return the current effective Ventura Chat LLM settings and overrides.

        Reads ``ventura_chat_model`` / ``ventura_chat_provider`` from the DB.
        Falls back to the legacy ``web_tts_enhancer_model`` /
        ``web_tts_enhancer_provider`` keys for backward compatibility with
        previously saved settings, then to env vars, then to hardcoded defaults.

        Returns:
            Dict with keys:

            - ``model`` – the effective model (stored override or default)
            - ``provider`` – the effective provider (stored override or default)
            - ``stored_model`` – the DB-stored model override, or ``None``
            - ``stored_provider`` – the DB-stored provider override, or ``None``
            - ``default_model`` – the fallback default model
            - ``default_provider`` – the fallback default provider
        """
        default_model = self._default_ventura_chat_model()
        default_provider = self._default_ventura_chat_provider()

        # Read new keys first, fall back to old legacy keys.
        stored_model = self.repository.get_setting(VENTURA_CHAT_MODEL_KEY)
        if stored_model is None:
            stored_model = self.repository.get_setting(ENHANCER_MODEL_KEY)

        stored_provider = self.repository.get_setting(VENTURA_CHAT_PROVIDER_KEY)
        if stored_provider is None:
            stored_provider = self.repository.get_setting(ENHANCER_PROVIDER_KEY)

        effective_model = stored_model or default_model
        effective_provider = stored_provider or default_provider
        return {
            "model": effective_model,
            "provider": effective_provider,
            "stored_model": stored_model,
            "stored_provider": stored_provider,
            "default_model": default_model,
            "default_provider": default_provider,
        }

    def set_ventura_chat_settings(
        self,
        model: str | None = None,
        provider: str | None = None,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        """
        Set or clear the Ventura Chat LLM model and/or provider overrides.

        Writes to both the new ``ventura_chat_*`` keys and the legacy
        ``web_tts_enhancer_*`` keys so that both the Ventura Chat service
        and the web TTS enhancer service pick up the change.

        Args:
            model: The model ID to store.  ``None`` leaves it unchanged.
                Empty string clears the override (revert to default).
                Validated against ``[A-Za-z0-9._/:-]``, max 128 chars.
            provider: The provider name to store.  ``None`` leaves it
                unchanged.  Empty string clears the override (revert to
                default).  Validated against ``[A-Za-z0-9._/:-]``,
                max 128 chars.
            updated_by: Optional identifier of who made the change.

        Returns:
            Updated settings dict (see :meth:`get_ventura_chat_settings`).

        Raises:
            ValueError: If *model* or *provider* fail validation.
        """
        if model is not None:
            if model.strip() == "":
                self.repository.delete_setting(VENTURA_CHAT_MODEL_KEY)
                self.repository.delete_setting(ENHANCER_MODEL_KEY)
            else:
                validated_model = WebTtsSettingsRepository.validate_model_id(model)
                if validated_model is None:
                    raise ValueError(
                        "Invalid model ID. Must be 1-128 characters matching: "
                        "[A-Za-z0-9._/:-]"
                    )
                self.repository.set_setting(
                    VENTURA_CHAT_MODEL_KEY, validated_model, updated_by
                )
                self.repository.set_setting(
                    ENHANCER_MODEL_KEY, validated_model, updated_by
                )
        if provider is not None:
            if provider.strip() == "":
                self.repository.delete_setting(VENTURA_CHAT_PROVIDER_KEY)
                self.repository.delete_setting(ENHANCER_PROVIDER_KEY)
            else:
                validated_provider = WebTtsSettingsRepository.validate_provider_name(
                    provider
                )
                if validated_provider is None:
                    raise ValueError(
                        "Invalid provider name. Must be 1-128 characters matching: "
                        "[A-Za-z0-9._/:-]"
                    )
                self.repository.set_setting(
                    VENTURA_CHAT_PROVIDER_KEY, validated_provider, updated_by
                )
                self.repository.set_setting(
                    ENHANCER_PROVIDER_KEY, validated_provider, updated_by
                )
        return self.get_ventura_chat_settings()

    def clear_ventura_chat_settings(
        self, updated_by: str | None = None
    ) -> dict[str, Any]:
        """
        Clear all Ventura Chat LLM overrides (revert to defaults).

        Clears both new ``ventura_chat_*`` and legacy ``web_tts_enhancer_*`` keys.

        Args:
            updated_by: Optional identifier.

        Returns:
            Updated settings dict (see :meth:`get_ventura_chat_settings`).
        """
        self.repository.delete_setting(VENTURA_CHAT_MODEL_KEY)
        self.repository.delete_setting(VENTURA_CHAT_PROVIDER_KEY)
        self.repository.delete_setting(ENHANCER_MODEL_KEY)
        self.repository.delete_setting(ENHANCER_PROVIDER_KEY)
        return self.get_ventura_chat_settings()
