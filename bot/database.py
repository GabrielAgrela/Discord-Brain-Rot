"""
Database module - Slimmed down after Repository Pattern refactoring.

This module now only contains:
- Singleton connection management
- Database creation/schema
- Core insert methods (used by downloaders)
- Fuzzy similarity search (complex logic kept here)
- get_sound (used by downloaders)

All other CRUD operations have been moved to specialized repositories:
- SoundRepository: get_random_sounds, get_sounds, update_sound, get_sound_by_name
- ActionRepository: insert_action (delegated here), get_top_users, get_top_sounds
- ListRepository: all sound list operations
- EventRepository: user event sounds
- StatsRepository: year stats, download dates
"""

import sqlite3
import os
import datetime
import time
from fuzzywuzzy import fuzz


class Database:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Database, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, behavior=None):
        if self._initialized:
            return
        self._initialized = True
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.db_path = os.path.join(script_dir, "..", "database.db")
        # Allow usage from background threads with reasonable timeout
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5.0)
        
        # Retry enabling WAL mode
        for attempt in range(3):
            try:
                self.conn.execute("PRAGMA journal_mode=WAL;")
                break
            except sqlite3.OperationalError as e:
                if attempt < 2:
                    print(f"[Database] Warning: Could not set journal_mode=WAL (attempt {attempt+1}): {e}. Retrying...")
                    time.sleep(1)
                else:
                    print(f"[Database] Warning: Could not set journal_mode=WAL after 3 attempts: {e}")
        
        self.cursor = self.conn.cursor()
        self.behavior = behavior
        
        # Set row_factory so repositories can use dict-style access
        self.conn.row_factory = sqlite3.Row
        
        # Share connection with repositories for consistency
        from bot.repositories.base import BaseRepository
        BaseRepository.set_shared_connection(self.conn, self.db_path)


    @staticmethod
    def create_database():
        try:
            # Get the current directory of the script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(script_dir, "..", "database.db")
            # Create a connection to the SQLite database
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Create actions table
            create_actions_table = '''
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            '''
            
            # Create sounds table
            create_sounds_table = '''
            CREATE TABLE IF NOT EXISTS sounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                originalfilename TEXT NOT NULL,
                Filename TEXT NOT NULL,
                favorite BOOLEAN NOT NULL CHECK (favorite IN (0, 1)),
                blacklist BOOLEAN NOT NULL CHECK (blacklist IN (0, 1)),
                slap BOOLEAN NOT NULL CHECK (slap IN (0, 1)) DEFAULT 0
            );
            '''

            # Create users table
            create_users_table = '''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT NOT NULL,
                event TEXT NOT NULL,
                sound TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            '''
            
            # Create voice_activity table
            create_voice_activity_table = '''
            CREATE TABLE IF NOT EXISTS voice_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                join_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                leave_time DATETIME
            );
            '''

            # Create sound_lists table
            create_sound_lists_table = '''
            CREATE TABLE IF NOT EXISTS sound_lists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                list_name TEXT NOT NULL,
                creator TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            '''

            # Create sound_list_items table
            create_list_items_table = '''
            CREATE TABLE IF NOT EXISTS sound_list_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                list_id INTEGER NOT NULL,
                sound_filename TEXT NOT NULL,
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (list_id) REFERENCES sound_lists (id) ON DELETE CASCADE
            );
            '''

            # Execute table creation
            cursor.execute(create_actions_table)
            cursor.execute(create_sounds_table)
            cursor.execute(create_users_table)
            cursor.execute(create_voice_activity_table)
            cursor.execute(create_sound_lists_table)
            cursor.execute(create_list_items_table)

            # Commit the changes
            conn.commit()
            print("Database created successfully")
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
        finally:
            if conn:
                conn.close()
                print("Connection closed")

    # ===== Core insert methods (used by downloaders) =====
    
    def insert_action(self, username, action, target):
        username = username.split("#")[0]
        try:
            self.cursor.execute("INSERT INTO actions (username, action, target) VALUES (?, ?, ?);", (username, action, target))
            self.conn.commit()
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")

    def insert_sound(self, originalfilename, filename, favorite=0, date=datetime.datetime.now()):
        try:
            self.cursor.execute("INSERT INTO sounds (originalfilename, Filename, favorite, blacklist, timestamp) VALUES (?, ?, ?, 0, ?);", (originalfilename, filename, favorite, date))
            self.conn.commit()
            print("Sound inserted successfully")
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
    
    def insert_user(self, event, sound):
        try:
            self.cursor.execute("INSERT INTO users (event, sound) VALUES (?, ?);", (event, sound))
            self.conn.commit()
            print("User inserted successfully")
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")

    # ===== Fuzzy similarity search (complex logic kept here) =====
    
    def normalize_text(self, text):
        substitutions = {
            '0': 'o',
            '1': 'i',
            '3': 'e',
            '4': 'a',
            '5': 's',
            '7': 't',
            '@': 'a',
            '$': 's',
            '!': 'i',
        }
        for key, value in substitutions.items():
            text = text.replace(key, value)
        return text.lower()

    def get_sounds_by_similarity(self, req_sound, num_results=5, sleep_interval=0.0):
        """Return the most similar sounds. Optionally sleep between iterations
        to reduce CPU spikes that can cause audio stutter."""
        normalized_req = self.normalize_text(req_sound)
        try:
            # Use a separate connection for this potentially heavy query
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM sounds")
            all_sounds = cursor.fetchall()
            if not all_sounds:
                print("No sounds available for similarity scoring.")
                return []
            scored_matches = []
            for sound in all_sounds:
                filename = sound[2]  # Filename is at index 2
                normalized_filename = self.normalize_text(filename)

                # Calculate multiple fuzzy matching scores
                token_set_score = fuzz.token_set_ratio(normalized_req, normalized_filename)
                partial_ratio_score = fuzz.partial_ratio(normalized_req, normalized_filename)
                token_sort_score = fuzz.token_sort_ratio(normalized_req, normalized_filename)

                # Combine scores with weighted average
                combined_score = (0.5 * token_set_score) + (0.3 * partial_ratio_score) + (0.2 * token_sort_score)

                scored_matches.append((combined_score, sound))

                if sleep_interval:
                    time.sleep(sleep_interval)
            
            # Sort by combined score descending
            scored_matches.sort(key=lambda x: x[0], reverse=True)
            
            # Select top N matches
            top_matches = scored_matches[:num_results]
            
            print("Sounds found successfully")
            return [(match[1], match[0]) for match in top_matches]  # (sound data, score) pairs
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
            return []
        finally:
            conn.close()

    def get_sounds_by_similarity_optimized(self, req_sound, num_results=5):
        """Optimized similarity search using SQL pre-filtering."""
        normalized_req = self.normalize_text(req_sound)
        try:
            # Split the search term into words
            search_words = normalized_req.replace('-', ' ').split()
            
            # Build dynamic SQL query
            like_conditions = []
            params = []

            # Handle special word combinations
            i = 0
            while i < len(search_words):
                current_word = search_words[i]
                next_word = search_words[i + 1] if i + 1 < len(search_words) else None

                # Handle "he is" / "hes" variations
                if current_word == "he" and next_word == "is":
                    like_conditions.extend([
                        "LOWER(Filename) LIKE ?",
                        "LOWER(Filename) LIKE ?"
                    ])
                    params.extend([f"%he%is%", f"%hes%"])
                    i += 2
                    continue
                elif current_word == "hes":
                    like_conditions.extend([
                        "LOWER(Filename) LIKE ?",
                        "LOWER(Filename) LIKE ?"
                    ])
                    params.extend([f"%he%is%", f"%hes%"])
                elif current_word == "is":
                    like_conditions.extend([
                        "LOWER(Filename) LIKE ?",
                        "LOWER(Filename) LIKE ?"
                    ])
                    params.extend([f"%is%", f"%'s%"])
                else:
                    like_conditions.append("LOWER(Filename) LIKE ?")
                    params.append(f"%{current_word}%")

                i += 1

            # Add full phrase match
            like_conditions.append("LOWER(Filename) LIKE ?")
            full_phrase = normalized_req.replace(' ', '%')
            params.append(f"%{full_phrase}%")
            
            query = f"""
                SELECT * FROM sounds 
                WHERE ({" OR ".join(like_conditions)})
                LIMIT 150
            """
            
            self.cursor.execute(query, tuple(params))
            potential_matches = self.cursor.fetchall()

            if not potential_matches:
                return []

            # Score matches using multiple fuzzy ratios
            scored_matches = []
            for sound in potential_matches:
                filename = sound[2]
                normalized_filename = self.normalize_text(filename)
                
                token_set_score = fuzz.token_set_ratio(normalized_req, normalized_filename)
                partial_ratio_score = fuzz.partial_ratio(normalized_req, normalized_filename)
                token_sort_score = fuzz.token_sort_ratio(normalized_req, normalized_filename)
                
                # Bonus for matches containing all search words
                all_words_present = all(word in normalized_filename for word in search_words)
                word_presence_bonus = 20 if all_words_present else 0
                
                combined_score = (0.5 * token_set_score) + (0.3 * partial_ratio_score) + (0.2 * token_sort_score) + word_presence_bonus
                scored_matches.append((combined_score, sound))
            
            # Sort and return top matches
            scored_matches.sort(key=lambda x: x[0], reverse=True)
            return [(match[1], match[0]) for match in scored_matches[:num_results]]
            
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
            return []

    # ===== Sound lookup (used by downloaders) =====
    
    def get_sound(self, sound_filename, original_filename=False):
        try:
            if original_filename:
                self.cursor.execute("SELECT * FROM sounds WHERE originalfilename = ?;", (sound_filename,))
            else:
                self.cursor.execute("SELECT * FROM sounds WHERE Filename = ?;", (sound_filename,))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")

    # ===== Backwards-compatible delegators (for UI layer) =====
    # These methods delegate to repositories for backwards compatibility
    
    def get_random_sounds(self, favorite=None, num_sounds=1):
        """Delegate to SoundRepository for backwards compatibility."""
        from bot.repositories import SoundRepository
        return SoundRepository().get_random_sounds(favorite=favorite, num_sounds=num_sounds)
    
    def get_sounds(self, favorite=None, slap=None, num_sounds=25, sort="DESC", favorite_by_user=False, user=None):
        """Delegate to SoundRepository for backwards compatibility."""
        from bot.repositories import SoundRepository
        return SoundRepository().get_sounds(favorite=favorite, slap=slap, num_sounds=num_sounds, 
                                            sort=sort, favorite_by_user=favorite_by_user, user=user)
    
    def get_sound_by_name(self, sound_name):
        """Delegate to SoundRepository for backwards compatibility."""
        from bot.repositories import SoundRepository
        return SoundRepository().get_sound_by_name(sound_name)
    
    async def update_sound(self, filename, new_filename=None, favorite=None, slap=None):
        """Delegate to SoundRepository for backwards compatibility."""
        from bot.repositories import SoundRepository
        return SoundRepository().update_sound(filename, new_filename=new_filename, favorite=favorite, slap=slap)
    
    def get_user_events(self, user, event):
        """Delegate to EventRepository for backwards compatibility."""
        from bot.repositories import EventRepository
        return EventRepository().get_user_events(user, event)
    
    def get_user_event_sound(self, user_id, event, sound):
        """Delegate to EventRepository for backwards compatibility."""
        from bot.repositories import EventRepository
        # Check if event exists
        events = EventRepository().get_user_events(user_id, event)
        return sound in events
    
    def toggle_user_event_sound(self, user_id, event, sound):
        """Delegate to EventRepository for backwards compatibility."""
        from bot.repositories import EventRepository
        return EventRepository().toggle(user_id, event, sound)
    
    def remove_user_event_sound(self, user_id, event, sound):
        """Delegate to EventRepository for backwards compatibility."""
        from bot.repositories import EventRepository
        return EventRepository().remove(user_id, event, sound)
    
    def get_sound_lists(self, creator=None):
        """Delegate to ListRepository for backwards compatibility."""
        from bot.repositories import ListRepository
        return ListRepository().get_all(creator=creator)
    
    def get_sound_list(self, list_id):
        """Delegate to ListRepository for backwards compatibility."""
        from bot.repositories import ListRepository
        return ListRepository().get_by_id(list_id)
    
    def get_sounds_in_list(self, list_id):
        """Delegate to ListRepository for backwards compatibility."""
        from bot.repositories import ListRepository
        return ListRepository().get_sounds_in_list(list_id)
    
    def get_list_by_name(self, list_name, creator=None):
        """Delegate to ListRepository for backwards compatibility."""
        from bot.repositories import ListRepository
        return ListRepository().get_by_name(list_name, creator)
    
    def create_sound_list(self, list_name, creator):
        """Delegate to ListRepository for backwards compatibility."""
        from bot.repositories import ListRepository
        return ListRepository().create(list_name, creator)
    
    def add_sound_to_list(self, list_id, sound_filename):
        """Delegate to ListRepository for backwards compatibility."""
        from bot.repositories import ListRepository
        return ListRepository().add_sound(list_id, sound_filename)
    
    def remove_sound_from_list(self, list_id, sound_filename):
        """Delegate to ListRepository for backwards compatibility."""
        from bot.repositories import ListRepository
        return ListRepository().remove_sound(list_id, sound_filename)
    
    def delete_sound_list(self, list_id, creator=None):
        """Delegate to ListRepository for backwards compatibility."""
        from bot.repositories import ListRepository
        return ListRepository().delete(list_id)
    
    def get_lists_containing_sound(self, sound_filename):
        """Delegate to ListRepository for backwards compatibility."""
        from bot.repositories import ListRepository
        return ListRepository().get_lists_containing_sound(sound_filename)
