from asyncio import Queue
import asyncio
import os
import random
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
from discord import default_permissions

env = Environment()
intents = discord.Intents(guilds=True, voice_states=True, messages=True, message_content=True, members=True)
bot = Bot(command_prefix="*", intents=intents, token=env.bot_token, ffmpeg_path=env.ffmpeg_path)

loader = SoundEventLoader(os.path.abspath(__file__))
USERS, SOUNDS = loader.load_sound_events()

behavior = BotBehavior(bot, env.ffmpeg_path)
file_name = 'play_requests.csv'

@default_permissions(manage_messages=True)
@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    await behavior.delete_controls_message()
    await behavior.clean_buttons()
    await behavior.play_random_sound()
    
    bot.loop.create_task(behavior.play_sound_periodically())
    bot.loop.create_task(behavior.update_bot_status())

@bot.slash_command(name="play", description="Write a name of something you want to hear")
async def play_requested(ctx: interactions.CommandContext, message: Option(str, "Sound name ('random' for random)", required=True), request_number: Option(str, "Number of Similar Sounds", default=5)):
    await ctx.defer()
    await behavior.delete_last_message()
    request_number = int(request_number)
    if request_number > 25:
        request_number = 25
    author = ctx.user
    username_with_discriminator = f"{author.name}#{author.discriminator}"
    try:
        number_similar_sounds = int(request_number)
    except:
        number_similar_sounds = 5
    print(f"Playing {message} for {username_with_discriminator}")
    try:
        if(message == "random"):
            asyncio.run_coroutine_threadsafe(behavior.play_random_sound(username_with_discriminator), bot.loop)
        else:
            await behavior.play_request(message, username_with_discriminator,request_number=number_similar_sounds)
    except Exception as e:
        print(e)
        asyncio.run_coroutine_threadsafe(behavior.play_random_sound(username_with_discriminator), bot.loop)
        return
    
@bot.slash_command(name='tts', description='TTS with google translate. Press tab and enter to select message and write')
async def tts(ctx, message: Option(str, "What you want to say", required=True), language: Option(str, "en, pt, br, es, fr, de, ar, ru and ch", required=True)):
    await ctx.defer()
    await behavior.delete_last_message()
    flag_emojis = {"pt": ":flag_pt:", "br": ":flag_br:", "es": ":flag_es:", "fr": ":flag_fr:", "de": ":flag_de:", "ru": ":flag_ru:", "ar": ":flag_sa:", "ch": ":flag_cn:", "ir": ":flag_ie:", "en": ":flag_gb:"}
    flag = flag_emojis.get(language, ":flag_gb:")
    user = discord.utils.get(bot.get_all_members(), name=ctx.user.name)

    await behavior.send_message(title=f"TTS in {flag}", description=f"'{message}'", thumbnail=user.avatar.url if user and user.avatar else user.default_avatar.url)

    try:
        if language == "pt":
            await behavior.tts(message, "pt")
        elif language == "br":
            await behavior.tts(message, "pt", "com.br")
        elif language == "es":
            await behavior.tts(message, "es")
        elif language == "fr":
            await behavior.tts(message, "fr")
        elif language == "de":
            await behavior.tts(message, "de")
        elif language == "ru":
            await behavior.tts(message, "ru")
        elif language == "ar":
            await behavior.tts(message, "ar")
        elif language == "ch":
            await behavior.tts(message, "zh-CN")
        elif language == "ir":
            await behavior.tts(message, "en", "ie")
        else:
            await behavior.tts(message)
    except Exception as e:
        await behavior.send_message(title=e)
        return
    

@bot.slash_command(name="change", description="change the name of a sound")
async def change(ctx, current: Option(str, "Current name of the sound", required=True), new: Option(str, "New name of the sound", required=True)):
    await ctx.defer()
    await behavior.delete_last_message()
    await behavior.change_filename(current, new)

@bot.slash_command(name="top", description="Leaderboard of sounds or users")
async def change(ctx, option: Option(str, "users or sounds", required=True)):
    await ctx.defer()
    await behavior.delete_last_message()
    if option == "sounds":
        await behavior.player_history_db.write_top_played_sounds()
    else:
        await behavior.player_history_db.write_top_users()

@bot.slash_command(name="list", description="returns database of sounds")
async def change(ctx):
    await ctx.defer()
    await behavior.delete_last_message()
    await behavior.list_sounds()    

@bot.slash_command(name="subwaysurfers", description="returns database of sounds")
async def change(ctx):
    await ctx.defer()
    await behavior.delete_last_message()
    await behavior.subway_surfers()    

@bot.slash_command(name="lastsounds", description="returns last sounds downloaded")
async def change(ctx, number: Option(str, "number of sounds", default=10)):
    await ctx.defer()
    await behavior.delete_last_message()
    await behavior.list_sounds(int(number))    




connections = {}

async def once_done(sink: discord.sinks, channel: discord.TextChannel, *args):
    recorded_users = [
        f"<@{user_id}>"
        for user_id, audio in sink.audio_data.items()
    ]
    await sink.vc.disconnect()
    files = [discord.File(audio.file, f"{user_id}.{sink.encoding}") for user_id, audio in sink.audio_data.items()]
    # STT files
    await behavior.stt(files)

@bot.command(name="re")
async def record_sound(ctx):
    voice = ctx.author.voice
    if not voice:
        await ctx.send("You aren't in a voice channel!")
        return

    #get connected voice client
    try:
        vc = await voice.channel.connect()
    except:
        vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    connections.update({ctx.guild.id: vc})

    # Start recording
    vc.start_recording(
        discord.sinks.WaveSink(), 
        once_done, 
        ctx.channel
    )
    print("Started recording!")

    # Wait for 5 seconds
    await asyncio.sleep(5)

    # Stop recording after 5 seconds
    if ctx.guild.id in connections:
        vc = connections[ctx.guild.id]
        vc.stop_recording()
        del connections[ctx.guild.id]

@bot.command()
async def stop_recording(ctx):
    if ctx.guild.id in connections:
        vc = connections[ctx.guild.id]
        vc.stop_recording()
        del connections[ctx.guild.id]
        print("Stopped recording.")
    else:
        print("not recording")




@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    member_str = f"{member.name}#{member.discriminator}"
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
        asyncio.run_coroutine_threadsafe(behavior.play_random_sound(), bot.loop)
    if key == keyboard.Key.f7:
        asyncio.run_coroutine_threadsafe(behavior.play_audio("",  random.choice(["slap.mp3", "tiro.mp3", "pubg-pan-sound-effect.mp3"]),"admin"), bot.loop)

keyboard_listener = keyboard.Listener(on_press=on_press)
thread = threading.Thread(target=keyboard_listener.start)
thread.start()

bot.run_bot()
bot.start()
