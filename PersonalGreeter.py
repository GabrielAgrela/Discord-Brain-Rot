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
import random
import time

env = Environment()
intents = discord.Intents(guilds=True, voice_states=True, messages=True, message_content=True, members=True)
bot = Bot(command_prefix="*", intents=intents, token=env.bot_token, ffmpeg_path=env.ffmpeg_path)

# Usage
#userUtils = UsersUtils(os.path.abspath(os.path.join(os.path.dirname(__file__), "Data", "Users.json")))

behavior = BotBehavior(bot, env.ffmpeg_path)
db = Database(behavior=behavior)
file_name = 'play_requests.csv'

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
            return [list_name for _, list_name, _, _ in all_lists][:25]
        
        # Filter lists based on input
        matching_lists = []
        for list_id, list_name, creator, created_at in all_lists:
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
    "request_number",
    description="Number of Similar Sounds",
    default="5"
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
async def play_requested(ctx, message: str, request_number: str = "5", speed: float = 1.0, volume: float = 1.0, reverse: bool = False):
    await ctx.respond("Processing your request...", delete_after=0)

    # --- Input Validation/Clamping ---
    try:
        request_number = int(request_number)
        if not 1 <= request_number <= 25:
            await ctx.followup.send("Request number must be between 1 and 25.", ephemeral=True, delete_after=5)
            return
    except ValueError:
        await ctx.followup.send("Invalid request number. Please enter a whole number.", ephemeral=True, delete_after=5)
        return

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
            await behavior.play_request(message, author.name, request_number=request_number, effects=effects)
    except Exception as e:
        print(f"Error in play_requested: {e}")
        # Fallback to random sound without effects on error? Or just report error?
        # Let's just report the error for now.
        await ctx.followup.send(f"An error occurred while trying to play '{message}'. Please try again later.", ephemeral=True, delete_after=10)
        # asyncio.run_coroutine_threadsafe(behavior.play_random_sound(username_with_discriminator), bot.loop) # Optional fallback
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

bot.run_bot()
