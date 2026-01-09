"""
Embedding Repository - Database operations for audio embeddings.

Stores and retrieves audio embeddings for similarity search and clustering.
"""

import json
import sqlite3
import os
from typing import Optional, List, Tuple


class EmbeddingRepository:
    """Repository for managing audio embeddings in the database."""
    
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(script_dir))
            db_path = os.path.join(project_root, "database.db")
        
        self._db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._ensure_tables()
    
    def _ensure_tables(self):
        """Create embedding tables if they don't exist."""
        cursor = self.conn.cursor()
        
        # Table for storing embeddings
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sound_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sound_id INTEGER NOT NULL UNIQUE,
                filename TEXT NOT NULL,
                embedding BLOB NOT NULL,
                model_name TEXT NOT NULL DEFAULT 'openl3',
                embedding_dim INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sound_id) REFERENCES sounds(id)
            )
        ''')
        
        # Table for cluster assignments
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sound_clusters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sound_id INTEGER NOT NULL,
                cluster_id INTEGER NOT NULL,
                cluster_label TEXT,
                algorithm TEXT NOT NULL DEFAULT 'kmeans',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sound_id) REFERENCES sounds(id)
            )
        ''')
        
        # Index for faster lookups
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_embeddings_sound_id 
            ON sound_embeddings(sound_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_clusters_cluster_id 
            ON sound_clusters(cluster_id)
        ''')
        
        self.conn.commit()
    
    def save_embedding(self, sound_id: int, filename: str, embedding: bytes, 
                       model_name: str = 'openl3', embedding_dim: int = 512) -> bool:
        """Save an embedding for a sound. Returns True if successful."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO sound_embeddings 
                (sound_id, filename, embedding, model_name, embedding_dim)
                VALUES (?, ?, ?, ?, ?)
            ''', (sound_id, filename, embedding, model_name, embedding_dim))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"[EmbeddingRepository] Error saving embedding: {e}")
            return False
    
    def get_embedding(self, sound_id: int) -> Optional[Tuple[bytes, str, int]]:
        """Get embedding for a sound. Returns (embedding, model_name, dim) or None."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT embedding, model_name, embedding_dim 
                FROM sound_embeddings WHERE sound_id = ?
            ''', (sound_id,))
            return cursor.fetchone()
        except sqlite3.Error as e:
            print(f"[EmbeddingRepository] Error getting embedding: {e}")
            return None
    
    def has_embedding(self, sound_id: int) -> bool:
        """Check if a sound already has an embedding."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT 1 FROM sound_embeddings WHERE sound_id = ?', (sound_id,))
            return cursor.fetchone() is not None
        except sqlite3.Error:
            return False
    
    def get_all_embeddings(self) -> List[Tuple[int, str, bytes]]:
        """Get all embeddings for clustering. Returns [(sound_id, filename, embedding), ...]"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT sound_id, filename, embedding FROM sound_embeddings')
            return cursor.fetchall()
        except sqlite3.Error as e:
            print(f"[EmbeddingRepository] Error getting all embeddings: {e}")
            return []
    
    def get_processed_count(self) -> int:
        """Get count of sounds that have embeddings."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM sound_embeddings')
            return cursor.fetchone()[0]
        except sqlite3.Error:
            return 0
    
    def save_cluster_labels(self, assignments: List[Tuple[int, int, str]], algorithm: str = 'kmeans'):
        """Save cluster assignments. assignments = [(sound_id, cluster_id, label), ...]"""
        try:
            cursor = self.conn.cursor()
            # Clear old clusters for this algorithm
            cursor.execute('DELETE FROM sound_clusters WHERE algorithm = ?', (algorithm,))
            
            cursor.executemany('''
                INSERT INTO sound_clusters (sound_id, cluster_id, cluster_label, algorithm)
                VALUES (?, ?, ?, ?)
            ''', [(sid, cid, label, algorithm) for sid, cid, label in assignments])
            
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"[EmbeddingRepository] Error saving clusters: {e}")
            return False
    
    def get_cluster(self, cluster_id: int) -> List[Tuple[int, str]]:
        """Get all sounds in a cluster. Returns [(sound_id, filename), ...]"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT sc.sound_id, se.filename 
                FROM sound_clusters sc
                JOIN sound_embeddings se ON sc.sound_id = se.sound_id
                WHERE sc.cluster_id = ?
            ''', (cluster_id,))
            return cursor.fetchall()
        except sqlite3.Error as e:
            print(f"[EmbeddingRepository] Error getting cluster: {e}")
            return []
    
    def get_cluster_for_sound(self, sound_id: int) -> Optional[Tuple[int, str]]:
        """Get cluster assignment for a sound. Returns (cluster_id, label) or None."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT cluster_id, cluster_label FROM sound_clusters WHERE sound_id = ?
            ''', (sound_id,))
            return cursor.fetchone()
        except sqlite3.Error:
            return None
    
    def get_cluster_summary(self) -> List[Tuple[int, str, int]]:
        """Get summary of all clusters. Returns [(cluster_id, label, count), ...]"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT cluster_id, cluster_label, COUNT(*) as count
                FROM sound_clusters
                GROUP BY cluster_id
                ORDER BY count DESC
            ''')
            return cursor.fetchall()
        except sqlite3.Error as e:
            print(f"[EmbeddingRepository] Error getting cluster summary: {e}")
            return []
