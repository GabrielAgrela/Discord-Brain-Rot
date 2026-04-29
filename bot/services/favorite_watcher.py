"""
Service for watching TikTok favorite collection URLs and importing new videos.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import yt_dlp

from bot.repositories import ActionRepository, FavoriteWatcherRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FavoriteCollectionVideo:
    """A single video entry discovered in a TikTok collection."""

    video_id: str
    url: str


class FavoriteWatcherService:
    """Manage TikTok collection watchers and import newly added videos."""

    def __init__(
        self,
        sound_service,
        behavior=None,
        watcher_repo: Optional[FavoriteWatcherRepository] = None,
        action_repo: Optional[ActionRepository] = None,
    ) -> None:
        """
        Initialize the watcher service.

        Args:
            sound_service: SoundService used to import video audio.
            behavior: Optional BotBehavior used to send Discord notifications.
            watcher_repo: Optional repository override for tests.
            action_repo: Optional action repository override for tests.
        """
        self.sound_service = sound_service
        self.behavior = behavior
        self.watcher_repo = watcher_repo or FavoriteWatcherRepository()
        self.action_repo = action_repo or ActionRepository()
        self.max_entries_per_scan = self._env_int("FAVORITE_WATCHER_SCAN_LIMIT", 50)

    async def add_watcher(
        self,
        *,
        url: str,
        guild_id: int | None,
        added_by_user_id: int | None,
        added_by_username: str | None,
    ) -> tuple[int, int]:
        """
        Add a collection watcher and seed the current videos as already seen.

        Args:
            url: TikTok collection URL.
            guild_id: Guild where future sounds should be imported.
            added_by_user_id: Discord user ID adding the watcher.
            added_by_username: Discord username adding the watcher.

        Returns:
            Tuple of watcher ID and number of videos seeded as the baseline.
        """
        normalized_url = self._normalize_collection_url(url)
        videos = await self.fetch_collection_videos(normalized_url)
        watcher_id = self.watcher_repo.add_watcher(
            url=normalized_url,
            guild_id=guild_id,
            added_by_user_id=added_by_user_id,
            added_by_username=added_by_username,
        )
        for video in videos:
            self.watcher_repo.record_video_seen(
                watcher_id=watcher_id,
                video_id=video.video_id,
                video_url=video.url,
            )
        self.watcher_repo.mark_checked(watcher_id)
        return watcher_id, len(videos)

    def list_watchers(self, guild_id: int | None) -> list:
        """Return enabled watchers for a guild."""
        return self.watcher_repo.list_watchers(guild_id)

    def remove_watcher(self, watcher_id: int, guild_id: int | None) -> bool:
        """Disable a watcher for a guild."""
        return self.watcher_repo.remove_watcher(watcher_id, guild_id)

    async def poll_once(self) -> int:
        """
        Poll every enabled watcher once and import videos not seen before.

        Returns:
            Number of new sounds imported.
        """
        imported_count = 0
        for watcher in self.watcher_repo.get_enabled_watchers():
            try:
                imported_count += await self._poll_watcher(watcher)
            except Exception as exc:
                logger.error(
                    "[FavoriteWatcherService] Watcher %s failed: %s",
                    watcher["id"],
                    exc,
                    exc_info=True,
                )
        return imported_count

    async def _poll_watcher(self, watcher) -> int:
        """Poll one watcher row."""
        watcher_id = int(watcher["id"])
        videos = await self.fetch_collection_videos(str(watcher["url"]))
        known_ids = self.watcher_repo.get_known_video_ids(watcher_id)
        new_videos = [video for video in videos if video.video_id not in known_ids]
        imported_count = 0

        for video in reversed(new_videos):
            guild_id = int(watcher["guild_id"]) if watcher["guild_id"] else None
            final_path = await self.sound_service.import_sound_from_video(
                video.url,
                guild_id=guild_id,
            )
            filename = final_path.rsplit("/", 1)[-1]
            imported_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            self.watcher_repo.record_video_seen(
                watcher_id=watcher_id,
                video_id=video.video_id,
                video_url=video.url,
                imported_at=imported_at,
                sound_filename=filename,
            )
            self.action_repo.insert(
                "favorite_watcher",
                "favorite_watcher_import",
                filename,
                guild_id=guild_id,
            )
            await self._notify_import(filename, guild_id=guild_id)
            imported_count += 1
            logger.info(
                "[FavoriteWatcherService] Imported TikTok collection video %s as %s",
                video.video_id,
                filename,
            )

        self.watcher_repo.mark_checked(watcher_id)
        return imported_count

    async def _notify_import(self, filename: str, guild_id: int | None) -> None:
        """Send a Discord notification for a newly imported watcher sound."""
        if self.behavior is None:
            return

        guild = None
        if guild_id is not None:
            bot = getattr(self.behavior, "bot", None)
            guild = bot.get_guild(guild_id) if bot and hasattr(bot, "get_guild") else None

        try:
            from bot.ui import DownloadedSoundView

            await self.behavior.send_message(
                title=f"🎵 New favorite sound imported: {filename}",
                view=DownloadedSoundView(self.behavior, filename),
                guild=guild,
                message_format="image",
                image_requester="Favorite Watcher",
                image_show_footer=False,
                image_show_sound_icon=False,
                image_border_color="#ED4245",
            )
        except Exception as exc:
            logger.error(
                "[FavoriteWatcherService] Failed to send import notification for %s: %s",
                filename,
                exc,
                exc_info=True,
            )

    async def fetch_collection_videos(self, url: str) -> list[FavoriteCollectionVideo]:
        """Fetch collection video entries without downloading media."""
        return await asyncio.to_thread(self._fetch_collection_videos_sync, url)

    def _fetch_collection_videos_sync(self, url: str) -> list[FavoriteCollectionVideo]:
        """Synchronous yt-dlp collection metadata extraction."""
        ydl_opts = {
            "extract_flat": True,
            "ignoreerrors": True,
            "playlistend": self.max_entries_per_scan,
            "quiet": True,
            "skip_download": True,
            "noconfig": True,
        }
        cookies_file = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "Data", "cookies.txt")
        )
        if os.path.exists(cookies_file):
            ydl_opts["cookiefile"] = cookies_file

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        entries = []
        collection_username = self._username_from_collection_url(url)
        for raw_entry in (info or {}).get("entries") or []:
            if not raw_entry:
                continue
            video_id = str(raw_entry.get("id") or "").strip()
            video_url = str(raw_entry.get("webpage_url") or raw_entry.get("url") or "").strip()
            if video_url and not video_url.startswith("http"):
                entry_id = video_id or video_url.rstrip("/").rsplit("/", 1)[-1]
                video_url = f"https://www.tiktok.com/@{collection_username}/video/{entry_id}"
            if not video_id and video_url:
                video_id = self._video_id_from_url(video_url)
            if not video_id or not video_url:
                continue
            entries.append(FavoriteCollectionVideo(video_id=video_id, url=video_url))
        return entries

    @staticmethod
    def _normalize_collection_url(url: str) -> str:
        """Validate and normalize a TikTok collection URL."""
        cleaned = (url or "").strip()
        if not re.match(r"^https?://([^/]+\.)?tiktok\.com/@[^/]+/collection/[^/?#]+", cleaned, re.IGNORECASE):
            raise ValueError("Provide a TikTok collection URL like https://www.tiktok.com/@user/collection/name-123.")
        return cleaned

    @staticmethod
    def _video_id_from_url(url: str) -> str:
        """Extract a stable video ID from a TikTok video URL."""
        match = re.search(r"/video/(\d+)", url)
        if match:
            return match.group(1)
        return url.rstrip("/").rsplit("/", 1)[-1]

    @staticmethod
    def _username_from_collection_url(url: str) -> str:
        """Extract the TikTok username from a collection URL."""
        match = re.search(r"tiktok\.com/@([^/]+)/collection/", url, re.IGNORECASE)
        return match.group(1) if match else "i"

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        """Parse a positive integer environment variable."""
        try:
            return max(1, int(os.getenv(name, str(default)).strip()))
        except ValueError:
            return default
