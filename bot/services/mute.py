"""
Mute service for bot muting functionality.

Encapsulates all mute-related operations that were previously in BotBehavior.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional
import discord


class MuteService:
    """
    Service for managing bot mute state.
    
    The mute feature temporarily prevents the bot from playing sounds,
    useful when users want quiet time without leaving voice channels.
    
    Attributes:
        is_muted: Whether the bot is currently muted
        mute_until: Datetime when mute expires
        muted_by: Username who activated mute
    """
    
    DEFAULT_DURATION = 1800  # 30 minutes
    
    def __init__(self, message_service=None):
        """
        Initialize the mute service.
        
        Args:
            message_service: Optional MessageService for notifications
        """
        self._is_muted = False
        self._mute_until: Optional[datetime] = None
        self._muted_by: Optional[str] = None
        self._message_service = message_service
        self._unmute_task: Optional[asyncio.Task] = None
    
    @property
    def is_muted(self) -> bool:
        """Check if the bot is currently muted."""
        if self._is_muted and self._mute_until:
            if datetime.now() >= self._mute_until:
                # Mute has expired
                self._is_muted = False
                self._mute_until = None
                self._muted_by = None
        return self._is_muted
    
    @property
    def mute_until(self) -> Optional[datetime]:
        """Get the mute expiration time."""
        return self._mute_until
    
    @property
    def muted_by(self) -> Optional[str]:
        """Get the username who activated mute."""
        return self._muted_by
    
    def get_remaining_seconds(self) -> int:
        """
        Get remaining mute time in seconds.
        
        Returns:
            Seconds remaining, or 0 if not muted
        """
        if not self.is_muted or not self._mute_until:
            return 0
        
        remaining = (self._mute_until - datetime.now()).total_seconds()
        return max(0, int(remaining))
    
    def get_remaining_formatted(self) -> str:
        """
        Get remaining mute time as a formatted string.
        
        Returns:
            String like "5m 30s" or "Not muted"
        """
        seconds = self.get_remaining_seconds()
        if seconds == 0:
            return "Not muted"
        
        minutes = seconds // 60
        secs = seconds % 60
        
        if minutes > 0:
            return f"{minutes}m {secs}s"
        return f"{secs}s"
    
    async def activate(
        self, 
        duration_seconds: int = DEFAULT_DURATION,
        requested_by: Optional[str] = None,
    ) -> bool:
        """
        Activate mute for a duration.
        
        Args:
            duration_seconds: How long to mute (default 30 minutes)
            requested_by: Username who requested the mute
            
        Returns:
            True if mute was activated
        """
        # Cancel any existing unmute task
        if self._unmute_task and not self._unmute_task.done():
            self._unmute_task.cancel()
        
        self._is_muted = True
        self._mute_until = datetime.now() + timedelta(seconds=duration_seconds)
        self._muted_by = requested_by
        
        # Schedule automatic unmute
        self._unmute_task = asyncio.create_task(
            self._auto_unmute(duration_seconds)
        )
        
        # Send notification if message service available
        if self._message_service:
            await self._message_service.send_message(
                title="🔇 Bot Muted",
                description=f"Muted for {self.get_remaining_formatted()}"
                           + (f"\nRequested by: {requested_by}" if requested_by else ""),
                color=discord.Color.orange(),
                delete_time=10,
            )
        
        return True
    
    async def deactivate(self, requested_by: Optional[str] = None) -> bool:
        """
        Deactivate mute immediately.
        
        Args:
            requested_by: Username who requested unmute
            
        Returns:
            True if unmute was successful
        """
        was_muted = self._is_muted
        
        # Cancel auto-unmute task
        if self._unmute_task and not self._unmute_task.done():
            self._unmute_task.cancel()
        
        self._is_muted = False
        self._mute_until = None
        self._muted_by = None
        
        # Send notification if was actually muted
        if was_muted and self._message_service:
            await self._message_service.send_message(
                title="🔊 Bot Unmuted",
                description="The bot can play sounds again!"
                           + (f"\nUnmuted by: {requested_by}" if requested_by else ""),
                color=discord.Color.green(),
                delete_time=10,
            )
        
        return was_muted
    
    async def _auto_unmute(self, duration_seconds: int):
        """Background task to automatically unmute after duration."""
        try:
            await asyncio.sleep(duration_seconds)
            await self.deactivate()
        except asyncio.CancelledError:
            pass  # Task was cancelled by manual unmute
    
    def should_block_playback(self) -> bool:
        """
        Check if playback should be blocked.
        
        This is the main check that audio playback should use.
        
        Returns:
            True if playback should be blocked
        """
        return self.is_muted
