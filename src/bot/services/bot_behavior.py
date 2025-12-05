import os
import discord
import asyncio
import re
import uuid
import aiohttp
import time
import datetime
from mutagen.mp3 import MP3
from src.common.config import Config
from src.common.database import Database

class BotBehavior:
    def __init__(self, bot):
        self.bot = bot
        self.ffmpeg_path = Config.FFMPEG_PATH
        self.db = Database()
        self.last_channel = {}
        self.playback_done = asyncio.Event()
        self.playback_done.set()
        self.dwdir = Config.SOUNDS_DIR
        self.volume = 1.0
        self.last_played_time = None
        self.mute_until = None
        self.upload_lock = asyncio.Lock()

        # We need to port ManualSoundDownloader eventually or use it
        # For now, let's assume we can implement simple downloaders here or import later

    async def get_bot_channel(self):
        # Assuming only one guild for now or first guild
        if not self.bot.guilds:
            return None
        return discord.utils.get(self.bot.guilds[0].text_channels, name='bot')

    def is_admin_or_mod(self, member: discord.Member) -> bool:
        allowed_roles = {"DEVELOPER", "MODERATOR"}
        if not hasattr(member, 'roles'): return False
        for role in member.roles:
            if role.name in allowed_roles:
                return True
        return False

    async def send_message(self, title="", description="", footer=None, thumbnail=None, view=None, send_controls=True, file=None, delete_time=0, bot_channel=None):
        channel = await self.get_bot_channel() if not bot_channel else discord.utils.get(self.bot.guilds[0].text_channels, name=bot_channel)
        if not channel:
            print("Bot channel not found")
            return None

        embed = discord.Embed(title=title, description=description, color=discord.Color.red()) # Default color
        if thumbnail: embed.set_thumbnail(url=thumbnail)
        if footer: embed.set_footer(text=footer)

        # Legacy link
        embed.add_field(name="", value="[🥵 gabrielagrela.com 🥵](https://gabrielagrela.com)")

        kwargs = {'view': view, 'embed': None if description == "" and title == "" else embed, 'file': file}
        if delete_time > 0:
            kwargs['delete_after'] = delete_time

        try:
            message = await channel.send(**kwargs)
            # if send_controls: await self.send_controls() # Implement controls later
            return message
        except Exception as e:
            print(f"Error sending message: {e}")
            return None

    def get_largest_voice_channel(self, guild):
        largest_channel = None
        largest_size = 0
        for channel in guild.voice_channels:
            if len(channel.members) > largest_size:
                largest_channel = channel
                largest_size = len(channel.members)
        return largest_channel

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
            return self.bot.voice_clients[0] if self.bot.voice_clients else None

    async def play_audio(self, channel, audio_file, user, effects=None):
        if self.mute_until and datetime.datetime.now() < self.mute_until:
            return

        voice_client = await self.ensure_voice_connected(channel)
        if not voice_client:
            return

        # Path resolution
        audio_file_path = os.path.join(Config.SOUNDS_DIR, audio_file)
        if not os.path.exists(audio_file_path):
             # Try lookup in DB
             sound_info = self.db.get_sound(audio_file, True)
             if sound_info:
                 audio_file_path = os.path.join(Config.SOUNDS_DIR, sound_info['Filename'])

             if not os.path.exists(audio_file_path):
                 print(f"File not found: {audio_file_path}")
                 return

        if voice_client.is_playing():
            voice_client.stop()
            # Wait for stop?
            await asyncio.sleep(0.5)

        ffmpeg_options = '-af "volume=1.0"'
        if effects:
             filters = [f'volume={effects.get("volume", 1.0):.4f}']
             speed = effects.get("speed", 1.0)
             if speed != 1.0:
                  filters.append(f'atempo={speed:.4f}')
             if effects.get("reverse", False):
                  filters.append('areverse')
             ffmpeg_options = '-af "' + ",".join(filters) + '"'

        def after_playing(error):
            if error:
                print(f"Playback error: {error}")
            self.bot.loop.call_soon_threadsafe(self.playback_done.set)

        try:
            audio_source = discord.FFmpegPCMAudio(
                audio_file_path,
                executable=self.ffmpeg_path,
                options=ffmpeg_options
            )
            audio_source = discord.PCMVolumeTransformer(audio_source)
            voice_client.play(audio_source, after=after_playing)
            self.playback_done.clear()

            # Log action
            sound_id = None
            sound_info = self.db.get_sound(os.path.basename(audio_file_path))
            if sound_info:
                sound_id = sound_info['id']

            if sound_id:
                self.db.insert_action(str(user), "play_sound", sound_id)

            # Send Now Playing message (Simplified)
            await self.send_message(title=f"🔊 Playing: {os.path.basename(audio_file_path)}", footer=f"Requested by {user}")

        except Exception as e:
            print(f"Error playing audio: {e}")
            self.playback_done.set()

    async def play_request(self, message, user, effects=None):
        # Logic to find sound
        sounds = self.db.get_sounds_by_similarity(message, 1)
        if not sounds:
            await self.send_message(title="Error", description=f"Sound '{message}' not found.")
            return

        sound_filename = sounds[0]
        # Find user channel
        member = user
        if not isinstance(member, discord.Member):
             # Try to find member in guild
             guild = self.bot.guilds[0]
             member = guild.get_member(user.id)

        if member and member.voice:
            await self.play_audio(member.voice.channel, sound_filename, user, effects)
        else:
             # Play in largest channel?
             guild = self.bot.guilds[0]
             channel = self.get_largest_voice_channel(guild)
             if channel:
                 await self.play_audio(channel, sound_filename, user, effects)

    # ... Add more methods as needed (upload, tts, etc.) ...
