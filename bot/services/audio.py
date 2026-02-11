import asyncio
import os
import discord
import time
import functools
import threading
import io
import wave
import json
import audioop
import queue
from datetime import datetime
import traceback
from typing import Optional, List, Dict, Any
from mutagen.mp3 import MP3
import speech_recognition as sr
import vosk
from discord import sinks
from bot.repositories import (
    SoundRepository, ActionRepository, ListRepository, 
    StatsRepository, KeywordRepository, EventRepository
)
from bot.services.image_generator import ImageGeneratorService

class AudioService:
    """
    Service for managing voice connections and audio playback.
    
    Attributes:
        bot: Discord bot instance
        ffmpeg_path: Path to ffmpeg executable
        mute_service: Service to check for mute status
        message_service: Service to send status messages
    """
    
    def __init__(self, bot, ffmpeg_path, mute_service, message_service):
        self.bot = bot
        self.ffmpeg_path = ffmpeg_path
        self.mute_service = mute_service
        self.message_service = message_service
        
        # Repositories
        self.sound_repo = SoundRepository()
        self.action_repo = ActionRepository()
        self.list_repo = ListRepository()
        self.stats_repo = StatsRepository()
        self.keyword_repo = KeywordRepository()
        self.event_repo = EventRepository()
        
        # Audio state moved from BotBehavior
        self.last_played_time: Optional[datetime] = None
        self.current_sound_message: Optional[discord.Message] = None
        self.stop_progress_update = False
        self.progress_already_updated = False
        self.cooldown_message: Optional[discord.Message] = None
        self.current_similar_sounds: Optional[List[Any]] = None
        self.volume = 1.0
        self.playback_done = asyncio.Event()
        self.volume = 1.0
        self.playback_done = asyncio.Event()
        self.playback_done.set()
        
        # Track current view to update progress button
        self.current_view: Optional[discord.ui.View] = None
        

        
        # Keyword detection state
        self.keyword_sinks: Dict[int, 'KeywordDetectionSink'] = {}
        
        # Per-guild connection locks to prevent race conditions
        self._connection_locks: Dict[int, asyncio.Lock] = {}
        self._pending_connections: Dict[int, asyncio.Task] = {}
        
        # Reconnection debounce: track when reconnection started to avoid competing reconnects
        self._reconnection_timestamps: Dict[int, float] = {}
        self.RECONNECTION_GRACE_PERIOD = 15.0  # Seconds to wait before health checks intervene
        
        # Buffer for /llmdebug (handled via ring buffer in sink)
        self.last_audio_buffer: Dict[int, bytes] = {} 
        
        # Initialize Vosk model for local STT
        try:
            # Silence internal Vosk logs to avoid spamming the console
            vosk.SetLogLevel(-1)
            model_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Data", "models", "vosk-model-small-pt-0.3"))
            if os.path.exists(model_path):
                print(f"[AudioService] Loading Vosk model from {model_path}...")
                self.vosk_model = vosk.Model(model_path)
                print("[AudioService] Vosk model loaded successfully.")
            else:
                print(f"[AudioService] Warning: Vosk model not found at {model_path}")
                self.vosk_model = None
        except Exception as e:
            print(f"[AudioService] Error loading Vosk model: {e}")
            self.vosk_model = None
        
        # Dependency on other services that will be added later
        self.sound_service = None
        self.voice_transformation_service = None
        
        # Image generator for sound cards
        self.image_generator = ImageGeneratorService()

    def _format_duration(self, seconds: float) -> str:
        """Format seconds into mm:ss string."""
        if seconds < 0:
            seconds = 0
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"

    def set_sound_service(self, sound_service):
        self.sound_service = sound_service

    def set_voice_transformation_service(self, vt_service):
        self.voice_transformation_service = vt_service

    def set_behavior(self, behavior):
        """Set reference to BotBehavior for passing to views."""
        self._behavior = behavior
        self.bot.behavior = behavior

    def _get_connection_lock(self, guild_id: int) -> asyncio.Lock:
        """Get or create a connection lock for the given guild."""
        if guild_id not in self._connection_locks:
            self._connection_locks[guild_id] = asyncio.Lock()
        return self._connection_locks[guild_id]

    def is_reconnection_pending(self, guild_id: int) -> bool:
        """Check if a reconnection is in progress and within the grace period.
        
        Returns True if callers should wait/skip their own reconnection attempt.
        """
        if guild_id not in self._reconnection_timestamps:
            return False
        elapsed = time.time() - self._reconnection_timestamps[guild_id]
        return elapsed < self.RECONNECTION_GRACE_PERIOD

    def get_reconnection_remaining(self, guild_id: int) -> float:
        """Get seconds remaining in the reconnection grace period."""
        if guild_id not in self._reconnection_timestamps:
            return 0.0
        elapsed = time.time() - self._reconnection_timestamps[guild_id]
        remaining = self.RECONNECTION_GRACE_PERIOD - elapsed
        return max(0.0, remaining)

    def _mark_reconnection_started(self, guild_id: int):
        """Mark that a reconnection attempt has started for a guild."""
        self._reconnection_timestamps[guild_id] = time.time()

    def _clear_reconnection_state(self, guild_id: int):
        """Clear reconnection state after successful connection."""
        if guild_id in self._reconnection_timestamps:
            del self._reconnection_timestamps[guild_id]

    async def ensure_voice_connected(self, channel: discord.VoiceChannel) -> Optional[discord.VoiceProtocol]:
        """Ensure the bot is connected to the specified voice channel.
        
        Uses per-guild locks to prevent race conditions from rapid channel switches.
        """
        guild_id = channel.guild.id
        lock = self._get_connection_lock(guild_id)
        
        # Cancel any pending connection task for this guild
        if guild_id in self._pending_connections:
            pending_task = self._pending_connections[guild_id]
            if not pending_task.done():
                print(f"[AudioService] Cancelling pending connection for {channel.guild.name}")
                pending_task.cancel()
                try:
                    await pending_task
                except asyncio.CancelledError:
                    pass
        
        async with lock:
            try:
                print(f"[AudioService] [LOCK ACQUIRED] for {channel.guild.name}")
                voice_client = channel.guild.voice_client

                if voice_client:
                    # Check for broken/uninitialized voice client state
                    if not hasattr(voice_client, 'ws') or voice_client.ws is None or str(type(voice_client.ws)) == "<class 'discord.utils._MissingSentinel'>":
                        print(f"[AudioService] Detected broken voice client in {channel.guild.name}, cleaning up")
                        self._mark_reconnection_started(guild_id)
                        try:
                            await self.stop_keyword_detection(channel.guild)
                            await voice_client.disconnect(force=True)
                        except Exception as e:
                            print(f"[AudioService] Error cleaning up broken voice client: {e}")
                        voice_client = None
                        await asyncio.sleep(0.5)
                        
                    elif voice_client.is_connected() and (voice_client.average_latency == float('inf') or voice_client.average_latency is None):
                        print(f"[AudioService] Detected zombie voice client (infinite latency) in {channel.guild.name}, cleaning up")
                        self._mark_reconnection_started(guild_id)
                        try:
                            await self.stop_keyword_detection(channel.guild)
                            await voice_client.disconnect(force=True)
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            print(f"[AudioService] Error cleaning up zombie voice client: {e}")
                        voice_client = None

                    elif not voice_client.is_connected():
                        print(f"[AudioService] Voice client in {channel.guild.name} exists but is not connected. Reconnecting...")
                        self._mark_reconnection_started(guild_id)
                        try:
                            await self.stop_keyword_detection(channel.guild)
                            await voice_client.disconnect(force=True)
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            print(f"[AudioService] Error forcing disconnect: {e}")
                        voice_client = None
                        
                    elif voice_client.channel.id != channel.id:
                        print(f"[AudioService] Moving from {voice_client.channel.name} to {channel.name}")
                        try:
                            await voice_client.move_to(channel)
                        except asyncio.TimeoutError:
                            print(f"[AudioService] Timeout moving to {channel.name}. Reconnecting...")
                            await self.stop_keyword_detection(channel.guild)
                            await voice_client.disconnect(force=True)
                            await asyncio.sleep(0.5)
                            voice_client = None
                        if voice_client:
                            # Successfully moved, restart keyword detection
                            self._clear_reconnection_state(guild_id)
                            await self.start_keyword_detection(channel.guild)
                            return voice_client
                    else:
                        # Already connected to the right channel
                        # Perform one final check on the socket just to be safe
                        if hasattr(voice_client, 'socket') and voice_client.socket:
                             # Current connection is good
                             self._clear_reconnection_state(guild_id)
                             await self.start_keyword_detection(channel.guild)
                             return voice_client
                        else:
                             print(f"[AudioService] Voice client has no socket in {channel.guild.name}, reconnecting...")
                             self._mark_reconnection_started(guild_id)
                             try:
                                 await self.stop_keyword_detection(channel.guild)
                                 await voice_client.disconnect(force=True)
                                 await asyncio.sleep(0.5)
                             except Exception as e:
                                 print(f"[AudioService] Error cleaning up socket-less client: {e}")
                             voice_client = None
                
                # Connect with retry logic
                for attempt in range(3):
                    try:
                        # Check if another connection snuck in while we waited
                        voice_client = channel.guild.voice_client
                        if voice_client and voice_client.is_connected():
                            if voice_client.channel.id != channel.id:
                                await voice_client.move_to(channel)
                            await self.start_keyword_detection(channel.guild)
                            return voice_client
                        
                        
                        voice_client = await channel.connect(timeout=10.0)
                        # Give the voice connection a moment to fully establish
                        await asyncio.sleep(0.5)
                        # Start keyword detection on new connection
                        self._clear_reconnection_state(guild_id)
                        await self.start_keyword_detection(channel.guild)
                        return voice_client
                    except asyncio.CancelledError:
                        print(f"[AudioService] Connection cancelled for {channel.name}")
                        raise
                    except Exception as e:
                        print(f"[AudioService] Connection attempt {attempt + 1} failed: {e}")
                        if attempt < 2:
                            await asyncio.sleep(0.5)
                        else:
                            # Last attempt failed, but let's try one more time to start detection if voice client exists
                            voice_client = channel.guild.voice_client
                            if voice_client and voice_client.is_connected():
                                print(f"[AudioService] Connection retry failed but voice client exists. Starting keyword detection anyway.")
                                await self.start_keyword_detection(channel.guild)
                                return voice_client
                
                print("[AudioService] Failed to connect after 3 attempts.")
                return None

            except asyncio.CancelledError:
                print(f"[AudioService] Connection to {channel.name} was cancelled")
                return None
            except Exception as e:
                print(f"[AudioService] Error connecting to voice channel: {e}")
                traceback.print_exc()
                if self.bot.voice_clients:
                    return self.bot.voice_clients[0]
                return None

    def get_largest_voice_channel(self, guild: discord.Guild) -> Optional[discord.VoiceChannel]:
        """Find the voice channel with the most members in the given guild."""
        channels = [c for c in guild.voice_channels if not c.name.lower().startswith('afk')]
        if not channels:
            return None
        return max(channels, key=lambda c: len(c.members))

    def get_user_voice_channel(self, guild: discord.Guild, user_name: str) -> Optional[discord.VoiceChannel]:
        """Find the voice channel where a specific user is currently connected."""
        # Use member object if possible, or search by name
        # Discord removed discriminators, so we check for name only or name#discriminator (legacy)
        search_name = user_name.split('#')[0]
        
        for channel in guild.voice_channels:
            for member in channel.members:
                if member.name == search_name or str(member) == user_name:
                    return channel
        return None

    def is_playing_sound(self) -> bool:
        """Check if the bot is currently playing audio in any voice channel."""
        for vc in self.bot.voice_clients:
            if vc.is_playing():
                return True
        return False

    def is_channel_empty(self, channel: discord.VoiceChannel) -> bool:
        """Check if a voice channel has no non-bot members."""
        non_bot_members = [m for m in channel.members if not m.bot]
        return len(non_bot_members) == 0

    async def play_slap(self, channel, audio_file, user):
        """Play a slap sound - stops current audio, plays immediately, no embed."""
        try:
            voice_client = await self.ensure_voice_connected(channel)
            if not voice_client:
                return False

            # Stop any currently playing audio and mark as slapped
            if voice_client.is_playing():
                self.stop_progress_update = True  # Stop the progress bar animation
                # Update the current sound message with slap icon
                if self.current_sound_message and self.current_view:
                    try:
                        if hasattr(self.current_view, 'update_progress_emoji'):
                             self.current_view.update_progress_emoji('👋')
                             await self.current_sound_message.edit(view=self.current_view)
                    except:
                        pass
                voice_client.stop()
                await asyncio.sleep(0.1)  # Allow FFmpeg process to terminate cleanly


            audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Sounds", audio_file))
            if not os.path.exists(audio_file_path):
                print(f"[AudioService] Slap sound not found: {audio_file_path}")
                return False

            audio_source = discord.FFmpegPCMAudio(
                audio_file_path,
                executable=self.ffmpeg_path,
                before_options="-nostdin -fflags nobuffer -flags low_delay -analyzeduration 0 -probesize 32"
            )
            audio_source = discord.PCMVolumeTransformer(audio_source, volume=self.volume)
            
            voice_client.play(audio_source)
            return True
        except Exception as e:
            print(f"[AudioService] Error playing slap: {e}")
            return False

    async def play_audio(self, channel, audio_file, user, 
                        is_entrance=False, is_tts=False, extra="", 
                        original_message="", 
                        send_controls=False, retry_count=0, effects=None, 
                        show_suggestions: bool = True, 
                        num_suggestions: int = 25,
                        sts_char: str = None,
                        requester_avatar_url: str = None,
                        sts_thumbnail_url: str = None,
                        loading_message: 'discord.Message' = None):
        """Play an audio file in the specified voice channel."""
        print(f"[AudioService] play_audio(file={audio_file}, user={user}, guild={channel.guild.name})")
        MAX_RETRIES = 3

        if self.mute_service.is_muted:
            if self.message_service:
                await self.message_service.send_message(
                    title="🔇 Bot Muted",
                    description=f"Muted for {self.mute_service.get_remaining_formatted()}",
                    color=discord.Color.orange(),
                    delete_time=5
                )
            return

        # Check cooldown first
        if self.last_played_time and (datetime.now() - self.last_played_time).total_seconds() < 2:
            if self.cooldown_message is None and not is_entrance:
                bot_channel = self.message_service.get_bot_channel(channel.guild)
                if bot_channel:
                    self.cooldown_message = await bot_channel.send(
                        embed=discord.Embed(title="Don't be rude, let Gertrudes speak 😤")
                    )
                    await asyncio.sleep(3)
                    try:
                        await self.cooldown_message.delete()
                    except:
                        pass
                    self.cooldown_message = None
                    return
        self.last_played_time = datetime.now()

        # We'll update the previous sound's message only if we actually interrupt it
        # This flag will be set below if we detect we're interrupting playback
        previous_sound_message = self.current_sound_message
        was_interrupted = False

        try:
            self.current_similar_sounds = None
            voice_client = await self.ensure_voice_connected(channel)
            if not voice_client:
                return False

            # Check if we're actually interrupting playback
            if voice_client.is_playing():
                was_interrupted = True
                self.stop_progress_update = True
                voice_client.stop()
                await asyncio.sleep(0.1)  # Allow FFmpeg process to terminate cleanly
                
                # Update the previous sound's message with skip emoji
                if previous_sound_message: 
                    # Use tracked current_view which corresponds to the sound being stopped
                    if self.current_view and hasattr(self.current_view, 'update_progress_emoji'):
                         try:
                             self.current_view.update_progress_emoji('⏭️')
                             await previous_sound_message.edit(view=self.current_view)
                         except:
                             pass
                    pass # Original logic relied on msg content, but now we use view buttons.
                         # If we don't have the view object, we can't update the button easily without
                         # retrieving the view from the message components, which is complex.
                         # For now, relying on self.current_view is the best bet as it points to the 
                         # sound we are about to stop.

            if not isinstance(audio_file, str):
                audio_file = str(audio_file)

            audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Sounds", audio_file))

            if not os.path.exists(audio_file_path):
                sound_info = self.sound_repo.get_sound(audio_file, False)
                if sound_info:
                    original_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Sounds", sound_info[1]))
                    if os.path.exists(original_path):
                        audio_file_path = original_path
                    else:
                        sound_info_orig = self.sound_repo.get_sound(audio_file, True)
                        if sound_info_orig and len(sound_info_orig) > 2:
                            audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Sounds", sound_info_orig[2]))
                        else:
                            await self.message_service.send_error(f"Sound '{audio_file}' not found on disk or database")
                            return False
                else:
                    sound_info_orig = self.sound_repo.get_sound(audio_file, True)
                    if sound_info_orig and len(sound_info_orig) > 2:
                        audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Sounds", sound_info_orig[2]))
                        if not os.path.exists(audio_file_path):
                             await self.message_service.send_error(f"Audio file not found: {audio_file_path}")
                             return False
                    else:
                        await self.message_service.send_error(f"Sound '{audio_file}' not found in database")
                        return False

            # Get sound info and duration early
            sound_info = self.sound_repo.get_sound(audio_file, False)
            try:
                audio = MP3(audio_file_path)
                duration = audio.info.length
                duration_str = f"{int(duration // 60)}:{int(duration % 60):02d}"
            except Exception as e:
                print(f"[AudioService] Error getting audio duration: {e}")
                duration_str = "Unknown"
                duration = 0

            # FFmpeg options
            vol = effects.get('volume', 1.0) if effects else 1.0
            ffmpeg_options = f'-af "volume={vol}'
            if effects:
                filters = []
                if effects.get('pitch'): filters.append(f"asetrate=44100*{effects['pitch']},aresample=44100")
                if effects.get('speed'): filters.append(f"atempo={effects['speed']}")
                if effects.get('reverb'): filters.append("aecho=0.8:0.9:1000:0.3")
                if effects.get('reverse'): filters.append('areverse')
                if filters: ffmpeg_options += "," + ",".join(filters)
            ffmpeg_options += '"'

            if not self.ffmpeg_path or not os.path.exists(self.ffmpeg_path):
                await self.message_service.send_error(f"Invalid FFmpeg path: {self.ffmpeg_path}")
                return False

            is_slap_sound = sound_info and sound_info[6] == 1

            # Start playback immediately
            try:
                audio_source = discord.FFmpegPCMAudio(
                    audio_file_path, 
                    executable=self.ffmpeg_path, 
                    options=ffmpeg_options,
                    before_options="-nostdin -fflags nobuffer -flags low_delay -analyzeduration 0 -probesize 32"
                )
                audio_source = discord.PCMVolumeTransformer(audio_source, volume=self.volume)
                
                def after_playing(error):
                    try:
                        if error: print(f'[AudioService] Error in playback: {error}')
                    finally:
                        self.bot.loop.call_soon_threadsafe(self.playback_done.set)

                voice_client.play(audio_source, after=after_playing)
                self.playback_done.clear()
            except Exception as e:
                print(f"[AudioService] Error starting playback early: {e}")
                self.playback_done.set()
                return False

            # Handle UI in background
            async def handle_ui():
                try:
                    bot_channel = self.message_service.get_bot_channel(channel.guild)
                    if not bot_channel or is_entrance: return

                    sound_message = None
                    view = None
                    
                    # Resolve requester avatar URL if not provided
                    resolved_avatar_url = requester_avatar_url
                    
                    # 1. Check for system/bot users -> Use bot's avatar
                    system_users = ["admin", "periodic function", "startup", "webpage", "scheduler", "auto-join"]
                    if isinstance(user, str) and any(s in user.lower() for s in system_users):
                        if self.bot.user and self.bot.user.display_avatar:
                            resolved_avatar_url = str(self.bot.user.display_avatar.url)
                    
                    # 2. If no avatar yet, try to resolve user object or string name
                    if not resolved_avatar_url:
                        if hasattr(user, 'display_avatar') and user.display_avatar:
                            resolved_avatar_url = str(user.display_avatar.url)
                        elif isinstance(user, str):
                            # Try to find member in guild
                            # Handle "Name#Discriminator" format from PersonalGreeter
                            target_name = user
                            target_discriminator = None
                            
                            if "#" in user:
                                parts = user.split("#")
                                target_name = parts[0]
                                if len(parts) > 1 and parts[1].isdigit():
                                    target_discriminator = parts[1]
                            
                            found_member = None
                            if target_discriminator and target_discriminator != '0':
                                # Precise match with discriminator
                                found_member = discord.utils.get(channel.guild.members, name=target_name, discriminator=target_discriminator)
                            else:
                                # Match by name or display_name
                                found_member = discord.utils.get(channel.guild.members, name=target_name)
                                if not found_member:
                                    found_member = discord.utils.get(channel.guild.members, display_name=target_name)

                            if found_member and found_member.display_avatar:
                                resolved_avatar_url = str(found_member.display_avatar.url)
                        
                        # 3. Fallback to bot avatar if still nothing (e.g., user left guild)
                        if not resolved_avatar_url and self.bot.user and self.bot.user.display_avatar:
                             resolved_avatar_url = str(self.bot.user.display_avatar.url)

                    if not is_slap_sound:
                        sound_filename = sound_info[2] if sound_info else audio_file
                        sound_id = sound_info[0] if sound_info else None
                        
                        play_count = None
                        download_date_str = None
                        lists_str = None
                        favorited_by_str = None
                        similarity_pct = int(extra) if extra else None
                        
                        if sound_id:
                            play_count = self.action_repo.get_sound_play_count(sound_id) + 1
                            download_date = self.stats_repo.get_sound_download_date(sound_id)
                            if download_date and download_date != "Unknown date":
                                try:
                                    if isinstance(download_date, str) and "2023-10-30" in download_date:
                                        download_date_str = "Before Oct 30, 2023"
                                    else:
                                        if isinstance(download_date, str):
                                            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
                                                try:
                                                    date_obj = datetime.strptime(download_date, fmt)
                                                    download_date_str = date_obj.strftime("%b %d, %Y")
                                                    break
                                                except ValueError: continue
                                        else:
                                            download_date_str = download_date.strftime("%b %d, %Y")
                                except Exception: pass
                            
                            favorited_by = self.stats_repo.get_users_who_favorited_sound(sound_id)
                            if favorited_by:
                                users_display = favorited_by[:3]
                                if len(favorited_by) > 3: users_display.append(f"+{len(favorited_by) - 3} more")
                                favorited_by_str = ", ".join(users_display)
                            elif sound_info and len(sound_info) > 3 and sound_info[3] == 1:
                                favorited_by_str = "Someone" # Fallback placeholder ✅
                        
                        if sound_filename:
                            lists_containing = self.list_repo.get_lists_containing_sound(sound_filename)
                            if lists_containing:
                                list_names = [lst[1] for lst in lists_containing[:3]]
                                if len(lists_containing) > 3: list_names.append(f"+{len(lists_containing) - 3} more")
                                lists_str = ", ".join(list_names)
                        
                        quote_text = original_message if (is_tts or sts_char) and original_message else None
                        
                        
                        # Fetch event data
                        event_data_str = None
                        try:
                            events = self.event_repo.get_events_for_sound(sound_filename)
                            if events:
                                # Format: "Join: User1, User2 | Leave: User3"
                                joins = [e[0] for e in events if e[1] == 'join']
                                leaves = [e[0] for e in events if e[1] == 'leave']
                                
                                parts = []
                                if joins:
                                    parts.append("Join")
                                if leaves:
                                    parts.append("Leave")
                                
                                if parts:
                                    event_data_str = " & ".join(parts)
                        except Exception as e:
                            print(f"[AudioService] Error fetching event data: {e}")

                        image_bytes = self.image_generator.generate_sound_card(
                            sound_name=audio_file, requester=str(user), play_count=play_count,
                            duration=duration_str if duration > 0 else None,
                            download_date=download_date_str, lists=lists_str,
                            favorited_by=favorited_by_str, similarity=similarity_pct,
                            quote=quote_text, is_tts=is_tts, sts_char=sts_char,
                            requester_avatar_url=resolved_avatar_url,
                            sts_thumbnail_url=sts_thumbnail_url,
                            event_data=event_data_str
                        )
                        
                        from bot.ui import SoundBeingPlayedView
                        behavior_ref = self._behavior if hasattr(self, '_behavior') else None
                        initial_label = "▶️ 0:01"
                        if duration > 0:
                            bar_length = 7
                            # Start dot at index 1 (offset)
                            bar = "▬🔘" + "▬" * (bar_length - 1)
                            initial_label = f"▶️ {bar} 0:01"
                        
                        view = SoundBeingPlayedView(
                            behavior_ref, audio_file, 
                            include_add_to_list_select=not is_tts, 
                            include_sts_select=True,
                            progress_label=initial_label,
                            show_controls=False # Start with controls hidden ✅
                        )
                        
                        if image_bytes:
                            file = discord.File(io.BytesIO(image_bytes), filename="sound_card.png")
                            if loading_message:
                                # Delete loading message and send sound card in its place
                                try:
                                    await loading_message.delete()
                                except Exception:
                                    pass
                            sound_message = await bot_channel.send(file=file, view=view)
                        else:
                            embed = discord.Embed(color=discord.Color.red())
                            if duration > 0:
                                bar = "▬🔘" + "▬" * 7
                                embed.description = f"▶️ {bar} 0:01 / {self._format_duration(duration)}"
                            embed.title = f"🔊 {audio_file.replace('.mp3', '')} 🔊"
                            embed.set_footer(text=f"Requested by {user}")
                            if loading_message:
                                try:
                                    await loading_message.delete()
                                except Exception:
                                    pass
                            sound_message = await bot_channel.send(embed=embed, view=view)
                        
                        self.current_sound_message = sound_message
                        self.current_view = view
                        self.stop_progress_update = False
                        
                        # if send_controls and hasattr(self, '_behavior') and self._behavior:
                        #     await self.message_service.send_controls(self._behavior, guild=channel.guild)
                    else:
                        embed = discord.Embed(title="👋 Slap!", color=discord.Color.orange())
                        sound_message = await bot_channel.send(embed=embed)
                        self.current_sound_message = sound_message
                        # if send_controls and hasattr(self, '_behavior') and self._behavior:
                        #     await self.message_service.send_controls(self._behavior)

                    if show_suggestions and not is_entrance and not is_tts and not is_slap_sound and self.sound_service:
                        asyncio.create_task(self.sound_service.find_and_update_similar_sounds(
                            sound_message=sound_message, audio_file=audio_file,
                            original_message=original_message, send_controls=False, num_suggestions=num_suggestions
                        ))
                    
                    if sound_message and not is_slap_sound and duration > 0:
                        asyncio.create_task(self.update_progress_bar(sound_message, duration, view))
                except Exception as ui_error:
                    print(f"[AudioService] Error in background UI task: {ui_error}")
                    traceback.print_exc()

            asyncio.create_task(handle_ui())
            return True

        except Exception as e:
            print(f"[AudioService] Error in play_audio: {e}")
            traceback.print_exc()
            self.playback_done.set()
            return False

    async def update_progress_bar(self, sound_message: discord.Message, duration: float, view: discord.ui.View = None):
        """Update the progress bar embed for a currently playing sound."""
        if duration <= 0:
            return

        start_time = time.time()
        # Shorter bar for button (Wider now, but trimmed to 6 ✅)
        bar_length = 7
        total_time_str = self._format_duration(duration)
        
        # If view passed, ensure it is set as current
        if view:
            self.current_view = view

        try:
            while time.time() - start_time < duration:
                if self.stop_progress_update:
                    break
                    
                # Add 1s offset to account for image processing/Discord delay
                OFFSET = 1.0
                elapsed = (time.time() - start_time) + OFFSET
                progress = max(0.0, min(1.0, elapsed / duration))
                
                # Calculate dot position
                filled = int(bar_length * progress)
                # Ensure dot doesn't go beyond bounds
                if filled >= bar_length:
                    filled = bar_length
                
                # Construct bar: ▬▬▬▬🔘▬▬▬▬▬
                bar = "▬" * filled + "🔘" + "▬" * (bar_length - filled)
                current_time_str = self._format_duration(elapsed)
                
                # Format: ▶️ 🔘▬▬▬▬ 0:05
                seeker_text = f"▶️ {bar} {current_time_str}"
                
                # Use self.current_view to handle view replacements
                current_view = self.current_view
                if current_view and hasattr(current_view, 'update_progress_label'):
                    try:
                        current_view.update_progress_label(seeker_text)
                        await sound_message.edit(view=current_view)
                    except discord.NotFound:
                        break
                    except Exception:
                        pass
                
                # Fallback for embeds (no view update here to keep simple, or keep old logic if needed)
                elif sound_message.embeds:
                    pass
                
                await asyncio.sleep(1.0) # Update roughly once per second

            # Final update
            if not self.stop_progress_update:
                final_bar = "▬" * bar_length + "🔘"
                final_text = f"✅ {final_bar} {total_time_str}"
                
                current_view = self.current_view
                if current_view and hasattr(current_view, 'update_progress_label'):
                    try:
                        current_view.update_progress_label(final_text)
                        await sound_message.edit(view=current_view)
                    except:
                        pass
        except Exception as e:
            print(f"[AudioService] Error updating progress bar: {e}")

    async def start_keyword_detection(self, guild: discord.Guild):
        """Start background keyword detection in the specified guild."""
        try:
            voice_client = guild.voice_client
            if not voice_client or not voice_client.is_connected():
                return False

            # Check if we already have a sink
            if guild.id in self.keyword_sinks:
                sink = self.keyword_sinks[guild.id]
                # Check if the worker thread is still alive
                if sink.worker_thread.is_alive():
                    print(f"[AudioService] Keyword detection already running in {guild.name}")
                    return True
                else:
                    # Thread died, clean up old sink and create new one
                    print(f"[AudioService] VoskWorker thread died, restarting in {guild.name}")
                    sink.stop()  # Clean up any remaining resources
                    del self.keyword_sinks[guild.id]

            # Wait for voice connection to fully stabilize
            await asyncio.sleep(1.0)
            
            # Re-check after delay
            voice_client = guild.voice_client
            if not voice_client or not voice_client.is_connected():
                print(f"[AudioService] Voice connection lost during delay, skipping keyword detection")
                return False

            print(f"[AudioService] Starting keyword detection in {guild.name}")
            sink = KeywordDetectionSink(self, guild, self.bot.loop)
            try:
                voice_client.start_recording(sink, self._on_detection_finished, guild)
                self.keyword_sinks[guild.id] = sink
                return True
            except Exception as e:
                print(f"[AudioService] Failed to start recording: {e}")
                sink.stop()
                return False
        except Exception as e:
            print(f"[AudioService] Error starting keyword detection: {e}")
            return False

    async def stop_keyword_detection(self, guild: discord.Guild):
        """Stop background keyword detection in the specified guild."""
        try:
            if guild.id in self.keyword_sinks:
                sink = self.keyword_sinks[guild.id]
                
                # Stop the sink worker thread first
                sink.stop()
                
                voice_client = guild.voice_client
                if voice_client:
                    try:
                        voice_client.stop_recording()
                    except Exception as e:
                        print(f"[AudioService] Error stopping recording: {e}")
                    
                    # Give the voice client time to clean up pending async tasks
                    await asyncio.sleep(0.5)
                
                del self.keyword_sinks[guild.id]
                print(f"[AudioService] Stopped keyword detection in {guild.name}")
            return True
        except Exception as e:
            print(f"[AudioService] Error stopping keyword detection: {e}")
            return False

    async def _on_detection_finished(self, sink, guild):
        """Cleanup when detection recording is stopped."""
        if hasattr(sink, 'stop'):
            sink.stop()

    def get_last_audio_segment_with_users(self, guild_id: int, seconds: int = 10) -> tuple:
        """Retrieve the last N seconds of mixed/concatenated audio and the list of users."""
        if guild_id in self.keyword_sinks:
            sink = self.keyword_sinks[guild_id]
            audio = sink.get_buffer_content(seconds)
            users = sink.get_recent_users(seconds)
            return audio, users
        return None, []

