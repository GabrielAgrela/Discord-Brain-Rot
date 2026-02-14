import discord
from discord import SelectDefaultValue, SelectDefaultValueType
from discord.ui import View
from bot.database import Database

class UserEventSelectView(View):
    def __init__(self, bot_behavior, audio_file, guild_members=None, interaction_user_id=None, message_to_edit=None, interaction_user=None):
        """
        View for assigning user events to sounds.
        
        Pycord 2.7.0: Uses SelectDefaultValue to pre-select the interaction user,
        making self-assignment more intuitive (common use case).
        
        Args:
            interaction_user: The User object of who triggered the view (for pre-selection)
        """
        super().__init__(timeout=180)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.sound_name_no_ext = audio_file.split('/')[-1].replace('.mp3', '')
        self.interaction_user_id = interaction_user_id
        self.message_to_edit = message_to_edit 

        # Pre-select the interaction user for convenience (most common: self-assignment)
        # Pre-select "join" event type as default (most common use case)
        self.selected_event_type = "join"
        if interaction_user:
            self.selected_user_id = f"{interaction_user.name}#{interaction_user.discriminator}"
            self.selected_user = interaction_user
        else:
            self.selected_user_id = None
            self.selected_user = None

        from bot.ui.selects import EventTypeSelect, UserSelectComponent
        from bot.ui.buttons.events import ConfirmUserEventButton, CancelButton

        self.event_type_select = EventTypeSelect(bot_behavior)
        
        # Create user select with default value (Pycord 2.7.0 feature)
        default_values = []
        if interaction_user:
            default_values = [SelectDefaultValue(id=interaction_user.id, type=SelectDefaultValueType.user)]
        
        self.user_select = UserSelectComponent(bot_behavior, row=1, default_values=default_values)
        self.confirm_button = ConfirmUserEventButton(bot_behavior, audio_file)
        self.cancel_button = CancelButton()

        self.add_item(self.event_type_select)
        self.add_item(self.user_select)
        self.add_item(self.confirm_button)
        self.add_item(self.cancel_button)

    def _build_message_content(self) -> str:
        """Build the event-assignment message content from current selections."""
        base = f"Assigning event for sound: **{self.sound_name_no_ext}**\n"
        if self.selected_user_id and self.selected_event_type:
            is_set = Database().get_user_event_sound(self.selected_user_id, self.selected_event_type, self.sound_name_no_ext)
            action_text = "REMOVE" if is_set else "ADD"
            user_display = self.selected_user_id.split('#')[0]
            base += f"\n **{action_text}** this sound as a **{self.selected_event_type}** event for **{user_display}**."
        elif self.selected_user_id:
            user_display = self.selected_user_id.split('#')[0]
            base += f"User **{user_display}** is pre-selected. Select an event type to continue."
        return base

    async def get_initial_message_content(self):
        """Get initial message content for the event assignment view."""
        return self._build_message_content()

    async def update_display_message(self, interaction_from_select: discord.Interaction):
        """Update the assignment message to match the current toggle state."""
        new_content = self._build_message_content()
        for option in self.event_type_select.options:
            option.default = (self.selected_event_type is not None and option.value == self.selected_event_type)
        
        try:
            if not interaction_from_select.response.is_done():
                await interaction_from_select.response.defer()
            if self.message_to_edit:
                await self.message_to_edit.edit(content=new_content, view=self)
        except Exception as e:
            print(f"UserEventSelectView.update_display_message: Error editing message: {e}")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.interaction_user_id:
            await interaction.response.send_message("You cannot interact with this menu.", ephemeral=True)
            return False
        return True
    
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message_to_edit:
            try:
                await self.message_to_edit.edit(content=f"Event assignment for '{self.sound_name_no_ext}' timed out.", view=self)
            except:
                pass


class EventView(View):
    def __init__(self, bot_behavior, user_id, event, sounds):
        super().__init__(timeout=None)
        from bot.ui.buttons.events import DeleteEventButton
        for sound in sounds:
            self.add_item(DeleteEventButton(bot_behavior, user_id, event, sound))

class PaginatedEventView(View):
    def __init__(self, bot_behavior, events, user_id, event):
        super().__init__(timeout=None)
        self.bot_behavior = bot_behavior
        self.current_page = 0
        self.user_id = user_id
        self.event = event
        
        chunk_size = 20
        self.pages = [events[i:i + chunk_size] for i in range(0, len(events), chunk_size)]
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        
        from bot.ui.buttons.events import DeleteEventButton
        from bot.ui.buttons.navigation import EventPaginationButton
        
        self.add_item(EventPaginationButton("Previous", "⬅️", discord.ButtonStyle.primary, "previous", 0))
        self.add_item(EventPaginationButton("Next", "➡️", discord.ButtonStyle.primary, "next", 0))
        
        if not self.pages:
            return
            
        current_events = self.pages[self.current_page]
        for i, event in enumerate(current_events):
            row = (i // 5) + 1
            self.add_item(DeleteEventButton(
                bot_behavior=self.bot_behavior,
                user_id=self.user_id,
                event=self.event,
                sound=event[2] # event[2] is sound name (as originally in components.py)
            ))
