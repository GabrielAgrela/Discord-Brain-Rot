"""
Message service for Discord messaging operations.

This service encapsulates all message-related operations that were
previously scattered across BotBehavior.
"""

import discord
import io
from typing import Optional, Any, Literal
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
        self._controls_messages_by_guild: dict[int, discord.Message] = {}
        self._bot_behavior = None  # Set later to avoid circular dependency
        self._controls_lock = asyncio.Lock()
        from bot.services.guild_settings import GuildSettingsService
        self.guild_settings_service = GuildSettingsService()

    def set_behavior(self, behavior):
        """Set bot behavior reference for re-sending controls."""
        self._bot_behavior = behavior

    def _build_default_inline_controls_view(
        self,
        style: discord.ButtonStyle = discord.ButtonStyle.primary,
    ) -> Optional[discord.ui.View]:
        """Build the default inline controls view for generic image messages."""
        if not self._bot_behavior:
            return None

        from bot.ui.views.controls import InlineControlsMessageView
        return InlineControlsMessageView(self._bot_behavior, style=style)

    @staticmethod
    def _hex_to_rgb(color_hex: Optional[str]) -> Optional[tuple[int, int, int]]:
        """Convert '#RRGGBB' or 'RRGGBB' into an RGB tuple."""
        if not color_hex:
            return None

        clean = color_hex.strip().lstrip("#")
        if len(clean) != 6:
            return None

        try:
            value = int(clean, 16)
        except ValueError:
            return None

        return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)

    @staticmethod
    def _button_style_from_rgb(rgb: Optional[tuple[int, int, int]]) -> discord.ButtonStyle:
        """Map a message color to the closest Discord button style."""
        if rgb is None:
            return discord.ButtonStyle.primary

        red, green, blue = rgb
        spread = max(red, green, blue) - min(red, green, blue)

        if spread < 25:
            return discord.ButtonStyle.secondary
        if red >= green + 30 and red >= blue + 30:
            return discord.ButtonStyle.danger
        if green >= red + 30 and green >= blue + 30:
            return discord.ButtonStyle.success
        if blue >= red + 20 and blue >= green + 20:
            return discord.ButtonStyle.primary
        return discord.ButtonStyle.secondary

    def _resolve_default_inline_controls_style(
        self,
        message_format: Literal["embed", "image"],
        color: Optional[discord.Color],
        image_border_color: Optional[str],
    ) -> discord.ButtonStyle:
        """Choose a default inline controls button style for the outgoing message."""
        if message_format == "image":
            return self._button_style_from_rgb(self._hex_to_rgb(image_border_color))

        embed_color = color or self.color
        value = getattr(embed_color, "value", None)
        if value is None:
            return discord.ButtonStyle.primary
        rgb = ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)
        return self._button_style_from_rgb(rgb)
    
    def get_bot_channel(self, guild: Optional[discord.Guild] = None) -> Optional[discord.TextChannel]:
        """
        Get the bot's primary text channel.
        
        Args:
            guild: Specific guild to get channel from. If None, searches all guilds.
            
        Returns:
            Text channel or None if not found
        """
        if guild:
            settings = self.guild_settings_service.get(guild.id)
            configured_channel_id = settings.bot_text_channel_id
            if configured_channel_id:
                try:
                    configured_channel = guild.get_channel(int(configured_channel_id))
                    if isinstance(configured_channel, discord.TextChannel):
                        return configured_channel
                except (TypeError, ValueError):
                    pass
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
        guild: Optional[discord.Guild] = None,
        message_format: Literal["embed", "image"] = "embed",
        image_requester: str = "Ventura",
        image_show_footer: bool = True,
        image_show_sound_icon: bool = True,
        image_border_color: Optional[str] = None,
    ) -> Optional[discord.Message]:
        """
        Send a message to the bot channel as an embed or image card.
        
        Args:
            title: Embed title
            description: Embed description
            thumbnail: URL for thumbnail image
            color: Embed color (uses default if None)
            view: Discord UI view to attach
            delete_time: Auto-delete after N seconds
            channel: Specific channel (uses bot channel if None)
            guild: Guild context for bot-channel resolution when channel is not provided
            message_format: "embed" (default) or "image"
            image_requester: Requester label used for image cards
            image_show_footer: Whether image card should include footer row
            image_show_sound_icon: Whether image card should include the leading sound icon
            image_border_color: Optional hex color (e.g. "#ED4245") for image card border
            
        Returns:
            The sent message or None on failure
        """
        if channel is None:
            channel = self.get_bot_channel(guild)
        
        if channel is None:
            print("[MessageService] No bot channel found")
            return None

        try:
            kwargs = {}
            effective_view = view
            if effective_view is None:
                style = self._resolve_default_inline_controls_style(
                    message_format=message_format,
                    color=color,
                    image_border_color=image_border_color,
                )
                effective_view = self._build_default_inline_controls_view(style=style)

            if effective_view:
                kwargs["view"] = effective_view
            if delete_time:
                kwargs["delete_after"] = delete_time

            if message_format == "image":
                image_bytes = await self._generate_message_image(
                    title=title,
                    description=description,
                    thumbnail=thumbnail,
                    requester=image_requester,
                    show_footer=image_show_footer,
                    show_sound_icon=image_show_sound_icon,
                    border_color=image_border_color,
                )
                if image_bytes:
                    kwargs["file"] = discord.File(io.BytesIO(image_bytes), filename="message_card.png")
                    message = await channel.send(**kwargs)
                    self._last_message = message
                    return message
                print("[MessageService] Image generation failed, falling back to embed")

            embed = discord.Embed(
                title=title,
                description=description,
                color=color or self.color,
            )
            if thumbnail:
                embed.set_thumbnail(url=thumbnail)

            kwargs["embed"] = embed
            message = await channel.send(**kwargs)
            self._last_message = message
            return message

        except Exception as e:
            print(f"[MessageService] Error sending message: {e}")
            return None

    async def _generate_message_image(
        self,
        title: str,
        description: str,
        thumbnail: Optional[str],
        requester: str,
        show_footer: bool,
        show_sound_icon: bool,
        border_color: Optional[str] = None,
    ) -> Optional[bytes]:
        """Build an image card for generic notifications."""
        if not self._bot_behavior:
            return None

        audio_service = getattr(self._bot_behavior, "_audio_service", None)
        image_generator = getattr(audio_service, "image_generator", None)
        if not image_generator:
            return None

        text = (title or description or "Notification").strip()
        event_data = description.strip() if description and title else None
        return await image_generator.generate_sound_card(
            sound_name=text,
            requester=requester,
            requester_avatar_url=thumbnail,
            event_data=event_data,
            show_footer=show_footer,
            show_sound_icon=show_sound_icon,
            accent_color=border_color,
        )
    
    async def send_error(
        self,
        message: str,
        channel: Optional[discord.TextChannel] = None,
        guild: Optional[discord.Guild] = None,
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
            guild=guild,
        )
    
    async def send_success(
        self,
        message: str,
        channel: Optional[discord.TextChannel] = None,
        guild: Optional[discord.Guild] = None,
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
            guild=guild,
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
                guild_id = guild.id if guild else getattr(channel.guild, "id", None)
                existing_controls = self._controls_messages_by_guild.get(guild_id) if guild_id else None
                if existing_controls and existing_controls.channel.id == channel.id:
                    try:
                        await existing_controls.delete()
                    except:
                        pass
                
                self._controls_message = await channel.send(view=ControlsView(bot_behavior), delete_after=delete_after)
                if guild_id:
                    self._controls_messages_by_guild[guild_id] = self._controls_message
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

    async def delete_controls_message(self, delete_all=True, guild: Optional[discord.Guild] = None):
        """Find and delete control messages in the bot channel history."""
        channel = self.get_bot_channel(guild)
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

    async def disable_controls_message(self, disable_all: bool = True, guild: Optional[discord.Guild] = None):
        """Find and disable control messages in the bot channel history."""
        channel = self.get_bot_channel(guild)
        if not channel:
            return

        try:
            if disable_all:
                async for message in channel.history(limit=100):
                    if message.components and not message.embeds:
                        try:
                            first_label = message.components[0].children[0].label or ""
                        except Exception:
                            first_label = ""

                        if "Play Random" in first_label:
                            await self._disable_message_components(message)
            else:
                if self._controls_message:
                    await self._disable_message_components(self._controls_message)
                    self._controls_message = None
        except Exception as e:
            print(f"[MessageService] Error disabling control messages: {e}")

    async def clean_buttons(self, count=5, guild: Optional[discord.Guild] = None):
        """Disable components/buttons from recent messages."""
        channel = self.get_bot_channel(guild)
        if not channel:
            return
            
        try:
            async for message in channel.history(limit=count):
                if message.components:
                    await self._disable_message_components(message)
        except Exception as e:
            print(f"[MessageService] Error cleaning buttons: {e}")

    async def _disable_message_components(self, message: discord.Message) -> bool:
        """Disable all interactive items in a message view."""
        try:
            view = discord.ui.View.from_message(message)
            updated = False
            for item in view.children:
                if hasattr(item, "disabled") and not item.disabled:
                    item.disabled = True
                    updated = True

            if not updated:
                return True

            await message.edit(view=view)
            return True
        except Exception as e:
            print(f"[MessageService] Error disabling message components: {e}")
            return False
