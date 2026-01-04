import asyncio
import os
import discord
import time
import functools
from datetime import datetime
import traceback
from typing import Optional, List, Dict, Any
from mutagen.mp3 import MP3
from bot.database import Database

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
        self.db = Database()
        
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
                if voice_client.channel.id != channel.id:
                    await voice_client.move_to(channel)
                return voice_client
            
            voice_client = await channel.connect(timeout=10.0)
            return voice_client

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
                        
                        sound_info = self.db.get_sound(audio_file, True)
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

            audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Sounds", audio_file))

            if not os.path.exists(audio_file_path):
                # Try getting sound info by Filename first
                sound_info = self.db.get_sound(audio_file, False)
                if sound_info:
                    # Found by Filename, check if original filename exists on disk
                    original_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Sounds", sound_info[1]))
                    if os.path.exists(original_path):
                        audio_file_path = original_path
                    else:
                        # Try searching by original filename directly (legacy fallback)
                        sound_info_orig = self.db.get_sound(audio_file, True)
                        if sound_info_orig and len(sound_info_orig) > 2:
                            audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Sounds", sound_info_orig[2]))
                        else:
                            await self.message_service.send_error(f"Sound '{audio_file}' not found on disk or database")
                            return False
                else:
                     # Try searching by original filename directly (legacy fallback)
                    sound_info_orig = self.db.get_sound(audio_file, True)
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
            sound_info = self.db.get_sound(audio_file, False)
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
                        play_count = self.db.get_sound_play_count(sound_id)
                        description.append(f"🔢 Play count: {play_count + 1}")
                        
                        # Add download date information
                        download_date = self.db.get_sound_download_date(sound_id)
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
                    
                    # Add branding
                    description.append("[🥵 gabrielagrela.com 🥵](https://gabrielagrela.com)")
                    description.append(f"Requested by {user}")
                    
                    description_text = "\n".join(description)
                    
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
                    view = SoundBeingPlayedView(behavior_ref, audio_file, include_add_to_list_select=False)
                    
                    embed = discord.Embed(title=embed_title, description=description_text, color=discord.Color.red())
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
        
        try:
            while time.time() - start_time < duration:
                if self.stop_progress_update:
                    break
                    
                elapsed = time.time() - start_time
                progress = elapsed / duration
                filled_length = int(bar_length * progress)
                bar = "█" * filled_length + "░" * (bar_length - filled_length)
                percent = int(progress * 100)
                
                if sound_message.embeds:
                    embed = sound_message.embeds[0]
                    lines = embed.description.split('\n') if embed.description else []
                    new_lines = []
                    for line in lines:
                        if line.startswith("Progress:"):
                            new_lines.append(f"Progress: {bar} {percent}%")
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
                            new_lines.append(f"Progress: {bar} 100% ✅")
                        else:
                            new_lines.append(line)
                    embed.description = "\n".join(new_lines)
                    try:
                        await sound_message.edit(embed=embed)
                    except:
                        pass
        except Exception as e:
            print(f"[AudioService] Error updating progress bar: {e}")

