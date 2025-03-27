import sqlite3
import os
import csv
import json
import datetime
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
        self.db_path = os.path.join(script_dir, "../database.db")
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self.behavior = behavior


    @staticmethod
    def create_database():
        try:
            # Get the current directory of the script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(script_dir, "../database.db")

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

            # Execute the SQL commands
            #cursor.execute(create_actions_table)
            cursor.execute(create_sound_lists_table)
            cursor.execute(create_sound_list_items_table)
            #cursor.execute(create_sounds_table)
            #cursor.execute(create_users_table)
            
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
            print("Action inserted successfully")
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

    def get_sounds_by_similarity(self, req_sound, num_results=5):
        # Normalize the requested sound to handle character substitutions
        normalized_req = self.normalize_text(req_sound)
        try:
            self.cursor.execute("SELECT * FROM sounds")
            all_sounds = self.cursor.fetchall()
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
            
            # Sort the matches by combined score in descending order
            scored_matches.sort(key=lambda x: x[0], reverse=True)
            
            # Select the top N matches based on the desired number of results
            top_matches = scored_matches[:num_results]
            
            print("Sounds found successfully")
            return [match[1] for match in top_matches]  # Return only the sound data
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
            return []

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
            return [match[1] for match in scored_matches[:num_results]]
            
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
            WHERE a.action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 'play_request')
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
            # Check if the sound exists
            self.cursor.execute("SELECT filename FROM sounds WHERE originalfilename = ?", (sound_filename,))
            sound = self.cursor.fetchone()
            if not sound:
                return False, "Sound not found"
                
            # Check if the sound is already in the list
            self.cursor.execute(
                "SELECT id FROM sound_list_items WHERE list_id = ? AND sound_filename = ?",
                (list_id, sound_filename)
            )
            if self.cursor.fetchone():
                return False, "Sound already in list"
                
            # Add the sound to the list
            self.cursor.execute(
                "INSERT INTO sound_list_items (list_id, sound_filename) VALUES (?, ?)",
                (list_id, sound_filename)
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
                    "SELECT id, list_name, creator, created_at FROM sound_lists WHERE creator = ? ORDER BY created_at DESC",
                    (creator,)
                )
            else:
                self.cursor.execute(
                    "SELECT id, list_name, creator, created_at FROM sound_lists ORDER BY created_at DESC"
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
                ORDER BY sli.added_at
                """,
                (list_id,)
            )
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error getting sounds in list: {e}")
            return []
            
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

class Migrate:
    # function that migrates sounds.csv to the database table 'sounds'
    @staticmethod
    def migrate_sounds():
        try:
            # Get the current directory of the script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            csv_path = os.path.join(script_dir, "../Data/soundsDB.csv")

            # Connect to SQLite database (or create it if it doesn't exist)
            conn = sqlite3.connect(Database().db_path)
            cursor = conn.cursor()

            # Open and read the CSV file using the csv module
            with open(csv_path, "r", newline='', encoding='utf-8') as csv_file:
                csv_reader = csv.reader(csv_file)

                # Skip the header row
                next(csv_reader)

                # Insert the data into the 'sounds' table
                for row in csv_reader:

                    filename, id, originalfilename, favorite, blacklist = row
                    # make blacklist and favorite 0 or 1 depending on true or false
                    favorite = 1 if favorite == "True" else 0
                    blacklist = 1 if blacklist == "True" else 0
                    
                    print(f"Inserting data: {id}")
                    try:
                        cursor.execute("INSERT INTO sounds (Filename, id, originalfilename, favorite, blacklist) VALUES (?, ?, ?, ?, ?);", (filename, int(id), originalfilename, favorite, blacklist))
                    except sqlite3.Error as e:
                        print(f"An error occurred: {e}")
            print("Data inserted successfully")

            # Commit the changes and close the connection
            conn.commit()
            print("Changes committed")
        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            if conn:
                conn.close()
                print("Connection closed")

    # function that migrates play_history.csv (col[0] is sound id, col1 is username, col2 is date) entries until 2024-05-27 18:40:20 to the database table 'actions'
    @staticmethod
    def migrate_play_history():
        try:
            # Get the current directory of the script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            csv_path = os.path.join(script_dir, "../Data/play_history.csv")

            # Connect to SQLite database (or create it if it doesn't exist)
            conn = sqlite3.connect(Database().db_path)
            cursor = conn.cursor()

            # Open and read the CSV file using the csv module
            with open(csv_path, "r", newline='', encoding='utf-8') as csv_file:
                csv_reader = csv.reader(csv_file)

                # Skip the header row
                next(csv_reader)

                # Insert the data into the 'actions' table
                for row in csv_reader:
                    sound_id, username, date = row
                    print(f"Inserting data: {sound_id}")
                    try:
                        cursor.execute("INSERT INTO actions (username, action, target, timestamp) VALUES (?, ?, ?, ?);", (username, "play_sound_generic", sound_id, date))
                    except sqlite3.Error as e:
                        print(f"An error occurred: {e}")
            print("Data inserted successfully")

            # Commit the changes and close the connection
            conn.commit()
            print("Changes committed")
        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            if conn:
                conn.close()
                print("Connection closed")
    
    # function that migrates other_actions.csv (col[0] is username, col1 is action, col2 is target, col3 is date) to the database table 'actions'
    @staticmethod
    def migrate_other_actions():
        try:
            # Get the current directory of the script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            csv_path = os.path.join(script_dir, "../Data/other_actions.csv")

            # Connect to SQLite database (or create it if it doesn't exist)
            conn = sqlite3.connect(Database().db_path)
            cursor = conn.cursor()

            # Open and read the CSV file using the csv module
            with open(csv_path, "r", newline='', encoding='utf-8') as csv_file:
                csv_reader = csv.reader(csv_file)

                # Skip the header row
                next(csv_reader)

                # Insert the data into the 'actions' table
                for row in csv_reader:
                    username, action, target, date = row
                    print(f"Inserting data: {action}")
                    try:
                        cursor.execute("""
                        SELECT s.id FROM sounds s 
                        WHERE s.originalfilename = ? OR s.Filename = ?
                        LIMIT 1
                        """, (target, target))

                        result = cursor.fetchone()

                        if result:
                            sound_id = result[0]
                            
                            # Now, let's insert into the actions table
                            cursor.execute("""
                            INSERT INTO actions (username, action, target, timestamp)
                            VALUES (?, ?, ?, ?)
                            """, (username, action, sound_id, date))
                        else:
                            # If the sound is not found, it means the target should be the target itself
                            cursor.execute("INSERT INTO actions (username, action, target, timestamp) VALUES (?, ?, ?, ?);", (username, action, target, date))
                    except sqlite3.Error as e:
                        print(f"An error occurred: {e}")
            print("Data inserted successfully")

            # Commit the changes and close the connection
            conn.commit()
            print("Changes committed")
        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            if conn:
                conn.close()
                print("Connection closed")

    # function that migrates the data from Users.json to the database table 'users'
    @staticmethod
    def migrate_users():
        try:
            # Get the current directory of the script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            json_path = os.path.join(script_dir, "../Data/Users.json")
            db_path = os.path.join(script_dir, "../database.db")

            # Connect to SQLite database
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Open and read the JSON file
            with open(json_path, "r", encoding='utf-8') as json_file:
                users_data = json.load(json_file)

            # Insert the data into the 'users' table
            for username, events in users_data.items():
                for event_data in events:
                    event = event_data['event']
                    sound = event_data['sound']
                    print(f"Inserting data: {username} - {event} - {sound}")
                    try:
                        cursor.execute("""
                        INSERT INTO users (id, event, sound)
                        VALUES (?, ?, ?)
                        """, (username, event, sound))
                    except sqlite3.Error as e:
                        print(f"An error occurred: {e}")

            print("Data inserted successfully")

            # Commit the changes and close the connection
            conn.commit()
            print("Changes committed")
        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            if conn:
                conn.close()
                print("Connection closed")


#create db and migrate
""" Database.create_database()
Migrate.migrate_sounds()
Migrate.migrate_play_history()
Migrate.migrate_other_actions()
Migrate.migrate_users() """
