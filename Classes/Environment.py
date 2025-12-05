import os
from dotenv import load_dotenv

class Environment:
    def __init__(self):
        load_dotenv()
        self.bot_token = os.getenv('DISCORD_BOT_TOKEN')
        self.ffmpeg_path = os.getenv('FFMPEG_PATH')
