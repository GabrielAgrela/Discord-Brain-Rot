import discord
from typing import Optional
import asyncio
from datetime import datetime
from bot.repositories import ActionRepository


class StatsService:
    """
    Service for calculating and displaying bot statistics.
    """
    
    def __init__(self, bot, message_service, sound_service):
        self.bot = bot
        self.message_service = message_service
        self.sound_service = sound_service
        self.action_repo = ActionRepository()

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

        return embed

    # Keep the old method for backwards compatibility
    async def display_top_users(self, requesting_user, number_users=5, number_sounds=5, days=7, by="plays", guild: Optional[discord.Guild] = None):
        """Calculate and display top users and sounds in the bot channel."""
        # Redirect to new method
        await self.display_stats(requesting_user, number_users, number_sounds, days, by, guild)
