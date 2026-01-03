import sqlite3
import os
import csv
import json
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
        # Allow usage from background threads
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.behavior = behavior


    @staticmethod
    def create_database():
        try:
            # Get the current directory of the script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(script_dir, "..", "database.db")

            # Connect to SQLite database (or create it if it doesn't exist)
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            print(f"Connected to the database at database.db")

            # SQL command to create 'actions' table if it doesn't exist
            create_actions_table = '''
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            '''
            
            # SQL command to create 'sound_lists' table if it doesn't exist
            create_sound_lists_table = '''
            CREATE TABLE IF NOT EXISTS sound_lists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                list_name TEXT NOT NULL,
                creator TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            '''
            
            # SQL command to create 'sound_list_items' table if it doesn't exist
            create_sound_list_items_table = '''
            CREATE TABLE IF NOT EXISTS sound_list_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                list_id INTEGER NOT NULL,
                sound_filename TEXT NOT NULL,
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (list_id) REFERENCES sound_lists (id) ON DELETE CASCADE
            );
            '''
            
            # SQL command to create 'sounds' table if it doesn't exist
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

            # users table should have id, event, sound, timestamp
            create_users_table = '''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT NOT NULL,
                event TEXT NOT NULL,
                sound TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            '''

            # SQL command to create 'playback_queue' table if it doesn't exist
            create_playback_queue_table = '''
            CREATE TABLE IF NOT EXISTS playback_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                sound_filename TEXT NOT NULL,
                requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                played_at DATETIME NULL
            );
            '''


            # Execute the SQL commands
            #cursor.execute(create_actions_table)
            cursor.execute(create_sound_lists_table)
            cursor.execute(create_sound_list_items_table)
            #cursor.execute(create_sounds_table)
            #cursor.execute(create_users_table)
            cursor.execute(create_playback_queue_table)
            
            print("Tables created successfully")

            # Commit the changes and close the connection
            conn.commit()
            print("Changes committed")
        except Exception as e:
            print(f"Error setting up database: {e}")
        finally:
            if conn:
                conn.close()
                print("Connection closed")

    def insert_action(self, username, action, target):
        username = username.split("#")[0]
        try:
            self.cursor.execute("INSERT INTO actions (username, action, target) VALUES (?, ?, ?);", (username, action, target))
            self.conn.commit()
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")


    def insert_sound(self, originalfilename, filename, favorite=0, blacklist=0, date=datetime.datetime.now()):
        try:
            self.cursor.execute("INSERT INTO sounds (originalfilename, Filename, favorite, blacklist, timestamp) VALUES (?, ?, ?, ?, ?);", (originalfilename, filename, favorite, blacklist, date))
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

    def get_random_sounds(self, favorite=None, num_sounds=1):
        # get random sound(s) where blacklist is 0, and favorite is 1 if favorite is True
        try:
            if favorite:
                self.cursor.execute("SELECT * FROM sounds WHERE blacklist = 0 AND favorite = 1 ORDER BY RANDOM() LIMIT ?;", (num_sounds,))
            else:
                self.cursor.execute("SELECT * FROM sounds WHERE blacklist = 0 ORDER BY RANDOM() LIMIT ?;", (num_sounds,))
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")

    def normalize_text(self,text):
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
            # Add more substitutions as needed
        }
        for key, value in substitutions.items():
            text = text.replace(key, value)
        return text.lower()

    def get_sounds_by_similarity(self, req_sound, num_results=5, sleep_interval=0.0):
        """Return the most similar sounds. Optionally sleep between iterations
        to reduce CPU spikes that can cause audio stutter."""
        # Normalize the requested sound to handle character substitutions
        normalized_req = self.normalize_text(req_sound)
        try:
            # Use a separate connection for this potentially heavy query to
            # avoid locking the main connection used by the bot.
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM sounds")
            all_sounds = cursor.fetchall()
            if not all_sounds:
                print("No sounds available for similarity scoring.")
                return []
            scored_matches = []
            for sound in all_sounds:
                filename = sound[2]  # Assuming 'Filename' is at index 2
                normalized_filename = self.normalize_text(filename)

                # Calculate multiple fuzzy matching scores
                token_set_score = fuzz.token_set_ratio(normalized_req, normalized_filename)
                partial_ratio_score = fuzz.partial_ratio(normalized_req, normalized_filename)
                token_sort_score = fuzz.token_sort_ratio(normalized_req, normalized_filename)

                # Combine scores with weighted average for a more robust similarity measure
                combined_score = (0.5 * token_set_score) + (0.3 * partial_ratio_score) + (0.2 * token_sort_score)

                scored_matches.append((combined_score, sound))

                if sleep_interval:
                    time.sleep(sleep_interval)
            
            # Sort the matches by combined score in descending order
            scored_matches.sort(key=lambda x: x[0], reverse=True)
            
            # Select the top N matches based on the desired number of results
            top_matches = scored_matches[:num_results]
            
            print("Sounds found successfully")
            return [(match[1], match[0]) for match in top_matches]  # Return (sound data, score) pairs
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
            return []
        finally:
            conn.close()

    def get_sounds_by_similarity_optimized(self, req_sound, num_results=5):
        # Normalize the requested sound
        normalized_req = self.normalize_text(req_sound)
        try:
            # Split the search term into words and create a more flexible search pattern
            search_words = normalized_req.replace('-', ' ').split()
            
            # Build a dynamic SQL query that searches for any of the words
            like_conditions = []
            params = []

            # Handle special word combinations first
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
                    params.extend([
                        f"%he%is%",
                        f"%hes%"
                    ])
                    i += 2  # Skip next word since we handled it
                    continue
                # Handle "hes" as "he is"
                elif current_word == "hes":
                    like_conditions.extend([
                        "LOWER(Filename) LIKE ?",
                        "LOWER(Filename) LIKE ?"
                    ])
                    params.extend([
                        f"%he%is%",
                        f"%hes%"
                    ])
                # Handle "is" / "'s" variations
                elif current_word == "is":
                    like_conditions.extend([
                        "LOWER(Filename) LIKE ?",
                        "LOWER(Filename) LIKE ?"
                    ])
                    params.extend([
                        f"%is%",
                        f"%'s%"
                    ])
                # For all other words, add flexible matching
                else:
                    like_conditions.append("LOWER(Filename) LIKE ?")
                    params.append(f"%{current_word}%")

                i += 1

            # Add a condition that tries to match the entire phrase
            like_conditions.append("LOWER(Filename) LIKE ?")
            full_phrase = normalized_req.replace(' ', '%')
            params.append(f"%{full_phrase}%")
            
            # Combine conditions with OR to match any variation
            query = f"""
                SELECT * FROM sounds 
                WHERE blacklist = 0 
                AND ({" OR ".join(like_conditions)})
                LIMIT 150
            """
            
            self.cursor.execute(query, tuple(params))
            potential_matches = self.cursor.fetchall()

            if not potential_matches:
                return []

            # Score matches using multiple fuzzy ratios for better accuracy
            scored_matches = []
            for sound in potential_matches:
                filename = sound[2]  # Filename is at index 2
                normalized_filename = self.normalize_text(filename)
                
                # Use multiple scoring methods for better accuracy
                token_set_score = fuzz.token_set_ratio(normalized_req, normalized_filename)
                partial_ratio_score = fuzz.partial_ratio(normalized_req, normalized_filename)
                token_sort_score = fuzz.token_sort_ratio(normalized_req, normalized_filename)
                
                # Add extra weight for matches that contain all search words
                all_words_present = all(word in normalized_filename for word in search_words)
                word_presence_bonus = 20 if all_words_present else 0
                
                # Weighted combination of scores with word presence bonus
                combined_score = (0.5 * token_set_score) + (0.3 * partial_ratio_score) + (0.2 * token_sort_score) + word_presence_bonus
                scored_matches.append((combined_score, sound))
            
            # Sort by score and get top matches
            scored_matches.sort(key=lambda x: x[0], reverse=True)
            return [(match[1], match[0]) for match in scored_matches[:num_results]]
            
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
            return []

    def get_sound(self, sound_filename, original_filename=False):
        try:
            if original_filename:
                self.cursor.execute("SELECT * FROM sounds WHERE originalfilename = ?;", (sound_filename,))
            else:
                self.cursor.execute("SELECT * FROM sounds WHERE Filename = ?;", (sound_filename,))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")

    def get_sound_by_name(self, sound_name):
        """Get a sound by its name (with or without .mp3 extension)"""
        try:
            # Add .mp3 extension if not already present
            if not sound_name.lower().endswith('.mp3'):
                sound_name = f"{sound_name}.mp3"
                
            # First try to match exact filename
            self.cursor.execute("SELECT * FROM sounds WHERE Filename = ?;", (sound_name,))
            result = self.cursor.fetchone()
            if result:
                return result
                
            # If no result, try to match against original filename
            self.cursor.execute("SELECT * FROM sounds WHERE originalfilename = ?;", (sound_name,))
            result = self.cursor.fetchone()
            if result:
                return result
                
            # If still no result, try to do a LIKE search
            sound_name_pattern = f"%{sound_name}%"
            self.cursor.execute("SELECT * FROM sounds WHERE Filename LIKE ? OR originalfilename LIKE ?;", 
                               (sound_name_pattern, sound_name_pattern))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
            return None

    def get_sounds(self, favorite=None, blacklist=None, slap=None, num_sounds=25, sort="DESC", favorite_by_user=False, user=None):
        if favorite_by_user and user:
            try:
                # Query the actions table for favorite_sound actions by the specified user
                # Join with sounds table and only get sounds where the most recent action is 'favorite_sound'
                query = """
                WITH LastActions AS (
                    SELECT target,
                           action,
                           timestamp,
                           ROW_NUMBER() OVER (PARTITION BY target ORDER BY timestamp DESC) as rn
                    FROM actions
                    WHERE username = ?
                    AND action IN ('favorite_sound', 'unfavorite_sound')
                )
                SELECT DISTINCT s.* 
                FROM sounds s
                JOIN LastActions la ON s.id = la.target
                WHERE la.rn = 1 
                AND la.action = 'favorite_sound'
                AND s.favorite = 1
                ORDER BY la.timestamp DESC
                LIMIT ?;
                """
                self.cursor.execute(query, (user, num_sounds))
                return self.cursor.fetchall()
            except sqlite3.Error as e:
                print(f"An error occurred: {e}")
                return []
        
        # Existing functionality
        favorite = 1 if favorite else 0
        blacklist = 1 if blacklist else 0
        slap = 1 if slap else 0
        try:
            conditions = []
            params = []
            
            if favorite is not None:
                conditions.append("favorite = ?")
                params.append(favorite)
            if blacklist is not None:
                conditions.append("blacklist = ?")
                params.append(blacklist)
            if slap is not None:
                if slap == 1:
                    #remove conditions
                    conditions = []
                    params = []
                conditions.append("slap = ?")
                params.append(slap)
            
            query = "SELECT * FROM sounds"
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += f" ORDER BY id {sort} LIMIT ?"
            params.append(num_sounds)
            
            self.cursor.execute(query, tuple(params))
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")

    def get_top_users(self, number=5, days=0, by="plays"):
        try:
            query = """
            SELECT a.username, COUNT(*) as count
            FROM actions a
            JOIN sounds s ON a.target = s.id
            WHERE a.action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 'play_request')
            AND s.slap = 0
            """
            
            if days > 0:
                query += f" AND a.timestamp >= datetime('now', '-{days} days')"
            
            query += """
            GROUP BY a.username
            ORDER BY count DESC
            LIMIT ?
            """
            
            self.cursor.execute(query, (number,))
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
            return []
        
    def get_top_sounds(self, number=5, days=0, user=None):
        try:
            query = """
            SELECT s.Filename, COUNT(*) as count
            FROM actions a
            JOIN sounds s ON a.target = s.id
            WHERE a.action IN ('play_sound_periodically','play_random_sound', 'replay_sound', 'play_random_favorite_sound', 'play_request')
            AND s.slap = 0
            """
            
            params = []
            
            if days > 0:
                query += " AND a.timestamp >= datetime('now', '-' || ? || ' days')"
                params.append(str(days))
            
            if user:
                query += " AND a.username = ?"
                params.append(user)
            
            query += """
            GROUP BY s.Filename
            ORDER BY count DESC
            LIMIT ?
            """
            params.append(number)
            
            self.cursor.execute(query, tuple(params))
            top_sounds = self.cursor.fetchall()

            # Get total count
            total_count_query = """
            SELECT COUNT(*) as total_count
            FROM actions a
            JOIN sounds s ON a.target = s.id
            WHERE a.action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 'play_request')
            AND s.slap = 0
            """
            
            if days > 0:
                total_count_query += " AND a.timestamp >= datetime('now', '-' || ? || ' days')"
            
            if user:
                total_count_query += " AND a.username = ?"
            
            self.cursor.execute(total_count_query, tuple(params[:-1]))  # Exclude the LIMIT parameter
            total_count = self.cursor.fetchone()[0]

            return top_sounds, total_count
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
            return [], 0
        
    def get_sound_play_count(self, sound_id):
        """Get the total play count for a specific sound"""
        try:
            query = """
            SELECT COUNT(*) as play_count
            FROM actions a
            WHERE a.target = ?
            AND a.action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 'play_request')
            """
            
            self.cursor.execute(query, (sound_id,))
            result = self.cursor.fetchone()
            return result[0] if result else 0
        except sqlite3.Error as e:
            print(f"An error occurred getting play count: {e}")
            return 0
        
    def get_user_events(self, user, event):
        try:
            if user == "*":
                self.cursor.execute("SELECT DISTINCT id FROM users WHERE event = ?;", (event,))
            else:
                self.cursor.execute("SELECT * FROM users WHERE id = ? AND event = ?;", (user, event))
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
            return []

    def get_all_users(self):
        """Get all unique users who have event sounds configured"""
        try:
            self.cursor.execute("SELECT DISTINCT id FROM users;")
            return [user[0] for user in self.cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
            return []

    def get_user_event_sound(self, user_id, event, sound):
        """Check if a specific user event sound exists"""
        try:
            self.cursor.execute("SELECT * FROM users WHERE id = ? AND event = ? AND sound = ?;", (user_id, event, sound))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
            return None

    def insert_user_event_sound(self, user_id, event, sound):
        """Insert a new user event sound"""
        try:
            self.cursor.execute("INSERT INTO users (id, event, sound) VALUES (?, ?, ?);", (user_id, event, sound))
            self.conn.commit()
            print("User event sound inserted successfully")
            return True
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
            return False

    def remove_user_event_sound(self, user_id, event, sound):
        """Remove a user event sound"""
        try:
            self.cursor.execute("DELETE FROM users WHERE id = ? AND event = ? AND sound = ?;", (user_id, event, sound))
            self.conn.commit()
            print("User event sound removed successfully")
            return True
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
            return False

    def toggle_user_event_sound(self, user_id, event, sound):
        """Toggle a user event sound (add if doesn't exist, remove if exists)"""
        try:
            # Check if the event sound exists
            existing = self.get_user_event_sound(user_id, event, sound)
            
            if existing:
                # If exists, remove it
                return self.remove_user_event_sound(user_id, event, sound)
            else:
                # If doesn't exist, add it
                return self.insert_user_event_sound(user_id, event, sound)
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
            return False

    async def update_sound(self, filename, new_filename=None, favorite=None, blacklist=None, slap=None):
        if new_filename is not None:
            new_filename = new_filename + ".mp3"
        favorite = 1 if favorite else 0 if favorite is not None else None
        blacklist = 1 if blacklist else 0 if blacklist is not None else None
        slap = 1 if slap else 0 if slap is not None else None

        try:
            if new_filename:
                self.cursor.execute("UPDATE sounds SET Filename = ? WHERE Filename = ?;", (new_filename, filename))
            if favorite is not None:
                self.cursor.execute("UPDATE sounds SET favorite = ? WHERE Filename = ?;", (favorite, filename))
            if blacklist is not None:
                self.cursor.execute("UPDATE sounds SET blacklist = ? WHERE Filename = ?;", (blacklist, filename))
            if slap is not None:
                self.cursor.execute("UPDATE sounds SET slap = ? WHERE filename = ?", (slap, filename))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error updating sound: {e}")
            return False
            
    # Sound List Methods
    def create_sound_list(self, list_name, creator):
        """Create a new sound list"""
        try:
            self.cursor.execute(
                "INSERT INTO sound_lists (list_name, creator) VALUES (?, ?)",
                (list_name, creator)
            )
            self.conn.commit()
            return self.cursor.lastrowid
        except Exception as e:
            print(f"Error creating sound list: {e}")
            return None
            
    def add_sound_to_list(self, list_id, sound_filename):
        """Add a sound to a list"""
        try:
            # Check if the sound exists - try both filename and originalfilename
            self.cursor.execute("SELECT filename FROM sounds WHERE originalfilename = ?", (sound_filename,))
            sound = self.cursor.fetchone()
            if not sound:
                # Try matching against the actual filename as well
                self.cursor.execute("SELECT filename FROM sounds WHERE filename = ?", (sound_filename,))
                sound = self.cursor.fetchone()
            if not sound:
                return False, "Sound not found"
            
            # Use the actual filename from the sounds table for storage
            actual_filename = sound[0]
                
            # Check if the sound is already in the list
            self.cursor.execute(
                "SELECT id FROM sound_list_items WHERE list_id = ? AND sound_filename = ?",
                (list_id, actual_filename)
            )
            if self.cursor.fetchone():
                return False, "Sound already in list"
                
            # Add the sound to the list using the actual filename
            self.cursor.execute(
                "INSERT INTO sound_list_items (list_id, sound_filename) VALUES (?, ?)",
                (list_id, actual_filename)
            )
            self.conn.commit()
            return True, "Sound added to list"
        except Exception as e:
            print(f"Error adding sound to list: {e}")
            return False, str(e)
            
    def remove_sound_from_list(self, list_id, sound_filename):
        """Remove a sound from a list"""
        try:
            self.cursor.execute(
                "DELETE FROM sound_list_items WHERE list_id = ? AND sound_filename = ?",
                (list_id, sound_filename)
            )
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error removing sound from list: {e}")
            return False
            
    def delete_sound_list(self, list_id):
        """Delete a sound list"""
        try:
            # Delete the list items first
            self.cursor.execute("DELETE FROM sound_list_items WHERE list_id = ?", (list_id,))
            # Delete the list
            self.cursor.execute("DELETE FROM sound_lists WHERE id = ?", (list_id,))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error deleting sound list: {e}")
            return False
            
    def get_sound_lists(self, creator=None):
        """Get all sound lists or lists created by a specific user"""
        try:
            if creator:
                self.cursor.execute(
                    """
                    SELECT sl.id, sl.list_name, sl.creator, sl.created_at, COUNT(sli.id) as sound_count
                    FROM sound_lists sl
                    LEFT JOIN sound_list_items sli ON sl.id = sli.list_id
                    WHERE sl.creator = ?
                    GROUP BY sl.id
                    ORDER BY sound_count DESC
                    """,
                    (creator,)
                )
            else:
                self.cursor.execute(
                    """
                    SELECT sl.id, sl.list_name, sl.creator, sl.created_at, COUNT(sli.id) as sound_count
                    FROM sound_lists sl
                    LEFT JOIN sound_list_items sli ON sl.id = sli.list_id
                    GROUP BY sl.id
                    ORDER BY sound_count DESC
                    """
                )
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error getting sound lists: {e}")
            return []
            
    def get_sound_list(self, list_id):
        """Get a specific sound list by ID"""
        try:
            self.cursor.execute(
                "SELECT id, list_name, creator, created_at FROM sound_lists WHERE id = ?",
                (list_id,)
            )
            return self.cursor.fetchone()
        except Exception as e:
            print(f"Error getting sound list: {e}")
            return None
            
    def get_sounds_in_list(self, list_id):
        """Get all sounds in a list"""
        try:
            self.cursor.execute(
                """
                SELECT s.filename, s.originalfilename 
                FROM sound_list_items sli
                JOIN sounds s ON sli.sound_filename = s.filename
                WHERE sli.list_id = ?
                ORDER BY sli.added_at DESC
                """,
                (list_id,)
            )
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error getting sounds in list: {e}")
            return []

    def get_random_sound_from_list(self, list_name):
        """Return a random sound from a given list name"""
        try:
            self.cursor.execute(
                """
                SELECT s.id, s.filename, s.originalfilename
                FROM sound_list_items sli
                JOIN sound_lists sl ON sli.list_id = sl.id
                JOIN sounds s ON sli.sound_filename = s.filename
                WHERE sl.list_name = ?
                ORDER BY RANDOM()
                LIMIT 1
                """,
                (list_name,)
            )
            return self.cursor.fetchone()
        except Exception as e:
            print(f"Error getting random sound from list: {e}")
            return None
            
    def get_list_by_name(self, list_name, creator=None):
        """Get a list by name and optionally creator"""
        try:
            if creator:
                self.cursor.execute(
                    "SELECT id, list_name, creator, created_at FROM sound_lists WHERE list_name = ? AND creator = ?",
                    (list_name, creator)
                )
            else:
                self.cursor.execute(
                    "SELECT id, list_name, creator, created_at FROM sound_lists WHERE list_name = ?",
                    (list_name,)
                )
            return self.cursor.fetchone()
        except Exception as e:
            print(f"Error getting list by name: {e}")
            return None

    def get_lists_containing_sound(self, sound_filename):
        """Get all lists that contain a specific sound"""
        try:
            self.cursor.execute("""
                SELECT sl.id, sl.list_name, sl.creator
                FROM sound_lists sl
                JOIN sound_list_items sli ON sl.id = sli.list_id
                WHERE sli.sound_filename = ?
                ORDER BY sl.list_name
            """, (sound_filename,))
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error getting lists containing sound: {e}")
            return []
            
    def get_users_who_favorited_sound(self, sound_id):
        """Get all users who have favorited a specific sound"""
        try:
            # Get the most recent favorite/unfavorite action for each user for this sound
            query = """
            WITH UserActions AS (
                SELECT 
                    username,
                    action,
                    timestamp,
                    ROW_NUMBER() OVER (PARTITION BY username ORDER BY timestamp DESC) as rn
                FROM actions
                WHERE target = ?
                AND action IN ('favorite_sound', 'unfavorite_sound')
            )
            SELECT username
            FROM UserActions
            WHERE rn = 1 AND action = 'favorite_sound'
            ORDER BY username
            """
            self.cursor.execute(query, (sound_id,))
            return [row[0] for row in self.cursor.fetchall()]
        except Exception as e:
            print(f"Error getting users who favorited sound: {e}")
            return []

    def get_sound_download_date(self, sound_id):
        """Get the date when a sound was downloaded/added to the database"""
        try:
            # First check if the sound has a timestamp in the sounds table
            self.cursor.execute("SELECT timestamp FROM sounds WHERE id = ?", (sound_id,))
            result = self.cursor.fetchone()
            
            if result and result[0]:
                # Check if it's close to the hardcoded date
                if isinstance(result[0], str) and result[0].startswith("2023-10-30"):
                    return "2023-10-30 11:04:46"  # Mark as the hardcoded date
                return result[0]
            
            # Check if this is one of the sounds with the hardcoded date
            # by looking for the earliest action and checking if it's the hardcoded date
            query = """
            SELECT MIN(timestamp) 
            FROM actions 
            WHERE target = ? 
            """
            self.cursor.execute(query, (sound_id,))
            result = self.cursor.fetchone()
            
            if result and result[0]:
                # If the date is exactly or close to the hardcoded date, mark it specially
                if isinstance(result[0], str) and result[0].startswith("2023-10-30"):
                    return "2023-10-30 11:04:46"
                return result[0]
                
            return "Unknown date"
        except Exception as e:
            print(f"Error getting sound download date: {e}")
            return "Unknown date"

    def get_user_year_stats(self, username, year):
        """Get comprehensive yearly stats for a user for the /yearreview command"""
        stats = {
            'total_plays': 0,
            'random_plays': 0,
            'requested_plays': 0,
            'favorite_plays': 0,
            'top_sounds': [],
            'sounds_favorited': 0,
            'sounds_uploaded': 0,
            'tts_messages': 0,
            'voice_joins': 0,
            'voice_leaves': 0,
            'mute_actions': 0,
        }
        
        try:
            year_start = f"{year}-01-01 00:00:00"
            year_end = f"{year}-12-31 23:59:59"
            
            # Total plays and breakdown
            play_actions = ['play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                           'play_request', 'play_from_list', 'play_similar_sound']
            
            self.cursor.execute("""
                SELECT action, COUNT(*) as count
                FROM actions
                WHERE username = ? 
                AND timestamp BETWEEN ? AND ?
                AND action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                              'play_request', 'play_from_list', 'play_similar_sound')
                GROUP BY action
            """, (username, year_start, year_end))
            
            for action, count in self.cursor.fetchall():
                stats['total_plays'] += count
                if action in ['play_random_sound']:
                    stats['random_plays'] += count
                elif action in ['play_request', 'replay_sound', 'play_from_list', 'play_similar_sound']:
                    stats['requested_plays'] += count
                elif action == 'play_random_favorite_sound':
                    stats['favorite_plays'] += count
            
            # Top 5 sounds played
            self.cursor.execute("""
                SELECT s.Filename, COUNT(*) as play_count
                FROM actions a
                JOIN sounds s ON a.target = s.id
                WHERE a.username = ?
                AND a.timestamp BETWEEN ? AND ?
                AND a.action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                                'play_request', 'play_from_list', 'play_similar_sound')
                AND s.slap = 0
                GROUP BY s.Filename
                ORDER BY play_count DESC
                LIMIT 5
            """, (username, year_start, year_end))
            stats['top_sounds'] = self.cursor.fetchall()
            
            # Sounds favorited
            self.cursor.execute("""
                SELECT COUNT(*) FROM actions
                WHERE username = ? AND action = 'favorite_sound'
                AND timestamp BETWEEN ? AND ?
            """, (username, year_start, year_end))
            stats['sounds_favorited'] = self.cursor.fetchone()[0]
            
            # Sounds uploaded
            self.cursor.execute("""
                SELECT COUNT(*) FROM actions
                WHERE username = ? AND action = 'upload_sound'
                AND timestamp BETWEEN ? AND ?
            """, (username, year_start, year_end))
            stats['sounds_uploaded'] = self.cursor.fetchone()[0]
            
            # TTS messages
            self.cursor.execute("""
                SELECT COUNT(*) FROM actions
                WHERE username = ? AND action IN ('tts', 'tts_EL', 'sts_EL')
                AND timestamp BETWEEN ? AND ?
            """, (username, year_start, year_end))
            stats['tts_messages'] = self.cursor.fetchone()[0]
            
            # Voice joins/leaves
            self.cursor.execute("""
                SELECT action, COUNT(*) FROM actions
                WHERE username = ? AND action IN ('join', 'leave')
                AND timestamp BETWEEN ? AND ?
                GROUP BY action
            """, (username, year_start, year_end))
            for action, count in self.cursor.fetchall():
                if action == 'join':
                    stats['voice_joins'] = count
                elif action == 'leave':
                    stats['voice_leaves'] = count
            
            # Mute actions
            self.cursor.execute("""
                SELECT COUNT(*) FROM actions
                WHERE username = ? AND action = 'mute_30_minutes'
                AND timestamp BETWEEN ? AND ?
            """, (username, year_start, year_end))
            stats['mute_actions'] = self.cursor.fetchone()[0]
            
            # === NEW FUN STATS ===
            
            # Unique sounds played
            self.cursor.execute("""
                SELECT COUNT(DISTINCT a.target)
                FROM actions a
                JOIN sounds s ON a.target = s.id
                WHERE a.username = ?
                AND a.timestamp BETWEEN ? AND ?
                AND a.action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                                'play_request', 'play_from_list', 'play_similar_sound')
                AND s.slap = 0
            """, (username, year_start, year_end))
            stats['unique_sounds'] = self.cursor.fetchone()[0]
            
            # Most active day of week (0=Sunday, 1=Monday, etc in SQLite strftime %w)
            self.cursor.execute("""
                SELECT strftime('%w', timestamp) as day_of_week, COUNT(*) as count
                FROM actions
                WHERE username = ?
                AND timestamp BETWEEN ? AND ?
                AND action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                              'play_request', 'play_from_list', 'play_similar_sound')
                GROUP BY day_of_week
                ORDER BY count DESC
                LIMIT 1
            """, (username, year_start, year_end))
            result = self.cursor.fetchone()
            if result:
                day_names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
                stats['most_active_day'] = day_names[int(result[0])]
                stats['most_active_day_count'] = result[1]
            else:
                stats['most_active_day'] = None
                stats['most_active_day_count'] = 0
            
            # Most active hour
            self.cursor.execute("""
                SELECT strftime('%H', timestamp) as hour, COUNT(*) as count
                FROM actions
                WHERE username = ?
                AND timestamp BETWEEN ? AND ?
                AND action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                              'play_request', 'play_from_list', 'play_similar_sound')
                GROUP BY hour
                ORDER BY count DESC
                LIMIT 1
            """, (username, year_start, year_end))
            result = self.cursor.fetchone()
            if result:
                hour = int(result[0])
                stats['most_active_hour'] = hour
                stats['most_active_hour_count'] = result[1]
            else:
                stats['most_active_hour'] = None
                stats['most_active_hour_count'] = 0
            
            # First sound of the year
            self.cursor.execute("""
                SELECT s.Filename, a.timestamp
                FROM actions a
                JOIN sounds s ON a.target = s.id
                WHERE a.username = ?
                AND a.timestamp BETWEEN ? AND ?
                AND a.action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                                'play_request', 'play_from_list', 'play_similar_sound')
                AND s.slap = 0
                ORDER BY a.timestamp ASC
                LIMIT 1
            """, (username, year_start, year_end))
            result = self.cursor.fetchone()
            stats['first_sound'] = result[0] if result else None
            stats['first_sound_date'] = result[1] if result else None
            
            # Last sound of the year (most recent)
            self.cursor.execute("""
                SELECT s.Filename, a.timestamp
                FROM actions a
                JOIN sounds s ON a.target = s.id
                WHERE a.username = ?
                AND a.timestamp BETWEEN ? AND ?
                AND a.action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                                'play_request', 'play_from_list', 'play_similar_sound')
                AND s.slap = 0
                ORDER BY a.timestamp DESC
                LIMIT 1
            """, (username, year_start, year_end))
            result = self.cursor.fetchone()
            stats['last_sound'] = result[0] if result else None
            stats['last_sound_date'] = result[1] if result else None
            
            # Brain rot activities (subway surfers, family guy, etc.)
            self.cursor.execute("""
                SELECT action, COUNT(*) as count
                FROM actions
                WHERE username = ?
                AND timestamp BETWEEN ? AND ?
                AND action IN ('subway_surfers', 'family_guy', 'slice_all')
                GROUP BY action
            """, (username, year_start, year_end))
            brain_rot = {}
            for action, count in self.cursor.fetchall():
                brain_rot[action] = count
            stats['brain_rot'] = brain_rot
            
            # Leaderboard rank (compare to other users)
            self.cursor.execute("""
                SELECT username, COUNT(*) as play_count
                FROM actions
                WHERE timestamp BETWEEN ? AND ?
                AND action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                              'play_request', 'play_from_list', 'play_similar_sound')
                GROUP BY username
                ORDER BY play_count DESC
            """, (year_start, year_end))
            all_users = self.cursor.fetchall()
            stats['total_users'] = len(all_users)
            stats['user_rank'] = None
            for i, (user, count) in enumerate(all_users, 1):
                if user == username:
                    stats['user_rank'] = i
                    break
            
            # === SESSION & TIME STATS ===
            
            # Get all join/leave events to calculate time spent in voice
            self.cursor.execute("""
                SELECT action, timestamp
                FROM actions
                WHERE username = ?
                AND timestamp BETWEEN ? AND ?
                AND action IN ('join', 'leave')
                ORDER BY timestamp ASC
            """, (username, year_start, year_end))
            voice_events = self.cursor.fetchall()
            
            total_seconds = 0
            longest_session_seconds = 0
            current_join_time = None
            
            for action, timestamp in voice_events:
                if action == 'join':
                    current_join_time = timestamp
                elif action == 'leave' and current_join_time:
                    try:
                        # Parse timestamps
                        from datetime import datetime
                        join_dt = datetime.strptime(current_join_time, '%Y-%m-%d %H:%M:%S')
                        leave_dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                        session_seconds = (leave_dt - join_dt).total_seconds()
                        
                        # Cap individual sessions at 12 hours to filter outliers
                        if 0 < session_seconds <= 43200:
                            total_seconds += session_seconds
                            if session_seconds > longest_session_seconds:
                                longest_session_seconds = session_seconds
                    except:
                        pass
                    current_join_time = None
            
            stats['total_voice_hours'] = round(total_seconds / 3600, 1)
            stats['longest_session_hours'] = round(longest_session_seconds / 3600, 1)
            stats['longest_session_minutes'] = round(longest_session_seconds / 60)
            
            # Activity streak (consecutive days with any play action)
            self.cursor.execute("""
                SELECT DISTINCT date(timestamp) as play_date
                FROM actions
                WHERE username = ?
                AND timestamp BETWEEN ? AND ?
                AND action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                              'play_request', 'play_from_list', 'play_similar_sound')
                ORDER BY play_date ASC
            """, (username, year_start, year_end))
            active_dates = [row[0] for row in self.cursor.fetchall()]
            
            stats['total_active_days'] = len(active_dates)
            
            # Calculate longest streak
            longest_streak = 0
            current_streak = 0
            prev_date = None
            
            from datetime import datetime, timedelta
            for date_str in active_dates:
                current_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                if prev_date is None:
                    current_streak = 1
                elif (current_date - prev_date).days == 1:
                    current_streak += 1
                else:
                    current_streak = 1
                
                if current_streak > longest_streak:
                    longest_streak = current_streak
                prev_date = current_date
            
            stats['longest_streak'] = longest_streak
            
            return stats
        except Exception as e:
            print(f"Error getting user year stats: {e}")
            return stats

