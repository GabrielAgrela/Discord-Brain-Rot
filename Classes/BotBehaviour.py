import asyncio
import time
import discord
import random
from Classes.SoundDownloader import SoundDownloader

class BotBehavior:
    def __init__(self, bot, ffmpeg_path):
        self.bot = bot
        self.ffmpeg_path = ffmpeg_path
        self.sound_downloader = SoundDownloader()
        self.last_channel = {}
        self.playback_done = asyncio.Event()

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

    async def play_audio(self, channel, audio_file):
        voice_client = await channel.connect()
        self.playback_done.clear() # Clearing the flag before starting the audio

        def after_playing(error):
            if error:
                print(f'Error in playback: {error}')
            else:
                self.playback_done.set()

        voice_client.play(
            discord.FFmpegPCMAudio(executable=self.ffmpeg_path, source=audio_file),
            after=after_playing
        )

        # Wait for the audio to finish playing
        await self.playback_done.wait()

        if voice_client.is_connected():
            await voice_client.disconnect()



    async def update_bot_status_once(self):
        if hasattr(self.bot, 'next_download_time'):
            time_left = self.bot.next_download_time - time.time()
            if time_left > 0:
                minutes = round(time_left / 60)
                if minutes == 0:
                    activity = discord.Activity(name=f'explosion imminent!!!', type=discord.ActivityType.playing)
                else:
                    activity = discord.Activity(name=f'an explosion in ~{minutes}m', type=discord.ActivityType.playing)
                await self.bot.change_presence(activity=activity)



    async def update_bot_status(self):
        while True:
            await self.update_bot_status_once()
            await asyncio.sleep(60)

    async def download_sound_periodically(self):
        while True:
            try:
                self.sound_downloader.download_sound()
                await asyncio.sleep(1)
                for guild in self.bot.guilds:
                    channel = self.get_largest_voice_channel(guild)
                    if channel is not None:
                        await self.disconnect_all_bots(guild)
                sleep_time = random.uniform(0, 8000)
                self.bot.next_download_time = time.time() + sleep_time
                print("time ", time.time(), " next ", self.bot.next_download_time, " diff  ",  self.bot.next_download_time-time.time())
                while time.time() < self.bot.next_download_time:
                    await self.update_bot_status_once()
                    await asyncio.sleep(60)
                # Playing the audio after ensuring that time_left has reached 0 or less
                for guild in self.bot.guilds:
                    channel = self.get_largest_voice_channel(guild)
                    if channel is not None:
                        await self.play_audio(channel, r"H:\bup82623\Downloads\random.mp3")
                    else:
                        await asyncio.sleep(sleep_time)
            except Exception as e:
                print(f"An error occurred: {e}")
                await asyncio.sleep(60) # if an error occurred, try again in 1 minute
    
    async def download_sound_and_play(self):
        try:
            #time.sleep(1)
            for guild in self.bot.guilds:
                channel = self.get_largest_voice_channel(guild)
                if channel is not None:
                    await self.play_audio(channel, r"H:\bup82623\Downloads\random.mp3")
                    self.sound_downloader.download_sound()
        except Exception as e:
            print(f"An error occurred: {e}")

