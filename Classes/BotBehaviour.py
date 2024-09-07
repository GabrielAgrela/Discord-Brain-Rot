import asyncio
from datetime import datetime
import time
import discord
import random
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
        self.player_history_db = PlayHistoryDatabase(self.ph_path,self.db,self.users_json, self.bot, self)
        self.other_actions_db = OtherActionsDatabase(self.oa_path, self)
        self.TTS = TTS(self,bot)
        self.ManualSoundDownloader = ManualSoundDownloader()
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

    async def prompt_upload_sound(self, interaction):
        if self.upload_lock.locked():
            message = await interaction.channel.send(embed=discord.Embed(title="Another upload is in progress. Wait caralho 😤", color=self.color))
            await asyncio.sleep(10)
            await message.delete()
            return
        
        async with self.upload_lock:
            message = await interaction.channel.send(embed=discord.Embed(title="Upload a the .mp3 (and write the name you wanna give to that sound) or provide an MP3/Tiktok URL. You have 60s ☝️🤓", color=self.color))

            def check(m):
                is_attachment = len(m.attachments) > 0 and m.attachments[0].filename.endswith('.mp3')
                is_mp3_url = re.match(r'^https?://.*\.mp3$', m.content)
                is_tiktok_url = re.match(r'^https?://.*tiktok\.com/.*$', m.content)
                return m.author == interaction.user and m.channel == interaction.channel and (is_attachment or is_mp3_url or is_tiktok_url)

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

                #time limit is the int after the url
                if re.match(r'^https?://.*tiktok\.com/.*$', response.content):
                    parts = response.content.split(maxsplit=1)
                    if len(parts) > 1 and parts[1].isdigit():
                        time_limit = int(parts[1])
                    else:
                        time_limit = None
                else:
                    time_limit = None

                await response.delete()
                
                if len(response.attachments) > 0:
                    file_path = await self.save_uploaded_sound(response.attachments[0], custom_filename)
                elif re.match(r'^https?://.*tiktok\.com/.*$', response.content):
                    # send_message("Downloading TikTok video... 🤓"), destroy after 5s
                    await self.send_message(title="Downloading TikTok video... 🤓", description="Espera, bixa", delete_time=5)
                    file_path = await self.save_sound_from_tiktok(response.content, custom_filename, time_limit=time_limit)
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
    
    async def clean_buttons(self, count=10):
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
    
    async def get_bot_channel(self):
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

    async def play_audio(self, channel, audio_file, user, is_entrance=False, is_tts=False, extra="", original_message="", send_controls=True, retry_count=0):
        MAX_RETRIES = 3
        if await self.is_channel_empty(channel):
            return

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
            # Try connecting to the voice channel
            voice_client = discord.utils.get(self.bot.voice_clients, guild=channel.guild)
            if voice_client:
                await voice_client.move_to(channel)
            else:
                try:
                    voice_client = await channel.connect()
                except Exception as e:
                    await self.send_error_message(f"Error connecting to channel: {e}")
                    print(f"Error connecting to channel: {e}")
                    if retry_count < MAX_RETRIES:
                        await asyncio.sleep(1)
                        await self.play_audio(channel, audio_file, user, is_entrance, is_tts, extra, original_message, send_controls, retry_count + 1)
                    return

            # Get the absolute path of the audio file
            audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", audio_file))

            # Check if the audio file exists
            if not os.path.exists(audio_file_path):
                await self.send_error_message(f"Audio file not found: {audio_file_path}")
                print(f"Audio file not found: {audio_file_path}")
                return

            # Send a message to the bot channel if the sound is not a slap, tiro or pubg-pan-sound-effect
            self.color = discord.Color.red()
            bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
            if bot_channel and not is_entrance:
                if audio_file.split('/')[-1].replace('.mp3', '') not in ["slap", "tiro", "pubg-pan-sound-effect", "gunshot", "slap-oh_LGvkhyt"]:
                    await self.send_message(view=SoundBeingPlayedView(self, audio_file), title=f"🔊 **{audio_file.split('/')[-1].replace('.mp3', '')}** 🔊", description = f"Similarity: {extra}%" if extra != "" else None, footer = f"{user} requested '{original_message}'" if original_message else f"Requested by {user}", send_controls=send_controls)

            # Stop the audio if it is already playing
            if voice_client.is_playing():
                voice_client.stop()

            def after_playing(error):
                if error:
                    asyncio.run_coroutine_threadsafe(self.send_error_message(f"Error in playback, but Gertrudes will retry: {error}"), self.bot.loop)
                    print(f'Error in playback: {error}')
                    if retry_count < MAX_RETRIES:
                        #sleep for 1 second before retrying without asyncio
                        time.sleep(5)
                        asyncio.run_coroutine_threadsafe(self.play_audio(channel, audio_file, user, is_entrance, is_tts, extra, original_message, send_controls, retry_count + 1), self.bot.loop)
               # else:
                    # Add the entry to the play history database
                self.bot.loop.call_soon_threadsafe(self.playback_done.set)

            # Check if FFmpeg path is set and valid
            if not self.ffmpeg_path or not os.path.exists(self.ffmpeg_path):
                await self.send_error_message(f"Invalid FFmpeg path: {self.ffmpeg_path}")
                print(f"Invalid FFmpeg path: {self.ffmpeg_path}")
                return

            # Play the audio file
            try:
                if audio_file.split('/')[-1].replace('.mp3', '') not in ["slap", "tiro", "pubg-pan-sound-effect", "gunshot", "slap-oh_LGvkhyt"]:
                    await asyncio.sleep(1)
                audio_source = discord.FFmpegPCMAudio(executable=self.ffmpeg_path, source=audio_file_path)
                voice_client.play(audio_source, after=after_playing)
            except Exception as e:
                await self.send_error_message(f"Error playing audio: {e}")
                print(f"Error playing audio: {e}")
                if retry_count < MAX_RETRIES:
                    await asyncio.sleep(1)
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
        await self.play_audio(channel,favorite_sound[0][2], username)

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
                asyncio.create_task(self.play_audio(channel, filenames[0][2], user, original_message=id, send_controls = False if filenames[1:] else True))
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
        Database().insert_action(user.name, "sts_EL", sound)
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

    async def send_message(self, title="", description="",footer=None, thumbnail=None, view=None, send_controls=True, file=None, delete_time=0):
        bot_channel = await self.get_bot_channel()
        embed = discord.Embed(title=title, description=description, color=self.color)
        embed.set_thumbnail(url=thumbnail)
        embed.set_footer(text=footer)
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


