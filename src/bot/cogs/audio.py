import os
import discord
from discord.ext import commands
from discord.commands import Option
from src.bot.services.bot_behavior import BotBehavior
from src.common.database import Database

# Define standalone function for autocomplete to avoid 'self' binding issues in decorators
async def sound_autocomplete(ctx):
    db = Database()
    current = ctx.value.lower() if ctx.value else ""
    if len(current) < 2: return []
    sounds = db.get_sounds_by_similarity(current, 15)
    return [s.replace('.mp3', '') for s in sounds]

class AudioCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.behavior = BotBehavior(bot)
        self.db = Database()

    @discord.slash_command(name="toca", description="Play a sound")
    async def play(self, ctx,
                   message: Option(str, "Sound name", autocomplete=sound_autocomplete, required=True),
                   speed: Option(float, "Speed (0.5-3.0)", default=1.0, required=False),
                   volume: Option(float, "Volume (0.1-5.0)", default=1.0, required=False),
                   reverse: Option(bool, "Reverse", default=False, required=False)):

        await ctx.respond("Processing...", delete_after=0)

        effects = {"speed": max(0.5, min(speed, 3.0)), "volume": max(0.1, min(volume, 5.0)), "reverse": reverse}

        if message == "random":
             await self.behavior.play_random_sound(ctx.author.name, effects)
        else:
             await self.behavior.play_request(message, ctx.author, effects)

    @discord.slash_command(name="list", description="List recent sounds")
    async def list_sounds(self, ctx):
        await ctx.respond("Processing...", delete_after=0)
        sounds = self.db.get_sounds(num_sounds=25)
        desc = "\n".join([f"{s['Filename']}" for s in sounds])
        await self.behavior.send_message(title="Recent Sounds", description=desc)

def setup(bot):
    bot.add_cog(AudioCog(bot))
