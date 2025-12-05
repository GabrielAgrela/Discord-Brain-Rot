import sqlite3
import os
import time
from fuzzywuzzy import fuzz
from src.common.config import Config
import datetime

class Database:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Database, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.db_path = Config.DB_PATH
        # Check if DB exists, if not maybe create it?
        # For now we assume it exists or will be created by legacy migration logic if we keep it.

    def get_connection(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def execute_query(self, query, params=()):
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            conn.commit()
            return cursor
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            raise
        finally:
            # We return cursor, so we can't close connection here if we want to fetch result from cursor later?
            # Standard practice with sqlite3 is fetching all results then closing.
            # Or returning context manager.
            pass

    def fetch_all(self, query, params=()):
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            return cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return []
        finally:
            conn.close()

    def fetch_one(self, query, params=()):
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            return cursor.fetchone()
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return None
        finally:
            conn.close()

    def execute_update(self, query, params=()):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return None
        finally:
            conn.close()

    # --- Specific Methods (Ported from legacy) ---

    def insert_action(self, username, action, target):
        username = username.split("#")[0]
        self.execute_update(
            "INSERT INTO actions (username, action, target) VALUES (?, ?, ?);",
            (username, action, target)
        )

    def get_sound(self, sound_filename, original_filename=False):
        if original_filename:
            return self.fetch_one("SELECT * FROM sounds WHERE originalfilename = ?;", (sound_filename,))
        else:
            return self.fetch_one("SELECT * FROM sounds WHERE Filename = ?;", (sound_filename,))

    def get_sounds(self, favorite=None, blacklist=None, slap=None, num_sounds=25, sort="DESC"):
        favorite = 1 if favorite else 0
        blacklist = 1 if blacklist else 0
        slap = 1 if slap else 0

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
                 # If asking for slap, ignore other filters? Original code did this
                 conditions = ["slap = ?"]
                 params = [slap]
             else:
                 conditions.append("slap = ?")
                 params.append(slap)

        query = "SELECT * FROM sounds"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += f" ORDER BY id {sort} LIMIT ?"
        params.append(num_sounds)

        return self.fetch_all(query, tuple(params))

    def get_random_sounds(self, num_sounds=1):
         return self.fetch_all("SELECT * FROM sounds WHERE blacklist = 0 ORDER BY RANDOM() LIMIT ?;", (num_sounds,))

    def get_all_users(self):
        rows = self.fetch_all("SELECT DISTINCT id FROM users;")
        return [row['id'] for row in rows]

    def get_user_events(self, user, event):
        if user == "*":
             return self.fetch_all("SELECT DISTINCT id FROM users WHERE event = ?;", (event,))
        else:
             return self.fetch_all("SELECT * FROM users WHERE id = ? AND event = ?;", (user, event))

    def insert_user_event_sound(self, user_id, event, sound):
        return self.execute_update("INSERT INTO users (id, event, sound) VALUES (?, ?, ?);", (user_id, event, sound))

    def normalize_text(self, text):
        substitutions = {
            '0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's',
            '7': 't', '@': 'a', '$': 's', '!': 'i'
        }
        for key, value in substitutions.items():
            text = text.replace(key, value)
        return text.lower()

    def get_sounds_by_similarity_optimized(self, req_sound, num_results=5):
        normalized_req = self.normalize_text(req_sound)
        search_words = normalized_req.replace('-', ' ').split()

        like_conditions = []
        params = []

        # (Simplified logic from legacy for brevity, but retaining core intent)
        for word in search_words:
             like_conditions.append("LOWER(Filename) LIKE ?")
             params.append(f"%{word}%")

        like_conditions.append("LOWER(Filename) LIKE ?")
        params.append(f"%{normalized_req.replace(' ', '%')}%")

        query = f"""
            SELECT * FROM sounds
            WHERE blacklist = 0
            AND ({" OR ".join(like_conditions)})
            LIMIT 150
        """

        potential_matches = self.fetch_all(query, tuple(params))
        if not potential_matches:
            return []

        scored_matches = []
        for sound in potential_matches:
            filename = sound['Filename']
            normalized_filename = self.normalize_text(filename)

            token_set_score = fuzz.token_set_ratio(normalized_req, normalized_filename)
            partial_ratio_score = fuzz.partial_ratio(normalized_req, normalized_filename)
            token_sort_score = fuzz.token_sort_ratio(normalized_req, normalized_filename)

            all_words_present = all(word in normalized_filename for word in search_words)
            word_presence_bonus = 20 if all_words_present else 0

            combined_score = (0.5 * token_set_score) + (0.3 * partial_ratio_score) + (0.2 * token_sort_score) + word_presence_bonus
            scored_matches.append((combined_score, sound))

        scored_matches.sort(key=lambda x: x[0], reverse=True)
        # Return tuples/rows to be compatible with legacy expectation if needed,
        # but rows are better. Legacy returned list of sound data (tuples/rows).
        return [match[1] for match in scored_matches[:num_results]]

    def get_sounds_by_similarity(self, req_sound, num_results=5):
        # Fallback to optimized
        return self.get_sounds_by_similarity_optimized(req_sound, num_results)

    # ... Add other methods as I discover they are needed by cogs ...

    def get_list_by_name(self, list_name, creator=None):
        if creator:
             return self.fetch_one("SELECT * FROM sound_lists WHERE list_name = ? AND creator = ?", (list_name, creator))
        else:
             return self.fetch_one("SELECT * FROM sound_lists WHERE list_name = ?", (list_name,))

    def create_sound_list(self, list_name, creator):
        return self.execute_update("INSERT INTO sound_lists (list_name, creator) VALUES (?, ?)", (list_name, creator))

    def get_sound_lists(self, creator=None):
        if creator:
            return self.fetch_all(
                """
                SELECT sl.id, sl.list_name, sl.creator, sl.created_at, COUNT(sli.id) as sound_count
                FROM sound_lists sl
                LEFT JOIN sound_list_items sli ON sl.id = sli.list_id
                WHERE sl.creator = ?
                GROUP BY sl.id
                ORDER BY sound_count DESC
                """, (creator,)
            )
        else:
             return self.fetch_all(
                """
                SELECT sl.id, sl.list_name, sl.creator, sl.created_at, COUNT(sli.id) as sound_count
                FROM sound_lists sl
                LEFT JOIN sound_list_items sli ON sl.id = sli.list_id
                GROUP BY sl.id
                ORDER BY sound_count DESC
                """
            )

    def add_sound_to_list(self, list_id, sound_filename):
        # Check sound existence (assuming Filename match or originalfilename match logic from legacy)
        sound = self.fetch_one("SELECT filename FROM sounds WHERE originalfilename = ? OR Filename = ?", (sound_filename, sound_filename))
        if not sound:
            return False, "Sound not found"

        existing = self.fetch_one("SELECT id FROM sound_list_items WHERE list_id = ? AND sound_filename = ?", (list_id, sound_filename))
        if existing:
            return False, "Sound already in list"

        self.execute_update("INSERT INTO sound_list_items (list_id, sound_filename) VALUES (?, ?)", (list_id, sound_filename))
        return True, "Sound added to list"

    def remove_sound_from_list(self, list_id, sound_filename):
        self.execute_update("DELETE FROM sound_list_items WHERE list_id = ? AND sound_filename = ?", (list_id, sound_filename))
        return True

    def delete_sound_list(self, list_id):
        self.execute_update("DELETE FROM sound_list_items WHERE list_id = ?", (list_id,))
        self.execute_update("DELETE FROM sound_lists WHERE id = ?", (list_id,))
        return True

    def get_sounds_in_list(self, list_id):
        return self.fetch_all(
            """
            SELECT s.filename, s.originalfilename
            FROM sound_list_items sli
            JOIN sounds s ON sli.sound_filename = s.filename
            WHERE sli.list_id = ?
            ORDER BY sli.added_at
            """, (list_id,)
        )
