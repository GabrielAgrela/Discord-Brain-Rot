import discord
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

    async def display_top_users(self, requesting_user, number_users=5, number_sounds=5, days=7, by="plays"):
        """Calculate and display top users and sounds in the bot channel."""
        self.action_repo.insert(requesting_user.name, "list_top_users", by)
        top_users = self.action_repo.get_top_users(days, number_users, by)
        
        bot_channel = self.message_service.get_bot_channel(self.bot.guilds[0] if self.bot.guilds else None)
        if not bot_channel:
            return

        messages = []
        for rank, (username, total_plays) in enumerate(top_users, 1):
            embed = discord.Embed(
                title=f"🔊 **#{rank} {username.upper()}**",
                description=f"🎵 **Total Sounds Played: {total_plays}**",
                color=discord.Color.green()
            )

            # Try to find user for avatar
            discord_user = discord.utils.get(self.bot.get_all_members(), name=username)
            if discord_user and discord_user.avatar:
                embed.set_thumbnail(url=discord_user.avatar.url)
            elif username == "syzoo":
                embed.set_thumbnail(url="https://media.npr.org/assets/img/2017/09/12/macaca_nigra_self-portrait-3e0070aa19a7fe36e802253048411a38f14a79f8-s800-c85.webp")
            elif discord_user:
                embed.set_thumbnail(url=discord_user.default_avatar.url)

            # Get top sounds for this specific user
            user_top_sounds, _ = self.action_repo.get_top_sounds(days, number_sounds, username)
            for sound in user_top_sounds:
                embed.add_field(name=f"🎵 **{sound[0]}**", value=f"Played **{sound[1]}** times", inline=False)

            message = await bot_channel.send(embed=embed)
            messages.append(message)

        # Overall summary
        sound_summary, total_plays = self.action_repo.get_top_sounds(days, 10, None)
        average_per_day = total_plays / days if days > 0 else total_plays
        
        summary_embed = discord.Embed(
            title=f"🎵 **TOP SOUNDS (LAST {days} DAYS)! TOTAL: {total_plays}** 🎵",
            description=f"Average of {average_per_day:.0f} plays per day!",
            color=discord.Color.yellow()
        )
        summary_embed.set_thumbnail(url="https://i.imgflip.com/1vdris.jpg")
        summary_embed.timestamp = datetime.utcnow()

        for i, (sound_name, play_count) in enumerate(sound_summary, 1):
            summary_embed.add_field(
                name=f"#{i}: {sound_name}",
                value=f"Played {play_count} times",
                inline=False
            )

        summary_message = await bot_channel.send(embed=summary_embed)
        messages.append(summary_message)

        await asyncio.sleep(60)
        for message in messages:
            try:
                await message.delete()
            except:
                pass
