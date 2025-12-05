import discord
from discord.ext import commands
from src.bot.services.lol import LoLService

class LoLCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.service = LoLService(bot)

    @discord.slash_command(name="userlolstats", description="Get LoL stats")
    async def user_stats(self, ctx, username: str):
        await ctx.respond("Not implemented yet.", ephemeral=True)

def setup(bot):
    bot.add_cog(LoLCog(bot))
