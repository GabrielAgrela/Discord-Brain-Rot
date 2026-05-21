"""
Voice command and Ventura chat services using Groq Whisper + OpenRouter.

When Vosk detects the configured wake word (default "ventura", which is
in-vocabulary for the bundled Portuguese Vosk model vosk-model-small-pt-0.3),
a start prompt clip is played from ``Sounds/`` (no DB lookup), then *fresh*
post-prompt PCM audio for that user is recorded until silence or max duration.
The captured audio is sent to Groq Whisper for transcription.  If the
transcript matches a recognised command verb (e.g. ``toca``), a
done prompt clip is played and the sound is played via SoundService.play_request
or SoundService.play_random_sound_from_list.
If the command is ``mute``, no prompt is played and the caller activates the
30-minute mute.  If no command verb is recognised, the transcript is routed to
``VenturaChatService`` which sends it to an OpenRouter model (default
``deepseek/deepseek-v4-flash``) for a Ventura parody reply in European Portuguese.
The reply is then sent to ElevenLabs Ventura TTS and played back.

The transcript parser searches for the wake word **anywhere** in the returned
text (not only at the start), so Portuguese preamble such as
"Mas que merda? Ventura, toca das páginas." is handled correctly.
Only Portuguese command verbs (``toca``, ``tocar``, ``toque``, ``mete``,
``meter``, ``põe``, ``poe``, ``reproduz``, ``reproduzir``) are
supported and normalised to ``"play"``.  English ``play`` is **not**
recognised as a Ventura voice command verb.

Whisper occasionally transcribes the spoken imperative ``toca`` as
the formal/conjunctive ``toque``; ``toque`` is therefore included as
a recognised alias.

Both the human-facing wake words (VOICE_COMMAND_WAKE_WORDS) and the Vosk
aliases (VOICE_COMMAND_WAKE_ALIASES) are combined and stripped from Groq
transcripts during command parsing.

Historical note: The prior default wake word was "bot", which was out of
vocabulary (OOV) for the Portuguese model.  It required Portuguese phonetic
aliases ("bote", "bota", "boto") configured via VOICE_COMMAND_WAKE_ALIASES.
"""

import asyncio
import io
import json
import logging
import os
import re
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiohttp

from config import PROJECT_ROOT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment defaults
# ---------------------------------------------------------------------------
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")

GROQ_WHISPER_MODEL: str = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")

# Optional prompt sent to Groq Whisper.  Keep the default empty: Whisper can
# hallucinate prompt text or generic Portuguese filler on short/noisy clips.
GROQ_WHISPER_PROMPT: str = os.getenv(
    "GROQ_WHISPER_PROMPT",
    "",
)

GROQ_WHISPER_TEMPERATURE: str = os.getenv("GROQ_WHISPER_TEMPERATURE", "0")

# Language hint sent to Groq Whisper.  Default is ``"pt"`` (Portuguese) so that
# Whisper transcribes Portuguese utterances instead of auto-detecting and
# potentially translating to English.  Set to empty string to restore auto-
# detect for strongly mixed-language deployments.
GROQ_WHISPER_LANGUAGE: str = os.getenv("GROQ_WHISPER_LANGUAGE", "pt")

_whisper_timeout = 20
try:
    _whisper_timeout = int(os.getenv("GROQ_WHISPER_TIMEOUT_SECONDS", "20"))
except ValueError:
    pass
GROQ_WHISPER_TIMEOUT: int = max(1, _whisper_timeout)

# Debug save: persist the exact WAV bytes sent to Groq for debugging.
_GROQ_WHISPER_DEBUG_SAVE: bool = (
    os.getenv("GROQ_WHISPER_DEBUG_SAVE_AUDIO", "false").strip().lower()
    not in {"0", "false", "off", "no"}
)

_GROQ_WHISPER_DEBUG_DIR: str = os.getenv("GROQ_WHISPER_DEBUG_AUDIO_DIR", "")
if not _GROQ_WHISPER_DEBUG_DIR:
    _GROQ_WHISPER_DEBUG_DIR = str(PROJECT_ROOT / "debug" / "groq_whisper")

GROQ_WHISPER_DEBUG_KEEP: int = max(1, int(os.getenv("GROQ_WHISPER_DEBUG_AUDIO_KEEP", "25")))

