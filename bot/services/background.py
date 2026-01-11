import asyncio
import os
import random
import time
import discord
from discord.ext import tasks
from bot.repositories import SoundRepository, ActionRepository
from bot.downloaders.sound import SoundDownloader

class BackgroundService:
    """
    Service for background tasks like status updates, periodic sound playback,
    and MyInstants scraping.
    """
    
    def __init__(self, bot, audio_service, sound_service, behavior=None):
        self.bot = bot
        self.audio_service = audio_service
        self.sound_service = sound_service
        self.behavior = behavior # BotBehavior instance
        
        # Repositories
        self.sound_repo = SoundRepository()
        self.action_repo = ActionRepository()
        
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
            if not self.scrape_sounds_loop.is_running():
                self.scrape_sounds_loop.start()
            if not self.keyword_detection_health_check.is_running():
                self.keyword_detection_health_check.start()
            print("[BackgroundService] Background tasks started.")

    @tasks.loop(seconds=30)
    async def keyword_detection_health_check(self):
        """
        Periodically check if keyword detection is running when bot is connected.
        
        This handles the case where the bot disconnects randomly and the STT stops
        but never gets restarted.
        """
        try:
            for guild in self.bot.guilds:
                voice_client = guild.voice_client
                # If bot is connected to voice but keyword detection is not running, restart it
                if voice_client and voice_client.is_connected():
                    if guild.id not in self.audio_service.keyword_sinks:
                        print(f"[BackgroundService] Health check: Keyword detection not running in {guild.name}, restarting...")
                        await self.audio_service.start_keyword_detection(guild)
        except Exception as e:
            print(f"[BackgroundService] Error in keyword detection health check: {e}")

    @tasks.loop(seconds=60)
    async def update_bot_status_loop(self):
        """Continuously update the bot's status based on next explosion time and AI cooldown."""
        try:
            status_parts = []
            
            # 1. Periodic sound (explosion) status
            if hasattr(self.bot, 'next_download_time'):
                time_left = self.bot.next_download_time - time.time()
                if time_left > 0:
                    minutes = round(time_left / 60)
                    if minutes < 1:
                        status_parts.append('🤯')
                    else:
                        status_parts.append(f'🤯 in ~{minutes}m')
            
            # 2. AI Commentary (Ventura) status
            if self.behavior and hasattr(self.behavior, '_ai_commentary_service'):
                ai_cooldown_seconds = self.behavior._ai_commentary_service.get_cooldown_remaining()
                ai_minutes = round(ai_cooldown_seconds / 60)
                if ai_cooldown_seconds > 0:
                    status_parts.append(f'👂🏻 in ~{ai_minutes}m')
                else:
                    status_parts.append('👂🏻')

            # 3. Scraper status
            if hasattr(self.bot, 'next_scrape_time'):
                scrape_time_left = self.bot.next_scrape_time - time.time()
                if scrape_time_left > 0:
                    scrape_minutes = round(scrape_time_left / 60)
                    status_parts.append(f'🔍 in ~{scrape_minutes}m')
                else:
                    status_parts.append('🔍')

            if status_parts:
                status_text = " | ".join(status_parts)
                activity = discord.Activity(name=status_text, type=discord.ActivityType.playing)
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
                        random_sounds = self.sound_repo.get_random_sounds(num_sounds=1)
                        if random_sounds:
                            sound = random_sounds[0]
                            print(f"[BackgroundService] Playing periodic sound: {sound[2]} in {guild.name}")
                            await self.audio_service.play_audio(channel, sound[2], "periodic function")
                            self.action_repo.insert("admin", "play_sound_periodically", sound[0])
                            
            except Exception as e:
                print(f"[BackgroundService] Error in periodic playback: {e}")
                await asyncio.sleep(60)  # Wait a minute before retrying on error

    @tasks.loop(count=1)
    async def scrape_sounds_loop(self):
        """Periodically scrape new sounds from MyInstants."""
        await self.bot.wait_until_ready()
        
        first_run = True
        while not self.bot.is_closed():
            try:
                if not first_run:
                    # Wait 8h between scrapes
                    sleep_time = 60*60*8
                    self.bot.next_scrape_time = time.time() + sleep_time
                    print(f"[BackgroundService] Next MyInstants scrape in {int(sleep_time/60)} minutes")
                    await asyncio.sleep(sleep_time)
                else:
                    # Set initial scrape time to 0 so it shows "scraping..." on first run
                    self.bot.next_scrape_time = 0
                    #wait 1 minute first time
                    await asyncio.sleep(0)
                first_run = False
                
                # Run the scraper in a thread executor since it uses Selenium (blocking)
                print("[BackgroundService] Starting MyInstants scraper...")
                loop = asyncio.get_event_loop()
                
                # Create scraper instance - needs behavior reference for db
                # We'll use a fresh Database instance since the scraper does that internally
                from bot.database import Database
                db = Database()
                downloader = SoundDownloader(None, db, os.getenv("CHROMEDRIVER_PATH"))
                
                # Run blocking download_sound in executor
                await loop.run_in_executor(None, downloader.download_sound)
                print("[BackgroundService] MyInstants scrape completed")
                
            except Exception as e:
                print(f"[BackgroundService] Error in scrape_sounds_loop: {e}")
                await asyncio.sleep(60)  # Wait a minute before retrying on error

