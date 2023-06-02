import asyncio,discord,os,json
from discord.ext import commands
from Classes.SoundEventFactory import SoundEventFactory
from dotenv import load_dotenv
import asyncio
from Classes.SoundDownloader import SoundDownloader

# Intents
intents = discord.Intents(guilds=True, voice_states=True)

# Bot
bot = commands.Bot(command_prefix="!", intents=intents)

# Load Environment Variables
load_dotenv()
bot_token = os.getenv('DISCORD_BOT_TOKEN')
FFMPEG_PATH = os.getenv('FFMPEG_PATH')

# Get the absolute path of the script file
script_path = os.path.abspath(__file__)

# Get the directory of the script
script_dir = os.path.dirname(script_path)

# Construct the absolute sounds file path
sounds_path = os.path.join(script_dir, 'Data', 'Sounds.json')

with open(sounds_path, 'r') as f:
    sound_keys = json.load(f)
    # Example of Sounds.json
    """
    [
    "ALERT",
    "GOODBYE",
    "FART",
    "ALLAH",
    "XFART",
    "MEXI",
    "HELLO"
    ] 
    """

# Construct the absolute users file path
users_path = os.path.join(script_dir, 'Data', 'Users.json')

with open(users_path, 'r', encoding='utf-8') as f:
    user_data = json.load(f)
    # Example of Users.json
    """ 
    {
        "user1#1111": [{
                "event": "leave",
                "sound": "XFART"
            },
            {
                "event": "join",
                "sound": "MEXI"
            }
        ],
        "user2#2222": [{
            "event": "join",
            "sound": "HELLO"
        }]
    } 
    """

# Load Variables from Data
SOUNDS = {sound: os.getenv(f'SOUND_{sound}') for sound in sound_keys}# these are urls with .mp3 files
USERS = {user: [SoundEventFactory.create_sound_event(user, event['event'], SOUNDS[event['sound']]) for event in events] for user, events in user_data.items()}

last_channel = {}

def get_largest_voice_channel(guild):
    """Find the voice channel with the most members."""
    largest_channel = None
    largest_size = 0

    for channel in guild.voice_channels:
        if len(channel.members) > largest_size:
            largest_channel = channel
            largest_size = len(channel.members)

    return largest_channel


async def disconnect_all_bots(guild):
    if bot.voice_clients:
        for vc_bot in bot.voice_clients:
            if vc_bot.guild == guild:
                await vc_bot.disconnect()

async def play_audio(channel, audio_file):
    voice_client = await channel.connect()
    voice_client.play(discord.FFmpegPCMAudio(executable=FFMPEG_PATH, source=audio_file))

    while voice_client.is_playing():
        await asyncio.sleep(.1)

    await voice_client.disconnect()


sound_downloader = SoundDownloader()

async def download_sound_periodically():
    while True:
        sound_downloader.download_sound()
        await asyncio.sleep(1)  # Wait for 1 second after downloading
        for guild in bot.guilds:  # For each server the bot is a member of
            channel = get_largest_voice_channel(guild)  # Get the largest voice channel
            if channel is not None:  # If we found a voice channel
                await disconnect_all_bots(guild)
                await play_audio(channel, r"C:\Users\netco\Downloads\random.mp3")  # Play the downloaded sound
        await asyncio.sleep(3600)  # Wait for 1h


@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    bot.loop.create_task(download_sound_periodically())

@bot.event
async def on_voice_state_update(member, before, after):
    member_str = str(member)
    # Check if the member is in the user list and if the member is in a voice channel (before or after) 
    if member_str in USERS:
        
        if before.channel is None or (before.channel != after.channel and after.channel is not None):
            event = "join"
            channel = after.channel
        elif after.channel is None or (before.channel != after.channel and before.channel is not None):
            event = "leave"
            channel = before.channel
        else:
            return
        
        # Check if the member has a sound event for the event and play it  
        user_events = USERS[member_str]
        for user_event in user_events:
            if user_event.event == event:
                last_channel[member_str] = channel
                await asyncio.sleep(1)
                if last_channel[member_str] == channel:
                    for guild in bot.guilds:
                        await disconnect_all_bots(guild)
                        if channel:  # Make sure the channel exists (it might not if the member disconnected)
                            await play_audio(channel, user_event.sound)
                        break

# Bot Run
bot.run(bot_token)
