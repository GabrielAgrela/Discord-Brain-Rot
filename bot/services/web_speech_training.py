"""
Web-facing business logic for the speech training labeling UI.

Validates label values, resolves safe file paths, builds API payloads,
delegates persistence to ``SpeechTrainingRepository``, and provides
offline Vosk keyword scanning for unlabeled clips.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from bot.repositories.speech_training import SpeechTrainingRepository

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level Vosk model cache (load once per process)
# ---------------------------------------------------------------------------

_vosk_model = None
_vosk_model_lock = threading.Lock()
_VOSK_MODEL_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "models", "vosk-model-small-pt-0.3")
)


def _get_vosk_model():
    """Return the cached Vosk model, loading it once per process.

    Thread-safe via a module-level lock.  Returns ``None`` when the model
    is unavailable (missing files, import error, load failure).
    """
    global _vosk_model
    if _vosk_model is not None:
        return _vosk_model
    with _vosk_model_lock:
        if _vosk_model is not None:
            return _vosk_model
        try:
            import vosk

            vosk.SetLogLevel(-1)
            if os.path.exists(_VOSK_MODEL_PATH):
                logger.info("Loading Vosk model for keyword scan from %s", _VOSK_MODEL_PATH)
                _vosk_model = vosk.Model(_VOSK_MODEL_PATH)
            else:
                logger.warning("Vosk model not found at %s", _VOSK_MODEL_PATH)
                _vosk_model = None
        except Exception as exc:
            logger.error("Failed to load Vosk model for keyword scan: %s", exc)
            _vosk_model = None
    return _vosk_model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_bytes(num_bytes: int) -> str:
    """Format a byte count into a human-readable string.

    Args:
        num_bytes: Size in bytes (must be non-negative).

    Returns:
        A compact string such as ``"0 B"``, ``"42.1 MB"``, ``"1.2 GB"``.
    """
    if num_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB"]
    unit_idx = 0
    remaining = float(num_bytes)
    while remaining >= 1024 and unit_idx < len(units) - 1:
        remaining /= 1024
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(remaining)} B"
    return f"{remaining:.1f} {units[unit_idx]}"

# Valid label values for the web labeling UI (unused — superseded by DEFAULT_LABEL_OPTIONS)
VALID_LABELS: set[str] = {"chapada", "ventura", "none", ""}

# Default label options shown in the dataset UI
DEFAULT_LABEL_OPTIONS: tuple[str, ...] = ("chapada", "ventura", "none")


class WebSpeechTrainingService:
    """Thin service for the speech training labeling page."""

    KEYWORD_SCAN_MAX_DURATION_SECONDS: float = 30.0
    KEYWORD_SCAN_WORKERS: int = 4  # concurrent workers per scan job

    def __init__(
        self,
        repository: SpeechTrainingRepository,
        data_dir: str,
    ) -> None:
        self.repo = repository
        self.data_dir = Path(data_dir).resolve()

    def ensure_schema(self) -> None:
        """Create the speech_training_clips table if needed."""
        self.repo.ensure_schema()

    # ------------------------------------------------------------------
    # User list
    # ------------------------------------------------------------------

    def get_users(self, guild_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return per-user aggregation for the labeling UI sidebar.

        Args:
            guild_id: Optional guild filter.

        Returns:
            List of user summary dicts.
        """
        return self.repo.list_users(guild_id=guild_id)

    # ------------------------------------------------------------------
    # Storage summary
    # ------------------------------------------------------------------

    def get_storage_summary(
        self, guild_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Return total MP3 storage used and clip count.

        Args:
            guild_id: Optional guild filter.

        Returns:
            Dict with ``total_bytes``, ``total_size`` (human-readable),
            and ``clip_count``.
        """
        raw = self.repo.get_storage_summary(guild_id=guild_id)
        return {
            "total_bytes": raw["total_bytes"],
            "total_size": format_bytes(raw["total_bytes"]),
            "clip_count": raw["clip_count"],
        }

    # ------------------------------------------------------------------
    # Label options (defaults + persisted custom labels)
    # ------------------------------------------------------------------

    def get_label_options(self, guild_id: Optional[str] = None) -> Dict[str, Any]:
        """Return available label options combining defaults and persisted custom labels.

        Default labels (``chapada``, ``ventura``, ``none``, ``unclear``) always
        appear first. Custom labels from the database are appended after,
        de-duplicated against the defaults.

        Args:
            guild_id: Optional guild filter for custom labels.

        Returns:
            Dict with ``labels`` (list of distinct label strings).
        """
        custom_labels = self.repo.list_labels(guild_id=guild_id)
        seen: set[str] = set(DEFAULT_LABEL_OPTIONS)
        combined: list[str] = list(DEFAULT_LABEL_OPTIONS)
        for label in custom_labels:
            if label not in seen:
                seen.add(label)
                combined.append(label)
        return {"labels": combined}

    # ------------------------------------------------------------------
    # Clip list
    # ------------------------------------------------------------------

    _SORT_MAP: dict[str, str] = {
        "newest": ("captured_at", "desc"),
        "oldest": ("captured_at", "asc"),
        "longest": ("duration_seconds", "desc"),
        "shortest": ("duration_seconds", "asc"),
        "unlabeled_first": ("label", "desc"),
        "label_asc": ("label", "asc"),
        "label_desc": ("label", "desc"),
        "speaker_asc": ("username", "asc"),
        "speaker_desc": ("username", "desc"),
        "reviewed_desc": ("reviewed_at", "desc"),
    }

    def get_clips(
        self,
        guild_id: Optional[str] = None,
        user_id: Optional[str] = None,
        label: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
        search: str = "",
        sort: str = "newest",
    ) -> Dict[str, Any]:
        """Return paginated clip payload for the web UI.

        Args:
            guild_id: Optional guild filter.
            user_id: Optional user filter.
            label: Optional label filter (``"unlabeled"`` for NULL/empty).
            page: 1-indexed page.
            per_page: Items per page.
            search: Optional search string.
            sort: Sort preset key (e.g. ``"newest"``, ``"oldest"``, …).

        Returns:
            Dict with ``items``, ``total``, ``page``, ``per_page``,
            ``total_pages``.
        """
        sort_by, sort_dir = self._SORT_MAP.get(sort, ("captured_at", "desc"))
        items, total = self.repo.list_clips(
            guild_id=guild_id,
            user_id=user_id,
            label=label,
            page=page,
            per_page=per_page,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        total_pages = max(1, (total + per_page - 1) // per_page)
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }

    # ------------------------------------------------------------------
    # Clip IDs (unpaginated, for "select all matching filters")
    # ------------------------------------------------------------------

    def get_clip_ids(
        self,
        guild_id: Optional[str] = None,
        user_id: Optional[str] = None,
        label: Optional[str] = None,
        search: str = "",
        sort: str = "newest",
    ) -> Dict[str, Any]:
        """Return IDs of all clips matching the current filters, without pagination.

        Args:
            guild_id: Optional guild filter.
            user_id: Optional user filter.
            label: Optional label filter (``"unlabeled"`` for NULL/empty).
            search: Optional search string.
            sort: Sort preset key (e.g. ``"newest"``, ``"oldest"``, …).

        Returns:
            Dict with ``ids`` (list of ints) and ``total`` (int).
        """
        sort_by, sort_dir = self._SORT_MAP.get(sort, ("captured_at", "desc"))
        ids = self.repo.list_clip_ids(
            guild_id=guild_id,
            user_id=user_id,
            label=label,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        return {"ids": ids, "total": len(ids)}

    # ------------------------------------------------------------------
    # Single clip
    # ------------------------------------------------------------------

    def get_clip(self, clip_id: int) -> Optional[Dict[str, Any]]:
        """Return a single clip by ID.

        Args:
            clip_id: Clip primary key.

        Returns:
            Clip dict or None.
        """
        return self.repo.get_clip(clip_id)

    def resolve_audio_path(self, clip: dict) -> Optional[Path]:
        """Resolve and validate the audio file path for a clip.

        Returns the absolute Path to the MP3 file, or None if the path
        is missing, outside the data directory, or the file does not exist.

        Args:
            clip: Clip dict with ``relative_path``.

        Returns:
            Absolute Path to the audio file, or None.
        """
        rel = clip.get("relative_path", "")
        if not rel:
            return None
        full = (self.data_dir / rel).resolve()
        # Reject path traversal outside data_dir
        try:
            full.relative_to(self.data_dir)
        except ValueError:
            logger.warning("Path traversal blocked: %s", full)
            return None
        if not full.is_file():
            return None
        return full

    # ------------------------------------------------------------------
    # Label update
    # ------------------------------------------------------------------

    LABEL_MAX_LENGTH = 64
    TRANSCRIPT_MAX_LENGTH = 2000
    NOTES_MAX_LENGTH = 2000

    def update_label(
        self,
        clip_id: int,
        label: Optional[str],
        transcript: Optional[str],
        notes: Optional[str],
        reviewer_user_id: str,
        reviewer_username: str,
    ) -> Tuple[bool, str]:
        """Validate and persist a label update for a clip.

        Args:
            clip_id: Clip primary key.
            label: Label value (e.g. ``"chapada"``, ``"ventura"``, etc.).
            transcript: Optional human transcript.
            notes: Optional reviewer notes.
            reviewer_user_id: Discord user ID of the reviewer.
            reviewer_username: Discord username.

        Returns:
            Tuple of ``(success, error_message)``.
        """
        # Validate label
        if label is not None and len(label) > self.LABEL_MAX_LENGTH:
            return False, f"Label exceeds {self.LABEL_MAX_LENGTH} characters"
        if transcript is not None and len(transcript) > self.TRANSCRIPT_MAX_LENGTH:
            return False, f"Transcript exceeds {self.TRANSCRIPT_MAX_LENGTH} characters"
        if notes is not None and len(notes) > self.NOTES_MAX_LENGTH:
            return False, f"Notes exceed {self.NOTES_MAX_LENGTH} characters"

        # Normalize legacy 'unclear' label to None (unlabeled)
        if label and label.strip().lower() == 'unclear':
            label = None

        ok = self.repo.update_review(
            clip_id=clip_id,
            label=label if label else None,
            transcript=transcript if transcript else None,
            notes=notes if notes else None,
            reviewer_user_id=reviewer_user_id,
            reviewer_username=reviewer_username,
        )
        if not ok:
            return False, "Clip not found"
        return True, ""

    # ------------------------------------------------------------------
    # Delete single clip
    # ------------------------------------------------------------------

    def delete_clip(
        self,
        clip_id: int,
        reviewer_user_id: str,
        reviewer_username: str,
    ) -> Tuple[bool, str]:
        """Delete a clip's DB row and its audio file.

        If the audio file is missing or cannot be removed, the DB row is
        still deleted.  A warning is logged for the missing file.

        Args:
            clip_id: Clip primary key.
            reviewer_user_id: Discord user ID of the reviewer.
            reviewer_username: Discord username.

        Returns:
            Tuple of ``(success, error_message)``.
        """
        deleted = self.repo.delete_clip(clip_id)
        if deleted is None:
            return False, "Clip not found"

        rel = deleted.get("relative_path", "")
        if rel:
            full = (self.data_dir / rel).resolve()
            try:
                full.relative_to(self.data_dir)
            except ValueError:
                logger.warning("Path traversal blocked on delete: %s", full)
            else:
                try:
                    full.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove audio file: %s", full)
        return True, ""

    # ------------------------------------------------------------------
    # Bulk label
    # ------------------------------------------------------------------

    MAX_BULK_IDS = 200

    def bulk_label(
        self,
        clip_ids: list[int],
        label: Optional[str],
        reviewer_user_id: str,
        reviewer_username: str,
    ) -> Tuple[bool, str]:
        """Apply a label to multiple clips in one operation.

        Args:
            clip_ids: List of clip primary keys (max ``MAX_BULK_IDS``).
            label: Label value to set.
            reviewer_user_id: Discord user ID of the reviewer.
            reviewer_username: Discord username.

        Returns:
            Tuple of ``(success, error_message)``.
        """
        if not clip_ids:
            return False, "No clips selected"
        if len(clip_ids) > self.MAX_BULK_IDS:
            return False, f"Maximum {self.MAX_BULK_IDS} clips at once"
        if label is not None and len(label) > self.LABEL_MAX_LENGTH:
            return False, f"Label exceeds {self.LABEL_MAX_LENGTH} characters"

        updated = self.repo.bulk_update_review(
            clip_ids=clip_ids,
            label=label if label else None,
            reviewer_user_id=reviewer_user_id,
            reviewer_username=reviewer_username,
        )
        return True, "" if updated > 0 else "No clips found"

    # ------------------------------------------------------------------
    # Bulk delete
    # ------------------------------------------------------------------

    def bulk_delete(
        self,
        clip_ids: list[int],
        reviewer_user_id: str,
        reviewer_username: str,
    ) -> Tuple[bool, str, int]:
        """Delete multiple clips and their audio files.

        Args:
            clip_ids: List of clip primary keys (max ``MAX_BULK_IDS``).
            reviewer_user_id: Discord user ID of the reviewer.
            reviewer_username: Discord username.

        Returns:
            Tuple of ``(success, error_message, deleted_count)``.
        """
        if not clip_ids:
            return False, "No clips selected", 0
        if len(clip_ids) > self.MAX_BULK_IDS:
            return False, f"Maximum {self.MAX_BULK_IDS} clips at once", 0

        clips = self.repo.bulk_delete_clips(clip_ids)
        if not clips:
            return False, "No clips found", 0

        for clip in clips:
            rel = clip.get("relative_path", "")
            if not rel:
                continue
            full = (self.data_dir / rel).resolve()
            try:
                full.relative_to(self.data_dir)
            except ValueError:
                logger.warning("Path traversal blocked on bulk delete: %s", full)
            else:
                try:
                    full.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove audio file: %s", full)

        return True, "", len(clips)

    # ------------------------------------------------------------------
    # Offline keyword scanning
    # ------------------------------------------------------------------

    def scan_unlabeled_keyword(
        self,
        keyword: str = "chapada",
        min_confidence: float = 0.5,
        guild_id: Optional[str] = None,
        user_id: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        delete_non_matches: bool = False,
        label_non_matches_as_none: bool = False,
    ) -> Dict[str, Any]:
        """Scan all unlabeled clips for a keyword using offline Vosk detection.

        Only clips with ``duration_seconds <= KEYWORD_SCAN_MAX_DURATION_SECONDS``
        (default 30.0) are eligible — longer clips are excluded from the
        unlabeled list before any Vosk decoding.

        Decodes each eligible MP3 clip to 16 kHz mono PCM, feeds it to a Vosk
        ``KaldiRecognizer``, and checks word-level confidence for the
        requested keyword.

        Processing is concurrent within this single scan job using a fixed-size
        thread pool (``KEYWORD_SCAN_WORKERS``, default 4). No environment
        variables are consulted.

        Args:
            keyword: The keyword to detect (lowercased for comparison).
            min_confidence: Minimum Vosk word confidence (0‑1) to consider a match.
            guild_id: Optional guild scope for unlabeled clips.
            user_id: Optional user scope for unlabeled clips.
            progress_callback: Optional callback invoked after total is known
                and as clips complete. Receives a dict with keys ``total``,
                ``scanned``, ``matched``, ``skipped``, ``current_clip_id``,
                and ``status`` (``"processing"`` or ``"done"``).  The initial
                call has ``current_clip_id=None``.
            delete_non_matches: When ``True``, delete clips that were
                successfully scanned but did **not** match the keyword.
                Skipped clips (missing audio, decode errors) and matched
                clips are preserved.  Deletion happens **after** the full
                scan completes, using the same batch-safe audio-removal
                logic as ``bulk_delete``.
            label_non_matches_as_none: When ``True`` (and ``delete_non_matches``
                is ``False``), non-matching clips are bulk-labeled as ``none``
                instead of being deleted.  Skipped clips remain untouched.

        Returns:
            Response dict with keys ``status``, ``keyword``,
            ``min_confidence``, ``max_duration_seconds``, ``scanned``,
            ``matched``, ``skipped``, and ``matches`` (list of clip dicts
            augmented with ``keyword_confidence`` and ``keyword_transcript``).
            When ``delete_non_matches`` was ``True``, also includes
            ``delete_non_matches`` (the input flag) and
            ``deleted_non_matches`` (count of clips actually deleted).
            When ``label_non_matches_as_none`` was ``True``, also includes
            that flag and ``labeled_non_matches`` (count).

        Raises:
            ValueError: When validation fails (empty keyword, bad
                confidence).
        """
        # ── Validate parameters ──────────────────────────────────────
        keyword = keyword.strip().lower()
        if not keyword:
            raise ValueError("Keyword must be non-empty")
        if not 0 <= min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1")

        # ── Ensure Vosk model ────────────────────────────────────────
        model = _get_vosk_model()
        if model is None:
            raise ValueError(
                "Vosk model is not available. Check that "
                "vosk-model-small-pt-0.3 exists under data/models/"
            )

        # ── Fetch unlabeled clips (≤30s only) ─────────────────────────
        clips = self.repo.list_unlabeled_clips(
            guild_id=guild_id,
            user_id=user_id,
            max_duration_seconds=self.KEYWORD_SCAN_MAX_DURATION_SECONDS,
        )
        total = len(clips)
        logger.debug(
            "Keyword scan: %d unlabeled clips ≤%ss",
            total, self.KEYWORD_SCAN_MAX_DURATION_SECONDS,
        )

        # ── Notify initial progress ──────────────────────────────────
        scanned = 0
        skipped = 0
        matches: List[Dict[str, Any]] = []
        non_match_ids: List[int] = []
        _lock = threading.Lock()

        if progress_callback is not None:
            progress_callback({
                "total": total,
                "scanned": 0,
                "matched": 0,
                "skipped": 0,
                "current_clip_id": None,
                "status": "processing",
            })

        if total == 0:
            return self._build_scan_result(
                keyword=keyword,
                min_confidence=min_confidence,
                scanned=0,
                matched=0,
                skipped=0,
                matches=[],
                delete_non_matches=delete_non_matches,
                deleted_non_matches=0,
                label_non_matches_as_none=label_non_matches_as_none,
                labeled_non_matches=0,
            )

        # ── Concurrency helpers ──────────────────────────────────────
        distractors = ["chapa", "ada", "cha", "o", "google", "jogo", "do jogo"]
        grammar = [keyword] + distractors + ["[unk]"]
        grammar_json = json.dumps(grammar)

        clip_list = list(clips)  # stable order
        # Map original index -> (clip, future)
        future_map: Dict[int, Any] = {}

        def _scan_one(clip: dict) -> dict:
            """Process a single clip: resolve audio, decode, run Vosk.

            Returns a dict with keys:
                matched (bool), conf (float), text (str), clip_id (int)
            or keys: error (str), clip_id (int)
            """
            path = self.resolve_audio_path(clip)
            if path is None:
                return {"matched": False, "conf": 0.0, "text": "", "clip_id": clip.get("id"), "skipped": True, "error": "no_audio"}

            try:
                from pydub import AudioSegment
                import vosk

                segment = (
                    AudioSegment.from_file(str(path), format="mp3")
                    .set_frame_rate(16000)
                    .set_channels(1)
                    .set_sample_width(2)
                )
                raw_pcm = segment.raw_data

                rec = vosk.KaldiRecognizer(model, 16000, grammar_json)
                rec.SetWords(True)
                rec.AcceptWaveform(raw_pcm)
                result = json.loads(rec.FinalResult())

                text = result.get("text", "").lower()
                word_results = result.get("result", [])

                best_conf = 0.0
                for wi in word_results:
                    w = wi.get("word", "").lower()
                    if w == keyword:
                        conf = wi.get("conf", 0.0)
                        if conf > best_conf:
                            best_conf = conf

                is_match = best_conf >= min_confidence and keyword in text.split()
                return {
                    "matched": is_match,
                    "conf": round(best_conf, 3),
                    "text": text,
                    "clip_id": clip.get("id"),
                    "skipped": False,
                    "error": None,
                }
            except Exception as exc:
                logger.warning("Failed to scan clip %s: %s", clip.get("id"), exc)
                return {"matched": False, "conf": 0.0, "text": "", "clip_id": clip.get("id"), "skipped": True, "error": str(exc)}

        def _notify_locked() -> None:
            """Thread-safe progress notification."""
            if progress_callback is not None:
                p_scanned, p_matched, p_skipped = 0, 0, 0
                with _lock:
                    p_scanned = scanned
                    p_matched = len(matches)
                    p_skipped = skipped
                progress_callback({
                    "total": total,
                    "scanned": p_scanned,
                    "matched": p_matched,
                    "skipped": p_skipped,
                    "current_clip_id": None,
                    "status": "processing",
                })

        # ── Submit all clips to the thread pool ──────────────────────
        pool = ThreadPoolExecutor(max_workers=self.KEYWORD_SCAN_WORKERS)
        for idx, clip in enumerate(clip_list):
            future = pool.submit(_scan_one, clip)
            future_map[idx] = (clip, future)

        # ── Collect results as they complete ─────────────────────────
        all_futures = [f for _, f in future_map.values()]
        while all_futures:
            done, all_futures = wait(all_futures, return_when=FIRST_COMPLETED)
            for fut in done:
                result = fut.result()
                cid = result.get("clip_id")
                with _lock:
                    if result.get("skipped"):
                        skipped += 1
                    elif result.get("matched"):
                        # Find the original clip data to augment
                        for orig in clip_list:
                            if orig.get("id") == cid:
                                aug = dict(orig)
                                aug["keyword_confidence"] = result["conf"]
                                aug["keyword_transcript"] = result["text"]
                                matches.append(aug)
                                break
                        scanned += 1
                    else:
                        non_match_ids.append(cid)
                        scanned += 1
            _notify_locked()

        pool.shutdown(wait=False)

        # ── Post-scan: delete or label non-matches ───────────────────
        deleted_non_matches = 0
        labeled_non_matches = 0

        if delete_non_matches and non_match_ids:
            deleted_non_matches = self._delete_nonmatches(non_match_ids)
        elif label_non_matches_as_none and non_match_ids:
            labeled_non_matches = self._label_nonmatches_as_none(non_match_ids, "none")

        # Sort matches in original clip order
        order_map = {c["id"]: i for i, c in enumerate(clip_list)}
        matches.sort(key=lambda m: order_map.get(m["id"], 999999))

        logger.info(
            "Keyword scan '%s' scanned=%d matched=%d skipped=%d "
            "deleted_nonmatches=%d labeled_nonmatches=%d (eligible clips ≤%ss=%d)",
            keyword, scanned, len(matches), skipped,
            deleted_non_matches, labeled_non_matches,
            self.KEYWORD_SCAN_MAX_DURATION_SECONDS, total,
        )

        return self._build_scan_result(
            keyword=keyword,
            min_confidence=min_confidence,
            scanned=scanned,
            matched=len(matches),
            skipped=skipped,
            matches=matches,
            delete_non_matches=delete_non_matches,
            deleted_non_matches=deleted_non_matches,
            label_non_matches_as_none=label_non_matches_as_none,
            labeled_non_matches=labeled_non_matches,
        )

    _DELETE_CHUNK_SIZE = 500

    def _delete_nonmatches(self, clip_ids: List[int]) -> int:
        """Delete clips and their audio files, chunking to avoid SQLite variable limits.

        Args:
            clip_ids: List of clip primary keys to delete.

        Returns:
            Number of clips actually deleted (may be less than input if some
            rows disappeared before deletion).
        """
        if not clip_ids:
            return 0

        total_deleted = 0

        for i in range(0, len(clip_ids), self._DELETE_CHUNK_SIZE):
            chunk = clip_ids[i : i + self._DELETE_CHUNK_SIZE]
            clips = self.repo.bulk_delete_clips(chunk)
            if not clips:
                continue

            for clip in clips:
                rel = clip.get("relative_path", "")
                if not rel:
                    continue
                full = (self.data_dir / rel).resolve()
                try:
                    full.relative_to(self.data_dir)
                except ValueError:
                    logger.warning("Path traversal blocked on delete: %s", full)
                else:
                    try:
                        full.unlink(missing_ok=True)
                    except OSError:
                        logger.warning("Could not remove audio file: %s", full)

            total_deleted += len(clips)

        return total_deleted

    def _label_nonmatches_as_none(
        self, clip_ids: List[int], label: str
    ) -> int:
        """Bulk-label non-matching clip IDs as a given label value.

        Chunks to avoid SQLite variable limits.
        Uses empty string for reviewer metadata to indicate automated action.

        Args:
            clip_ids: List of clip primary keys to label.
            label: Label value to apply (e.g. ``"none"``).

        Returns:
            Number of clips actually labeled.
        """
        if not clip_ids:
            return 0
        total_labeled = 0
        for i in range(0, len(clip_ids), self._DELETE_CHUNK_SIZE):
            chunk = clip_ids[i : i + self._DELETE_CHUNK_SIZE]
            updated = self.repo.bulk_update_review(
                clip_ids=chunk,
                label=label,
                reviewer_user_id="",
                reviewer_username="(scan)",
            )
            total_labeled += updated
        return total_labeled

    @staticmethod
    def _build_scan_result(
        *,
        keyword: str,
        min_confidence: float,
        scanned: int,
        matched: int,
        skipped: int,
        matches: List[Dict[str, Any]],
        delete_non_matches: bool,
        deleted_non_matches: int,
        label_non_matches_as_none: bool,
        labeled_non_matches: int,
    ) -> Dict[str, Any]:
        """Build the standard scan response dict."""
        result: Dict[str, Any] = {
            "status": "ok",
            "keyword": keyword,
            "min_confidence": min_confidence,
            "max_duration_seconds": WebSpeechTrainingService.KEYWORD_SCAN_MAX_DURATION_SECONDS,
            "scanned": scanned,
            "matched": matched,
            "skipped": skipped,
            "matches": matches,
            "delete_non_matches": delete_non_matches,
            "deleted_non_matches": deleted_non_matches,
            "label_non_matches_as_none": label_non_matches_as_none,
            "labeled_non_matches": labeled_non_matches,
        }
        return result

    @staticmethod
    def _notify_scan_progress(
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
        total: int,
        scanned: int,
        matches: List[Dict[str, Any]],
        skipped: int,
        clip: Dict[str, Any],
    ) -> None:
        """Invoke the progress callback with updated scan state, if set."""
        if progress_callback is not None:
            progress_callback({
                "total": total,
                "scanned": scanned,
                "matched": len(matches),
                "skipped": skipped,
                "current_clip_id": clip.get("id"),
                "status": "processing",
            })

    # ------------------------------------------------------------------
    # Auto-transcribe empty clips via Groq Whisper
    # ------------------------------------------------------------------

    TRANSCRIBE_MAX_CLIPS: int = 500  # safety cap per job

    def transcribe_empty_clips(
        self,
        guild_id: Optional[str] = None,
        user_id: Optional[str] = None,
        groq_api_key: str = "",
        groq_whisper_model: str = "whisper-large-v3",
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Transcribe all clips with empty/missing transcript via Groq Whisper.

        Only processes clips whose ``transcript`` is ``NULL`` or empty.
        The audio file must exist and be readable; missing/unreadable files
        are counted as skipped.

        Processing is **sequential** (one clip at a time) to avoid rate
        limiting.  A safety cap of ``TRANSCRIBE_MAX_CLIPS`` is enforced.

        Args:
            guild_id: Optional guild scope for empty-transcript clips.
            user_id: Optional user scope for empty-transcript clips.
            groq_api_key: The GROQ_API_KEY to use.
            groq_whisper_model: Groq Whisper model name (default
                ``whisper-large-v3``).
            progress_callback: Optional callback invoked after the total
                is known and after each clip. Receives a dict with keys
                ``total``, ``processed``, ``updated``, ``empty_marked``,
                ``skipped``, ``status``. The initial call has
                ``processed=0``.

        Returns:
            Dict with keys ``status``, ``total``, ``processed``,
            ``updated``, ``empty_marked``, ``skipped``, and ``errors``
            (list of error strings, max 20).

        Raises:
            ValueError: When ``groq_api_key`` is empty or missing.
        """
        if not groq_api_key:
            raise ValueError(
                "GROQ_API_KEY is not configured.  "
                "Set the GROQ_API_KEY environment variable and restart the web container."
            )

        # ── Fetch empty-transcript clips ──────────────────────────────
        clips = self.repo.list_empty_transcript_clips(
            guild_id=guild_id,
            user_id=user_id,
        )
        total = len(clips)
        if total > self.TRANSCRIBE_MAX_CLIPS:
            logger.warning(
                "Transcribe: capping %d empty-transcript clips to %d",
                total, self.TRANSCRIBE_MAX_CLIPS,
            )
            clips = clips[: self.TRANSCRIBE_MAX_CLIPS]
            total = len(clips)

        logger.debug(
            "Transcribe: %d clips with empty transcript%s%s",
            total,
            f" guild={guild_id}" if guild_id else "",
            f" user={user_id}" if user_id else "",
        )

        # ── Notify initial progress ──────────────────────────────────
        processed = 0
        updated = 0
        empty_marked = 0
        skipped = 0
        errors: List[str] = []

        if progress_callback is not None:
            progress_callback({
                "total": total,
                "processed": 0,
                "updated": 0,
                "empty_marked": 0,
                "skipped": 0,
                "status": "processing",
            })

        if total == 0:
            result = {
                "status": "ok",
                "total": 0,
                "processed": 0,
                "updated": 0,
                "empty_marked": 0,
                "skipped": 0,
                "errors": [],
            }
            if progress_callback is not None:
                progress_callback({**result, "status": "done"})
            return result

        # ── Process clips sequentially ────────────────────────────────
        from bot.services.voice_command import GroqWhisperService
        from pydub import AudioSegment

        whisper = GroqWhisperService()

        for clip in clips:
            clip_id = clip.get("id")

            # Resolve audio path
            path = self.resolve_audio_path(clip)
            if path is None:
                skipped += 1
                self._notify_transcript_progress(
                    progress_callback, total, processed, updated, empty_marked, skipped,
                )
                continue

            try:
                # Convert MP3 to WAV bytes in memory
                segment = AudioSegment.from_file(str(path), format="mp3")
                wav_buf = io.BytesIO()
                segment.export(wav_buf, format="wav")
                wav_bytes = wav_buf.getvalue()

                # Transcribe via Groq Whisper (sequential)
                result = asyncio.run(whisper.transcribe_detailed(wav_bytes))
                processed += 1

                if result.is_empty:
                    # Successful 200 with empty text → store "-"
                    self.repo.update_transcript(
                        clip_id=clip_id,
                        transcript="-",
                        reviewer_username="(auto-transcript)",
                    )
                    empty_marked += 1
                    updated += 1
                elif result.text:
                    # Non-empty transcript
                    transcript_text = result.text[:self.TRANSCRIPT_MAX_LENGTH]
                    self.repo.update_transcript(
                        clip_id=clip_id,
                        transcript=transcript_text,
                        reviewer_username="(auto-transcript)",
                    )
                    updated += 1
                else:
                    # Failure (timeout, API error, etc.)
                    skipped += 1
                    if len(errors) < 20:
                        clip_filename = clip.get("filename", f"id={clip_id}")
                        errors.append(f"Clip {clip_filename}: {result.error or 'unknown error'}")

            except Exception as exc:
                logger.warning("Failed to transcribe clip %s: %s", clip_id, exc)
                skipped += 1
                if len(errors) < 20:
                    clip_filename = clip.get("filename", f"id={clip_id}")
                    errors.append(f"Clip {clip_filename}: {exc}")

            self._notify_transcript_progress(
                progress_callback, total, processed, updated, empty_marked, skipped,
            )

        # ── Final result ──────────────────────────────────────────────
        logger.info(
            "Auto-transcribe done: %d clips — updated=%d empty_marked=%d skipped=%d",
            total, updated, empty_marked, skipped,
        )

        result = {
            "status": "ok",
            "total": total,
            "processed": processed,
            "updated": updated,
            "empty_marked": empty_marked,
            "skipped": skipped,
            "errors": errors,
        }
        if progress_callback is not None:
            progress_callback({**result, "status": "done"})
        return result

    @staticmethod
    def _notify_transcript_progress(
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
        total: int,
        processed: int,
        updated: int,
        empty_marked: int,
        skipped: int,
    ) -> None:
        """Invoke the progress callback with current transcript state."""
        if progress_callback is not None:
            progress_callback({
                "total": total,
                "processed": processed,
                "updated": updated,
                "empty_marked": empty_marked,
                "skipped": skipped,
                "status": "processing",
            })