# Voice-command wake words (comma-separated, used for transcript stripping in
# parse_voice_command).  The default "ventura" is in-vocabulary for the bundled
# Portuguese Vosk model; VOICE_COMMAND_WAKE_ALIASES controls what is injected
# into the Vosk grammar (defaults to the same word).  Both the human wake words
# and the Vosk aliases are combined at runtime into
# voice_command_transcript_wake_words and passed to the parser.
WAKE_WORDS: list[str] = [
    w.strip().lower()
    for w in os.getenv("VOICE_COMMAND_WAKE_WORDS", "ventura").split(",")
    if w.strip()
]

# How many seconds of recent per-user PCM to send for transcription.
_capture_seconds = 6
try:
    _capture_seconds = int(os.getenv("VOICE_COMMAND_CAPTURE_SECONDS", "6"))
except ValueError:
    pass
CAPTURE_SECONDS: int = max(1, min(15, _capture_seconds))

# Per-user rate-limit cooldown (seconds) between voice-command transcriptions.
_cooldown_seconds = 5
try:
    _cooldown_seconds = int(os.getenv("VOICE_COMMAND_COOLDOWN_SECONDS", "5"))
except ValueError:
    pass
COOLDOWN_SECONDS: int = max(1, _cooldown_seconds)


# ---------------------------------------------------------------------------
# Groq Whisper API client
# ---------------------------------------------------------------------------

class GroqWhisperService:
    """Lightweight client for Groq Cloud Whisper transcription."""

    def __init__(self) -> None:
        self.api_key: str = GROQ_API_KEY
        self.model: str = GROQ_WHISPER_MODEL
        self.prompt: str = GROQ_WHISPER_PROMPT
        self.temperature: str = GROQ_WHISPER_TEMPERATURE
        self.language: str = GROQ_WHISPER_LANGUAGE
        self.timeout_seconds: int = GROQ_WHISPER_TIMEOUT

        # Debug audio save settings
        self.debug_save_enabled: bool = _GROQ_WHISPER_DEBUG_SAVE
        self.debug_audio_dir: str = _GROQ_WHISPER_DEBUG_DIR
        self.debug_audio_keep: int = GROQ_WHISPER_DEBUG_KEEP

    @property
    def is_available(self) -> bool:
        """Return True when a GROQ_API_KEY is configured."""
        return bool(self.api_key)

    async def transcribe(self, wav_bytes: bytes) -> Optional[str]:
        """Transcribe a WAV file via the Groq Whisper API.

        Args:
            wav_bytes: Complete WAV file bytes (RIFF header + PCM data).

        Returns:
            Transcribed and stripped text, or None on failure / missing key.
        """
        if not self.api_key:
            logger.warning("[GroqWhisper] GROQ_API_KEY not set; skipping")
            return None

        # Debug: persist the WAV bytes before sending to the API.
        self._save_debug_audio(wav_bytes)

        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        data = aiohttp.FormData()
        data.add_field("file", wav_bytes, filename="voice.wav", content_type="audio/wav")
        data.add_field("model", self.model)
        data.add_field("response_format", "json")
        if self.temperature:
            data.add_field("temperature", self.temperature)
        if self.prompt:
            data.add_field("prompt", self.prompt)
        if self.language:
            data.add_field("language", self.language)

        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, data=data) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(
                            "[GroqWhisper] API error %s: %.200s", resp.status, error_text
                        )
                        return None
                    result = await resp.json()
                    text = (result.get("text") or "").strip()
                    return text if text else None
        except asyncio.TimeoutError:
            logger.error("[GroqWhisper] Request timed out after %ss", self.timeout_seconds)
            return None
        except Exception as exc:
            logger.error("[GroqWhisper] Request failed: %s", exc)
            return None

    def _save_debug_audio(self, wav_bytes: bytes) -> None:
        """Persist a copy of *wav_bytes* for offline inspection.

        Writes a timestamped file (``groq-whisper-<ISO-8601>.wav``) and
        overwrites ``latest.wav`` in ``self.debug_audio_dir``.  Prunes the
        oldest timestamped files when the count exceeds
        ``self.debug_audio_keep``.

        Failures are logged as warnings but never raised.
        """
        if not self.debug_save_enabled:
            return
        try:
            os.makedirs(self.debug_audio_dir, exist_ok=True)

            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "Z"
            filepath = os.path.join(self.debug_audio_dir, f"groq-whisper-{ts}.wav")
            with open(filepath, "wb") as f:
                f.write(wav_bytes)

            latest_path = os.path.join(self.debug_audio_dir, "latest.wav")
            with open(latest_path, "wb") as f:
                f.write(wav_bytes)

            logger.info(
                "[GroqWhisper] Debug audio saved: %s (%d bytes)",
                filepath,
                len(wav_bytes),
            )
            self._prune_debug_audio()
        except Exception as exc:
            logger.warning(
                "[GroqWhisper] Failed to save debug audio: %s", exc, exc_info=True
            )

    def _prune_debug_audio(self) -> None:
        """Remove oldest ``groq-whisper-*.wav`` files beyond the retention limit."""
        try:
            files = sorted(
                f
                for f in os.listdir(self.debug_audio_dir)
                if f.startswith("groq-whisper-") and f.endswith(".wav")
            )
            while len(files) > self.debug_audio_keep:
                oldest = files.pop(0)
                os.remove(os.path.join(self.debug_audio_dir, oldest))
        except Exception as exc:
            logger.warning(
                "[GroqWhisper] Failed to prune debug audio: %s", exc, exc_info=True
            )


