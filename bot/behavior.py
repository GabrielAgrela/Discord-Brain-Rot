import asyncio
from datetime import datetime, timedelta
import time
import discord
import random
import functools
from mutagen.mp3 import MP3
import math # Added for ceiling function

from requests import HTTPError
from bot.downloaders.sound import SoundDownloader
import os
import uuid



from bot.tts import TTS
import csv
from bot.ui.components import (
    SoundBeingPlayedView,
    SoundBeingPlayedWithSuggestionsView,
    LoadingSimilarSoundsSelect,
    ControlsView,
    SoundView,
    EventView,
    PaginatedEventView,
)
from bot.downloaders.manual import ManualSoundDownloader
from moviepy.editor import VideoFileClip

import aiohttp
import re


from bot.database import Database
from bot.services.mute import MuteService
from bot.services.message import MessageService



class BotBehavior:
    def __init__(self, bot, ffmpeg_path):
        self.bot = bot
        self.ffmpeg_path = ffmpeg_path
        self.last_channel = {}
        self.playback_done = asyncio.Event()
        self.playback_done.set()  # Ensure the event starts in a ready state
        self.script_dir = os.path.dirname(__file__)  # Get the directory of the current script
        self.dwdir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Downloads"))
        
        # Initialize TTS and ManualSoundDownloader
        self.TTS = TTS(self, bot)
        self.ManualSoundDownloader = ManualSoundDownloader()

        self.view = None
        self.embed = None
        self.controls_message = None
        self.color = discord.Color.red()
        self.upload_lock = asyncio.Lock()
        self.brain_rot_lock = asyncio.Lock()  # Lock for brain rot functions
        self.brain_rot_cooldown_message = None # Message indicating brain rot is active
        # self.lastInteractionDateTime = current
        self.lastInteractionDateTime = datetime.now()
        self.last_played_time = None
        self.cooldown_message = None
        self.error_message = None
        self.checking_voice_connection = False
        self.current_sound_message = None  # Track the current sound's message
        self.stop_progress_update = False  # Flag to control progress updates
        self.progress_already_updated = False  # Flag to track if progress has been updated with emoji
        self.volume = 1.0  # Default volume for sound playback
        self.current_similar_sounds = None
        self.admin_channel = None
        self.mod_role = None
        self.now_playing_messages = []
        self.last_sound_played = {}
        self.mute_until = None
        
        # New SOLID-compliant services
        # These are instantiated here but will gradually replace inline logic
        self._mute_service = MuteService()
        self._message_service = None  # Will be set after bot is ready
        self.player_history_db = Database()
        self.db = self.player_history_db



    def is_admin_or_mod(self, member: discord.Member) -> bool:
        """Checks if a member has the DEVELOPER or MODERATOR role."""
        allowed_roles = {"DEVELOPER", "MODERATOR"}
        for role in member.roles:
            if role.name in allowed_roles:
                return True
        return False

    async def display_top_users(self, user, number_users=5, number_sounds=5, days=7, by="plays"):
        Database().insert_action(user.name, "list_top_users", by)
        top_users = Database().get_top_users(number_users, days, by)
        
        bot_channel = await self.get_bot_channel()
        
        total_plays = sum(count for _, count in top_users)

        messages = []
        for rank, (username, total_plays) in enumerate(top_users, 1):
            embed = discord.Embed(
                title=f"🔊 **#{rank} {username.upper()}**",
                description=f"🎵 **Total Sounds Played: {total_plays}**",
                color=discord.Color.green()
            )

            # Attempt to get user avatar, set a default if unavailable
            discord_user = discord.utils.get(self.bot.get_all_members(), name=username)
            if discord_user and discord_user.avatar:
                embed.set_thumbnail(url=discord_user.avatar.url)
            elif username == "syzoo":
                embed.set_thumbnail(url="https://media.npr.org/assets/img/2017/09/12/macaca_nigra_self-portrait-3e0070aa19a7fe36e802253048411a38f14a79f8-s800-c85.webp")
            elif discord_user:
                embed.set_thumbnail(url=discord_user.default_avatar.url)

            # You might want to add top sounds for each user here if that data is available
            top_sounds = Database().get_top_sounds(number=number_sounds, days=days, user=username)
            for sound in top_sounds[0]:
                embed.add_field(name=f"🎵 **{sound[0]}**", value=f"Played **{sound[1]}** times", inline=False)

            message = await bot_channel.send(embed=embed)
            messages.append(message)

        sound_summary, total_plays = Database().get_top_sounds(number=100000, days=days, user=None)
        average_per_day = total_plays / days
        title = f"🎵 **TOP MANUALLY PLAYED SOUNDS IN THE LAST {days} DAYS! TOTAL PLAYS: {total_plays}** 🎵"
        description = f"Average of {average_per_day:.0f} plays per day!"
        color = discord.Color.yellow()

        summary_embed = discord.Embed(
            title=title,
            description=description,
            color=color
        )
        summary_embed.set_thumbnail(url="https://i.imgflip.com/1vdris.jpg")
        summary_embed.set_footer(text="Updated as of")
        summary_embed.timestamp = datetime.utcnow()

        # Add top 10 sounds to the summary embed
        top_10_sounds = sound_summary[:10]
        for i, (sound_name, play_count) in enumerate(top_10_sounds, 1):
            summary_embed.add_field(
                name=f"#{i}: {sound_name}",
                value=f"Played {play_count} times",
                inline=False
            )

        summary_message = await bot_channel.send(embed=summary_embed)
        messages.append(summary_message)

        await self.send_controls()
        await asyncio.sleep(60)

        for message in messages:
            await message.delete()

    async def prompt_upload_sound(self, interaction):
        if self.upload_lock.locked():
            message = await interaction.channel.send(embed=discord.Embed(title="Another upload is in progress. Wait caralho 😤", color=self.color))
            await asyncio.sleep(10)
            await message.delete()
            return
        
        async with self.upload_lock:
            message = await interaction.channel.send(embed=discord.Embed(title="MP3/TikTok/YouTube/Instagram URL + custom name (optional). You can also DM me instead. ☝️🤓", color=self.color))

            def check(m):
                is_attachment = len(m.attachments) > 0 and m.attachments[0].filename.endswith('.mp3')
                is_mp3_url = re.match(r'^https?://.*\.mp3$', m.content)
                is_tiktok_url = re.match(r'^https?://.*tiktok\.com/.*$', m.content)
                is_youtube_url = re.match(r'^https?://(www\.)?(youtube\.com|youtu\.be)/.*$', m.content)
                is_instagram_url = re.match(r'^https?://(www\.)?instagram\.com/(p|reels|reel|stories)/.*$', m.content)
                return m.author == interaction.user and m.channel == interaction.channel and (is_attachment or is_mp3_url or is_tiktok_url or is_youtube_url or is_instagram_url)

            try:
                response = await self.bot.wait_for('message', check=check, timeout=60.0)
                await message.delete()

                # Extract the custom filename if provided
                custom_filename = None
                if response.content:
                    parts = response.content.split(maxsplit=1)
                    if len(parts) > 1 and not parts[0].startswith('http'):
                        custom_filename = response.content
                    elif len(parts) > 1 and parts[0].startswith('http'):
                        custom_filename = parts[1]

                # Handle time limit for TikTok, YouTube and Instagram
                time_limit = None
                if re.match(r'^https?://.*tiktok\.com/.*$', response.content) or \
                   re.match(r'^https?://(www\.)?(youtube\.com|youtu\.be)/.*$', response.content) or \
                   re.match(r'^https?://(www\.)?instagram\.com/(p|reels|reel|stories)/.*$', response.content):
                    parts = response.content.split(maxsplit=2)
                    if len(parts) > 1 and parts[1].isdigit():
                        time_limit = int(parts[1])
                        if len(parts) > 2:
                            custom_filename = parts[2]
                
                if len(response.attachments) > 0:
                    # Use secure save for attachments
                    file_path = await self.save_uploaded_sound_secure(response.attachments[0], custom_filename)
                elif re.match(r'^https?://.*tiktok\.com/.*$', response.content) or \
                     re.match(r'^https?://(www\.)?(youtube\.com|youtu\.be)/.*$', response.content) or \
                     re.match(r'^https?://(www\.)?instagram\.com/(p|reels|reel|stories)/.*$', response.content):
                    await self.send_message(title="Downloading video... 🤓", description="Espera, bixa", delete_time=5)
                    try:
                        file_path = await self.save_sound_from_video(response.content, custom_filename, time_limit=time_limit)
                    except ValueError as e:
                        error_message = await interaction.channel.send(embed=discord.Embed(title="Error", description=str(e), color=self.color))
                        await asyncio.sleep(10)
                        await error_message.delete()
                        return
                else:
                    file_path = await self.save_sound_from_url(response.content, custom_filename)

                Database().insert_action(interaction.user.name, "upload_sound", file_path)
                await response.delete()
                confirmation_message = await interaction.channel.send(embed=discord.Embed(title="Sound uploaded successfully! (may take up to 10s to be available)", color=self.color))
                await asyncio.sleep(10)
                await confirmation_message.delete()
            except asyncio.TimeoutError:
                await message.delete()
                timeout_message = await interaction.channel.send(embed=discord.Embed(title="Upload timed out 🤬", color=self.color))
                await asyncio.sleep(10)
                await timeout_message.delete()
            except Exception as e:
                error_message = await interaction.channel.send(embed=discord.Embed(title="An error occurred.", description=str(e), color=self.color))
                await asyncio.sleep(10)
                await error_message.delete()

    async def save_uploaded_sound(self, attachment, custom_filename=None):
        os.makedirs(self.dwdir, exist_ok=True)
        if custom_filename:
            filename = f"{custom_filename}.mp3"
        else:
            filename = attachment.filename
        file_path = os.path.join(self.dwdir, filename)
        await attachment.save(file_path)
        return file_path

    async def prompt_upload_mp3(self, interaction):
        """Prompt user to upload a single MP3 attachment with strong validation."""
        if self.upload_lock.locked():
            message = await interaction.channel.send(embed=discord.Embed(title="Another upload is in progress. Wait caralho 😤", color=self.color))
            await asyncio.sleep(10)
            await message.delete()
            return

        async with self.upload_lock:
            message = await interaction.channel.send(embed=discord.Embed(title="Attach an MP3 file (optional message = custom name). You can also DM me.", color=self.color))

            def check(m):
                return (
                    m.author == interaction.user
                    and m.channel == interaction.channel
                    and len(m.attachments) > 0
                    and m.attachments[0].filename.lower().endswith('.mp3')
                )

            try:
                response = await self.bot.wait_for('message', check=check, timeout=60.0)
                await message.delete()

                custom_filename = response.content.strip()[:50] if response.content else None
                file_path = await self.save_uploaded_sound_secure(response.attachments[0], custom_filename)

                Database().insert_action(interaction.user.name, "upload_sound", file_path)
                await response.delete()
                confirmation_message = await interaction.channel.send(embed=discord.Embed(title="Sound uploaded successfully! (may take up to 10s to be available)", color=self.color))
                await asyncio.sleep(10)
                await confirmation_message.delete()
            except asyncio.TimeoutError:
                await message.delete()
                timeout_message = await interaction.channel.send(embed=discord.Embed(title="Upload timed out 🤬", color=self.color))
                await asyncio.sleep(10)
                await timeout_message.delete()
            except Exception as e:
                error_message = await interaction.channel.send(embed=discord.Embed(title="An error occurred.", description=str(e), color=self.color))
                await asyncio.sleep(10)
                await error_message.delete()

    async def save_uploaded_sound_secure(self, attachment, custom_filename=None, max_mb: int = 20):
        """Save an uploaded attachment safely after validation.

        - Enforces `.mp3` extension
        - Sanitizes filename
        - Enforces size limit
        - Validates MP3 header / structure
        """
        os.makedirs(self.dwdir, exist_ok=True)

        # Enforce size limit using Discord-provided metadata first
        size_bytes = getattr(attachment, 'size', None)
        if size_bytes is not None and size_bytes > max_mb * 1024 * 1024:
            raise ValueError(f"File too large. Max allowed is {max_mb} MB.")

        # Determine safe filename base
        if custom_filename:
            base = custom_filename
        else:
            # strip extension from original
            base = os.path.splitext(attachment.filename)[0]

        # Sanitize filename
        base = re.sub(r'[^A-Za-z0-9_\-\. ]+', '', base).strip()
        base = re.sub(r'\s+', '_', base)
        if not base:
            base = 'sound'
        base = base[:50]

        # Always enforce .mp3 extension
        filename = f"{base}.mp3"

        # Avoid collisions
        final_path = os.path.join(self.dwdir, filename)
        counter = 1
        while os.path.exists(final_path):
            final_path = os.path.join(self.dwdir, f"{base}_{counter}.mp3")
            counter += 1

        # Save to a temporary file first
        tmp_path = os.path.join(self.dwdir, f"upload_{uuid.uuid4().hex}.part")
        await attachment.save(tmp_path)

        try:
            # Re-check size on disk
            actual_size = os.path.getsize(tmp_path)
            if actual_size > max_mb * 1024 * 1024:
                raise ValueError(f"File too large. Max allowed is {max_mb} MB.")

            # Basic MP3 validation: ID3 header or common frame sync bytes
            with open(tmp_path, 'rb') as f:
                head = f.read(4096)
            if not self._looks_like_mp3(head):
                raise ValueError("Uploaded file does not look like a valid MP3.")

            # Try parsing with mutagen for extra validation
            try:
                _ = MP3(tmp_path)
            except Exception:
                raise ValueError("Unable to parse MP3 metadata; file may be corrupt.")

            # Move into place
            os.replace(tmp_path, final_path)
        finally:
            # Clean up temp file on error
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

        return final_path

    def _looks_like_mp3(self, head: bytes) -> bool:
        if not head or len(head) < 2:
            return False
        # ID3v2 tag
        if head[:3] == b'ID3':
            return True
        # Look for common MP3 frame sync patterns within the first 4KB
        for i in range(0, min(len(head) - 1, 4095)):
            b0, b1 = head[i], head[i + 1]
            if b0 == 0xFF and b1 in (0xFB, 0xF3, 0xF2) or (b0 == 0xFF and (b1 & 0xE0) == 0xE0):
                return True
        return False
    
    async def save_sound_from_tiktok(self, url, custom_filename=None, time_limit=None):
        os.makedirs(self.dwdir, exist_ok=True)

        # Download the TikTok video
        filename = ManualSoundDownloader.tiktok_to_mp3(url, self.dwdir, custom_filename, time_limit)
        file_path = os.path.join(self.dwdir, filename)

        return file_path

    async def save_sound_from_url(self, url, custom_filename=None, max_mb: int = 20):
        os.makedirs(self.dwdir, exist_ok=True)

        # Sanitize target filename
        if custom_filename:
            base = custom_filename
        else:
            base = os.path.basename(url.split('?')[0])
            base = os.path.splitext(base)[0]
        base = re.sub(r'[^A-Za-z0-9_\-\. ]+', '', base).strip()
        base = re.sub(r'\s+', '_', base)
        if not base:
            base = 'sound'
        base = base[:50]

        final_path = os.path.join(self.dwdir, f"{base}.mp3")
        counter = 1
        while os.path.exists(final_path):
            final_path = os.path.join(self.dwdir, f"{base}_{counter}.mp3")
            counter += 1

        tmp_path = os.path.join(self.dwdir, f"download_{uuid.uuid4().hex}.part")
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise Exception("Failed to download the MP3 file.")

                # Pre-check content length if provided
                try:
                    cl = response.headers.get('Content-Length')
                    if cl and int(cl) > max_mb * 1024 * 1024:
                        raise Exception(f"File too large. Max allowed is {max_mb} MB.")
                except Exception:
                    pass

                with open(tmp_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        f.write(chunk)

        try:
            # Enforce size on disk
            actual_size = os.path.getsize(tmp_path)
            if actual_size > max_mb * 1024 * 1024:
                raise Exception(f"File too large. Max allowed is {max_mb} MB.")

            # Validate content looks like MP3
            with open(tmp_path, 'rb') as f:
                head = f.read(4096)
            if not self._looks_like_mp3(head):
                raise Exception("Downloaded file does not look like a valid MP3.")

            try:
                _ = MP3(tmp_path)
            except Exception:
                raise Exception("Unable to parse MP3 metadata; file may be corrupt.")

            os.replace(tmp_path, final_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

        return final_path

    async def save_sound_from_video(self, url, custom_filename=None, time_limit=None):
        os.makedirs(self.dwdir, exist_ok=True)

        # Download the video (TikTok or YouTube)
        filename = ManualSoundDownloader.video_to_mp3(url, self.dwdir, custom_filename, time_limit)
        file_path = os.path.join(self.dwdir, filename)

        return file_path

    async def get_new_name(self, interaction):
        message = await interaction.channel.send(embed=discord.Embed(title="Please enter the new name for the sound.", color=self.color))
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel
        try:
            response = await self.bot.wait_for('message', check=check, timeout=10.0)
            await response.delete()
            await message.delete()
        except asyncio.TimeoutError:
            await message.delete()
            return None
        return response.content

    async def write_list(self, message, description=""):
        formatted_message = "```" + "\n".join(message) + "```"  # Surrounds the message with code block markdown
        self.color = discord.Color.orange()
        message = await self.send_message(title=description, description=formatted_message)
        await asyncio.sleep(30)
        await message.delete()     

    async def delete_controls_message(self, delete_all=True):
        try:
            bot_channel = await self.get_bot_channel()
            if delete_all:
                async for message in bot_channel.history(limit=100):
                    if message.components and not message.embeds:
                        try:
                            first_label = message.components[0].children[0].label or ""
                        except Exception:
                            first_label = ""
                        if "Play Random" in first_label:
                            await message.delete()
            else:
                messages = await bot_channel.history(limit=100).flatten()
                control_messages = []
                for m in messages:
                    if m.components and not m.embeds:
                        try:
                            first_label = m.components[0].children[0].label or ""
                        except Exception:
                            first_label = ""
                        if "Play Random" in first_label:
                            control_messages.append(m)
                for message in control_messages[1:]:  # Skip the last message
                    await message.delete()
        except Exception as e:
            print(f"1An error occurred: {e}")

    async def delete_last_message(self, count=1):
        bot_channel = await self.get_bot_channel()
        async for message in bot_channel.history(limit=count):
            await message.delete()
            return
    
    async def clean_buttons(self, count=5):
        try:
            bot_channel = await self.get_bot_channel()
            async for message in bot_channel.history(limit=count):
                # if message.components and not empty
                if message.components and message.embeds:
                    await message.edit(view=None)      
                elif message.components:
                    await message.delete()                 
        except Exception as e:
            print(f"2An error occurred: {e}")
    
    async def get_bot_channel(self, bot_channel=None):
        if bot_channel:
            bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name=bot_channel)
            return bot_channel
        else:
            bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
            return bot_channel

    def get_mute_remaining(self):
        if not self.mute_until:
            return 0

        remaining = (self.mute_until - datetime.now()).total_seconds()
        if remaining <= 0:
            self.mute_until = None
            return 0

        return remaining

    async def activate_mute(self, duration_seconds=1800, requested_by=None):
        self.mute_until = datetime.now() + timedelta(seconds=duration_seconds)

        requester_text = ""
        if requested_by:
            requester_text = f" by {requested_by.mention}" if hasattr(requested_by, "mention") else f" by {requested_by.name}"

        minutes, seconds = divmod(duration_seconds, 60)
        parts = []
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        if seconds or not parts:
            parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
        duration_text = " ".join(parts)

        description = (
            f"🔇 The bot is muted{requester_text} for the next {duration_text}.\n"
            f"Mute ends at <t:{int(self.mute_until.timestamp())}:t>."
        )

        await self.send_message(
            title="🔕 30-Minute Mute Activated",
            description=description,
            delete_time=duration_seconds,
            send_controls=False,
        )

    async def deactivate_mute(self, requested_by=None):
        if not self.mute_until:
            return

        self.mute_until = None

        requester_text = ""
        if requested_by:
            requester_text = f" by {requested_by.mention}" if hasattr(requested_by, "mention") else f" by {requested_by.name}"

        await self.send_message(
            title="🔔 Mute Disabled",
            description=f"The bot has been unmuted{requester_text}.",
            delete_time=10,
            send_controls=False,
        )

    async def notify_mute_status(self):
        remaining_seconds = int(self.get_mute_remaining())
        if remaining_seconds <= 0:
            return

        minutes, seconds = divmod(remaining_seconds, 60)
        parts = []
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        if seconds or not parts:
            parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
        remaining_text = " ".join(parts)

        await self.send_message(
            title="🔕 Mute Active",
            description=f"The bot is muted for another {remaining_text}.",
            delete_time=10,
            send_controls=False,
        )

    def get_largest_voice_channel(self, guild):
        largest_channel = None
        largest_size = 0
        for channel in guild.voice_channels:
            if len(channel.members) > largest_size:
                largest_channel = channel
                largest_size = len(channel.members)
        return largest_channel
    
    def get_user_voice_channel(self, guild, user):
        #stip the user of the discriminator
        user = user.split("#")[0]
        for channel in guild.voice_channels:
            if channel.members:
                for member in channel.members:
                    if user in member.name:
                        return channel
        return None
    
    async def send_error_message(self, message):
        self.error_message = await self.send_message(view=None, title="🤬 Error 🤬", description=message)
        #await asyncio.sleep(3)
        #await self.cooldown_message.delete()

    async def ensure_voice_connected(self, channel):
        try:
            voice_client = channel.guild.voice_client

            if voice_client:
                if voice_client.channel.id != channel.id:
                    await voice_client.move_to(channel)
                return voice_client
            
            voice_client = await channel.connect(timeout=10.0)
            return voice_client

        except Exception as e:
            print(f"Error connecting to voice channel: {e}")
            # get current voice client
            voice_client = self.bot.voice_clients[0]
            return voice_client
       

    async def play_audio(self, channel, audio_file, user, 
                        is_entrance=False, is_tts=False, extra="", 
                        original_message="", # Crucial for finding relevant suggestions
                        send_controls=True, retry_count=0, effects=None, 
                        show_suggestions: bool = True, # New flag
                        num_suggestions: int = 5): # Control how many suggestions to fetch
        MAX_RETRIES = 3

        remaining_mute = self.get_mute_remaining()
        if remaining_mute:
            await self.notify_mute_status()
            return

        # Check cooldown first
        if self.last_played_time and (datetime.now() - self.last_played_time).total_seconds() < 2:
            bot_channel = await self.get_bot_channel()
            if self.cooldown_message is None and not is_entrance:
                self.cooldown_message = await bot_channel.send(embed=discord.Embed(title="Don't be rude, let Gertrudes speak 😤"))
                await asyncio.sleep(3)
                await self.cooldown_message.delete()
                self.cooldown_message = None
                return
        self.last_played_time = datetime.now()

        # Stop updating the previous sound's progress
        if self.current_sound_message and not self.progress_already_updated:
            self.stop_progress_update = True
            try:
                # Get the current progress bar state
                if self.current_sound_message.embeds:
                    embed = self.current_sound_message.embeds[0]
                    description_lines = embed.description.split('\n') if embed.description else []
                    progress_line = next((line for line in description_lines if line.startswith("Progress:")), None)
                    
                    if progress_line and not any(emoji in progress_line for emoji in ["👋", "⏭️"]):
                        description = []
                        if extra != "":
                            description.append(f"Similarity: {extra}%")
                        
                        # Check if interrupted by a slap sound
                        sound_info = Database().get_sound(audio_file, True)
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
                print(f"Error updating previous sound message: {e}")

        try:
            # Clear any previously stored similar sounds when starting a new sound
            self.current_similar_sounds = None
            
            voice_client = await self.ensure_voice_connected(channel)

            voice_client = await self.ensure_voice_connected(channel)

            # Get the absolute path of the audio file
            audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", audio_file))

            # Check if the audio file exists
            if not os.path.exists(audio_file_path):
                # Try to get the sound from database
                sound_info = Database().get_sound(audio_file, True)
                if sound_info and len(sound_info) > 2:
                    audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", sound_info[2]))
                    if not os.path.exists(audio_file_path):
                        await self.send_error_message(f"Audio file not found: {audio_file_path}")
                        print(f"Audio file not found: {audio_file_path}")
                        return
                else:
                    await self.send_error_message(f"Sound '{audio_file}' not found in database")
                    print(f"Sound '{audio_file}' not found in database")
                    return

            # Get audio duration
            try:
                audio = MP3(audio_file_path)
                duration = audio.info.length
                duration_str = f"{int(duration // 60)}:{int(duration % 60):02d}"
            except Exception as e:
                print(f"Error getting audio duration: {e}")
                duration_str = "Unknown"
                duration = 0

            # Send a message to the bot channel if the sound is not a slap, tiro or pubg-pan-sound-effect
            self.color = discord.Color.red()
            bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
            sound_message = None
            
            if bot_channel and not is_entrance:
                # Get sound info from database to check if it's a slap sound
                sound_info = Database().get_sound(audio_file, True)
                is_slap_sound = sound_info and sound_info[6] == 1  # Check slap attribute from database
                
                if not is_slap_sound:
                    description = []
                    if extra != "":
                        description.append(f"Similarity: {extra}%")
                    
                    # Get lists containing this sound
                    db = Database()
                    sound_filename = sound_info[2] if sound_info else audio_file
                    sound_id = sound_info[0] if sound_info else None
                    
                    # Get play count for this sound
                    play_count = 0
                    if sound_id:
                        play_count = db.get_sound_play_count(sound_id)
                        description.append(f"🔢 Play count: **{play_count + 1}**")
                    
                    # Add download date information
                    if sound_id:
                        download_date = db.get_sound_download_date(sound_id)
                        if download_date and download_date != "Unknown date":
                            try:
                                # Check for the hardcoded date first
                                if isinstance(download_date, str) and "2023-10-30" in download_date:
                                    description.append(f"📅 Added: **Before Oct 30, 2023**")
                                else:
                                    # Parse the date string to a datetime object
                                    if isinstance(download_date, str):
                                        # Try different date formats
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
                                        
                                        if not date_obj:
                                            raise ValueError(f"Could not parse date: {download_date}")
                                    else:
                                        date_obj = download_date
                                    
                                    # Format the date in a user-friendly way
                                    formatted_date = date_obj.strftime("%b %d, %Y")
                                    description.append(f"📅 Added: **{formatted_date}**")
                            except Exception as e:
                                print(f"Error formatting date: {e}")
                                description.append(f"📅 Added: **{download_date}**")
                        elif download_date:
                            description.append(f"📅 Added: **{download_date}**")
                    
                    # Add favorites information
                    if sound_id:
                        favorited_by = db.get_users_who_favorited_sound(sound_id)
                        if favorited_by:
                            if len(favorited_by) == 1:
                                description.append(f"⭐ Favorited by: **{favorited_by[0]}**")
                            else:
                                description.append(f"⭐ Favorited by: **{favorited_by[0]}**, **{favorited_by[1]}**" + 
                                                 (f" and {len(favorited_by) - 2} others" if len(favorited_by) > 2 else ""))
                                
                     # Add lists information
                    lists = db.get_lists_containing_sound(sound_filename)
                    if lists:
                        list_names = [f"**{list_name}** (by {creator})" for _, list_name, creator in lists]
                        if len(list_names) == 1:
                            description.append(f"📋 In list: {list_names[0]}")
                        else:
                            description.append(f"📋 In lists: {', '.join(list_names[:3])}")
                            if len(list_names) > 3:
                                description[-1] += f" and {len(list_names) - 3} more"

                    
                    # Initialize progress bar
                    current_time = "0:00"
                    description.append(f"⏱️ Duration: {duration_str}")
                    description.append(f"Progress: Loading...")
                    description_text = "\n".join(description) if description else None

                    view = SoundBeingPlayedView(self, audio_file, include_add_to_list_select=False)
                    if show_suggestions and not is_entrance and not is_tts and not is_slap_sound:
                        view.add_item(LoadingSimilarSoundsSelect())

                    sound_message = await self.send_message(
                        view=view,
                        title=f"🔊 **{sound_info[2].replace('.mp3', '') if sound_info and len(sound_info) > 2 else audio_file.replace('.mp3', '')}** 🔊",
                        description=description_text,
                        footer=f"{user} requested '{original_message}'" if original_message else f"Requested by {user}",
                        # Only send controls on the main message if no similar sounds are being shown
                        send_controls=True
                    )

                    
                    self.current_sound_message = sound_message
                    self.stop_progress_update = False
                    self.progress_already_updated = False  # Reset the flag for the new sound
                    
                   

            # Stop the audio if it is already playing
            if voice_client.is_playing():
                voice_client.stop()
                try:
                    await asyncio.wait_for(self.playback_done.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    print("Timeout waiting for previous playback to stop; continuing anyway.")
                    self.playback_done.set()

            # --- FFmpeg Options Setup ---
            ffmpeg_options = '-af "'
            filters = []

            # Default volume filter
            filters.append(f'volume={self.volume}')

            # Apply effects if provided
            if effects:
                # Volume adjustment (multiplier)
                volume_multiplier = effects.get("volume", 1.0)
                if volume_multiplier != 1.0:
                    filters.append(f'volume={volume_multiplier:.4f}')

                # Speed adjustment (tempo)
                speed = effects.get("speed", 1.0)
                if speed != 1.0:
                    # FFmpeg atempo filter works best in [0.5, 2.0] range.
                    # Chain multiple filters if needed.
                    # Max speed 3.0, so max 2 filters needed (2.0 * 1.5)
                    # Min speed 0.5, so max 1 filter needed.
                    current_speed = speed
                    while current_speed > 2.0:
                        filters.append('atempo=2.0')
                        current_speed /= 2.0
                    if current_speed < 0.5:
                        # Should not happen due to clamping in /toca, but safety check
                        filters.append('atempo=0.5')
                    elif current_speed != 1.0:
                         # Only add if it's not exactly 1 after adjustments
                        filters.append(f'atempo={current_speed:.4f}') 

                # Reverse
                if effects.get("reverse", False):
                    filters.append('areverse')
            
            # Join filters if any were added
            if filters:
                ffmpeg_options += ",".join(filters)
            ffmpeg_options += '"' # Close the -af option string
            # ---------------------------

            def after_playing(error):
                try:
                    if error:
                        error_message = str(error)
                        print(f'Error in playback: {error_message}')

                        if "not connected" in error_message.lower():
                            # Connection lost during playback
                            message = "Voice connection lost during playback"
                            print(message)
                            asyncio.run_coroutine_threadsafe(
                                self.send_error_message(message),
                                self.bot.loop
                            )
                        elif retry_count < MAX_RETRIES:
                            # Other errors, retry with delay
                            asyncio.run_coroutine_threadsafe(
                                self.send_error_message(f"Playback error: {error_message}. Retrying..."),
                                self.bot.loop
                            )
                            time.sleep(2)  # Increased delay
                            # Pass all parameters to keep consistency
                            asyncio.run_coroutine_threadsafe(
                                self.play_audio(
                                    channel, audio_file, user, is_entrance, is_tts,
                                    extra, original_message, send_controls,
                                    retry_count + 1, effects, show_suggestions, num_suggestions
                                ),
                                self.bot.loop
                            )
                    else:

                        # Add list selector after sound finishes playing successfully
                        if sound_message:
                            # Add a short delay to ensure suggestions have time to be added
                            asyncio.run_coroutine_threadsafe(
                                self.delayed_list_selector_update(sound_message, audio_file),
                                self.bot.loop
                            )
                finally:
                    # Set playback_done flag to signal completion regardless of outcome
                    self.bot.loop.call_soon_threadsafe(self.playback_done.set)

            # Check if FFmpeg path is set and valid
            if not self.ffmpeg_path or not os.path.exists(self.ffmpeg_path):
                await self.send_error_message(f"Invalid FFmpeg path: {self.ffmpeg_path}")
                print(f"Invalid FFmpeg path: {self.ffmpeg_path}")
                return

            # Play the audio file
            try:
                audio_source = discord.FFmpegPCMAudio(
                    audio_file_path,
                    executable=self.ffmpeg_path,
                    # Pass the constructed ffmpeg options
                    options=ffmpeg_options
                )
                
                # PCMVolumeTransformer might interfere with ffmpeg volume filter,
                # but is often needed for smoother playback. Test if it causes issues.
                # If volume seems off, consider removing this or adjusting ffmpeg volume.
                audio_source = discord.PCMVolumeTransformer(audio_source)
                
                # Add a small delay right before playing to ensure connection stability
                await asyncio.sleep(0.5)
                
                voice_client.play(audio_source, after=after_playing)
                print(f"Successfully playing audio: {audio_file}")

                 # Start finding similar sounds in a background task
                if show_suggestions and not is_entrance and not is_tts and not is_slap_sound:
                    # Pass all necessary parameters to the background task
                    asyncio.create_task(self.find_and_update_similar_sounds(
                        sound_message=sound_message,
                        audio_file=audio_file,
                        original_message=original_message,
                        send_controls=False,
                        num_suggestions=num_suggestions
                    ))
                
                self.playback_done.clear()
                if sound_message and not is_slap_sound and duration > 0:
                    # Start updating the progress bar
                    asyncio.create_task(self.update_progress_bar(sound_message, duration))

                return True
            except Exception as e:
                await self.send_error_message(f"Error playing sound: {e}")
                print(f"Error playing audio: {e}")
                import traceback
                traceback.print_exc()
                self.playback_done.set()
                return False
        except Exception as e:
            await self.send_error_message(f"Error in play_audio: {e}")
            print(f"Error in play_audio: {e}")
            import traceback
            traceback.print_exc()
            self.playback_done.set()
            return False

    async def update_progress_bar(self, sound_message, duration):
        """Update the progress bar for the currently playing sound"""
        start_time = time.time()
        duration_str = f"{int(duration // 60)}:{int(duration % 60):02d}"
        voice_client = discord.utils.get(self.bot.voice_clients, channel__guild=sound_message.guild)
        
        while voice_client and voice_client.is_playing() and not self.stop_progress_update:
            elapsed = time.time() - start_time
            progress = min(elapsed / duration, 1.0)
            bar_length = 20
            filled = '█' * int(bar_length * progress)
            empty = '░' * (bar_length - int(bar_length * progress))
            progress_bar = f"{filled}{empty}"
            
            current_minutes = int(elapsed // 60)
            current_seconds = int(elapsed % 60)
            current_time = f"{current_minutes}:{current_seconds:02d}"
            
            # Get the current description and update only the progress parts
            if sound_message.embeds:
                embed = sound_message.embeds[0]
                description_lines = embed.description.split('\n') if embed.description else []
                
                # Keep all lines except duration and progress
                updated_description = []
                for line in description_lines:
                    # Check for any variation of the duration line (with or without emoji)
                    if "Duration:" not in line and not line.startswith("Progress:"):
                        updated_description.append(line)
                
                # Add updated duration and progress
                updated_description.append(f"⏱️ Duration: {current_time} / {duration_str}")
                updated_description.append(f"Progress: {progress_bar}")
                
                embed.description = "\n".join(updated_description)
                # Only update the embed content without modifying the view
                await sound_message.edit(embed=embed)
            
            # Increase the delay between updates to reduce the frequency of
            # message edits. This helps determine if frequent updates are
            # causing short freezes during audio playback.
            await asyncio.sleep(1)  # Update every second
        
        # Remove only the progress bar when done
        if sound_message and not self.stop_progress_update:
            if sound_message.embeds:
                embed = sound_message.embeds[0]
                description_lines = embed.description.split('\n') if embed.description else []
                
                # Keep all lines except duration and progress
                updated_description = []
                for line in description_lines:
                    # Check for any variation of the duration line (with or without emoji)
                    if "Duration:" not in line and not line.startswith("Progress:"):
                        updated_description.append(line)
                
                # Add just the final duration
                updated_description.append(f"⏱️ Duration: {duration_str}")
                
                embed.description = "\n".join(updated_description)
                # Only update the embed content
                await sound_message.edit(embed=embed)

    async def update_bot_status(self):
        while True:
            if hasattr(self.bot, 'next_download_time'):
                time_left = self.bot.next_download_time - time.time()
                if time_left > 0:
                    minutes = round(time_left / 60)
                    if minutes < 2:
                        activity = discord.Activity(name=f'explosion imminent!!!', type=discord.ActivityType.playing)
                    else:
                        activity = discord.Activity(name=f'an explosion in ~{minutes}m', type=discord.ActivityType.playing)
                    await self.bot.change_presence(activity=activity)
            await asyncio.sleep(60)

    async def play_sound_periodically(self):
        while True:
            try:
                sleep_time = random.uniform(0, 800)
                self.bot.next_download_time = time.time() + sleep_time
                while time.time() < self.bot.next_download_time:
                    await asyncio.sleep(60)
                for guild in self.bot.guilds:
                    channel = self.get_largest_voice_channel(guild)
                    if channel is not None:
                        random_file = Database().get_random_sounds()

                        await self.play_audio(channel, random_file[0][2], "periodic function")
                        Database().insert_action("admin", "play_sound_periodically", random_file[0][0])
                    else:
                        await asyncio.sleep(sleep_time)
            except Exception as e:
                print(f"4An error occurred: {e}")
                await asyncio.sleep(60)

    async def play_random_sound(self, user="admin", effects=None):
        try:
            for guild in self.bot.guilds:
                if (user == "admin"):
                    channel = self.get_largest_voice_channel(guild)
                else:
                    channel = self.get_user_voice_channel(guild,user)
                if channel is not None:
                    random_sound = Database().get_random_sounds()
                    asyncio.create_task(self.play_audio(channel, random_sound[0][2], user, effects=effects))
                    Database().insert_action(user, "play_random_sound", random_sound[0][0])
        except Exception as e:
            print(f"3An error occurred: {e}")

    async def play_random_favorite_sound(self, username):
        channel = self.get_user_voice_channel(self.bot.guilds[0], username)
        favorite_sound = Database().get_random_sounds(favorite=True)
        Database().insert_action(username, "play_random_favorite_sound", favorite_sound[0][0])
        await self.play_audio(channel,favorite_sound[0][1], username)

    async def play_random_sound_from_list(self, list_name, username):
        """Play a random sound from a specific list"""
        try:
            channel = self.get_user_voice_channel(self.bot.guilds[0], username)
            if channel is None:
                return
            random_sound = Database().get_random_sound_from_list(list_name)
            if not random_sound:
                await self.send_error_message(f"No sounds found in list '{list_name}'.")
                return
            Database().insert_action(username, f"play_random_from_{list_name}", random_sound[0])
            await self.play_audio(channel, random_sound[1], username)
        except Exception as e:
            print(f"Error playing random sound from list {list_name}: {e}")

    def randomize_color(self):
        temp_color = discord.Color.random()
        while temp_color == self.color:
            temp_color = discord.Color.random()
        self.color = temp_color
    
    async def play_request(self, id, user, exact=False, effects=None):
        filename_to_play = None
        sound_id_to_log = None
        show_suggestions_flag = False
        filenames = [] # Initialize filenames

        if exact:
            # If exact, assume `id` is the filename. Don't show suggestions.
            # Attempt to get sound info to verify and get ID for logging
            sound_info = Database().get_sound(id, True) 
            if sound_info:
                filename_to_play = sound_info[2] # Use the actual filename from DB
                sound_id_to_log = sound_info[0]
                # Could potentially still show suggestions even if exact filename matched? 
                # For now, exact means no suggestions.
                show_suggestions_flag = False 
            else:
                # Maybe it's a direct path already? Risky. Let's error for now if not found.
                 await self.send_error_message(f"Exact sound '{id}' not found in database.")
                 print(f"Exact sound '{id}' requested by {user} not found in database.")
                 return
        else:
            # Find the best match
            filenames = Database().get_sounds_by_similarity(id, 1) # Find only the top match
            #remove first element from list
            if not filenames:
                await self.send_error_message(f"No sounds found matching '{id}'.")
                return
            filename_to_play = filenames[0][1] # Get the filename of the best match
            sound_id_to_log = filenames[0][0]  # Get the ID of the best match
            show_suggestions_flag = True # Request suggestions

        if not filename_to_play: # Should not happen if logic above is correct, but safety check
             await self.send_error_message(f"Could not determine sound to play for '{id}'.")
             return

        for guild in self.bot.guilds:
            channel = self.get_user_voice_channel(guild, user)
            if channel is not None:
                asyncio.create_task(self.play_audio(
                    channel, 
                    filename_to_play, 
                    user, 
                    original_message=id, # Pass the original search term
                    effects=effects, 
                    show_suggestions=show_suggestions_flag # Control suggestion fetching
                    # send_controls defaults to True, play_audio handles adjustment
                ))
                
                # Log the action with the determined sound ID
                if sound_id_to_log:
                     Database().insert_action(user, "play_request", sound_id_to_log)
                else:
                     # Fallback if ID couldn't be determined (should be rare)
                     Database().insert_action(user, "play_request_unknown_id", filename_to_play) 

                break # Assume we only play in the first guild found

    async def change_filename(self, oldfilename, newfilename, user):
        Database().insert_action(user.name, "change_filename", oldfilename + " to " + newfilename)
        await Database().update_sound(oldfilename, new_filename=newfilename)
                    
    async def tts(self, user, speech, lang="en", region=""):
        Database().insert_action(user.name, "tts", speech)
        await self.TTS.save_as_mp3(speech, lang, region)   

    async def tts_EL(self, user, speech, lang="en", region=""):
        Database().insert_action(user.name, "tts_EL", speech)
        await self.TTS.save_as_mp3_EL(speech, lang, region)  

    async def sts_EL(self, user, sound, char="ventura", region=""):
        await self.TTS.speech_to_speech(sound, char, region)  


    
    async def list_sounds(self, user, count=0):
        try:
            bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
            if bot_channel:
                message = ""
                sounds = Database().get_sounds(num_sounds=count)
                if count > 0:
                    sound_view = SoundView(self, sounds)
                    Database().insert_action(user.name, "list_last_sounds", str(count))
                    message = await self.send_message(title="Last "+ str(count)+" Sounds Downloaded", view=sound_view)
                else:
                    Database().insert_action(user.name, "list_all_sounds", "all")
                    message = await self.send_message(description="Total sounds downloaded: "+str(len(sounds)), file=discord.File(self.db_path, 'Data/soundsDB.csv'))
                print(f"Message sent to the chat.")
                await asyncio.sleep(120)
                await message.delete()
                return
        except Exception as e:
            print(f"An error occurred: {e}")







    async def subway_surfers(self, user):
        folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Data", "SubwaySurfers"))
        files = os.listdir(folder)
        file = random.choice(files)
        title = files.index(file) + 1  # Adding 1 because index is 0-based
        message = await self.send_message(title="Subway Surfers clip "+str(title)+" of "+str(len(files)), file=discord.File(os.path.abspath(os.path.join(folder, file)), f"SubwaySurfers/{file}"))
        await asyncio.sleep(VideoFileClip(os.path.join(folder, file)).duration + 5)
        Database().insert_action(user.name, "subway_surfers", file)
        await message.delete()
    
    async def slice_all(self, user):
        folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Data", "SliceAll"))
        files = os.listdir(folder)
        file = random.choice(files)
        title = files.index(file) + 1  # Adding 1 because index is 0-based
        message = await self.send_message(title="Slice All clip "+str(title)+" of "+str(len(files)), file=discord.File(os.path.abspath(os.path.join(folder, file)), f"SliceAll/{file}"))
        await asyncio.sleep(VideoFileClip(os.path.join(folder, file)).duration + 5)
        Database().insert_action(user.name, "slice_all", file)
        await message.delete()

    async def family_guy(self, user):
        folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Data", "FamilyGuy"))
        files = os.listdir(folder)
        file = random.choice(files)
        title = files.index(file) + 1  # Adding 1 because index is 0-based
        message = await self.send_message(title="Family Guy clip "+str(title)+" of "+str(len(files)), file=discord.File(os.path.abspath(os.path.join(folder, file)), f"FamilyGuy/{file}"))
        await asyncio.sleep(VideoFileClip(os.path.join(folder, file)).duration + 5)
        Database().insert_action(user.name, "family_guy", file)
        await message.delete()

    async def send_message(self, title="", description="",footer=None, thumbnail=None, view=None, send_controls=True, file=None, delete_time=0, bot_channel=None):
        bot_channel = await self.get_bot_channel(bot_channel)
        embed = discord.Embed(title=title, description=description, color=self.color)
        embed.set_thumbnail(url=thumbnail)
        embed.set_footer(text=footer)
        embed.add_field(name="", value="[🥵 gabrielagrela.com 🥵](https://gabrielagrela.com)")
        if delete_time > 0:
            message = await bot_channel.send(view=view, embed=None if description == "" and title == "" else embed, file=file, delete_after=delete_time)
        else:
            message = await bot_channel.send(view=view, embed=None if description == "" and title == "" else embed, file=file)
        if send_controls:
            await self.send_controls()
        return message
    
    async def is_channel_empty(self, channel):
        if len(channel.members) == 0 or (len(channel.members) == 1 and self.bot.user in channel.members):
            await self.bot.voice_clients[0].disconnect()
            bot_channel = await self.get_bot_channel()
            await bot_channel.send(f"Disconnected from {channel.name} because it was empty")
            return True

        return False

    async def send_controls(self, force=False):
        bot_channel = await self.get_bot_channel()
        try:
            if self.controls_message:
                try:
                    await self.controls_message.delete()
                except:
                    pass
            self.controls_message = await bot_channel.send(view=ControlsView(self))
        except Exception as e:
            print("error sending controls ", e)
        
    async def is_playing_sound(self):
        for vc in self.bot.voice_clients:
            if vc.is_playing():
                return True
        return False


    

        
    #every 10 seconds check if the user is in a game


    
    async def add_user_event(self, username, event, sound_name):
        """Add a join/leave event sound for a user"""
        try:
            # Find the most similar sound in the database
            similar_sounds = Database().get_sounds_by_similarity(sound_name)
            if not similar_sounds:
                return False
            
            # Get the most similar sound
            most_similar_sound = similar_sounds[0][2].split('/')[-1].replace('.mp3', '')
            
            # Add the event sound to the database
            success = Database().toggle_user_event_sound(username, event, most_similar_sound)
            
            # Log the action
            if success:
                Database().insert_action(username, f"add_{event}_sound", most_similar_sound)
            
            return success
        except Exception as e:
            print(f"Error adding user event: {e}")
            return False





    async def list_user_events(self, user, user_full_name, requesting_user=None):
        """List all join/leave events for a user with delete buttons"""
        # Get user's events from database
        join_events = Database().get_user_events(user_full_name, "join")
        leave_events = Database().get_user_events(user_full_name, "leave")
        user_name = user_full_name.split('#')[0]
        
        if not join_events and not leave_events:
            return False
        
        # Log the action
        action_user = requesting_user if requesting_user else user
        Database().insert_action(action_user, "list_events", f"{len(join_events) + len(leave_events)} events for {user}")
        
        # Send a message for each event type with all its events
        if join_events:
            total_events = len(join_events)
            current_page_end = min(20, total_events)
            
            description = "**Current sounds:**\n"
            description += "\n".join([f"• {event[2]}" for event in join_events[:current_page_end]])
            description += f"\nShowing sounds 1-{current_page_end} of {total_events}"
            
            await self.send_message(
                title=f"🎵 {user_name}'s Join Event Sounds (Page 1/{(total_events + 19) // 20})",
                description=description,
                view=PaginatedEventView(self, join_events, user_full_name, "join"),
                delete_time=60
            )
        
        if leave_events:
            total_events = len(leave_events)
            current_page_end = min(20, total_events)
            
            description = "**Current sounds:**\n"
            description += "\n".join([f"• {event[2]}" for event in leave_events[:current_page_end]])
            description += f"\nShowing sounds 1-{current_page_end} of {total_events}"
            
            await self.send_message(
                title=f"🎵 {user_name}'s Leave Event Sounds (Page 1/{(total_events + 19) // 20})",
                description=description,
                view=PaginatedEventView(self, leave_events, user_full_name, "leave"),
                delete_time=60
            )
        
        return True

    async def find_and_update_similar_sounds(self, sound_message, audio_file, original_message, send_controls, num_suggestions):
        """Find similar sounds and update the original message with them."""
        try:
            # Check if the sound message still exists
            try:
                await sound_message.edit(content=sound_message.content)  # Small edit to verify message exists
            except discord.NotFound:
                print(f"Sound message was deleted before similar sounds could be added")
                return
            
            # Get the sound name without .mp3 extension
            sound_info = Database().get_sound(audio_file, True)
            if not sound_info:
                print(f"Could not find sound info for {audio_file}")
                return
                
            sound_name = sound_info[2].replace('.mp3', '')
            
            # Skip if the sound name matches the original message exactly
            if sound_name == original_message:
                return
            
            # Use original_message for similarity search
            # Fetch N+1 in case the top result is the one being played
            loop = asyncio.get_running_loop()
            all_similar = await loop.run_in_executor(
                None,
                functools.partial(
                    Database().get_sounds_by_similarity,
                    sound_name,
                    num_suggestions + 1,
                    0.00001,
                ),
            )
            
            if not all_similar:
                print(f"No similar sounds found for {sound_name}")
                return
            
            # Filter out the exact audio_file being played from suggestions
            similar_sounds_list = [s for s in all_similar if s[1] != audio_file]
            
            # Limit to the desired number of suggestions
            similar_sounds_list = similar_sounds_list[:num_suggestions]
            
            print(f"Found {len(similar_sounds_list)} similar sounds for {sound_name}")
            
            if not similar_sounds_list:
                print(f"No similar sounds left after filtering out current sound {audio_file}")
                return  # No similar sounds found
            
            # Store the similar sounds for later use when the sound finishes
            self.current_similar_sounds = similar_sounds_list
            
            # Create a new combined view
            combined_view = SoundBeingPlayedWithSuggestionsView(
                self, audio_file, similar_sounds_list, include_add_to_list_select=False
            )
            
            # Update the message with the combined view
            await sound_message.edit(view=combined_view)
            
            # Send controls as a separate message if needed
            if send_controls:
                await self.send_controls()
            
        except Exception as e:
            print(f"Error finding and updating similar sounds: {e}")
            import traceback
            traceback.print_exc()

    # New method to update message with list selector after playing
    async def update_sound_message_with_list_selector(self, sound_message, audio_file):
        try:
            # Check if message still exists
            try:
                await sound_message.edit(content=sound_message.content)
            except discord.NotFound:
                print("Sound message was deleted before list selector could be added")
                return
                
            # Import UI classes to avoid circular imports
            from bot.ui.components import SoundBeingPlayedView, SoundBeingPlayedWithSuggestionsView
            
            # Use the previously stored similar sounds instead of finding them again
            similar_sounds = self.current_similar_sounds
            
            if similar_sounds is None:
                # Fallback: if no similar sounds were stored, get them from database
                # This should only happen if suggestions were disabled initially
                sound_info = Database().get_sound(audio_file, True)
                if not sound_info:
                    print(f"Could not find sound info for {audio_file}")
                    return
                    
                sound_name = sound_info[2].replace('.mp3', '')
                
                # Get similar sounds (excluding the current one) without blocking the loop
                loop = asyncio.get_running_loop()
                similar_sounds = await loop.run_in_executor(
                    None,
                    functools.partial(Database().get_sounds_by_similarity, sound_name, 6, 0.00001),
                )  # Get 6 to ensure we have enough after filtering
                similar_sounds = [s for s in similar_sounds if s[1] != audio_file][:5]  # Limit to 5
                print(f"Fallback: Found {len(similar_sounds)} similar sounds for updating message")
            else:
                print(f"Reusing {len(similar_sounds)} previously found similar sounds for updating message")
            
            # Create new view
            if similar_sounds:
                new_view = SoundBeingPlayedWithSuggestionsView(
                    self, audio_file, similar_sounds, include_add_to_list_select=True
                )
            else:
                new_view = SoundBeingPlayedView(
                    self, audio_file, include_add_to_list_select=True
                )
            
            # Update the message view
            await sound_message.edit(view=new_view)
            
            # Clear the stored similar sounds after use
            self.current_similar_sounds = None
            
        except Exception as e:
            print(f"Error updating sound message with list selector: {e}")
            import traceback
            traceback.print_exc()

    async def delayed_list_selector_update(self, sound_message, audio_file):
        """Wait a moment for suggestions to be added, then update with the list selector"""
        # Wait 1.5 seconds to ensure suggestions have time to be added
        await asyncio.sleep(1.5)
        await self.update_sound_message_with_list_selector(sound_message, audio_file)

    async def cleanup_all_voice_connections(self):
        """Clean up all voice connections across all guilds"""
        print("Cleaning up all voice connections...")
        for vc in list(self.bot.voice_clients):
            try:
                print(f"Disconnecting from {vc.channel.name} in {vc.guild.name}")
                await vc.disconnect(force=True)
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Error disconnecting from {vc.guild.name}: {e}")
        
        print("All voice connections cleaned up.")

