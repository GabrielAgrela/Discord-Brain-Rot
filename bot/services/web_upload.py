"""
Service layer for authenticated web sound uploads.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import math
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from mutagen.mp3 import MP3
from pydub import AudioSegment
from pydub.effects import compress_dynamic_range
from werkzeug.datastructures import FileStorage

from bot.downloaders.manual import ManualSoundDownloader
from bot.models.web import DiscordWebUser
from bot.repositories.action import ActionRepository
from bot.repositories.sound import SoundRepository
from bot.repositories.web_upload import WebUploadRepository


class WebUploadService:
    """
    Save web-uploaded MP3 files and maintain the upload inbox.
    """

    def __init__(
        self,
        upload_repository: WebUploadRepository,
        sound_repository: SoundRepository,
        action_repository: ActionRepository,
        sounds_dir: str | Path,
    ) -> None:
        """
        Initialize the service.

        Args:
            upload_repository: Repository for upload audit records.
            sound_repository: Repository for sound insertion.
            action_repository: Repository for action audit logging.
            sounds_dir: Destination folder for approved sound files.
        """
        self.upload_repository = upload_repository
        self.sound_repository = sound_repository
        self.action_repository = action_repository
        self.sounds_dir = Path(sounds_dir)
        self.sounds_dir.mkdir(parents=True, exist_ok=True)
        self.manual_downloader = ManualSoundDownloader()
        self.enable_ingest_loudness_normalization = (
            os.getenv("SOUND_INGEST_NORMALIZE_ENABLED", "true").strip().lower()
            not in {"0", "false", "off", "no"}
        )
        self.ingest_loudness_target_dbfs = float(
            os.getenv("SOUND_INGEST_TARGET_DBFS", "-18.0")
        )
        self.ingest_peak_ceiling_dbfs = float(
            os.getenv("SOUND_INGEST_PEAK_CEILING_DBFS", "-2.0")
        )
        self.ingest_compression_enabled = (
            os.getenv("SOUND_INGEST_COMPRESS_ENABLED", "true").strip().lower()
            not in {"0", "false", "off", "no"}
        )
        self.ingest_compression_threshold_dbfs = float(
            os.getenv("SOUND_INGEST_COMPRESS_THRESHOLD_DBFS", "-14.0")
        )
        self.ingest_compression_ratio = max(
            1.0,
            float(os.getenv("SOUND_INGEST_COMPRESS_RATIO", "6.0")),
        )

    def save_upload(
        self,
        *,
        uploaded_file: FileStorage | None,
        current_user: DiscordWebUser,
        guild_id: int | None,
        custom_name: str | None = None,
        source_url: str | None = None,
        time_limit: int | None = None,
        max_mb: int = 20,
    ) -> dict[str, Any]:
        """
        Save an authenticated web upload.

        Uploads are approved by default and immediately inserted into the
        normal sound library. This mirrors the bot upload modal: uploaded MP3
        files take priority over URLs, and URLs may be direct MP3, TikTok,
        YouTube, or Instagram links.

        Args:
            uploaded_file: Optional uploaded MP3 file.
            current_user: Authenticated Discord web user.
            guild_id: Selected guild ID.
            custom_name: Optional custom filename.
            source_url: Optional direct MP3 or video URL.
            time_limit: Optional trim limit in seconds for video URLs.
            max_mb: Maximum accepted upload size in megabytes.

        Returns:
            Upload result payload.
        """
        source_url = (source_url or "").strip()
        has_file = uploaded_file is not None and bool(uploaded_file.filename)
        if not has_file and not source_url:
            raise ValueError("Please provide a URL or upload an MP3 file.")
        if time_limit is not None and time_limit > 999:
            raise ValueError("Time limit must be 999 seconds or less.")

        if has_file:
            final_path, original_filename = self._save_uploaded_file(
                uploaded_file,
                custom_name=custom_name,
                max_mb=max_mb,
            )
        else:
            final_path, original_filename = self._save_url(
                source_url,
                custom_name=custom_name,
                time_limit=time_limit,
                max_mb=max_mb,
            )

        filename = final_path.name
        sound_id = self.sound_repository.insert_sound(
            filename,
            filename,
            guild_id=guild_id,
        )
        upload_id = self.upload_repository.insert_upload(
            guild_id=guild_id,
            sound_id=sound_id,
            filename=filename,
            original_filename=original_filename or filename,
            uploaded_by_username=current_user.global_name or current_user.username,
            uploaded_by_user_id=current_user.id,
            status="approved",
        )
        self.action_repository.insert(
            current_user.global_name or current_user.username,
            "upload_sound",
            filename,
            guild_id=guild_id,
        )
        return {
            "upload_id": upload_id,
            "sound_id": sound_id,
            "filename": filename,
            "status": "approved",
        }

    def _save_uploaded_file(
        self,
        uploaded_file: FileStorage,
        *,
        custom_name: str | None,
        max_mb: int,
    ) -> tuple[Path, str]:
        """Save and validate an uploaded MP3 file."""
        original_filename = (uploaded_file.filename or "").strip()
        if not original_filename.lower().endswith(".mp3") and not custom_name:
            raise ValueError("Only .mp3 files are allowed.")

        content_length = int(getattr(uploaded_file, "content_length", 0) or 0)
        if content_length > max_mb * 1024 * 1024:
            raise ValueError(f"File too large. Max {max_mb}MB.")

        final_filename = self._build_unique_filename(
            self._sanitize_mp3_filename(custom_name or original_filename, "web_upload")
        )
        final_path = self.sounds_dir / final_filename

        uploaded_file.save(final_path)
        self._validate_and_normalize_mp3(final_path, max_mb=max_mb)
        return final_path, original_filename or final_filename

    def _save_url(
        self,
        source_url: str,
        *,
        custom_name: str | None,
        time_limit: int | None,
        max_mb: int,
    ) -> tuple[Path, str]:
        """Save a direct MP3 or supported video URL."""
        if not self._is_supported_upload_url(source_url):
            raise ValueError("Please provide a valid MP3, TikTok, YouTube, or Instagram URL.")

        if self._is_direct_mp3_url(source_url):
            return self._save_direct_mp3_url(
                source_url,
                custom_name=custom_name,
                max_mb=max_mb,
            )

        return self._save_video_url(
            source_url,
            custom_name=custom_name,
            time_limit=time_limit,
            max_mb=max_mb,
        )

    def _save_direct_mp3_url(
        self,
        source_url: str,
        *,
        custom_name: str | None,
        max_mb: int,
    ) -> tuple[Path, str]:
        """Download and save a direct MP3 URL."""
        parsed = urlparse(source_url)
        candidate_name = custom_name or os.path.basename(parsed.path)
        final_filename = self._build_unique_filename(
            self._sanitize_mp3_filename(candidate_name, "url_sound")
        )
        final_path = self.sounds_dir / final_filename

        try:
            response = requests.get(source_url, timeout=30, stream=True)
            if response.status_code != 200:
                raise ValueError(f"Failed to download. Status: {response.status_code}")

            total = 0
            with final_path.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 128):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_mb * 1024 * 1024:
                        raise ValueError(f"File too large. Max {max_mb}MB.")
                    output.write(chunk)
        except Exception:
            final_path.unlink(missing_ok=True)
            raise
        finally:
            if "response" in locals():
                response.close()

        try:
            self._validate_and_normalize_mp3(final_path, max_mb=max_mb)
        except Exception:
            final_path.unlink(missing_ok=True)
            raise
        return final_path, os.path.basename(parsed.path) or final_filename

    def _save_video_url(
        self,
        source_url: str,
        *,
        custom_name: str | None,
        time_limit: int | None,
        max_mb: int,
    ) -> tuple[Path, str]:
        """Download a supported video URL, then validate and approve it."""
        with tempfile.TemporaryDirectory(prefix="web_upload_", dir=str(self.sounds_dir.parent)) as temp_dir:
            downloaded_filename = self.manual_downloader.video_to_mp3(
                source_url,
                temp_dir,
                custom_name,
                time_limit,
            )
            downloaded_path = Path(temp_dir) / downloaded_filename
            if not downloaded_path.exists():
                raise ValueError("Download completed but file verification failed. Please try again.")

            final_filename = self._build_unique_filename(
                self._sanitize_mp3_filename(downloaded_filename, "video_sound")
            )
            final_path = self.sounds_dir / final_filename
            shutil.move(str(downloaded_path), final_path)

        self._validate_and_normalize_mp3(final_path, max_mb=max_mb)
        return final_path, downloaded_filename

    def _validate_and_normalize_mp3(self, final_path: Path, *, max_mb: int) -> None:
        """Validate an MP3 file and apply best-effort ingest normalization."""
        try:
            if final_path.stat().st_size > max_mb * 1024 * 1024:
                raise ValueError(f"File too large. Max {max_mb}MB.")
            MP3(str(final_path))
        except Exception as exc:
            final_path.unlink(missing_ok=True)
            if isinstance(exc, ValueError):
                raise
            raise ValueError("Invalid MP3 file format.") from exc

        self._maybe_normalize_ingested_mp3(final_path)

    def _maybe_normalize_ingested_mp3(self, sound_file: Path) -> None:
        """Normalize ingested MP3 loudness when enabled, without failing upload flow."""
        if not self.enable_ingest_loudness_normalization:
            return
        try:
            self._normalize_mp3_loudness(sound_file, self.ingest_loudness_target_dbfs)
        except Exception:
            # Keep parity with SoundService: normalization is best-effort and
            # should not block otherwise valid uploads.
            return

    def _normalize_mp3_loudness(self, sound_file: Path, target_dbfs: float) -> None:
        """Normalize an MP3 file in-place with compression and peak-safe loudness."""
        temp_path = sound_file.with_suffix(".normalized.tmp.mp3")
        try:
            sound = AudioSegment.from_file(sound_file, format="mp3")
            current_dbfs = float(sound.dBFS)
            if current_dbfs == float("-inf"):
                return

            working_sound = sound
            compression_applied = False
            if self.ingest_compression_enabled:
                working_sound = compress_dynamic_range(
                    working_sound,
                    threshold=self.ingest_compression_threshold_dbfs,
                    ratio=self.ingest_compression_ratio,
                    attack=5.0,
                    release=80.0,
                )
                compression_applied = True

            working_dbfs = float(working_sound.dBFS)
            if not math.isfinite(working_dbfs):
                return

            peak_dbfs = float(working_sound.max_dBFS)
            gain_change = self._calculate_safe_gain(
                current_dbfs=working_dbfs,
                peak_dbfs=peak_dbfs,
                target_dbfs=target_dbfs,
                peak_ceiling_dbfs=self.ingest_peak_ceiling_dbfs,
            )
            if abs(gain_change) < 0.25 and not compression_applied:
                return

            normalized = working_sound.apply_gain(gain_change)
            final_peak_dbfs = float(normalized.max_dBFS)
            if math.isfinite(final_peak_dbfs) and final_peak_dbfs > self.ingest_peak_ceiling_dbfs:
                normalized = normalized.apply_gain(self.ingest_peak_ceiling_dbfs - final_peak_dbfs)

            normalized.export(temp_path, format="mp3")
            os.replace(temp_path, sound_file)
        finally:
            temp_path.unlink(missing_ok=True)

    @staticmethod
    def _calculate_safe_gain(
        current_dbfs: float,
        peak_dbfs: float,
        target_dbfs: float,
        peak_ceiling_dbfs: float,
    ) -> float:
        """Return gain that targets loudness without exceeding peak ceiling."""
        desired_gain = target_dbfs - current_dbfs
        if not math.isfinite(peak_dbfs):
            return desired_gain
        max_allowed_gain = peak_ceiling_dbfs - peak_dbfs
        return min(desired_gain, max_allowed_gain)

    def get_inbox(
        self,
        *,
        limit: int = 50,
        guild_id: int | None = None,
        page: int = 1,
    ) -> dict[str, Any]:
        """
        Return recent web uploads for admin moderation.

        Args:
            limit: Maximum records to return.
            guild_id: Optional guild scope.
            page: One-based inbox page.
        """
        safe_limit = max(1, min(int(limit), 100))
        safe_page = max(1, int(page))
        total = self.upload_repository.count_recent(guild_id=guild_id)
        total_pages = max(1, math.ceil(total / safe_limit))
        safe_page = min(safe_page, total_pages)
        return {
            "uploads": self.upload_repository.get_recent(
                limit=safe_limit,
                guild_id=guild_id,
                offset=(safe_page - 1) * safe_limit,
            ),
            "page": safe_page,
            "per_page": safe_limit,
            "total": total,
            "total_pages": total_pages,
            "unreviewed_count": self.upload_repository.count_unreviewed(guild_id=guild_id),
        }

    def moderate_upload(
        self,
        upload_id: int,
        *,
        status: str,
        moderator: DiscordWebUser,
    ) -> dict[str, Any]:
        """
        Moderate a web upload record.

        Args:
            upload_id: Upload record ID.
            status: ``approved`` or ``rejected``.
            moderator: Admin user.
        """
        upload = self.upload_repository.get_by_id(upload_id)
        if not upload:
            raise ValueError("Upload not found.")

        self.upload_repository.moderate(
            upload_id,
            status=status,
            moderator_username=moderator.global_name or moderator.username,
        )
        sound_id = upload.get("sound_id")
        if sound_id is not None:
            self.upload_repository.set_sound_blacklist(
                int(sound_id),
                blacklist=status == "rejected",
            )
        return {"upload_id": upload_id, "status": status}

    def _build_unique_filename(self, filename: str) -> str:
        """Return a unique destination filename inside ``sounds_dir``."""
        candidate = filename
        base = candidate[:-4]
        counter = 1
        while (self.sounds_dir / candidate).exists():
            candidate = f"{base} {counter}.mp3"
            counter += 1
        return candidate

    @staticmethod
    def _sanitize_mp3_filename(name: str, default_base: str) -> str:
        """Sanitize an MP3 filename while preserving readable spaces."""
        cleaned = (name or "").strip()
        if cleaned.lower().endswith(".mp3"):
            cleaned = cleaned[:-4]
        cleaned = re.sub(r"[^\w\-. ]+", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
        if not cleaned:
            cleaned = default_base
        return f"{cleaned}.mp3"

    @staticmethod
    def _is_direct_mp3_url(source_url: str) -> bool:
        """Return whether the URL points directly to an MP3 path."""
        return bool(re.match(r"^https?://.*\.mp3(?:[?#].*)?$", source_url, re.IGNORECASE))

    @classmethod
    def _is_supported_upload_url(cls, source_url: str) -> bool:
        """Return whether the URL matches the bot upload modal URL allowlist."""
        return bool(
            cls._is_direct_mp3_url(source_url)
            or re.match(r"^https?://.*tiktok\.com/.*$", source_url, re.IGNORECASE)
            or re.match(r"^https?://(www\.)?(youtube\.com|youtu\.be)/.*$", source_url, re.IGNORECASE)
            or re.match(
                r"^https?://(www\.)?instagram\.com/(p|reels|reel|stories)/.*$",
                source_url,
                re.IGNORECASE,
            )
        )
