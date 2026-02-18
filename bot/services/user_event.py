import discord
from bot.repositories import EventRepository, ActionRepository
from bot.database import Database  # Keep for get_sounds_by_similarity
from typing import Optional
import sqlite3

class UserEventService:
    """
    Service for managing user-specific join/leave event sounds.
    """
    
    def __init__(self, bot, audio_service, message_service):
        self.bot = bot
        self.audio_service = audio_service
        self.message_service = message_service
        
        # Repositories
        self.event_repo = EventRepository()
        self.action_repo = ActionRepository()
        
        # Keep Database for complex similarity query
        self.db = Database()
        
        self.behavior = None

    def set_behavior(self, behavior):
        """Set the behavior reference."""
        self.behavior = behavior

    async def add_user_event(self, username: str, event: str, sound_name: str, guild_id: Optional[int] = None) -> bool:
        """Add a join/leave event sound for a user."""
        try:
            from bot.repositories import SoundRepository
            
            # Try exact match first
            exact_match = SoundRepository().get_by_filename(sound_name, guild_id=guild_id)
            if exact_match:
                most_similar_sound = exact_match.filename.replace('.mp3', '')
            else:
                # Fall back to fuzzy search
                results = self.db.get_sounds_by_similarity(sound_name, 1, guild_id=guild_id)
                if not results:
                    return False
                
                # Get the most similar sound
                # results[0] is (sound_data, score)
                sound_data = results[0][0]
                if isinstance(sound_data, (sqlite3.Row, dict)):
                    most_similar_sound = sound_data['Filename'].replace('.mp3', '')
                else:
                    most_similar_sound = sound_data[2].replace('.mp3', '')
            
            # Add the event sound to the database
            success = self.event_repo.toggle(username, event, most_similar_sound, guild_id=guild_id)
            
            # Log the action
            if success:
                self.action_repo.insert(username, f"add_{event}_sound", most_similar_sound, guild_id=guild_id)
            
            return success
        except Exception as e:
            print(f"[UserEventService] Error adding user event: {e}")
            return False

    async def list_user_events(self, user_full_name: str, requesting_user: Optional[str] = None, guild_id: Optional[int] = None):
        """List all join/leave events for a user with delete buttons."""
        # Get user's events from database
        join_events = self.event_repo.get_user_events(user_full_name, "join", guild_id=guild_id)
        leave_events = self.event_repo.get_user_events(user_full_name, "leave", guild_id=guild_id)
        user_name = user_full_name.split('#')[0]
        
        if not join_events and not leave_events:
            return False
        
        # Log the action
        action_user = requesting_user if requesting_user else user_full_name
        self.action_repo.insert(
            action_user,
            "list_events",
            f"{len(join_events) + len(leave_events)} events for {user_full_name}",
            guild_id=guild_id,
        )
        
        from bot.ui import PaginatedEventView
        
        # Extract sound names from tuples (row[2] is sound)
        join_event_tuples = [(None, None, s[2]) for s in join_events]
        leave_event_tuples = [(None, None, s[2]) for s in leave_events]
        
        # Send a message for each event type with all its events
        if join_events:
            total_events = len(join_events)
            current_page_end = min(20, total_events)
            
            description = "**Current sounds:**\n"
            description += "\n".join([f"• {event[2]}" for event in join_events[:current_page_end]])
            description += f"\nShowing sounds 1-{current_page_end} of {total_events}"
            
            await self.message_service.send_message(
                title=f"🎵 {user_name}'s Join Event Sounds (Page 1/{(total_events + 19) // 20})",
                description=description,
                view=PaginatedEventView(self.behavior, join_event_tuples, user_full_name, "join"),
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
                view=PaginatedEventView(self.behavior, leave_event_tuples, user_full_name, "leave"),
                delete_time=60
            )
        
        return True
