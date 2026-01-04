import discord
from bot.database import Database
from typing import Optional

class UserEventService:
    """
    Service for managing user-specific join/leave event sounds.
    """
    
    def __init__(self, bot, audio_service, message_service):
        self.bot = bot
        self.audio_service = audio_service
        self.message_service = message_service
        self.db = Database()

    async def add_user_event(self, username: str, event: str, sound_name: str) -> bool:
        """Add a join/leave event sound for a user."""
        try:
            # Find the most similar sound in the database
            results = self.db.get_sounds_by_similarity(sound_name, 1)
            if not results:
                return False
            
            # Get the most similar sound
            # results[0] is (sound_data, score), sound_data[2] is filename
            most_similar_sound = results[0][0][2].replace('.mp3', '')
            
            # Add the event sound to the database
            success = self.db.toggle_user_event_sound(username, event, most_similar_sound)
            
            # Log the action
            if success:
                self.db.insert_action(username, f"add_{event}_sound", most_similar_sound)
            
            return success
        except Exception as e:
            print(f"[UserEventService] Error adding user event: {e}")
            return False

    async def list_user_events(self, user_full_name: str, requesting_user: Optional[str] = None):
        """List all join/leave events for a user with delete buttons."""
        # Get user's events from database
        join_events = self.db.get_user_events(user_full_name, "join")
        leave_events = self.db.get_user_events(user_full_name, "leave")
        user_name = user_full_name.split('#')[0]
        
        if not join_events and not leave_events:
            return False
        
        # Log the action
        action_user = requesting_user if requesting_user else user_full_name
        self.db.insert_action(action_user, "list_events", f"{len(join_events) + len(leave_events)} events for {user_full_name}")
        
        from bot.ui import PaginatedEventView
        
        # Send a message for each event type with all its events
        if join_events:
            total_events = len(join_events)
            current_page_end = min(20, total_events)
            
            description = "**Current sounds:**\n"
            description += "\n".join([f"• {event[2]}" for event in join_events[:current_page_end]])
            description += f"\nShowing sounds 1-{current_page_end} of {total_events}"
            
            # We'll pass None for behavior, will need to fix this dependency later
            await self.message_service.send_message(
                title=f"🎵 {user_name}'s Join Event Sounds (Page 1/{(total_events + 19) // 20})",
                description=description,
                view=PaginatedEventView(None, join_events, user_full_name, "join"),
                delete_time=60
            )
        
        if leave_events:
            total_events = len(leave_events)
            current_page_end = min(20, total_events)
            
            description = "**Current sounds:**\n"
            description += "\n".join([f"• {event[2]}" for event in leave_events[:current_page_end]])
            description += f"\nShowing sounds 1-{current_page_end} of {total_events}"
            
            await self.message_service.send_message(
                title=f"🎵 {user_name}'s Leave Event Sounds (Page 1/{(total_events + 19) // 20})",
                description=description,
                view=PaginatedEventView(None, leave_events, user_full_name, "leave"),
                delete_time=60
            )
        
        return True
