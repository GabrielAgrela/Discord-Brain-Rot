import discord
from discord.ui import View

class PaginatedFavoritesView(View):
    def __init__(self, bot_behavior, favorites, owner):
        super().__init__(timeout=None)
        self.bot_behavior = bot_behavior
        self.current_page = 0
        self.owner = owner 
        
        chunk_size = 20
        self.pages = [favorites[i:i + chunk_size] for i in range(0, len(favorites), chunk_size)]
        self.update_page_buttons()
    
    def update_buttons(self):
        self.clear_items()
        
        from bot.ui.buttons.navigation import PaginationButton
        self.add_item(PaginationButton("Previous", "⬅️", discord.ButtonStyle.primary, "previous", 0))
        self.add_item(PaginationButton("Next", "➡️", discord.ButtonStyle.primary, "next", 0))
        
        self.update_page_buttons()
    
    def update_page_buttons(self):
        if not self.pages:
            return
            
        from bot.ui.buttons.sounds import PlaySoundButton
        current_sounds = self.pages[self.current_page]
        for i, sound in enumerate(current_sounds):
            row = (i // 5) + 1  
            self.add_item(PlaySoundButton(
                self.bot_behavior,
                sound[1],
                style=discord.ButtonStyle.primary,
                label=sound[2].split('/')[-1].replace('.mp3', ''),
                row=row
            ))
