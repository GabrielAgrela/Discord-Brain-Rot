import asyncio
import os
import discord
from discord.ext import tasks
import sqlite3
import datetime
from Classes.Environment import Environment
from Classes.Bot import Bot
from Classes.BotBehaviour import BotBehavior
import interactions
from discord.commands import Option
from discord import default_permissions
from Classes.UsersUtils import UsersUtils
from Classes.SoundDownloader import SoundDownloader
from Classes.Database import Database
from Classes.MinecraftLogMonitor import MinecraftLogMonitor
import random
import time
import wave
import io
import numpy as np
from pydub import AudioSegment
from pydub.effects import normalize
from pydub.silence import detect_nonsilent
from discord.sinks import WaveSink
import json
from Classes.SpeechRecognition import SpeechRecognizer, DiscordVoiceListener
import platform # Added for OS detection
import re # Add import for regex

env = Environment()
intents = discord.Intents(guilds=True, voice_states=True, messages=True, message_content=True, members=True)
bot = Bot(command_prefix="*", intents=intents, token=env.bot_token, ffmpeg_path=env.ffmpeg_path)

# Usage
#userUtils = UsersUtils(os.path.abspath(os.path.join(os.path.dirname(__file__), "Data", "Users.json")))

behavior = BotBehavior(bot, env.ffmpeg_path)
db = Database(behavior=behavior)
file_name = 'play_requests.csv'

# Flag to enable/disable voice recognition
voice_recognition_enabled = True

# Keywords to detect in voice chat
voice_keywords = [ "chapada", "diogo"]

# Initialize speech recognizer
vosk_model_path = os.path.join(os.path.dirname(__file__), "vosk-model-pt/vosk-model-small-pt-0.3")
speech_recognizer = SpeechRecognizer(
    model_path=vosk_model_path,
    keywords=voice_keywords,
    temp_dir=os.path.join(os.path.dirname(__file__), "temp_audio")
)

# Keyword detection callback
async def handle_keyword_detection(guild, voice_channel, member, text, keywords):
    """Handle keyword detection events from the voice listener"""
    try:
        # Special action for "chapada" keyword
        if "chapada" in keywords:
            # Get a random slap sound from the database
            slap_sounds = Database().get_sounds(slap=True)
            if slap_sounds:
                random_slap = random.choice(slap_sounds)
                # Play the sound in the voice channel
                await behavior.play_audio(voice_channel, random_slap[2], member.name, is_entrance=False)
                # Send notification message
                await behavior.send_message(title=f"👋 {member.name} requested slap 👋", delete_time=5, send_controls=False)
                # Log the action
                Database().insert_action(member.name, "voice_activated_slap", random_slap[0])
            else:
                print("No slap sounds found in the database!")
                
        # Action for "black" keyword
        elif "diogo" in keywords:
            await behavior.send_message(title=f"🧑🏿 {member.name} requested black sound 🧑🏿", delete_time=5, send_controls=False)
            # Get top 25 sounds similar to "black"
            similar_sounds = Database().get_sounds_by_similarity_optimized("nigga", 25)
            if similar_sounds:
                # Choose one randomly
                chosen_sound = random.choice(similar_sounds)
                sound_id = chosen_sound[0]
                sound_filename = chosen_sound[1] # Assuming index 1 is filename based on play_request
                
                # Play the sound
                await behavior.play_audio(voice_channel, sound_filename, member.name, is_entrance=False)
                # Send notification message
                # Log the action
                Database().insert_action(member.name, "voice_activated_black", sound_id)
            else:
                print("No sounds similar to 'black' found in the database!")
                await behavior.send_message(title=f"Couldn't find sounds similar to 'black' for {member.name}", delete_time=10, send_controls=False)
                
    except Exception as e:
        print(f"Error handling keyword detection: {e}")

# Initialize voice listener
voice_listener = DiscordVoiceListener(bot, speech_recognizer, handle_keyword_detection)

# Initialize Minecraft log monitor
minecraft_monitor = MinecraftLogMonitor(bot, "minecraft")

class CooldownManager:
    def __init__(self, cooldown_time):
        self.cooldown = 0
        self.cooldown_time = cooldown_time
        self.latest_event = None

    def is_on_cooldown(self):
        return time.time() - self.cooldown < self.cooldown_time

    def set_cooldown(self):
        self.cooldown = time.time()

    def set_latest_event(self, event):
        self.latest_event = event

    def get_and_clear_latest_event(self):
        event = self.latest_event
        self.latest_event = None
        return event

    def time_left(self):
        return max(0, self.cooldown_time - (time.time() - self.cooldown))

cooldown_manager = CooldownManager(5)  # 5 seconds cooldown

