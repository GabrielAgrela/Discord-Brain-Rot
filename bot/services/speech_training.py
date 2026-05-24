"""
Background speech training recorder service.

Receives raw PCM audio segments from ``KeywordDetectionSink``, converts them
to MP3 in a background writer thread, and persists the files + DB records so
they can be labelled in the web labeling UI.
"""

from __future__ import annotations

import logging
import os
import queue
import re
import threading
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

from bot.repositories.speech_training import SpeechTrainingRepository

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment / configuration defaults
# ---------------------------------------------------------------------------

_ENABLED_VAR = "SPEECH_TRAINING_RECORDING_ENABLED"
_DATA_DIR_VAR = "SPEECH_TRAINING_DATA_DIR"
_SILENCE_SECONDS_VAR = "SPEECH_TRAINING_SILENCE_SECONDS"
_MIN_DURATION_VAR = "SPEECH_TRAINING_MIN_DURATION_SECONDS"
_MAX_DURATION_VAR = "SPEECH_TRAINING_MAX_DURATION_SECONDS"
_MIN_RMS_VAR = "SPEECH_TRAINING_MIN_RMS"
_MP3_BITRATE_VAR = "SPEECH_TRAINING_MP3_BITRATE"
_QUEUE_SIZE_VAR = "SPEECH_TRAINING_QUEUE_SIZE"
_SPEECH_RMS_THRESHOLD_VAR = "SPEECH_TRAINING_SPEECH_RMS_THRESHOLD"
_PREROLL_SECONDS_VAR = "SPEECH_TRAINING_PREROLL_SECONDS"
_TRIM_SILENCE_VAR = "SPEECH_TRAINING_TRIM_SILENCE"


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name, "").strip().lower()
    if not val:
        return default
    return val not in {"0", "false", "off", "no"}


