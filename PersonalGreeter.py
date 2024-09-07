import asyncio
import os
import discord
from Classes.Environment import Environment
from Classes.Bot import Bot
from Classes.BotBehaviour import BotBehavior
import interactions
from discord.commands import Option
from discord import default_permissions
from Classes.UsersUtils import UsersUtils
from Classes.SoundDownloader import SoundDownloader
from Classes.Database import Database

env = Environment()
intents = discord.Intents(guilds=True, voice_states=True, messages=True, message_content=True, members=True)
bot = Bot(command_prefix="*", intents=intents, token=env.bot_token, ffmpeg_path=env.ffmpeg_path)

# Usage
userUtils = UsersUtils(os.path.abspath(os.path.join(os.path.dirname(__file__), "Data", "Users.json")))

behavior = BotBehavior(bot, env.ffmpeg_path)
db = Database(behavior=behavior)
file_name = 'play_requests.csv'

@default_permissions(manage_messages=True)
@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    await behavior.delete_controls_message()
    await behavior.clean_buttons()
    await behavior.send_controls(force=True)
    
    
    bot.loop.create_task(behavior.play_sound_periodically())
    bot.loop.create_task(behavior.update_bot_status())
    bot.loop.create_task(SoundDownloader(behavior, behavior.db, os.getenv("CHROMEDRIVER_PATH")).move_sounds())

@bot.slash_command(name="play", description="Write a name of something you want to hear")
async def play_requested(ctx: interactions.ComponentContext, message: Option(str, "Sound name ('random' for random)", required=True), request_number: Option(str, "Number of Similar Sounds", default=5)):
    await ctx.respond("Processing your request...", delete_after=0)
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
            await behavior.play_request(message, author.name,request_number=number_similar_sounds)
    except Exception as e:
        print(e)
        asyncio.run_coroutine_threadsafe(behavior.play_random_sound(username_with_discriminator), bot.loop)
        return
    
@bot.slash_command(name='tts', description='TTS with google translate. Press tab and enter to select message and write')
async def tts(ctx, message: Option(str, "What you want to say", required=True), language: Option(str, "en, pt, br, es, fr, de, ar, ru and ch", required=True)):
    await ctx.respond("Processing your request...", delete_after=0)
    flag_emojis = {"pt": ":flag_pt:", "br": ":flag_br:", "es": ":flag_es:", "fr": ":flag_fr:", "de": ":flag_de:", "ru": ":flag_ru:", "ar": ":flag_sa:", "ch": ":flag_cn:", "ir": ":flag_ie:", "en": ":flag_gb:"}
    flag = flag_emojis.get(language, ":flag_gb:")
    user = discord.utils.get(bot.get_all_members(), name=ctx.user.name)

    behavior.color = discord.Color.dark_blue()
    if language in ["pt", "en"]:
        url = "https://play-lh.googleusercontent.com/cyy3sqDw73x3LRwLbqMmWVHtCFp36RHaMO7Hh_YGqD6NRiLa8B5X8x-OLjAnnXbhYaw=w240-h480-rw" if language == "pt" else "https://www.famousbirthdays.com/headshots/mike-tyson-7.jpg"
    else:
        url = user.avatar.url if user and user.avatar else user.default_avatar.url

    await behavior.send_message(
        title=f"TTS in {flag}",
        description=f"'{message}'",
        thumbnail=url
    )
    try:
        if language == "pt":
            await behavior.tts_EL(user, message, "pt")
        elif language == "br":
            await behavior.tts(user, message, "pt", "com.br")
        elif language == "es":
            await behavior.tts(user, message, "es")
        elif language == "fr":
            await behavior.tts(user, message, "fr")
        elif language == "de":
            await behavior.tts(user, message, "de")
        elif language == "ru":
            await behavior.tts(user, message, "ru")
        elif language == "ar":
            await behavior.tts(user, message, "ar")
        elif language == "ch":
            await behavior.tts(user, message, "zh-CN")
        elif language == "ir":
            await behavior.tts(user, message, "en", "ie")
        else:
            await behavior.tts_EL(user, message)
    except Exception as e:
        await behavior.send_message(title=e)
        return
    
