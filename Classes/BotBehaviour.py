import asyncio
import time
import discord
import random
from Classes.SoundDownloader import SoundDownloader
import os
import glob
import threading
from Classes.AudioDatabase import AudioDatabase
from Classes.PlayHistoryDatabase import PlayHistoryDatabase
from Classes.TTS import TTS

from discord.ui import Button, View
import sounddevice as sd
import numpy as np
from scipy.io.wavfile import write
from pydub import AudioSegment


class ReplayButton(Button):
    def __init__(self, bot_behavior, audio_file, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        

    async def callback(self, interaction):
        try:
            # Delete the last message
            await interaction.response.defer()
            # Then start the audio playback
            asyncio.create_task(self.bot_behavior.play_audio(interaction.message.channel, self.audio_file, interaction.user.name))
        except discord.errors.NotFound:
            # Handle expired interaction
            await interaction.message.channel.send("The buttons have expired. Sending new ones...")
            # Send new message with fresh buttons
            view = ControlsView(self.bot_behavior, self.audio_file)
            await interaction.message.channel.send(view=view)

class PlayRandomButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        # Start the audio playback
        asyncio.create_task(self.bot_behavior.play_random_sound(interaction.user.name))

class PlaySlapButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        # Start the slap sound playback
        asyncio.create_task(self.bot_behavior.play_audio("", "slap.mp3", "admin"))

class FavoriteButton(Button):
    def __init__(self, bot_behavior, audio_file):
        if bot_behavior.db.is_favorite(audio_file):
            super().__init__(label="⭐❌", style=discord.ButtonStyle.primary)
        else:
            super().__init__(label="⭐", style=discord.ButtonStyle.primary)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # Update the favorite status of the sound in the database
        if self.bot_behavior.db.is_favorite(self.audio_file):
            self.bot_behavior.db.update_favorite_status(self.audio_file, False)
        else:
            self.bot_behavior.db.update_favorite_status(self.audio_file, True)
        view = SoundBeingPlayedView(self.bot_behavior, self.audio_file)
        await interaction.message.edit(view=view)

class BlacklistButton(Button):
    def __init__(self, bot_behavior, audio_file):
        if bot_behavior.db.is_blacklisted(audio_file):
            super().__init__( label="🗑️❌", style=discord.ButtonStyle.primary)
        else:
            super().__init__(label="", emoji="🗑️", style=discord.ButtonStyle.primary)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # Update the favorite status of the sound in the database
        if self.bot_behavior.db.is_blacklisted(self.audio_file):
            self.bot_behavior.db.update_blacklist_status(self.audio_file, False)
        else:
            self.bot_behavior.db.update_blacklist_status(self.audio_file, True)
            # update this interactions view
        view = SoundBeingPlayedView(self.bot_behavior, self.audio_file)
        await interaction.message.edit(view=view)

class ListFavoritesButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        # Get the list of favorite sounds
        favorites = self.bot_behavior.db.get_favorite_sounds()
        if len(favorites) > 0:
            # Send the list of favorite sounds
            await self.bot_behavior.write_to_channel(favorites, "Favorite sounds")
        else:
            # Send a message if there are no favorite sounds
            await interaction.message.channel.send("No favorite sounds found.")

class ListBlacklistButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        # Get the list of blacklisted sounds
        blacklisted = self.bot_behavior.db.get_blacklisted_sounds()
        if len(blacklisted) > 0:
            # Send the list of blacklisted sounds
            await self.bot_behavior.write_to_channel(blacklisted, "Blacklisted sounds")
        else:
            # Send a message if there are no blacklisted sounds
            await interaction.message.channel.send("No blacklisted sounds found.")

class SimilarSoundButton(Button):
    def __init__(self, bot_behavior, sound_name, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.sound_name = sound_name

    async def callback(self, interaction):
        await interaction.response.defer()
        # Start the audio playback of the similar sound
        print(f"Playing similar sound: {self.sound_name}")
        asyncio.create_task(self.bot_behavior.play_audio(interaction.message.channel, self.sound_name, interaction.user.name))

class ChangeSoundNameButton(Button):
    def __init__(self, bot_behavior, sound_name, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.sound_name = sound_name

    async def callback(self, interaction):
        await interaction.response.defer()
        # Get the new name from the user
        new_name = await self.bot_behavior.get_new_name(interaction)
        if new_name:
            # Call the change_filename method with the current and new name
            await self.bot_behavior.change_filename(self.sound_name, new_name)

class ControlsView(View):
    def __init__(self, bot_behavior):
        super().__init__(timeout=None)
        # Add the play random button to the view
        self.add_item(PlayRandomButton(bot_behavior, label="🎲Play Random🎶", style=discord.ButtonStyle.success))
        # Add the list favorites button to the view
        self.add_item(ListFavoritesButton(bot_behavior, label="⭐Favorites⭐", style=discord.ButtonStyle.success))
        # Add the list blacklist button to the view
        self.add_item(ListBlacklistButton(bot_behavior, label="🗑️Blacklisted🗑️", style=discord.ButtonStyle.success))

class SoundBeingPlayedView(View):
    def __init__(self, bot_behavior, audio_file):
        super().__init__(timeout=None)
        # Add the replay button to the view
        self.add_item(ReplayButton(bot_behavior, audio_file, label=None, emoji="🔁", style=discord.ButtonStyle.primary))
        # Add the slap button to the view
        self.add_item(PlaySlapButton(bot_behavior, label=None, emoji="👋", style=discord.ButtonStyle.primary))
        # Add the favorite button to the view
        self.add_item(FavoriteButton(bot_behavior, audio_file))
        # Add the blacklist button to the view
        self.add_item(BlacklistButton(bot_behavior, audio_file))
        self.add_item(ChangeSoundNameButton(bot_behavior, audio_file, label="📝", style=discord.ButtonStyle.primary))

class SoundSimilarView(View):
    def __init__(self, bot_behavior, similar_sounds):
        super().__init__(timeout=None)
        # Add a button for each similar sound
        for sound in similar_sounds:
            self.add_item(SimilarSoundButton(bot_behavior, sound, style=discord.ButtonStyle.danger, label=sound.split('/')[-1].replace('.mp3', '')))



class BotBehavior:
    def __init__(self, bot, ffmpeg_path):
        self.bot = bot
        self.ffmpeg_path = ffmpeg_path
        
        self.temp_channel = ""
        self.last_channel = {}
        self.playback_done = asyncio.Event()
        # Usage example
        self.button_message = None
        self.script_dir = os.path.dirname(__file__)  # Get the directory of the current script
        self.db_path = os.path.join(self.script_dir, "../Data/soundsDB.csv")
        self.ph_path = os.path.join(self.script_dir, "../Data/play_history.csv")
        self.db = AudioDatabase(self.db_path, self)
        self.player_history_db = PlayHistoryDatabase(self.ph_path,self.db, self.bot)
        self.sound_downloader = SoundDownloader(self.db)
        self.TTS = TTS(self,bot)
        self.view = None
        self.embed = None
        self.color = discord.Color.red()

    async def get_new_name(self, interaction):
        # Send a message asking for the new name
        message = await interaction.channel.send(embed=discord.Embed(title="Please enter the new name for the sound.", color=self.color))
        # Define a check that only passes for messages from the user who clicked the button
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel

        try:
            # Wait for a message from the user
            response = await self.bot.wait_for('message', check=check, timeout=10.0)
            await response.delete()
            await message.delete()
        except asyncio.TimeoutError:
            # delete the message if the user didn't respond in time
            await message.delete()
            return None

        # Return the content of the response message as the new name
        return response.content

    async def write_to_channel(self, message, description=""):
        bot_channel = await self.get_bot_channel()
        formatted_message = "```" + "\n".join(message) + "```"  # Surrounds the message with code block markdown
        
        embed = discord.Embed(title=description, description=formatted_message, color=self.color)
        embed.set_footer(text=f"Auto-destructing in 30 seconds...")
        message = await bot_channel.send(embed=embed)
        await asyncio.sleep(30)
        await message.delete()
        

    async def delete_message_components(self):
        bot_channel = await self.get_bot_channel()
        async for message in bot_channel.history(limit=100):
            # delete the message if there are buttons and no text
            if message.components and len(message.components[0].children) == 3:
                await message.delete()

    async def delete_last_message(self, ctx):
        bot_channel = await self.get_bot_channel()
        async for message in bot_channel.history(limit=1):
            await message.delete()
            return
    
    async def clean_buttons(self):
        bot_channel = await self.get_bot_channel()
        async for message in bot_channel.history(limit=100):
            # remove the components of the message if there are any
            if message.components:
                await message.edit(view=None)

    async def delayed_button_clean(self, message):
        await asyncio.sleep(119)  # Wait for 5 minutes
        if message.components:
            await message.edit(view=None)
    
    async def get_bot_channel(self):
        bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
        return bot_channel
        
    def get_largest_voice_channel(self, guild):
        """Find the voice channel with the most members."""
        largest_channel = None
        largest_size = 0
        for channel in guild.voice_channels:
            if len(channel.members) > largest_size:
                largest_channel = channel
                largest_size = len(channel.members)
        return largest_channel

    async def disconnect_all_bots(self, guild):
        if self.bot.voice_clients:
            for vc_bot in self.bot.voice_clients:
                if vc_bot.guild == guild:
                    await vc_bot.disconnect()

    async def play_audio(self, channel, audio_file, user, is_entrance=False, is_tts=False, extra="", original_message=""):
        self.randomize_color()
        self.player_history_db.add_entry(audio_file, user)
        #make channel be the current channel
        if channel == "":
            channel = self.temp_channel
        self.temp_channel = channel
        voice_client = discord.utils.get(self.bot.voice_clients, guild=channel.guild)
        bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
        if bot_channel and not is_entrance and not is_tts:
            if extra != "": 
                embed = discord.Embed(
                    title=f"🔊 **{audio_file.split('/')[-1].replace('.mp3', '')}** 🔊",
                    description= f"Similarity: {extra}%",
                    color=self.color
                )
            else:
                embed = discord.Embed(
                    title=f"🔊 **{audio_file.split('/')[-1].replace('.mp3', '')}** 🔊",
                    color=self.color
                )
            # Set the footer to show who requested the sound
            if original_message:
                embed.set_footer(text=f"{user} requested '{original_message}'")
            else:
                embed.set_footer(text=f"Requested by {user}")
            #delete last message
            self.view = ControlsView(self)
            self.embed = discord.Embed(thumbnail="https://i.imgur.com/RFmwCdu.png", color=self.color)
            # add footer
            self.embed.set_footer(text=f"Control Menu")

            # Add the view to the message
            if audio_file.split('/')[-1].replace('.mp3', '') != "slap":
                if extra != "":
                    await self.delete_message_components()
                    message = await bot_channel.send(embed=embed,view=SoundBeingPlayedView(self, audio_file))
                else:
                    await self.delete_message_components()
                    message = await bot_channel.send(embed=embed,view=SoundBeingPlayedView(self, audio_file))
                    # Store the new message with buttons
                    self.button_message = await bot_channel.send(view=self.view)

                # Start a new thread that will wait for 5 minutes then clear the buttons
                #asyncio.create_task(self.delayed_button_clean(message))
            
            
        audio_file_path =  os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds",audio_file))

        voice_client = discord.utils.get(self.bot.voice_clients, guild=channel.guild)

        if voice_client:
            # Move to new channel if needed and stop current audio if playing
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


    async def refresh_button_message(self):
        while True:  # This will run indefinitely
            await asyncio.sleep(119)  # Wait for 3 seconds
            try:
                if self.button_message:
                    await self.button_message.delete()
                    bot_channel = await self.get_bot_channel()
                    self.button_message = await bot_channel.send(embed=self.embed, view=self.view)
            except Exception as e:
                print("The message was not found. It may have been deleted.",e)

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
                    #if channel is not None:
                        #await self.disconnect_all_bots(guild)
                sleep_time = random.uniform(0, 800)
                self.bot.next_download_time = time.time() + sleep_time
                while time.time() < self.bot.next_download_time:
                    await self.update_bot_status_once()
                    await asyncio.sleep(60)
                # Playing the audio after ensuring that time_left has reached 0 or less
                for guild in self.bot.guilds:
                    channel = self.get_largest_voice_channel(guild)
                    if channel is not None:
    
                        random_file = self.db.get_random_filename()
                        
                        await self.play_audio(channel, random_file, "periodic function")
                    else:
                        await asyncio.sleep(sleep_time)
            except Exception as e:
                print(f"1An error occurred: {e}")
                await asyncio.sleep(60) # if an error occurred, try again in 1 minute

    async def play_random_sound(self, user="admin"):
        try:
            for guild in self.bot.guilds:
                channel = self.get_largest_voice_channel(guild)
                if channel is not None:
                    asyncio.create_task(self.play_audio(channel, self.db.get_random_filename(),user))
        except Exception as e:
            print(f"2An error occurred: {e}")

    def randomize_color(self):
        # from all discord.colors choose a random one that is different from the current color
        temp_color = discord.Color.random()
        while temp_color == self.color:
            temp_color = discord.Color.random()
        self.color = temp_color
    
    async def play_request(self, id, user):
        filenames = self.db.get_most_similar_filenames(id,5)
        filename = filenames[0][1] if filenames else None
        similarity = filenames[0][0] if filenames else None
        for guild in self.bot.guilds:
            channel = self.get_largest_voice_channel(guild)
            if channel is not None:
                
                asyncio.create_task(self.play_audio(channel, filename, user,extra=similarity, original_message=id))
                # after waiting 2 seconds, if there are multiple sounds with similarity > 50, send message of each sound > 50 similarity
                await asyncio.sleep(2)
                bot_channel = await self.get_bot_channel()
                similar_sounds = [f"{filename[1]}" for filename in filenames[1:] if filename[0] > 70]
                if similar_sounds:
                    embed = discord.Embed(title="Maybe you meant one of these?", color=self.color)
                    view = SoundSimilarView(self, similar_sounds)
                    await bot_channel.send(view=view, embed=embed)
                # Store the new message with buttons
                self.button_message = await bot_channel.send(embed=self.embed, view=self.view)

    async def change_filename(self, oldfilename, newfilename):
        await self.db.modify_filename(oldfilename, newfilename)
                    
    async def tts(self, speech, lang="en", region=""):
        await self.TTS.save_as_mp3(speech, lang, region)     

    async def stt(self, audio_files):
        return await self.TTS.speech_to_text(audio_files)
    
    async def list_sounds(self):
        try:
            for guild in self.bot.guilds:
                channel = self.get_largest_voice_channel(guild)
                if channel is not None:
                    bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
                    
                    if bot_channel:
                        with open(self.db_path, 'rb') as file:
                            # Sending the .csv file to the chat
                            await bot_channel.send(file=discord.File(file, 'Data/soundsDB.csv'))
                        print(f"csv sent to the chat.")
                        return
                    
        except Exception as e:
            print(f"3An error occurred: {e}")
