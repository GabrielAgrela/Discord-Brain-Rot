import discord
from discord.ui import Button
import asyncio
import random
from bot.database import Database

class SubwaySurfersButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.subway_surfers())

class SliceAllButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.slice_all())

class FamilyGuyButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.family_guy())

class BrainRotButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()

        if self.bot_behavior.brain_rot_lock.locked():
            if self.bot_behavior.brain_rot_cooldown_message:
                try:
                    await self.bot_behavior.brain_rot_cooldown_message.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass 
            self.bot_behavior.brain_rot_cooldown_message = await self.bot_behavior.send_message(
                title="🧠 Brain Rot Active 🧠",
                description="A brain rot function is already in progress. Please wait!",
                delete_time=5, 
                send_controls=False 
            )
            return

        async def run_brain_rot():
            try:
                async with self.bot_behavior.brain_rot_lock:
                    brain_rot_functions = [
                        self.bot_behavior.subway_surfers,
                        self.bot_behavior.slice_all,
                        self.bot_behavior.family_guy
                    ]
                    chosen_function = random.choice(brain_rot_functions)
                    
                    try:
                        await chosen_function(interaction.user)
                        Database().insert_action(interaction.user.name, f"brain_rot_{chosen_function.__name__}", "")
                    except Exception as e:
                        print(f"Error during brain rot function '{chosen_function.__name__}': {e}")
            finally:
                if self.bot_behavior.brain_rot_cooldown_message:
                    try:
                        await self.bot_behavior.brain_rot_cooldown_message.delete()
                    except (discord.NotFound, discord.Forbidden):
                        pass 
                    self.bot_behavior.brain_rot_cooldown_message = None

        asyncio.create_task(run_brain_rot())

class StatsButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.display_top_users(interaction.user, number_users=20, number_sounds=5, days=700, by="plays"))

class PlayRandomButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.play_random_sound(interaction.user.name))

class PlayRandomFavoriteButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.play_random_favorite_sound(interaction.user.name))

class ListFavoritesButton(Button):
    current_favorites_message = None

    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        
        if ListFavoritesButton.current_favorites_message:
            try:
                await ListFavoritesButton.current_favorites_message.delete()
            except:
                pass 
        
        favorites = Database().get_sounds(num_sounds=1000, favorite=True)
        Database().insert_action(interaction.user.name, "list_favorites", len(favorites))
        
        if len(favorites) > 0:
            from bot.ui.views.favorites import PaginatedFavoritesView
            view = PaginatedFavoritesView(self.bot_behavior, favorites, interaction.user.name)
            message = await self.bot_behavior.send_message(
                title=f"⭐ All Favorite Sounds (Page 1/{len(view.pages)}) ⭐",
                description=f"All favorite sounds in the database\nShowing sounds 1-{min(20, len(favorites))} of {len(favorites)}",
                view=view,
                delete_time=300
            )
            ListFavoritesButton.current_favorites_message = message
        else:
            await interaction.followup.send("No favorite sounds found.", ephemeral=True)

class ListUserFavoritesButton(Button):
    current_user_messages = {}

    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        
        if interaction.user.name in ListUserFavoritesButton.current_user_messages:
            try:
                await ListUserFavoritesButton.current_user_messages[interaction.user.name].delete()
            except:
                pass 
        
        favorites = Database().get_sounds(num_sounds=1000, favorite_by_user=True, user=interaction.user.name)
        Database().insert_action(interaction.user.name, "list_user_favorites", len(favorites))
        
        if len(favorites) > 0:
            from bot.ui.views.favorites import PaginatedFavoritesView
            view = PaginatedFavoritesView(self.bot_behavior, favorites, interaction.user.name)
            message = await self.bot_behavior.send_message(
                title=f"🤩 {interaction.user.name}'s Favorites (Page 1/{len(view.pages)}) 🤩",
                description=f"Showing sounds 1-{min(20, len(favorites))} of {len(favorites)}",
                view=view,
                delete_time=300
            )
            ListUserFavoritesButton.current_user_messages[interaction.user.name] = message
        else:
            await interaction.followup.send("No favorite sounds found.", ephemeral=True)
