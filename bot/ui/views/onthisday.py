"""
UI View for On This Day feature - shows sounds popular in the past.
"""

import discord
from discord.ui import View, Button
from datetime import datetime, timedelta
from typing import List, Tuple


class OnThisDayButton(Button):
    """Button to play a sound from the On This Day view."""
    
    def __init__(self, sound_filename: str, play_count: int, row: int = 0):
        # Remove .mp3 extension for display
        display_name = sound_filename.replace('.mp3', '')
        super().__init__(
            label=f"{display_name} ({play_count}x)",
            style=discord.ButtonStyle.secondary,
            row=row
        )
        self.sound_filename = sound_filename
    
    async def callback(self, interaction: discord.Interaction):
        """Play the sound when button is clicked."""
        await interaction.response.defer()
        
        view: OnThisDayView = self.view
        if view.audio_service and view.sound_service:
            # Get user's voice channel
            channel = None
            if interaction.user.voice:
                channel = interaction.user.voice.channel
            
            if channel:
                sound = view.sound_service.get_sound_by_name(self.sound_filename)
                if sound:
                    await view.audio_service.play_audio(
                        channel=channel,
                        audio_file=sound[2],  # filename
                        user=interaction.user.name,
                        show_suggestions=True
                    )
            else:
                await interaction.followup.send(
                    "You need to be in a voice channel!", ephemeral=True
                )


class OnThisDayNavigationButton(Button):
    """Navigation button for pagination."""
    
    def __init__(self, direction: str):
        emoji = "⬅️" if direction == "previous" else "➡️"
        label = "Previous" if direction == "previous" else "Next"
        super().__init__(label=label, emoji=emoji, style=discord.ButtonStyle.primary, row=2)
        self.direction = direction
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view: OnThisDayView = self.view
        
        if self.direction == "previous":
            view.current_page = max(0, view.current_page - 1)
        else:
            max_page = (len(view.sounds) - 1) // view.sounds_per_page
            view.current_page = min(max_page, view.current_page + 1)
        
        embed = view.create_embed()
        view.update_buttons()
        await interaction.message.edit(embed=embed, view=view)


class OnThisDayView(View):
    """View for displaying sounds from the past with playable buttons."""
    
    def __init__(
        self, 
        sounds: List[Tuple[str, int]], 
        months_ago: int,
        audio_service=None,
        sound_service=None
    ):
        """
        Initialize the On This Day view.
        
        Args:
            sounds: List of (filename, play_count) tuples
            months_ago: How many months ago (for display)
            audio_service: AudioService for playing sounds
            sound_service: SoundService for sound lookups
        """
        super().__init__(timeout=300)  # 5 minute timeout
        self.sounds = sounds
        self.months_ago = months_ago
        self.audio_service = audio_service
        self.sound_service = sound_service
        self.current_page = 0
        self.sounds_per_page = 5
        
        self.update_buttons()
    
    def update_buttons(self):
        """Update the view with buttons for current page."""
        self.clear_items()
        
        start_idx = self.current_page * self.sounds_per_page
        end_idx = start_idx + self.sounds_per_page
        page_sounds = self.sounds[start_idx:end_idx]
        
        # Add sound buttons (rows 0-1)
        for i, (filename, count) in enumerate(page_sounds):
            row = 0 if i < 3 else 1
            self.add_item(OnThisDayButton(filename, count, row=row))
        
        # Add navigation buttons if needed (row 2)
        if len(self.sounds) > self.sounds_per_page:
            self.add_item(OnThisDayNavigationButton("previous"))
            self.add_item(OnThisDayNavigationButton("next"))
    
    def create_embed(self) -> discord.Embed:
        """Create the embed for the current page."""
        target_date = datetime.now() - timedelta(days=self.months_ago * 30)
        
        if self.months_ago == 12:
            period_text = "1 Year Ago"
        elif self.months_ago == 1:
            period_text = "1 Month Ago"
        else:
            period_text = f"{self.months_ago} Months Ago"
        
        embed = discord.Embed(
            title=f"📅 On This Day - {period_text}",
            description=f"**{target_date.strftime('%B %d, %Y')}**\n\nThese sounds were popular around this time!",
            color=discord.Color.gold()
        )
        
        if not self.sounds:
            embed.add_field(
                name="No Data",
                value="No sounds were played around this date 😢",
                inline=False
            )
        else:
            start_idx = self.current_page * self.sounds_per_page
            end_idx = start_idx + self.sounds_per_page
            page_sounds = self.sounds[start_idx:end_idx]
            
            sounds_list = []
            for i, (filename, count) in enumerate(page_sounds, start=start_idx + 1):
                display_name = filename.replace('.mp3', '')
                sounds_list.append(f"**{i}.** {display_name} - *{count} plays*")
            
            embed.add_field(
                name="🔊 Top Sounds",
                value="\n".join(sounds_list),
                inline=False
            )
            
            # Add pagination info
            total_pages = (len(self.sounds) - 1) // self.sounds_per_page + 1
            embed.set_footer(text=f"Page {self.current_page + 1}/{total_pages} • Click a button to play")
        
        embed.timestamp = datetime.utcnow()
        return embed
