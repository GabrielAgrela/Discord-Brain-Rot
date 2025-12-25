import asyncio
import os
import subprocess
import discord
from discord.ext import tasks
import sqlite3
import datetime
from Classes.Environment import Environment
from Classes.Bot import Bot
from Classes.BotBehaviour import BotBehavior
from discord.commands import Option
from discord import default_permissions
from Classes.UsersUtils import UsersUtils
from Classes.SoundDownloader import SoundDownloader
from Classes.Database import Database
from Classes.MinecraftLogMonitor import MinecraftLogMonitor
import random
import time


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

TTS_PROFILES = {
    "ventura": {
        "display": "Ventura (PT-PT)",
        "flag": ":flag_pt:",
        "thumbnail": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d2/Andr%C3%A9_Ventura_%28Agencia_LUSA%2C_Entrevista_Presidenciais_2021%29%2C_cropped.png/250px-Andr%C3%A9_Ventura_%28Agencia_LUSA%2C_Entrevista_Presidenciais_2021%29%2C_cropped.png",
        "provider": "elevenlabs",
        "voice": "pt",
    },
    "costa": {
        "display": "Costa (PT-PT)",
        "flag": ":flag_pt:",
        "thumbnail": "https://filipamoreno.com/wp-content/uploads/2015/09/18835373_7vzpq.png",
        "provider": "elevenlabs",
        "voice": "costa",
    },
    "tyson": {
        "display": "Tyson (EN)",
        "flag": ":flag_us:",
        "thumbnail": "https://static.wikia.nocookie.net/ippo/images/0/00/Mike_Tyson.png",
        "provider": "elevenlabs",
        "voice": "en",
    },
    "en": {
        "display": "English (Google)",
        "flag": ":flag_gb:",
        "provider": "gtts",
        "lang": "en",
    },
    "pt": {
        "display": "Portuguese (PT - Google)",
        "flag": ":flag_pt:",
        "provider": "gtts",
        "lang": "pt",
    },
    "br": {
        "display": "Portuguese (BR - Google)",
        "flag": ":flag_br:",
        "provider": "gtts",
        "lang": "pt",
        "region": "com.br",
    },
    "es": {
        "display": "Spanish",
        "flag": ":flag_es:",
        "provider": "gtts",
        "lang": "es",
    },
    "fr": {
        "display": "French",
        "flag": ":flag_fr:",
        "provider": "gtts",
        "lang": "fr",
    },
    "de": {
        "display": "German",
        "flag": ":flag_de:",
        "provider": "gtts",
        "lang": "de",
    },
    "ru": {
        "display": "Russian",
        "flag": ":flag_ru:",
        "provider": "gtts",
        "lang": "ru",
    },
    "ar": {
        "display": "Arabic",
        "flag": ":flag_sa:",
        "provider": "gtts",
        "lang": "ar",
    },
    "ch": {
        "display": "Chinese (Mandarin)",
        "flag": ":flag_cn:",
        "provider": "gtts",
        "lang": "zh-CN",
    },
    "ir": {
        "display": "Irish English",
        "flag": ":flag_ie:",
        "provider": "gtts",
        "lang": "en",
        "region": "ie",
    },
}

DEFAULT_TTS_THUMBNAIL = "https://cdn-icons-png.flaticon.com/512/4470/4470312.png"

CHARACTER_CHOICES = [choice for choice, profile in TTS_PROFILES.items() if profile.get("provider") == "elevenlabs"]

# Path to the bot's log file for command history
COMMAND_LOG_FILE = '/var/log/personalgreeter.log'


def tail_command_logs(lines=10, log_path=COMMAND_LOG_FILE):
    """Return the last `lines` lines from the bot's log file."""
    try:
        output = subprocess.check_output(
            ['tail', '-n', str(lines), log_path],
            stderr=subprocess.STDOUT,
            text=True,
        )
        return output.strip().splitlines()
    except Exception as e:
        print(f"Error reading command log: {e}")
        return None