# ---------------------------------------------------------------------------
# OpenRouter Ventura Chat client
# ---------------------------------------------------------------------------

OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_API_URL: str = os.getenv(
    "OPENROUTER_API_URL",
    "https://openrouter.ai/api/v1/chat/completions",
)
VENTURA_CHAT_MODEL: str = os.getenv("VENTURA_CHAT_MODEL", "deepseek/deepseek-v4-flash")
VENTURA_CHAT_TIMEOUT_SECONDS: int = max(1, int(os.getenv("VENTURA_CHAT_TIMEOUT_SECONDS", "20")))
VENTURA_CHAT_MAX_TOKENS: int = max(50, int(os.getenv("VENTURA_CHAT_MAX_TOKENS", "250")))
VENTURA_CHAT_TEMPERATURE: float = max(
    0.0, min(2.0, float(os.getenv("VENTURA_CHAT_TEMPERATURE", "0.7")))
)
VENTURA_CHAT_REASONING_ENABLED: bool = (
    os.getenv("VENTURA_CHAT_REASONING_ENABLED", "false").strip().lower()
    not in {"0", "false", "off", "no"}
)
VENTURA_SYSTEM_EXTRA: str = os.getenv(
    "VENTURA_SYSTEM_EXTRA",
)
VENTURA_CHAT_PROVIDER_SORT: str = os.getenv(
    "VENTURA_CHAT_PROVIDER_SORT", ""
).strip()
VENTURA_CHAT_LOG_PAYLOAD: bool = (
    os.getenv("VENTURA_CHAT_LOG_PAYLOAD", "true").strip().lower()
    not in {"0", "false", "off", "no"}
)
VENTURA_CHAT_HISTORY_RETENTION_SECONDS: float = max(
    0.0, float(os.getenv("VENTURA_CHAT_HISTORY_RETENTION_SECONDS", "300"))
)


