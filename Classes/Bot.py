import discord
from discord.ext import commands

class Bot(commands.Bot):
    def __init__(self, command_prefix, intents, token, ffmpeg_path):
        super().__init__(command_prefix=command_prefix, intents=intents)
        self.token = token
        self.ffmpeg_path = ffmpeg_path

    def run_bot(self):
        self.run(self.token)


