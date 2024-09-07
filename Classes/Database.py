import sqlite3
import os
import csv
import json

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

            # SQL command to create 'sounds' table if it doesn't exist
            create_sounds_table = '''
            CREATE TABLE IF NOT EXISTS sounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                originalfilename TEXT NOT NULL,
                Filename TEXT NOT NULL,
                favorite BOOLEAN NOT NULL CHECK (favorite IN (0, 1)),
                blacklist BOOLEAN NOT NULL CHECK (blacklist IN (0, 1))
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
            cursor.execute(create_actions_table)
            cursor.execute(create_sounds_table)
            cursor.execute(create_users_table)
            print("Tables created successfully")

            # Commit the changes and close the connection
            conn.commit()
            print("Changes committed")
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")
        finally:
            if conn:
                conn.close()
                print("Connection closed")

    def insert_action(self, username, action, target):
        try:
            self.cursor.execute("INSERT INTO actions (username, action, target) VALUES (?, ?, ?);", (username, action, target))
            self.conn.commit()
            print("Action inserted successfully")
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")

    def insert_sound(self, originalfilename, filename, favorite=0, blacklist=0):
        try:
            self.cursor.execute("INSERT INTO sounds (originalfilename, Filename, favorite, blacklist) VALUES (?, ?, ?, ?);", (originalfilename, filename, favorite, blacklist))
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

    def get_sounds_by_similarity(self, req_sound, num_results=1):
        # Split the input into individual words
        words = req_sound.split()
        
        # Build the SQL query with LIKE and SOUNDEX conditions
        conditions = " OR ".join([f"(Filename LIKE ? OR SOUNDEX(Filename) = SOUNDEX(?))" for _ in words])
        
        # Create the parameters for the LIKE and SOUNDEX queries (duplicate for both)
        params = [item for word in words for item in (f"%{word}%", word)]

        try:
            # Execute the query and count how many words match (either LIKE or SOUNDEX)
            query = f"""
                SELECT *, 
                    ({' + '.join([f"(Filename LIKE ? OR SOUNDEX(Filename) = SOUNDEX(?))" for _ in words])}) AS match_count
                FROM sounds 
                WHERE {conditions}
                ORDER BY match_count DESC
                LIMIT ?;
            """
            
            # Add the limit parameter at the end
            self.cursor.execute(query, (*params, *params, num_results))

            print("Sounds found successfully")
            return self.cursor.fetchall()

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

    def get_sounds(self, favorite=None, blacklist=None, num_sounds=25, sort="DESC"):
        # if favorite/blacklist is true then make it 1, else 0
        favorite = 1 if favorite else 0
        blacklist = 1 if blacklist else 0

        try:
            if favorite is not None and blacklist is not None:
                self.cursor.execute("SELECT * FROM sounds WHERE favorite = ? AND blacklist = ? ORDER BY id " + sort + " LIMIT ?;", (favorite, blacklist, num_sounds))
            elif favorite is not None:
                self.cursor.execute("SELECT * FROM sounds WHERE favorite = ? ORDER BY id " + sort + " LIMIT ?;", (favorite, num_sounds))
            elif blacklist is not None:
                self.cursor.execute("SELECT * FROM sounds WHERE blacklist = ? ORDER BY id " + sort + " LIMIT ?;", (blacklist, num_sounds))
            else:
                self.cursor.execute("SELECT * FROM sounds ORDER BY id " + sort + " LIMIT ?;", (num_sounds,))
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")

    def get_top_users(self, number=5, days=0, by="plays"):
        try:
            query = """
            SELECT username, COUNT(*) as count
            FROM actions
            WHERE action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 'play_request')
            """
            
            if days > 0:
                query += f" AND timestamp >= datetime('now', '-{days} days')"
            
            query += """
            GROUP BY username
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
            WHERE a.action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 'play_request')
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
        
        
        

    async def update_sound(self, filename, new_filename=None, favorite=None, blacklist=None):
        new_filename = new_filename + ".mp3"
        try:
            if new_filename:
                self.cursor.execute("UPDATE sounds SET Filename = ? WHERE Filename = ?;", (new_filename, filename))
            if favorite is not None:
                self.cursor.execute("UPDATE sounds SET favorite = ? WHERE Filename = ?;", (favorite, filename))
            if blacklist is not None:
                self.cursor.execute("UPDATE sounds SET blacklist = ? WHERE Filename = ?;", (blacklist, filename))
            self.conn.commit()
            await self.behavior.send_message(title=f"Modified {filename} to {new_filename}")
            print("Sound updated successfully")
        except sqlite3.Error as e:
            print(f"An error occurred: {e}")






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
