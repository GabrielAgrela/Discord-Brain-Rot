import discord
from discord.ui import View, Button
from datetime import datetime


class StatsPaginationButton(Button):
    """Button for navigating between user stats pages."""
    
    def __init__(self, direction: str, **kwargs):
        emoji = "⬅️" if direction == "previous" else "➡️"
        label = "Previous" if direction == "previous" else "Next"
        super().__init__(label=label, emoji=emoji, style=discord.ButtonStyle.primary, row=0)
        self.direction = direction

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view: PaginatedStatsView = self.view
        
        if self.direction == "previous":
            if view.current_index == 0:
                view.current_index = len(view.users_data) - 1
            else:
                view.current_index -= 1
        else:  # next
            if view.current_index == len(view.users_data) - 1:
                view.current_index = 0
            else:
                view.current_index += 1
        
        # Update the embed with new user data
        embed = view.create_user_embed()
        await interaction.message.edit(embed=embed, view=view)


class PaginatedStatsView(View):
    """View for displaying paginated user stats with navigation buttons."""
    
    def __init__(self, bot, users_data: list, number_sounds: int = 5, days: int = 700, guild_id: int | None = None):
        """
        Initialize the paginated stats view.
        
        Args:
            bot: The Discord bot instance
            users_data: List of tuples (username, total_plays)
            number_sounds: Number of top sounds to show per user
            days: Number of days to calculate stats from
        """
        super().__init__(timeout=None)
        self.bot = bot
        self.users_data = users_data
        self.number_sounds = number_sounds
        self.days = days
        self.guild_id = guild_id
        self.current_index = 0
        
        # Import here to avoid circular imports
        from bot.repositories import ActionRepository
        self.action_repo = ActionRepository()
        
        # Add navigation buttons
        self.add_item(StatsPaginationButton("previous"))
        self.add_item(StatsPaginationButton("next"))
    
    def create_user_embed(self) -> discord.Embed:
        """Create an embed for the current user."""
        if not self.users_data:
            return discord.Embed(
                title="📊 No Stats Available",
                description="No user statistics found.",
                color=discord.Color.gray()
            )
        
        username, total_plays = self.users_data[self.current_index]
        rank = self.current_index + 1
        
        embed = discord.Embed(
            title=f"🔊 **#{rank} {username.upper()}**",
            description=f"🎵 **Total Sounds Played: {total_plays}**\n\n👤 User {rank} of {len(self.users_data)}",
            color=discord.Color.green()
        )
        
        # Try to find user for avatar
        discord_user = discord.utils.get(self.bot.get_all_members(), name=username)
        if discord_user and discord_user.avatar:
            embed.set_thumbnail(url=discord_user.avatar.url)
        elif username == "syzoo":
            embed.set_thumbnail(url="https://media.npr.org/assets/img/2017/09/12/macaca_nigra_self-portrait-3e0070aa19a7fe36e802253048411a38f14a79f8-s800-c85.webp")
        elif discord_user:
            embed.set_thumbnail(url=discord_user.default_avatar.url)
        
        # Get top sounds for this user
        user_top_sounds, _ = self.action_repo.get_top_sounds(
            self.days,
            self.number_sounds,
            username,
            guild_id=self.guild_id,
        )
        for sound in user_top_sounds:
            embed.add_field(name=f"🎵 **{sound[0]}**", value=f"Played **{sound[1]}** times", inline=False)
        
        embed.timestamp = datetime.utcnow()
        
        return embed
