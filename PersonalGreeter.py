from bot.logger import setup_logging
setup_logging()

import asyncio
import os
import subprocess
import discord
from discord.ext import tasks
import sqlite3
import datetime
from bot.environment import Environment
from bot.core import Bot
from bot.behavior import BotBehavior
from discord.commands import Option
from discord import default_permissions
from bot.database import Database
from bot.downloaders.sound import SoundDownloader
from bot.commands.sound import SoundCog
from bot.commands.tts import TTSCog
from bot.commands.admin import AdminCog
from bot.commands.lists import ListCog
from bot.commands.events import EventCog
from bot.commands.stats import StatsCog
from bot.commands.keywords import KeywordCog
from bot.commands.debug import DebugCog
from bot.commands.onthisday import OnThisDayCog
import random
import time
from collections import defaultdict

# Debounce tracking for voice state updates
_voice_event_debounce: dict = {}  # member_id -> asyncio.Task
VOICE_DEBOUNCE_SECONDS = 0.5  # Debounce rapid channel switches

import platform # Added for OS detection
import re # Add import for regex
import ctypes.util
import discord.opus

env = Environment()
intents = discord.Intents(guilds=True, voice_states=True, messages=True, message_content=True, members=True)
bot = Bot(command_prefix="*", intents=intents, token=env.bot_token, ffmpeg_path=env.ffmpeg_path)




behavior = BotBehavior(bot, env.ffmpeg_path)

# Load Cogs
bot.add_cog(SoundCog(bot, behavior))
bot.add_cog(TTSCog(bot, behavior))
bot.add_cog(AdminCog(bot, behavior))
bot.add_cog(ListCog(bot, behavior))
bot.add_cog(EventCog(bot, behavior))
bot.add_cog(StatsCog(bot, behavior))
bot.add_cog(KeywordCog(bot, behavior))
bot.add_cog(DebugCog(bot, behavior))
bot.add_cog(OnThisDayCog(bot, behavior))
db = Database(behavior=behavior)


# --- Background Task to Handle Web Playback Requests ---
@tasks.loop(seconds=5.0)
async def check_playback_queue():
    """Process queued playback requests from the web interface."""
    # Use the shared database connection to avoid "database is locked"
    # The commands are executed, but commit is handled carefully or rely on autocommit if set
    # Using the shared connection means we need to be careful about threading if this task runs in a diff thread
    # discord.py tasks run in the main event loop, so it is safe to use the same sqlite3 connection
    try:
        # We can actully just use db.cursor directly since we are on the same thread
        cursor = db.cursor
        
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
            # Results are tuples: (id, guild_id, sound_filename)
            req_id = request[0]
            guild_id = request[1]
            sound_filename = request[2]

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
                db.conn.commit()
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
                db.conn.commit()
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
                db.conn.commit()
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
                db.conn.commit()

                await asyncio.sleep(1)

            except Exception as e:
                print(f"[Playback Queue] Error playing sound for request {req_id}: {e}")
                cursor.execute(
                    "UPDATE playback_queue SET played_at = ? WHERE id = ?",
                    (datetime.datetime.now(), req_id),
                )
                db.conn.commit()
    except sqlite3.Error as db_err:
        print(f"[Playback Queue] Database error: {db_err}")
    except Exception as e:
        print(f"[Playback Queue] Unexpected error in background task: {e}")


