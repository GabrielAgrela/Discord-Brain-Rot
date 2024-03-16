import asyncio
import time
import discord
import random
from Classes.SoundDownloader import SoundDownloader
import os
from Classes.AudioDatabase import AudioDatabase
from Classes.PlayHistoryDatabase import PlayHistoryDatabase
from Classes.TTS import TTS
import csv
from Classes.UI import ReplayButton, FavoriteButton, BlacklistButton, ChangeSoundNameButton, PlayRandomButton, PlayRandomFavoriteButton, ListFavoritesButton, ListBlacklistButton, PlaySlapButton, ListSoundsButton, SubwaySurfersButton, SliceAllButton, FamilyGuyButton, ListTopSoundsButton, ListTopUsersButton, PlaySoundButton, SoundBeingPlayedView, ControlsView, SoundView



class BotBehavior:
    def __init__(self, bot, ffmpeg_path):
        self.bot = bot
        self.ffmpeg_path = ffmpeg_path
        self.temp_channel = ""
        self.last_channel = {}
        self.playback_done = asyncio.Event()
        self.script_dir = os.path.dirname(__file__)  # Get the directory of the current script
        self.db_path = os.path.join(self.script_dir, "../Data/soundsDB.csv")
        self.ph_path = os.path.join(self.script_dir, "../Data/play_history.csv")
        self.db = AudioDatabase(self.db_path, self)
        self.player_history_db = PlayHistoryDatabase(self.ph_path,self.db, self.bot, self)
        self.sound_downloader = SoundDownloader(self.db)
        self.TTS = TTS(self,bot)
        self.view = None
        self.embed = None
        self.controls_message = None
        self.color = discord.Color.red()

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
        message = await self.send_message(title=description, description=formatted_message, footer="Auto-destructing in 30 seconds...")
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
                for message in control_messages[:-1]:  # Skip the last message
                    await message.delete()
        except Exception as e:
            print(f"1An error occurred: {e}")

    async def delete_last_message(self):
        bot_channel = await self.get_bot_channel()
        async for message in bot_channel.history(limit=1):
            await message.delete()
            return
    
    async def clean_buttons(self):
        try:
            bot_channel = await self.get_bot_channel()
            async for message in bot_channel.history(limit=20):
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

    async def play_audio(self, channel, audio_file, user, is_entrance=False, is_tts=False, extra="", original_message="", send_controls=True):
        self.randomize_color()
        self.player_history_db.add_entry(audio_file, user)
        if channel == "":
            channel = self.temp_channel
        self.temp_channel = channel
        voice_client = discord.utils.get(self.bot.voice_clients, guild=channel.guild)
        bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
        if bot_channel and not is_entrance and not is_tts:
            if audio_file.split('/')[-1].replace('.mp3', '') not in ["slap", "tiro", "pubg-pan-sound-effect"]:
                await self.send_message(view=SoundBeingPlayedView(self, audio_file), title=f"🔊 **{audio_file.split('/')[-1].replace('.mp3', '')}** 🔊", description = f"Similarity: {extra}%" if extra != "" else None, footer = f"{user} requested '{original_message}'" if original_message else f"Requested by {user}", send_controls=send_controls)
        audio_file_path =  os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", audio_file))
        voice_client = discord.utils.get(self.bot.voice_clients, guild=channel.guild)
        if voice_client:
            if voice_client.channel != channel:
                await voice_client.move_to(channel)
            if voice_client.is_playing():
                voice_client.stop()
        else:
            try:
                voice_client = await channel.connect()
            except Exception as e:
                print(f"----------------Error connecting to channel: {e}")
                return
        self.playback_done.clear()

        def after_playing(error):
            if error:
                print(f'---------------------Error in playback: {error}')
            self.playback_done.set()

        try:
            voice_client.play(
                discord.FFmpegPCMAudio(executable=self.ffmpeg_path, source=audio_file_path),
                after=after_playing
            )
        except Exception as e:
            print(f"----------------------An error occurred: {e}")
            await voice_client.disconnect()
        await self.playback_done.wait()

    async def update_bot_status_once(self):
        if hasattr(self.bot, 'next_download_time'):
            time_left = self.bot.next_download_time - time.time()
            if time_left > 0:
                minutes = round(time_left / 60)
                if minutes < 2:
                    activity = discord.Activity(name=f'explosion imminent!!!', type=discord.ActivityType.playing)
                else:
                    activity = discord.Activity(name=f'an explosion in ~{minutes}m', type=discord.ActivityType.playing)
                await self.bot.change_presence(activity=activity)

    async def update_bot_status(self):
        while True:
            await self.update_bot_status_once()
            await asyncio.sleep(60)

    async def play_sound_periodically(self):
        while True:
            try:
                for guild in self.bot.guilds:
                    channel = self.get_largest_voice_channel(guild)
                sleep_time = random.uniform(0, 800)
                self.bot.next_download_time = time.time() + sleep_time
                while time.time() < self.bot.next_download_time:
                    await self.update_bot_status_once()
                    await asyncio.sleep(60)
                for guild in self.bot.guilds:
                    channel = self.get_largest_voice_channel(guild)
                    if channel is not None:
                        random_file = self.db.get_random_filename()
                        await self.play_audio(channel, random_file, "periodic function")
                    else:
                        await asyncio.sleep(sleep_time)
            except Exception as e:
                print(f"4An error occurred: {e}")
                await asyncio.sleep(60)

    async def play_random_sound(self, user="admin"):
        try:
            for guild in self.bot.guilds:
                channel = self.get_largest_voice_channel(guild)
                if channel is not None:
                    asyncio.create_task(self.play_audio(channel, self.db.get_random_filename(),user))
        except Exception as e:
            print(f"3An error occurred: {e}")

    async def play_random_favorite_sound(self, username):
        favorite_sounds = self.db.get_favorite_sounds()
        channel = self.get_largest_voice_channel(self.bot.guilds[0])
        if favorite_sounds:
            sound_to_play = random.choice(favorite_sounds)
            await self.play_audio(channel,sound_to_play, username)
        else:
            print("No favorite sounds found.")

    def randomize_color(self):
        temp_color = discord.Color.random()
        while temp_color == self.color:
            temp_color = discord.Color.random()
        self.color = temp_color
    
    async def play_request(self, id, user, request_number=5):
        filenames = self.db.get_most_similar_filenames(id,request_number)
        filename = filenames[0][1] if filenames else None
        similarity = filenames[0][0] if filenames else None
        for guild in self.bot.guilds:
            channel = self.get_largest_voice_channel(guild)
            if channel is not None:
                similar_sounds = [f"{filename[1]}" for filename in filenames[1:] if filename[0] > 70]
                asyncio.create_task(self.play_audio(channel, filename, user,extra=similarity, original_message=id, send_controls = False if similar_sounds else True))
                await asyncio.sleep(2)
                if similar_sounds:
                    await self.send_message(view=SoundView(self, similar_sounds))

    async def change_filename(self, oldfilename, newfilename):
        await self.db.modify_filename(oldfilename, newfilename)
                    
    async def tts(self, speech, lang="en", region=""):
        await self.TTS.save_as_mp3(speech, lang, region)     

    async def stt(self, audio_files):
        return await self.TTS.speech_to_text(audio_files)
    
    async def list_sounds(self, count=0):
        try:
            for guild in self.bot.guilds:
                channel = self.get_largest_voice_channel(guild)
                if channel is not None:
                    bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
                    if bot_channel:
                        with open(self.db_path, 'r') as file:
                            reader = csv.reader(file)
                            data = list(reader)
                            if count > 0:
                                data = data[-count:]  # Get the last 'count' entries
                                sound_names = [row[0] for row in data]  # Extract the first column
                                message = "\n".join(sound_names)  # Convert to string
                                sound_view = SoundView(self, sound_names)
                                await self.send_message(title="Last "+ str(count)+" Sounds Scraped:", view=sound_view)
                            else:
                                await bot_channel.send(file=discord.File(self.db_path, 'Data/soundsDB.csv'))
                            print(f"Message sent to the chat.")
                            return
        except Exception as e:
            print(f"An error occurred: {e}")

    async def subway_surfers(self):
        folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Data", "SubwaySurfers"))
        files = os.listdir(folder)
        file = random.choice(files)
        title = files.index(file) + 1  # Adding 1 because index is 0-based
        message = await self.send_message(title="Subway Surfers clip "+str(title)+" of "+str(len(files)), file=discord.File(os.path.abspath(os.path.join(folder, file)), f"SubwaySurfers/{file}"))
        await asyncio.sleep(60)
        await message.delete()
    
    async def slice_all(self):
        folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Data", "SliceAll"))
        files = os.listdir(folder)
        file = random.choice(files)
        title = files.index(file) + 1  # Adding 1 because index is 0-based
        message = await self.send_message(title="Slice All clip "+str(title)+" of "+str(len(files)), file=discord.File(os.path.abspath(os.path.join(folder, file)), f"SliceAll/{file}"))
        await asyncio.sleep(60)
        await message.delete()

    async def family_guy(self):
        folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Data", "FamilyGuy"))
        files = os.listdir(folder)
        file = random.choice(files)
        title = files.index(file) + 1  # Adding 1 because index is 0-based
        message = await self.send_message(title="Family Guy clip "+str(title)+" of "+str(len(files)), file=discord.File(os.path.abspath(os.path.join(folder, file)), f"FamilyGuy/{file}"))
        await asyncio.sleep(60)
        await message.delete()

    async def send_message(self, title="", description="",footer=None, thumbnail=None, view=None, send_controls=True, file=None):
        await self.delete_controls_message()
        bot_channel = await self.get_bot_channel()
        embed = discord.Embed(title=title, description=description, color=self.color)
        embed.set_thumbnail(url=thumbnail)
        embed.set_footer(text=footer)
        message = await bot_channel.send(view=view, embed=None if description == "" and title == "" else embed, file=file)
        if send_controls:
            await self.send_controls()
        return message
    
    async def send_controls(self):
        bot_channel = await self.get_bot_channel()
        self.controls_message = await bot_channel.send(view=ControlsView(self))
        await self.delete_controls_message(delete_all=False)
