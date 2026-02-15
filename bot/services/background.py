import asyncio
import os
import random
import time
from typing import Any, Optional
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
            if not self.check_voice_activity_loop.is_running():
                self.check_voice_activity_loop.start()
            if not self.ensure_last_message_controls_button_loop.is_running():
                self.ensure_last_message_controls_button_loop.start()
            print("[BackgroundService] Background tasks started.")

    @staticmethod
    def _is_message_from_bot(message: discord.Message, bot_user: Optional[discord.User]) -> bool:
        """Return True when a message was authored by this bot."""
        if not message or not bot_user:
            return False
        return message.author == bot_user

    @staticmethod
    def _find_available_component_row(
        message: discord.Message,
        view: discord.ui.View,
    ) -> Optional[int]:
        """Find an available row using live message component widths first."""
        rows = getattr(message, "components", None) or []
        if rows:
            for row_index, row in enumerate(rows):
                row_children = getattr(row, "children", None) or []
                if len(row_children) < 5:
                    return row_index
            if len(rows) < 5:
                return len(rows)
            return None

        # Fallback when message.components is unavailable.
        row_counts = {row: 0 for row in range(5)}
        for item in view.children:
            row = getattr(item, "row", None)
            if row is None:
                continue
            if row in row_counts:
                row_counts[row] += 1

        for row, count in row_counts.items():
            if count < 5:
                return row
        return None

    @staticmethod
    def _message_components_have_send_controls_button(message: discord.Message) -> bool:
        """Return True when raw message components include the inline controls button."""
        rows = getattr(message, "components", None) or []
        for row in rows:
            components = getattr(row, "children", None) or getattr(row, "components", None) or []
            for component in components:
                custom_id = getattr(component, "custom_id", None)
                if custom_id == "send_controls_button":
                    return True

                emoji = getattr(component, "emoji", None)
                if emoji is None:
                    continue
                emoji_name = getattr(emoji, "name", None) or str(emoji)
                emoji_normalized = emoji_name.replace("\ufe0f", "").replace("\ufe0e", "").strip()
                label = (getattr(component, "label", "") or "").strip()
                if "⚙" in emoji_normalized and label == "":
                    return True

        return False

    @staticmethod
    def _view_has_send_controls_button(view: discord.ui.View) -> bool:
        """Return True when a reconstructed view already contains a gear button."""
        for item in getattr(view, "children", []):
            custom_id = getattr(item, "custom_id", None)
            if isinstance(custom_id, str) and "send_controls_button" in custom_id:
                return True

            emoji = getattr(item, "emoji", None)
            if emoji is None:
                continue

            emoji_text = (getattr(emoji, "name", None) or str(emoji)).replace("\ufe0f", "").replace("\ufe0e", "").strip()
            label = (getattr(item, "label", "") or "").strip()
            if "⚙" in emoji_text and label == "":
                return True
        return False

    async def _add_controls_button_to_message(self, message: discord.Message) -> bool:
        """Attach an inline controls button to a message if component space allows."""
        if self._message_components_have_send_controls_button(message):
            return True

        try:
            view = discord.ui.View.from_message(message)
        except Exception:
            return False

        if self._view_has_send_controls_button(view):
            return True

        row = self._find_available_component_row(message, view)
        if row is None:
            return False

        style = discord.ButtonStyle.primary
        message_service = getattr(self.audio_service, "message_service", None)
        if message_service and hasattr(message_service, "_resolve_default_inline_controls_style"):
            message_format = "embed" if message.embeds else "image"
            embed_color = message.embeds[0].color if message.embeds else None
            style = message_service._resolve_default_inline_controls_style(
                message_format=message_format,
                color=embed_color,
                image_border_color=None,
            )

        from bot.ui.buttons.sounds import SendControlsButton
        try:
            view.add_item(SendControlsButton(style=style, row=row))
            await message.edit(view=view)
            return True
        except Exception as e:
            print(f"[BackgroundService] Failed to add controls button: {e}")
            return False

    async def _ensure_controls_button_on_last_bot_message_for_guild(self, guild: discord.Guild) -> None:
        """Normalize controls buttons in recent messages for one guild bot channel."""
        message_service = getattr(self.audio_service, "message_service", None)
        if not message_service:
            return

        channel = message_service.get_bot_channel(guild)
        if not channel:
            return

        recent_messages = []
        async for message in channel.history(limit=10):
            recent_messages.append(message)

        if not recent_messages:
            return

        bot_messages = [
            message
            for message in recent_messages
            if self._is_message_from_bot(message, self.bot.user)
        ]
        if not bot_messages:
            return

        # Remove controls button from all bot-authored recent messages.
        for message in bot_messages:
            if hasattr(self.audio_service, "_remove_send_controls_button_from_message"):
                await self.audio_service._remove_send_controls_button_from_message(message)

        # Add one controls button back on the newest non-controls bot message.
        target_candidates = bot_messages
        if hasattr(self.audio_service, "_is_controls_menu_message"):
            target_candidates = [
                message for message in bot_messages
                if not self.audio_service._is_controls_menu_message(message)
            ]

        for target_message in target_candidates:
            added = await self._add_controls_button_to_message(target_message)
            if added:
                break

    async def _notify_scraper_start(self) -> None:
        """Send a scraper start notification to the bot channel."""
        if not self.behavior:
            return

        try:
            await self.behavior.send_message(
                title="🔍 MyInstants scraper started",
                message_format="image",
                image_requester="MyInstants Scraper",
                image_show_footer=False,
                image_show_sound_icon=False,
                image_border_color="#ED4245",
            )
        except Exception as e:
            print(f"[BackgroundService] Failed to send scraper start message: {e}")

    async def _notify_scraper_complete(self, summary: dict[str, Any] | None) -> None:
        """Send a short scraper completion summary to the bot channel."""
        if not self.behavior:
            return

        summary = summary or {}
        countries_scanned = summary.get("countries_scanned", 0)
        total_sounds_seen = summary.get("total_sounds_seen", 0)
        detected = summary.get("new_sounds_detected", 0)
        added = summary.get("sounds_added", 0)
        invalid = summary.get("sounds_invalid", 0)
        scrape_errors = summary.get("scrape_errors", 0)
        duration_seconds = summary.get("duration_seconds", 0)

        description = (
            f"{countries_scanned} sites checked in {duration_seconds}s | "
            f"{total_sounds_seen} sounds seen | "
            f"{detected} new sounds found ({added} downloaded) | "
            f"{invalid} skipped/invalid"
        )
        if scrape_errors:
            description += f" | {scrape_errors} site errors"

        try:
            await self.behavior.send_message(
                title="✅ MyInstants scraper finished",
                description=description,
                message_format="image",
                image_requester="MyInstants Scraper",
                image_show_footer=False,
                image_show_sound_icon=False,
                image_border_color="#ED4245",
            )
        except Exception as e:
            print(f"[BackgroundService] Failed to send scraper completion message: {e}")

    async def _notify_scraper_failure(self, error: Exception) -> None:
        """Send a short scraper failure summary to the bot channel."""
        if not self.behavior:
            return

        error_text = str(error).strip() or "Unknown error"
        if len(error_text) > 180:
            error_text = f"{error_text[:177]}..."

        try:
            await self.behavior.send_message(
                title="⚠️ MyInstants scraper failed",
                description=error_text,
                message_format="image",
                image_requester="MyInstants Scraper",
                image_show_footer=False,
                image_show_sound_icon=False,
                image_border_color="#ED4245",
            )
        except Exception as notify_error:
            print(f"[BackgroundService] Failed to send scraper failure message: {notify_error}")

    @tasks.loop(seconds=30)
    async def keyword_detection_health_check(self):
        """
        Periodically check if keyword detection is running when bot is connected.
        
        This handles the case where the bot disconnects randomly and the STT stops
        but never gets restarted. It also checks if the worker thread is alive,
        since Discord voice reconnections can stop the worker without removing the sink.
        
        Additionally detects and cleans up zombie voice connections (broken WebSocket
        state after shard reconnection) that cause 'Already connected' errors.
        """
        try:
            for guild in self.bot.guilds:
                voice_client = guild.voice_client
                
                # Check for zombie/broken voice client (e.g., after shard reconnect)
                if voice_client:
                    ws = getattr(voice_client, 'ws', None)
                    is_zombie = ws is None or str(type(ws)) == "<class 'discord.utils._MissingSentinel'>"
                    
                    if is_zombie:
                        # Check if reconnection is already in progress (grace period)
                        if self.audio_service.is_reconnection_pending(guild.id):
                            remaining = self.audio_service.get_reconnection_remaining(guild.id)
                            print(f"[BackgroundService] Reconnection in progress ({remaining:.1f}s remaining), skipping zombie cleanup for {guild.name}...")
                            continue  # Skip this guild, let the ongoing reconnection complete
                        
                        print(f"[BackgroundService] Health check: Zombie voice client detected in {guild.name}, forcing cleanup...")
                        try:
                            await self.audio_service.stop_keyword_detection(guild)
                            await voice_client.disconnect(force=True)
                            await asyncio.sleep(1)
                            # Reconnect to largest populated channel
                            channel = self.audio_service.get_largest_voice_channel(guild)
                            if channel and len([m for m in channel.members if not m.bot]) > 0:
                                await self.audio_service.ensure_voice_connected(channel)
                                print(f"[BackgroundService] Health check: Reconnected to {channel.name} after zombie cleanup")
                        except Exception as e:
                            print(f"[BackgroundService] Error cleaning up zombie connection: {e}")
                        continue  # Skip normal checks for this guild since we just reconnected
                
                # Normal health checks - only if voice client is actually connected
                if voice_client and voice_client.is_connected():
                    sink = self.audio_service.keyword_sinks.get(guild.id)
                    
                    if sink is None:
                        # No sink at all - start keyword detection
                        print(f"[BackgroundService] Health check: Keyword detection not running in {guild.name}, starting...")
                        await self.audio_service.start_keyword_detection(guild)
                    elif hasattr(sink, 'worker_thread') and not sink.worker_thread.is_alive():
                        # Sink exists but worker thread is dead - restart keyword detection
                        print(f"[BackgroundService] Health check: VoskWorker thread dead in {guild.name}, restarting keyword detection...")
                        await self.audio_service.stop_keyword_detection(guild)
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
                    elif minutes >= 60:
                        hours = round(minutes / 60)
                        status_parts.append(f'🤯 in ~{hours}h')
                    else:
                        status_parts.append(f'🤯 in ~{minutes}m')
            
            # 2. AI Commentary (Ventura) status
            if self.behavior and hasattr(self.behavior, '_ai_commentary_service'):
                ai_service = self.behavior._ai_commentary_service
                if not ai_service.enabled:
                    status_parts.append('👂🏻 ❌')
                else:
                    ai_cooldown_seconds = ai_service.get_cooldown_remaining()
                    ai_minutes = round(ai_cooldown_seconds / 60)
                    if ai_cooldown_seconds > 0:
                        if ai_minutes >= 60:
                            ai_hours = round(ai_minutes / 60)
                            status_parts.append(f'👂🏻 in ~{ai_hours}h')
                        else:
                            status_parts.append(f'👂🏻 in ~{ai_minutes}m')
                    else:
                        status_parts.append('👂🏻')

            # 3. Scraper status
            if hasattr(self.bot, 'next_scrape_time'):
                scrape_time_left = self.bot.next_scrape_time - time.time()
                if scrape_time_left > 0:
                    scrape_minutes = round(scrape_time_left / 60)
                    if scrape_minutes >= 60:
                        scrape_hours = round(scrape_minutes / 60)
                        status_parts.append(f'🔍 in ~{scrape_hours}h')
                    else:
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
                        # Skip if channel is empty (no non-bot members)
                        non_bot_members = [m for m in channel.members if not m.bot]
                        if not non_bot_members:
                            print(f"[BackgroundService] Skipping periodic sound in {guild.name} - no users in channel")
                            continue
                        
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
                    await asyncio.sleep(60)
                first_run = False
                
                # Run the scraper in a thread executor since it uses Selenium (blocking)
                print("[BackgroundService] Starting MyInstants scraper...")
                await self._notify_scraper_start()
                loop = asyncio.get_event_loop()
                
                # Create scraper instance - needs behavior reference for db
                # We'll use a fresh Database instance since the scraper does that internally
                from bot.database import Database
                db = Database()
                downloader = SoundDownloader(None, db, os.getenv("CHROMEDRIVER_PATH"))
                
                # Run blocking download_sound in executor
                summary = await loop.run_in_executor(None, downloader.download_sound)
                print("[BackgroundService] MyInstants scrape completed")
                await self._notify_scraper_complete(summary)
                
            except Exception as e:
                print(f"[BackgroundService] Error in scrape_sounds_loop: {e}")
                await self._notify_scraper_failure(e)
                await asyncio.sleep(60)  # Wait a minute before retrying on error


    @tasks.loop(seconds=60)
    async def check_voice_activity_loop(self):
        """
        Periodically check if the bot is alone in a voice channel and disconnect if so.
        This serves as a backup to the event-based auto-disconnect.
        """
        try:
            for guild in self.bot.guilds:
                if guild.voice_client and guild.voice_client.is_connected():
                    channel = guild.voice_client.channel
                    if not channel:
                        continue
                        
                    # Count non-bot members
                    non_bot_members = [m for m in channel.members if not m.bot]
                    
                    if len(non_bot_members) == 0:
                        print(f"[BackgroundService] Bot is alone in {channel.name} ({guild.name}), disconnecting...")
                        try:
                            # Stop keyword detection before disconnecting
                            if self.behavior and hasattr(self.behavior, '_audio_service'):
                                await self.behavior._audio_service.stop_keyword_detection(guild)
                            elif self.audio_service:
                                await self.audio_service.stop_keyword_detection(guild)
                                
                            await guild.voice_client.disconnect()
                            print(f"[BackgroundService] Disconnected from {channel.name}")
                        except Exception as e:
                            print(f"[BackgroundService] Error disconnecting from {channel.name}: {e}")

        except Exception as e:
            print(f"[BackgroundService] Error in voice activity check: {e}")

    @tasks.loop(seconds=60)
    async def ensure_last_message_controls_button_loop(self):
        """Every minute, normalize controls button presence in the latest 10 messages."""
        try:
            for guild in self.bot.guilds:
                await self._ensure_controls_button_on_last_bot_message_for_guild(guild)
        except Exception as e:
            print(f"[BackgroundService] Error ensuring controls button on latest message: {e}")