def _env_float_clamped(name: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(os.getenv(name, str(default)))
        return max(lo, min(hi, v))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Segment metadata dataclass
# ---------------------------------------------------------------------------


@dataclass
class SpeechTrainingSegment:
    """A discrete voice segment ready for background MP3 export."""

    pcm_data: bytes
    guild_id: Optional[str]
    user_id: str
    username: str
    display_name: Optional[str]
    folder_name: str
    duration_seconds: float
    sample_rate: int = 48000
    channels: int = 2
    sample_width: int = 2


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SpeechTrainingRecorderService:
    """Non-blocking speech training recorder.

    Call :meth:`enqueue_segment` from the Discord receive thread to offload
    PCM-to-MP3 conversion and DB insertion to a background daemon writer.

    Configuration is read from environment variables on construction.
    """

    def __init__(self) -> None:
        self.enabled: bool = _env_bool(_ENABLED_VAR, False)

        # Directory layout: ``<data_dir>/<guild_id>/<folder_name>/<filename>``
        raw_dir = os.getenv(
            _DATA_DIR_VAR,
            os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__), "..", "..", "data", "speech_training"
                )
            ),
        )
        self.data_dir: str = raw_dir.rstrip("/\\")

        # Duration / silence / RMS thresholds
        self.silence_seconds: float = _env_float_clamped(
            _SILENCE_SECONDS_VAR, 0.35, 0.15, 3.0
        )
        self.min_duration_seconds: float = _env_float_clamped(
            _MIN_DURATION_VAR, 0.25, 0.05, 10.0
        )
        self.max_duration_seconds: float = _env_float_clamped(
            _MAX_DURATION_VAR, 10.0, 0.5, 60.0
        )
        self.min_rms: int = _env_int(_MIN_RMS_VAR, 120)
        self.mp3_bitrate: str = str(os.getenv(_MP3_BITRATE_VAR, "64k"))
        self.max_queue_size: int = _env_int(_QUEUE_SIZE_VAR, 200)

        # Energy-based speech detection (per-chunk gating, trailing trim)
        self.speech_rms_threshold: int = _env_int(_SPEECH_RMS_THRESHOLD_VAR, 250)
        """Minimum per-chunk RMS to consider a frame as voiced.
        Segments only start on voiced chunks (plus preroll context).
        Range: 50–5000; adjust downward to make detection more sensitive."""
        self.speech_rms_threshold = max(50, min(5000, self.speech_rms_threshold))

        self.preroll_seconds: float = _env_float_clamped(
            _PREROLL_SECONDS_VAR, 0.08, 0.0, 0.5
        )
        """Seconds of pre-voiced audio to include when a segment starts.
        Provides context so word onsets are not clipped."""

        self.trim_silence: bool = _env_bool(_TRIM_SILENCE_VAR, True)
        """When True, trailing low-energy frames are removed from captured
        segments before enqueuing for export."""

        # Internal write-ahead queue + daemon writer thread
        self._queue: queue.Queue = queue.Queue(maxsize=self.max_queue_size)
        self._running: bool = True
        self._writer_thread: Optional[threading.Thread] = None

        if self.enabled:
            os.makedirs(self.data_dir, exist_ok=True)
            self._start_writer()
            logger.info(
                "[SpeechTrainingRecorder] Enabled. data_dir=%s silence=%.2fs "
                "min_dur=%.2fs max_dur=%.2fs min_rms=%d bitrate=%s "
                "speech_rms_threshold=%d preroll=%.3fs trim_silence=%s",
                self.data_dir,
                self.silence_seconds,
                self.min_duration_seconds,
                self.max_duration_seconds,
                self.min_rms,
                self.mp3_bitrate,
                self.speech_rms_threshold,
                self.preroll_seconds,
                self.trim_silence,
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _start_writer(self) -> None:
        """Start the background MP3 writer daemon thread."""
        if self._writer_thread is not None and self._writer_thread.is_alive():
            return
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="SpeechTrainingWriter",
            daemon=True,
        )
        self._writer_thread.start()

    def stop(self) -> None:
        """Signal the writer thread to shut down after draining."""
        self._running = False
        # Unblock the writer if it is waiting on an empty queue
        try:
            self._queue.put(None, block=False)
        except queue.Full:
            pass

    # ------------------------------------------------------------------
    # Public API (called from KeywordDetectionSink.write thread)
    # ------------------------------------------------------------------

    def enqueue_segment(self, segment: SpeechTrainingSegment) -> bool:
        """Queue a PCM segment for background MP3 export.

        Must be called from the Discord receive thread.  Validates duration
        and RMS thresholds before queueing.  Returns ``False`` when the
        segment is below threshold or the queue is full.

        Args:
            segment: Captured speech segment metadata + raw PCM.

        Returns:
            ``True`` if the segment was queued successfully.
        """
        if not self.enabled:
            return False

        if segment.duration_seconds < self.min_duration_seconds:
            return False

        # Compute RMS to skip near-silent segments
        if len(segment.pcm_data) > 0:
            try:
                rms = _compute_rms(segment.pcm_data, segment.sample_width)
                if rms < self.min_rms:
                    logger.debug(
                        "[SpeechTrainingRecorder] Skipping low-RMS segment: "
                        "rms=%d < min_rms=%d user=%s dur=%.2fs",
                        rms,
                        self.min_rms,
                        segment.username,
                        segment.duration_seconds,
                    )
                    return False
            except Exception:
                logger.warning(
                    "[SpeechTrainingRecorder] RMS computation error",
                    exc_info=True,
                )

        try:
            self._queue.put_nowait(segment)
            return True
        except queue.Full:
            logger.warning(
                "[SpeechTrainingRecorder] Queue full (%d); dropping segment "
                "from user=%s dur=%.2fs",
                self.max_queue_size,
                segment.username,
                segment.duration_seconds,
            )
            return False

    # ------------------------------------------------------------------
    # Background writer
    # ------------------------------------------------------------------

    def _writer_loop(self) -> None:
        """Daemon writer loop: dequeue, export to MP3, insert DB record."""
        repo = SpeechTrainingRepository()

        while self._running:
            try:
                segment: Optional[SpeechTrainingSegment] = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if segment is None:
                break

            try:
                self._write_segment(repo, segment)
            except Exception:
                logger.exception(
                    "[SpeechTrainingRecorder] Failed to write segment for user=%s",
                    segment.username,
                )
            finally:
                self._queue.task_done()

        logger.info("[SpeechTrainingRecorder] Writer thread exited")

    def _write_segment(
        self,
        repo: SpeechTrainingRepository,
        segment: SpeechTrainingSegment,
    ) -> None:
        """Convert PCM to MP3, write file, insert DB record."""
        if not segment.pcm_data:
            return

        # Build directory path
        guild_part = str(segment.guild_id) if segment.guild_id else "noguild"
        folder_part = _sanitise_path_component(segment.folder_name)
        dir_path = os.path.join(self.data_dir, guild_part, folder_part)
        os.makedirs(dir_path, exist_ok=True)

        # Timestamped filename
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
        dur_ms = int(segment.duration_seconds * 1000)
        filename = f"{ts}_{dur_ms}ms.mp3"
        relative_path = f"{guild_part}/{folder_part}/{filename}"
        full_path = os.path.join(self.data_dir, relative_path)

        # Convert to MP3 via pydub
        try:
            from pydub import AudioSegment

            audio = AudioSegment(
                data=segment.pcm_data,
                sample_width=segment.sample_width,
                frame_rate=segment.sample_rate,
                channels=segment.channels,
            )
            audio.export(full_path, format="mp3", bitrate=self.mp3_bitrate)
        except Exception:
            logger.exception(
                "[SpeechTrainingRecorder] pydub export failed for %s",
                filename,
            )
            return

        # Verify file was written
        try:
            byte_size = os.path.getsize(full_path)
        except OSError:
            logger.warning(
                "[SpeechTrainingRecorder] File not found after export: %s",
                full_path,
            )
            return

        # Insert DB record
        try:
            repo.ensure_schema()
            repo.insert_clip(
                guild_id=str(segment.guild_id) if segment.guild_id else None,
                user_id=segment.user_id,
                username=segment.username,
                display_name=segment.display_name,
                folder_name=segment.folder_name,
                filename=filename,
                relative_path=relative_path,
                duration_seconds=segment.duration_seconds,
                byte_size=byte_size,
                sample_rate=segment.sample_rate,
                channels=segment.channels,
                sample_width=segment.sample_width,
            )
        except Exception:
            logger.exception(
                "[SpeechTrainingRecorder] DB insert failed for %s; "
                "removing orphan file %s",
                filename,
                full_path,
            )
            try:
                os.remove(full_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAFE_PATH_RE = re.compile(r"[^\w\-_. ]+", re.UNICODE)


def _sanitise_path_component(name: str) -> str:
    """Strip or replace characters unsafe for directory names."""
    # Collapse whitespace, replace unsafe chars
    result = _SAFE_PATH_RE.sub("_", name).strip()
    if not result:
        result = "unknown"
    if len(result) > 128:
        result = result[:128]
    return result


def _compute_rms(pcm_data: bytes, sample_width: int = 2) -> int:
    """Compute root-mean-square of raw PCM audio.

    Uses a simple manual RMS calculation instead of audioop.rms to avoid
    import overhead in the hot receive path during enqueue.  The
    calculation runs in the calling thread (briefly) so we keep it cheap.
    """
    if not pcm_data:
        return 0
    if sample_width == 2:
        import struct

        fmt = f"<{len(pcm_data) // 2}h"
        samples = struct.unpack(fmt, pcm_data[: len(pcm_data) // 2 * 2])
        if not samples:
            return 0
        sum_sq = sum(s * s for s in samples)
        return int((sum_sq / len(samples)) ** 0.5)
    if sample_width == 1:
        samples = [b - 128 for b in pcm_data]
        sum_sq = sum(s * s for s in samples)
        return int((sum_sq / len(samples)) ** 0.5)
    return 0
