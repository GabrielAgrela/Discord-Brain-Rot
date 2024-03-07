from asyncio import Queue
import asyncio
import os
import discord
from Classes.Environment import Environment
from Classes.Bot import Bot
from Classes.SoundEventsLoader import SoundEventLoader
from Classes.BotBehaviour import BotBehavior, ControlsView
import threading
from pynput import keyboard
import time
from collections import defaultdict
from datetime import datetime, timedelta
import csv
from collections import Counter
import atexit
import interactions
from discord.commands import Option


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
    await behavior.clean_buttons()
    channel = await behavior.get_bot_channel()
    behavior.button_message = await channel.send(view=ControlsView(behavior))

@bot.slash_command(
    name="play",
    description="Write a name of something you want to hear"
)
async def play_requested(ctx: interactions.CommandContext, message: Option(str, "Sound", required=False, default='random')):
    await ctx.defer()
    await behavior.delete_last_message(ctx)
    author = ctx.user
    username_with_discriminator = f"{author.name}#{author.discriminator}"
    try:
        if(message == "random"):
            asyncio.run_coroutine_threadsafe(behavior.play_random_sound(), bot.loop)
        else:
            await behavior.play_request(message, username_with_discriminator)
    except:
        asyncio.run_coroutine_threadsafe(behavior.play_random_sound(), bot.loop)
        return
    
@bot.slash_command(name='tts', description='TTS with google translate. Press tab and enter to select message and write')
async def tts(ctx, language: Option(str, "pt, br, es, fr, de and ch", required=False, default=''), message: Option(str, "What you want to say", required=False, default='write something')):

    await ctx.defer()
    await behavior.delete_last_message(ctx)
    try:
        if language == "pt":
            await behavior.tts(behavior, message, "pt")
        elif language == "br":
            await behavior.tts(behavior, message, "pt", "com.br")
        elif language == "es":
            await behavior.tts(behavior, message, "es")
        elif language == "fr":
            await behavior.tts(behavior, message, "fr")
        elif language == "de":
            await behavior.tts(behavior, message, "de")
        elif language == "ch":
            await behavior.tts(behavior, message, "zh-CN")
        else:
            await behavior.tts(behavior, message)
    except Exception as e:
        print(f"An error occurred: {e}")
        await ctx.send(content="An error occurred while processing your request.")
        return

    
    # Send the final response
    await ctx.send(content="tts: "+message)



@bot.slash_command(
    name="change",
    description="change the name of a sound"
)
async def change(ctx, current: Option(str, "Current name of the sound", required=True, default=''), new: Option(str, "New name of the sound", required=True, default='write something')):
    await ctx.defer()
    await behavior.delete_last_message(ctx)
    await behavior.change_filename(current, new)


@bot.slash_command(
    name="top",
    description="Leaderboard of sounds or users"
)
async def change(ctx, option: Option(str, "users or sounds", required=False, default='sounds')):
    await ctx.defer()
    await behavior.delete_last_message(ctx)
    if option == "sounds":
        await behavior.player_history_db.write_top_played_sounds()
    elif option == "users":
        await behavior.player_history_db.write_top_users()

@bot.slash_command(
    name="list",
    description="returns database of sounds"
)
async def change(ctx):
    await ctx.defer()
    await behavior.delete_last_message(ctx)
    await behavior.list_sounds()    

@bot.command(
    name="re",
    description="Record a sound"
)
async def record(ctx):
    behavior.record_sound('output', 5)  # 'output' is the filename, 5 is the duration

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
bot.start()