class KeywordDetectionSink(sinks.Sink):
    def __init__(self, audio_service, guild, loop):
        super().__init__()
        self.audio_service = audio_service
        self.guild = guild
        self.loop = loop
        self.recognizers = {} # user_id -> vosk.KaldiRecognizer
        self.resample_states = {} # user_id -> audioop state
        self.last_audio_time = {} # user_id -> timestamp
        self.queue = queue.Queue()
        self.running = True
        
        # Load keywords from database
        self.keywords = {}
        self.refresh_keywords()
        
        self.last_partial = {} # user_id -> last partial text to avoid duplicate logs
        self.max_queue_size = 100 # Queue limit to prevent lag
        self.recognizer_start_time = {} # user_id -> when recognizer was created
        self.max_segment_duration = 10.0 # Force flush after 10 seconds of continuous speech
        self.audio_buffers = {} # user_id -> bytearray for batching
        self.min_batch_size = 28800 # ~300ms at 48kHz stereo (48000 * 2 * 2 * 0.3)
        # Audio buffering for AI Commentary - PER-USER timestamped chunks
        self.buffer_seconds = 30
        self.user_audio_buffers: Dict[int, list] = {}  # user_id -> list of (timestamp, audio_bytes)
        self.buffer_last_update: Dict[int, float] = {}  # user_id -> timestamp
        self.buffer_lock = threading.Lock()
        
        # Auto-AI Commentary state
        self.speech_start_time: Dict[int, float] = {}  # user_id -> when they started talking
        self.pending_ai_trigger: Optional[float] = None  # Time when 2s speech detected (wait for silence)
        self.ventura_trigger_times: Dict[int, float] = {}  # user_id -> when "ventura" heard
        self.ventura_keywords = ["ventura", "andre ventura"]
        self.last_ventura_trigger_time = 0
        self.ventura_trigger_enabled = False

        # Log directory for per-user transcripts
        self.log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Data", "vosk_logs"))
        os.makedirs(self.log_dir, exist_ok=True)
        # Single worker thread
        self.worker_thread = threading.Thread(target=self._worker, name=f"VoskWorker-{guild.id}", daemon=True)
        self.worker_thread.start()

    def refresh_keywords(self):
        """Reload keywords from the database repository."""
        try:
            self.keywords = self.audio_service.keyword_repo.get_as_dict()
            # Reset recognizers so they are recreated with the new grammar list
            self.recognizers = {}
            print(f"[KeywordDetectionSink] Refreshed {len(self.keywords)} keywords")
        except Exception as e:
            print(f"[KeywordDetectionSink] Error refreshing keywords: {e}")

    def _log_to_file(self, username, text):
        """Log final transcription to per-user file."""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_file = os.path.join(self.log_dir, f"{username}.txt")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {text}\n")
        except Exception as e:
            print(f"[VoskLogger] Error writing log for {username}: {e}")

    def _is_ventura_match(self, text: str) -> bool:
        """Check if text contains 'ventura' as a whole word (not substring).
        
        Uses word boundary matching to prevent false triggers on similar words
        like 'aventura', 'boaventura', 'venturar', etc.
        """
        import re
        text_lower = text.lower()
        for keyword in self.ventura_keywords:
            # Use word boundaries to match whole words only
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, text_lower):
                return True
        return False

    def stop(self):
        self.running = False
        self.queue.put((None, None))

    def ensure_worker_running(self):
        """Ensure the worker thread is running, restart if needed."""
        if not self.worker_thread.is_alive():
            print(f"[KeywordDetectionSink] Worker thread died, restarting for guild {self.guild.id}")
            self.running = True
            self.worker_thread = threading.Thread(target=self._worker, name=f"VoskWorker-{self.guild.id}", daemon=True)
            self.worker_thread.start()
            return True
        return False

    def write(self, data, user_id):
        if not self.running:
            return
        
        # Check if worker thread is alive, restart if needed (resilience)
        if not self.worker_thread.is_alive():
            self.ensure_worker_running()
        
        receive_time = time.time()
        self.last_audio_time[user_id] = receive_time
        self.buffer_last_update[user_id] = receive_time
        
        # Track speech duration for Auto-AI (mark for trigger, wait for silence)
        if user_id not in self.speech_start_time:
            self.speech_start_time[user_id] = receive_time
        else:
            duration = receive_time - self.speech_start_time[user_id]
            if duration >= 2.0 and self.pending_ai_trigger is None:
                # Mark pending - actual trigger fires when silence is detected
                self.pending_ai_trigger = receive_time
        
        # Store audio in per-user timestamped buffer
        with self.buffer_lock:
            if user_id not in self.user_audio_buffers:
                self.user_audio_buffers[user_id] = []
            
            self.user_audio_buffers[user_id].append((receive_time, data))
            
            # Prune old chunks
            cutoff = receive_time - self.buffer_seconds
            self.user_audio_buffers[user_id] = [
                (ts, audio) for ts, audio in self.user_audio_buffers[user_id] if ts >= cutoff
            ]

        # Buffer audio per-user to reduce queue pressure
        if user_id not in self.audio_buffers:
            self.audio_buffers[user_id] = bytearray()
        self.audio_buffers[user_id].extend(data)
        
        # CRITICAL: Cap buffer size to prevent massive chunks (max ~500ms = 48000B)
        max_buffer = 48000
        if len(self.audio_buffers[user_id]) > max_buffer:
            # Keep only the most recent audio
            self.audio_buffers[user_id] = self.audio_buffers[user_id][-max_buffer:]
        
        # Only queue when we have enough data (~300ms) or if queue is empty
        if len(self.audio_buffers[user_id]) >= self.min_batch_size or self.queue.qsize() == 0:
            buf_size = len(self.audio_buffers[user_id])
            if self.queue.qsize() < self.max_queue_size:
                # Include timestamp in queue entry for latency tracking
                self.queue.put((bytes(self.audio_buffers[user_id]), user_id, receive_time))
            self.audio_buffers[user_id] = bytearray()


    def _worker(self):
        """Single worker thread for all audio processing."""
        last_heartbeat = time.time()
        while self.running:
            try:
                # Heartbeat every 60 seconds
                if time.time() - last_heartbeat > 60:
                    qsize = self.queue.qsize()
                    print(f"[VoskWorker] Heartbeat - Queue: {qsize}, Running: {self.running}")
                    
                    # Health check: Verify voice connection is actually connected
                    try:
                        voice_client = self.guild.voice_client
                        if voice_client:
                            # Check if reconnection is already in progress (grace period)
                            if self.audio_service.is_reconnection_pending(self.guild.id):
                                remaining = self.audio_service.get_reconnection_remaining(self.guild.id)
                                print(f"[VoskWorker] Reconnection in progress ({remaining:.1f}s remaining), skipping health check...")
                            elif not voice_client.is_connected():
                                print(f"[VoskWorker] WARNING: Voice client exists but is not connected! Triggering reconnection...")
                                # Schedule reconnection on the main event loop
                                asyncio.run_coroutine_threadsafe(
                                    self.audio_service.ensure_voice_connected(voice_client.channel),
                                    self.loop
                                )
                            elif not hasattr(voice_client, 'ws') or voice_client.ws is None:
                                print(f"[VoskWorker] WARNING: Voice client has no WebSocket! Triggering reconnection...")
                                # Schedule reconnection on the main event loop  
                                asyncio.run_coroutine_threadsafe(
                                    self.audio_service.ensure_voice_connected(voice_client.channel),
                                    self.loop
                                )
                        else:
                            print(f"[VoskWorker] WARNING: No voice client found for {self.guild.name}")
                    except Exception as health_err:
                        print(f"[VoskWorker] Error during health check: {health_err}")
                    
                    last_heartbeat = time.time()
                
                try:
                    item = self.queue.get(timeout=0.1)
                    if len(item) == 3:
                        data, user_id, queued_time = item
                        dequeue_latency = (time.time() - queued_time) * 1000
                    else:
                        data, user_id = item
                except queue.Empty:
                    # Timeout - check for silence to flush
                    self._flush_silence()
                    continue
                
                if data is None:  # Stop signal
                    print("[VoskWorker] Received stop signal")
                    break
                
                self.detect_keyword(data, user_id)
                self.queue.task_done()
            except Exception as e:
                print(f"[VoskWorker] Error: {e}")
                traceback.print_exc()
        print("[VoskWorker] Thread exited")

    def _flush_silence(self):
        """Force Vosk to finalize results for users who stopped talking and cleanup idle users."""
        now = time.time()
        
        # Check if ALL users are silent (for pending AI trigger)
        all_silent = True
        for user_id, last_time in self.buffer_last_update.items():
            if now - last_time < 1.5:
                all_silent = False
                break
        
        # Handle pending Auto-AI trigger on silence
        if self.pending_ai_trigger is not None and all_silent:
            trigger_start = self.pending_ai_trigger
            self.pending_ai_trigger = None
            
            # SAFETY: If trigger is older than 60s, something went wrong - skip it
            if now - trigger_start > 60:
                print(f"[AutoAI] WARNING: Stale trigger detected ({now - trigger_start:.1f}s old). Skipping.")
            else:
                duration = min(now - trigger_start + 5.0, 30.0)  # Add context, cap at 30s
                
                # Check if already processing before queueing
                if hasattr(self.audio_service.bot, 'behavior'):
                    behavior = self.audio_service.bot.behavior
                    if hasattr(behavior, '_ai_commentary_service'):
                        if behavior._ai_commentary_service.is_processing:
                            print(f"[AutoAI] Already processing. Skipping trigger.")
                        else:
                            print(f"[AutoAI] Silence detected. Triggering (duration={duration:.1f}s)")
                            future = asyncio.run_coroutine_threadsafe(
                                behavior._ai_commentary_service.trigger_commentary(self.guild.id, duration=duration),
                                self.loop
                            )
                            future.add_done_callback(lambda f: print(f"[AutoAI] ERROR in trigger_commentary: {f.exception()}") if f.exception() else None)
        
        # Send "listening" notification when cooldown ends
        if hasattr(self.audio_service.bot, 'behavior'):
            behavior = self.audio_service.bot.behavior
            if hasattr(behavior, '_ai_commentary_service'):
                future = asyncio.run_coroutine_threadsafe(
                    behavior._ai_commentary_service.notify_listening_if_ready(self.guild.id),
                    self.loop
                )
                future.add_done_callback(lambda f: print(f"[AutoAI] ERROR in notify_listening: {f.exception()}") if f.exception() else None)
        
        # Handle Vosk flushing for speech-to-text (1s threshold)
        for user_id, last_time in list(self.last_audio_time.items()):
            idle_time = now - last_time
            if idle_time > 1:
                if user_id in self.speech_start_time:
                    del self.speech_start_time[user_id]
                
                self._flush_user(user_id)
                if user_id in self.last_audio_time:
                    del self.last_audio_time[user_id]
            
            elif user_id in self.recognizer_start_time:
                segment_time = now - self.recognizer_start_time[user_id]
                if segment_time > self.max_segment_duration:
                    self._flush_user(user_id)

        # 2. Handle Ventura trigger silence detection (2.0s threshold)
        # We use buffer_last_update as it is more persistent than last_audio_time
        if not self.ventura_trigger_enabled:
            self.ventura_trigger_times.clear()  # Clear any pending triggers
        else:
            for user_id in list(self.ventura_trigger_times.keys()):
                last_activity = self.buffer_last_update.get(user_id, 0)
                idle_time = now - last_activity
                
                if idle_time > 2.0:
                    trigger_time = self.ventura_trigger_times.pop(user_id)
                    # Duration is trigger until now + 5s prefix for context
                    duration = (now - trigger_time) + 5.0
                    duration = min(duration, 30.0) # Cap at 30s
                    
                    # Check if already processing before queueing
                    if hasattr(self.audio_service.bot, 'behavior'):
                        behavior = self.audio_service.bot.behavior
                        if hasattr(behavior, '_ai_commentary_service'):
                            if behavior._ai_commentary_service.is_processing:
                                print(f"[VenturaTrigger] Already processing. Skipping trigger for user {user_id}.")
                            else:
                                print(f"[VenturaTrigger] Silence detected (2s) for user {user_id}. Triggering AI commentary (duration={duration:.1f}s)")
                                future = asyncio.run_coroutine_threadsafe(
                                    behavior._ai_commentary_service.trigger_commentary(self.guild.id, force=True, duration=duration),
                                    self.loop
                                )
                                future.add_done_callback(lambda f: print(f"[VenturaTrigger] ERROR in trigger_commentary: {f.exception()}") if f.exception() else None)
            
        # 3. Cleanup users idle for more than 30 seconds to free memory
        for user_id, last_time in list(self.buffer_last_update.items()):
            idle_time = now - last_time
            if idle_time > 30:
                if user_id in self.recognizers:
                    del self.recognizers[user_id]
                if user_id in self.resample_states:
                    del self.resample_states[user_id]
                if user_id in self.last_partial:
                    del self.last_partial[user_id]
                # Keep buffer_last_update a bit longer or let it be cleaned up
                # del self.buffer_last_update[user_id]
                if user_id in self.last_partial:
                    del self.last_partial[user_id]
    def get_buffer_content(self, seconds: int = 10) -> bytes:
        """Get the last N seconds of audio from all users' buffers."""
        # SAFETY: Hard cap at 30 seconds no matter what is requested
        seconds = min(seconds, 30)
        
        now = time.time()
        cutoff = now - seconds
        
        with self.buffer_lock:
            all_chunks = []
            for user_id, chunks in self.user_audio_buffers.items():
                for ts, audio in chunks:
                    if ts >= cutoff:
                        all_chunks.append((ts, audio))
            
            if not all_chunks:
                return bytes()
            
            all_chunks.sort(key=lambda x: x[0])
            result = b''.join(audio for ts, audio in all_chunks)
            
            # SAFETY: Hard cap on bytes (~30 seconds at 48kHz stereo 16-bit)
            max_bytes = 48000 * 2 * 2 * 30  # 5.76MB max
            if len(result) > max_bytes:
                print(f"[AudioBuffer] WARNING: Truncating {len(result)} bytes to {max_bytes} bytes")
                result = result[-max_bytes:]
            
            return result

    def get_recent_users(self, seconds: int = 15) -> List[str]:
        """Get the list of usernames who spoke in the last N seconds."""
        now = time.time()
        active_usernames = []
        with self.buffer_lock:
            for user_id, last_time in self.buffer_last_update.items():
                if now - last_time < seconds:
                    member = self.guild.get_member(user_id)
                    username = member.name if member else f"User_{user_id}"
                    active_usernames.append(username)
        return active_usernames

    def _flush_user(self, user_id):
        """Force finalize and cleanup a user's recognizer."""
        if user_id not in self.recognizers:
            return
        
        rec = self.recognizers[user_id]
        try:
            result = json.loads(rec.FinalResult())
            text = result.get("text", "").lower()
        except Exception:
            result = {}
            text = ""
        
        # Always delete recognizer after FinalResult (it's finished)
        del self.recognizers[user_id]
        if user_id in self.resample_states: del self.resample_states[user_id]
        if user_id in self.recognizer_start_time: del self.recognizer_start_time[user_id]
        
        if text:
            member = self.guild.get_member(user_id)
            username = member.name if member else f"user_{user_id}"
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"[{timestamp}] [Vosk Final (Flushed)] {username}: \"{text}\"")
            self._log_to_file(username, text)
            
            # Use _check_keywords with the result object to get confidence-based detection
            # FinalResult() includes word-level confidence when SetWords(True) is enabled
            keyword, action = self._check_keywords(text, result)
            if keyword:
                print(f"[{timestamp}] [KeywordDetection] Detected keyword '{keyword}' from user {username}!")
                asyncio.run_coroutine_threadsafe(self.trigger_action(user_id, keyword, action), self.audio_service.bot.loop)

    def _check_keywords(self, text: str, result_obj: dict = None) -> tuple:
        """Check if any keyword is in the text. Returns (keyword, action) or (None, None).
        
        Uses confidence scores when available to filter out misrecognitions.
        """
        import re
        
        # If we have word-level confidence from Vosk, use it
        if result_obj and "result" in result_obj:
            for word_info in result_obj["result"]:
                word = word_info.get("word", "").lower()
                conf = word_info.get("conf", 0.0)
                
                if word not in self.keywords:
                    continue
                
                # Single confidence threshold for all keywords
                required_conf = 0.95
                if conf >= required_conf:
                    print(f"[KeywordDetection] Confirmed keyword '{word}' (confidence: {conf:.3f})")
                    return word, self.keywords[word]
                else:
                    print(f"[KeywordDetection] Rejected keyword '{word}' - confidence {conf:.3f} < {required_conf}")
            
            return None, None

        # Fallback: no confidence info available, do simple text match
        for keyword, action in self.keywords.items():
            if re.search(rf"\b{re.escape(keyword.lower())}\b", text.lower()):
                print(f"[KeywordDetection] Detected keyword '{keyword}' (no confidence info)")
                return keyword, action
        return None, None

    def detect_keyword(self, pcm_data, user_id, is_silence=False):
        member = self.guild.get_member(user_id)
        username = member.name if member else f"user_{user_id}"
        
        try:
            if not is_silence:
                # OPTIMIZATION: C-accelerated resampling using audioop with state tracking
                # 1. Convert to mono by taking left channel
                mono_data = audioop.tomono(pcm_data, 2, 1, 0)
                # 2. Resample from 48000 to 16000 with per-user state to avoid audio skew
                state = self.resample_states.get(user_id)
                optimized_pcm, state = audioop.ratecv(mono_data, 2, 1, 48000, 16000, state)
                self.resample_states[user_id] = state
            else:
                optimized_pcm = pcm_data # Already resampled silence
            
            if not self.audio_service.vosk_model:
                return

            if user_id not in self.recognizers:
                # Use grammar to significantly improve keyword detection accuracy
                if self.keywords:
                    # Keywords + distractor words + [unk] to allow non-keyword speech to be ignored
                    # This prevents Vosk from "forcing" every sound into a keyword
                    distractors = [
                        # Common Portuguese words
                        "chapa","ada","cha","o","google", "jogo","do jogo",
                    ]
                    grammar = list(self.keywords.keys()) + distractors + ["[unk]"]
                    grammar_json = json.dumps(grammar)
                    self.recognizers[user_id] = vosk.KaldiRecognizer(self.audio_service.vosk_model, 16000, grammar_json)
                else:
                    self.recognizers[user_id] = vosk.KaldiRecognizer(self.audio_service.vosk_model, 16000)
                
                # Enable confidence scores
                self.recognizers[user_id].SetWords(True)
                self.recognizer_start_time[user_id] = time.time()

            rec = self.recognizers[user_id]
            if rec.AcceptWaveform(optimized_pcm):
                result = json.loads(rec.Result())
                text = result.get("text", "").lower()
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                if text:
                    print(f"[{timestamp}] [Vosk Final] {username}: \"{text}\"")
                    self._log_to_file(username, text)
                    
                    # Detect Ventura in final results as well (strict word match)
                    if self.ventura_trigger_enabled and self._is_ventura_match(text):
                        now = time.time()
                        if now - self.last_ventura_trigger_time < 30:
                            print(f"[VenturaTrigger] Cooldown active (final). Skipping trigger for {username}.")
                        elif user_id not in self.ventura_trigger_times:
                            print(f"[VenturaTrigger] 'Ventura' detected in final result from {username}")
                            self.ventura_trigger_times[user_id] = now
                            self.last_ventura_trigger_time = now
                    
                    # Check keywords in final result (most accurate)
                    keyword, action = self._check_keywords(text, result)
                    if keyword:
                        print(f"[{timestamp}] [KeywordDetection] Detected keyword '{keyword}' from user {username}")
                        if user_id in self.recognizers: del self.recognizers[user_id]
                        if user_id in self.resample_states: del self.resample_states[user_id]
                        if user_id in self.last_partial: del self.last_partial[user_id]
                        asyncio.run_coroutine_threadsafe(self.trigger_action(user_id, keyword, action), self.audio_service.bot.loop)
                        return
            else:
                result = json.loads(rec.PartialResult())
                text = result.get("partial", "").lower()
                
                # Only log if partial changed (avoid duplicate spam)
                if text and text != self.last_partial.get(user_id):
                    self.last_partial[user_id] = text
                    
                    # Detect Ventura in partial results for faster response (strict word match)
                    if self.ventura_trigger_enabled and self._is_ventura_match(text):
                        now = time.time()
                        if now - self.last_ventura_trigger_time < 30:
                            # Too much spam in partials, only log once if we haven't already
                            pass
                        elif user_id not in self.ventura_trigger_times:
                            print(f"[VenturaTrigger] 'Ventura' detected in partial result from {username}")
                            self.ventura_trigger_times[user_id] = now
                            self.last_ventura_trigger_time = now
        except Exception as e:
            if not is_silence:
                print(f"[KeywordDetection] Error in detect_keyword for {username}: {e}")

    async def trigger_action(self, user_id, keyword: str, action: str):
        """Trigger the action for a detected keyword."""
        if not self.guild.voice_client:
            return

        member = self.guild.get_member(user_id)
        requester_name = member.name if member else f"user_{user_id}"
        channel = self.guild.voice_client.channel
        
        if not channel:
            return
        
        if action == "slap":
            # Play random slap sound
            slap_sounds = self.audio_service._behavior.db.get_sounds(slap=True, num_sounds=100)
            if slap_sounds:
                import random
                random_slap = random.choice(slap_sounds)
                print(f"[KeywordDetection] Playing random slap for {requester_name}")
                await self.audio_service.play_slap(channel, random_slap[2], requester_name)
                self.audio_service._behavior.db.insert_action(requester_name, "keyword_slap", random_slap[0])
        
        elif action.startswith("list:"):
            # Play random sound from a specific list
            list_name = action.split(":", 1)[1]
            from bot.repositories import ListRepository
            sound = ListRepository().get_random_sound_from_list(list_name)
            if sound:
                print(f"[KeywordDetection] Playing random sound from '{list_name}' list for {requester_name}: {sound[2]}")
                # Use play_audio instead of play_slap to show the normal message in chat
                # Suggestions are now enabled because they run in the background
                await self.audio_service.play_audio(channel, sound[2], requester_name)
                self.audio_service._behavior.db.insert_action(requester_name, f"keyword_{keyword}", sound[0])
            else:
                print(f"[KeywordDetection] No sounds found in list '{list_name}'")