@default_permissions(manage_messages=True)
@bot.event
async def on_ready():
    # --- Load Opus library ---
    if not discord.opus.is_loaded():
        opus_path = ctypes.util.find_library('opus')
        if opus_path:
            try:
                discord.opus.load_opus(opus_path)
                print(f"Successfully loaded Opus library from {opus_path}")
            except Exception as e:
                print(f"Failed to load Opus library: {e}")
        else:
            print("Warning: Opus library not found in the system.")

    print(f"We have logged in as {bot.user}")
    #bot.loop.create_task(behavior.check_if_in_game())
    await behavior.delete_controls_message()
    await behavior.clean_buttons()
    await behavior.send_controls(force=True)
    
    # Background tasks are handled by BackgroundService (started automatically in BotBehavior)
    bot.loop.create_task(SoundDownloader(behavior, behavior.db, os.getenv("CHROMEDRIVER_PATH")).move_sounds())
    check_playback_queue.start()


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
                
                # Play startup sound FIRST before starting keyword detection
                if not bot.startup_sound_played:
                    try:
                        from bot.repositories import SoundRepository
                        random_sound = SoundRepository().get_random_sounds(num_sounds=1)[0][2]
                        await behavior.play_audio(channel_to_join, random_sound, "startup")
                        # Wait for sound to start playing
                        await asyncio.sleep(3)
                    except Exception as e:
                        print(f"Error playing startup sound: {e}")
                    bot.startup_sound_played = True
                
                # Start keyword detection AFTER startup sound
                try:
                    await behavior._audio_service.start_keyword_detection(guild)
                except Exception as e:
                    print(f"Could not start keyword detection: {e}")
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
    
    # Check if bot should disconnect when someone leaves
    if event == "leave" and before.channel:
        # Check if the bot is in the channel the user left
        voice_client = before.channel.guild.voice_client
        if voice_client and voice_client.channel == before.channel:
            # Check if only bots remain in the channel
            non_bot_members = [m for m in before.channel.members if not m.bot]
            if len(non_bot_members) == 0:
                print(f"[AutoDisconnect] No non-bot members left in {before.channel.name}, disconnecting...")
                try:
                    # Stop keyword detection before disconnecting
                    await behavior._audio_service.stop_keyword_detection(before.channel.guild)
                    await voice_client.disconnect()
                    print(f"[AutoDisconnect] Disconnected from {before.channel.name}")
                except Exception as e:
                    print(f"[AutoDisconnect] Error disconnecting: {e}")
                return  # No need to play leave sound if disconnecting
        
    # Log the voice state update
    print(f"Voice state update: {member_str} {event} channel ► {channel}")

    # Debounce: Cancel any pending event for this member and schedule new one
    member_id = member.id
    if member_id in _voice_event_debounce:
        pending_task = _voice_event_debounce[member_id]
        if not pending_task.done():
            print(f"[Debounce] Cancelling pending event for {member_str}")
            pending_task.cancel()
            try:
                await pending_task
            except asyncio.CancelledError:
                pass
    
    async def debounced_play():
        try:
            await asyncio.sleep(VOICE_DEBOUNCE_SECONDS)
            await play_audio_for_event(member, member_str, event, channel)
        except asyncio.CancelledError:
            print(f"[Debounce] Event cancelled for {member_str} (rapid channel switch)")
        finally:
            if member_id in _voice_event_debounce:
                del _voice_event_debounce[member_id]
    
    _voice_event_debounce[member_id] = asyncio.create_task(debounced_play())

async def play_audio_for_event(member, member_str, event, channel):
    try:
        user_events = db.get_user_events(member_str, event)
        if user_events:
            if await behavior.is_channel_empty(channel):
                return
            sound_name = random.choice(user_events)[2]
            behavior.last_channel[member_str] = channel
            if channel:
                print(f"Playing {sound_name} for {member_str} on {event}")
                # Get sound info only once
                similar_sounds = db.get_sounds_by_similarity(sound_name, 1)
                if similar_sounds:
                    sound_row = similar_sounds[0][0] # (row, score) -> row
                    filename = sound_row[2]
                    sound_id = sound_row[0]
                    await behavior.play_audio(channel, filename, member_str)
                    db.insert_action(member_str, event, sound_id)
                else:
                    print(f"Sound {sound_name} not found for user event")
                    
        elif event == "join":
            await behavior.play_audio(channel, "gay-echo.mp3", "admin")
            # Log action for default join sound
            similar_sounds = db.get_sounds_by_similarity("gay-echo.mp3", 1)
            if similar_sounds:
                 db.insert_action(member_str, event, similar_sounds[0][0][0])
            else:
                 # Fallback if gay-echo not found in DB but exists on disk?
                 db.insert_action(member_str, event, "gay-echo.mp3")

        elif event == "leave":
            db.insert_action(member_str, event, "-")
            await behavior.is_channel_empty(channel)
    except Exception as e:
        print(f"An error occurred in play_audio_for_event: {e}")

# Add an event handler for bot shutdown
@bot.event
async def on_close():
    print("Bot is closing, cleaning up resources...")

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






bot.run_bot()
