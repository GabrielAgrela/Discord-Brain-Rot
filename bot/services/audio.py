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
    StatsRepository, KeywordRepository
)

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

    def set_sound_service(self, sound_service):
        self.sound_service = sound_service

    def set_voice_transformation_service(self, vt_service):
        self.voice_transformation_service = vt_service

    def set_behavior(self, behavior):
        """Set reference to BotBehavior for passing to views."""
        self._behavior = behavior
        self.bot.behavior = behavior

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
                        num_suggestions: int = 25,
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
                        # Stop keyword detection first
                        await self.stop_keyword_detection(channel.guild)
                        await voice_client.disconnect(force=True)
                        await asyncio.sleep(1)
                        # Reconnect and restart keyword detection
                        print("[AudioService] Attempting to reconnect after zombie cleanup...")
                        new_vc = await self.ensure_voice_connected(channel)
                        if new_vc:
                            print("[AudioService] Reconnected successfully, retrying sound playback...")
                            # Retry playing the sound (increment retry count to prevent infinite loop)
                            return await self.play_audio(
                                channel, audio_file, user, is_entrance, is_tts,
                                extra, original_message, send_controls,
                                retry_count + 1, effects, show_suggestions, num_suggestions
                            )
                    except Exception as reconnect_error:
                        print(f"[AudioService] Error during zombie cleanup/reconnect: {reconnect_error}")
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
                            new_lines.append(f"Progress: {bar}")
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
                            new_lines.append(f"Progress: {bar} ✅")
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
        # Audio buffering for /llmdebug (Global)
        self.buffer_seconds = 30
        self.full_buffer_size = 48000 * 2 * 2 * self.buffer_seconds 
        self.audio_ring_buffer = bytearray(self.full_buffer_size)
        self.buffer_pos = 0
        self.buffer_last_update: Dict[int, float] = {} # user_id -> timestamp (persistent)
        self.buffer_lock = threading.Lock()
        
        # Auto-AI Commentary state
        self.speech_start_time: Dict[int, float] = {} # user_id -> timestamp when they started talking
        self.ventura_trigger_times: Dict[int, float] = {} # user_id -> timestamp when "ventura" was heard
        # Exact keywords to match (must be whole words, not substrings)
        self.ventura_keywords = ["ventura", "andré ventura", "andre ventura"]
        self.last_ventura_trigger_time = 0
        self.ventura_trigger_enabled = False  # Set to True to enable Ventura speech trigger

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

    def write(self, data, user_id):
        if not self.running:
            return
        receive_time = time.time()
        self.last_audio_time[user_id] = receive_time
        self.buffer_last_update[user_id] = receive_time
        
        # Track speech duration for Auto-AI
        if user_id not in self.speech_start_time:
            self.speech_start_time[user_id] = receive_time
        else:
            duration = receive_time - self.speech_start_time[user_id]
            if duration >= 2.0: # User has been talking for 2+ seconds
                # Trigger Auto-AI
                if hasattr(self.audio_service.bot, 'behavior'):
                    behavior = self.audio_service.bot.behavior
                    if hasattr(behavior, '_ai_commentary_service'):
                        asyncio.run_coroutine_threadsafe(
                            behavior._ai_commentary_service.trigger_commentary(self.guild.id),
                            self.loop
                        )
                    else:
                        print("[AutoAI] Error: _ai_commentary_service not found on behavior")
                else:
                    print("[AutoAI] Error: behavior not found on bot")
        
        # Add to global circular buffer for /llmdebug
        with self.buffer_lock:
            data_len = len(data)
            if data_len > self.full_buffer_size:
                data = data[-self.full_buffer_size:]
                data_len = len(data)
            
            end_pos = self.buffer_pos + data_len
            if end_pos <= self.full_buffer_size:
                self.audio_ring_buffer[self.buffer_pos:end_pos] = data
                self.buffer_pos = end_pos % self.full_buffer_size
            else:
                # Wrap around
                first_part_len = self.full_buffer_size - self.buffer_pos
                self.audio_ring_buffer[self.buffer_pos:] = data[:first_part_len]
                second_part_len = data_len - first_part_len
                self.audio_ring_buffer[:second_part_len] = data[first_part_len:]
                self.buffer_pos = second_part_len

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
        
        # 1. Handle Vosk flushing for speech-to-text (0.3s threshold)
        for user_id, last_time in list(self.last_audio_time.items()):
            idle_time = now - last_time
            if idle_time > 1:
                # Reset speech start time on silence
                if user_id in self.speech_start_time:
                    del self.speech_start_time[user_id]
                
                self._flush_user(user_id)
                if user_id in self.last_audio_time:
                    del self.last_audio_time[user_id]
            
            # Force flush after max segment duration even if still talking
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
                    
                    print(f"[VenturaTrigger] Silence detected (2s) for user {user_id}. Triggering AI commentary (duration={duration:.1f}s)")
                    if hasattr(self.audio_service.bot, 'behavior'):
                        behavior = self.audio_service.bot.behavior
                        if hasattr(behavior, '_ai_commentary_service'):
                            asyncio.run_coroutine_threadsafe(
                                behavior._ai_commentary_service.trigger_commentary(self.guild.id, force=True, duration=duration),
                                self.loop
                            )
            
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
        """Get the last N seconds of audio from the global ring buffer."""
        bytes_needed = 48000 * 2 * 2 * seconds
        if bytes_needed > self.full_buffer_size:
            bytes_needed = self.full_buffer_size
            
        with self.buffer_lock:
            if self.buffer_pos >= bytes_needed:
                return bytes(self.audio_ring_buffer[self.buffer_pos - bytes_needed : self.buffer_pos])
            else:
                # Need to wrap around for reading
                part2 = self.audio_ring_buffer[:self.buffer_pos]
                remaining = bytes_needed - len(part2)
                part1 = self.audio_ring_buffer[self.full_buffer_size - remaining :]
                return bytes(part1 + part2)

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
            
            # Check for keywords in flushed text
            for keyword, action in self.keywords.items():
                if keyword in text:
                    print(f"[{timestamp}] [KeywordDetection] Detected keyword '{keyword}' from user {username}!")
                    asyncio.run_coroutine_threadsafe(self.trigger_action(user_id, keyword, action), self.audio_service.bot.loop)
                    break  # Only trigger one action per flush

    def _check_keywords(self, text: str, result_obj: dict = None) -> tuple:
        """Check if any keyword is in the text as a whole word. Returns (keyword, action) or (None, None)."""
        import re
        
        # If we have word-level confidence, check it
        if result_obj and "result" in result_obj:
            for word_info in result_obj["result"]:
                word = word_info.get("word", "").lower()
                conf = word_info.get("conf", 0.0)
                
                # Use a higher threshold for keywords to avoid false positives (e.g., chaves vs chapada)
                if word in self.keywords and conf > 0.90:
                    print(f"[KeywordDetection] Confirmed keyword '{word}' with high confidence: {conf:.2f}")
                    return word, self.keywords[word]
                elif word in self.keywords:
                    print(f"[KeywordDetection] Ignored potential keyword '{word}' due to low confidence: {conf:.2f}")
            
            return None, None

        # Fallback for simple text check (use with caution)
        # We only do this if we don't have a structured result (should not happen for final results)
        for keyword, action in self.keywords.items():
            if re.search(rf"\b{re.escape(keyword.lower())}\b", text.lower()):
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
                        "o", "a", "os", "as", "um", "uma", "de", "do", "da", "em", "no", "na", "com", "para", "por",
                        "que", "se", "foi", "tem", "sim", "mas", "mais", "eu", "ele",
                        "eles", "isso", "esta", "este", "aqui", "quem", "como", "quando", "onde", "ventura"
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
                # Disable suggestions for keywords to avoid lag (user request)
                await self.audio_service.play_audio(channel, sound[2], requester_name, show_suggestions=False)
                self.audio_service._behavior.db.insert_action(requester_name, f"keyword_{keyword}", sound[0])
            else:
                print(f"[KeywordDetection] No sounds found in list '{list_name}'")
