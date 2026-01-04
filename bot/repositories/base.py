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
    
    _shared_connection: Optional[sqlite3.Connection] = None
    _shared_db_path: Optional[str] = None
    
    @classmethod
    def set_shared_connection(cls, conn: sqlite3.Connection, db_path: str):
        """Set a shared connection for all repositories (from Database singleton)."""
        cls._shared_connection = conn
        cls._shared_db_path = db_path
    
    def __init__(self, db_path: Optional[str] = None, use_shared: bool = True):
        """
        Initialize the repository with a database path.
        
        Args:
            db_path: Path to SQLite database. If None, uses default.
            use_shared: If True and shared connection exists, use it.
        """
        self._use_shared = use_shared and BaseRepository._shared_connection is not None
        
        if db_path is None:
            if self._use_shared and BaseRepository._shared_db_path:
                db_path = BaseRepository._shared_db_path
            else:
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
        Get a database connection.
        
        If shared connection is available and enabled, returns it.
        Otherwise creates a new connection.
        """
        if self._use_shared and BaseRepository._shared_connection is not None:
            return BaseRepository._shared_connection
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
        if self._use_shared and BaseRepository._shared_connection is not None:
            cursor = BaseRepository._shared_connection.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
        
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
        if self._use_shared and BaseRepository._shared_connection is not None:
            cursor = BaseRepository._shared_connection.cursor()
            cursor.execute(query, params)
            BaseRepository._shared_connection.commit()
            return cursor.lastrowid
        
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
        if self._use_shared and BaseRepository._shared_connection is not None:
            cursor = BaseRepository._shared_connection.cursor()
            cursor.executemany(query, params_list)
            BaseRepository._shared_connection.commit()
            return cursor.rowcount
        
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
