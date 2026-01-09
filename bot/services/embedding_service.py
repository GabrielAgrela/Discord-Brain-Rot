"""
Embedding Service - Audio embedding generation and similarity search.

Uses openL3 for audio embeddings (deep learning based, semantic understanding).
"""

import os
import numpy as np
from typing import Optional, List, Tuple


def _load_audio_pydub(file_path: str, sr: int = 48000) -> Tuple[Optional[np.ndarray], int]:
    """Load audio file using pydub."""
    try:
        from pydub import AudioSegment
        
        # Load audio with pydub
        audio_segment = AudioSegment.from_file(file_path)
        
        # Convert to mono if stereo
        if audio_segment.channels > 1:
            audio_segment = audio_segment.set_channels(1)
        
        # Resample to target sample rate
        audio_segment = audio_segment.set_frame_rate(sr)
        
        # Convert to numpy array
        samples = np.array(audio_segment.get_array_of_samples(), dtype=np.float32)
        
        # Normalize to [-1, 1] range
        max_val = np.iinfo(np.int16).max
        samples = samples / max_val
        
        return samples, sr
    except Exception as e:
        print(f"[EmbeddingService] Error loading {file_path}: {e}")
        return None, sr


# Lazy load openL3 model
_openl3_model = None

def _get_openl3():
    """Lazy load openL3 to avoid slow startup."""
    global _openl3_model
    if _openl3_model is None:
        import openl3
        _openl3_model = openl3
    return _openl3_model


class EmbeddingService:
    """Service for generating and managing audio embeddings using openL3."""
    
    def __init__(self, sounds_dir: str = None):
        """Initialize the embedding service."""
        if sounds_dir is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            self.sounds_dir = os.path.join(script_dir, "..", "..", "Sounds")
        else:
            self.sounds_dir = sounds_dir
        
        self.sounds_dir = os.path.abspath(self.sounds_dir)
        self._embedding_dim = 512  # openL3 512-dim embeddings
        
    def generate_embedding(self, file_path: str) -> Optional[np.ndarray]:
        """Generate openL3 embedding for an audio file."""
        try:
            openl3 = _get_openl3()
            
            # Load audio
            audio, sr = _load_audio_pydub(file_path, sr=48000)
            if audio is None or len(audio) == 0:
                return None
            
            # Generate embedding (content_type='env' for environmental sounds/effects)
            embedding, _ = openl3.get_audio_embedding(
                audio, sr,
                content_type='env',  # Better for sound effects
                embedding_size=512,
                hop_size=0.5
            )
            
            # Average over time frames to get single vector
            if len(embedding.shape) > 1:
                embedding = np.mean(embedding, axis=0)
            
            return embedding.astype(np.float32)
            
        except Exception as e:
            print(f"[EmbeddingService] Error generating embedding for {file_path}: {e}")
            return None
    
    @property
    def embedding_dim(self) -> int:
        """Get the embedding dimension."""
        return self._embedding_dim
    
    def embedding_to_bytes(self, embedding: np.ndarray) -> bytes:
        """Convert numpy embedding to bytes for database storage."""
        return embedding.tobytes()
    
    def bytes_to_embedding(self, data: bytes, dim: int = None) -> np.ndarray:
        """Convert bytes back to numpy embedding."""
        if dim is None:
            dim = self._embedding_dim
        return np.frombuffer(data, dtype=np.float32).reshape(dim)
    
    def cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Calculate cosine similarity between two embeddings."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
    
    def find_similar(self, query_embedding: np.ndarray, 
                     all_embeddings: List[Tuple[int, str, bytes]], 
                     top_k: int = 5) -> List[Tuple[int, str, float]]:
        """Find most similar sounds to a query embedding."""
        similarities = []
        
        for sound_id, filename, emb_bytes in all_embeddings:
            emb = self.bytes_to_embedding(emb_bytes)
            sim = self.cosine_similarity(query_embedding, emb)
            similarities.append((sound_id, filename, sim))
        
        similarities.sort(key=lambda x: x[2], reverse=True)
        return similarities[:top_k]
    
    def cluster_embeddings(self, embeddings: List[Tuple[int, str, bytes]], 
                           n_clusters: int = 50) -> List[Tuple[int, int]]:
        """Cluster embeddings using K-means."""
        from sklearn.cluster import KMeans
        
        sound_ids = []
        emb_matrix = []
        
        for sound_id, filename, emb_bytes in embeddings:
            sound_ids.append(sound_id)
            emb_matrix.append(self.bytes_to_embedding(emb_bytes))
        
        X = np.array(emb_matrix)
        
        # Adjust n_clusters if needed
        n_clusters = min(n_clusters, len(X))
        
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(X)
        
        return list(zip(sound_ids, labels.tolist()))
    
    def get_all_sound_files(self) -> List[Tuple[str, str]]:
        """Get all sound files from the Sounds directory."""
        sound_files = []
        
        for entry in os.listdir(self.sounds_dir):
            full_path = os.path.join(self.sounds_dir, entry)
            if os.path.isfile(full_path) and entry.lower().endswith('.mp3'):
                sound_files.append((entry, full_path))
        
        return sound_files
