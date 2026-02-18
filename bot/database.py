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
import config
from rapidfuzz import fuzz


class Database:
    _instance = None
    _sound_cache = None  # In-memory cache: list of (id, original_filename, filename, favorite, blacklist, ...)
    _sound_cache_normalized = None  # Pre-normalized filenames for faster matching
    _cache_timestamp = None  # Track when cache was last refreshed

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Database, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, behavior=None):
        if self._initialized:
            return
        self._initialized = True
        self.db_path = str(config.DATABASE_PATH)
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

        # Ensure runtime schema is compatible with the current code.
        self._run_schema_migrations()
        
        # Share connection with repositories for consistency
        from bot.repositories.base import BaseRepository
        BaseRepository.set_shared_connection(self.conn, self.db_path)
        
        # Initialize sound cache on first run
        self._load_sound_cache()

    def _load_sound_cache(self):
        """Load all sounds into memory for fast similarity search."""
        try:
            # Use the existing connection if possible to see uncommitted changes in the same session
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM sounds")
            Database._sound_cache = cursor.fetchall()
            
            # Pre-normalize all filenames for faster matching
            Database._sound_cache_normalized = [
                (dict(sound) if isinstance(sound, sqlite3.Row) else sound, 
                 self.normalize_text(sound['Filename'] if isinstance(sound, sqlite3.Row) else sound[2]))
                for sound in Database._sound_cache
            ]
            Database._cache_timestamp = time.time()
            print(f"[Database] Sound cache loaded: {len(Database._sound_cache)} sounds")
        except sqlite3.Error as e:
            print(f"[Database] Error loading sound cache: {e}")
            Database._sound_cache = []
            Database._sound_cache_normalized = []

    def refresh_sound_cache(self):
        """Manually refresh the sound cache (call after adding/removing sounds)."""
        self._load_sound_cache()

    def invalidate_sound_cache(self):
        """Invalidate the cache so it reloads on next similarity search."""
        Database._sound_cache = None
        Database._sound_cache_normalized = None
        Database._cache_timestamp = None

    def _table_exists(self, table_name: str) -> bool:
        """Return True if a SQLite table exists."""
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _column_exists(self, table_name: str, column_name: str) -> bool:
        """Return True if a column exists on a table."""
        try:
            rows = self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        except sqlite3.Error:
            return False
        for row in rows:
            # Row format: cid, name, type, notnull, dflt_value, pk
            if str(row[1]) == column_name:
                return True
        return False

    def _ensure_column(self, table_name: str, column_def: str, column_name: str):
        """Add a column if it does not already exist."""
        if not self._table_exists(table_name):
            return
        if self._column_exists(table_name, column_name):
            return
        self.conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_def}")
        self.conn.commit()

    def _run_schema_migrations(self):
        """Apply lightweight schema migrations for multi-guild support."""
        try:
            # Core guild settings table for per-guild channels + feature flags.
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id TEXT PRIMARY KEY,
                    bot_text_channel_id TEXT,
                    default_voice_channel_id TEXT,
                    autojoin_enabled INTEGER NOT NULL DEFAULT 0 CHECK (autojoin_enabled IN (0,1)),
                    periodic_enabled INTEGER NOT NULL DEFAULT 0 CHECK (periodic_enabled IN (0,1)),
                    stt_enabled INTEGER NOT NULL DEFAULT 0 CHECK (stt_enabled IN (0,1)),
                    audio_policy TEXT NOT NULL DEFAULT 'low_latency',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # Tenant scoping columns (nullable => global/legacy row).
            self._ensure_column("sounds", "guild_id TEXT", "guild_id")
            self._ensure_column("actions", "guild_id TEXT", "guild_id")
            self._ensure_column("users", "guild_id TEXT", "guild_id")
            self._ensure_column("voice_activity", "guild_id TEXT", "guild_id")
            self._ensure_column("sound_lists", "guild_id TEXT", "guild_id")

            # Helpful indexes for scoped queries.
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_guild_id ON actions(guild_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_sounds_guild_id ON sounds(guild_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_users_guild_event ON users(guild_id, id, event)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_voice_activity_guild ON voice_activity(guild_id, join_time)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_sound_lists_guild ON sound_lists(guild_id, list_name)")
            self.conn.commit()
        except sqlite3.Error as e:
            print(f"[Database] Schema migration warning: {e}")

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
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                guild_id TEXT
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
                slap BOOLEAN NOT NULL CHECK (slap IN (0, 1)) DEFAULT 0,
                is_elevenlabs BOOLEAN NOT NULL DEFAULT 0 CHECK (is_elevenlabs IN (0, 1)),
                guild_id TEXT
            );
            '''

            # Create users table
            create_users_table = '''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT NOT NULL,
                event TEXT NOT NULL,
                sound TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                guild_id TEXT
            );
            '''
            
            # Create voice_activity table
            create_voice_activity_table = '''
            CREATE TABLE IF NOT EXISTS voice_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                join_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                leave_time DATETIME,
                guild_id TEXT
            );
            '''

            # Create sound_lists table
            create_sound_lists_table = '''
            CREATE TABLE IF NOT EXISTS sound_lists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                list_name TEXT NOT NULL,
                creator TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                guild_id TEXT
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

            # Create keywords table
            create_keywords_table = '''
            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL UNIQUE,
                action_type TEXT NOT NULL,
                action_value TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            '''

            # Execute table creation
            cursor.execute(create_actions_table)
            cursor.execute(create_sounds_table)
            cursor.execute(create_users_table)
            cursor.execute(create_voice_activity_table)
            cursor.execute(create_sound_lists_table)
            cursor.execute(create_list_items_table)
            cursor.execute(create_keywords_table)

            # Create ai_commentary_memory table
            create_ai_memory_table = '''
            CREATE TABLE IF NOT EXISTS ai_commentary_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                transcription TEXT NOT NULL,
                response TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            '''
            cursor.execute(create_ai_memory_table)

            create_guild_settings_table = '''
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id TEXT PRIMARY KEY,
                bot_text_channel_id TEXT,
                default_voice_channel_id TEXT,
                autojoin_enabled INTEGER NOT NULL DEFAULT 0 CHECK (autojoin_enabled IN (0,1)),
                periodic_enabled INTEGER NOT NULL DEFAULT 0 CHECK (periodic_enabled IN (0,1)),
                stt_enabled INTEGER NOT NULL DEFAULT 0 CHECK (stt_enabled IN (0,1)),
                audio_policy TEXT NOT NULL DEFAULT 'low_latency',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            '''
            cursor.execute(create_guild_settings_table)

            # Populate default keywords if empty
            cursor.execute("SELECT COUNT(*) FROM keywords")
            if cursor.fetchone()[0] == 0:
                defaults = [
                    ("chapada", "slap", "")
                ]
                cursor.executemany(
                    "INSERT INTO keywords (keyword, action_type, action_value) VALUES (?, ?, ?)",
                    defaults
                )
                print("Populated default keywords")

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
    
    def insert_action(self, username, action, target, guild_id=None):
        username = username.split("#")[0]
        try:
            self.cursor.execute(
                "INSERT INTO actions (username, action, target, guild_id) VALUES (?, ?, ?, ?);",
                (username, action, target, str(guild_id) if guild_id is not None else None),
            )
            self.conn.commit()
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")

    def insert_sound(self, originalfilename, filename, favorite=0, date=None, is_elevenlabs=0, guild_id=None):
        if date is None:
            date = datetime.datetime.now()
        try:
            self.cursor.execute(
                "INSERT INTO sounds (originalfilename, Filename, favorite, blacklist, timestamp, is_elevenlabs, guild_id) VALUES (?, ?, ?, 0, ?, ?, ?);",
                (originalfilename, filename, favorite, date, is_elevenlabs, str(guild_id) if guild_id is not None else None)
            )
            self.conn.commit()
            self.invalidate_sound_cache()  # Refresh cache for similarity search
            print("Sound inserted successfully")
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
    
    def insert_user(self, event, sound, guild_id=None):
        try:
            self.cursor.execute(
                "INSERT INTO users (event, sound, guild_id) VALUES (?, ?, ?);",
                (event, sound, str(guild_id) if guild_id is not None else None),
            )
            self.conn.commit()
            print("User inserted successfully")
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")

    # ===== AI Commentary Memory =====
    
    def save_ai_memory(self, guild_id: str, transcription: str, response: str):
        """Save an AI commentary interaction to memory."""
        try:
            self.cursor.execute(
                "INSERT INTO ai_commentary_memory (guild_id, transcription, response) VALUES (?, ?, ?);",
                (str(guild_id), transcription, response)
            )
            self.conn.commit()
        except sqlite3.Error as e:
            print(f"[Database] Error saving AI memory: {e}")
    
    def get_recent_ai_memories(self, guild_id: str, limit: int = 3) -> list:
        """Get the last N AI commentary memories for a guild."""
        try:
            self.cursor.execute(
                """SELECT transcription, response, timestamp 
                   FROM ai_commentary_memory 
                   WHERE guild_id = ? 
                   ORDER BY timestamp DESC 
                   LIMIT ?""",
                (str(guild_id), limit)
            )
            rows = self.cursor.fetchall()
            # Reverse to get chronological order (oldest first)
            return [(row[0], row[1]) for row in reversed(rows)]
        except sqlite3.Error as e:
            print(f"[Database] Error getting AI memories: {e}")
            return []

    # ===== Fuzzy similarity search (complex logic kept here) =====
    
    def normalize_text(self, text):
        """Normalize text for fuzzy matching.
        
        Handles:
        - Leet-speak substitutions (0->o, 1->i, etc.)
        - File extensions (.mp3)
        - Special characters (hyphens, underscores -> spaces)
        - Multiple spaces collapsed to single space
        """
        import re
        
        # Leet-speak substitutions
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
        
        # Remove .mp3 extension
        text = text.replace('.mp3', '')
        
        # Replace hyphens and underscores with spaces (improves tokenization)
        text = re.sub(r'[-_]+', ' ', text)
        
        # Collapse multiple spaces to single space
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text.lower()

    def get_sounds_by_similarity(self, req_sound, num_results=5, sleep_interval=0.0, guild_id=None):
        """Return the most similar sounds using in-memory cache.
        
        Uses RapidFuzz (C++ optimized) + cached sounds for ~10-50x speedup.
        The sleep_interval parameter is kept for API compatibility but ignored
        since the cache makes iteration fast enough.
        """
        # Ensure cache is loaded
        if Database._sound_cache_normalized is None:
            self._load_sound_cache()
        
        if not Database._sound_cache_normalized:
            print("No sounds available for similarity scoring.")
            return []
        
        normalized_req = self.normalize_text(req_sound)
        scored_matches = []
        
        # Use cached sounds with pre-normalized filenames
        for sound, normalized_filename in Database._sound_cache_normalized:
            # Skip ElevenLabs generated sounds
            sound_dict = sound if isinstance(sound, dict) else dict(sound)
            if sound_dict.get('is_elevenlabs', 0) == 1:
                continue
            sound_guild_id = sound_dict.get("guild_id")
            if guild_id is not None and sound_guild_id not in (None, str(guild_id), guild_id):
                continue
            
            # Calculate multiple fuzzy matching scores (same algorithms, C++ speed)
            token_set_score = fuzz.token_set_ratio(normalized_req, normalized_filename)
            partial_ratio_score = fuzz.partial_ratio(normalized_req, normalized_filename)
            token_sort_score = fuzz.token_sort_ratio(normalized_req, normalized_filename)

            # Combine scores with weighted average
            combined_score = (0.5 * token_set_score) + (0.3 * partial_ratio_score) + (0.2 * token_sort_score)
            if guild_id is not None and str(sound_guild_id) == str(guild_id):
                combined_score += 5.0  # Prefer guild-local sounds over global fallback.

            scored_matches.append((combined_score, sound))
        
        # Sort by combined score descending
        scored_matches.sort(key=lambda x: x[0], reverse=True)
        
        # Select top N matches
        top_matches = scored_matches[:num_results]
        
        print("Sounds found successfully")
        return [(match[1], match[0]) for match in top_matches]  # (sound data, score) pairs

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
    
    def get_sound(self, sound_filename, original_filename=False, guild_id=None):
        """Delegate to SoundRepository for tenant-aware sound resolution."""
        from bot.repositories import SoundRepository
        return SoundRepository().get_sound(sound_filename, original_filename, guild_id=guild_id)

    # ===== Backwards-compatible delegators (for UI layer) =====
    # These methods delegate to repositories for backwards compatibility
    
    def get_random_sounds(self, favorite=None, num_sounds=1, guild_id=None):
        """Delegate to SoundRepository for backwards compatibility."""
        from bot.repositories import SoundRepository
        return SoundRepository().get_random_sounds(favorite=favorite, num_sounds=num_sounds, guild_id=guild_id)
    
    def get_sounds(self, favorite=None, slap=None, num_sounds=25, sort="DESC", favorite_by_user=False, user=None, guild_id=None):
        """Delegate to SoundRepository for backwards compatibility."""
        from bot.repositories import SoundRepository
        return SoundRepository().get_sounds(favorite=favorite, slap=slap, num_sounds=num_sounds, 
                                            sort=sort, favorite_by_user=favorite_by_user, user=user, guild_id=guild_id)
    
    def get_sound_by_name(self, sound_name, guild_id=None):
        """Delegate to SoundRepository for backwards compatibility."""
        from bot.repositories import SoundRepository
        return SoundRepository().get_sound_by_name(sound_name, guild_id=guild_id)
    
    async def update_sound(self, filename, new_filename=None, favorite=None, slap=None):
        """Delegate to SoundRepository for backwards compatibility."""
        from bot.repositories import SoundRepository
        return SoundRepository().update_sound(filename, new_filename=new_filename, favorite=favorite, slap=slap)
    
    def get_user_events(self, user, event, guild_id=None):
        """Delegate to EventRepository for backwards compatibility."""
        from bot.repositories import EventRepository
        return EventRepository().get_user_events(user, event, guild_id=guild_id)
    
    def get_user_event_sound(self, user_id, event, sound, guild_id=None):
        """Delegate to EventRepository for backwards compatibility."""
        from bot.repositories import EventRepository
        # Use get_event_sound which returns the tuple if exists, None otherwise
        result = EventRepository().get_event_sound(user_id, event, sound, guild_id=guild_id)
        return result is not None
    
    def toggle_user_event_sound(self, user_id, event, sound, guild_id=None):
        """Delegate to EventRepository for backwards compatibility."""
        from bot.repositories import EventRepository
        return EventRepository().toggle(user_id, event, sound, guild_id=guild_id)
    
    def remove_user_event_sound(self, user_id, event, sound, guild_id=None):
        """Delegate to EventRepository for backwards compatibility."""
        from bot.repositories import EventRepository
        return EventRepository().remove(user_id, event, sound, guild_id=guild_id)
    
    def get_sound_lists(self, creator=None, guild_id=None):
        """Delegate to ListRepository for backwards compatibility."""
        from bot.repositories import ListRepository
        return ListRepository().get_all(creator=creator, guild_id=guild_id)
    
    def get_sound_list(self, list_id, guild_id=None):
        """Delegate to ListRepository for backwards compatibility."""
        from bot.repositories import ListRepository
        return ListRepository().get_by_id(list_id, guild_id=guild_id)
    
    def get_sounds_in_list(self, list_id):
        """Delegate to ListRepository for backwards compatibility."""
        from bot.repositories import ListRepository
        return ListRepository().get_sounds_in_list(list_id)
    
    def get_list_by_name(self, list_name, creator=None, guild_id=None):
        """Delegate to ListRepository for backwards compatibility."""
        from bot.repositories import ListRepository
        return ListRepository().get_by_name(list_name, creator, guild_id=guild_id)
    
    def create_sound_list(self, list_name, creator, guild_id=None):
        """Delegate to ListRepository for backwards compatibility."""
        from bot.repositories import ListRepository
        return ListRepository().create(list_name, creator, guild_id=guild_id)
    
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
    
    def get_lists_containing_sound(self, sound_filename, guild_id=None):
        """Delegate to ListRepository for backwards compatibility."""
        from bot.repositories import ListRepository
        return ListRepository().get_lists_containing_sound(sound_filename, guild_id=guild_id)
