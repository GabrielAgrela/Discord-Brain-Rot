import asyncio
import random
import time
import discord
from discord.ext import tasks
from bot.database import Database

class BackgroundService:
    """
    Service for background tasks like status updates and periodic sound playback.
    """
    
    def __init__(self, bot, audio_service, sound_service):
        self.bot = bot
        self.audio_service = audio_service
        self.sound_service = sound_service
        self.db = Database()
        self._started = False

    def start_tasks(self):
        """Schedule tasks to start when the bot is ready."""
        if self._started:
            return
        self._started = True
        
        # Register with bot's on_ready event
        @self.bot.listen('on_ready')
        async def on_ready_start_tasks():
            if not self.update_bot_status_loop.is_running():
                self.update_bot_status_loop.start()
            if not self.play_sound_periodically_loop.is_running():
                self.play_sound_periodically_loop.start()
            print("[BackgroundService] Background tasks started.")

    @tasks.loop(seconds=60)
    async def update_bot_status_loop(self):
        """Continuously update the bot's status based on next explosion time."""
        try:
            if hasattr(self.bot, 'next_download_time'):
                time_left = self.bot.next_download_time - time.time()
                if time_left > 0:
                    minutes = round(time_left / 60)
                    if minutes < 2:
                        activity = discord.Activity(name='explosion imminent!!!', type=discord.ActivityType.playing)
                    else:
                        activity = discord.Activity(name=f'an explosion in ~{minutes}m', type=discord.ActivityType.playing)
                    await self.bot.change_presence(activity=activity)
        except Exception as e:
            print(f"[BackgroundService] Error updating status: {e}")

    @tasks.loop(count=1)
    async def play_sound_periodically_loop(self):
        """Randomly play sounds at random intervals (10-30 minutes)."""
        await self.bot.wait_until_ready()
        
        while not self.bot.is_closed():
            try:
                # Set random wait time (10-30 minutes)
                sleep_time = random.uniform(60*3, 60*15)
                self.bot.next_download_time = time.time() + sleep_time
                
                await asyncio.sleep(sleep_time)
                
                # Play sound in each guild
                for guild in self.bot.guilds:
                    channel = self.audio_service.get_largest_voice_channel(guild)
                    if channel:
                        random_sounds = self.db.get_random_sounds(num_sounds=1)
                        if random_sounds:
                            sound = random_sounds[0]
                            print(f"[BackgroundService] Playing periodic sound: {sound[2]} in {guild.name}")
                            await self.audio_service.play_audio(channel, sound[2], "periodic function")
                            self.db.insert_action("admin", "play_sound_periodically", sound[0])
                            
            except Exception as e:
                print(f"[BackgroundService] Error in periodic playback: {e}")
                await asyncio.sleep(60)  # Wait a minute before retrying on error