def get_service_logs(lines=10, service_name=None):
    """Return the last `lines` lines from service logs using journalctl."""
    try:
        # First try to get logs for a specific service if provided
        if service_name:
            output = subprocess.check_output(
                ['journalctl', '-u', service_name, '-n', str(lines), '--no-pager'],
                stderr=subprocess.STDOUT,
                text=True,
            )
            return output.strip().splitlines()
        
        # If no service name, try to get logs for current user or system
        commands_to_try = [
            ['journalctl', '--user', '-n', str(lines), '--no-pager'],  # User logs
            ['journalctl', '-n', str(lines), '--no-pager'],  # System logs
        ]
        
        for cmd in commands_to_try:
            try:
                output = subprocess.check_output(
                    cmd,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                return output.strip().splitlines()
            except subprocess.CalledProcessError:
                continue
                
        # If journalctl fails, try to read from the bot's log file
        if os.path.exists(COMMAND_LOG_FILE):
            return tail_command_logs(lines, COMMAND_LOG_FILE)
        
        return None
        
    except Exception as e:
        print(f"Error reading service logs: {e}")
        return None



# --- Background Task to Handle Web Playback Requests ---
@tasks.loop(seconds=5.0)
async def check_playback_queue():
    """Process queued playback requests from the web interface."""
    conn = None
    try:
        conn = sqlite3.connect(db.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, guild_id, sound_filename
            FROM playback_queue
            WHERE played_at IS NULL
            ORDER BY requested_at ASC
        """
        )
        pending_requests = cursor.fetchall()

        if not pending_requests:
            return

        print(f"[Playback Queue] Found {len(pending_requests)} pending requests.")

        for request in pending_requests:
            req_id = request["id"]
            guild_id = request["guild_id"]
            sound_filename = request["sound_filename"]

            print(
                f"[Playback Queue] Processing request ID {req_id}: Play '{sound_filename}' in guild {guild_id}"
            )

            guild = bot.get_guild(guild_id)
            if not guild:
                print(
                    f"[Playback Queue] Error: Bot is not in guild {guild_id}. Skipping request {req_id}."
                )
                cursor.execute(
                    "UPDATE playback_queue SET played_at = ? WHERE id = ?",
                    (datetime.datetime.now(), req_id),
                )
                conn.commit()
                continue

            sound_data = db.get_sound(sound_filename)
            if not sound_data:
                print(
                    f"[Playback Queue] Error: Sound '{sound_filename}' not found in database. Skipping request {req_id}."
                )
                cursor.execute(
                    "UPDATE playback_queue SET played_at = ? WHERE id = ?",
                    (datetime.datetime.now(), req_id),
                )
                conn.commit()
                continue

            sound_folder = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "Sounds")
            )
            sound_path = os.path.join(sound_folder, sound_filename)

            if not os.path.exists(sound_path):
                print(
                    f"[Playback Queue] Error: Sound file not found at '{sound_path}'. Skipping request {req_id}."
                )
                cursor.execute(
                    "UPDATE playback_queue SET played_at = ? WHERE id = ?",
                    (datetime.datetime.now(), req_id),
                )
                conn.commit()
                continue

            try:
                channel = behavior.get_largest_voice_channel(guild)
                if channel is not None:
                    await behavior.play_audio(channel, sound_filename, "webpage")
                    Database().insert_action("admin", "play_sound_periodically", sound_filename)

                cursor.execute(
                    "UPDATE playback_queue SET played_at = ? WHERE id = ?",
                    (datetime.datetime.now(), req_id),
                )
                conn.commit()

                await asyncio.sleep(1)

            except Exception as e:
                print(f"[Playback Queue] Error playing sound for request {req_id}: {e}")
                cursor.execute(
                    "UPDATE playback_queue SET played_at = ? WHERE id = ?",
                    (datetime.datetime.now(), req_id),
                )
                conn.commit()
    except sqlite3.Error as db_err:
        print(f"[Playback Queue] Database error: {db_err}")
    except Exception as e:
        print(f"[Playback Queue] Unexpected error in background task: {e}")
    finally:
        if conn:
            conn.close()


@default_permissions(manage_messages=True)
@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    # Debug: print voice stack versions (opus / sodium) to help diagnose decode errors
    try:
        import discord.opus as _opus
        v = _opus._OpusStruct.get_opus_version()
        print(f"Opus loaded: {_opus.is_loaded()} - version: {v}")
    except Exception as e:
        print(f"Opus not loaded or version unknown: {e}")
    try:
        import nacl, nacl.bindings
        sv = getattr(nacl.bindings, 'sodium_version_string', lambda: b'unknown')()
        print(f"PyNaCl: {getattr(nacl, '__version__', 'unknown')} - libsodium: {sv.decode() if isinstance(sv, (bytes, bytearray)) else sv}")
    except Exception as e:
        print(f"PyNaCl/libsodium check failed: {e}")
    #bot.loop.create_task(behavior.check_if_in_game())
    await behavior.delete_controls_message()
    await behavior.clean_buttons()
    await behavior.send_controls(force=True)
    
    
    bot.loop.create_task(behavior.play_sound_periodically())
    bot.loop.create_task(behavior.update_bot_status())
    bot.loop.create_task(SoundDownloader(behavior, behavior.db, os.getenv("CHROMEDRIVER_PATH")).move_sounds())
    check_playback_queue.start()

    
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
                try:
                    vc = guild.voice_client
                    if vc is not None:
                        print(f"Voice encryption mode: {getattr(vc, 'mode', 'unknown')}")
                except Exception as e:
                    print(f"Could not read voice mode: {e}")
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
    
@bot.slash_command(name='tts', description='Generate TTS with Google or ElevenLabs voices.')
async def tts(ctx, message: Option(str, "What you want to say", required=True), language: Option(str, "Select a voice or language", choices=list(TTS_PROFILES.keys()), required=True)):
    await ctx.respond("Processing your request...", delete_after=0)
    profile = TTS_PROFILES.get(language, TTS_PROFILES["en"])
    flag = profile.get("flag", ":speech_balloon:")
    discord_user = ctx.author if isinstance(ctx.author, (discord.Member, discord.User)) else ctx.user
    user = discord_user

    behavior.color = discord.Color.dark_blue()
    url = profile.get("thumbnail")
    if not url:
        avatar = getattr(discord_user, "display_avatar", None)
        if avatar:
            url = avatar.url
        else:
            url = DEFAULT_TTS_THUMBNAIL

    await behavior.send_message(
        title=f"TTS • {profile.get('display', language.title())} {flag}",
        description=f"'{message}'",
        thumbnail=url
    )
    try:
        if profile.get("provider") == "elevenlabs":
            await behavior.tts_EL(user, message, profile.get("voice", "en"))
        else:
            lang = profile.get("lang", "en")
            region = profile.get("region", "")
            await behavior.tts(user, message, lang, region)
    except Exception as e:
        await behavior.send_message(title=e)
        return
    
@bot.slash_command(name='sts', description='Speech-To-Speech. Press tab and enter to select message and write')
async def tts(ctx, sound: Option(str, "Base sound you want to convert", required=True), char: Option(str, "Voice to convert into", choices=CHARACTER_CHOICES, required=True)):
    await ctx.respond("Processing your request...", delete_after=0)

    discord_user = ctx.author if isinstance(ctx.author, (discord.Member, discord.User)) else ctx.user
    user = discord_user

    behavior.color = discord.Color.dark_blue()
    profile = TTS_PROFILES.get(char, TTS_PROFILES["tyson"])
    url = profile.get("thumbnail")
    if not url:
        avatar = getattr(discord_user, "display_avatar", None)
        if avatar:
            url = avatar.url
        else:
            url = DEFAULT_TTS_THUMBNAIL

    await behavior.send_message(
        title=f"{sound} to {profile.get('display', char.title())}",
        description=f"'{profile.get('display', char.title())}'",
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

@bot.slash_command(name="yearreview", description="Show yearly stats wrapped!")
async def year_review(ctx, 
    user: Option(discord.Member, "User to view (defaults to yourself)", required=False, default=None),
    year: Option(int, "Year to review (defaults to current year)", required=False, default=None)):
    
    # Default to command author if no user specified
    target_user = user if user else ctx.author
    await ctx.respond(f"Generating year review for {target_user.display_name}... 🎉", delete_after=0)
    
    # Default to current year
    import datetime
    if year is None:
        year = datetime.datetime.now().year
    
    # Get the user's stats
    username = target_user.name
    stats = db.get_user_year_stats(username, year)
    
    # Check if user has any activity
    total_activity = (stats['total_plays'] + stats['sounds_favorited'] + 
                      stats['sounds_uploaded'] + stats['tts_messages'] + 
                      stats['voice_joins'] + stats['mute_actions'])
    
    if total_activity == 0:
        await behavior.send_message(
            title=f"📊 {username}'s {year} Review",
            description=f"No activity found for {year}! 😢\nMaybe try a different year?"
        )
        return
    
    # Build the embed description
    lines = []
    
    # Leaderboard rank (if available)
    if stats.get('user_rank') and stats.get('total_users'):
        rank_emoji = "🏆" if stats['user_rank'] == 1 else "🎖️" if stats['user_rank'] <= 3 else "📊"
        lines.append(f"{rank_emoji} **Rank #{stats['user_rank']}** of {stats['total_users']} users")
        lines.append("")
    
    # Sound plays section
    lines.append(f"## 🎵 Sounds Played: **{stats['total_plays']}**")
    if stats['total_plays'] > 0:
        breakdown = []
        if stats['requested_plays'] > 0:
            breakdown.append(f"🎯 Requested: {stats['requested_plays']}")
        if stats['random_plays'] > 0:
            breakdown.append(f"🎲 Random: {stats['random_plays']}")
        if stats['favorite_plays'] > 0:
            breakdown.append(f"⭐ Favorites: {stats['favorite_plays']}")
        if breakdown:
            lines.append("  " + " • ".join(breakdown))
        
        # Unique sounds variety
        if stats.get('unique_sounds', 0) > 0:
            variety_pct = round((stats['unique_sounds'] / stats['total_plays']) * 100)
            lines.append(f"  🎨 Variety: **{stats['unique_sounds']}** unique sounds ({variety_pct}% variety)")
    
    # Top sounds
    if stats['top_sounds']:
        lines.append("")
        lines.append("## 🔥 Your Top Sounds")
        for i, (filename, count) in enumerate(stats['top_sounds'], 1):
            emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i-1]
            clean_name = filename.replace('.mp3', '')
            lines.append(f"{emoji} **{clean_name}** ({count} plays)")
    
    # Fun time stats
    if stats.get('most_active_day') or stats.get('most_active_hour') is not None:
        lines.append("")
        lines.append("## ⏰ When You're Most Active")
        if stats.get('most_active_day'):
            lines.append(f"📅 Favorite day: **{stats['most_active_day']}** ({stats['most_active_day_count']} plays)")
        if stats.get('most_active_hour') is not None:
            hour = stats['most_active_hour']
            hour_str = f"{hour}:00" if hour >= 10 else f"0{hour}:00"
            time_emoji = "🌙" if hour < 6 or hour >= 22 else "🌅" if hour < 12 else "☀️" if hour < 18 else "🌆"
            lines.append(f"{time_emoji} Peak hour: **{hour_str}** ({stats['most_active_hour_count']} plays)")
    
    # First and last sounds
    if stats.get('first_sound') or stats.get('last_sound'):
        lines.append("")
        lines.append("## 📖 Your Sound Journey")
        if stats.get('first_sound'):
            first_name = stats['first_sound'].replace('.mp3', '')
            first_date = stats['first_sound_date'][:10] if stats.get('first_sound_date') else ""
            lines.append(f"🎬 First sound: **{first_name}** ({first_date})")
        if stats.get('last_sound'):
            last_name = stats['last_sound'].replace('.mp3', '')
            last_date = stats['last_sound_date'][:10] if stats.get('last_sound_date') else ""
            lines.append(f"🎞️ Latest sound: **{last_name}** ({last_date})")
    
    # Brain rot section (if any)
    brain_rot = stats.get('brain_rot', {})
    if brain_rot:
        lines.append("")
        lines.append("## 🧠 Brain Rot Activities")
        if brain_rot.get('subway_surfers', 0) > 0:
            lines.append(f"🛹 Subway Surfers: **{brain_rot['subway_surfers']}** times")
        if brain_rot.get('family_guy', 0) > 0:
            lines.append(f"👨‍👩‍👧 Family Guy: **{brain_rot['family_guy']}** times")
        if brain_rot.get('slice_all', 0) > 0:
            lines.append(f"🔪 Slice All: **{brain_rot['slice_all']}** times")
    
    # Voice & Activity Stats section
    has_time_stats = (stats.get('total_voice_hours', 0) > 0 or 
                      stats.get('longest_streak', 0) > 0 or 
                      stats.get('total_active_days', 0) > 0)
    if has_time_stats:
        lines.append("")
        lines.append("## 🎮 Voice & Activity Stats")
        
        if stats.get('total_voice_hours', 0) > 0:
            hours = stats['total_voice_hours']
            if hours >= 24:
                days = round(hours / 24, 1)
                lines.append(f"⏱️ Time in Voice: **{hours}h** ({days} days!)")
            else:
                lines.append(f"⏱️ Time in Voice: **{hours} hours**")
        
        if stats.get('longest_session_minutes', 0) > 0:
            mins = stats['longest_session_minutes']
            if mins >= 60:
                hrs = stats.get('longest_session_hours', 0)
                lines.append(f"🏃 Longest Session: **{hrs}h** ({mins} minutes)")
            else:
                lines.append(f"🏃 Longest Session: **{mins} minutes**")
        
        if stats.get('longest_streak', 0) > 0:
            streak = stats['longest_streak']
            streak_emoji = "🔥" if streak >= 7 else "📆"
            lines.append(f"{streak_emoji} Longest Streak: **{streak} days** in a row!")
        
        if stats.get('total_active_days', 0) > 0:
            lines.append(f"📅 Total Active Days: **{stats['total_active_days']}** days")
    
    # Other stats
    lines.append("")
    lines.append("## 📈 Other Activity")
    
    other_stats = []
    if stats['sounds_favorited'] > 0:
        other_stats.append(f"❤️ Favorited: **{stats['sounds_favorited']}** sounds")
    if stats['sounds_uploaded'] > 0:
        other_stats.append(f"📤 Uploaded: **{stats['sounds_uploaded']}** sounds")
    if stats['tts_messages'] > 0:
        other_stats.append(f"🗣️ TTS Messages: **{stats['tts_messages']}**")
    if stats['voice_joins'] > 0:
        other_stats.append(f"🚪 Voice Joins: **{stats['voice_joins']}**")
    if stats['mute_actions'] > 0:
        other_stats.append(f"🔇 Muted the Bot: **{stats['mute_actions']}** times 😤")
    
    if other_stats:
        lines.extend(other_stats)
    else:
        lines.append("No other activity recorded!")
    
    # Send the embed
    behavior.color = discord.Color.gold()
    await behavior.send_message(
        title=f"🎊 {username}'s {year} Year Review 🎊",
        description="\n".join(lines),
        thumbnail=target_user.display_avatar.url if target_user.display_avatar else None
    )

@bot.slash_command(name="sendyearreview", description="[Admin] Send year review as DM to a user")
async def send_year_review(ctx, 
    user: Option(discord.Member, "User to send the review to", required=True),
    year: Option(int, "Year to review (defaults to current year)", required=False, default=None)):
    
    # Check admin permissions
    if not behavior.is_admin_or_mod(ctx.author):
        await ctx.respond("You don't have permission to use this command.", ephemeral=True)
        return
    
    await ctx.respond(f"Generating year review for {user.display_name}... 📬", ephemeral=True)
    
    # Default to current year
    import datetime
    if year is None:
        year = datetime.datetime.now().year
    
    # Get the user's stats
    target_username = user.name
    stats = db.get_user_year_stats(target_username, year)
    
    # Check if user has any activity
    total_activity = (stats['total_plays'] + stats['sounds_favorited'] + 
                      stats['sounds_uploaded'] + stats['tts_messages'] + 
                      stats['voice_joins'] + stats['mute_actions'])
    
    if total_activity == 0:
        await ctx.followup.send(f"No activity found for {user.display_name} in {year}.", ephemeral=True)
        return
    
    # Build the embed (same as yearreview command)
    lines = []
    
    if stats.get('user_rank') and stats.get('total_users'):
        rank_emoji = "🏆" if stats['user_rank'] == 1 else "🎖️" if stats['user_rank'] <= 3 else "📊"
        lines.append(f"{rank_emoji} **Rank #{stats['user_rank']}** of {stats['total_users']} users")
        lines.append("")
    
    lines.append(f"## 🎵 Sounds Played: **{stats['total_plays']}**")
    if stats['total_plays'] > 0:
        breakdown = []
        if stats['requested_plays'] > 0:
            breakdown.append(f"🎯 Requested: {stats['requested_plays']}")
        if stats['random_plays'] > 0:
            breakdown.append(f"🎲 Random: {stats['random_plays']}")
        if stats['favorite_plays'] > 0:
            breakdown.append(f"⭐ Favorites: {stats['favorite_plays']}")
        if breakdown:
            lines.append("  " + " • ".join(breakdown))
        if stats.get('unique_sounds', 0) > 0:
            variety_pct = round((stats['unique_sounds'] / stats['total_plays']) * 100)
            lines.append(f"  🎨 Variety: **{stats['unique_sounds']}** unique sounds ({variety_pct}% variety)")
    
    if stats['top_sounds']:
        lines.append("")
        lines.append("## 🔥 Your Top Sounds")
        for i, (filename, count) in enumerate(stats['top_sounds'], 1):
            emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i-1]
            clean_name = filename.replace('.mp3', '')
            lines.append(f"{emoji} **{clean_name}** ({count} plays)")
    
    if stats.get('most_active_day') or stats.get('most_active_hour') is not None:
        lines.append("")
        lines.append("## ⏰ When You're Most Active")
        if stats.get('most_active_day'):
            lines.append(f"📅 Favorite day: **{stats['most_active_day']}** ({stats['most_active_day_count']} plays)")
        if stats.get('most_active_hour') is not None:
            hour = stats['most_active_hour']
            hour_str = f"{hour}:00" if hour >= 10 else f"0{hour}:00"
            time_emoji = "🌙" if hour < 6 or hour >= 22 else "🌅" if hour < 12 else "☀️" if hour < 18 else "🌆"
            lines.append(f"{time_emoji} Peak hour: **{hour_str}** ({stats['most_active_hour_count']} plays)")
    
    if stats.get('first_sound') or stats.get('last_sound'):
        lines.append("")
        lines.append("## 📖 Your Sound Journey")
        if stats.get('first_sound'):
            first_name = stats['first_sound'].replace('.mp3', '')
            first_date = stats['first_sound_date'][:10] if stats.get('first_sound_date') else ""
            lines.append(f"🎬 First sound: **{first_name}** ({first_date})")
        if stats.get('last_sound'):
            last_name = stats['last_sound'].replace('.mp3', '')
            last_date = stats['last_sound_date'][:10] if stats.get('last_sound_date') else ""
            lines.append(f"🎞️ Latest sound: **{last_name}** ({last_date})")
    
    has_time_stats = (stats.get('total_voice_hours', 0) > 0 or 
                      stats.get('longest_streak', 0) > 0 or 
                      stats.get('total_active_days', 0) > 0)
    if has_time_stats:
        lines.append("")
        lines.append("## 🎮 Voice & Activity Stats")
        if stats.get('total_voice_hours', 0) > 0:
            hours = stats['total_voice_hours']
            if hours >= 24:
                days = round(hours / 24, 1)
                lines.append(f"⏱️ Time in Voice: **{hours}h** ({days} days!)")
            else:
                lines.append(f"⏱️ Time in Voice: **{hours} hours**")
        if stats.get('longest_session_minutes', 0) > 0:
            mins = stats['longest_session_minutes']
            if mins >= 60:
                hrs = stats.get('longest_session_hours', 0)
                lines.append(f"🏃 Longest Session: **{hrs}h** ({mins} minutes)")
            else:
                lines.append(f"🏃 Longest Session: **{mins} minutes**")
        if stats.get('longest_streak', 0) > 0:
            streak = stats['longest_streak']
            streak_emoji = "🔥" if streak >= 7 else "📆"
            lines.append(f"{streak_emoji} Longest Streak: **{streak} days** in a row!")
        if stats.get('total_active_days', 0) > 0:
            lines.append(f"📅 Total Active Days: **{stats['total_active_days']}** days")
    
    # Create the embed
    embed = discord.Embed(
        title=f"🎊 {target_username}'s {year} Year Review 🎊",
        description="\n".join(lines),
        color=discord.Color.gold()
    )
    if user.display_avatar:
        embed.set_thumbnail(url=user.display_avatar.url)
    
    # Send as DM
    try:
        await user.send(embed=embed)
        await ctx.followup.send(f"✅ Year review sent to {user.display_name} via DM!", ephemeral=True)
    except discord.Forbidden:
        await ctx.followup.send(f"❌ Could not send DM to {user.display_name}. They may have DMs disabled.", ephemeral=True)
    except Exception as e:
        await ctx.followup.send(f"❌ Error sending DM: {e}", ephemeral=True)



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

    # Handle AFK channel joins
    if event == "join" and channel and channel == channel.guild.afk_channel:
        if before.channel:
            # Treat moving to AFK as leaving the previous channel
            print(
                f"User {member_str} moved to AFK channel {channel}; treating as leave from {before.channel}"
            )
            event = "leave"
            channel = before.channel
        else:
            # Ignore when directly joining the AFK channel
            print(f"Ignoring join event for {member_str} in AFK channel {channel}")
            return
        
    # Log the voice state update
    print(f"Voice state update: {member_str} {event} channel {channel}")

    await play_audio_for_event(member, member_str, event, channel)

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
                await behavior.play_audio(channel, db.get_sounds_by_similarity(sound)[0][1], member_str)
                db.insert_action(member_str, event, db.get_sounds_by_similarity(sound)[0][0])
        elif event == "join":
            await behavior.play_audio(channel, "gay-echo.mp3", "admin")
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
            r')(?=\s|$)'                                       # Positive lookahead for space or end of string (instead of word boundary)
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
                remaining_content = message.content[match.end():].strip()
                time_limit = None
                custom_filename = None

                if remaining_content:
                    # Split the remaining content into parts
                    parts = remaining_content.split(maxsplit=1)
                    
                    # Check if first part is a number (time limit)
                    if len(parts) > 0 and parts[0].isdigit():
                        time_limit = int(parts[0])
                        # If there's more content after the time limit, it's the filename
                        if len(parts) > 1:
                            custom_filename = parts[1].strip()
                    else:
                        # No time limit, everything is the filename
                        custom_filename = remaining_content.strip()

                # Sanitize the custom filename
                if custom_filename:
                    # Remove leading slashes and whitespace
                    custom_filename = custom_filename.lstrip('/ \t')
                    # If stripping leaves an empty string, set to None
                    if not custom_filename:
                        custom_filename = None

                file_path = await behavior.save_sound_from_video(url, custom_filename=custom_filename, time_limit=time_limit)
                if file_path:
                    await processing_msg.edit(content="Check botchannel for your new sound!")

            except ValueError as ve: # Catch specific yt-dlp errors (like duration limit)
                 await processing_msg.edit(content=f"Error: {ve}")
            except Exception as e:
                print(f"Error processing video link in DM: {e}")
                await processing_msg.edit(content="Sorry, an error occurred while processing the video. " + str(e)) # Keep str(e)
            # Note: Don't clean up the file here - SoundDownloader will handle moving it to the Sounds folder

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

@bot.slash_command(name="lastlogs", description="Show the last service logs")
async def last_logs(ctx, lines: Option(int, "Number of log lines", required=False, default=10), service: Option(str, "Service name (optional)", required=False)):
    await ctx.respond("Fetching service logs...", delete_after=0)
    
    logs = get_service_logs(lines, service)
    if not logs:
        await ctx.followup.send("No log entries found or unable to access logs.", ephemeral=True)
        return
    
    formatted = "\n".join(logs)
    if len(formatted) > 1900:
        formatted = formatted[-1900:]
    await ctx.followup.send(f"```{formatted}```", ephemeral=True)

@bot.slash_command(name="commands", description="Show recent bot commands from the log")
async def show_commands(ctx, count: Option(int, "Number of entries", required=False, default=10)):
    await ctx.respond("Fetching logs...", delete_after=0)
    lines = tail_command_logs(count)

    if not lines:
        await ctx.followup.send("No command logs found or log file unavailable.", ephemeral=True)
        return

    formatted = "\n".join(lines)
    if len(formatted) > 1900:
        formatted = formatted[-1900:]
    await ctx.followup.send(f"```{formatted}```", ephemeral=True)

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

@bot.slash_command(name="backup", description="Backup Discord-Brain-Rot project to USB drive (Admin only)")
async def backup_command(ctx):
    """Backup the entire Discord-Brain-Rot project to USB drive with logging."""
    # Check for admin permissions
    if not behavior.is_admin_or_mod(ctx.author):
        await ctx.respond("You don't have permission to use this command.", ephemeral=True)
        return

    await ctx.respond("🔄 Starting backup process...", ephemeral=False)
    print(f"Backup initiated by {ctx.author.name} ({ctx.author.id})")

    try:
        # Step 1: Check if USB drive is mounted
        usb_path = "/media/usb"
        backup_dir = "/media/usb/brainrotbup"
        source_dir = "/home/gabi/github/Discord-Brain-Rot"

        print(f"DEBUG: USB path: {usb_path}")
        print(f"DEBUG: Backup dir: {backup_dir}")
        print(f"DEBUG: Source dir: {source_dir}")

        # Create empty directory for rsync method if it doesn't exist
        empty_dir = "/tmp/empty_dir"
        if not os.path.exists(empty_dir):
            os.makedirs(empty_dir, exist_ok=True)
            print(f"DEBUG: Created empty dir: {empty_dir}")

        print("DEBUG: Starting Step 1 - USB drive check")
        await behavior.send_message(
            title="📋 Backup Step 1",
            description="Checking USB drive connection...",
            delete_time=5
        )

        if not os.path.exists(usb_path):
            print("DEBUG: USB path does not exist!")
            await behavior.send_message(
                title="❌ Backup Failed",
                description="USB drive not found at /media/usb. Please ensure the USB drive is connected and mounted.",
                delete_time=10
            )
            return

        print("DEBUG: USB path exists, proceeding to Step 2")
        await behavior.send_message(
            title="✅ Step 1 Complete",
            description="USB drive is connected and mounted.",
            delete_time=5
        )

        # Step 2: Clean the backup directory
        print("DEBUG: Starting Step 2 - Directory cleanup")
        await behavior.send_message(
            title="🧹 Backup Step 2",
            description="Cleaning existing backup directory...",
            delete_time=5
        )

        if os.path.exists(backup_dir):
            print(f"DEBUG: Backup directory exists: {backup_dir}")
            try:
                # Show directory size before cleanup
                print("DEBUG: Checking directory size")
                await behavior.send_message(
                    title="📊 Directory Size Check",
                    description="Checking backup directory size...",
                    delete_time=5
                )
                size_result = subprocess.run(['sudo', 'du', '-sh', backup_dir], capture_output=True, text=True, timeout=30)
                print(f"DEBUG: Size check result - Return code: {size_result.returncode}")
                print(f"DEBUG: Size check stdout: {size_result.stdout}")
                print(f"DEBUG: Size check stderr: {size_result.stderr}")
                if size_result.returncode == 0 and size_result.stdout.strip():
                    dir_size = size_result.stdout.split()[0]
                    print(f"DEBUG: Directory size: {dir_size}")
                    await behavior.send_message(
                        title="📊 Directory Size",
                        description=f"Backup directory size: {dir_size} - This may take a while to remove...",
                        delete_time=10
                    )
                else:
                    print("DEBUG: Size check failed or empty output")
                    await behavior.send_message(
                        title="⚠️ Size Check Warning",
                        description="Could not determine directory size, proceeding with cleanup...",
                        delete_time=5
                    )
            except subprocess.TimeoutExpired:
                print("DEBUG: Size check timed out")
                await behavior.send_message(
                    title="⚠️ Size Check Timeout",
                    description="Size check timed out, proceeding with cleanup...",
                    delete_time=5
                )
            except Exception as e:
                print(f"DEBUG: Size check error: {str(e)}")
                await behavior.send_message(
                    title="⚠️ Size Check Error",
                    description=f"Size check failed: {str(e)}, proceeding with cleanup...",
                    delete_time=5
                )

            # Try normal removal first with timeout
            try:
                print("DEBUG: Starting primary cleanup method (rm -rfv)")
                await behavior.send_message(
                    title="🧹 Step 2 Progress",
                    description="Starting directory cleanup (timeout: 5 minutes)...",
                    delete_time=10
                )

                # First check if we can list the directory contents
                print("DEBUG: Checking directory access with ls -la")
                ls_result = subprocess.run(['sudo', 'ls', '-la', backup_dir], capture_output=True, text=True, timeout=30)
                print(f"DEBUG: ls result - Return code: {ls_result.returncode}")
                print(f"DEBUG: ls stdout: {ls_result.stdout}")
                print(f"DEBUG: ls stderr: {ls_result.stderr}")
                if ls_result.returncode != 0:
                    print("DEBUG: Directory access failed")
                    await behavior.send_message(
                        title="⚠️ Directory Access Warning",
                        description="Cannot access directory contents. It may be corrupted or have permission issues.",
                        delete_time=10
                    )

                print("DEBUG: Executing rm -rfv command")
                clean_result = subprocess.run(['sudo', 'rm', '-rfv', backup_dir], capture_output=True, text=True, timeout=300)
                print(f"DEBUG: rm result - Return code: {clean_result.returncode}")
                print(f"DEBUG: rm stdout length: {len(clean_result.stdout) if clean_result.stdout else 0}")
                print(f"DEBUG: rm stderr length: {len(clean_result.stderr) if clean_result.stderr else 0}")
                if clean_result.returncode == 0:
                    await behavior.send_message(
                        title="✅ Step 2 Complete",
                        description="Old backup directory cleaned successfully.",
                        delete_time=5
                    )
                else:
                    # Check if directory still exists after the rm command
                    if not os.path.exists(backup_dir):
                        print("DEBUG: Directory successfully removed despite non-zero exit code")
                        await behavior.send_message(
                            title="✅ Step 2 Complete",
                            description="Old backup directory cleaned (some warnings but successful).",
                            delete_time=5
                        )
                    else:
                        # Directory still exists, but some files may have been removed
                        # Let's check what's left and decide whether to continue or fail
                        print("DEBUG: Directory still exists after rm command")

                        # Get directory size to see if most files were removed
                        try:
                            size_check = subprocess.run(['sudo', 'du', '-sb', backup_dir], capture_output=True, text=True, timeout=30)
                            if size_check.returncode == 0:
                                remaining_size = int(size_check.stdout.split()[0])
                                print(f"DEBUG: Remaining directory size: {remaining_size} bytes")

                                # If less than 100MB remains, consider it mostly cleaned
                                if remaining_size < 100000000:  # 100MB
                                    print("DEBUG: Most files removed, continuing with backup")
                                    await behavior.send_message(
                                        title="⚠️ Partial Cleanup",
                                        description=f"Most files cleaned, but {remaining_size/1000000:.1f}MB remains. Continuing with backup...",
                                        delete_time=10
                                    )
                                    # Continue to Step 3 (create directory)
                                else:
                                    # Too much data remains, try alternative methods
                                    print("DEBUG: Too much data remains, trying alternative cleanup")
                                    raise subprocess.CalledProcessError(clean_result.returncode, clean_result.args, "Too much data remains after cleanup")
                            else:
                                raise subprocess.CalledProcessError(clean_result.returncode, clean_result.args, "Could not determine remaining size")
                        except subprocess.TimeoutExpired:
                            print("DEBUG: Size check timed out, assuming partial cleanup")
                            await behavior.send_message(
                                title="⚠️ Cleanup Check Timeout",
                                description="Could not verify cleanup progress. Continuing with backup...",
                                delete_time=10
                            )
                            # Continue to Step 3
            except subprocess.TimeoutExpired:
                # If normal removal times out, try alternative methods
                print("DEBUG: Primary cleanup timed out, trying alternative methods")
                await behavior.send_message(
                    title="⚠️ Step 2 Timeout",
                    description="Normal cleanup timed out, trying alternative methods...",
                    delete_time=10
                )

                # Method 1: Try find -delete (good for large directories)
                try:
                    print("DEBUG: Starting alternative method 1 (find -delete)")
                    await behavior.send_message(
                        title="🔄 Alternative Method 1",
                        description="Trying find -delete approach...",
                        delete_time=5
                    )
                    alt_clean = subprocess.run(['sudo', 'find', backup_dir, '-delete'], capture_output=True, text=True, timeout=240)
                    print(f"DEBUG: find -delete result - Return code: {alt_clean.returncode}")
                    print(f"DEBUG: find -delete stdout length: {len(alt_clean.stdout) if alt_clean.stdout else 0}")
                    print(f"DEBUG: find -delete stderr length: {len(alt_clean.stderr) if alt_clean.stderr else 0}")
                    if alt_clean.returncode == 0:
                        # Check if directory still exists and remove if empty
                        if os.path.exists(backup_dir):
                            rmdir_result = subprocess.run(['sudo', 'rmdir', backup_dir], capture_output=True, text=True, timeout=30)
                            if rmdir_result.returncode != 0:
                                await behavior.send_message(
                                    title="⚠️ Directory Not Empty",
                                    description="Files removed but directory not empty. This is normal.",
                                    delete_time=10
                                )
                        await behavior.send_message(
                            title="✅ Step 2 Complete",
                            description="Old backup directory cleaned using find -delete method.",
                            delete_time=5
                        )
                        return  # Success, exit the cleanup section
                    else:
                        error_msg = alt_clean.stderr.strip() if alt_clean.stderr else "Find command failed"
                        await behavior.send_message(
                            title="⚠️ Method 1 Failed",
                            description=f"Find -delete failed: {error_msg}",
                            delete_time=10
                        )
                except subprocess.TimeoutExpired:
                    await behavior.send_message(
                        title="⚠️ Method 1 Timeout",
                        description="Find -delete also timed out, trying method 2...",
                        delete_time=10
                    )
                except Exception as e:
                    await behavior.send_message(
                        title="⚠️ Method 1 Failed",
                        description=f"Find -delete failed: {str(e)}",
                        delete_time=10
                    )

                # Method 2: Try rsync with delete (sometimes more reliable)
                try:
                    await behavior.send_message(
                        title="🔄 Alternative Method 2",
                        description="Trying rsync delete approach...",
                        delete_time=5
                    )
                    rsync_clean = subprocess.run(['sudo', 'rsync', '-a', '--delete', '/tmp/empty_dir/', backup_dir], capture_output=True, text=True, timeout=180)
                    if rsync_clean.returncode == 0:
                        await behavior.send_message(
                            title="✅ Step 2 Complete",
                            description="Old backup directory cleaned using rsync method.",
                            delete_time=5
                        )
                        return  # Success
                    else:
                        await behavior.send_message(
                            title="⚠️ Method 2 Failed",
                            description=f"Rsync method failed (exit code: {rsync_clean.returncode})",
                            delete_time=10
                        )
                except subprocess.TimeoutExpired:
                    await behavior.send_message(
                        title="❌ All Methods Failed",
                        description="All cleanup methods timed out. The directory may be too large or have filesystem issues.",
                        delete_time=15
                    )
                    return
                except Exception as e:
                    await behavior.send_message(
                        title="⚠️ Method 2 Failed",
                        description=f"Rsync method failed: {str(e)}",
                        delete_time=10
                    )

                # Method 3: Try chmod + rm as final attempt
                try:
                    print("DEBUG: Starting final method (chmod + rm)")
                    await behavior.send_message(
                        title="🔄 Final Method",
                        description="Trying chmod + rm approach for stubborn files...",
                        delete_time=5
                    )

                    # First try to change permissions on all files
                    chmod_result = subprocess.run(['sudo', 'chmod', '-R', '777', backup_dir], capture_output=True, text=True, timeout=60)
                    print(f"DEBUG: chmod result - Return code: {chmod_result.returncode}")

                    # Then try to remove again
                    final_rm = subprocess.run(['sudo', 'rm', '-rf', backup_dir], capture_output=True, text=True, timeout=180)
                    print(f"DEBUG: final rm result - Return code: {final_rm.returncode}")

                    if final_rm.returncode == 0 or not os.path.exists(backup_dir):
                        await behavior.send_message(
                            title="✅ Step 2 Complete",
                            description="Old backup directory cleaned using final method.",
                            delete_time=5
                        )
                        return  # Success, exit the cleanup section
                    else:
                        await behavior.send_message(
                            title="❌ All Cleanup Methods Failed",
                            description="Could not clean backup directory. Please manually remove /media/usb/brainrotbup and try again.",
                            delete_time=20
                        )
                        return  # Give up
                except Exception as e:
                    await behavior.send_message(
                        title="❌ Final Method Failed",
                        description=f"Final cleanup attempt failed: {str(e)}",
                        delete_time=10
                    )

                # Final failure
                await behavior.send_message(
                    title="❌ Step 2 Failed",
                    description="All cleanup methods failed. You may need to manually remove the directory.",
                    delete_time=15
                )
                return
            except subprocess.CalledProcessError as e:
                error_msg = e.stderr if e.stderr else "Unknown error"
                await behavior.send_message(
                    title="❌ Step 2 Failed",
                    description=f"Failed to clean directory: {error_msg}",
                    delete_time=10
                )
                return
        else:
            await behavior.send_message(
                title="ℹ️ Step 2 Skipped",
                description="No existing backup directory found.",
                delete_time=5
            )

        # Step 3: Create backup directory
        await behavior.send_message(
            title="📁 Backup Step 3",
            description="Creating backup directory...",
            delete_time=5
        )

        mkdir_result = subprocess.run(['sudo', 'mkdir', '-p', backup_dir], capture_output=True, text=True)
        if mkdir_result.returncode == 0:
            await behavior.send_message(
                title="✅ Step 3 Complete",
                description="Backup directory created successfully.",
                delete_time=5
            )
        else:
            await behavior.send_message(
                title="❌ Step 3 Failed",
                description=f"Failed to create directory: {mkdir_result.stderr}",
                delete_time=10
            )
            return

        # Step 4: Copy files with progress logging
        await behavior.send_message(
            title="📂 Backup Step 4",
            description="Copying Discord-Brain-Rot project files... This may take a while.",
            delete_time=10
        )

        # Get source directory size for progress estimation
        size_result = subprocess.run(['du', '-sh', source_dir], capture_output=True, text=True)
        if size_result.returncode == 0:
            source_size = size_result.stdout.split()[0]
            await behavior.send_message(
                title="📊 Backup Info",
                description=f"Source directory size: {source_size}",
                delete_time=5
            )

        # Perform the copy operation using rsync (better for special characters and large files)
        print("DEBUG: Starting file copy with rsync")
        await behavior.send_message(
            title="📂 Step 4 Progress",
            description="Copying files using rsync (better for special characters and large files)...",
            delete_time=10
        )

        # Use rsync instead of cp - it's better for:
        # - Special characters in filenames
        # - Large files
        # - Resuming interrupted transfers
        # - Excluding problematic files
        rsync_cmd = [
            'sudo', 'rsync', '-av',
            '--ignore-existing',  # Skip files that already exist
            '--safe-links',       # Ignore symlinks that point outside the tree
            '--copy-links',       # Copy symlinks as regular files
            '--exclude=.git',
            '--exclude=__pycache__',
            '--exclude=*.pyc',
            '--exclude=venv',     # Exclude Python virtual environment
            '--exclude=actions-runner',  # Exclude GitHub actions runner
            '--exclude=temp_audio',      # Exclude temporary audio files
            '--exclude=.DS_Store',       # Exclude macOS system files
            '--exclude=Thumbs.db',       # Exclude Windows system files
            source_dir + '/',
            os.path.join(backup_dir, "Discord-Brain-Rot")
        ]

        print(f"DEBUG: Running rsync command: {' '.join(rsync_cmd)}")
        await behavior.send_message(
            title="📂 Copy Progress",
            description="Starting file copy (this may take several minutes for large backups)...",
            delete_time=30
        )
        copy_result = subprocess.run(rsync_cmd, capture_output=True, text=True, timeout=1800)  # 30 minute timeout

        print(f"DEBUG: rsync result - Return code: {copy_result.returncode}")
        print(f"DEBUG: rsync stdout length: {len(copy_result.stdout) if copy_result.stdout else 0}")
        print(f"DEBUG: rsync stderr length: {len(copy_result.stderr) if copy_result.stderr else 0}")

        if copy_result.returncode != 0:
            # Check if it's a partial success (rsync returns 23 for some files failing but others succeeding)
            if copy_result.returncode == 23:
                print("DEBUG: rsync completed with some files skipped (exit code 23) - this is usually OK")
                await behavior.send_message(
                    title="⚠️ Copy Completed with Warnings",
                    description="Some files had issues (special characters, symlinks) but most were copied successfully.",
                    delete_time=15
                )
            else:
                error_msg = copy_result.stderr.strip() if copy_result.stderr else "Unknown copy error"
                print(f"DEBUG: Copy failed with error: {error_msg}")
                await behavior.send_message(
                    title="❌ Copy Failed",
                    description=f"Failed to copy files: {error_msg[:500]}",
                    delete_time=15
                )
                return

        # Step 5: Verify backup
        await behavior.send_message(
            title="🔍 Backup Step 5",
            description="Verifying backup integrity...",
            delete_time=5
        )

        if os.path.exists(os.path.join(backup_dir, "Discord-Brain-Rot")):
            # Get backup size
            backup_size_result = subprocess.run(['du', '-sh', backup_dir], capture_output=True, text=True)
            if backup_size_result.returncode == 0:
                backup_size = backup_size_result.stdout.split()[0]
                await behavior.send_message(
                    title="✅ Backup Complete",
                    description=f"Backup created successfully!\n📦 Backup size: {backup_size}\n📍 Location: {backup_dir}",
                    delete_time=15
                )
            else:
                await behavior.send_message(
                    title="✅ Backup Complete",
                    description=f"Backup created successfully!\n📍 Location: {backup_dir}",
                    delete_time=10
                )
        else:
            raise Exception("Backup verification failed - directory not found")

        print("Backup completed successfully")

    except Exception as e:
        await behavior.send_message(
            title="❌ Backup Failed",
            description=f"Backup failed with error: {e}",
            delete_time=15
        )
        print(f"Error during backup: {e}")

bot.run_bot()
