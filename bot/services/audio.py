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
from bot.repositories import SoundRepository, ActionRepository, ListRepository, StatsRepository

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
        
        # Audio state moved from BotBehavior
        self.last_played_time: Optional[datetime] = None
        self.current_sound_message: Optional[discord.Message] = None
        self.stop_progress_update = False
        self.progress_already_updated = False
        self.cooldown_message: Optional[discord.Message] = None
        self.current_similar_sounds: Optional[List[Any]] = None
        self.volume = 1.0
        self.playback_done = asyncio.Event()
        self.playback_done.set()
        
        # Keyword detection state
        self.keyword_sinks: Dict[int, 'KeywordDetectionSink'] = {}
        
        # Initialize Vosk model for local STT
        try:
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

    def set_sound_service(self, sound_service):
        self.sound_service = sound_service

    def set_voice_transformation_service(self, vt_service):
        self.voice_transformation_service = vt_service

    def set_behavior(self, behavior):
        """Set reference to BotBehavior for passing to views."""
        self._behavior = behavior

    async def ensure_voice_connected(self, channel: discord.VoiceChannel) -> Optional[discord.VoiceProtocol]:
        """Ensure the bot is connected to the specified voice channel."""
        try:
            voice_client = channel.guild.voice_client

            if voice_client:
                if not voice_client.is_connected():
                    print(f"[AudioService] Voice client in {channel.guild.name} exists but is not connected. Reconnecting...")
                    try:
                        await voice_client.disconnect(force=True)
                        await asyncio.sleep(1)
                    except Exception as e:
                         print(f"[AudioService] Error forcing disconnect: {e}")
                elif voice_client.channel.id != channel.id:
                    await voice_client.move_to(channel)
                    # Restart keyword detection if moved
                    await self.start_keyword_detection(channel.guild)
                    return voice_client
                else:
                    # Ensure detection is running
                    await self.start_keyword_detection(channel.guild)
                    return voice_client
            
            for attempt in range(3):
                try:
                    voice_client = await channel.connect(timeout=10.0)
                    # Start keyword detection on new connection
                    await self.start_keyword_detection(channel.guild)
                    return voice_client
                except Exception as e:
                    print(f"[AudioService] Connection attempt {attempt + 1} failed: {e}")
                    if attempt < 2:
                        await asyncio.sleep(1)
            
            print("[AudioService] Failed to connect after 3 attempts.")
            return None

        except Exception as e:
            print(f"[AudioService] Error connecting to voice channel: {e}")
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
        user_name_parts = user_name.split('#')
        name = user_name_parts[0]
        
        for channel in guild.voice_channels:
            for member in channel.members:
                if member.name == name:
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
                if self.current_sound_message and self.current_sound_message.embeds:
                    try:
                        embed = self.current_sound_message.embeds[0]
                        lines = embed.description.split('\n') if embed.description else []
                        new_lines = []
                        for line in lines:
                            if line.startswith("Progress:"):
                                new_lines.append(f"{line} 👋")
                            else:
                                new_lines.append(line)
                        embed.description = "\n".join(new_lines)
                        await self.current_sound_message.edit(embed=embed)
                    except:
                        pass
                voice_client.stop()


            audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Sounds", audio_file))
            if not os.path.exists(audio_file_path):
                print(f"[AudioService] Slap sound not found: {audio_file_path}")
                return False

            ffmpeg_options = '-af "volume=1.0"'
            audio_source = discord.FFmpegPCMAudio(
                audio_file_path,
                executable=self.ffmpeg_path,
                options=ffmpeg_options
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
                        send_controls=True, retry_count=0, effects=None, 
                        show_suggestions: bool = True, 
                        num_suggestions: int = 5,
                        sts_char: str = None):
        """Play an audio file in the specified voice channel."""
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

        # Stop updating the previous sound's progress
        if self.current_sound_message and not self.progress_already_updated:
            self.stop_progress_update = True
            try:
                if self.current_sound_message.embeds:
                    embed = self.current_sound_message.embeds[0]
                    description_lines = embed.description.split('\n') if embed.description else []
                    progress_line = next((line for line in description_lines if line.startswith("Progress:")), None)
                    
                    if progress_line and not any(emoji in progress_line for emoji in ["👋", "⏭️"]):
                        description = []
                        if extra != "":
                            description.append(f"Similarity: {extra}%")
                        
                        sound_info = self.sound_repo.get_sound(audio_file, True)
                        is_slap_sound = sound_info and sound_info[6] == 1
                        interrupt_emoji = "👋" if is_slap_sound else "⏭️"
                        
                        for line in description_lines:
                            if line.startswith("Progress:"):
                                description.append(f"{line} {interrupt_emoji}")
                            else:
                                description.append(line)
                        description_text = "\n".join(description)
                        
                        embed.description = description_text
                        await self.current_sound_message.edit(embed=embed)
                        self.progress_already_updated = True
            except Exception as e:
                print(f"[AudioService] Error updating previous sound message: {e}")

        try:
            self.current_similar_sounds = None
            voice_client = await self.ensure_voice_connected(channel)
            if not voice_client:
                return False

            # Stop any currently playing audio to allow instant skip
            if voice_client.is_playing():
                voice_client.stop()

            if not isinstance(audio_file, str):
                print(f"[AudioService] WARNING: audio_file is not a string! Type: {type(audio_file)}, Value: {audio_file}")
                audio_file = str(audio_file)

            audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Sounds", audio_file))

            if not os.path.exists(audio_file_path):
                # Try getting sound info by Filename first
                sound_info = self.sound_repo.get_sound(audio_file, False)
                if sound_info:
                    # Found by Filename, check if original filename exists on disk
                    original_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Sounds", sound_info[1]))
                    if os.path.exists(original_path):
                        audio_file_path = original_path
                    else:
                        # Try searching by original filename directly (legacy fallback)
                        sound_info_orig = self.sound_repo.get_sound(audio_file, True)
                        if sound_info_orig and len(sound_info_orig) > 2:
                            audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Sounds", sound_info_orig[2]))
                        else:
                            await self.message_service.send_error(f"Sound '{audio_file}' not found on disk or database")
                            return False
                else:
                     # Try searching by original filename directly (legacy fallback)
                    sound_info_orig = self.sound_repo.get_sound(audio_file, True)
                    if sound_info_orig and len(sound_info_orig) > 2:
                        audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Sounds", sound_info_orig[2]))
                        if not os.path.exists(audio_file_path):
                             await self.message_service.send_error(f"Audio file not found: {audio_file_path}")
                             return False
                    else:
                        await self.message_service.send_error(f"Sound '{audio_file}' not found in database")
                        return False

            try:
                audio = MP3(audio_file_path)
                duration = audio.info.length
                duration_str = f"{int(duration // 60)}:{int(duration % 60):02d}"
            except Exception as e:
                print(f"[AudioService] Error getting audio duration: {e}")
                duration_str = "Unknown"
                duration = 0

            bot_channel = self.message_service.get_bot_channel(channel.guild)
            sound_message = None
            
            # Re-check slap sound
            sound_info = self.sound_repo.get_sound(audio_file, False)
            is_slap_sound = sound_info and sound_info[6] == 1
            
            if bot_channel and not is_entrance:
                if not is_slap_sound:
                    description = []
                    if extra:
                        description.append(f"Similarity: {extra}%")
                    
                    # Get play count for this sound
                    sound_filename = sound_info[2] if sound_info else audio_file
                    sound_id = sound_info[0] if sound_info else None
                    
                    if sound_id:
                        play_count = self.action_repo.get_sound_play_count(sound_id)
                        description.append(f"🔢 Play count: {play_count + 1}")
                        
                        # Add download date information
                        download_date = self.stats_repo.get_sound_download_date(sound_id)
                        if download_date and download_date != "Unknown date":
                            try:
                                if isinstance(download_date, str) and "2023-10-30" in download_date:
                                    description.append(f"📅 Added: Before Oct 30, 2023")
                                else:
                                    if isinstance(download_date, str):
                                        date_formats = [
                                            "%Y-%m-%d %H:%M:%S",
                                            "%Y-%m-%d %H:%M:%S.%f",
                                            "%Y-%m-%dT%H:%M:%S",
                                            "%Y-%m-%d"
                                        ]
                                        date_obj = None
                                        for date_format in date_formats:
                                            try:
                                                date_obj = datetime.strptime(download_date, date_format)
                                                break
                                            except ValueError:
                                                continue
                                        if date_obj:
                                            formatted_date = date_obj.strftime("%b %d, %Y")
                                            description.append(f"📅 Added: {formatted_date}")
                                    else:
                                        formatted_date = download_date.strftime("%b %d, %Y")
                                        description.append(f"📅 Added: {formatted_date}")
                            except Exception as e:
                                print(f"[AudioService] Error formatting date: {e}")
                    
                    if duration > 0:
                        description.append(f"⏱️ Duration: {duration_str}")
                        description.append("Progress: Loading...")
                    
                    # Add lists containing this sound
                    if sound_filename:
                        lists_containing = self.list_repo.get_lists_containing_sound(sound_filename)
                        if lists_containing:
                            list_names = [lst[1] for lst in lists_containing[:3]]  # Max 3 lists
                            if len(lists_containing) > 3:
                                list_names.append(f"+{len(lists_containing) - 3} more")
                            description.append(f"📁 Lists: {', '.join(list_names)}")
                    
                    # Add users who favorited this sound
                    if sound_id:
                        favorited_by = self.stats_repo.get_users_who_favorited_sound(sound_id)
                        if favorited_by:
                            users_display = favorited_by[:3]  # Max 3 users
                            if len(favorited_by) > 3:
                                users_display.append(f"+{len(favorited_by) - 3} more")
                            description.append(f"❤️ Favorited by: {', '.join(users_display)}")
                    
                    description_text = "\n".join(description)
                    
                    # Footer with requester
                    footer_text = f"Requested by {user}"
                    
                    embed_title = f"🔊 {audio_file.replace('.mp3', '')} 🔊"
                    thumbnail_url = None
                    
                    if sts_char:
                        # STS: Show character name as speaker with original sound name
                        char_names = {
                            "ventura": "🐷 Ventura",
                            "tyson": "🐵 Tyson",
                            "costa": "🐗 Costa"
                        }
                        char_thumbnails = {
                            "ventura": "https://i.imgur.com/JQ8VXZZ.png",
                            "tyson": "https://i.imgur.com/8QZGZ0x.png",
                            "costa": "https://i.imgur.com/YQ5VXZZ.png"
                        }
                        char_display = char_names.get(sts_char, sts_char.title())
                        embed_title = f"🗣️ {char_display} says:"
                        if original_message:
                            description_text = f"\"{original_message}\"\n" + description_text
                        thumbnail_url = char_thumbnails.get(sts_char)
                    elif is_tts:
                        embed_title = f"🗣️ Gertrudes says:"
                        if original_message:
                            description_text = f"\"{original_message}\"\n" + description_text
                    
                    from bot.ui import SoundBeingPlayedView
                    # Pass behavior reference if available
                    behavior_ref = self._behavior if hasattr(self, '_behavior') else None
                    view = SoundBeingPlayedView(behavior_ref, audio_file, include_add_to_list_select=True)
                    
                    embed = discord.Embed(title=embed_title, description=description_text, color=discord.Color.red())
                    embed.set_footer(text=footer_text)
                    if thumbnail_url:
                        embed.set_thumbnail(url=thumbnail_url)
                    sound_message = await bot_channel.send(embed=embed, view=view)
                    self.current_sound_message = sound_message
                    self.stop_progress_update = False
                    self.progress_already_updated = False
                    
                    # Re-send controls to keep them at the bottom
                    if hasattr(self, '_behavior') and self._behavior:
                        await self.message_service.send_controls(self._behavior)
                else:
                    # Slap sound - minimal message
                    embed = discord.Embed(title="👋 Slap!", color=discord.Color.orange())
                    sound_message = await bot_channel.send(embed=embed)
                    self.current_sound_message = sound_message
                    
                    # Re-send controls to keep them at the bottom
                    if hasattr(self, '_behavior') and self._behavior:
                        await self.message_service.send_controls(self._behavior)

            # FFmpeg options
            vol = effects.get('volume', 1.0) if effects else 1.0
            ffmpeg_options = f'-af "volume={vol}'
            if effects:
                filters = []
                if effects.get('pitch'):
                    filters.append(f"asetrate=44100*{effects['pitch']},aresample=44100")
                if effects.get('speed'):
                    filters.append(f"atempo={effects['speed']}")
                if effects.get('reverb'):
                    filters.append("aecho=0.8:0.9:1000:0.3")
                if effects.get('reverse'):
                    filters.append('areverse')
                if filters:
                    ffmpeg_options += "," + ",".join(filters)
            ffmpeg_options += '"'

            def after_playing(error):
                try:
                    if error:
                        error_message = str(error)
                        print(f'[AudioService] Error in playback: {error_message}')
                        if retry_count < MAX_RETRIES:
                            time.sleep(2)
                            asyncio.run_coroutine_threadsafe(
                                self.play_audio(
                                    channel, audio_file, user, is_entrance, is_tts,
                                    extra, original_message, send_controls,
                                    retry_count + 1, effects, show_suggestions, num_suggestions
                                ),
                                self.bot.loop
                            )
                    else:
                        if sound_message and self.sound_service:
                            asyncio.run_coroutine_threadsafe(
                                self.sound_service.delayed_list_selector_update(sound_message, audio_file),
                                self.bot.loop
                            )
                finally:
                    self.bot.loop.call_soon_threadsafe(self.playback_done.set)

            if not self.ffmpeg_path or not os.path.exists(self.ffmpeg_path):
                await self.message_service.send_error(f"Invalid FFmpeg path: {self.ffmpeg_path}")
                return False

            try:
                audio_source = discord.FFmpegPCMAudio(
                    audio_file_path,
                    executable=self.ffmpeg_path,
                    options=ffmpeg_options
                )
                audio_source = discord.PCMVolumeTransformer(audio_source, volume=self.volume)
                
                await asyncio.sleep(0.5)
                voice_client.play(audio_source, after=after_playing)
                self.playback_done.clear()
                
                if show_suggestions and not is_entrance and not is_tts and not is_slap_sound and self.sound_service:
                    asyncio.create_task(self.sound_service.find_and_update_similar_sounds(
                        sound_message=sound_message,
                        audio_file=audio_file,
                        original_message=original_message,
                        send_controls=False,
                        num_suggestions=num_suggestions
                    ))
                
                if sound_message and not is_slap_sound and duration > 0:
                    asyncio.create_task(self.update_progress_bar(sound_message, duration))

                return True
            except Exception as e:
                print(f"[AudioService] Error playing sound: {e}")
                if "Not connected to voice" in str(e):
                    try:
                        print("[AudioService] Detected zombie connection in play loop, forcing disconnect.")
                        await voice_client.disconnect(force=True)
                        await asyncio.sleep(1)
                    except:
                        pass
                self.playback_done.set()
                return False

        except Exception as e:
            print(f"[AudioService] Error in play_audio: {e}")
            traceback.print_exc()
            self.playback_done.set()
            return False

    async def update_progress_bar(self, sound_message: discord.Message, duration: float):
        """Update the progress bar embed for a currently playing sound."""
        if duration <= 0:
            return

        start_time = time.time()
        bar_length = 10
        duration_int = int(duration)
        
        try:
            while time.time() - start_time < duration:
                if self.stop_progress_update:
                    break
                    
                elapsed = time.time() - start_time
                elapsed_int = int(elapsed)
                progress = elapsed / duration
                filled_length = int(bar_length * progress)
                bar = "█" * filled_length + "░" * (bar_length - filled_length)
                
                if sound_message.embeds:
                    embed = sound_message.embeds[0]
                    lines = embed.description.split('\n') if embed.description else []
                    new_lines = []
                    for line in lines:
                        if line.startswith("Progress:"):
                            new_lines.append(f"Progress: {bar} {elapsed_int}s / {duration_int}s")
                        else:
                            new_lines.append(line)
                    
                    embed.description = "\n".join(new_lines)
                    try:
                        await sound_message.edit(embed=embed)
                    except discord.NotFound:
                        break
                    except Exception:
                        pass
                
                await asyncio.sleep(max(1, duration / 10)) # Update roughly 10 times

            # Final update
            if not self.stop_progress_update:
                if sound_message.embeds:
                    embed = sound_message.embeds[0]
                    lines = embed.description.split('\n') if embed.description else []
                    new_lines = []
                    bar = "█" * bar_length
                    for line in lines:
                        if line.startswith("Progress:"):
                            new_lines.append(f"Progress: {bar} {duration_int}s / {duration_int}s ✅")
                        else:
                            new_lines.append(line)
                    embed.description = "\n".join(new_lines)
                    try:
                        await sound_message.edit(embed=embed)
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

            if guild.id in self.keyword_sinks:
                return True

            # Wait for voice connection to fully stabilize
            await asyncio.sleep(1.0)
            
            # Re-check after delay
            voice_client = guild.voice_client
            if not voice_client or not voice_client.is_connected():
                print(f"[AudioService] Voice connection lost during delay, skipping keyword detection")
                return False

            print(f"[AudioService] Starting keyword detection in {guild.name}")
            sink = KeywordDetectionSink(self, guild)
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
                voice_client = guild.voice_client
                if voice_client:
                    voice_client.stop_recording()
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