# --- New Background Task --- 
@tasks.loop(seconds=5.0) # Check every 5 seconds
async def check_playback_queue():
    # Use a separate connection for the task to avoid potential threading issues with the main db connection
    conn = None 
    try:
        conn = sqlite3.connect(db.db_path)
        conn.row_factory = sqlite3.Row # Optional: Access columns by name
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, guild_id, sound_filename 
            FROM playback_queue 
            WHERE played_at IS NULL 
            ORDER BY requested_at ASC
        """)
        pending_requests = cursor.fetchall()

        if not pending_requests:
            return # No pending requests

        print(f"[Playback Queue] Found {len(pending_requests)} pending requests.")

        for request in pending_requests:
            req_id = request['id']
            guild_id = request['guild_id']
            sound_filename = request['sound_filename']
            
            print(f"[Playback Queue] Processing request ID {req_id}: Play '{sound_filename}' in guild {guild_id}")

            # Find the guild
            guild = bot.get_guild(guild_id)
            if not guild:
                print(f"[Playback Queue] Error: Bot is not in guild {guild_id}. Skipping request {req_id}.")
                # Mark as played to prevent retrying indefinitely if bot left server
                cursor.execute("UPDATE playback_queue SET played_at = ? WHERE id = ?", (datetime.datetime.now(), req_id))
                conn.commit()
                continue
            
            # Get sound details from DB (needed for path?)
            # Assuming get_sound returns a tuple/row with filename at index 2
            sound_data = db.get_sound(sound_filename)
            if not sound_data:
                 print(f"[Playback Queue] Error: Sound '{sound_filename}' not found in database. Skipping request {req_id}.")
                 cursor.execute("UPDATE playback_queue SET played_at = ? WHERE id = ?", (datetime.datetime.now(), req_id)) # Mark as played
                 conn.commit()
                 continue

            # --- Play the sound --- 
            # Using behavior.play_sound directly might be simpler if it takes a path
            # We need the actual sound file path. Let's assume it's in a specific folder
            # TODO: Adjust this path based on where sounds are stored!
            sound_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "Sounds"))
            sound_path = os.path.join(sound_folder, sound_filename) 

            if not os.path.exists(sound_path):
                print(f"[Playback Queue] Error: Sound file not found at '{sound_path}'. Skipping request {req_id}.")
                cursor.execute("UPDATE playback_queue SET played_at = ? WHERE id = ?", (datetime.datetime.now(), req_id)) # Mark as played
                conn.commit()
                continue
            
            try:
                # Use the core play_sound method from BotBehavior (assuming it exists and takes path + voice_client)
                # Need to check BotBehavior for the correct method signature
                # Let's assume it's behavior.play_sound(sound_path, voice_client)
                channel = behavior.get_largest_voice_channel(guild)
                if channel is not None:
                    await behavior.play_audio(channel, sound_filename, "webpage")
                    Database().insert_action("admin", "play_sound_periodically", sound_filename)
                print(f"[Playback Queue] Successfully played '{sound_filename}' for request {req_id}.")
                
                # Mark as played in DB
                cursor.execute("UPDATE playback_queue SET played_at = ? WHERE id = ?", (datetime.datetime.now(), req_id))
                conn.commit()

                # Optional: Small delay between sounds if processing multiple
                await asyncio.sleep(1) 

            except Exception as e:
                print(f"[Playback Queue] Error playing sound for request {req_id}: {e}")
                # Mark as played even on error to avoid retrying constantly
                cursor.execute("UPDATE playback_queue SET played_at = ? WHERE id = ?", (datetime.datetime.now(), req_id))
                conn.commit()
        
    except sqlite3.Error as db_err:
        print(f"[Playback Queue] Database error: {db_err}")
    except Exception as e:
        print(f"[Playback Queue] Unexpected error in background task: {e}")
    finally:
        if conn:
            conn.close()
# --- End Background Task ---

@default_permissions(manage_messages=True)
@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    #bot.loop.create_task(behavior.check_if_in_game())
    await behavior.delete_controls_message()
    await behavior.clean_buttons()
    await behavior.send_controls(force=True)
    
    
    bot.loop.create_task(behavior.play_sound_periodically())
    bot.loop.create_task(behavior.update_bot_status())
    bot.loop.create_task(SoundDownloader(behavior, behavior.db, os.getenv("CHROMEDRIVER_PATH")).move_sounds())
    check_playback_queue.start() # Start the new background task
    bot.loop.create_task(voice_listener.listen_to_voice_channels())  # Start voice recognition
    
    # Start Minecraft log monitoring
    if minecraft_monitor.start_monitoring():
        print("Minecraft log monitoring started successfully")
        # Test channel access and send initial message
       # await minecraft_monitor.test_channel_access()
    else:
        print("Failed to start Minecraft log monitoring - check if /opt/minecraft/logs exists")

    # --- Auto-join most populated voice channel --- 
    print("Attempting to join the most populated voice channel in each guild...")
    for guild in bot.guilds:
        print(f"Checking guild: {guild.name} ({guild.id})")
        channel_to_join = behavior.get_largest_voice_channel(guild)
        
        if channel_to_join:
            print(f"Found most populated channel in {guild.name}: {channel_to_join.name} ({len(channel_to_join.members)} members)")
            try:
                # Disconnect if already connected in this guild
                if guild.voice_client and guild.voice_client.is_connected():
                    print(f"Disconnecting from current channel in {guild.name}...")
                    await behavior.send_message(title=f"Disconnecting from current channel in {guild.name}...", send_controls=False)
                    await guild.voice_client.disconnect(force=True)
                    await asyncio.sleep(1) # Short delay after disconnecting

                # Attempt to connect
                print(f"Attempting to connect to {channel_to_join.name} in {guild.name}...")
                await channel_to_join.connect()
                print(f"Successfully connected to {channel_to_join.name} in {guild.name}.")
                if not bot.startup_sound_played:
                    try:
                        random_sound = Database().get_random_sounds()[0][2]
                        await behavior.play_audio(channel_to_join, random_sound, "startup")
                    except Exception as e:
                        print(f"Error playing startup sound: {e}")
                    bot.startup_sound_played = True
            except discord.ClientException as e:
                print(f"Error connecting to {channel_to_join.name} in {guild.name}: {e}. Already connected elsewhere or connection issue.")
            except asyncio.TimeoutError:
                print(f"Timeout trying to connect to {channel_to_join.name} in {guild.name}.")
            except Exception as e:
                print(f"An unexpected error occurred while trying to connect to {channel_to_join.name} in {guild.name}: {e}")
        else:
            print(f"No suitable voice channel found in {guild.name} (or all are empty).")
    print("Finished auto-join process.")
    # --- End Auto-join ---

@bot.slash_command(name="voicerecognition", description="Enable or disable real-time voice conversation logging")
async def voice_recognition_cmd(ctx, enabled: Option(bool, "Enable or disable voice recognition", required=True)):
    global voice_recognition_enabled
    
    # Check if user has admin permission
    if not behavior.is_admin_or_mod(ctx.author):
        await ctx.respond("You don't have permission to use this command.", ephemeral=True)
        return
    
    voice_recognition_enabled = enabled
    voice_listener.set_enabled(enabled)
    
    if enabled:
        await ctx.respond("Real-time voice conversation logging has been **enabled**. The bot will now print conversations it hears to the console.", ephemeral=False)
        print("Voice recognition ENABLED by", ctx.author.name)
    else:
        await ctx.respond("Real-time voice conversation logging has been **disabled**.", ephemeral=False)
        print("Voice recognition DISABLED by", ctx.author.name)
    
    Database().insert_action(ctx.author.name, "voice_recognition", "enabled" if enabled else "disabled")

@bot.slash_command(name="keywords", description="Manage keywords for voice recognition")
async def manage_keywords(ctx, 
                         action: Option(str, "Action to perform", choices=["add", "remove", "list"], required=True),
                         keyword: Option(str, "Keyword to add or remove", required=False)):
    global voice_keywords, speech_recognizer
    
    # Check if user has admin permission
    if not behavior.is_admin_or_mod(ctx.author):
        await ctx.respond("You don't have permission to use this command.", ephemeral=True)
        return
                                
    if action == "list":
        if not voice_keywords:
            await ctx.respond("No keywords are currently being monitored.", ephemeral=False)
        else:
            formatted_keywords = ", ".join(f"`{kw}`" for kw in voice_keywords)
            await ctx.respond(f"**Currently monitoring these keywords:**\n{formatted_keywords}", ephemeral=False)
    
    elif action == "add" and keyword:
        if keyword.lower() in [k.lower() for k in voice_keywords]:
            await ctx.respond(f"Keyword `{keyword}` is already being monitored.", ephemeral=False)
        else:
            voice_keywords.append(keyword.lower())
            # Update the speech recognizer with the new keywords
            speech_recognizer.keywords = voice_keywords
            await ctx.respond(f"Added keyword `{keyword}` to monitoring list.", ephemeral=False)
            print(f"Keyword '{keyword}' added by {ctx.author.name}")
    
    elif action == "remove" and keyword:
        # Case insensitive removal
        lower_keywords = [k.lower() for k in voice_keywords]
        if keyword.lower() in lower_keywords:
            index = lower_keywords.index(keyword.lower())
            removed = voice_keywords.pop(index)
            # Update the speech recognizer with the updated keywords
            speech_recognizer.keywords = voice_keywords
            await ctx.respond(f"Removed keyword `{removed}` from monitoring list.", ephemeral=False)
            print(f"Keyword '{removed}' removed by {ctx.author.name}")
        else:
            await ctx.respond(f"Keyword `{keyword}` is not in the monitoring list.", ephemeral=False)
    
    else:
        await ctx.respond("Please provide a valid keyword to add or remove.", ephemeral=True)
    
    Database().insert_action(ctx.author.name, f"keyword_{action}", keyword if keyword else "list")

async def get_sound_autocomplete(ctx):
    try:
        # Get the current input value and return immediately if too short
        current = ctx.value.lower() if ctx.value else ""
        if not current or len(current) < 2:
            return []
        
        # Benchmark the query time
        start_time = time.time()
        similar_sounds = Database().get_sounds_by_similarity_optimized(current, 15)
        end_time = time.time()
        query_time = end_time - start_time
        print(f"get_sounds_by_similarity took {query_time:.3f} seconds for query: '{current}'")
        
        # Quick process and return
        return [sound[2].split('/')[-1].replace('.mp3', '') for sound in similar_sounds]
    except Exception as e:
        print(f"Autocomplete error: {e}")
        return []

async def get_list_autocomplete(ctx):
    try:
        # Get the current input value
        current = ctx.value.lower() if ctx.value else ""
        
        # Get all lists
        all_lists = db.get_sound_lists()
        
        # If no input, return all lists (up to 25)
        if not current:
            return [list_name for _, list_name, _, _, _ in all_lists][:25]
        
        # Filter lists based on input
        matching_lists = []
        for list_id, list_name, creator, created_at, sound_count in all_lists:
            if current in list_name.lower():
                # Format as "list_name"
                matching_lists.append(f"{list_name}")
        
        # Sort by relevance (exact matches first, then starts with, then contains)
        exact_matches = [name for name in matching_lists if name.lower() == current]
        starts_with = [name for name in matching_lists if name.lower().startswith(current) and name.lower() != current]
        contains = [name for name in matching_lists if current in name.lower() and not name.lower().startswith(current) and name.lower() != current]
        
        # Combine and limit to 25 results
        sorted_results = exact_matches + starts_with + contains
        return sorted_results[:25]
    except Exception as e:
        print(f"List autocomplete error: {e}")
        return []

@bot.slash_command(name="toca", description="Write a name of something you want to hear")
@discord.option(
    "message",
    description="Sound name ('random' for random)",
    autocomplete=get_sound_autocomplete,
    required=True
)
@discord.option(
    "speed",
    description="Playback speed multiplier (e.g., 1.5 for faster, 0.8 for slower). Default: 1.0",
    required=False,
    type=float, # Specify type for better validation
    default=1.0
)
@discord.option(
    "volume",
    description="Volume multiplier (e.g., 1.5 for 150%, 0.5 for 50%). Default: 1.0",
    required=False,
    type=float, # Specify type for better validation
    default=1.0 # Default multiplier is 1.0 (no change)
)
@discord.option(
    "reverse",
    description="Play the sound in reverse? (True/False). Default: False",
    required=False,
    type=bool, # Specify type for better validation
    default=False
)
async def play_requested(ctx, message: str, speed: float = 1.0, volume: float = 1.0, reverse: bool = False):
    await ctx.respond("Processing your request...", delete_after=0)

    # --- Input Validation/Clamping ---
    try:
        # Clamp speed to a reasonable range (e.g., 0.5x to 3.0x)
        speed = max(0.5, min(speed, 3.0))
        # Clamp volume multiplier (e.g., 0.1x to 5.0x)
        volume = max(0.1, min(volume, 5.0))
        # --------------------------------

        author = ctx.user
        username_with_discriminator = f"{author.name}#{author.discriminator}"

        effects = {
            "speed": speed,
            "volume": volume, # Now a multiplier
            "reverse": reverse
        }

        print(f"Playing '{message}' for {username_with_discriminator} with effects: {effects}")
        try:
            if message == "random":
                # Note: Applying effects to random sounds might need adjustments in play_random_sound
                # For now, let's pass effects=None or handle it inside play_random_sound
                asyncio.run_coroutine_threadsafe(behavior.play_random_sound(username_with_discriminator, effects=effects), bot.loop)
            else:
                # Pass the effects dictionary to play_request
                await behavior.play_request(message, author.name, effects=effects)
        except Exception as e:
            print(f"Error in play_requested: {e}")
            # Fallback to random sound without effects on error? Or just report error?
            # Let's just report the error for now.
            await ctx.followup.send(f"An error occurred while trying to play '{message}'. Please try again later.", ephemeral=True, delete_after=10)
            # asyncio.run_coroutine_threadsafe(behavior.play_random_sound(username_with_discriminator), bot.loop) # Optional fallback
            return
    except Exception as e:
        print(f"Error in play_requested: {e}")
        await ctx.followup.send(f"An error occurred while processing your request. Please try again later.", ephemeral=True, delete_after=10)
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
        elif language == "costa":
            await behavior.tts_EL(user, message, "costa")
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
async def tts(ctx, sound: Option(str, "Base sound you want to convert", required=True), char: Option(str, "tyson, ventura, costa", required=True)):
    await ctx.respond("Processing your request...", delete_after=0)

    user = discord.utils.get(bot.get_all_members(), name=ctx.user.name)

    behavior.color = discord.Color.dark_blue()
    if char in ["tyson", "ventura", "costa"]:
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
    await behavior.slice_all(ctx)

@bot.slash_command(name="lastsounds", description="returns last sounds downloaded")
async def change(ctx, number: Option(str, "number of sounds", default=10)):
    await behavior.list_sounds(ctx, int(number))

# @bot.slash_command(name="userlolstats", description="get your lol stats", channel_ids=["1321095299367833723"])
# async def userlolstats(ctx, username: Option(str, "username", required=True), gamemode: Option(str, "ARAM, CHERRY, CLASSIC, NEXUSBLITZ, ONEFORALL, STRAWBERRY, ULTBOOK, URF", required=True), champion: Option(str, "champion (ignore if you want all)", required=False)):
#     await ctx.respond("Processing your request...", delete_after=0)
#     await behavior.userlolstats(username, gamemode, champion)

# @bot.slash_command(name="user_vs_userlolstats", description="get your lol stats vs another user", channel_ids=["1321095299367833723"])
# async def user_vs_userlolstats(ctx, username1: Option(str, "username1", required=True), username2: Option(str, "username2", required=True), gamemode: Option(str, "ARAM, CHERRY, CLASSIC, NEXUSBLITZ, ONEFORALL, STRAWBERRY, ULTBOOK, URF", required=True), champion: Option(str, "champion name", required=True)):
#     await ctx.respond("Processing your request...", delete_after=0)
#     await behavior.user_vs_userlolstats(username1, username2, gamemode, champion)

# @bot.slash_command(name="loltime", description="get this servers users lol time played this year(ish)", channel_ids=["1321095299367833723"])
# async def loltime(ctx):
#     await ctx.respond("Processing your request...", delete_after=0)
#     await behavior.userloltime()

# @bot.slash_command(name="lolfriends", description="stats of your friends in league of legends when you play with them", channel_ids=["1321095299367833723"])
# async def lolfriends(ctx, username: Option(str, "username", required=True)):
#     await ctx.respond("Processing your request...", delete_after=0)
#     await behavior.userlolfriends(username)

# @bot.slash_command(name="addloluser", description="username#tagline", channel_ids=["1321095299367833723"])
# async def addloluser(ctx, username: Option(str, "username", required=True)):
#     await ctx.respond("Processing your request...", delete_after=0)
#     await behavior.insertLoLUser(username)

# @bot.slash_command(name="refreshgames", description="refresh games")
# async def refreshgames(ctx):
#     await ctx.respond("Processing your request...", delete_after=0)
#     await behavior.refreshgames()

@bot.slash_command(name="addevent", description="Add a join/leave event sound for a user")
async def add_event(ctx, 
    username: Option(str, "Select a user", choices=db.get_all_users(), required=True),
    event: Option(str, "Event type", choices=["join", "leave"], required=True),
    sound: Option(str, "Sound name to play", required=True)):
    
    await ctx.respond("Processing your request...", delete_after=0)
    success = await behavior.add_user_event(username, event, sound)
    if success:
        await ctx.followup.send(f"Successfully added {sound} as {event} sound for {username}!", ephemeral=True, delete_after=5)
    else:
        await ctx.followup.send("Failed to add event sound. Make sure the username and sound are correct!", ephemeral=True, delete_after=5)

@bot.slash_command(name="listevents", description="List your join/leave event sounds")
async def list_events(ctx, 
    username: Option(str, "User to list events for (defaults to you)", choices=db.get_all_users(), required=False)):
    await ctx.respond("Processing your request...", delete_after=0)
    
    if username:
        target_user = username
        target_user_full = username  # Since the database already stores the full username
    else:
        target_user = ctx.user.name
        target_user_full = f"{ctx.user.name}#{ctx.user.discriminator}"
    
    if not await behavior.list_user_events(target_user, target_user_full, requesting_user=ctx.user.name):
        await ctx.followup.send(f"No event sounds found for {target_user}!", ephemeral=True)

# Sound List Commands
@bot.slash_command(name="createlist", description="Create a new sound list")
async def create_list(ctx, list_name: Option(str, "Name for your sound list", required=True)):
    # Check if the user already has a list with this name
    existing_list = db.get_list_by_name(list_name, ctx.author.name)
    if existing_list:
        await ctx.respond(f"You already have a list named '{list_name}'.", ephemeral=True)
        return
        
    # Create the list
    list_id = db.create_sound_list(list_name, ctx.author.name)
    if list_id:
        await ctx.respond(f"Created list '{list_name}'.", ephemeral=True)
        
        # Send a message confirming the creation
        await behavior.send_message(
            title="List Created",
            description=f"Created a new sound list: '{list_name}'\nAdd sounds with `/addtolist`."
        )
    else:
        await ctx.respond("Failed to create list.", ephemeral=True)

@bot.slash_command(name="addtolist", description="Add a sound to a sound list")
async def add_to_list(
    ctx, 
    sound: Option(str, "Sound to add to the list", autocomplete=get_sound_autocomplete, required=True),
    list_name: Option(str, "Name of the list", autocomplete=get_list_autocomplete, required=True)
):
    # Get the list
    sound_list = db.get_list_by_name(list_name)
    if not sound_list:
        await ctx.respond(f"List '{list_name}' not found.", ephemeral=True)
        return
    
    # Get the sound ID
    soundid = db.get_sounds_by_similarity(sound)[0][1]
        
    # Add the sound to the list
    success, message = db.add_sound_to_list(sound_list[0], soundid)
    if success:
        # Get the list creator for the success message
        list_creator = sound_list[2]
        
        # If the user adding the sound is not the creator, include that in the message
        if list_creator != ctx.author.name:
            await ctx.respond(f"Added sound '{sound}' to {list_creator}'s list '{list_name}'.", ephemeral=True)
            
            # Optionally notify in the channel about the addition
            await behavior.send_message(
                title=f"Sound Added to List",
                description=f"{ctx.author.name} added '{sound}' to {list_creator}'s list '{list_name}'."
            )
        else:
            await ctx.respond(f"Added sound '{sound}' to your list '{list_name}'.", ephemeral=True)
    else:
        await ctx.respond(f"Failed to add sound to list: {message}", ephemeral=True)

@bot.slash_command(name="removefromlist", description="Remove a sound from one of your lists")
async def remove_from_list(
    ctx, 
    sound: Option(str, "Sound to remove from the list", required=True),
    list_name: Option(str, "Name of your list", autocomplete=get_list_autocomplete, required=True)
):
    # Get the list
    sound_list = db.get_list_by_name(list_name)
    if not sound_list:
        await ctx.respond(f"List '{list_name}' not found.", ephemeral=True)
        return
    
    # Check if the user is the creator of the list
    if sound_list[2] != ctx.author.name:
        await ctx.respond(f"You don't have permission to modify the list '{list_name}'. Only the creator ({sound_list[2]}) can remove sounds from it.", ephemeral=True)
        return
        
    # Remove the sound from the list
    success = db.remove_sound_from_list(sound_list[0], sound)
    if success:
        await ctx.respond(f"Removed sound '{sound}' from list '{list_name}'.", ephemeral=True)
    else:
        await ctx.respond("Failed to remove sound from list.", ephemeral=True)

@bot.slash_command(name="deletelist", description="Delete one of your sound lists")
async def delete_list(ctx, list_name: Option(str, "Name of your list", autocomplete=get_list_autocomplete, required=True)):
    # Get the list
    sound_list = db.get_list_by_name(list_name)
    if not sound_list:
        await ctx.respond(f"List '{list_name}' not found.", ephemeral=True)
        return
    
    # Check if the user is the creator of the list
    if sound_list[2] != ctx.author.name:
        await ctx.respond(f"You don't have permission to delete the list '{list_name}'. Only the creator ({sound_list[2]}) can delete it.", ephemeral=True)
        return
        
    # Delete the list
    success = db.delete_sound_list(sound_list[0])
    if success:
        await ctx.respond(f"Deleted list '{list_name}'.", ephemeral=True)
        
        # Send a message confirming the deletion
        await behavior.send_message(
            title="List Deleted",
            description=f"The list '{list_name}' has been deleted."
        )
    else:
        await ctx.respond("Failed to delete list.", ephemeral=True)

@bot.slash_command(name="showlist", description="Display a sound list with buttons")
async def show_list(ctx, list_name: Option(str, "Name of the list to display", autocomplete=get_list_autocomplete, required=True)):
    # Get the list
    sound_list = db.get_list_by_name(list_name)
    if not sound_list:
        await ctx.respond(f"List '{list_name}' not found.", ephemeral=True)
        return
        
    list_id = sound_list[0]
    
    # Get the sounds in the list
    sounds = db.get_sounds_in_list(list_id)
    if not sounds:
        await ctx.respond(f"List '{list_name}' is empty.", ephemeral=True)
        return
        
    # Create a paginated view with buttons for each sound
    from Classes.UI import PaginatedSoundListView
    view = PaginatedSoundListView(behavior, list_id, list_name, sounds, ctx.author.name)
    
    # Send a message with the view
    await behavior.send_message(
        title=f"Sound List: {list_name} (Page 1/{len(view.pages)})",
        description=f"Contains {len(sounds)} sounds. Showing sounds 1-{min(8, len(sounds))} of {len(sounds)}",
        view=view
    )
    
    # Remove the redundant confirmation message
    await ctx.respond(delete_after=0)

@bot.slash_command(name="mylists", description="Show your sound lists")
async def my_lists(ctx):
    # Get the user's lists
    lists = db.get_sound_lists(creator=ctx.author.name)
    if not lists:
        await ctx.respond("You don't have any sound lists yet. Create one with `/createlist`.", ephemeral=True)
        return
        
    # Create a view with buttons for each list
    from Classes.UI import UserSoundListsView
    view = UserSoundListsView(behavior, lists, ctx.author.name)
    
    # Send a message with the view
    await behavior.send_message(
        title="Your Sound Lists",
        description=f"You have {len(lists)} sound lists. Click a list to view its sounds.",
        view=view
    )
    
    # Remove the redundant confirmation message
    await ctx.respond(delete_after=0)

@bot.slash_command(name="showlists", description="Show all available sound lists")
async def show_lists(ctx):
    # Get all sound lists
    lists = db.get_sound_lists()
    if not lists:
        await ctx.respond("There are no sound lists available yet. Create one with `/createlist`.", ephemeral=True)
        return
    
    # Create a view with buttons for each list
    from Classes.UI import UserSoundListsView
    view = UserSoundListsView(behavior, lists, None)  # Pass None as creator to indicate showing all lists
    
    # Send a message with the view
    await behavior.send_message(
        title="All Sound Lists",
        description=f"There are {len(lists)} sound lists available. Click a list to view its sounds.",
        view=view
    )
    
    await ctx.respond(delete_after=0)

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    member_str = f"{member.name}#{member.discriminator}"
    
    if member == bot.user:
        return

    # Determine the event type
    if before.channel is None and after.channel is not None:
        event = "join"
        channel = after.channel
    elif before.channel is not None and after.channel is None:
        event = "leave"
        channel = before.channel
    elif before.channel != after.channel:
        event = "join"
        channel = after.channel
    else:
        return  # No relevant change

    # Skip if the user joined the server's AFK channel
    if event == "join" and channel and channel == channel.guild.afk_channel:
        print(f"Ignoring join event for {member_str} in AFK channel {channel}")
        return
        
    # Log the voice state update
    print(f"Voice state update: {member_str} {event} channel {channel}")

    if cooldown_manager.is_on_cooldown():
        # Store the latest event while on cooldown
        cooldown_manager.set_latest_event((member, member_str, event, channel))
        return

    # Play audio immediately
    await play_audio_for_event(member, member_str, event, channel)

    # Set cooldown after playing
    cooldown_manager.set_cooldown()

    # Schedule checking for latest event after cooldown
    bot.loop.create_task(check_latest_event_after_cooldown())

async def check_latest_event_after_cooldown():
    await asyncio.sleep(cooldown_manager.time_left())
    latest_event = cooldown_manager.get_and_clear_latest_event()
    if latest_event:
        member, member_str, event, channel = latest_event
        await play_audio_for_event(member, member_str, event, channel)
        cooldown_manager.set_cooldown()  # Reset cooldown after playing the latest event

async def play_audio_for_event(member, member_str, event, channel):
    try:
        user_events = db.get_user_events(member_str, event)
        if user_events:
            if await behavior.is_channel_empty(channel):
                return
            sound = random.choice(user_events)[2]
            behavior.last_channel[member_str] = channel
            if channel:
                print(f"Playing {sound} for {member_str} on {event}")
                await behavior.play_audio(channel, db.get_sounds_by_similarity(sound)[0][1], member_str, is_entrance=True)
                db.insert_action(member_str, event, db.get_sounds_by_similarity(sound)[0][0])
        elif event == "join":
            await behavior.play_audio(channel, "gay-echo.mp3", "admin", is_entrance=True)
            db.insert_action(member_str, event, db.get_sounds_by_similarity("gay-echo.mp3")[0][0])
        elif event == "leave":
            db.insert_action(member_str, event, "-")
            await behavior.is_channel_empty(channel)
    except Exception as e:
        print(f"An error occurred: {e}")

# Add an event handler for bot shutdown
@bot.event
async def on_close():
    print("Bot is closing, cleaning up resources...")
    # Stop voice listeners and shut down the executor
    await voice_listener.stop_all_listeners()
    # Stop Minecraft log monitoring
    if minecraft_monitor.observer and minecraft_monitor.observer.is_alive():
        minecraft_monitor.stop_monitoring()
        print("Minecraft log monitoring stopped")
    # Cancel the playback queue task
    check_playback_queue.cancel()
    print("Cleanup complete.")

# --- New DM Video Link Handler ---
@bot.event
async def on_message(message):
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return
    
    # Check if the message is a DM
    if isinstance(message.channel, discord.DMChannel):
        # Refined regex to better match specific video/post URLs, including optional query params/fragments
        url_pattern = re.compile(
            r'(?:'                                             # Start non-capturing group for all patterns
            r'https?://(?:www\.|vm\.)?tiktok\.com/'             # TikTok (www or vm)
            r'(?:@[\w.-]+/video/\d+|[^/?#\s]+/?)'             # Matches /@user/video/id or /shortcode (now ignores ?#)
            r'(?:[?#][^\s]*)?|'                                # Optional query/fragment
            r'https?://(?:www\.)?instagram\.com/'              # Instagram
            r'(?:p|reels|reel|stories)/[\w-]+/?'               # Matches /p/..., /reels/..., /reel/..., /stories/...
            r'(?:[?#][^\s]*)?|'                                # Optional query/fragment
            r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)' # YouTube (youtube.com/watch?v= or youtu.be/)
            r'[\w-]+'                                           # Matches the video ID
            r'(?:[?#][^\s]*)?'                                   # Optional query/fragment
            r')\b'                                            # Word boundary to prevent partial matches
        )
        match = url_pattern.search(message.content)

        if match:
            url = match.group(0)
            print(f"Detected video URL in DM from {message.author}: {url}")
            
            # Send processing message
            processing_msg = await message.channel.send("Processing your video... 🤓 This might take a moment.")

            file_path = None  # Initialize file_path to None
            try:
                # Use BotBehavior to download and convert the video
                # Extract potential custom filename or time limit (if user provides them after URL)
                parts = message.content[match.end():].strip().split(maxsplit=1)
                time_limit_str = None
                custom_filename = None

                if len(parts) > 0 and parts[0].isdigit():
                    time_limit_str = parts[0]
                    if len(parts) > 1:
                        custom_filename = parts[1]
                elif len(parts) > 0:
                     custom_filename = " ".join(parts) # Assume rest is filename

                # Sanitize the custom filename
                if custom_filename:
                    custom_filename = custom_filename.strip() # Remove leading/trailing whitespace
                    custom_filename = custom_filename.lstrip('/') # Remove leading slashes
                    # Add any other necessary sanitization here (e.g., removing invalid characters)
                    if not custom_filename: # If stripping leaves an empty string
                        custom_filename = None

                time_limit = int(time_limit_str) if time_limit_str else None

                file_path = await behavior.save_sound_from_video(url, custom_filename=custom_filename, time_limit=time_limit)
                if file_path:
                    await processing_msg.edit(content="Check botchannel for your new sound!")

            except ValueError as ve: # Catch specific yt-dlp errors (like duration limit)
                 await processing_msg.edit(content=f"Error: {ve}")
            except Exception as e:
                print(f"Error processing video link in DM: {e}")
                await processing_msg.edit(content="Sorry, an error occurred while processing the video. " + str(e)) # Keep str(e)
            finally:
                # Clean up the downloaded file
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        print(f"Cleaned up temporary file: {file_path}")
                    except Exception as e:
                        print(f"Error cleaning up file {file_path}: {e}")

    # Allow other on_message handlers or commands to process the message if needed
    # If you are using commands.Bot, you might need this:
    # await bot.process_commands(message) # Uncomment if you use bot.command decorators

# --- End DM Video Link Handler ---

@bot.slash_command(name="minecraft", description="Control Minecraft server log monitoring")
async def minecraft_logs(ctx, 
                        action: Option(str, "Action to perform", choices=["start", "stop", "status", "test"], required=True),
                        channel: Option(str, "Channel name for monitoring (default: minecraft)", required=False, default="minecraft")):
    """Control Minecraft server log monitoring"""
    global minecraft_monitor
    
    # Check for admin permissions
    if not behavior.is_admin_or_mod(ctx.author):
        await ctx.respond("You don't have permission to use this command.", ephemeral=True)
        return
    
    if action == "start":
        # Stop existing monitor if running
        if minecraft_monitor.observer and minecraft_monitor.observer.is_alive():
            minecraft_monitor.stop_monitoring()
        
        # Create new monitor with specified channel
        minecraft_monitor = MinecraftLogMonitor(bot, channel)
        
        if minecraft_monitor.start_monitoring():
            await ctx.respond(f"✅ Minecraft log monitoring started for channel `#{channel}`")
            # Test channel access
            success = await minecraft_monitor.test_channel_access()
            if not success:
                await ctx.followup.send(f"⚠️ Warning: Could not find or access channel `#{channel}`. Make sure the channel exists and the bot has permissions.")
        else:
            await ctx.respond("❌ Failed to start Minecraft log monitoring. Check if `/opt/minecraft/logs/latest.log` exists.")
    
    elif action == "stop":
        if minecraft_monitor.observer and minecraft_monitor.observer.is_alive():
            minecraft_monitor.stop_monitoring()
            await ctx.respond("✅ Minecraft log monitoring stopped")
        else:
            await ctx.respond("⚠️ Minecraft log monitoring is not currently running")
    
    elif action == "status":
        if minecraft_monitor.observer and minecraft_monitor.observer.is_alive():
            channel_name = minecraft_monitor.channel_name
            log_path = "/opt/minecraft/logs/latest.log"
            log_exists = os.path.exists(log_path)
            
            embed = discord.Embed(
                title="🎮 Minecraft Log Monitor Status",
                color=discord.Color.green(),
                timestamp=datetime.datetime.now()
            )
            embed.add_field(name="Status", value="✅ Running", inline=True)
            embed.add_field(name="Channel", value=f"#{channel_name}", inline=True)
            embed.add_field(name="Log File", value="✅ Exists" if log_exists else "❌ Missing", inline=True)
            
            await ctx.respond(embed=embed)
        else:
            embed = discord.Embed(
                title="🎮 Minecraft Log Monitor Status",
                color=discord.Color.red(),
                timestamp=datetime.datetime.now()
            )
            embed.add_field(name="Status", value="❌ Stopped", inline=True)
            
            await ctx.respond(embed=embed)
    
    elif action == "test":
        if minecraft_monitor.observer and minecraft_monitor.observer.is_alive():
            success = await minecraft_monitor.test_channel_access()
            if success:
                await ctx.respond("✅ Test message sent successfully to minecraft channel")
            else:
                await ctx.respond("❌ Failed to send test message. Check channel permissions.")
        else:
            await ctx.respond("⚠️ Minecraft log monitoring is not running. Start it first with `/minecraft start`")

@bot.slash_command(name="reboot", description="Reboots the host machine (Admin only).")
async def reboot_command(ctx):
    """Reboots the machine the bot is running on. Requires admin permissions."""
    # Check for admin permissions
    if not behavior.is_admin_or_mod(ctx.author):
        # Use ctx.respond directly for ephemeral permission denial
        await ctx.respond("You don't have permission to use this command.", ephemeral=True)
        return

    # Use behavior.send_message for public confirmation (removed invalid ephemeral argument)
    await behavior.send_message(title="🚨 System Reboot Initiated 🚨", description=f"Rebooting the machine as requested by {ctx.author.mention}...")
    # Still need an initial response to the interaction
    await ctx.respond("Reboot command received...", ephemeral=True, delete_after=1)
    print(f"Reboot initiated by {ctx.author.name} ({ctx.author.id})")

    # Allow Discord to send the message before shutting down
    await asyncio.sleep(2)

    # Determine OS and execute reboot command
    system = platform.system()
    try:
        if system == "Windows":
            os.system("shutdown /r /t 1 /f") # /f forces closing applications, /t 1 gives 1 second delay
        elif system == "Linux" or system == "Darwin": # Darwin is macOS
            # WARNING: Requires passwordless sudo or running as root.
            print("Attempting reboot via 'sudo reboot'...")
            os.system("sudo reboot")
        else:
            # Edit the original interaction response for unsupported OS
            await ctx.edit_original_response(content=f"Reboot command not supported on this operating system ({system}).")
            # Send public error message via behavior.send_message (removed invalid ephemeral argument)
            await behavior.send_message(title="Reboot Failed", description=f"Reboot command not supported on this operating system ({system}).", delete_time=10)
            print(f"Reboot command failed: Unsupported OS ({system})")
            return
        # If the script continues after os.system, the command might have failed silently or is just queued.
        print(f"Reboot command issued successfully for {system}.")

    except Exception as e:
        # Edit the original interaction response for failure
        try:
            await ctx.edit_original_response(content=f"Failed to initiate reboot: {e}")
            # Send public error message via behavior.send_message (removed invalid ephemeral argument)
            await behavior.send_message(title="Reboot Failed", description=f"Failed to initiate reboot: {e}", delete_time=10)
        except discord.NotFound: # Interaction might be gone if reboot was too fast
            pass
        print(f"Error during reboot command execution: {e}")

@bot.slash_command(name="fixvoice", description="Fix voice connection issues by cleaning up all connections (Admin only).")
async def fix_voice_command(ctx):
    """Cleans up all voice connections to fix connection issues. Requires admin permissions."""
    # Check for admin permissions
    if not behavior.is_admin_or_mod(ctx.author):
        await ctx.respond("You don't have permission to use this command.", ephemeral=True)
        return

    await ctx.respond("🔧 Cleaning up voice connections...", ephemeral=False)
    print(f"Voice cleanup initiated by {ctx.author.name} ({ctx.author.id})")

    try:
        # Use the new cleanup method
        await behavior.cleanup_all_voice_connections()
        
        await behavior.send_message(
            title="✅ Voice Cleanup Complete",
            description=f"All voice connections have been cleaned up by {ctx.author.mention}. The bot should now be able to connect properly.",
            delete_time=10
        )
        
        print("Voice cleanup completed successfully")
        
    except Exception as e:
        await behavior.send_message(
            title="❌ Voice Cleanup Failed", 
            description=f"Failed to clean up voice connections: {e}",
            delete_time=10
        )
        print(f"Error during voice cleanup: {e}")

bot.run_bot()
