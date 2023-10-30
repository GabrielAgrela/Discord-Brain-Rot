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

class BotBehavior:
    def __init__(self, bot, ffmpeg_path):
        self.bot = bot
        self.ffmpeg_path = ffmpeg_path
        self.sound_downloader = SoundDownloader()
        self.last_channel = {}
        self.playback_done = asyncio.Event()
        # Usage example
        self.db = AudioDatabase('Data/soundsDB.csv')
        self.player_history_db = PlayHistoryDatabase('Data/play_history.csv',self.db)
        

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

    async def play_audio(self, channel, audio_file,user, is_entrance=False):
        print("USER------------", user)
        self.player_history_db.add_entry(audio_file, user)
        voice_client = discord.utils.get(self.bot.voice_clients, guild=channel.guild)
        bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
        
        if bot_channel and not is_entrance:
            #delete last message
            await bot_channel.send(f"🎶{audio_file.split('/')[-1].replace('.mp3', '')}🎶")
            
            
        audio_file = "H:/bup82623/Downloads/sounds/"+audio_file
        # If the bot is already connected to a voice channel in the guild
        if voice_client:
            if voice_client.is_playing():
                voice_client.stop()
            # Check if the bot is not in the target channel
            if voice_client.channel != channel:
                await voice_client.move_to(channel)  # Move the bot to the new channel
        else:
            # Connect to the target channel if the bot was not connected to any channel
            try:
                voice_client = await channel.connect()
            except Exception as e:
                print(f"Error connecting to channel: {e}")
                return

        self.playback_done.clear()  # Clearing the flag before starting the audio

        def after_playing(error):
            if error:
                print(f'Error in playback: {error}')
            else:
                self.playback_done.set()

        try:
            
            print(audio_file)
            voice_client.play(
                discord.FFmpegPCMAudio(executable=self.ffmpeg_path, source=audio_file),
                after=after_playing
            )
        except Exception as e:
            print(f"An error occurred: {e}")
            try:
                await voice_client.disconnect()
            except:
                pass

        print("playing")
        # Wait for the audio to finish playing
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
                        
                        await self.play_audio(channel, random_file)
                    else:
                        await asyncio.sleep(sleep_time)
            except Exception as e:
                print(f"An error occurred: {e}")
                await asyncio.sleep(60) # if an error occurred, try again in 1 minute

    async def play_random_sound(self):
        try:
            for guild in self.bot.guilds:
                channel = self.get_largest_voice_channel(guild)
                if channel is not None:
                    asyncio.create_task(self.play_audio(channel, self.db.get_random_filename(),"admin"))
                    print("playing")
        except Exception as e:
            print(f"An error occurred: {e}")

    async def download_sound_periodically(self):
        while True:
            thread = threading.Thread(target=self.sound_downloader.download_sound)
            thread.start()
            await asyncio.sleep(60)
    
    async def play_request(self, id, user):
        distance, filename = self.db.get_most_similar_filename(id)
        for guild in self.bot.guilds:
            channel = self.get_largest_voice_channel(guild)
            if channel is not None:
                asyncio.create_task(self.play_audio(channel, filename,user))
                #bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
                #if bot_channel:
                    #await bot_channel.send(f"🎶{distance}🎶 ")

    async def change_filename(self, oldfilename, newfilename):
        print("oldfilename: ", oldfilename, " newfilename: ", newfilename)
        self.db.modify_filename(oldfilename, newfilename)
                    
            
    
    

    async def list_sounds(self):
        try:
            for guild in self.bot.guilds:
                channel = self.get_largest_voice_channel(guild)
                if channel is not None:
                    bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
                    
                    if bot_channel:
                        with open("Data/soundsDB.csv", 'rb') as file:
                            # Sending the .csv file to the chat
                            await bot_channel.send(file=discord.File(file, 'Data/soundsDB.csv'))
                        print(f"csv sent to the chat.")
                        return
                    
        except Exception as e:
            print(f"An error occurred: {e}")



    

