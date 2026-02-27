import os
import asyncio
import discord
import random
import re
import aiohttp
import functools
import uuid
import time
import sqlite3
import math
from typing import Optional, List, Tuple, Any
from bot.repositories import SoundRepository, ActionRepository, ListRepository
from bot.database import Database  # Keep for get_sounds_by_similarity until migrated
from moviepy.editor import VideoFileClip
from bot.downloaders.manual import ManualSoundDownloader
from mutagen.mp3 import MP3
from pydub import AudioSegment
from pydub.effects import compress_dynamic_range

class SoundService:
    """
    Service for managing sound files, metadata, and search.
    """
    
    def __init__(self, bot_behavior, bot, audio_service, message_service):
        self.bot_behavior = bot_behavior
        self.bot = bot
        self.audio_service = audio_service
        self.message_service = message_service
        
        # Repositories
        self.sound_repo = SoundRepository()
        self.action_repo = ActionRepository()
        self.list_repo = ListRepository()
        
        # Keep Database for complex queries (get_sounds_by_similarity)
        self.db = Database()
        self.manual_downloader = ManualSoundDownloader()
        self.upload_lock = asyncio.Lock()
        
        # Base paths
        self.sounds_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Sounds"))
        self.downloads_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Downloads"))
        self.enable_ingest_loudness_normalization = (
            os.getenv("SOUND_INGEST_NORMALIZE_ENABLED", "true").strip().lower()
            not in {"0", "false", "off", "no"}
        )
        self.ingest_loudness_target_dbfs = float(
            os.getenv("SOUND_INGEST_TARGET_DBFS", "-18.0")
        )
        self.ingest_peak_ceiling_dbfs = float(
            os.getenv("SOUND_INGEST_PEAK_CEILING_DBFS", "-2.0")
        )
        self.ingest_compression_enabled = (
            os.getenv("SOUND_INGEST_COMPRESS_ENABLED", "true").strip().lower()
            not in {"0", "false", "off", "no"}
        )
        self.ingest_compression_threshold_dbfs = float(
            os.getenv("SOUND_INGEST_COMPRESS_THRESHOLD_DBFS", "-14.0")
        )
        self.ingest_compression_ratio = max(
            1.0,
            float(os.getenv("SOUND_INGEST_COMPRESS_RATIO", "6.0")),
        )
        
        os.makedirs(self.sounds_dir, exist_ok=True)
        os.makedirs(self.downloads_dir, exist_ok=True)

    def _sanitize_mp3_filename(self, name: str, default_base: str) -> str:
        """Sanitize an mp3 filename while preserving spaces."""
        cleaned = (name or "").strip()
        if cleaned.lower().endswith(".mp3"):
            cleaned = cleaned[:-4]

        # Keep letters/numbers/underscore/dot/hyphen/spaces, drop everything else.
        cleaned = re.sub(r"[^\w\-. ]+", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")

        if not cleaned:
            cleaned = default_base

        return f"{cleaned}.mp3"

    def _normalize_mp3_loudness(self, sound_file: str, target_dbfs: float) -> None:
        """Normalize an MP3 file in-place with compression and peak-safe loudness."""
        temp_path = f"{sound_file}.normalized.tmp.mp3"
        try:
            sound = AudioSegment.from_file(sound_file, format="mp3")
            current_dbfs = float(sound.dBFS)
            if current_dbfs == float("-inf"):
                print(
                    f"[SoundService] Skipping loudness normalization for silent file: {sound_file}"
                )
                return

            working_sound = sound
            compression_applied = False
            if self.ingest_compression_enabled:
                working_sound = compress_dynamic_range(
                    working_sound,
                    threshold=self.ingest_compression_threshold_dbfs,
                    ratio=self.ingest_compression_ratio,
                    attack=5.0,
                    release=80.0,
                )
                compression_applied = True

            working_dbfs = float(working_sound.dBFS)
            if not math.isfinite(working_dbfs):
                print(
                    f"[SoundService] Skipping loudness normalization due to invalid dBFS: {sound_file}"
                )
                return
            peak_dbfs = float(working_sound.max_dBFS)
            gain_change = self._calculate_safe_gain(
                current_dbfs=working_dbfs,
                peak_dbfs=peak_dbfs,
                target_dbfs=target_dbfs,
                peak_ceiling_dbfs=self.ingest_peak_ceiling_dbfs,
            )
            if abs(gain_change) < 0.25 and not compression_applied:
                return

            normalized = working_sound.apply_gain(gain_change)
            final_peak_dbfs = float(normalized.max_dBFS)
            if math.isfinite(final_peak_dbfs) and final_peak_dbfs > self.ingest_peak_ceiling_dbfs:
                normalized = normalized.apply_gain(self.ingest_peak_ceiling_dbfs - final_peak_dbfs)

            normalized.export(temp_path, format="mp3")
            os.replace(temp_path, sound_file)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @staticmethod
    def _calculate_safe_gain(
        current_dbfs: float,
        peak_dbfs: float,
        target_dbfs: float,
        peak_ceiling_dbfs: float,
    ) -> float:
        """Return gain that targets loudness without exceeding peak ceiling."""
        desired_gain = target_dbfs - current_dbfs
        if not math.isfinite(peak_dbfs):
            return desired_gain
        max_allowed_gain = peak_ceiling_dbfs - peak_dbfs
        return min(desired_gain, max_allowed_gain)

    async def _maybe_normalize_ingested_mp3(self, sound_file: str) -> None:
        """Normalize ingested MP3 loudness when enabled, without failing upload flow."""
        if not self.enable_ingest_loudness_normalization:
            return
        try:
            await asyncio.to_thread(
                self._normalize_mp3_loudness,
                sound_file,
                self.ingest_loudness_target_dbfs,
            )
        except Exception as e:
            print(f"[SoundService] Loudness normalization failed for {sound_file}: {e}")

    async def play_random_sound(self, user: str = "admin", effects: Optional[dict] = None, guild: Optional[discord.Guild] = None):
        """Pick a random sound and play it in the user's or largest channel."""
        if guild is None:
            print("[SoundService] No guild available for play_random_sound")
            return

        guild_id = guild.id
        sounds = self.sound_repo.get_random_sounds(num_sounds=1, guild_id=guild_id)
        if not sounds:
            return
        
        sound = sounds[0]

        channel = self.audio_service.get_user_voice_channel(guild, user)
        if not channel:
            channel = self.audio_service.get_largest_voice_channel(guild)
            
        if channel:
            await self.audio_service.play_audio(channel, sound[2], user, effects=effects)
            self.action_repo.insert(user, "play_random_sound", sound[0], guild_id=guild_id)

    async def play_random_favorite_sound(self, username: str, guild: Optional[discord.Guild] = None):
        """Pick a random favorite sound for the user and play it."""
        if guild is None:
            print("[SoundService] No guild available for play_random_favorite_sound")
            return

        guild_id = guild.id
        sounds = self.sound_repo.get_random_sounds(favorite=True, num_sounds=1, guild_id=guild_id)
        if sounds:
            sound = sounds[0]

            channel = self.audio_service.get_user_voice_channel(guild, username)
            if not channel:
                channel = self.audio_service.get_largest_voice_channel(guild)
            
            if channel:
                await self.audio_service.play_audio(channel, sound[2], username)
                self.action_repo.insert(username, "play_random_favorite_sound", sound[0], guild_id=guild_id)

    async def play_random_sound_from_list(self, list_name: str, username: str, guild: Optional[discord.Guild] = None):
        """Play a random sound from a specific list."""
        try:
            if guild is None:
                print("[SoundService] No guild available for play_random_sound_from_list")
                return
            guild_id = guild.id

            channel = self.audio_service.get_user_voice_channel(guild, username)
            if not channel:
                channel = self.audio_service.get_largest_voice_channel(guild)
                
            if not channel:
                return

            random_sound = self.list_repo.get_random_sound_from_list(list_name, guild_id=guild_id)
            if not random_sound:
                await self.message_service.send_error(f"No sounds found in list '{list_name}'.")
                return
            
            self.action_repo.insert(username, f"play_random_from_{list_name}", random_sound[0], guild_id=guild_id)
            # random_sound[1] is filename
            await self.audio_service.play_audio(channel, random_sound[1], username)
        except Exception as e:
            print(f"[SoundService] Error playing random sound from list {list_name}: {e}")

    async def play_request(self, sound_id_or_name: str, user: str, exact: bool = False, effects: Optional[dict] = None, guild: Optional[discord.Guild] = None):
        """Play a specific sound requested by a user, with fuzzy matching support."""
        if guild is None:
            print("[SoundService] No guild available for play_request")
            return False
        guild_id = guild.id
        filenames = []
        
        # Always try exact match first (before fuzzy search)
        exact_match = self.sound_repo.get_by_filename(sound_id_or_name, guild_id=guild_id)
        if exact_match:
            filenames = [exact_match.filename]
        elif exact:
            # User requested exact match only, but no exact match found
            # Fallback to direct file check if not in DB
            if not sound_id_or_name.endswith('.mp3'):
                sound_id_or_name += '.mp3'
            filenames = [sound_id_or_name]
        else:
            # No exact match found, use fuzzy search
            results = self.db.get_sounds_by_similarity(sound_id_or_name, 1, guild_id=guild_id)
            for r in results:
                sound_data = r[0]
                # Robustly get filename from Row, dict, or tuple
                if isinstance(sound_data, (sqlite3.Row, dict)):
                    filenames.append(sound_data['Filename'])
                else:
                    filenames.append(sound_data[2])

        if not filenames:
            await self.message_service.send_error(f"No sounds found matching '{sound_id_or_name}'.")
            return False

        filename = filenames[0]

        channel = self.audio_service.get_user_voice_channel(guild, user)
        if not channel:
            channel = self.audio_service.get_largest_voice_channel(guild)

        if channel:
            # Extract clean sound name for similarity suggestions
            clean_name = filename.replace('.mp3', '')
            await self.audio_service.play_audio(
                channel, filename, user, 
                original_message=clean_name,
                effects=effects
            )
            
            # Insert action
            sound_info = self.sound_repo.get_sound(filename, guild_id=guild_id)
            if sound_info:
                self.action_repo.insert(user, "play_request", sound_info[0], guild_id=guild_id)
            return True
        return False

    async def save_uploaded_sound_secure(
        self,
        attachment: discord.Attachment,
        custom_filename: Optional[str] = None,
        max_mb: int = 20,
        guild_id: Optional[int] = None,
        lock_already_held: bool = False,
    ):
        """Save an uploaded Discord attachment safely after validation."""

        async def _save_without_lock() -> tuple[bool, str]:
            if not attachment.filename.lower().endswith('.mp3') and not custom_filename:
                return False, "Only .mp3 files are allowed."

            if attachment.size > max_mb * 1024 * 1024:
                return False, f"File too large! Max {max_mb}MB."

            # Sanitize filename while preserving spaces.
            final_filename = self._sanitize_mp3_filename(custom_filename or attachment.filename, "uploaded_sound")
            save_path = os.path.join(self.sounds_dir, final_filename)

            if os.path.exists(save_path):
                return False, f"A sound with the name '{final_filename}' already exists."

            await attachment.save(save_path)

            # Verify it's a valid MP3
            try:
                MP3(save_path)
            except Exception:
                os.remove(save_path)
                return False, "Invalid MP3 file format."

            await self._maybe_normalize_ingested_mp3(save_path)

            # Insert into DB
            self.sound_repo.insert_sound(final_filename, final_filename, guild_id=guild_id)
            self.db.invalidate_sound_cache()
            return True, save_path

        try:
            if lock_already_held:
                return await _save_without_lock()

            async with self.upload_lock:
                return await _save_without_lock()
        except Exception as e:
            print(f"[SoundService] Error saving uploaded sound: {e}")
            return False, "System error while saving file."


    async def prompt_upload_sound(self, interaction: discord.Interaction):
        """Prompt user for a sound upload (DM or channel interaction)."""
        if self.upload_lock.locked():
            await self.message_service.send_error("Another upload is in progress. Wait caralho 😤")
            return
        
        async with self.upload_lock:
            # Send initial prompt
            prompt_embed = discord.Embed(
                title="📤 Sound Upload",
                description="Drop an **MP3 file** or paste a **TikTok/YouTube/Instagram URL**.\n"
                            "Optionally add a custom name after the link.",
                color=discord.Color.blue()
            )
            prompt_msg = await interaction.channel.send(embed=prompt_embed)

            def check(m):
                if m.author != interaction.user or m.channel != interaction.channel:
                    return False
                
                is_attachment = any(a.filename.lower().endswith('.mp3') for a in m.attachments)
                is_url = re.match(r'^https?://', m.content)
                return is_attachment or is_url

            try:
                response = await self.bot.wait_for('message', check=check, timeout=60.0)
                await prompt_msg.delete()

                # Parse response
                custom_filename = None
                file_path = None
                
                if response.attachments:
                    # Handle attachment
                    custom_filename = response.content.strip() if response.content else None
                    success, result = await self.save_uploaded_sound_secure(
                        response.attachments[0],
                        custom_filename,
                        guild_id=interaction.guild.id if interaction.guild else None,
                        lock_already_held=True,
                    )
                    if not success:
                        await self.message_service.send_error(result)
                        return
                    file_path = result
                else:
                    # Handle URL
                    url_full = response.content.strip()
                    parts = url_full.split()
                    url = parts[0]
                    custom_filename = " ".join(parts[1:]) if len(parts) > 1 else None
                    
                    await self.message_service.send_message("⏳ Processing...", "Downloading and converting video...")
                    
                    if any(x in url for x in ["tiktok.com", "youtube.com", "youtu.be", "instagram.com"]):
                        file_path = await self.save_sound_from_video(url, custom_filename)
                    else:
                        file_path = await self.save_sound_from_url(
                            url,
                            custom_filename,
                            guild_id=interaction.guild.id if interaction.guild else None,
                        )

                if file_path:
                    filename = os.path.basename(file_path)
                    self.action_repo.insert(
                        interaction.user.name,
                        "upload_sound",
                        filename,
                        guild_id=interaction.guild.id if interaction.guild else None,
                    )
                    await self.message_service.send_message("✅ Success!", f"Sound `{filename}` uploaded successfully.")
                
                await response.delete()

            except asyncio.TimeoutError:
                await prompt_msg.delete()
                await self.message_service.send_error("Upload timed out 🤬")
            except Exception as e:
                await self.message_service.send_error(f"Error during upload: {str(e)}")

    async def save_sound_from_video(self, url: str, custom_filename: Optional[str] = None, time_limit: Optional[int] = None) -> str:
        """Download sound from TikTok or YouTube video to Downloads folder.
        
        The file will be picked up by move_sounds() which will move it to Sounds,
        register it in the database, and show the button view.
        """
        try:
            # Save to Downloads folder so move_sounds picks it up with button view
            downloads_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Downloads"))
            os.makedirs(downloads_dir, exist_ok=True)
            filename = self.manual_downloader.video_to_mp3(url, downloads_dir, custom_filename, time_limit)
            full_path = os.path.join(downloads_dir, filename)
            # Don't insert to DB here - move_sounds will do that
            return full_path
        except Exception as e:
            print(f"[SoundService] Error in save_sound_from_video: {e}")
            raise

    async def save_sound_from_url(
        self,
        url: str,
        custom_filename: Optional[str] = None,
        max_mb: int = 20,
        guild_id: Optional[int] = None,
    ) -> str:
        """Download an MP3 file directly from a URL."""
        # Build candidate base name from custom name or URL path.
        if custom_filename:
            candidate_name = custom_filename
        else:
            candidate_name = os.path.basename(url.split('?')[0])

        filename = self._sanitize_mp3_filename(candidate_name, "url_sound")
        base = filename[:-4]
        final_path = os.path.join(self.sounds_dir, filename)
        
        # Avoid collisions
        counter = 1
        while os.path.exists(final_path):
            final_path = os.path.join(self.sounds_dir, f"{base} {counter}.mp3")
            counter += 1

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"Failed to download. Status: {response.status}")
                
                content = await response.read()
                if len(content) > max_mb * 1024 * 1024:
                    raise Exception(f"File too large. Max {max_mb}MB.")
                
                with open(final_path, 'wb') as f:
                    f.write(content)
                
                # Verify it's an MP3
                try:
                    MP3(final_path)
                except:
                    os.remove(final_path)
                    raise Exception("Downloaded file is not a valid MP3.")

                await self._maybe_normalize_ingested_mp3(final_path)
                
                # Insert into DB
                self.sound_repo.insert_sound(
                    os.path.basename(final_path),
                    os.path.basename(final_path),
                    guild_id=guild_id,
                )
                self.db.invalidate_sound_cache()
                return final_path

    async def find_and_update_similar_sounds(self, sound_message, audio_file, original_message, send_controls=False, num_suggestions=25):
        """Background task to find similar sounds and update the playback message."""
        try:
            if not sound_message:
                return

            sound_info = self.sound_repo.get_sound(audio_file, True)
            if not sound_info:
                return

            sound_name = sound_info[2].replace('.mp3', '')
            
            # Use original_message for similarity search
            loop = asyncio.get_running_loop()
            all_similar = await loop.run_in_executor(
                None,
                functools.partial(
                    self.db.get_sounds_by_similarity,
                    sound_name,
                    num_suggestions + 1,
                    0.00001,
                    sound_message.guild.id if sound_message and sound_message.guild else None,
                ),
            )
            
            if not all_similar:
                return
            
            # Filter out current sound and deduplicate by filename
            seen_filenames = set()
            seen_filenames.add(audio_file)  # Exclude current sound
            similar_sounds_list = []
            for s in all_similar:
                sound_data = s[0]
                # Robustly get filename from Row, dict, or tuple
                if isinstance(sound_data, (sqlite3.Row, dict)):
                    filename = sound_data['Filename']
                else:
                    filename = sound_data[2]
                
                if filename not in seen_filenames:
                    seen_filenames.add(filename)
                    similar_sounds_list.append(s)
                if len(similar_sounds_list) >= num_suggestions:
                    break
            
            if not similar_sounds_list:
                return

            # Retrieve current label and toggle state to preserve it
            current_label = "▶️ 0:00"
            show_controls = False
            guild_id = sound_message.guild.id if sound_message and sound_message.guild else None
            current_view = self.audio_service.get_current_view(guild_id) if guild_id else self.audio_service.current_view
            if current_view:
                if hasattr(current_view, 'progress_button'):
                    current_label = current_view.progress_button.label
                if hasattr(current_view, 'show_controls'):
                    show_controls = current_view.show_controls

            from bot.ui import SoundBeingPlayedWithSuggestionsView
            combined_view = SoundBeingPlayedWithSuggestionsView(
                self.bot_behavior, 
                audio_file, 
                similar_sounds_list, 
                include_add_to_list_select=True,
                progress_label=current_label,
                show_controls=show_controls
            )
            
            await sound_message.edit(view=combined_view)
            
            # Update the current view in AudioService so progress bar continues
            if guild_id:
                self.audio_service.set_current_view(guild_id, combined_view)
            else:
                self.audio_service.current_view = combined_view
            
        except Exception as e:
            import traceback
            print(f"[SoundService] Error in find_and_update_similar_sounds: {e}")
            traceback.print_exc()

    async def delayed_list_selector_update(self, sound_message, audio_file):
        """Update playback message with list selection after sound finishes."""
        await asyncio.sleep(2)  # Wait for suggestions to finish
        
        try:
            from bot.ui import SoundBeingPlayedWithSuggestionsView
            guild_id = sound_message.guild.id if sound_message and sound_message.guild else None
            similar_sounds = (
                self.audio_service.get_current_similar_sounds(guild_id)
                if guild_id
                else self.audio_service.current_similar_sounds
            )
            
            # Fallback if suggestions were missed
            if similar_sounds is None:
                results = self.db.get_sounds_by_similarity(
                    audio_file.replace('.mp3', ''),
                    6,
                    guild_id=sound_message.guild.id if sound_message and sound_message.guild else None,
                )
                seen_filenames = set()
                seen_filenames.add(audio_file)  # Exclude current sound
                similar_sounds = []
                for s in results:
                    # s is a (sound_data, score) pair from get_sounds_by_similarity
                    sound_data = s[0]
                    # Handle both Row and Tuple
                    if isinstance(sound_data, (sqlite3.Row, dict)):
                        filename = sound_data['Filename']
                    else:
                        # It's a tuple, filename is at index 2
                        filename = sound_data[2]
                    
                    if filename not in seen_filenames:
                        seen_filenames.add(filename)
                        similar_sounds.append(s)
                    if len(similar_sounds) >= 25:
                        break

            # Retrieve current label and toggle state to preserve it (Final state ✅)
            current_label = "▶️ 0:00"
            show_controls = False
            current_view = self.audio_service.get_current_view(guild_id) if guild_id else self.audio_service.current_view
            if current_view:
                if hasattr(current_view, 'progress_button'):
                    current_label = current_view.progress_button.label
                if hasattr(current_view, 'show_controls'):
                    show_controls = current_view.show_controls

            view = SoundBeingPlayedWithSuggestionsView(
                self.bot_behavior, 
                audio_file, 
                similar_sounds, 
                include_add_to_list_select=True,
                progress_label=current_label,
                show_controls=show_controls
            )
            await sound_message.edit(view=view)
            
            # Update the current view in AudioService
            if guild_id:
                self.audio_service.set_current_view(guild_id, view)
            else:
                self.audio_service.current_view = view
            
        except Exception as e:
            import traceback
            print(f"[SoundService] Error in delayed_list_selector_update: {e}")
            traceback.print_exc()

    async def list_sounds(self, user, count=0, guild: Optional[discord.Guild] = None):
        """List sounds in the bot channel."""
        try:
            bot_channel = self.message_service.get_bot_channel(guild)
            if not bot_channel:
                return

            guild_id = guild.id if guild else None
            sounds = self.sound_repo.get_sounds(num_sounds=count, guild_id=guild_id)
            from bot.ui import SoundView
            
            if count > 0:
                self.action_repo.insert(user.name, "list_last_sounds", str(count), guild_id=guild_id)
                message = await self.message_service.send_message(
                    title=f"📦 Last {count} Sounds Downloaded", 
                    view=SoundView(self.bot_behavior, sounds),
                    message_format="image",
                    image_requester=user.name,
                    image_show_footer=False,
                    image_show_sound_icon=False,
                    image_border_color="#ED4245",
                )
            
            await asyncio.sleep(120)
            try:
                await message.delete()
            except:
                pass
        except Exception as e:
            print(f"[SoundService] Error listing sounds: {e}")

    async def change_filename(self, oldfilename: str, newfilename: str, user: Any):
        """Update a sound's filename in the database and log the action."""
        guild_id = user.guild.id if hasattr(user, "guild") and user.guild else None
        self.action_repo.insert(user.name, "change_filename", f"{oldfilename} to {newfilename}", guild_id=guild_id)
        await asyncio.to_thread(self.sound_repo.update_sound, oldfilename, new_filename=newfilename)
