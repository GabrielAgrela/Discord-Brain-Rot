import discord
from discord.ui import View

class PaginatedSoundListView(View):
    def __init__(self, bot_behavior, list_id, list_name, sounds, owner):
        super().__init__(timeout=None)
        self.bot_behavior = bot_behavior
        self.list_id = list_id
        self.list_name = list_name
        self.current_page = 0
        self.owner = owner 
        
        chunk_size = 4
        self.pages = [sounds[i:i + chunk_size] for i in range(0, len(sounds), chunk_size)]
        self.update_buttons()
    
    def update_buttons(self):
        self.clear_items()
        
        from bot.ui.buttons.navigation import SoundListPaginationButton
        from bot.ui.buttons.list_buttons import DeleteListButton, SoundListItemButton, RemoveFromListButton

        self.add_item(SoundListPaginationButton("Previous", "⬅️", discord.ButtonStyle.primary, "previous", 0))
        self.add_item(SoundListPaginationButton("Next", "➡️", discord.ButtonStyle.primary, "next", 0))
        
        if self.current_page == 0:
            self.add_item(DeleteListButton(
                bot_behavior=self.bot_behavior,
                list_id=self.list_id,
                list_name=self.list_name,
                label="Delete List",
                style=discord.ButtonStyle.danger,
                row=0
            ))
        
        if not self.pages:
            return
            
        current_sounds = self.pages[self.current_page]
        for i, sound in enumerate(current_sounds):
            # Sound is a full database tuple: (id, originalfilename, Filename, favorite, blacklist, ...)
            filename = sound[2]  # Filename column
            original_name = sound[1]  # originalfilename column
            display_name = original_name if original_name else filename
            if len(display_name) > 80:
                display_name = display_name[:77] + "..."
            
            row = i + 1 
            self.add_item(SoundListItemButton(
                bot_behavior=self.bot_behavior,
                sound_filename=filename,
                display_name=display_name,
                row=row
            ))
            
            self.add_item(RemoveFromListButton(
                bot_behavior=self.bot_behavior,
                list_id=self.list_id,
                list_name=self.list_name,
                sound_filename=filename,
                label="❌",
                style=discord.ButtonStyle.primary,
                row=row
            ))

