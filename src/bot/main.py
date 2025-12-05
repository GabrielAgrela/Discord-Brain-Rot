import discord
from discord.ext import commands
from src.common.config import Config

# Initialize bot
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=Config.COMMAND_PREFIX, intents=intents)

# Load cogs
cogs = [
    'src.bot.cogs.audio',
    'src.bot.cogs.admin',
    'src.bot.cogs.general',
    # 'src.bot.cogs.tts', # Add when implemented
    # 'src.bot.cogs.minecraft', # Add when implemented
]

for cog in cogs:
    try:
        bot.load_extension(cog)
        print(f"Loaded {cog}")
    except Exception as e:
        print(f"Failed to load {cog}: {e}")

if __name__ == "__main__":
    if Config.DISCORD_BOT_TOKEN:
        bot.run(Config.DISCORD_BOT_TOKEN)
    else:
        print("Error: DISCORD_BOT_TOKEN not found.")
