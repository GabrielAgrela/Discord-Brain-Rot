"""
On This Day slash command cog.

Shows sounds that were popular on this day in the past.
"""

import discord
from discord.ext import commands
from discord.commands import Option

from bot.repositories import ActionRepository


class OnThisDayCog(commands.Cog):
    """Cog for the On This Day feature."""
    
    def __init__(self, bot: discord.Bot, behavior):
        self.bot = bot
        self.behavior = behavior
        self.action_repo = ActionRepository()
    
    @discord.slash_command(name="onthisday", description="See sounds popular on this day in the past")
    async def on_this_day(
        self,
        ctx: discord.ApplicationContext,
        period: Option(
            str,
            "Time period to look back",
            choices=["1 year ago", "1 month ago"],
            required=True
        )
    ):
        """Show sounds that were popular on this day in the past."""
        await ctx.defer()
        
        # Convert period to months
        months_ago = 12 if period == "1 year ago" else 1
        
        # Get sounds from that time period
        sounds = self.action_repo.get_sounds_on_this_day(months_ago=months_ago, limit=10)
        
        # Create the view
        from bot.ui.views.onthisday import OnThisDayView
        
        view = OnThisDayView(
            sounds=sounds,
            months_ago=months_ago,
            audio_service=self.behavior.audio_service if self.behavior else None,
            sound_service=self.behavior.sound_service if self.behavior else None
        )
        
        embed = view.create_embed()
        await ctx.respond(embed=embed, view=view)


def setup(bot: discord.Bot, behavior=None):
    """Add the cog to the bot."""
    bot.add_cog(OnThisDayCog(bot, behavior))
