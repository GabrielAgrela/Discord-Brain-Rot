"""
Base repository class providing common database operations.
"""

from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Optional, List, Any
import sqlite3
import os

T = TypeVar('T')


class BaseRepository(ABC, Generic[T]):
    """
    Abstract base class for all repositories.
    
    Provides common database connection handling and defines
    the interface that all repositories must implement.
    
    This follows the Repository Pattern, which:
    - Centralizes data access logic
    - Provides a collection-like interface for entities
    - Enables swapping storage backends (e.g., for testing)
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the repository with a database path.
        
        Args:
            db_path: Path to SQLite database. If None, uses default.
        """
        if db_path is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(script_dir))
            db_path = os.path.join(project_root, "database.db")
        self._db_path = db_path
    
    @property
    def db_path(self) -> str:
        """Get the database path."""
        return self._db_path
    
    def _get_connection(self) -> sqlite3.Connection:
        """
        Create a new database connection.
        
        Note: Connections should be short-lived and closed after use.
        """
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _execute(self, query: str, params: tuple = ()) -> List[sqlite3.Row]:
        """
        Execute a query and return all results.
        
        Args:
            query: SQL query string
            params: Query parameters
            
        Returns:
            List of Row objects
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
        finally:
            conn.close()
    
    def _execute_one(self, query: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        """
        Execute a query and return the first result.
        
        Args:
            query: SQL query string
            params: Query parameters
            
        Returns:
            Single Row or None
        """
        results = self._execute(query, params)
        return results[0] if results else None
    
    def _execute_write(self, query: str, params: tuple = ()) -> int:
        """
        Execute a write query (INSERT, UPDATE, DELETE).
        
        Args:
            query: SQL query string
            params: Query parameters
            
        Returns:
            Last row ID for INSERT, or rows affected for UPDATE/DELETE
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()
    
    def _execute_many(self, query: str, params_list: List[tuple]) -> int:
        """
        Execute a query multiple times with different parameters.
        
        Args:
            query: SQL query string  
            params_list: List of parameter tuples
            
        Returns:
            Number of rows affected
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
    
    # Abstract methods that subclasses must implement
    
    @abstractmethod
    def get_by_id(self, id: int) -> Optional[T]:
        """Get an entity by its ID."""
        pass
    
    @abstractmethod
    def get_all(self, limit: int = 100) -> List[T]:
        """Get all entities, with optional limit."""
        pass
    
    @abstractmethod
    def _row_to_entity(self, row: sqlite3.Row) -> T:
        """Convert a database row to an entity object."""
        pass
