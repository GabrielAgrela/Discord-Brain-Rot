from asyncio import Queue
import asyncio
import os
import discord
from Classes.Environment import Environment
from Classes.Bot import Bot
from Classes.SoundEventsLoader import SoundEventLoader
from Classes.BotBehaviour import BotBehavior
import threading
from pynput import keyboard
import time
from collections import defaultdict
from datetime import datetime, timedelta
import csv
from collections import Counter
import atexit


# Dictionary to store the counts for each user
user_scores = defaultdict(int)
# Dictionary to store the timestamps for each command invocation
user_timestamps = defaultdict(list)

intents = discord.Intents(guilds=True, voice_states=True, messages=True, message_content=True, members=True)


env = Environment()
bot = Bot(command_prefix="*", intents=intents, token=env.bot_token, ffmpeg_path=env.ffmpeg_path)


loader = SoundEventLoader(os.path.abspath(__file__))
USERS, SOUNDS = loader.load_sound_events()

behavior = BotBehavior(bot, env.ffmpeg_path)
file_name = 'play_requests.csv'

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    bot.loop.create_task(behavior.play_sound_periodically())
    bot.loop.create_task(behavior.update_bot_status())
    await behavior.delete_message_components()
    bot.loop.create_task(behavior.refresh_button_message())

@bot.command(name='play')
async def play_random(ctx):
    bot_channel = discord.utils.get(bot.guilds[0].text_channels, name='bot')
    if bot_channel:
        #delete last message
        await bot_channel.send(f"escreve '*p' burra do crl")

@bot.command(name='p')
async def play_requested(ctx):
    author = ctx.message.author
    username_with_discriminator = f"{author.name}#{author.discriminator}"
    try:
        if(ctx.message.content.split(" ")[1] == "random"):
            asyncio.run_coroutine_threadsafe(behavior.play_random_sound(), bot.loop)
        else:
            await behavior.play_request(ctx.message.content, username_with_discriminator)
    except:
        asyncio.run_coroutine_threadsafe(behavior.play_random_sound(), bot.loop)
        return
    
@bot.command(name='tts')
async def tts(ctx):
    parts = ctx.message.content.split(" ")[1:]
    
    # Join the words back together into a string
    rest_of_message = " ".join(parts)
    
    await behavior.tts(behavior,rest_of_message)

@bot.command(name='ttsPT')
async def tts(ctx):
    parts = ctx.message.content.split(" ")[1:]
    
    # Join the words back together into a string
    rest_of_message = " ".join(parts)
    
    await behavior.tts(behavior,rest_of_message, "pt")

@bot.command(name='ttsBR')
async def tts(ctx):
    parts = ctx.message.content.split(" ")[1:]
    
    # Join the words back together into a string
    rest_of_message = " ".join(parts)
    
    await behavior.tts(behavior,rest_of_message, "pt","com.br")

@bot.command(name='ttsES')
async def tts(ctx):
    parts = ctx.message.content.split(" ")[1:]
    
    # Join the words back together into a string
    rest_of_message = " ".join(parts)
    
    await behavior.tts(behavior,rest_of_message, "es")

@bot.command(name='change')
async def play_requested(ctx):
    await behavior.change_filename(ctx.message.content.split(" ")[1], ctx.message.content.split(" ")[2])

@bot.command(name='top')
async def top(ctx):
    if ctx.message.content.split(" ")[1] == "sounds":
        await behavior.player_history_db.write_top_played_sounds()
    elif ctx.message.content.split(" ")[1] == "users":
        await behavior.player_history_db.write_top_users()

@bot.command(name='list')
async def list_sounds(ctx):
    await behavior.list_sounds()    

@bot.event
async def on_voice_state_update(member, before, after):
    member_str = str(member)
    if member_str not in USERS and before.channel is None and after.channel is not None and member != bot.user:
        await behavior.play_audio(after.channel, "gay-echo.mp3","admin", is_entrance=True)
    else:
        if member_str in USERS and member != bot.user:
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
                            #await behavior.disconnect_all_bots(guild)
                            if channel:
                                print(f"Playing {user_event.sound} for {member_str}")
                                await behavior.play_audio(channel, user_event.sound,member_str, is_entrance=True)
                            break

def on_press(key):
    if key == keyboard.Key.f6:
        # This is a simple function that runs the function in the event loop
        # when the F6 key is pressed.
        asyncio.run_coroutine_threadsafe(behavior.play_random_sound(), bot.loop)
    if key == keyboard.Key.f7:
        # This is a simple function that runs the function in the event loop
        # when the F6 key is pressed.
        asyncio.run_coroutine_threadsafe(behavior.play_audio("", "slap.mp3","admin"), bot.loop)


# Start the listener in a separate thread so that it doesn't block
# the main thread where the Discord bot runs.
keyboard_listener = keyboard.Listener(on_press=on_press)
thread = threading.Thread(target=keyboard_listener.start)
thread.start()

bot.run_bot()