@bot.slash_command(name='sts', description='Speech-To-Speech. Press tab and enter to select message and write')
async def tts(ctx, sound: Option(str, "Base sound you want to convert", required=True), char: Option(str, "tyson, ventura", required=True)):
    await ctx.respond("Processing your request...", delete_after=0)

    user = discord.utils.get(bot.get_all_members(), name=ctx.user.name)

    behavior.color = discord.Color.dark_blue()
    if char in ["tyson", "ventura"]:
        url = "https://play-lh.googleusercontent.com/cyy3sqDw73x3LRwLbqMmWVHtCFp36RHaMO7Hh_YGqD6NRiLa8B5X8x-OLjAnnXbhYaw=w240-h480-rw" if char == "ventura" else "https://www.famousbirthdays.com/headshots/mike-tyson-7.jpg"
    else:
        char = "tyson"
        url = "https://play-lh.googleusercontent.com/cyy3sqDw73x3LRwLbqMmWVHtCFp36RHaMO7Hh_YGqD6NRiLa8B5X8x-OLjAnnXbhYaw=w240-h480-rw"

    await behavior.send_message(
        title=f"{sound} to {char}",
        description=f"'{char}'",
        thumbnail=url
    )
    try:
        await behavior.sts_EL(user, sound, char)
    except Exception as e:
        await behavior.send_message(title=e)
        return
    
@bot.slash_command(name='isolate', description='Isolate voice from a sound.')
async def isolate(ctx, sound: Option(str, "Base sound you want to isolate", required=True)):
    await ctx.respond("Processing your request...", delete_after=0)

    user = discord.utils.get(bot.get_all_members(), name=ctx.user.name)

    behavior.color = discord.Color.dark_blue()

    try:
        await behavior.isolate_voice(user, sound)
    except Exception as e:
        await behavior.send_message(title=e)
        return

@bot.slash_command(name="change", description="change the name of a sound")
async def change(ctx, current: Option(str, "Current name of the sound", required=True), new: Option(str, "New name of the sound", required=True)):
    await ctx.respond("Processing your request...", delete_after=0)
    await behavior.change_filename(current, new, ctx.user)

@bot.slash_command(name="top", description="Leaderboard of sounds or users")
async def change(ctx, option: Option(str, "users or sounds", required=True), number: Option(str, "number of users", default=5), numberdays: Option(str, "number of days", default=7)):
    await ctx.respond("Processing your request...", delete_after=0)
    if option == "sounds":
        await behavior.player_history_db.write_top_played_sounds(daysFrom=numberdays)
    else:
        await behavior.player_history_db.write_top_users(int(number),daysFrom=numberdays)

@bot.slash_command(name="list", description="returns database of sounds")
async def change(ctx):
    await ctx.respond("Processing your request...", delete_after=0)
    await behavior.list_sounds(ctx.user)    

@bot.slash_command(name="subwaysurfers", description="returns database of sounds")
async def change(ctx):
    await ctx.respond("Processing your request...", delete_after=0)
    await behavior.subway_surfers()    

@bot.slash_command(name="familyguy", description="returns database of sounds")
async def change(ctx):
    await ctx.respond("Processing your request...", delete_after=0)
    await behavior.family_guy()

@bot.slash_command(name="slice", description="returns database of sounds")
async def change(ctx):
    await ctx.respond("Processing your request...", delete_after=0)
    await behavior.slice_all()

@bot.slash_command(name="lastsounds", description="returns last sounds downloaded")
async def change(ctx, number: Option(str, "number of sounds", default=10)):
    await ctx.respond("Processing your request...", delete_after=0)
    await behavior.list_sounds(ctx.user, int(number))    




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
    
    if before.channel is None and after.channel is not None and member != bot.user:
        event = "join"
        channel = after.channel
    elif after.channel is None and before.channel is not None:
        event = "leave"
        channel = before.channel
    else:
        return

    if member != bot.user:
        try:
            user_events = db.get_user_events(member_str, event)
            if user_events:
                behavior.last_channel[member_str] = channel
                await asyncio.sleep(.5)
                if channel:
                    sound = user_events[0][2]  # Assuming the sound is in the third column
                    print(f"Playing {sound} for {member_str}")
                    await behavior.play_audio(channel, db.get_sound(sound)[0][2], member_str, is_entrance=True)
            elif event == "join" and not db.get_user_events(member_str):
                await behavior.play_audio(after.channel, "gay-echo.mp3", "admin", is_entrance=True)
        except Exception as e:
            print(f"An error occurred: {e}")

bot.run_bot()
