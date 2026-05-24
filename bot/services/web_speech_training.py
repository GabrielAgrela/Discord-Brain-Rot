"""
Web-facing business logic for the speech training labeling UI.

Validates label values, resolves safe file paths, builds API payloads,
and delegates persistence to ``SpeechTrainingRepository``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bot.repositories.speech_training import SpeechTrainingRepository

logger = logging.getLogger(__name__)


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

# Valid label values for the web labeling UI
VALID_LABELS: set[str] = {"chapada", "ventura", "none", "unclear", ""}


class WebSpeechTrainingService:
    """Thin service for the speech training labeling page."""

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
