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
from bot.ui import (
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
from bot.services.audio import AudioService
from bot.services.sound import SoundService
from bot.services.brain_rot import BrainRotService
from bot.services.user_event import UserEventService
from bot.services.voice_transformation import VoiceTransformationService
from bot.services.stats import StatsService
from bot.services.background import BackgroundService
from bot.services.backup import BackupService



class BotBehavior:
    def __init__(self, bot, ffmpeg_path):
        self.bot = bot
        self.ffmpeg_path = ffmpeg_path
        self.last_channel = {}
        self.script_dir = os.path.dirname(__file__)
        self.dwdir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Downloads"))
        
        # Services - SOLID-compliant modular architecture
        self._message_service = MessageService(bot)
        self._mute_service = MuteService(self._message_service)
        self._audio_service = AudioService(bot, ffmpeg_path, self._mute_service, self._message_service)
        self._sound_service = SoundService(self, bot, self._audio_service, self._message_service)
        self._brain_rot_service = BrainRotService(bot, self._audio_service, self._message_service)
        self._user_event_service = UserEventService(bot, self._audio_service, self._message_service)
        self._voice_transformation_service = VoiceTransformationService(bot, self._audio_service, self._message_service)
        self._stats_service = StatsService(bot, self._message_service, self._sound_service)
        self._background_service = BackgroundService(bot, self._audio_service, self._sound_service, self)
        self._backup_service = BackupService(bot, self._message_service)
        
        from bot.services.ai_commentary import AICommentaryService
        self._ai_commentary_service = AICommentaryService(self)
        
        # Start background tasks
        self._background_service.start_tasks()
        
        # Cross-link dependencies
        self._audio_service.set_sound_service(self._sound_service)
        self._audio_service.set_voice_transformation_service(self._voice_transformation_service)
        self._audio_service.set_behavior(self)
        self._message_service.set_behavior(self)
        self._user_event_service.set_behavior(self)
        
        # Legacy components still in transition
        self.TTS = self._voice_transformation_service.tts_engine
        self.ManualSoundDownloader = self._sound_service.manual_downloader
        self.db = self._sound_service.db

        self.view = None
        self.embed = None
        self.color = discord.Color.red()
        
        self.lastInteractionDateTime = datetime.now()
        self.admin_channel = None
        self.mod_role = None
        self.now_playing_messages = []
        self.last_sound_played = {}
        
    @property
    def playback_done(self): return self._audio_service.playback_done
    
    @property
    def last_played_time(self): return self._audio_service.last_played_time
    
    @property
    def cooldown_message(self): return self._audio_service.cooldown_message
    @cooldown_message.setter
    def cooldown_message(self, value): self._audio_service.cooldown_message = value
    
    @property
    def current_sound_message(self): return self._audio_service.current_sound_message
    @current_sound_message.setter
    def current_sound_message(self, value): self._audio_service.current_sound_message = value
    
    @property
    def stop_progress_update(self): return self._audio_service.stop_progress_update
    @stop_progress_update.setter
    def stop_progress_update(self, value): self._audio_service.stop_progress_update = value
    
    @property
    def progress_already_updated(self): return self._audio_service.progress_already_updated
    @progress_already_updated.setter
    def progress_already_updated(self, value): self._audio_service.progress_already_updated = value
    
    @property
    def volume(self): return self._audio_service.volume
    @volume.setter
    def volume(self, value): self._audio_service.volume = value
    
    @property
    def current_similar_sounds(self): return self._audio_service.current_similar_sounds
    @current_similar_sounds.setter
    def current_similar_sounds(self, value): self._audio_service.current_similar_sounds = value
    
    @property
    def controls_message(self): return self._message_service.controls_message
    @controls_message.setter
    def controls_message(self, value): self._message_service._controls_message = value
    
    @property
    def upload_lock(self): return self._sound_service.upload_lock
    
    @property
    def brain_rot_lock(self): return self._brain_rot_service.lock
    
    @property
    def brain_rot_cooldown_message(self): return self._brain_rot_service.cooldown_message
    @brain_rot_cooldown_message.setter
    def brain_rot_cooldown_message(self, value): self._brain_rot_service.cooldown_message = value

    def is_admin_or_mod(self, member: discord.Member) -> bool:
        """Checks if a member has the DEVELOPER or MODERATOR role."""
        allowed_roles = {"DEVELOPER", "MODERATOR"}
        for role in member.roles:
            if role.name in allowed_roles:
                return True
        return False

    async def display_top_users(self, user, number_users=5, number_sounds=5, days=7, by="plays"):
        await self.delete_controls_message()  # Delete controls first so it can be re-sent at bottom
        await self._stats_service.display_top_users(user, number_users, number_sounds, days, by)
        await self.send_controls()

    async def prompt_upload_sound(self, interaction):
        return await self._sound_service.prompt_upload_sound(interaction)

    async def save_uploaded_sound(self, attachment, custom_filename=None):
        success, result = await self._sound_service.save_uploaded_sound_secure(attachment, custom_filename)
        return result if success else None

    async def prompt_upload_mp3(self, interaction):
        return await self._sound_service.prompt_upload_sound(interaction) # They can be unified or handled similarly

    async def save_uploaded_sound_secure(self, attachment, custom_filename=None, max_mb: int = 20):
        return await self._sound_service.save_uploaded_sound_secure(attachment, custom_filename, max_mb)
    
    async def save_sound_from_tiktok(self, url, custom_filename=None, time_limit=None):
        return await self._sound_service.save_sound_from_video(url, custom_filename, time_limit)

    async def save_sound_from_url(self, url, custom_filename=None, max_mb: int = 20):
        return await self._sound_service.save_sound_from_url(url, custom_filename, max_mb)

    async def save_sound_from_video(self, url, custom_filename=None, time_limit=None):
        return await self._sound_service.save_sound_from_video(url, custom_filename, time_limit)

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
        return await self._message_service.delete_controls_message(delete_all)

    async def delete_last_message(self, count=1):
        bot_channel = await self.get_bot_channel()
        if bot_channel:
            return await self._message_service.delete_messages(bot_channel, count, bot_only=False)
    
    async def clean_buttons(self, count=5):
        return await self._message_service.clean_buttons(count)
    
    async def get_bot_channel(self, bot_channel=None):
        return self._message_service.get_bot_channel(self.bot.guilds[0] if self.bot.guilds else None)

    def get_mute_remaining(self):
        return self._mute_service.get_remaining_seconds()

    async def activate_mute(self, duration_seconds=1800, requested_by=None):
        return await self._mute_service.activate(duration_seconds, str(requested_by) if requested_by else None)

    async def deactivate_mute(self, requested_by=None):
        return await self._mute_service.deactivate(str(requested_by) if requested_by else None)

    async def notify_mute_status(self):
        if self._mute_service.is_muted:
            return await self._message_service.send_message(
                title="🔇 Bot Muted",
                description=f"Muted for {self._mute_service.get_remaining_formatted()}",
            )

    def get_largest_voice_channel(self, guild):
        return self._audio_service.get_largest_voice_channel(guild)

    def get_user_voice_channel(self, guild, user):
        user_name = user if isinstance(user, str) else user.name
        return self._audio_service.get_user_voice_channel(guild, user_name)

    def send_error_message(self, message):
        asyncio.create_task(self._message_service.send_error(message))

    async def ensure_voice_connected(self, channel):
        return await self._audio_service.ensure_voice_connected(channel)
       

    async def play_audio(self, channel, audio_file, user, **kwargs):
        return await self._audio_service.play_audio(channel, audio_file, user, **kwargs)

    async def update_progress_bar(self, sound_message, duration):
        return await self._audio_service.update_progress_bar(sound_message, duration)

    async def update_bot_status(self):
        pass # Handled by BackgroundService

    async def play_sound_periodically(self):
        pass # Handled by BackgroundService

    async def play_random_sound(self, user="admin", effects=None):
        return await self._sound_service.play_random_sound(user, effects)

    async def play_random_favorite_sound(self, username):
        return await self._sound_service.play_random_favorite_sound(username)

    async def play_random_sound_from_list(self, list_name, username):
        return await self._sound_service.play_random_sound_from_list(list_name, username)

    async def play_request(self, id, user, exact=False, effects=None):
        return await self._sound_service.play_request(id, user, exact, effects)

    async def change_filename(self, oldfilename, newfilename, user):
        return await self._sound_service.change_filename(oldfilename, newfilename, user)
                    
    async def tts(self, user, speech, lang="en", region=""):
        return await self._voice_transformation_service.tts(user, speech, lang, region)

    async def tts_EL(self, user, speech, lang="en", region=""):
        return await self._voice_transformation_service.tts_EL(user, speech, lang, region)

    async def sts_EL(self, user, sound, char="ventura", region=""):
        return await self._voice_transformation_service.sts_EL(user, sound, char, region)


    
    async def list_sounds(self, user, count=0):
        return await self._sound_service.list_sounds(user, count)







    async def run_random_brain_rot(self, user):
        return await self._brain_rot_service.run_random(user)

    async def subway_surfers(self, user):
        return await self._brain_rot_service.subway_surfers(user)

    async def slice_all(self, user):
        return await self._brain_rot_service.slice_all(user)

    async def family_guy(self, user):
        return await self._brain_rot_service.family_guy(user)

    async def send_message(self, **kwargs):
        # Merge local color if not provided
        if 'color' not in kwargs:
            kwargs['color'] = self.color
        return await self._message_service.send_message(**kwargs)
    
    async def is_channel_empty(self, channel):
        return self._audio_service.is_channel_empty(channel)

    async def send_controls(self, force=False):
        return await self._message_service.send_controls(self)
        
    async def is_playing_sound(self):
        return self._audio_service.is_playing_sound()

    async def add_user_event(self, username, event, sound_name):
        return await self._user_event_service.add_user_event(username, event, sound_name)

    async def list_user_events(self, user, user_full_name, requesting_user=None):
        return await self._user_event_service.list_user_events(user_full_name, requesting_user)

    async def find_and_update_similar_sounds(self, *args, **kwargs):
        return await self._sound_service.find_and_update_similar_sounds(*args, **kwargs)

    async def delayed_list_selector_update(self, *args, **kwargs):
        return await self._sound_service.delayed_list_selector_update(*args, **kwargs)

    async def perform_backup(self, interaction):
        return await self._backup_service.perform_backup(interaction)


