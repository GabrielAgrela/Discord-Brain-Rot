import discord
from typing import Optional
import asyncio
from datetime import datetime
from bot.repositories import ActionRepository, StatsRepository


class StatsService:
    """
    Service for calculating and displaying bot statistics.
    """
    
    def __init__(self, bot, message_service, sound_service):
        self.bot = bot
        self.message_service = message_service
        self.sound_service = sound_service
        self.action_repo = ActionRepository()
        self.stats_repo = StatsRepository()

    async def display_stats(self, requesting_user, number_users=20, number_sounds=5, days=700, by="plays", guild: Optional[discord.Guild] = None):
        """
        Display stats in two phases:
        1. Server-wide summary embed
        2. Paginated user stats with navigation buttons
        """
        self.action_repo.insert(requesting_user.name, "list_top_users", by)
        
        bot_channel = self.message_service.get_bot_channel(guild)
        if not bot_channel:
            return

        messages = []
        
        # Phase 1: Send server-wide summary
        server_embed = self._create_server_stats_embed(days)
        server_message = await bot_channel.send(embed=server_embed)
        messages.append(server_message)
        
        # Phase 2: Send paginated user stats
        top_users = self.action_repo.get_top_users(days, number_users, by)
        
        if top_users:
            from bot.ui.views.stats import PaginatedStatsView
            view = PaginatedStatsView(self.bot, top_users, number_sounds, days)
            user_embed = view.create_user_embed()
            user_message = await bot_channel.send(embed=user_embed, view=view)
            messages.append(user_message)
        
        async def cleanup():
            # Auto-delete after 60 seconds
            await asyncio.sleep(60)
            for message in messages:
                try:
                    await message.delete()
                except:
                    pass
                    
        asyncio.create_task(cleanup())

    def _create_server_stats_embed(self, days: int) -> discord.Embed:
        """Create an embed with server-wide statistics."""
        sound_summary, total_plays = self.action_repo.get_top_sounds(days, 10, None)
        average_per_day = total_plays / days if days > 0 else total_plays
        
        embed = discord.Embed(
            title=f"🎵 **SERVER STATS (LAST {days} DAYS)** 🎵",
            description=f"**Total Plays:** {total_plays}\n**Average:** {average_per_day:.0f} plays per day",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url="https://i.imgflip.com/1vdris.jpg")
        embed.timestamp = datetime.utcnow()

        # Add top 10 sounds
        if sound_summary:
            sounds_text = ""
            for i, (sound_name, play_count) in enumerate(sound_summary, 1):
                sounds_text += f"**#{i}** {sound_name} — {play_count} plays\n"
            embed.add_field(name="🔥 Top 10 Sounds", value=sounds_text, inline=False)

        top_voice_users = self.stats_repo.get_top_voice_users(days=days, limit=5)
        if top_voice_users:
            users_text = ""
            for i, user_data in enumerate(top_voice_users, 1):
                users_text += (
                    f"**#{i}** {user_data['username']} — "
                    f"{user_data['total_hours']:.2f}h ({user_data['session_count']} sessions)\n"
                )
            embed.add_field(name="🎤 Top Voice Users", value=users_text, inline=False)

        top_voice_channels = self.stats_repo.get_top_voice_channels(days=days, limit=3)
        if top_voice_channels:
            channels_text = ""
            for i, channel_data in enumerate(top_voice_channels, 1):
                channel_label = self._resolve_voice_channel_label(channel_data["channel_id"])
                channels_text += (
                    f"**#{i}** {channel_label} — "
                    f"{channel_data['total_hours']:.2f}h ({channel_data['session_count']} sessions)\n"
                )
            embed.add_field(name="🗣️ Top Voice Channels", value=channels_text, inline=False)

        return embed

    def _resolve_voice_channel_label(self, channel_id: str) -> str:
        """Resolve a voice channel ID to a readable label."""
        try:
            channel_int = int(channel_id)
        except (TypeError, ValueError):
            return f"Channel {channel_id}"

        for guild in self.bot.guilds:
            channel = guild.get_channel(channel_int)
            if channel and isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                return f"{guild.name} / {channel.name}"

        return f"Channel {channel_id}"

    # Keep the old method for backwards compatibility
    async def display_top_users(self, requesting_user, number_users=5, number_sounds=5, days=7, by="plays", guild: Optional[discord.Guild] = None):
        """Calculate and display top users and sounds in the bot channel."""
        # Redirect to new method
        await self.display_stats(requesting_user, number_users, number_sounds, days, by, guild)
