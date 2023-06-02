import asyncio
import os
import discord
from Classes.Environment import Environment
from Classes.Bot import Bot
from Classes.SoundEventsLoader import SoundEventLoader
from Classes.BotBehaviour import BotBehavior
intents = discord.Intents(guilds=True, voice_states=True)

env = Environment()
bot = Bot(command_prefix="!", intents=intents, token=env.bot_token, ffmpeg_path=env.ffmpeg_path)

loader = SoundEventLoader(os.path.abspath(__file__))
USERS, SOUNDS = loader.load_sound_events()

behavior = BotBehavior(bot, env.ffmpeg_path)

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    bot.loop.create_task(behavior.download_sound_periodically())
    bot.loop.create_task(behavior.update_bot_status())

@bot.event
async def on_voice_state_update(member, before, after):
    member_str = str(member)
    if member_str in USERS:
        if before.channel is None or (before.channel != after.channel and after.channel is not None):
            event = "join"
            channel = after.channel
        elif after.channel is None or (before.channel != after.channel and before.channel is not None):
            event = "leave"
            channel = before.channel
        else:
            return
        user_events = USERS[member_str]
        for user_event in user_events:
            if user_event.event == event:
                behavior.last_channel[member_str] = channel
                await asyncio.sleep(1)
                if behavior.last_channel[member_str] == channel:
                    for guild in bot.guilds:
                        await behavior.disconnect_all_bots(guild)
                        if channel:
                            await behavior.play_audio(channel, user_event.sound)
                        break

bot.run_bot()
