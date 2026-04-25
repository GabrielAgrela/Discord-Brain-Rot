"""
Service for rendering year review animations with Remotion.

The Python service prepares the same analytics used by /yearreview, asks the
Remotion composition to render an MP4, then converts it to a compact GIF that
can be uploaded directly to Discord.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


ProgressCallback = Optional[Callable[[int, str], None]]


@dataclass
class YearReviewVideoResult:
    """Result metadata for a rendered year review animation."""

    path: str
    size_bytes: int
    compact_mode: bool = False


class YearReviewVideoService:
    """Render Discord Brain Rot themed year review animations via Remotion."""

    def __init__(
        self,
        output_dir: Optional[str] = None,
        trailer_dir: Optional[str] = None,
        composition_entry: Optional[str] = None,
    ):
        """Initialize the Remotion renderer.

        Args:
            output_dir: Optional directory where generated files are stored.
            trailer_dir: Directory containing Remotion's node_modules.
            composition_entry: Optional Remotion entrypoint path.
        """
        repo_root = Path(__file__).resolve().parents[2]
        self.output_dir = Path(output_dir or repo_root / "Debug" / "year_reviews").resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.trailer_dir = Path(trailer_dir or repo_root / "trailer").resolve()
        self.composition_entry = Path(
            composition_entry or repo_root / "bot" / "remotion_year_review" / "index.tsx"
        ).resolve()
        self.composition_id = "YearReview"
        self.remotion_binary = self.trailer_dir / "node_modules" / ".bin" / "remotion"
        self.ffmpeg_binary = os.getenv("FFMPEG_PATH", "ffmpeg")
        self.render_timeout_seconds = int(os.getenv("YEAR_REVIEW_RENDER_TIMEOUT_SECONDS", "180"))

    def render_year_review_gif(
        self,
        *,
        username: str,
        display_name: str,
        year: int,
        stats: Dict[str, Any],
        avatar_url: Optional[str] = None,
        max_bytes: int = 8 * 1024 * 1024,
        progress_callback: ProgressCallback = None,
    ) -> YearReviewVideoResult:
        """Render a compact animated GIF for a user's year review.

        Args:
            username: Stable Discord username used for the output filename.
            display_name: Display name shown in the animation.
            year: Review year.
            stats: Year review statistics from ``StatsRepository``.
            avatar_url: Optional Discord avatar URL.
            max_bytes: Maximum desired GIF size in bytes.
            progress_callback: Optional callback receiving percent and label.

        Returns:
            Metadata for the rendered GIF.
        """
        props = self._build_remotion_props(
            username=username,
            display_name=display_name,
            year=year,
            stats=stats,
            avatar_url=avatar_url,
        )
        return self._render_props_gif(
            username=username,
            display_name=display_name,
            year=year,
            kind="year-review",
            props=props,
            max_bytes=max_bytes,
            progress_callback=progress_callback,
        )

    def render_weekly_wrapped_gif(
        self,
        *,
        guild_name: str,
        days: int,
        stats: Dict[str, Any],
        max_bytes: int = 8 * 1024 * 1024,
        progress_callback: ProgressCallback = None,
    ) -> YearReviewVideoResult:
        """Render a compact animated GIF for a guild's weekly wrapped digest.

        Args:
            guild_name: Guild/server name shown in the animation.
            days: Rolling window size.
            stats: Weekly wrapped statistics.
            max_bytes: Maximum desired GIF size in bytes.
            progress_callback: Optional callback receiving percent and label.

        Returns:
            Metadata for the rendered GIF.
        """
        props = self._build_weekly_wrapped_props(
            guild_name=guild_name,
            days=days,
            stats=stats,
        )
        return self._render_props_gif(
            username=guild_name,
            display_name=guild_name,
            year=int(stats.get("year") or time.strftime("%Y")),
            kind="weekly-wrapped",
            props=props,
            max_bytes=max_bytes,
            progress_callback=progress_callback,
        )

    def _render_props_gif(
        self,
        *,
        username: str,
        display_name: str,
        year: int,
        kind: str,
        props: Dict[str, Any],
        max_bytes: int,
        progress_callback: ProgressCallback,
    ) -> YearReviewVideoResult:
        """Render prepared Remotion props to a compact GIF."""
        progress_callback = progress_callback or (lambda _percent, _label: None)
        safe_username = self._safe_filename(username or display_name or "user")
        output_stem = f"{safe_username}-{year}-{kind}"
        props_path = self.output_dir / f"{output_stem}.json"
        mp4_path = self.output_dir / f"{output_stem}.mp4"

        progress_callback(8, "Writing Remotion props")
        props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")

        progress_callback(18, "Rendering Remotion video")
        self._render_remotion_mp4(props_path=props_path, mp4_path=mp4_path)

        progress_callback(76, "Converting video to GIF")
        gif_path, compact_mode = self._convert_mp4_to_gif(
            mp4_path=mp4_path,
            output_stem=output_stem,
            max_bytes=max_bytes,
            progress_callback=progress_callback,
        )

        size_bytes = gif_path.stat().st_size
        progress_callback(96, "GIF ready")
        return YearReviewVideoResult(
            path=str(gif_path),
            size_bytes=size_bytes,
            compact_mode=compact_mode,
        )

    def _render_remotion_mp4(self, *, props_path: Path, mp4_path: Path) -> None:
        """Render the Remotion composition to MP4."""
        if not self.remotion_binary.exists():
            raise FileNotFoundError(f"Remotion binary not found at {self.remotion_binary}")
        if not self.composition_entry.exists():
            raise FileNotFoundError(f"Remotion entrypoint not found at {self.composition_entry}")

        command = [
            str(self.remotion_binary),
            "render",
            str(self.composition_entry),
            self.composition_id,
            str(mp4_path),
            f"--props={props_path}",
            "--overwrite",
            "--codec=h264",
            "--crf=28",
            "--pixel-format=yuv420p",
            "--log=warn",
        ]
        browser_executable = self._browser_executable()
        if browser_executable:
            command.append(f"--browser-executable={browser_executable}")
        self._run_command(command, cwd=self.trailer_dir, timeout=self.render_timeout_seconds)

    def _browser_executable(self) -> Optional[str]:
        """Return a system Chrome/Chromium path when available."""
        candidates = [
            os.getenv("REMOTION_BROWSER_EXECUTABLE"),
            os.getenv("CHROME_PATH"),
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/google-chrome",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return candidate
        return None

    def _convert_mp4_to_gif(
        self,
        *,
        mp4_path: Path,
        output_stem: str,
        max_bytes: int,
        progress_callback: Callable[[int, str], None],
    ) -> Tuple[Path, bool]:
        """Convert rendered MP4 to GIF, retrying smaller presets when needed."""
        presets = [
            {"width": 640, "fps": 9, "colors": 80, "suffix": "gif"},
            {"width": 560, "fps": 8, "colors": 72, "suffix": "compact"},
            {"width": 480, "fps": 7, "colors": 56, "suffix": "tiny"},
            {"width": 420, "fps": 6, "colors": 48, "suffix": "micro"},
        ]

        last_path: Optional[Path] = None
        for index, preset in enumerate(presets):
            percent = 78 + (index * 4)
            progress_callback(
                percent,
                f"Encoding GIF {preset['width']}px/{preset['fps']}fps",
            )
            gif_path = self.output_dir / f"{output_stem}-{preset['suffix']}.gif"
            self._encode_gif(
                mp4_path=mp4_path,
                gif_path=gif_path,
                width=int(preset["width"]),
                fps=int(preset["fps"]),
                colors=int(preset["colors"]),
            )
            last_path = gif_path
            if gif_path.stat().st_size <= max_bytes:
                return gif_path, index > 0

        if last_path is None:
            raise RuntimeError("GIF conversion produced no output.")
        return last_path, True

    def _encode_gif(
        self,
        *,
        mp4_path: Path,
        gif_path: Path,
        width: int,
        fps: int,
        colors: int,
    ) -> None:
        """Encode a GIF with palette generation for better quality per byte."""
        palette_path = gif_path.with_suffix(".palette.png")
        filters = f"fps={fps},scale={width}:-1:flags=lanczos"
        palette_command = [
            self.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(mp4_path),
            "-vf",
            f"{filters},palettegen=max_colors={colors}:stats_mode=diff",
            str(palette_path),
        ]
        gif_command = [
            self.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(mp4_path),
            "-i",
            str(palette_path),
            "-lavfi",
            f"{filters} [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=3",
            "-loop",
            "0",
            str(gif_path),
        ]
        self._run_command(palette_command, cwd=self.output_dir, timeout=60)
        self._run_command(gif_command, cwd=self.output_dir, timeout=60)
        try:
            palette_path.unlink()
        except OSError:
            pass

    def _run_command(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        """Run a subprocess and raise a useful error if it fails."""
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}\n{stderr}")
        return completed

    def _build_remotion_props(
        self,
        *,
        username: str,
        display_name: str,
        year: int,
        stats: Dict[str, Any],
        avatar_url: Optional[str],
    ) -> Dict[str, Any]:
        """Build props consumed by the Remotion composition."""
        total_plays = int(stats.get("total_plays") or 0)
        unique_sounds = int(stats.get("unique_sounds") or 0)
        voice_hours = float(stats.get("total_voice_hours") or 0)
        rank = stats.get("user_rank")
        total_users = stats.get("total_users")
        top_sounds = [
            {"name": self._clean_sound_name(filename), "plays": int(count)}
            for filename, count in (stats.get("top_sounds") or [])[:4]
        ]

        return {
            "username": username,
            "displayName": display_name,
            "year": year,
            "avatarUrl": avatar_url,
            "headlineStats": [
                {"label": "plays", "value": self._format_number(total_plays), "tone": "blurple"},
                {"label": "unique sounds", "value": self._format_number(unique_sounds), "tone": "green"},
                {"label": "voice hours", "value": f"{voice_hours:g}h", "tone": "pink"},
            ],
            "playBreakdown": [
                {"label": "requested", "value": int(stats.get("requested_plays") or 0)},
                {"label": "random", "value": int(stats.get("random_plays") or 0)},
                {"label": "favorites", "value": int(stats.get("favorite_plays") or 0)},
            ],
            "rankText": f"Rank #{rank} of {total_users}" if rank and total_users else "No rank data yet",
            "topSounds": top_sounds,
            "timing": {
                "favoriteDay": stats.get("most_active_day") or "No data",
                "peakHour": self._hour_text(stats.get("most_active_hour")),
                "activeDays": self._format_number(stats.get("total_active_days") or 0),
                "longestStreak": f"{int(stats.get('longest_streak') or 0)} days",
            },
            "journey": {
                "firstSound": self._clean_sound_name(stats.get("first_sound")) or "No data",
                "firstDate": self._date_text(stats.get("first_sound_date")),
                "latestSound": self._clean_sound_name(stats.get("last_sound")) or "No data",
                "latestDate": self._date_text(stats.get("last_sound_date")),
            },
            "finalLine": (
                f"{self._format_number(total_plays)} plays, "
                f"{self._format_number(unique_sounds)} unique sounds, {voice_hours:g}h in voice"
            ),
        }

    def _build_weekly_wrapped_props(
        self,
        *,
        guild_name: str,
        days: int,
        stats: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build props consumed by the Remotion composition for weekly wrapped."""
        total_plays = int(stats.get("total_plays") or 0)
        active_users = int(stats.get("active_users") or 0)
        voice_hours = float(stats.get("voice_hours") or 0)
        new_sounds = int(stats.get("new_sounds") or 0)
        top_sounds = [
            {"name": self._clean_sound_name(name), "plays": int(count)}
            for name, count in (stats.get("top_sounds") or [])[:5]
        ]
        top_users = stats.get("top_users") or []
        top_voice_users = stats.get("top_voice_users") or []
        top_voice_channels = stats.get("top_voice_channels") or []
        weird_stats = stats.get("weird_stats") or []

        return {
            "mode": "weekly",
            "username": guild_name,
            "displayName": guild_name,
            "year": int(stats.get("year") or time.strftime("%Y")),
            "commandLabel": "/weeklywrapped",
            "kicker": f"last {days} day{'s' if days != 1 else ''} server recap",
            "title": f"{guild_name} weekly wrapped",
            "subtitle": "the server's loudest little highlight reel",
            "avatarUrl": None,
            "headlineStats": [
                {"label": "plays", "value": self._format_number(total_plays), "tone": "blurple"},
                {"label": "active users", "value": self._format_number(active_users), "tone": "green"},
                {"label": "voice hours", "value": f"{voice_hours:g}h", "tone": "pink"},
            ],
            "playBreakdown": [],
            "rankText": stats.get("window_text") or f"Rolling {days} day window",
            "topSounds": top_sounds,
            "timing": {
                "favoriteDay": stats.get("favorite_day") or "No data",
                "peakHour": stats.get("peak_window") or "No peak yet",
                "activeDays": self._format_number(days),
                "longestStreak": f"{new_sounds} new",
            },
            "journey": {
                "firstSound": str(top_users[0][0]) if top_users else "No top user yet",
                "firstDate": "top button presser",
                "latestSound": str(top_voice_users[0].get("username")) if top_voice_users else "No voice MVP yet",
                "latestDate": "voice MVP",
            },
            "finalLine": (
                f"{self._format_number(total_plays)} plays, "
                f"{self._format_number(active_users)} active users, {voice_hours:g}h in voice"
            ),
            "outroTitle": "Same time next week.",
            "footerAccent": "generated by /weeklywrapped",
            "weeklyWindow": stats.get("window_text") or f"Rolling {days} day window",
            "weeklySections": [
                {
                    "title": "Top Sounds",
                    "subtitle": "sounds",
                    "items": [
                        {"name": item["name"], "value": f"{item['plays']}x"}
                        for item in top_sounds
                    ] or [{"name": "No sound plays this week", "value": "-"}],
                },
                {
                    "title": "Top Users",
                    "subtitle": "button pressers",
                    "items": [
                        {"name": str(name), "value": str(int(count))}
                        for name, count in top_users[:5]
                    ] or [{"name": "No active users this week", "value": "-"}],
                },
                {
                    "title": "Voice MVPs",
                    "subtitle": "voice activity",
                    "items": [
                        {
                            "name": str(item.get("username") or "Unknown"),
                            "meta": f"{float(item.get('total_hours', 0) or 0):.2f}h",
                            "value": str(int(item.get("session_count", 0) or 0)),
                        }
                        for item in top_voice_users[:5]
                    ] or [{"name": "No voice activity this week", "value": "-"}],
                },
                {
                    "title": "Busiest Voice Channels",
                    "subtitle": "voice rooms",
                    "items": [
                        {
                            "name": str(item.get("name") or item.get("channel_name") or item.get("channel_id") or "Unknown"),
                            "meta": f"{float(item.get('total_hours', 0) or 0):.2f}h",
                            "value": str(int(item.get("session_count", 0) or 0)),
                        }
                        for item in top_voice_channels[:5]
                    ] or [{"name": "No active voice channels this week", "value": "-"}],
                },
                {
                    "title": "Weird Stats",
                    "subtitle": "lab results",
                    "items": [
                        {"name": str(line), "value": ""}
                        for line in weird_stats[:5]
                    ] or [{"name": f"New sounds added this week: {new_sounds}", "value": ""}],
                },
            ],
        }

    def _safe_filename(self, value: str) -> str:
        """Convert a display value into a safe filename."""
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
        return cleaned[:80] or f"year-review-{int(time.time())}"

    def _clean_sound_name(self, filename: Optional[str]) -> str:
        """Return a display-friendly sound name."""
        if not filename:
            return ""
        return str(filename).replace(".mp3", "").replace("_", " ").strip()

    def _format_number(self, value: Any) -> str:
        """Format an integer-ish metric for display."""
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return "0"

    def _hour_text(self, hour: Any) -> str:
        """Format an hour metric for display."""
        if hour is None:
            return "No data"
        try:
            return f"{int(hour):02d}:00"
        except (TypeError, ValueError):
            return "No data"

    def _date_text(self, value: Any) -> str:
        """Format an ISO-ish timestamp as YYYY-MM-DD."""
        if not value:
            return "No data"
        return str(value)[:10]
