import discord
from discord.ext import commands
from discord.commands import Option
from src.bot.services.bot_behavior import BotBehavior

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.behavior = BotBehavior(bot)

    @discord.slash_command(name="reboot", description="Reboot the host")
    async def reboot(self, ctx):
        if not self.behavior.is_admin_or_mod(ctx.author):
            await ctx.respond("Permission denied.", ephemeral=True)
            return

        await ctx.respond("Rebooting...", ephemeral=True)
        import os
        os.system("sudo reboot")

def setup(bot):
    bot.add_cog(AdminCog(bot))
