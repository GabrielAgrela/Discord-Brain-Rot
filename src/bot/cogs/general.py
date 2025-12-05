import discord
import os
from discord.ext import commands
from src.common.config import Config
from src.bot.services.bot_behavior import BotBehavior

class GeneralCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.behavior = BotBehavior(bot)

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"Logged in as {self.bot.user}")
        # Auto-join logic could go here

def setup(bot):
    bot.add_cog(GeneralCog(bot))
