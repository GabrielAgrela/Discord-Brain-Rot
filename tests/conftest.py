"""
Shared pytest fixtures for Discord Brain Rot tests.
"""

import pytest
import sqlite3
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================
# Database Fixtures
# ============================================================================

@pytest.fixture
def db_connection():
    """Create an in-memory SQLite database with the required schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Create sounds table
    cursor.execute("""
        CREATE TABLE sounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            originalfilename TEXT NOT NULL,
            Filename TEXT NOT NULL,
            date TEXT,
            favorite INTEGER DEFAULT 0,
            blacklist INTEGER DEFAULT 0,
            slap INTEGER DEFAULT 0,
            timestamp TEXT
        )
    """)
    
    # Create actions table
    cursor.execute("""
        CREATE TABLE actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT,
            timestamp TEXT
        )
    """)
    
    # Create users table (for user events)
    cursor.execute("""
        CREATE TABLE users (
            id TEXT NOT NULL,
            event TEXT NOT NULL,
            sound TEXT NOT NULL
        )
    """)
    
    # Create keywords table
    cursor.execute("""
        CREATE TABLE keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL UNIQUE,
            action_type TEXT NOT NULL,
            action_value TEXT DEFAULT ''
        )
    """)
    
    # Create sound_lists table
    cursor.execute("""
        CREATE TABLE sound_lists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            list_name TEXT NOT NULL,
            creator TEXT NOT NULL
        )
    """)
    
    # Create sound_list_items table
    cursor.execute("""
        CREATE TABLE sound_list_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            list_id INTEGER NOT NULL,
            sound_filename TEXT NOT NULL,
            added_at TEXT,
            FOREIGN KEY (list_id) REFERENCES sound_lists(id)
        )
    """)
    
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def sound_repository(db_connection):
    """Create a SoundRepository with the test database."""
    from bot.repositories.sound import SoundRepository
    from bot.repositories.base import BaseRepository
    
    # Set up shared connection
    BaseRepository.set_shared_connection(db_connection, ":memory:")
    
    repo = SoundRepository(use_shared=True)
    yield repo
    
    # Clean up shared connection
    BaseRepository._shared_connection = None
    BaseRepository._shared_db_path = None


@pytest.fixture
def action_repository(db_connection):
    """Create an ActionRepository with the test database."""
    from bot.repositories.action import ActionRepository
    from bot.repositories.base import BaseRepository
    
    BaseRepository.set_shared_connection(db_connection, ":memory:")
    
    repo = ActionRepository(use_shared=True)
    yield repo
    
    BaseRepository._shared_connection = None
    BaseRepository._shared_db_path = None


@pytest.fixture
def event_repository(db_connection):
    """Create an EventRepository with the test database."""
    from bot.repositories.event import EventRepository
    from bot.repositories.base import BaseRepository
    
    BaseRepository.set_shared_connection(db_connection, ":memory:")
    
    repo = EventRepository(use_shared=True)
    yield repo
    
    BaseRepository._shared_connection = None
    BaseRepository._shared_db_path = None


@pytest.fixture
def keyword_repository(db_connection):
    """Create a KeywordRepository with the test database."""
    from bot.repositories.keyword import KeywordRepository
    from bot.repositories.base import BaseRepository
    
    BaseRepository.set_shared_connection(db_connection, ":memory:")
    
    repo = KeywordRepository(use_shared=True)
    yield repo
    
    BaseRepository._shared_connection = None
    BaseRepository._shared_db_path = None


@pytest.fixture
def list_repository(db_connection):
    """Create a ListRepository with the test database."""
    from bot.repositories.list import ListRepository
    from bot.repositories.base import BaseRepository
    
    BaseRepository.set_shared_connection(db_connection, ":memory:")
    
    repo = ListRepository(use_shared=True)
    yield repo
    
    BaseRepository._shared_connection = None
    BaseRepository._shared_db_path = None


@pytest.fixture
def stats_repository(db_connection):
    """Create a StatsRepository with the test database."""
    from bot.repositories.stats import StatsRepository
    from bot.repositories.base import BaseRepository
    
    BaseRepository.set_shared_connection(db_connection, ":memory:")
    
    repo = StatsRepository(use_shared=True)
    yield repo
    
    BaseRepository._shared_connection = None
    BaseRepository._shared_db_path = None


# ============================================================================
# Sample Data Fixtures
# ============================================================================

@pytest.fixture
def sample_sound_data():
    """Return sample sound data for testing."""
    return {
        "original_filename": "test_sound.mp3",
        "filename": "test_sound.mp3",
        "favorite": 0,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@pytest.fixture
def sample_sounds(db_connection):
    """Insert sample sounds into the database and return their IDs."""
    cursor = db_connection.cursor()
    sounds = [
        ("original1.mp3", "sound1.mp3", "2024-01-01 10:00:00", 1, 0, 0, "2024-01-01 10:00:00"),
        ("original2.mp3", "sound2.mp3", "2024-01-02 11:00:00", 0, 0, 0, "2024-01-02 11:00:00"),
        ("original3.mp3", "sound3.mp3", "2024-01-03 12:00:00", 0, 0, 1, "2024-01-03 12:00:00"),
        ("slap1.mp3", "slap_sound.mp3", "2024-01-04 13:00:00", 0, 0, 1, "2024-01-04 13:00:00"),
    ]
    
    ids = []
    for sound in sounds:
        cursor.execute(
            "INSERT INTO sounds (originalfilename, Filename, date, favorite, blacklist, slap, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            sound
        )
        ids.append(cursor.lastrowid)
    
    db_connection.commit()
    return ids


@pytest.fixture
def sample_actions(db_connection, sample_sounds):
    """Insert sample actions into the database."""
    cursor = db_connection.cursor()
    actions = [
        ("user1", "play_random_sound", str(sample_sounds[0]), "2024-01-01 10:00:00"),
        ("user1", "play_random_sound", str(sample_sounds[0]), "2024-01-01 11:00:00"),
        ("user2", "play_request", str(sample_sounds[1]), "2024-01-02 10:00:00"),
        ("user1", "favorite_sound", str(sample_sounds[0]), "2024-01-01 12:00:00"),
        ("user2", "favorite_sound", str(sample_sounds[0]), "2024-01-02 11:00:00"),
    ]
    
    for action in actions:
        cursor.execute(
            "INSERT INTO actions (username, action, target, timestamp) VALUES (?, ?, ?, ?)",
            action
        )
    
    db_connection.commit()
    return sample_sounds
