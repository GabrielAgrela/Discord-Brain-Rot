import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    FFMPEG_PATH = os.getenv('FFMPEG_PATH')
    CHROMEDRIVER_PATH = os.getenv('CHROMEDRIVER_PATH')

    # ElevenLabs
    EL_KEY = os.getenv('EL_key')
    EL_VOICE_ID_PT = os.getenv('EL_voice_id_pt')
    EL_VOICE_ID_EN = os.getenv('EL_voice_id_en')
    EL_VOICE_ID_COSTA = os.getenv('EL_voice_id_costa')

    # Paths
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    DB_PATH = os.path.join(BASE_DIR, "database.db")
    SOUNDS_DIR = os.path.join(BASE_DIR, "Sounds")
    LOG_FILE = '/var/log/personalgreeter.log' # Keep as legacy or move to local?
    MINECRAFT_LOG_PATH = '/opt/minecraft/logs/latest.log'

    # Bot Config
    COMMAND_PREFIX = "*"

    @staticmethod
    def validate():
        if not Config.DISCORD_BOT_TOKEN:
            print("Warning: DISCORD_BOT_TOKEN is not set.")