class KeywordDetectionSink(sinks.Sink):
    def __init__(self, audio_service, guild):
        super().__init__()
        self.audio_service = audio_service
        self.guild = guild
        self.recognizers = {} # user_id -> vosk.KaldiRecognizer
        self.resample_states = {} # user_id -> audioop state
        self.last_audio_time = {} # user_id -> timestamp
        self.queue = queue.Queue()
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker, name=f"VoskWorker-{guild.id}", daemon=True)
        self.worker_thread.start()
        self.keyword = "chapada"
        # Log directory for per-user transcripts
        self.log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Data", "vosk_logs"))
        os.makedirs(self.log_dir, exist_ok=True)

    def _log_to_file(self, username, text):
        """Log final transcription to per-user file."""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_file = os.path.join(self.log_dir, f"{username}.txt")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {text}\n")
        except Exception as e:
            print(f"[VoskLogger] Error writing log for {username}: {e}")

    def stop(self):
        self.running = False
        self.queue.put((None, None))

    def write(self, data, user_id):
        if self.running:
            self.last_audio_time[user_id] = time.time()
            self.queue.put((data, user_id))

    def _worker(self):
        while self.running:
            try:
                # Wait for data or timeout to handle silence flushing
                try:
                    data, user_id = self.queue.get(timeout=0.1)
                except queue.Empty:
                    # Timeout reached - check for silent periods to flush Vosk
                    self._flush_silence()
                    continue

                if data is None: # Stop signal
                    break
                
                self.detect_keyword(data, user_id)
                self.queue.task_done()
            except Exception as e:
                print(f"[VoskWorker] Error: {e}")
                traceback.print_exc()

    def _flush_silence(self):
        """Force Vosk to finalize results for users who stopped talking."""
        now = time.time()
        
        for user_id, last_time in list(self.last_audio_time.items()):
            # If idle for > 300ms, force Vosk to finalize
            if now - last_time > 0.3:
                if user_id in self.recognizers:
                    rec = self.recognizers[user_id]
                    # Force finalization by getting the final result
                    result = json.loads(rec.FinalResult())
                    text = result.get("text", "").lower()
                    
                    if text:
                        member = self.guild.get_member(user_id)
                        username = member.name if member else f"user_{user_id}"
                        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        print(f"[{timestamp}] [Vosk Final (Flushed)] {username}: \"{text}\"")
                        self._log_to_file(username, text)
                        
                        if self.keyword in text:
                            print(f"[{timestamp}] [KeywordDetection] Detected keyword '{self.keyword}' from user {username}!")
                            # Reset state
                            del self.recognizers[user_id]
                            if user_id in self.resample_states: del self.resample_states[user_id]
                            asyncio.run_coroutine_threadsafe(self.trigger_slap(user_id), self.audio_service.bot.loop)
                
                # Remove from tracking until they speak again
                del self.last_audio_time[user_id]

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
                self.recognizers[user_id] = vosk.KaldiRecognizer(self.audio_service.vosk_model, 16000)

            rec = self.recognizers[user_id]
            if rec.AcceptWaveform(optimized_pcm):
                result = json.loads(rec.Result())
                text = result.get("text", "").lower()
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                if text:
                    print(f"[{timestamp}] [Vosk Final] {username}: \"{text}\"")
                    self._log_to_file(username, text)
            else:
                result = json.loads(rec.PartialResult())
                text = result.get("partial", "").lower()
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                if text:
                    # Only print partials if they are not silence flushes
                    if not is_silence:
                        print(f"[{timestamp}] [Vosk Hearing] {username}: \"{text}...\"")

            if text and self.keyword in text:
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"[{timestamp}] [KeywordDetection] Detected keyword '{self.keyword}' from user {username}!")
                # Reset state so we start fresh for the next detection
                if user_id in self.recognizers: del self.recognizers[user_id]
                if user_id in self.resample_states: del self.resample_states[user_id]
                # Trigger slap asynchronously
                asyncio.run_coroutine_threadsafe(self.trigger_slap(user_id), self.audio_service.bot.loop)
        except Exception as e:
            if not is_silence:
                print(f"[KeywordDetection] Error in detect_keyword for {username}: {e}")

    async def trigger_slap(self, user_id):
        if not self.guild.voice_client:
            return

        member = self.guild.get_member(user_id)
        requester_name = member.name if member else f"user_{user_id}"
        
        # Get a random slap sound
        slap_sounds = self.audio_service._behavior.db.get_sounds(slap=True, num_sounds=100)
        if slap_sounds:
            import random
            random_slap = random.choice(slap_sounds)
            channel = self.guild.voice_client.channel
            if channel:
                print(f"[KeywordDetection] Playing random slap for {requester_name}")
                await self.audio_service.play_slap(channel, random_slap[2], requester_name)
                # Log action
                self.audio_service._behavior.db.insert_action(requester_name, "keyword_slap", random_slap[0])

