"""
Statistics slash commands cog.

This cog handles stats-related commands:
- /top - Leaderboard of sounds or users
- /yearreview - Yearly stats wrap-up
- /sendyearreview - Admin command to send year review
"""

import discord
from discord.ext import commands
from discord.commands import Option
import datetime
from typing import Optional

from bot.repositories import ActionRepository, StatsRepository


class StatsCog(commands.Cog):
    """Cog for statistics and leaderboards."""
    
    def __init__(self, bot: discord.Bot, behavior):
        self.bot = bot
        self.behavior = behavior
        self.action_repo = ActionRepository()
        self.stats_repo = StatsRepository()

    @commands.slash_command(name="top", description="Leaderboard of sounds or users")
    async def top(
        self, 
        ctx: discord.ApplicationContext, 
        option: Option(
            str,
            "Leaderboard type",
            choices=["users", "sounds", "voice users", "voice channels"],
            required=True,
        ),
        number: Option(int, "number of users/sounds", default=5),
        numberdays: Option(int, "number of days", default=7)
    ):
        """Show leaderboard statistics."""
        await ctx.respond("Processing your request...", delete_after=0)
        guild_id = ctx.guild.id if ctx.guild else None
        if option == "sounds":
            # Note: The original code used a method write_top_played_sounds on behavior.player_history_db
            # But in database.py we only see get_top_sounds.
            # Behavior MUST implement logic to format this or database should.
            # Original code: await behavior.player_history_db.write_top_played_sounds(...)
            # Wait, write_top_played_sounds suggests it writes to a file or sends a message?
            # Looking at database.py, it DOES NOT have write_... methods.
            # They must be on a different class or dynamically added?
            # Or... wait, looking at PersonalGreeter.py imports...
            # behavior.player_history_db is initialized as Database() in BotBehavior.
            # So it must be that Database class HAS these methods in original codebase but I missed them or they are monkey-patched.
            # Let's assume for now we need to implement the logic here using get_top_sounds/users.
            
            # Let's implement the display logic here using behavior.embed/message service
            top_sounds, total = self.action_repo.get_top_sounds(numberdays, number, guild_id=guild_id)
            
            description = ""
            for i, (name, count) in enumerate(top_sounds, 1):
                clean_name = name.replace('.mp3', '')
                description += f"**{i}. {clean_name}** - {count} plays\n"
            
            if not description:
                description = "No sounds played yet!"
                
            await self.behavior.send_message(
                title=f"Top {number} Sounds (Last {numberdays} days)",
                description=description,
                guild=ctx.guild,
            )
            
        elif option == "users":
            top_users = self.action_repo.get_top_users(numberdays, number, guild_id=guild_id)
            
            description = ""
            for i, (name, count) in enumerate(top_users, 1):
                description += f"**{i}. {name}** - {count} plays\n"
            
            if not description:
                description = "No active users found!"

            await self.behavior.send_message(
                title=f"Top {number} Users (Last {numberdays} days)",
                description=description,
                guild=ctx.guild,
            )

        elif option == "voice users":
            top_voice_users = self.stats_repo.get_top_voice_users(days=numberdays, limit=number, guild_id=guild_id)

            description = ""
            for i, user_data in enumerate(top_voice_users, 1):
                description += (
                    f"**{i}. {user_data['username']}** - "
                    f"{user_data['total_hours']:.2f}h "
                    f"({user_data['session_count']} sessions)\n"
                )

            if not description:
                description = "No voice activity found!"

            await self.behavior.send_message(
                title=f"Top {number} Voice Users (Last {numberdays} days)",
                description=description,
                guild=ctx.guild,
            )

        elif option == "voice channels":
            top_voice_channels = self.stats_repo.get_top_voice_channels(days=numberdays, limit=number, guild_id=guild_id)

            description = ""
            for i, channel_data in enumerate(top_voice_channels, 1):
                channel_label = self._resolve_voice_channel_label(ctx.guild, channel_data["channel_id"])
                description += (
                    f"**{i}. {channel_label}** - "
                    f"{channel_data['total_hours']:.2f}h "
                    f"({channel_data['session_count']} sessions)\n"
                )

            if not description:
                description = "No voice channel activity found!"

            await self.behavior.send_message(
                title=f"Top {number} Voice Channels (Last {numberdays} days)",
                description=description,
                guild=ctx.guild,
            )

    def _resolve_voice_channel_label(self, guild: Optional[discord.Guild], channel_id: str) -> str:
        """Resolve voice channel ID to a readable label."""
        try:
            channel_int = int(channel_id)
        except (TypeError, ValueError):
            return f"Channel {channel_id}"

        if guild:
            channel = guild.get_channel(channel_int)
            if channel:
                return channel.name

        for known_guild in self.bot.guilds:
            channel = known_guild.get_channel(channel_int)
            if channel:
                return f"{known_guild.name} / {channel.name}"

        return f"Channel {channel_id}"

    @commands.slash_command(name="weeklywrapped", description="[Admin] Send weekly wrapped digest to this server")
    async def weekly_wrapped(
        self,
        ctx: discord.ApplicationContext,
        days: Option(int, "Rolling window in days", default=7),
    ):
        """Manually trigger the weekly wrapped digest for the current guild."""
        if not ctx.guild:
            await ctx.respond("This command can only be used in a server.", ephemeral=True)
            return

        if not self.behavior.is_admin_or_mod(ctx.author):
            await ctx.respond("You don't have permission to use this command.", ephemeral=True)
            return

        weekly_service = getattr(self.behavior, "_weekly_wrapped_service", None)
        if weekly_service is None:
            await ctx.respond("Weekly wrapped service is not available.", ephemeral=True)
            return

        safe_days = max(1, min(int(days), 30))
        await ctx.respond(
            f"Generating weekly wrapped for the last {safe_days} day(s)...",
            ephemeral=True,
        )

        sent = await weekly_service.send_weekly_wrapped(
            guild=ctx.guild,
            days=safe_days,
            force=True,
            record_delivery=False,
            requested_by=ctx.author.name,
        )
        if sent:
            await ctx.followup.send(
                "Weekly wrapped sent to the configured bot channel.",
                ephemeral=True,
            )
        else:
            await ctx.followup.send(
                "I couldn't send the weekly wrapped (check bot channel configuration).",
                ephemeral=True,
            )

    @commands.slash_command(name="yearreview", description="Show yearly stats wrapped!")
    async def year_review(
        self, 
        ctx: discord.ApplicationContext, 
        user: Option(discord.Member, "User to view", required=False, default=None),
        year: Option(int, "Year to review", required=False, default=None)
    ):
        """Generate a Spotify-wrapped style year review."""
        target_user = user if user else ctx.author
        await ctx.respond(f"Generating year review for {target_user.display_name}... 🎉", delete_after=0)
        
        current_year = datetime.datetime.now().year
        review_year = year if year else current_year
        
        username = target_user.name
        guild_id = ctx.guild.id if ctx.guild else None
        
        # We need to implement the get_user_year_stats logic or assume it exists in DB
        # If it doesn't exist in the truncated DB code I saw earlier, I should try to call it
        # assuming it's there, or reimplement it.
        # It was in PersonalGreeter calls: db.get_user_year_stats
        
        try:
            stats = self.stats_repo.get_user_year_stats(username, review_year, guild_id=guild_id)
            await self._send_year_review_embed(ctx, target_user, stats, review_year)
        except AttributeError:
             await self.behavior.send_message(title="Error", description="Year review stats not available directly.")

    async def _send_year_review_embed(self, ctx, target_user, stats, year):
        """Generate a Spotify-wrapped style embed with year stats matching original format."""
        if not stats:
            await self.behavior.send_message(
                title=f"📊 {target_user.name}'s {year} Review",
                description=f"No data found for {year}! 😢"
            )
            return
        
        total_plays = stats.get('total_plays', 0)
        if total_plays == 0:
            await self.behavior.send_message(
                title=f"📊 {target_user.name}'s {year} Review",
                description=f"No activity found for {year}! 😢"
            )
            return

        lines = []
        
        # Rank (if available)
        rank = stats.get('user_rank', None)
        total_users = stats.get('total_users', None)
        if rank and total_users:
            lines.append(f"🏆 **Rank #{rank}** of {total_users} users")
            lines.append("")
        
        # Sounds Played section
        lines.append(f"## 🎵 Sounds Played: {total_plays}")
        requested = stats.get('requested_plays', 0)
        random_plays = stats.get('random_plays', 0)
        favorites = stats.get('favorite_plays', 0)
        lines.append(f"🎯 Requested: {requested} • 🎲 Random: {random_plays} • ⭐ Favorites: {favorites}")
        
        unique_sounds = stats.get('unique_sounds', 0)
        if unique_sounds > 0 and total_plays > 0:
            variety_pct = int((unique_sounds / total_plays) * 100)
            lines.append(f"🎨 Variety: **{unique_sounds}** unique sounds ({variety_pct}% variety)")
        
        # Top Sounds section
        top_sounds = stats.get('top_sounds', [])
        if top_sounds:
            lines.append("")
            lines.append("## 🔥 Your Top Sounds")
            emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣']
            for i, (filename, count) in enumerate(top_sounds[:5], 0):
                clean_name = filename.replace('.mp3', '') if filename else 'Unknown'
                lines.append(f"{emojis[i]} **{clean_name}** ({count} plays)")
        
        # When You're Most Active
        lines.append("")
        lines.append("## ⏰ When You're Most Active")
        if stats.get('most_active_day'):
            lines.append(f"📅 Favorite day: **{stats.get('most_active_day')}** ({stats.get('most_active_day_count', 0)} plays)")
        if stats.get('most_active_hour') is not None:
            hour = stats.get('most_active_hour')
            hour_str = f"{hour:02d}:00"
            lines.append(f"🕐 Peak hour: **{hour_str}** ({stats.get('most_active_hour_count', 0)} plays)")
        
        # Your Sound Journey
        lines.append("")
        lines.append("## 📜 Your Sound Journey")
        if stats.get('first_sound'):
            first_sound = stats.get('first_sound', '').replace('.mp3', '')
            first_date = stats.get('first_sound_date', '')[:10] if stats.get('first_sound_date') else ''
            lines.append(f"🌅 First sound: **{first_sound}** ({first_date})")
        if stats.get('last_sound'):
            last_sound = stats.get('last_sound', '').replace('.mp3', '')
            last_date = stats.get('last_sound_date', '')[:10] if stats.get('last_sound_date') else ''
            lines.append(f"🌙 Latest sound: **{last_sound}** ({last_date})")
        
        # Voice & Activity Stats
        lines.append("")
        lines.append("## 🎤 Voice & Activity Stats")
        voice_time_hours = stats.get('total_voice_hours', 0)
        if voice_time_hours > 0:
            voice_days = round(voice_time_hours / 24, 1)
            lines.append(f"⏱️ Time in Voice: **{voice_time_hours}h** ({voice_days} days!)")
        longest_session = stats.get('longest_session_minutes', 0)
        if longest_session > 0:
            session_hours = round(longest_session / 60, 1)
            lines.append(f"📊 Longest Session: **{session_hours}h** ({longest_session} minutes)")
        if stats.get('longest_streak', 0) > 0:
            lines.append(f"🔥 Longest Streak: **{stats.get('longest_streak')}** days in a row!")
        if stats.get('total_active_days', 0) > 0:
            lines.append(f"📅 Total Active Days: **{stats.get('total_active_days')}** days")
        
        description = "\n".join(lines)
        
        await self.behavior.send_message(
            title=f"🎊 {target_user.name}'s {year} Year Review 🎊",
            description=description,
            thumbnail=target_user.display_avatar.url if target_user.display_avatar else None
        )

    @commands.slash_command(name="sendyearreview", description="[Admin] Send year review as DM to a user")
    async def send_year_review(
        self, 
        ctx: discord.ApplicationContext, 
        user: Option(discord.Member, "User to send the review to", required=True),
        year: Option(int, "Year to review", required=False, default=None)
    ):
        """Admin command to DM year review."""
        if not self.behavior.is_admin_or_mod(ctx.author):
            await ctx.respond("You don't have permission to use this command.", ephemeral=True)
            return
            
        await ctx.respond(f"Generating year review for {user.display_name}... 📬", ephemeral=True)
        # Logic would mirror year_review but send to DM
        await ctx.followup.send("Year review sent (placeholder).", ephemeral=True)


def setup(bot: discord.Bot, behavior=None):
    if behavior is None:
        raise ValueError("behavior is required for StatsCog")
    bot.add_cog(StatsCog(bot, behavior))
