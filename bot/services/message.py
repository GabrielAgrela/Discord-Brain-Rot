"""
Message service for Discord messaging operations.

This service encapsulates all message-related operations that were
previously scattered across BotBehavior.
"""

import discord
from typing import Optional, Any
import os
import asyncio


class MessageService:
    """
    Service for sending Discord messages and embeds.
    
    This service follows the Single Responsibility Principle by
    handling only message-related operations.
    
    Attributes:
        bot: The Discord bot instance
        bot_channel_name: Name of the bot's primary channel
        color: Default embed color
    """
    
    def __init__(self, bot: discord.Bot, bot_channel_name: str = "bot"):
        """
        Initialize the message service.
        
        Args:
            bot: Discord bot instance
            bot_channel_name: Name of channel to send messages to
        """
        self.bot = bot
        self.bot_channel_name = bot_channel_name
        self.color = discord.Color.dark_grey()
        self._last_message: Optional[discord.Message] = None
        self._controls_message: Optional[discord.Message] = None
        self._bot_behavior = None  # Set later to avoid circular dependency
        self._controls_lock = asyncio.Lock()

    def set_behavior(self, behavior):
        """Set bot behavior reference for re-sending controls."""
        self._bot_behavior = behavior
    
    def get_bot_channel(self, guild: Optional[discord.Guild] = None) -> Optional[discord.TextChannel]:
        """
        Get the bot's primary text channel.
        
        Args:
            guild: Specific guild to get channel from. If None, searches all guilds.
            
        Returns:
            Text channel or None if not found
        """
        if guild:
            return discord.utils.get(guild.text_channels, name=self.bot_channel_name)
        
        # Search across all guilds
        for g in self.bot.guilds:
            channel = discord.utils.get(g.text_channels, name=self.bot_channel_name)
            if channel:
                return channel
        return None
    
    async def send_message(
        self,
        title: str = "",
        description: str = "",
        thumbnail: Optional[str] = None,
        color: Optional[discord.Color] = None,
        view: Optional[discord.ui.View] = None,
        delete_time: Optional[int] = None,
        channel: Optional[discord.TextChannel] = None,
    ) -> Optional[discord.Message]:
        """
        Send an embed message to the bot channel.
        
        Args:
            title: Embed title
            description: Embed description
            thumbnail: URL for thumbnail image
            color: Embed color (uses default if None)
            view: Discord UI view to attach
            delete_time: Auto-delete after N seconds
            channel: Specific channel (uses bot channel if None)
            
        Returns:
            The sent message or None on failure
        """
        if channel is None:
            channel = self.get_bot_channel()
        
        if channel is None:
            print("[MessageService] No bot channel found")
            return None
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=color or self.color,
        )
        
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        
        try:
            kwargs = {"embed": embed}
            if view:
                kwargs["view"] = view
            if delete_time:
                kwargs["delete_after"] = delete_time
            
            message = await channel.send(**kwargs)
            self._last_message = message
            
            return message
            
        except Exception as e:
            print(f"[MessageService] Error sending message: {e}")
            return None
    
    async def send_error(
        self,
        message: str,
        channel: Optional[discord.TextChannel] = None,
        delete_time: int = 10,
    ) -> Optional[discord.Message]:
        """
        Send an error message with red color.
        
        Args:
            message: Error message text
            channel: Target channel
            delete_time: Auto-delete after N seconds
            
        Returns:
            The sent message
        """
        return await self.send_message(
            title="❌ Error",
            description=message,
            color=discord.Color.red(),
            delete_time=delete_time,
            channel=channel,
        )
    
    async def send_success(
        self,
        message: str,
        channel: Optional[discord.TextChannel] = None,
        delete_time: int = 10,
    ) -> Optional[discord.Message]:
        """
        Send a success message with green color.
        
        Args:
            message: Success message text
            channel: Target channel
            delete_time: Auto-delete after N seconds
            
        Returns:
            The sent message
        """
        return await self.send_message(
            title="✅ Success",
            description=message,
            color=discord.Color.green(),
            delete_time=delete_time,
            channel=channel,
        )
    
    async def delete_last_message(self) -> bool:
        """
        Delete the last message sent by this service.
        
        Returns:
            True if deleted successfully
        """
        if self._last_message:
            try:
                await self._last_message.delete()
                self._last_message = None
                return True
            except discord.NotFound:
                self._last_message = None
                return True  # Already deleted
            except Exception as e:
                print(f"[MessageService] Error deleting message: {e}")
                return False
        return False
    
    async def delete_messages(
        self,
        channel: discord.TextChannel,
        count: int = 1,
        bot_only: bool = True,
    ) -> int:
        """
        Delete recent messages from a channel.
        
        Args:
            channel: Channel to delete from
            count: Number of messages to delete
            bot_only: Only delete messages from this bot
            
        Returns:
            Number of messages deleted
        """
        deleted = 0
        try:
            async for message in channel.history(limit=count * 2):
                if bot_only and message.author != self.bot.user:
                    continue
                try:
                    await message.delete()
                    deleted += 1
                    if deleted >= count:
                        break
                except discord.NotFound:
                    continue
        except Exception as e:
            print(f"[MessageService] Error bulk deleting: {e}")
        
        return deleted
    
    async def update_message(
        self,
        message: discord.Message,
        title: Optional[str] = None,
        description: Optional[str] = None,
        view: Optional[discord.ui.View] = None,
    ) -> bool:
        """
        Update an existing message's embed.
        
        Args:
            message: Message to update
            title: New title (None = keep existing)
            description: New description (None = keep existing)
            view: New view (None = keep existing)
            
        Returns:
            True if updated successfully
        """
        try:
            embed = message.embeds[0] if message.embeds else discord.Embed()
            
            if title is not None:
                embed.title = title
            if description is not None:
                embed.description = description
            
            kwargs = {"embed": embed}
            if view is not None:
                kwargs["view"] = view
            
            await message.edit(**kwargs)
            return True
            
        except Exception as e:
            print(f"[MessageService] Error updating message: {e}")
            return False
    
    async def send_controls(self, bot_behavior, guild: Optional[discord.Guild] = None, delete_after: Optional[int] = None) -> bool:
        """Send the main bot controls view."""
        from bot.ui.views.controls import ControlsView
        channel = self.get_bot_channel(guild)
        if not channel:
            print(f"[MessageService] No bot channel found for controls in guild: {guild.name if guild else 'None'}")
            return False
            
        try:
            async with self._controls_lock:
                # We only track the controls message per-instance, which is a bit limiting
                # for multi-guild, but better than nothing for now.
                if self._controls_message and self._controls_message.channel.id == channel.id:
                    try:
                        await self._controls_message.delete()
                    except:
                        pass
                
                self._controls_message = await channel.send(view=ControlsView(bot_behavior), delete_after=delete_after)
                return True
        except Exception as e:
            print(f"[MessageService] Error sending controls: {e}")
            return False

    async def delete_controls(self):
        """Delete the current controls message."""
        """Delete the current controls message."""
        async with self._controls_lock:
            if self._controls_message:
                try:
                    await self._controls_message.delete()
                    self._controls_message = None
                except:
                    pass

    @property
    def last_message(self) -> Optional[discord.Message]:
        """Get the last message sent by this service."""
        return self._last_message

    @property
    def controls_message(self) -> Optional[discord.Message]:
        """Get the current controls message."""
        return self._controls_message

    async def delete_controls_message(self, delete_all=True):
        """Find and delete control messages in the bot channel history."""
        channel = self.get_bot_channel()
        if not channel:
            return
            
        try:
            if delete_all:
                async for message in channel.history(limit=100):
                    if message.components and not message.embeds:
                        try:
                            # Discord.py components structure
                            first_label = message.components[0].children[0].label or ""
                        except:
                            first_label = ""
                        
                        if "Play Random" in first_label:
                            await message.delete()
            else:
                # Just find the current one if not already tracked
                if self._controls_message:
                    await self._controls_message.delete()
                    self._controls_message = None
        except Exception as e:
            print(f"[MessageService] Error deleting control messages: {e}")

    async def clean_buttons(self, count=5):
        """Remove components/buttons from recent messages."""
        channel = self.get_bot_channel()
        if not channel:
            return
            
        try:
            async for message in channel.history(limit=count):
                if message.components:
                    is_sound_msg = message.embeds or (message.attachments and any(a.filename.endswith('.png') for a in message.attachments))
                    if is_sound_msg:
                        await message.edit(view=None)
                    else:
                        await message.delete()
        except Exception as e:
            print(f"[MessageService] Error cleaning buttons: {e}")
