"""
Tests for bot/repositories/list.py - ListRepository.
"""

import pytest


class TestListRepository:
    """Tests for the ListRepository class."""
    
    def test_create_list(self, list_repository, db_connection):
        """Test creating a new sound list."""
        list_id = list_repository.create(name="favorites", creator="testuser")
        
        assert list_id is not None
        assert list_id > 0
        
        cursor = db_connection.cursor()
        cursor.execute("SELECT * FROM sound_lists WHERE id = ?", (list_id,))
        row = cursor.fetchone()
        assert row["list_name"] == "favorites"
        assert row["creator"] == "testuser"
    
    def test_get_by_id(self, list_repository):
        """Test getting a list by ID."""
        list_id = list_repository.create("mylist", "user1")
        
        result = list_repository.get_by_id(list_id)
        assert result is not None
        assert result[0] == list_id
        assert result[1] == "mylist"
        assert result[2] == "user1"
    
    def test_get_by_id_not_found(self, list_repository):
        """Test getting a non-existent list."""
        result = list_repository.get_by_id(9999)
        assert result is None
    
    def test_get_by_name(self, list_repository):
        """Test getting a list by name."""
        list_repository.create("findbyname", "creator")
        
        result = list_repository.get_by_name("findbyname")
        assert result is not None
        assert result[1] == "findbyname"
    
    def test_get_by_name_with_creator(self, list_repository):
        """Test getting a list by name and creator."""
        list_repository.create("samename", "user1")
        list_repository.create("samename", "user2")
        
        result = list_repository.get_by_name("samename", creator="user2")
        assert result is not None
        assert result[2] == "user2"
    
    def test_get_all(self, list_repository):
        """Test getting all lists."""
        list_repository.create("list1", "user1")
        list_repository.create("list2", "user2")
        list_repository.create("list3", "user1")
        
        all_lists = list_repository.get_all()
        assert len(all_lists) == 3
    
    def test_get_all_by_creator(self, list_repository):
        """Test getting all lists filtered by creator."""
        list_repository.create("a", "targetuser")
        list_repository.create("b", "targetuser")
        list_repository.create("c", "otheruser")
        
        user_lists = list_repository.get_all(creator="targetuser")
        assert len(user_lists) == 2
        for lst in user_lists:
            assert lst[2] == "targetuser"
    
    def test_delete(self, list_repository, db_connection):
        """Test deleting a list."""
        list_id = list_repository.create("deleteme", "user")
        
        result = list_repository.delete(list_id)
        assert result is True
        
        cursor = db_connection.cursor()
        cursor.execute("SELECT * FROM sound_lists WHERE id = ?", (list_id,))
        assert cursor.fetchone() is None
    
    def test_add_sound(self, list_repository, db_connection, sample_sounds):
        """Test adding a sound to a list."""
        list_id = list_repository.create("withsounds", "user")
        
        result = list_repository.add_sound(list_id, "sound1.mp3")
        assert result is True
        
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT * FROM sound_list_items WHERE list_id = ? AND sound_filename = ?",
            (list_id, "sound1.mp3")
        )
        assert cursor.fetchone() is not None
    
    def test_add_sound_duplicate(self, list_repository, sample_sounds):
        """Test adding duplicate sound returns False."""
        list_id = list_repository.create("duptest", "user")
        
        list_repository.add_sound(list_id, "sound1.mp3")
        result = list_repository.add_sound(list_id, "sound1.mp3")
        
        assert result is False
    
    def test_remove_sound(self, list_repository, db_connection, sample_sounds):
        """Test removing a sound from a list."""
        list_id = list_repository.create("removetest", "user")
        list_repository.add_sound(list_id, "sound1.mp3")
        
        result = list_repository.remove_sound(list_id, "sound1.mp3")
        assert result is True
        
        cursor = db_connection.cursor()
        cursor.execute(
            "SELECT * FROM sound_list_items WHERE list_id = ? AND sound_filename = ?",
            (list_id, "sound1.mp3")
        )
        assert cursor.fetchone() is None
    
    def test_get_sounds_in_list(self, list_repository, sample_sounds):
        """Test getting all sounds in a list."""
        list_id = list_repository.create("fulllist", "user")
        list_repository.add_sound(list_id, "sound1.mp3")
        list_repository.add_sound(list_id, "sound2.mp3")
        
        sounds = list_repository.get_sounds_in_list(list_id)
        
        assert len(sounds) == 2
    
    def test_get_lists_containing_sound(self, list_repository, sample_sounds):
        """Test finding all lists that contain a sound."""
        list1 = list_repository.create("list1", "user")
        list2 = list_repository.create("list2", "user")
        list3 = list_repository.create("list3", "user")
        
        list_repository.add_sound(list1, "sound1.mp3")
        list_repository.add_sound(list2, "sound1.mp3")
        # list3 doesn't have sound1
        
        lists = list_repository.get_lists_containing_sound("sound1.mp3")
        
        assert len(lists) == 2
        list_ids = [l[0] for l in lists]
        assert list1 in list_ids
        assert list2 in list_ids
        assert list3 not in list_ids
    
    def test_get_random_sound_from_list(self, list_repository, sample_sounds):
        """Test getting a random sound from a list."""
        list_id = list_repository.create("randomlist", "user")
        list_repository.add_sound(list_id, "sound1.mp3")
        list_repository.add_sound(list_id, "sound2.mp3")
        
        sound = list_repository.get_random_sound_from_list("randomlist")
        
        assert sound is not None
        assert sound[2] in ["sound1.mp3", "sound2.mp3"]  # Filename is third column

    def test_get_by_name_case_insensitive(self, list_repository):
        """get_by_name should match list names case-insensitively."""
        list_repository.create("CaseList", "creator")

        result_lower = list_repository.get_by_name("caselist")
        assert result_lower is not None
        assert result_lower[1] == "CaseList"  # Returns stored canonical name

        result_upper = list_repository.get_by_name("CASELIST")
        assert result_upper is not None
        assert result_upper[1] == "CaseList"

        result_mixed = list_repository.get_by_name("cAsElIsT")
        assert result_mixed is not None
        assert result_mixed[1] == "CaseList"

    def test_get_by_name_case_insensitive_not_found(self, list_repository):
        """Non-matching case-insensitive query should return None."""
        list_repository.create("existinglist", "creator")
        result = list_repository.get_by_name("nonexistent")
        assert result is None

    def test_get_by_name_case_insensitive_with_creator(self, list_repository):
        """get_by_name with creator should match list names case-insensitively."""
        list_repository.create("MyList", "user1")
        list_repository.create("MyList", "user2")

        result = list_repository.get_by_name("mylist", creator="user2")
        assert result is not None
        assert result[1] == "MyList"
        assert result[2] == "user2"

        result = list_repository.get_by_name("MYLIST", creator="user1")
        assert result is not None
        assert result[1] == "MyList"
        assert result[2] == "user1"

    def test_get_random_sound_from_list_case_insensitive(self, list_repository, sample_sounds):
        """get_random_sound_from_list should match list names case-insensitively."""
        list_id = list_repository.create("RandomList", "user")
        list_repository.add_sound(list_id, "sound1.mp3")

        sound_lower = list_repository.get_random_sound_from_list("randomlist")
        assert sound_lower is not None
        assert sound_lower[2] == "sound1.mp3"

        sound_upper = list_repository.get_random_sound_from_list("RANDOMLIST")
        assert sound_upper is not None
        assert sound_upper[2] == "sound1.mp3"


class TestListRepositoryEdgeCases:
    """Edge case tests for ListRepository."""
    
    def test_get_all_empty(self, list_repository):
        """Test get_all on empty database."""
        lists = list_repository.get_all()
        assert lists == []
    
    def test_get_sounds_in_empty_list(self, list_repository):
        """Test getting sounds from an empty list."""
        list_id = list_repository.create("emptylist", "user")
        sounds = list_repository.get_sounds_in_list(list_id)
        assert sounds == []
    
    def test_get_random_from_empty_list(self, list_repository):
        """Test getting random sound from empty list."""
        list_repository.create("emptylist2", "user")
        sound = list_repository.get_random_sound_from_list("emptylist2")
        assert sound is None
