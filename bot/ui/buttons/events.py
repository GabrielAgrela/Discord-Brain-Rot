import discord
from discord.ui import Button
from bot.database import Database

class ConfirmUserEventButton(Button):
    def __init__(self, bot_behavior, audio_file, **kwargs):
        super().__init__(label="Confirm", style=discord.ButtonStyle.success, custom_id="confirm_user_event", **kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        selected_event_type = getattr(self.view, 'selected_event_type', None)
        selected_user_id_for_db = getattr(self.view, 'selected_user_id', None) 

        if not selected_event_type:
            if self.view.message_to_edit:
                await self.view.message_to_edit.edit(content="Please select an event type.", view=self.view)
            return
        if not selected_user_id_for_db:
            if self.view.message_to_edit:
                await self.view.message_to_edit.edit(content="Please select a user.", view=self.view)
            return

        acting_user_full_name = f"{interaction.user.name}#{interaction.user.discriminator}"
        is_admin = self.bot_behavior.is_admin_or_mod(interaction.user)
        is_self_assign = (acting_user_full_name == selected_user_id_for_db)

        if not (is_self_assign or is_admin):
            user_display_name_target = selected_user_id_for_db.split('#')[0]
            if self.view.message_to_edit:
                await self.view.message_to_edit.edit(
                    content=(
                        f"You do not have permission to assign an event for {user_display_name_target}. "
                        "Admins can assign to any user, and users can assign to themselves."
                    ),
                    view=None
                )
            return

        sound_name = self.audio_file.split('/')[-1].replace('.mp3', '')
        try:
            Database().toggle_user_event_sound(selected_user_id_for_db, selected_event_type, sound_name)
            if self.view.message_to_edit:
                await self.view.message_to_edit.edit(content=self.view._build_message_content(), view=self.view)
        except Exception as e:
            print(f"Error toggling event sound: {e}")
            user_display_name = selected_user_id_for_db.split('#')[0] if selected_user_id_for_db else "user"
            if self.view.message_to_edit:
                await self.view.message_to_edit.edit(
                    content=f"Failed to process event assignment for '{sound_name}' to {user_display_name}.",
                    view=self.view
                )

class CancelButton(Button):
    def __init__(self, **kwargs):
        super().__init__(label="Cancel", style=discord.ButtonStyle.grey, custom_id="cancel_user_event", **kwargs)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if self.view.message_to_edit:
            await self.view.message_to_edit.edit(content="Event assignment cancelled.", view=None)

class DeleteEventButton(Button):
    def __init__(self, bot_behavior, user_id, event, sound, **kwargs):
        super().__init__(label=sound, style=discord.ButtonStyle.danger, **kwargs)
        self.bot_behavior = bot_behavior
        self.user_id = user_id
        self.event = event
        self.sound = sound

    async def callback(self, interaction):
        await interaction.response.defer()
        
        if interaction.user.name == self.user_id.split('#')[0]:
            if Database().remove_user_event_sound(self.user_id, self.event, self.sound):
                Database().insert_action(interaction.user.name, f"delete_{self.event}_event", self.sound)
                remaining_events = Database().get_user_events(self.user_id, self.event)
                
                if not remaining_events:
                    await interaction.message.delete()
                else:
                    from bot.ui.views.events import PaginatedEventView
                    view = PaginatedEventView(self.bot_behavior, remaining_events, self.user_id, self.event)
                    total_events = len(remaining_events)
                    current_page_end = min(20, total_events)
                    
                    description = "**Current sounds:**\n"
                    description += "\n".join([f"• {event[2]}" for event in remaining_events[:current_page_end]])
                    description += f"\nShowing sounds 1-{current_page_end} of {total_events}"
                    
                    embed = interaction.message.embeds[0]
                    embed.description = description
                    await interaction.message.edit(embed=embed, view=view)
                
                await interaction.followup.send(f"Event {self.event} with sound {self.sound} deleted!", ephemeral=True)
            else:
                await interaction.followup.send("Failed to delete the event!", ephemeral=True)
        else:
            channel = self.bot_behavior._audio_service.get_user_voice_channel(interaction.guild, interaction.user.name)
            if channel:
                similar_sounds = Database().get_sounds_by_similarity(self.sound, 1)
                await self.bot_behavior._audio_service.play_audio(channel, similar_sounds[0][1], interaction.user.name)
                Database().insert_action(interaction.user.name, f"play_{self.event}_event_sound", self.sound)
            else:
                await interaction.followup.send("You need to be in a voice channel to play sounds! 😭", ephemeral=True)