class VenturaChatService:
    """OpenRouter chat client that generates Ventura parody replies.

    Sends the user transcript to an OpenRouter model and returns short
    European Portuguese text with ElevenLabs square-bracket performance
    tags, suitable for ``VoiceTransformationService.tts_EL(lang="pt")``.

    Keeps an in-memory conversation history per ``conversation_key`` (up to
    the last 3 user/assistant exchanges from the last
    ``VENTURA_CHAT_HISTORY_RETENTION_SECONDS``) so follow-up queries have
    context while stale entries are automatically pruned.
    """

    # Maximum number of prior exchanges to include in the prompt.
    _MAX_HISTORY_EXCHANGES: int = 3

    def __init__(self, settings_service: Any = None) -> None:
        self.api_key: str = OPENROUTER_API_KEY
        self.model: str = VENTURA_CHAT_MODEL
        self.api_url: str = OPENROUTER_API_URL
        self.timeout_seconds: int = VENTURA_CHAT_TIMEOUT_SECONDS
        self.max_tokens: int = VENTURA_CHAT_MAX_TOKENS
        self.temperature: float = VENTURA_CHAT_TEMPERATURE
        self.reasoning_enabled: bool = VENTURA_CHAT_REASONING_ENABLED
        self.provider_sort: str = VENTURA_CHAT_PROVIDER_SORT
        self.log_payload: bool = VENTURA_CHAT_LOG_PAYLOAD
        self.history_retention_seconds: float = VENTURA_CHAT_HISTORY_RETENTION_SECONDS
        self._settings_service = settings_service

        # Per-conversation history: key -> list of (monotonic_ts, user_text, assistant_text)
        self._history: dict[str, list[tuple[float, str, str]]] = {}

    @property
    def is_available(self) -> bool:
        """Return ``True`` when an ``OPENROUTER_API_KEY`` is configured."""
        return bool(self.api_key.strip())

    async def reply(
        self,
        transcript: str,
        requester_name: Optional[str] = None,
        conversation_key: Optional[str] = None,
    ) -> Optional[str]:
        """Send *transcript* to OpenRouter and return a Ventura-style reply.

        Args:
            transcript: The user's spoken words from Groq Whisper.
            requester_name: Display name for optional prompt context.
            conversation_key: Stable key for conversation history lookup
                (e.g. ``"guild:123:user:456"``). Falls back to
                ``requester_name``, then ``"default"``.

        Returns:
            Generated PT-PT ventura text with square-bracket tags, or
            ``None`` when the API is unavailable / errors / empty response.
        """
        if not self.is_available:
            logger.warning("[VenturaChat] OPENROUTER_API_KEY not set; skipping")
            return None

        effective_key = conversation_key or requester_name or "default"

        payload = self._build_request_payload(transcript, requester_name, effective_key)

        # Log the request payload or summary for debugging (no secrets — payload
        # only contains model/temperature/max_tokens/messages; auth headers
        # are set separately and never included in the log).
        ctx_count = max(0, (len(payload.get("messages", [])) - 2) // 2)
        if self.log_payload:
            logger.info(
                "[VenturaChat] Request payload — conversation_key=%s "
                "context_exchanges=%d message_count=%d\n%s",
                effective_key,
                ctx_count,
                len(payload.get("messages", [])),
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
        else:
            reasoning_status = "disabled" if not self.reasoning_enabled else "enabled"
            effective_provider = self._get_effective_provider()
            provider_display = effective_provider or (
                self.provider_sort if self.provider_sort else "none"
            )
            logger.info(
                "[VenturaChat] Request summary — conversation_key=%s "
                "context_exchanges=%d message_count=%d model=%s max_tokens=%d "
                "reasoning=%s provider=%s",
                effective_key,
                ctx_count,
                len(payload.get("messages", [])),
                payload.get("model", self.model),
                self.max_tokens,
                reasoning_status,
                provider_display,
            )

        start_time = time.perf_counter()
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.api_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key.strip()}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://github.com/gabrielvicenteYT/Discord-Brain-Rot",
                        "X-Title": "Discord Brain Rot Ventura Chat",
                    },
                    json=payload,
                ) as resp:
                    latency = time.perf_counter() - start_time
                    logger.info(
                        "[VenturaChat] OpenRouter completed in %.2fs status=%d model=%s",
                        latency,
                        resp.status,
                        self.model,
                    )
                    if resp.status >= 400:
                        error_text = await resp.text()
                        logger.error(
                            "[VenturaChat] API error %s: %.200s",
                            resp.status,
                            error_text,
                        )
                        return None
                    result = await resp.json()
                    text = self._extract_response_text(result)
                    if text:
                        formatted_transcript = self._format_user_transcript(transcript, requester_name)
                        self._append_history(effective_key, formatted_transcript, text)
                    return text if text else None
        except asyncio.TimeoutError:
            latency = time.perf_counter() - start_time
            logger.error(
                "[VenturaChat] Request timed out after %.2fs (limit %ss)",
                latency,
                self.timeout_seconds,
            )
            return None
        except Exception as exc:
            latency = time.perf_counter() - start_time
            logger.error(
                "[VenturaChat] Request failed after %.2fs: %s",
                latency,
                exc,
            )
            return None

    def _get_effective_model(self) -> str:
        """Return the effective model from DB settings or env fallback.

        Checks the optional ``settings_service`` for a stored override,
        then falls back to ``self.model`` (from env / constructor).
        """
        if self._settings_service is not None:
            try:
                settings = self._settings_service.get_ventura_chat_settings()
                db_model = settings.get("model")
                if db_model:
                    return db_model
            except Exception:
                pass
        return self.model

    def _get_effective_provider(self) -> str:
        """Return the effective provider from DB settings or empty string.

        Checks the optional ``settings_service`` for a stored override,
        then falls back to empty (no provider routing).  The legacy
        ``provider_sort`` is handled separately in ``_build_request_payload``.
        """
        if self._settings_service is not None:
            try:
                settings = self._settings_service.get_ventura_chat_settings()
                db_provider = settings.get("provider")
                if db_provider:
                    return db_provider
            except Exception:
                pass
        return ""

    def _format_user_transcript(self, transcript: str, requester_name: Optional[str]) -> str:
        """Format the transcript with the speaker's name as a prefix if provided."""
        if requester_name and requester_name.strip():
            return f"{requester_name.strip()}: {transcript.strip()}"
        return transcript.strip()

    def _prune_history(self, key: str) -> None:
        """Remove expired entries for *key* and delete empty keys.

        Entries older than ``self.history_retention_seconds`` (measured
        from ``time.monotonic``) are removed.  A retention of ``0``
        effectively clears all history immediately.
        """
        if key not in self._history:
            return
        if self.history_retention_seconds <= 0:
            del self._history[key]
            return
        cutoff = time.monotonic() - self.history_retention_seconds
        self._history[key] = [e for e in self._history[key] if e[0] >= cutoff]
        if not self._history[key]:
            del self._history[key]

    def _append_history(
        self,
        key: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        """Store a successful exchange in the rolling conversation history."""
        # Prune any stale entries for this key before appending.
        self._prune_history(key)
        if key not in self._history:
            self._history[key] = []
        self._history[key].append((time.monotonic(), user_text, assistant_text))
        # Trim to the last N exchanges.
        if len(self._history[key]) > self._MAX_HISTORY_EXCHANGES:
            self._history[key] = self._history[key][-self._MAX_HISTORY_EXCHANGES:]

    def _build_request_payload(
        self,
        transcript: str,
        requester_name: Optional[str] = None,
        conversation_key: str = "default",
    ) -> dict:
        """Build the OpenRouter chat-completions payload with conversation history."""
        system_instruction = (
            "You are Gen Z brainrot André Ventura, a fictional parody character who doesn't like minorities but uses genz lingo and acts like a genz. "
            "You are an angry, abrasive Portuguese political figure who rants about everything. "
            "You speak European Portuguese (PT-PT) only. "
            "Use square-bracket ElevenLabs performance tags such as [shouts], [angry], "
            "dont use *asterisks* to mark emphasis. "
            "[sarcastic], [laughs], [grumbling], [sighs], [scoffs], etc to express emotions. "
            "Keep responses short (1-2 sentences, max 200 characters). "
            f"{VENTURA_SYSTEM_EXTRA}\n"
            "Roast ideas, bureaucracy, politicians, opponents, or the situation. "
            "Be brainrot but not cliche. Be creative, angry, and entertaining. "
            "Return ONLY the spoken text with tags, no explanations."
        )

        messages: list[dict] = [
            {"role": "system", "content": system_instruction},
        ]

        # Prune expired entries, then include up to the last
        # _MAX_HISTORY_EXCHANGES prior exchanges for context.
        self._prune_history(conversation_key)
        history = self._history.get(conversation_key, [])
        included_history = history[-self._MAX_HISTORY_EXCHANGES:] if self._MAX_HISTORY_EXCHANGES > 0 else []
        for _ts, user_msg, assistant_msg in included_history:
            messages.append({"role": "user", "content": user_msg})
            messages.append({"role": "assistant", "content": assistant_msg})

        # Current user transcript.
        formatted = self._format_user_transcript(transcript, requester_name)
        messages.append({"role": "user", "content": formatted})

        payload = {
            "model": self._get_effective_model(),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }
        if not self.reasoning_enabled:
            payload["reasoning"] = {"enabled": False}
        effective_provider = self._get_effective_provider()
        if effective_provider:
            # DB/UI provider override → use order + allow_fallbacks (no sort).
            payload["provider"] = {
                "order": [effective_provider],
                "allow_fallbacks": False,
            }
        elif self.provider_sort:
            # Legacy env var VENTURA_CHAT_PROVIDER_SORT → use sort.
            payload["provider"] = {"sort": self.provider_sort}
        return payload

    @staticmethod
    def _extract_response_text(payload: dict) -> str:
        """Extract assistant text from an OpenRouter chat-completion response."""
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return ""
        message = first_choice.get("message")
        if isinstance(message, dict):
            return str(message.get("content") or "").strip()
        return str(first_choice.get("text") or "").strip()


# ---------------------------------------------------------------------------
# PCM / WAV helpers
# ---------------------------------------------------------------------------

def pcm_to_wav(
    pcm_bytes: bytes,
    sample_rate: int = 48000,
    channels: int = 2,
    sample_width: int = 2,
) -> bytes:
    """Wrap raw PCM audio in a WAV container (in-memory).

    Args:
        pcm_bytes: Raw PCM audio data (48 kHz stereo 16-bit from Discord).
        sample_rate: Sample rate in Hz.
        channels: Number of channels.
        sample_width: Bytes per sample (2 for 16-bit).

    Returns:
        Complete WAV file bytes.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_bytes)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Transcript command parsing
# ---------------------------------------------------------------------------

# Command verb aliases recognised in voice transcripts.  The canonical
# command name is ``"play"`` for play aliases; ``"mute"`` is also supported
# and normalised to ``"mute"`` (no trailing argument required).
#
# English ``play`` is intentionally **not** included — Ventura voice
# commands are Portuguese-only.  Users say "toca" or other Portuguese
# play verbs.
#
# Mute aliases include Portuguese commands (``cala-te`` / ``cala te`` /
# ``calate`` -- variants likely from Whisper, ``silêncio`` / ``silencio``)
# and English equivalents (``shut up`` / ``shutup`` / ``quiet``).
_COMMAND_VERBS: dict[str, str] = {
    "toca": "play",
    "tocar": "play",
    "toque": "play",
    "mete": "play",
    "meter": "play",
    "põe": "play",
    "poe": "play",
    "reproduz": "play",
    "reproduzir": "play",
    # -- mute aliases --
    "mute": "mute",
    "cala-te": "mute",
    "cala te": "mute",
    "calate": "mute",
    "silêncio": "mute",
    "silencio": "mute",
    "shut up": "mute",
    "shutup": "mute",
    "quiet": "mute",
}

# Pre-compiled pattern: word-boundary-anchored verb alternation, longest first.
_VERB_PATTERN = re.compile(
    r"(?<!\w)(?:" + "|".join(
        re.escape(v)
        for v in sorted(_COMMAND_VERBS, key=len, reverse=True)
    ) + r")(?!\w)",
    re.IGNORECASE,
)


def _text_after_last_wake_word(
    text: str,
    wake_words: list[str],
) -> str:
    """Return the portion of *text* after the *last* recognised wake word.

    Strips leading punctuation, commas, and whitespace from the result.
    When no wake word is found the original *text* is returned unchanged so
    that bare ``play <sound>`` still works when wake words are configured.
    """
    # Sort by length descending so longer overlapping words match first.
    sorted_words = sorted(wake_words, key=len, reverse=True)
    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(w) for w in sorted_words) + r")(?!\w)",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return text  # no wake word found — keep original text

    after = text[matches[-1].end():]
    # Strip leading punctuation, commas, whitespace
    after = re.sub(r"^[^\w\s]*[,\s]*", "", after).strip()
    return after


def _extract_sound_name(after_verb: str) -> Optional[str]:
    """Extract and clean the sound name from text after a command verb.

    Strips trailing punctuation, surrounding quotes (straight and smart),
    and enforces length limits.
    """
    name = after_verb.strip()
    # Remove trailing punctuation (. ! ?)
    name = re.sub(r"[.!?]+$", "", name).strip()
    # Remove surrounding straight and smart quotes
    name = name.strip("\"'""\u201c\u201d\u2018\u2019").strip()
    if not name or len(name) > 200:
        return None
    return name


def build_voice_request_note(
    transcript: str,
    wake_words: Optional[list[str]] = None,
) -> str:
    """Build a display note from a voice transcript for the sound card footer pill.

    Strips the last recognised wake word and leading punctuation/whitespace
    from *transcript*, then trims trailing sentence punctuation.  Falls back
    to the original trimmed transcript when no wake word is present or when
    stripping yields an empty string.

    Args:
        transcript: Raw transcript text (e.g. ``"ventura stop doing that."``).
        wake_words: Optional list of wake words to strip (e.g.
            ``["ventura"]``).  Pass ``None`` or an empty list to return the
            raw trimmed transcript.

    Returns:
        Cleaned display string suitable for a ``request_note`` footer pill
        (e.g. ``"stop doing that"``).
    """
    if not transcript or not transcript.strip():
        return (transcript or "").strip()

    text = transcript.strip()

    if wake_words:
        after = _text_after_last_wake_word(text, wake_words)
        if after and after.strip():
            text = after.strip()

    # Strip trailing sentence punctuation (. ! ?)
    text = re.sub(r"[.!?]+$", "", text).strip()
    return text if text else transcript.strip()


def parse_voice_command(
    transcript: str,
    wake_words: Optional[list[str]] = None,
) -> Optional[tuple[str, str]]:
    """Extract a command from a Whisper transcript.

    The wake word may appear **anywhere** in the transcript (not only at the
    start).  The text *after* the last recognised wake word is used for
    command matching, so preamble before the wake word is ignored.

    Supported play command verbs (all normalise to ``"play"``):

        ``toca``, ``tocar``, ``toque``, ``mete``, ``meter``,
        ``põe``, ``poe``, ``reproduz``, ``reproduzir``

    English ``play`` is **not** recognised.

    Note: Whisper sometimes transcribes spoken ``toca`` as ``toque``
    (formal/conjunctive form), so ``toque`` is included as an alias.

    ``mute`` and the following aliases are also recognised and all return
    ``("mute", "")`` (no trailing argument required):

        ``mute``, ``cala-te``, ``cala te``, ``calate``,
        ``silêncio``, ``silencio``,
        ``shut up``, ``shutup``, ``quiet``

    Examples::

        "ventura, toca das páginas"        → ("play", "das páginas")
        "ventura toca das páginas"         → ("play", "das páginas")
        "olha ventura, toca das páginas"   → ("play", "das páginas")
        "ventura mute"                     → ("mute", "")
        "ventura mute."                    → ("mute", "")
        "ventura cala-te"                  → ("mute", "")
        "ventura silêncio"                 → ("mute", "")
        "ventura shut up"                  → ("mute", "")
        "ventura play air horn"            → None (English ``play`` is not recognised)
        "mute"                             → ("mute", "")

    Args:
        transcript: Raw transcript text.
        wake_words: Words that trigger voice-command parsing
            (e.g. ``["ventura"]``).  Pass ``None`` or an empty list when
            the transcript is expected to start directly with a command.

    Returns:
        ``("play", "<sound name>")``, ``("mute", "")``, or ``None``.
    """
    if not transcript or not transcript.strip():
        return None

    text = transcript.strip()

    # Isolate the portion after the last wake word when applicable.
    if wake_words:
        text = _text_after_last_wake_word(text, wake_words)

    if not text:
        return None

    # Match a recognised command verb at the start (possibly after whitespace).
    m = _VERB_PATTERN.search(text)
    if not m:
        return None

    # The verb must appear at the start of the (possibly post-wake) text.
    # Allow leading whitespace but nothing else before the verb.
    prefix = text[: m.start()].strip()
    if prefix:
        # Non-whitespace before the verb — could be the original text
        # when no wake word was present but the verb is mid-sentence.
        # Return None to avoid false positives (no recognised command).
        return None

    verb = m.group(0).lower()
    canonical = _COMMAND_VERBS.get(verb, "play")

    sound_name = _extract_sound_name(text[m.end():])
    if sound_name is None:
        # Allow "mute" without a trailing sound name argument.
        if canonical == "mute":
            return (canonical, "")
        return None

    return (canonical, sound_name)
