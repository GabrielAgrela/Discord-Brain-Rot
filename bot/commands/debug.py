import asyncio
import discord
from discord.ext import commands

class DebugCog(commands.Cog):
    """Cog for debug commands."""
    
    def __init__(self, bot: discord.Bot, behavior):
        self.bot = bot
        self.behavior = behavior

def setup(bot: discord.Bot, behavior=None):
    if behavior is None:
        raise ValueError("behavior is required for DebugCog")
    bot.add_cog(DebugCog(bot, behavior))
