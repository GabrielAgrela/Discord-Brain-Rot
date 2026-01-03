"""
Message service for Discord messaging operations.

This service encapsulates all message-related operations that were
previously scattered across BotBehavior.
"""

import discord
from typing import Optional, Any
import os


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
    
    @property
    def last_message(self) -> Optional[discord.Message]:
        """Get the last message sent by this service."""
        return self._last_message
