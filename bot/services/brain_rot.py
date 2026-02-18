import asyncio
import random
import os
import discord
from bot.repositories import ActionRepository
from typing import Optional
from moviepy.editor import VideoFileClip

class BrainRotService:
    """
    Service for managing 'brain rot' functionalities.
    Sends video clips from Data folders to the chat.
    """
    
    def __init__(self, bot, audio_service, message_service):
        self.bot = bot
        self.audio_service = audio_service
        self.message_service = message_service
        self.action_repo = ActionRepository()
        self.lock = asyncio.Lock()
        self.cooldown_message: Optional[discord.Message] = None
        self.data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Data"))

    async def run_random(self, user, guild=None):
        """Run a random brain rot function."""
        if self.lock.locked():
            if self.cooldown_message:
                try:
                    await self.cooldown_message.delete()
                except:
                    pass
            
            bot_channel = self.message_service.get_bot_channel(guild)
            if bot_channel:
                self.cooldown_message = await self.message_service.send_message(
                    title="🧠 Brain Rot Active 🧠",
                    description="A brain rot function is already in progress. Please wait!",
                    delete_time=5
                )
            return

        async def run():
            async with self.lock:
                functions = [
                    self.subway_surfers,
                    self.slice_all,
                    self.family_guy
                ]
                chosen = random.choice(functions)
                try:
                    await chosen(user, guild)
                    guild_id = guild.id if guild else None
                    self.action_repo.insert(user.name if hasattr(user, 'name') else str(user), 
                                         f"brain_rot_{chosen.__name__}", "", guild_id=guild_id)
                except Exception as e:
                    print(f"[BrainRotService] Error in {chosen.__name__}: {e}")

        asyncio.create_task(run())

    async def subway_surfers(self, user=None, guild=None):
        """Send a random Subway Surfers video clip to chat."""
        await self._send_video_clip("SubwaySurfers", "Subway Surfers", user, guild)

    async def slice_all(self, user=None, guild=None):
        """Send a random Slice All video clip to chat."""
        await self._send_video_clip("SliceAll", "Slice All", user, guild)

    async def family_guy(self, user=None, guild=None):
        """Send a random Family Guy video clip to chat."""
        await self._send_video_clip("FamilyGuy", "Family Guy", user, guild)

    async def _send_video_clip(self, folder_name: str, display_name: str, user=None, guild=None):
        """Send a random video clip from the specified folder."""
        folder = os.path.join(self.data_dir, folder_name)
        if not os.path.exists(folder):
            print(f"[BrainRotService] Folder not found: {folder}")
            return
            
        files = [f for f in os.listdir(folder) if f.endswith(('.mp4', '.webm', '.mov'))]
        if not files:
            print(f"[BrainRotService] No video files in {folder}")
            return
            
        file = random.choice(files)
        file_path = os.path.join(folder, file)
        title_num = files.index(file) + 1
        
        bot_channel = self.message_service.get_bot_channel(guild)
        if not bot_channel:
            return
            
        # Send the video
        embed = discord.Embed(
            title=f"{display_name} clip {title_num} of {len(files)}",
            color=discord.Color.red()
        )
        
        message = await bot_channel.send(
            embed=embed,
            file=discord.File(file_path, f"{folder_name}/{file}")
        )
        
        # Re-send controls to keep them at the bottom
        if hasattr(self, 'message_service') and self.message_service._bot_behavior:
            await self.message_service.send_controls(self.message_service._bot_behavior, guild=guild)
        
        # Wait for video duration + buffer, then delete
        try:
            clip = VideoFileClip(file_path)
            duration = clip.duration
            clip.close()
            await asyncio.sleep(duration + 5)
        except:
            await asyncio.sleep(30)  # Fallback
            
        try:
            await message.delete()
        except:
            pass
        
        username = user.name if hasattr(user, 'name') else str(user) if user else "admin"
        self.action_repo.insert(username, folder_name.lower(), file, guild_id=guild.id if guild else None)
