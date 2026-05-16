"""
Voice command service using Groq Whisper for transcription.

When Vosk detects the configured wake word (default "ventura", which is
in-vocabulary for the bundled Portuguese Vosk model vosk-model-small-pt-0.3),
a start prompt clip is played from ``Sounds/`` (no DB lookup), then *fresh*
post-prompt PCM audio for that user is recorded until silence or max duration.
After capture, a done prompt clip is played.  The captured audio is sent to
Groq Whisper for transcription.  If the transcript matches a recognised
command verb (e.g. ``play``, ``toca``), the sound is played via
SoundService.play_request.

The transcript parser searches for the wake word **anywhere** in the returned
text (not only at the start), so English preamble such as
"What the fuck was that? Ventura, play das páginas." is handled correctly.
Both English (``play``) and Portuguese (``toca``, ``tocar``, ``mete``,
``meter``, ``põe``, ``poe``, ``reproduz``, ``reproduzir``) command verbs are
supported and normalised to ``"play"``.

Both the human-facing wake words (VOICE_COMMAND_WAKE_WORDS) and the Vosk
aliases (VOICE_COMMAND_WAKE_ALIASES) are combined and stripped from Groq
transcripts during command parsing.

Historical note: The prior default wake word was "bot", which was out of
vocabulary (OOV) for the Portuguese model.  It required Portuguese phonetic
aliases ("bote", "bota", "boto") configured via VOICE_COMMAND_WAKE_ALIASES.
"""

import asyncio
import io
import logging
import os
import re
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp

from config import PROJECT_ROOT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment defaults
# ---------------------------------------------------------------------------
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")

GROQ_WHISPER_MODEL: str = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")

# Optional prompt to guide Groq Whisper for mixed-language speech (e.g. English
# preamble + Portuguese command).  Sent as the ``prompt`` field when non-empty.
GROQ_WHISPER_PROMPT: str = os.getenv(
    "GROQ_WHISPER_PROMPT",
    "Mixed Portuguese and English Discord voice command. "
    "Preserve the wake word Ventura, command words such as play/toca, "
    "and sound names exactly.",
)

# Optional language hint sent to Groq Whisper.  Leave empty (default) for auto-
# detect since users mix Portuguese and English.
GROQ_WHISPER_LANGUAGE: str = os.getenv("GROQ_WHISPER_LANGUAGE", "")

_whisper_timeout = 20
try:
    _whisper_timeout = int(os.getenv("GROQ_WHISPER_TIMEOUT_SECONDS", "20"))
except ValueError:
    pass
GROQ_WHISPER_TIMEOUT: int = max(1, _whisper_timeout)

# Debug save: persist the exact WAV bytes sent to Groq for debugging.
_GROQ_WHISPER_DEBUG_SAVE: bool = (
    os.getenv("GROQ_WHISPER_DEBUG_SAVE_AUDIO", "true").strip().lower()
    not in {"0", "false", "off", "no"}
)

_GROQ_WHISPER_DEBUG_DIR: str = os.getenv("GROQ_WHISPER_DEBUG_AUDIO_DIR", "")
if not _GROQ_WHISPER_DEBUG_DIR:
    _GROQ_WHISPER_DEBUG_DIR = str(PROJECT_ROOT / "Debug" / "groq_whisper")

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
# command name is always ``"play"`` so callers do not need to handle
# Portuguese variants.
_COMMAND_VERBS: dict[str, str] = {
    "play": "play",
    "toca": "play",
    "tocar": "play",
    "mete": "play",
    "meter": "play",
    "põe": "play",
    "poe": "play",
    "reproduz": "play",
    "reproduzir": "play",
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


def parse_voice_command(
    transcript: str,
    wake_words: Optional[list[str]] = None,
) -> Optional[tuple[str, str]]:
    """Extract a command from a Whisper transcript.

    The wake word may appear **anywhere** in the transcript (not only at the
    start).  The text *after* the last recognised wake word is used for
    command matching, so preamble before the wake word is ignored.

    Supported command verbs (all normalised to ``"play"``):

        ``play``, ``toca``, ``tocar``, ``mete``, ``meter``,
        ``põe``, ``poe``, ``reproduz``, ``reproduzir``

    Examples::

        "Ventura, play das páginas."       → ("play", "das páginas")
        "ventura toca das páginas"         → ("play", "das páginas")
        "olha ventura, toca das páginas"   → ("play", "das páginas")
        "play something"                   → ("play", "something")

    Args:
        transcript: Raw transcript text.
        wake_words: Words that trigger voice-command parsing
            (e.g. ``["ventura"]``).  Pass ``None`` or an empty list when
            the transcript is expected to start directly with a command.

    Returns:
        ``("play", "<sound name>")`` or ``None``.
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
        return None

    return (canonical, sound_name)
