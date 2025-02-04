import asyncio
from datetime import datetime
import time
import discord
import random
from mutagen.mp3 import MP3

from requests import HTTPError
from Classes.SoundDownloader import SoundDownloader
import os
from Classes.AudioDatabase import AudioDatabase
from Classes.PlayHistoryDatabase import PlayHistoryDatabase
from Classes.OtherActionsDatabase import OtherActionsDatabase
from Classes.TTS import TTS
import csv
from Classes.UI import SoundBeingPlayedView, ControlsView, SoundView
from Classes.ManualSoundDownloader import ManualSoundDownloader
from moviepy.editor import VideoFileClip

import aiohttp
import re
from Classes.LoLDatabase import LoLDatabase
from Classes.LoL import RiotAPI

from Classes.Database import Database



class BotBehavior:
    def __init__(self, bot, ffmpeg_path):
        self.bot = bot
        self.ffmpeg_path = ffmpeg_path
        self.last_channel = {}
        self.playback_done = asyncio.Event()
        self.script_dir = os.path.dirname(__file__)  # Get the directory of the current script
        self.db_path = os.path.join(self.script_dir, "../Data/soundsDB.csv")
        self.ph_path = os.path.join(self.script_dir, "../Data/play_history.csv")
        self.oa_path = os.path.join(self.script_dir, "../Data/other_actions.csv")
        self.users_json = os.path.join(self.script_dir, "../Data/Users.json")
        self.dwdir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Downloads"))
        self.db = AudioDatabase(self.db_path, self)
        self.lol_db = LoLDatabase()
        self.player_history_db = PlayHistoryDatabase(self.ph_path,self.db,self.users_json, self.bot, self)
        self.other_actions_db = OtherActionsDatabase(self.oa_path, self)
        self.TTS = TTS(self,bot)
        self.ManualSoundDownloader = ManualSoundDownloader()
        self.riotAPI = RiotAPI(os.getenv("RIOT_API_KEY"), db=self.lol_db, bot=self)
        self.view = None
        self.embed = None
        self.controls_message = None
        self.color = discord.Color.red()
        self.upload_lock = asyncio.Lock()
        # self.lastInteractionDateTime = current
        self.lastInteractionDateTime = datetime.now()
        self.last_played_time = None
        self.cooldown_message = None
        self.error_message = None
        self.checking_voice_connection = False

    async def display_top_users(self, user, number=5, days=7, by="plays"):
        Database().insert_action(user.name, "list_top_users", by)
        top_users = Database().get_top_users(number, days, by)
        
        bot_channel = await self.get_bot_channel()
        
        total_plays = sum(count for _, count in top_users)

        messages = []
        for rank, (username, total_plays) in enumerate(top_users, 1):
            embed = discord.Embed(
                title=f"🔊 **#{rank} {username.upper()}**",
                description=f"🎵 **Total Sounds Played: {total_plays}**",
                color=discord.Color.green()
            )

            # Attempt to get user avatar, set a default if unavailable
            discord_user = discord.utils.get(self.bot.get_all_members(), name=username)
            if discord_user and discord_user.avatar:
                embed.set_thumbnail(url=discord_user.avatar.url)
            elif username == "syzoo":
                embed.set_thumbnail(url="https://media.npr.org/assets/img/2017/09/12/macaca_nigra_self-portrait-3e0070aa19a7fe36e802253048411a38f14a79f8-s800-c85.webp")
            elif discord_user:
                embed.set_thumbnail(url=discord_user.default_avatar.url)

            # You might want to add top sounds for each user here if that data is available
            top_sounds = Database().get_top_sounds(number=number, days=days, user=username)
            for sound in top_sounds[0]:
                embed.add_field(name=f"🎵 **{sound[0]}**", value=f"Played **{sound[1]}** times", inline=False)

            message = await bot_channel.send(embed=embed)
            messages.append(message)

        sound_summary, total_plays = Database().get_top_sounds(number=100000, days=30, user=None)
        average_per_day = total_plays / 30
        title = f"🎵 **TOP MANUALLY PLAYED SOUNDS IN THE LAST {days} DAYS! TOTAL PLAYS: {total_plays}** 🎵"
        description = f"Average of {average_per_day:.0f} plays per day!"
        color = discord.Color.yellow()

        summary_embed = discord.Embed(
            title=title,
            description=description,
            color=color
        )
        summary_embed.set_thumbnail(url="https://i.imgflip.com/1vdris.jpg")
        summary_embed.set_footer(text="Updated as of")
        summary_embed.timestamp = datetime.utcnow()

        # Add top 10 sounds to the summary embed
        top_10_sounds = sound_summary[:10]
        for i, (sound_name, play_count) in enumerate(top_10_sounds, 1):
            summary_embed.add_field(
                name=f"#{i}: {sound_name}",
                value=f"Played {play_count} times",
                inline=False
            )

        summary_message = await bot_channel.send(embed=summary_embed)
        messages.append(summary_message)

        await self.send_controls()
        await asyncio.sleep(60)

        for message in messages:
            await message.delete()

    async def prompt_upload_sound(self, interaction):
        if self.upload_lock.locked():
            message = await interaction.channel.send(embed=discord.Embed(title="Another upload is in progress. Wait caralho 😤", color=self.color))
            await asyncio.sleep(10)
            await message.delete()
            return
        
        async with self.upload_lock:
            message = await interaction.channel.send(embed=discord.Embed(title="Upload an .mp3, or provide an MP3/TikTok/YouTube URL (max 10 minutes for YouTube). You have 60s ☝️🤓", color=self.color))

            def check(m):
                is_attachment = len(m.attachments) > 0 and m.attachments[0].filename.endswith('.mp3')
                is_mp3_url = re.match(r'^https?://.*\.mp3$', m.content)
                is_tiktok_url = re.match(r'^https?://.*tiktok\.com/.*$', m.content)
                is_youtube_url = re.match(r'^https?://(www\.)?(youtube\.com|youtu\.be)/.*$', m.content)
                return m.author == interaction.user and m.channel == interaction.channel and (is_attachment or is_mp3_url or is_tiktok_url or is_youtube_url)

            try:
                response = await self.bot.wait_for('message', check=check, timeout=60.0)
                await message.delete()

                # Extract the custom filename if provided
                custom_filename = None
                if response.content:
                    parts = response.content.split(maxsplit=1)
                    if len(parts) > 1 and not parts[0].startswith('http'):
                        custom_filename = response.content
                    elif len(parts) > 1 and parts[0].startswith('http'):
                        custom_filename = parts[1]

                # Handle time limit for TikTok and YouTube
                time_limit = None
                if re.match(r'^https?://.*tiktok\.com/.*$', response.content) or re.match(r'^https?://(www\.)?(youtube\.com|youtu\.be)/.*$', response.content):
                    parts = response.content.split(maxsplit=2)
                    if len(parts) > 1 and parts[1].isdigit():
                        time_limit = int(parts[1])
                        if len(parts) > 2:
                            custom_filename = parts[2]

                await response.delete()
                
                if len(response.attachments) > 0:
                    file_path = await self.save_uploaded_sound(response.attachments[0], custom_filename)
                elif re.match(r'^https?://.*tiktok\.com/.*$', response.content) or re.match(r'^https?://(www\.)?(youtube\.com|youtu\.be)/.*$', response.content):
                    await self.send_message(title="Downloading video... 🤓", description="Espera, bixa", delete_time=5)
                    try:
                        file_path = await self.save_sound_from_video(response.content, custom_filename, time_limit=time_limit)
                    except ValueError as e:
                        error_message = await interaction.channel.send(embed=discord.Embed(title="Error", description=str(e), color=self.color))
                        await asyncio.sleep(10)
                        await error_message.delete()
                        return
                else:
                    file_path = await self.save_sound_from_url(response.content, custom_filename)

                Database().insert_action(interaction.user.name, "upload_sound", file_path)
                confirmation_message = await interaction.channel.send(embed=discord.Embed(title="Sound uploaded successfully! (may take up to 10s to be available)", color=self.color))
                await asyncio.sleep(10)
                await confirmation_message.delete()
            except asyncio.TimeoutError:
                await message.delete()
                timeout_message = await interaction.channel.send(embed=discord.Embed(title="Upload timed out 🤬", color=self.color))
                await asyncio.sleep(10)
                await timeout_message.delete()
            except Exception as e:
                error_message = await interaction.channel.send(embed=discord.Embed(title="An error occurred.", description=str(e), color=self.color))
                await asyncio.sleep(10)
                await error_message.delete()

    async def save_uploaded_sound(self, attachment, custom_filename=None):
        os.makedirs(self.dwdir, exist_ok=True)
        if custom_filename:
            filename = f"{custom_filename}.mp3"
        else:
            filename = attachment.filename
        file_path = os.path.join(self.dwdir, filename)
        await attachment.save(file_path)
        return file_path
    
    async def save_sound_from_tiktok(self, url, custom_filename=None, time_limit=None):
        os.makedirs(self.dwdir, exist_ok=True)

        # Download the TikTok video
        filename = ManualSoundDownloader.tiktok_to_mp3(url, self.dwdir, custom_filename, time_limit)
        file_path = os.path.join(self.dwdir, filename)

        return file_path

    async def save_sound_from_url(self, url, custom_filename=None):
        os.makedirs(self.dwdir, exist_ok=True)
        if custom_filename:
            filename = f"{custom_filename}.mp3"
        else:
            filename = url.split("/")[-1]
        file_path = os.path.join(self.dwdir, filename)

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    with open(file_path, 'wb') as f:
                        f.write(await response.read())
                else:
                    raise Exception("Failed to download the MP3 file.")
        return file_path

    async def save_sound_from_video(self, url, custom_filename=None, time_limit=None):
        os.makedirs(self.dwdir, exist_ok=True)

        # Download the video (TikTok or YouTube)
        filename = ManualSoundDownloader.video_to_mp3(url, self.dwdir, custom_filename, time_limit)
        file_path = os.path.join(self.dwdir, filename)

        return file_path

    async def get_new_name(self, interaction):
        message = await interaction.channel.send(embed=discord.Embed(title="Please enter the new name for the sound.", color=self.color))
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel
        try:
            response = await self.bot.wait_for('message', check=check, timeout=10.0)
            await response.delete()
            await message.delete()
        except asyncio.TimeoutError:
            await message.delete()
            return None
        return response.content

    async def write_list(self, message, description=""):
        formatted_message = "```" + "\n".join(message) + "```"  # Surrounds the message with code block markdown
        self.color = discord.Color.orange()
        message = await self.send_message(title=description, description=formatted_message)
        await asyncio.sleep(30)
        await message.delete()     

    async def delete_controls_message(self, delete_all=True):
        try:
            bot_channel = await self.get_bot_channel()
            if delete_all:
                async for message in bot_channel.history(limit=100):
                    if message.components and len(message.components[0].children) == 5 and len(message.components[1].children) == 5 and not message.embeds and "Play Random" in message.components[0].children[0].label:
                        await message.delete()
            else:
                messages = await bot_channel.history(limit=100).flatten()
                control_messages = [message for message in messages if message.components and len(message.components[0].children) == 5 and len(message.components[1].children) == 5 and not message.embeds and "Play Random" in message.components[0].children[0].label]
                for message in control_messages[1:]:  # Skip the last message
                    await message.delete()
        except Exception as e:
            print(f"1An error occurred: {e}")

    async def delete_last_message(self, count=1):
        bot_channel = await self.get_bot_channel()
        async for message in bot_channel.history(limit=count):
            await message.delete()
            return
    
    async def clean_buttons(self, count=5):
        try:
            bot_channel = await self.get_bot_channel()
            async for message in bot_channel.history(limit=count):
                # if message.components and not empty
                if message.components and message.embeds:
                    await message.edit(view=None)      
                elif message.components:
                    await message.delete()                 
        except Exception as e:
            print(f"2An error occurred: {e}")
    
    async def get_bot_channel(self, bot_channel=None):
        if bot_channel:
            bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name=bot_channel)
            return bot_channel
        else:
            bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
            return bot_channel
        
    def get_largest_voice_channel(self, guild):
        largest_channel = None
        largest_size = 0
        for channel in guild.voice_channels:
            if len(channel.members) > largest_size:
                largest_channel = channel
                largest_size = len(channel.members)
        return largest_channel
    
    def get_user_voice_channel(self, guild, user):
        #stip the user of the discriminator
        user = user.split("#")[0]
        for channel in guild.voice_channels:
            if channel.members:
                for member in channel.members:
                    if user in member.name:
                        return channel
        return None
    
    async def send_error_message(self, message):
        self.error_message = await self.send_message(view=None, title="🤬 Error 🤬", description=message)
        #await asyncio.sleep(3)
        #await self.cooldown_message.delete()

    async def ensure_voice_connected(self, channel):
        voice_client = discord.utils.get(self.bot.voice_clients, guild=channel.guild)
        if voice_client and voice_client.is_connected():
            if voice_client.channel != channel:
                await voice_client.move_to(channel)
        else:
            voice_client = await channel.connect()
        return voice_client

    async def play_audio(self, channel, audio_file, user, is_entrance=False, is_tts=False, extra="", original_message="", send_controls=True, retry_count=0):
        MAX_RETRIES = 3

        # Check cooldown first
        if self.last_played_time and (datetime.now() - self.last_played_time).total_seconds() < 2:
            bot_channel = await self.get_bot_channel()
            if self.cooldown_message is None and not is_entrance:
                self.cooldown_message = await bot_channel.send(embed=discord.Embed(title="Don't be rude, let Gertrudes speak 😤"))
                await asyncio.sleep(3)
                await self.cooldown_message.delete()
                self.cooldown_message = None
                return
        self.last_played_time = datetime.now()

        try:
            voice_client = await self.ensure_voice_connected(channel)

            # Get the absolute path of the audio file
            audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", audio_file))

            # Check if the audio file exists
            if not os.path.exists(audio_file_path):
                audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", Database().get_sound(audio_file, True)[2]))
                if not os.path.exists(audio_file_path):
                    await self.send_error_message(f"Audio file not found: {audio_file_path}")
                    print(f"Audio file not found: {audio_file_path}")
                    return

            # Get audio duration
            try:
                audio = MP3(audio_file_path)
                duration = audio.info.length
                duration_str = f"{int(duration // 60)}:{int(duration % 60):02d}"
            except Exception as e:
                print(f"Error getting audio duration: {e}")
                duration_str = "Unknown"
                duration = 0

            # Send a message to the bot channel if the sound is not a slap, tiro or pubg-pan-sound-effect
            self.color = discord.Color.red()
            bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
            sound_message = None
            
            if bot_channel and not is_entrance:
                if audio_file.split('/')[-1] not in ["slap.mp3", "tiro.mp3", "pubg-pan-sound-effect.mp3", "slap-oh_LGvkhyt.mp3", "kid-slap-oh.mp3", "gunshot-one.mp3"]:
                    description = []
                    if extra != "":
                        description.append(f"Similarity: {extra}%")
                    
                    # Initialize progress bar
                    current_time = "0:00"
                    description.append(f"Duration: {current_time} / {duration_str}")
                    description.append(f"Progress: ░░░░░░░░░░░░░░░░░░░░")
                    description_text = "\n".join(description) if description else None
                    
                    sound_message = await self.send_message(
                        view=SoundBeingPlayedView(self, audio_file), 
                        title=f"🔊 **{Database().get_sound(audio_file, True)[2].replace('.mp3', '')}** 🔊", 
                        description=description_text,
                        footer=f"{user} requested '{original_message}'" if original_message else f"Requested by {user}", 
                        send_controls=send_controls
                    )

            # Stop the audio if it is already playing
            if voice_client.is_playing():
                voice_client.stop()

            def after_playing(error):
                if error:
                    asyncio.run_coroutine_threadsafe(self.send_error_message(f"Error in playback, but Gertrudes will retry: {error}"), self.bot.loop)
                    print(f'Error in playback: {error}')
                    if retry_count < MAX_RETRIES:
                        time.sleep(5)
                        asyncio.run_coroutine_threadsafe(self.play_audio(channel, audio_file, user, is_entrance, is_tts, extra, original_message, send_controls, retry_count + 1), self.bot.loop)
                self.bot.loop.call_soon_threadsafe(self.playback_done.set)

            # Check if FFmpeg path is set and valid
            if not self.ffmpeg_path or not os.path.exists(self.ffmpeg_path):
                await self.send_error_message(f"Invalid FFmpeg path: {self.ffmpeg_path}")
                print(f"Invalid FFmpeg path: {self.ffmpeg_path}")
                return

            # Add this check before playing
            if not voice_client.is_connected():
                await self.send_error_message("Voice client is not connected. Attempting to reconnect...")
                await voice_client.connect(timeout=10, reconnect=True)

            # Play the audio file
            try:
                if audio_file.split('/')[-1] not in ["slap.mp3", "tiro.mp3", "pubg-pan-sound-effect.mp3", "slap-oh_LGvkhyt.mp3", "kid-slap-oh.mp3", "gunshot-one.mp3"]:
                    await asyncio.sleep(.5)
                audio_source = discord.FFmpegPCMAudio(executable=self.ffmpeg_path, source=audio_file_path)
                voice_client.play(audio_source, after=after_playing)
                
                # Update progress bar while playing
                start_time = time.time()
                while voice_client.is_playing():
                    if sound_message and duration > 0:
                        elapsed = time.time() - start_time
                        progress = min(elapsed / duration, 1.0)
                        bar_length = 20
                        filled = '█' * int(bar_length * progress)
                        empty = '░' * (bar_length - int(bar_length * progress))
                        progress_bar = f"{filled}{empty}"
                        
                        current_minutes = int(elapsed // 60)
                        current_seconds = int(elapsed % 60)
                        current_time = f"{current_minutes}:{current_seconds:02d}"
                        
                        description = []
                        if extra != "":
                            description.append(f"Similarity: {extra}%")
                        description.append(f"Duration: {current_time} / {duration_str}")
                        description.append(f"Progress: {progress_bar}")
                        description_text = "\n".join(description)
                        
                        embed = sound_message.embeds[0]
                        embed.description = description_text
                        await sound_message.edit(embed=embed)
                    await asyncio.sleep(1)
                
                # Remove only the progress bar when done
                if sound_message:
                    description = []
                    if extra != "":
                        description.append(f"Similarity: {extra}%")
                    description.append(f"Duration: {duration_str}")
                    description_text = "\n".join(description) if description else None
                    
                    embed = sound_message.embeds[0]
                    embed.description = description_text
                    await sound_message.edit(embed=embed)
                
            except discord.ClientException as e:
                if "Not connected to voice" in str(e):
                    await self.send_error_message("Lost voice connection. Attempting to reconnect...")
                    if retry_count < MAX_RETRIES:
                        await self.play_audio(channel, audio_file, user, is_entrance, is_tts, extra, original_message, send_controls, retry_count + 1)
                    return
                else:
                    raise e
            except Exception as e:
                await self.send_error_message(f"Error playing audio: {e}")
                print(f"Error playing audio: {e}")
                if retry_count < MAX_RETRIES:
                    await self.play_audio(channel, audio_file, user, is_entrance, is_tts, extra, original_message, send_controls, retry_count + 1)
                return

            await self.playback_done.wait()

        except Exception as e:
            await self.send_error_message(f"An error occurred: {e}")
            print(f"An error occurred: {e}")
            if retry_count < MAX_RETRIES:
                await asyncio.sleep(1)
                await self.play_audio(channel, audio_file, user, is_entrance, is_tts, extra, original_message, send_controls, retry_count + 1)

    async def update_bot_status(self):
        while True:
            if hasattr(self.bot, 'next_download_time'):
                time_left = self.bot.next_download_time - time.time()
                if time_left > 0:
                    minutes = round(time_left / 60)
                    if minutes < 2:
                        activity = discord.Activity(name=f'explosion imminent!!!', type=discord.ActivityType.playing)
                    else:
                        activity = discord.Activity(name=f'an explosion in ~{minutes}m', type=discord.ActivityType.playing)
                    await self.bot.change_presence(activity=activity)
            await asyncio.sleep(60)

    async def play_sound_periodically(self):
        while True:
            try:
                sleep_time = random.uniform(0, 800)
                self.bot.next_download_time = time.time() + sleep_time
                while time.time() < self.bot.next_download_time:
                    await asyncio.sleep(60)
                for guild in self.bot.guilds:
                    channel = self.get_largest_voice_channel(guild)
                    if channel is not None:
                        random_file = Database().get_random_sounds()

                        await self.play_audio(channel, random_file[0][2], "periodic function")
                        Database().insert_action("admin", "play_sound_periodically", random_file[0][0])
                    else:
                        await asyncio.sleep(sleep_time)
            except Exception as e:
                print(f"4An error occurred: {e}")
                await asyncio.sleep(60)

    async def play_random_sound(self, user="admin"):
        try:
            for guild in self.bot.guilds:
                if (user == "admin"):
                    channel = self.get_largest_voice_channel(guild)
                else:
                    channel = self.get_user_voice_channel(guild,user)
                if channel is not None:
                    random_sound = Database().get_random_sounds()
                    asyncio.create_task(self.play_audio(channel, random_sound[0][2], user))
                    Database().insert_action(user, "play_random_sound", random_sound[0][0])
        except Exception as e:
            print(f"3An error occurred: {e}")

    async def play_random_favorite_sound(self, username): 
        channel = self.get_user_voice_channel(self.bot.guilds[0], username)
        favorite_sound = Database().get_random_sounds(favorite=True)
        Database().insert_action(username, "play_random_favorite_sound", favorite_sound[0][0])
        await self.play_audio(channel,favorite_sound[0][1], username)

    def randomize_color(self):
        temp_color = discord.Color.random()
        while temp_color == self.color:
            temp_color = discord.Color.random()
        self.color = temp_color
    
    async def play_request(self, id, user, request_number=5):
        filenames = Database().get_sounds_by_similarity(id,request_number)
        for guild in self.bot.guilds:
            channel = self.get_user_voice_channel(guild, user)
            if channel is not None:
                asyncio.create_task(self.play_audio(channel, filenames[0][1], user, original_message=id, send_controls = False if filenames[1:] else True))
                Database().insert_action(user, "play_request", filenames[0][0])
                await asyncio.sleep(2)
                if filenames[1:]:
                    await self.send_message(view=SoundView(self, filenames[1:]))

    async def change_filename(self, oldfilename, newfilename, user):
        Database().insert_action(user.name, "change_filename", oldfilename + " to " + newfilename)
        await Database().update_sound(oldfilename, new_filename=newfilename)
                    
    async def tts(self, user, speech, lang="en", region=""):
        Database().insert_action(user.name, "tts", speech)
        await self.TTS.save_as_mp3(speech, lang, region)   

    async def tts_EL(self, user, speech, lang="en", region=""):
        Database().insert_action(user.name, "tts_EL", speech)
        await self.TTS.save_as_mp3_EL(speech, lang, region)  

    async def sts_EL(self, user, sound, char="ventura", region=""):
        await self.TTS.speech_to_speech(sound, char, region)  

    async def isolate_voice(self, user, sound):
        Database().insert_action(user.name, "isolate_voice", sound)
        await self.TTS.isolate_voice(sound)

    async def stt(self, user, audio_files):
        return await self.TTS.speech_to_text(audio_files)
    
    async def list_sounds(self, user, count=0):
        try:
            bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
            if bot_channel:
                message = ""
                sounds = Database().get_sounds(num_sounds=count)
                if count > 0:
                    sound_view = SoundView(self, sounds)
                    Database().insert_action(user.name, "list_last_sounds", str(count))
                    message = await self.send_message(title="Last "+ str(count)+" Sounds Downloaded", view=sound_view)
                else:
                    Database().insert_action(user.name, "list_all_sounds", "all")
                    message = await self.send_message(description="Total sounds downloaded: "+str(len(sounds)), file=discord.File(self.db_path, 'Data/soundsDB.csv'))
                print(f"Message sent to the chat.")
                await asyncio.sleep(120)
                await message.delete()
                return
        except Exception as e:
            print(f"An error occurred: {e}")

    async def user_vs_userlolstats(self, username1, username2, gamemode, champion):
        data = await self.lol_db.get_player_stats(username1, gamemode, champion)
        if not data:
            await self.send_message(title="No stats found", description=f"No {gamemode} stats found for {username1} (or less than 4 games per champion)")
            return
        data2 = await self.lol_db.get_player_stats(username2, gamemode, champion)
        if not data2:
            await self.send_message(title="No stats found", description=f"No {gamemode} stats found for {username2} (or less than 4 games per champion)")
            return

        # Get overall stats from the first row for both players
        total_games1, total_hours1 = data[0][5], data[0][9]
        total_games2, total_hours2 = data2[0][5], data2[0][9]

        # Create dictionaries of champion stats
        champ_dict1 = {row[0]: row[1:] for row in data}
        champ_dict2 = {row[0]: row[1:] for row in data2}
        all_champs = sorted(set(list(champ_dict1.keys()) + list(champ_dict2.keys())))

        # Create the table header
        table = "```\n"
        table += f"{'Stat':<20} {username1:<15} {username2:<15}\n"
        table += "-" * 50 + "\n"

        # Add champion stats
        for champ in all_champs:            
            # Get stats for both players
            stats1 = champ_dict1.get(champ, [0] * 13)  # Updated to match new column count
            stats2 = champ_dict2.get(champ, [0] * 13)  # Updated to match new column count
            
            if stats1[0] > 0 or stats2[0] > 0:  # Only show if either player has games
                table += f"{'Games':<20} {stats1[0]:<15} {stats2[0]:<15}\n"
                table += f"{'Total Hours':<20} {total_hours1:<15.1f} {total_hours2:<15.1f}\n"
                table += f"{'Win Rate %':<20} {stats1[1]:<15.1f} {stats2[1]:<15.1f}\n"
                table += f"{'DPM':<20} {int(stats1[2]):<15} {int(stats2[2]):<15}\n"
                table += f"{'KDA':<20} {stats1[3]:<15.2f} {stats2[3]:<15.2f}\n"
                table += f"{'Triple Kills':<20} {stats1[9]:<15} {stats2[9]:<15}\n"
                table += f"{'Quadra Kills':<20} {stats1[10]:<15} {stats2[10]:<15}\n"
                table += f"{'Penta Kills':<20} {stats1[11]:<15} {stats2[11]:<15}\n"
                table += "\n"

        table += "```"

        await self.send_message(
            title=f"🎮 {gamemode} Stats Comparison on {champion}",
            description=table,
            bot_channel="botlol"
        )

    async def userlolstats(self, username, gamemode, champion=None):
        data = await self.lol_db.get_player_stats(username, gamemode, champion)
        if not data:
            await self.send_message(title="No stats found", description=f"No {gamemode} stats found for {username} (or less than 4 games per champion)")
            return

        # Get overall stats from the first row
        total_games = data[0][5]
        unique_champs = data[0][6]
        unique_ratio = data[0][7]
        oldest_game = datetime.strptime(data[0][8], '%Y-%m-%d %H:%M:%S.%f').strftime('%Y-%m-%d')
        total_hours = data[0][9]
        total_pentas = data[0][13]

        # Create the stats table with wider columns
        table = "```\nChampion Stats:\n"
        table += f"{'Champion':<15} {'Games':<8} {'Win%':<8} {'DPM':<8} {'KDA':<5} {'x4':<2} {'x5':<2}\n"
        table += "-" * 55 + "\n"  # Increased separator length
        
        for row in data:
            champ = row[0][:14] if "Strawberry_" not in row[0] else row[0].replace("Strawberry_", "")[:14]
            games = str(row[1])
            winrate = f"{row[2]:.1f}"
            dpm = str(int(row[3]))
            kda = f"{row[4]:.2f}"
            quadras = str(row[11])
            pentas = str(row[12])

            
            table += f"{champ:<15} {games:<8} {winrate:<8} {dpm:<8} {kda:<5} {quadras:2} {pentas:2}\n"
        
        table += "```"

        # Create overall stats description
        description = f"**Overall Stats in the last ~1 or 2 years:**\n"
        description += f"• Total Games: {total_games}\n"
        description += f"• Unique Champions: {unique_champs}\n"
        description += f"• Champion Variety: {unique_ratio:.1f}%\n"
        description += f"• Total Hours: {total_hours}\n"
        description += f"• Total Pentas: {total_pentas}\n"
        description += f"• Latest Game Fetched: {oldest_game}\n\n"
        description += table

        await self.send_message(
            title=f"🎮 {username}'s {gamemode} Stats",
            description=description,
            bot_channel="botlol"
        )

    async def userloltime(self):
        data = await self.lol_db.get_player_time_stats()
        if not data:
            await self.send_message(title="No stats found", description="No time stats found")
            return

        # Create the stats table
        table = "```\nPlayer Time Stats:\n"
        table += f"{'Player':<15} {'Hours':<6} {'2024h':<6} {'Games':<5} {' WR':<4} {'Avg(m)':<8} {'Pentas':<5}\n"
        table += "-" * 55 + "\n"
        
        for row in data:
            name = f"{row[0]}"[:14] 
            total_hours = f"{row[2]:.1f}"
            hours_2024 = f"{row[3]:.1f}"
            games = str(row[4])
            avg_minutes = f"{row[5]:.1f}"
            pentas = str(row[7])  # New field for pentakills
            winrate = f"{row[8]:.1f}"
            table += f"{name:<15} {total_hours:<6} {hours_2024:<6} {games:<5} {winrate:<4} {avg_minutes:<8} {pentas:5}\n"
        
        table += "```"

        # Create description with the table
        description = f"**League of Legends Time Stats**\n"
        description += table

        await self.send_message(
            title="⌛ LoL Time Statistics",
            description=description,
            bot_channel="botlol"
        )

    async def subway_surfers(self, user):
        folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Data", "SubwaySurfers"))
        files = os.listdir(folder)
        file = random.choice(files)
        title = files.index(file) + 1  # Adding 1 because index is 0-based
        message = await self.send_message(title="Subway Surfers clip "+str(title)+" of "+str(len(files)), file=discord.File(os.path.abspath(os.path.join(folder, file)), f"SubwaySurfers/{file}"))
        await asyncio.sleep(VideoFileClip(os.path.join(folder, file)).duration + 5)
        Database().insert_action(user.name, "subway_surfers", file)
        await message.delete()
    
    async def slice_all(self, user):
        folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Data", "SliceAll"))
        files = os.listdir(folder)
        file = random.choice(files)
        title = files.index(file) + 1  # Adding 1 because index is 0-based
        message = await self.send_message(title="Slice All clip "+str(title)+" of "+str(len(files)), file=discord.File(os.path.abspath(os.path.join(folder, file)), f"SliceAll/{file}"))
        await asyncio.sleep(VideoFileClip(os.path.join(folder, file)).duration + 5)
        Database().insert_action(user.name, "slice_all", file)
        await message.delete()

    async def family_guy(self, user):
        folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Data", "FamilyGuy"))
        files = os.listdir(folder)
        file = random.choice(files)
        title = files.index(file) + 1  # Adding 1 because index is 0-based
        message = await self.send_message(title="Family Guy clip "+str(title)+" of "+str(len(files)), file=discord.File(os.path.abspath(os.path.join(folder, file)), f"FamilyGuy/{file}"))
        await asyncio.sleep(VideoFileClip(os.path.join(folder, file)).duration + 5)
        Database().insert_action(user.name, "family_guy", file)
        await message.delete()

    async def send_message(self, title="", description="",footer=None, thumbnail=None, view=None, send_controls=True, file=None, delete_time=0, bot_channel=None):
        bot_channel = await self.get_bot_channel(bot_channel)
        embed = discord.Embed(title=title, description=description, color=self.color)
        embed.set_thumbnail(url=thumbnail)
        embed.set_footer(text=footer)
        embed.add_field(name="", value="[🥵 gabrielagrela.com 🥵](https://gabrielagrela.com)")
        if delete_time > 0:
            message = await bot_channel.send(view=view, embed=None if description == "" and title == "" else embed, file=file, delete_after=delete_time)
        else:
            message = await bot_channel.send(view=view, embed=None if description == "" and title == "" else embed, file=file)
        if send_controls:
            await self.send_controls()
        return message
    
    async def is_channel_empty(self, channel):
        if len(channel.members) == 0 or (len(channel.members) == 1 and self.bot.user in channel.members):
            await self.bot.voice_clients[0].disconnect()
            return True

        return False

    async def send_controls(self, force = False):
        bot_channel = await self.get_bot_channel()
        try:
            await self.controls_message.delete()
            self.controls_message = await bot_channel.send(view=ControlsView(self))
        except Exception as e:
            print("error sending controls ", e)
        if force:
            self.controls_message = await bot_channel.send(view=ControlsView(self))
        
    async def is_playing_sound(self):
        for vc in self.bot.voice_clients:
            if vc.is_playing():
                return True
        return False

    async def userlolfriends(self, username):
        data = await self.lol_db.get_player_friend_stats(username)
        if not data:
            await self.send_message(
                title="No friend stats found", 
                description=f"No duo stats found for {username} (minimum 5 games together required)"
            )
            return

        # Create the stats table
        table = "```\nDuo Queue Stats:\n"
        table += f"{'Friend':<15} {'Games':<8} {'Wins':<8} {'Win%':<8}\n"
        table += "-" * 42 + "\n"
        
        total_games = 0
        weighted_winrate = 0
        
        for row in data:
            name = row[0][:14]  # Limit name length
            games = str(row[1])
            wins = str(row[2])
            winrate = f"{row[3]:.1f}"
            
            total_games += row[1]
            weighted_winrate += row[1] * row[3]
            
            table += f"{name:<15} {games:<8} {wins:<8} {winrate:<8}\n"
        
        avg_winrate = weighted_winrate / total_games if total_games > 0 else 0
        table += "-" * 42 + "\n"
        table += f"Average Win Rate: {avg_winrate:.1f}%\n"
        table += "```"

        # Create description with the table
        description = f"**Showing duo stats for {username}**\n"
        description += f"Total duo games analyzed: {total_games}\n\n"
        description += table

        await self.send_message(
            title=f"👥 Duo Queue Statistics",
            description=description,
            bot_channel="botlol"
        )
    
    async def insertLoLUser(self, username):
        # Parse username and tagline
        if '#' in username:
            game_name, tag_line = username.split('#')
        else:
            game_name = username
            tag_line = 'EUW1'  # Default to EUW1 if no tagline provided
        
        try:
            # Get account info from Riot API
            account_info = await self.riotAPI.get_acc_from_riot_id(game_name, tag_line)
            
            # Insert user into database
            await self.lol_db.insert_user(
                username=username,
                puuid=account_info['puuid'],
                riot_id_game_name=account_info['gameName'],
                riot_id_tagline=account_info['tagLine']
            )
            await self.send_message(
                title="User added",
                description=f"User {username} added to the database",
                bot_channel="botlol"
            )
            return True
            
        except HTTPError as e:
            print(f"Error fetching user data from Riot API: {e}")
            await self.send_message(
                title="Error",
                description=f"Error fetching user data from Riot API: {e}",
                bot_channel="botlol"
            )
            return False
        except Exception as e:
            print(f"Error inserting user into database: {e}")
            await self.send_message(
                title="Error",
                description=f"Error inserting user into database: {e}",
                bot_channel="botlol"
            )
            return False
        
    #every 10 seconds check if the user is in a game
    async def check_if_in_game(self):
        while True:
            users = await self.lol_db.get_users()
            active_players = []
            processed_users = set()  # Keep track of processed users

            # Collect data for all users in games
            for user in users:
                if user[1] in processed_users:  # Skip if user was already processed
                    continue

                try:
                    game_data = await self.riotAPI.get_current_game(user[2])
                    if game_data:
                        # Process all tracked users in this game
                        for participant in game_data['participants']:
                            # Find if this participant is one of our tracked users
                            tracked_user = next((u for u in users if u[2] == participant['puuid']), None)
                            if tracked_user and str(tracked_user[5]) != str(game_data['gameId']):
                                champion = await self.lol_db.get_champion(participant['championId'])
                                
                                # Get player stats for this champion/gamemode
                                stats = await self.lol_db.get_player_stats(tracked_user[3], game_data['gameMode'], champion.replace(" ", "").replace("'", ""))
                                
                                # Extract relevant stats or use defaults if no stats available
                                if stats:
                                    games = stats[0][1]
                                    winrate = f"{stats[0][2]:.1f}"
                                    kda = f"{stats[0][4]:.2f}"
                                    pentas = stats[0][12] if len(stats[0]) > 12 else 0
                                else:
                                    games = 0
                                    winrate = "N/A"
                                    kda = "N/A"
                                    pentas = 0

                                active_players.append({
                                    'name': tracked_user[3],
                                    'champion': champion,
                                    'gameMode': game_data['gameMode'],
                                    'games': games,
                                    'winrate': winrate,
                                    'kda': kda,
                                    'pentas': pentas
                                })

                                await self.lol_db.update_user(tracked_user[1], last_game_played=game_data['gameId'])
                                processed_users.add(tracked_user[1])  # Mark this user as processed

                except Exception as e:
                    print(f"Error checking if {user[3]} is in a game: {e}")
                await asyncio.sleep(0.1)

            # If there are active players, create and send the table
            if active_players:
                # Sort players by winrate (handling N/A cases)
                def get_winrate_value(player):
                    # Convert "N/A" to -1 for sorting purposes
                    # Convert "XX.X%" to float
                    wr = player['winrate']
                    return -1 if wr == "N/A" else float(wr.rstrip('%'))
                
                active_players.sort(key=get_winrate_value, reverse=True)
                
                table = "```"
                table += f"{'Player':<15} {'Champion':<10} {'Mode':<5} {'Games':<6} {'Win%':<6} {'KDA':<5} {'x5':<3}\n"
                table += "-" * 56 + "\n"
                
                for player in active_players:
                    name = player['name'][:14]
                    champ = player['champion'][:10]
                    mode = player['gameMode'][:5]
                    games = str(player['games'])
                    winrate = player['winrate']
                    kda = player['kda']
                    pentas = str(player['pentas'])
                    
                    table += f"{name:<15} {champ:<10} {mode:<5} {games:<6} {winrate:<6} {kda:<5} {pentas:<3}\n"
                
                table += "```"
                
                await self.send_message(
                    title="🎮 Live Game(s)",
                    description=table,
                    bot_channel="botlol"
                )
                num_matches_updated = await self.riotAPI.update_database()

                if num_matches_updated > 0:
                    await self.send_message(
                        title="🎮 Database Updated",
                        description=f"Added {num_matches_updated} matches to the database ({await self.lol_db.get_match_count()} total)",
                        bot_channel="botlol"
                    )
                else:
                    await self.send_message(
                        title="🎮 Database Updated",
                        description=f"No new matches found",
                        bot_channel="botlol"
                    )
                await asyncio.sleep(200)

            await asyncio.sleep(10)
    
    async def update_database_loop(self):
            await self.riotAPI.update_database()
            await asyncio.sleep(200)

    async def refreshgames(self):
        num_matches_updated = await self.riotAPI.update_database()
        await self.send_message(
            title="🎮 Database Updated",
            description=f"Added {num_matches_updated} matches to the database ({await self.lol_db.get_match_count()} total)",
            bot_channel="botlol"
        )





