"""
Tests for bot/repositories/keyword.py - KeywordRepository.
"""

import pytest


class TestKeywordRepository:
    """Tests for the KeywordRepository class."""
    
    def test_add_keyword(self, keyword_repository, db_connection):
        """Test adding a new keyword."""
        result = keyword_repository.add(
            keyword="test",
            action_type="slap",
            action_value=""
        )
        
        assert result is True
        
        cursor = db_connection.cursor()
        cursor.execute("SELECT * FROM keywords WHERE keyword = ?", ("test",))
        row = cursor.fetchone()
        assert row is not None
        assert row["action_type"] == "slap"
    
    def test_add_keyword_with_list(self, keyword_repository):
        """Test adding a keyword linked to a list."""
        result = keyword_repository.add(
            keyword="mylist",
            action_type="list",
            action_value="favorites"
        )
        
        assert result is True
        
        keyword = keyword_repository.get_by_keyword("mylist")
        assert keyword["action_type"] == "list"
        assert keyword["action_value"] == "favorites"
    
    def test_add_keyword_lowercase(self, keyword_repository):
        """Test that keywords are stored lowercase."""
        keyword_repository.add("UPPERCASE", "slap")
        
        keyword = keyword_repository.get_by_keyword("uppercase")
        assert keyword is not None
    
    def test_get_by_keyword(self, keyword_repository):
        """Test getting a keyword by name."""
        keyword_repository.add("findme", "slap")
        
        keyword = keyword_repository.get_by_keyword("findme")
        assert keyword is not None
        assert keyword["keyword"] == "findme"
    
    def test_get_by_keyword_not_found(self, keyword_repository):
        """Test getting a non-existent keyword."""
        keyword = keyword_repository.get_by_keyword("nonexistent")
        assert keyword is None
    
    def test_get_by_id(self, keyword_repository, db_connection):
        """Test getting a keyword by ID."""
        keyword_repository.add("byid", "slap")
        
        cursor = db_connection.cursor()
        cursor.execute("SELECT id FROM keywords WHERE keyword = ?", ("byid",))
        row = cursor.fetchone()
        keyword_id = row["id"]
        
        keyword = keyword_repository.get_by_id(keyword_id)
        assert keyword is not None
        assert keyword["keyword"] == "byid"
    
    def test_get_all(self, keyword_repository):
        """Test getting all keywords."""
        keyword_repository.add("kw1", "slap")
        keyword_repository.add("kw2", "list", "mylist")
        keyword_repository.add("kw3", "slap")
        
        keywords = keyword_repository.get_all()
        assert len(keywords) == 3
    
    def test_get_as_dict(self, keyword_repository):
        """Test getting keywords as dictionary."""
        keyword_repository.add("slapword", "slap")
        keyword_repository.add("listword", "list", "mylist")
        
        kw_dict = keyword_repository.get_as_dict()
        
        assert kw_dict["slapword"] == "slap"
        assert kw_dict["listword"] == "list:mylist"
    
    def test_remove(self, keyword_repository, db_connection):
        """Test removing a keyword."""
        keyword_repository.add("removeme", "slap")
        
        result = keyword_repository.remove("removeme")
        assert result is True
        
        cursor = db_connection.cursor()
        cursor.execute("SELECT * FROM keywords WHERE keyword = ?", ("removeme",))
        assert cursor.fetchone() is None
    
    def test_add_or_replace(self, keyword_repository):
        """Test that add replaces existing keyword."""
        keyword_repository.add("replace", "slap")
        keyword_repository.add("replace", "list", "newlist")
        
        keyword = keyword_repository.get_by_keyword("replace")
        assert keyword["action_type"] == "list"
        assert keyword["action_value"] == "newlist"


class TestKeywordRepositoryEdgeCases:
    """Edge case tests for KeywordRepository."""
    
    def test_get_all_empty(self, keyword_repository):
        """Test get_all on empty database."""
        keywords = keyword_repository.get_all()
        assert keywords == []
    
    def test_get_as_dict_empty(self, keyword_repository):
        """Test get_as_dict on empty database."""
        kw_dict = keyword_repository.get_as_dict()
        assert kw_dict == {}
