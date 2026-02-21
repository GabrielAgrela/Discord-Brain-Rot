"""
Weekly wrapped digest service.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import discord

from bot.repositories import ActionRepository, StatsRepository


class WeeklyWrappedService:
    """
    Build and send weekly wrapped summaries per guild.

    This service is intentionally presentation-focused: it gathers weekly data
    from repositories, formats a digest, and delivers it to the configured bot
    text channel via ``MessageService``.
    """

    DELIVERY_ACTION = "weekly_wrapped_sent"
    MANUAL_ACTION = "weekly_wrapped_manual"

    def __init__(self, bot: discord.Bot, message_service):
        """
        Initialize the service.

        Args:
            bot: Discord bot instance.
            message_service: Message service used for delivery.
        """
        self.bot = bot
        self.message_service = message_service
        self.action_repo = ActionRepository()
        self.stats_repo = StatsRepository()

    @staticmethod
    def week_key_from_utc(now_utc: Optional[datetime] = None) -> str:
        """
        Return a stable week key (Monday date) in UTC.

        Args:
            now_utc: Current UTC datetime.

        Returns:
            String key in format ``week:YYYY-MM-DD``.
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        week_start = (now_utc - timedelta(days=now_utc.weekday())).date()
        return f"week:{week_start.isoformat()}"

    def was_sent_for_week(self, guild_id: int, week_key: str) -> bool:
        """
        Check whether the weekly wrapped digest was already delivered.

        Args:
            guild_id: Guild ID.
            week_key: Week key from ``week_key_from_utc``.

        Returns:
            True if delivery was already recorded.
        """
        return self.action_repo.has_action_for_target(
            self.DELIVERY_ACTION,
            week_key,
            guild_id=guild_id,
            include_global=False,
        )

    def _resolve_voice_channel_label(self, guild: discord.Guild, channel_id: str) -> str:
        """Resolve a voice channel ID into a friendly label."""
        try:
            channel_int = int(channel_id)
        except (TypeError, ValueError):
            return f"Channel {channel_id}"

        channel = guild.get_channel(channel_int) if guild else None
        if channel:
            return channel.name
        return f"Channel {channel_id}"

    @staticmethod
    def _format_top_items(title: str, items: list[tuple[str, int]], empty_text: str) -> str:
        """Format top-list sections for the digest."""
        lines = [title]
        if not items:
            lines.append(empty_text)
            return "\n".join(lines)

        for idx, (name, count) in enumerate(items, 1):
            clean = (name or "Unknown").replace(".mp3", "")
            lines.append(f"{idx}. **{clean}** — {count}")
        return "\n".join(lines)

    def _build_weird_stats(
        self,
        guild: discord.Guild,
        days: int,
        top_sounds: list[tuple[str, int]],
        top_voice_users: list[dict],
    ) -> list[str]:
        """Build fun/quirky weekly metrics from available aggregates."""
        stats = self.stats_repo.get_summary_stats(days=days, guild_id=guild.id)
        heatmap = self.stats_repo.get_activity_heatmap(days=days, guild_id=guild.id)
        weird_lines: list[str] = []

        if heatmap:
            day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            peak = max(heatmap, key=lambda item: item.get("count", 0))
            peak_day = day_names[peak["day"]] if 0 <= peak["day"] <= 6 else str(peak["day"])
            weird_lines.append(
                f"Peak chaos window: **{peak_day} {int(peak['hour']):02d}:00** ({peak['count']} plays)"
            )

            overnight_count = sum(
                item.get("count", 0)
                for item in heatmap
                if int(item.get("hour", 0)) in {0, 1, 2, 3, 4, 5}
            )
            if overnight_count > 0:
                weird_lines.append(f"Insomnia plays (00:00-05:59): **{overnight_count}**")

        total_plays = int(stats.get("total_plays", 0) or 0)
        if top_sounds and total_plays > 0:
            leader_count = int(top_sounds[0][1])
            dominance = (leader_count / total_plays) * 100.0
            weird_lines.append(f"Top-sound domination: **{dominance:.1f}%** of all plays")

        if top_voice_users:
            grinder = top_voice_users[0]
            weird_lines.append(
                f"Voice grinder: **{grinder['username']}** ({grinder['total_hours']:.2f}h)"
            )

        new_sounds = int(stats.get("sounds_this_week", 0) or 0)
        weird_lines.append(f"New sounds added this week: **{new_sounds}**")

        return weird_lines

    def _build_description(
        self,
        guild: discord.Guild,
        days: int,
        top_sounds: list[tuple[str, int]],
        top_users: list[tuple[str, int]],
        top_voice_users: list[dict],
        top_voice_channels: list[dict],
        now_utc: datetime,
    ) -> str:
        """Render the final digest description."""
        window_start = (now_utc - timedelta(days=days)).date().isoformat()
        window_end = now_utc.date().isoformat()

        voice_users_fmt = [
            (f"{item['username']} ({item['total_hours']:.2f}h)", int(item["session_count"]))
            for item in top_voice_users
        ]
        voice_channels_fmt = [
            (
                f"{self._resolve_voice_channel_label(guild, item['channel_id'])} ({item['total_hours']:.2f}h)",
                int(item["session_count"]),
            )
            for item in top_voice_channels
        ]

        weird_stats = self._build_weird_stats(
            guild=guild,
            days=days,
            top_sounds=top_sounds,
            top_voice_users=top_voice_users,
        )

        sections = [
            f"Window: **{window_start} → {window_end} (UTC)**",
            "",
            self._format_top_items("## 🔥 Top Sounds", top_sounds, "No sound plays this week."),
            "",
            self._format_top_items("## 👥 Top Users", top_users, "No active users this week."),
            "",
            self._format_top_items("## 🎤 Voice MVPs", voice_users_fmt, "No voice activity this week."),
            "",
            self._format_top_items(
                "## 🗣️ Busiest Voice Channels",
                voice_channels_fmt,
                "No active voice channels this week.",
            ),
            "",
            "## 🧪 Weird Stats",
            *[f"- {line}" for line in weird_stats],
        ]
        return "\n".join(sections)

    async def send_weekly_wrapped(
        self,
        guild: discord.Guild,
        days: int = 7,
        force: bool = False,
        record_delivery: bool = True,
        now_utc: Optional[datetime] = None,
        requested_by: Optional[str] = None,
    ) -> bool:
        """
        Send weekly wrapped for one guild.

        Args:
            guild: Target guild.
            days: Rolling window size in days.
            force: Ignore duplicate-delivery checks.
            record_delivery: Persist weekly-delivery marker.
            now_utc: Injected time for deterministic scheduling/tests.
            requested_by: Optional username for manual-trigger audit logs.

        Returns:
            True if a message was sent.
        """
        if not guild:
            return False

        now_utc = now_utc or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        days = max(1, min(int(days), 30))
        week_key = self.week_key_from_utc(now_utc)

        if record_delivery and not force and self.was_sent_for_week(guild.id, week_key):
            return False

        top_sounds, _total = self.action_repo.get_top_sounds(days=days, limit=5, guild_id=guild.id)
        top_users = self.action_repo.get_top_users(days=days, limit=5, guild_id=guild.id)
        top_voice_users = self.stats_repo.get_top_voice_users(days=days, limit=5, guild_id=guild.id)
        top_voice_channels = self.stats_repo.get_top_voice_channels(days=days, limit=3, guild_id=guild.id)

        description = self._build_description(
            guild=guild,
            days=days,
            top_sounds=top_sounds,
            top_users=top_users,
            top_voice_users=top_voice_users,
            top_voice_channels=top_voice_channels,
            now_utc=now_utc,
        )

        message = await self.message_service.send_message(
            title=f"📈 Weekly Wrapped — {guild.name}",
            description=description,
            guild=guild,
            color=discord.Color.gold(),
        )
        if not message:
            return False

        if record_delivery:
            self.action_repo.insert("admin", self.DELIVERY_ACTION, week_key, guild_id=guild.id)

        if force:
            actor = requested_by or "admin"
            self.action_repo.insert(actor, self.MANUAL_ACTION, f"{days}d", guild_id=guild.id)

        return True
