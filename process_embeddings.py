#!/usr/bin/env python3
"""
Audio Embedding Processing Script

Standalone CLI tool for generating embeddings and clustering sounds.

Usage:
    python process_embeddings.py --generate              # Generate embeddings for all sounds
    python process_embeddings.py --generate --limit 100  # Test with 100 sounds
    python process_embeddings.py --cluster --n-clusters 50  # Cluster existing embeddings
    python process_embeddings.py --similar "filename.mp3"   # Find similar sounds
    python process_embeddings.py --report                # Show cluster summary
"""

import argparse
import os
import sys

# Add project root to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from bot.services.embedding_service import EmbeddingService
from bot.repositories.embedding_repository import EmbeddingRepository
from bot.repositories.sound import SoundRepository


def generate_embeddings(limit: int = None, force: bool = False):
    """Generate embeddings for all sounds in the database."""
    print("[*] Starting embedding generation...")
    
    service = EmbeddingService()
    repo = EmbeddingRepository()
    sound_repo = SoundRepository()
    
    # Get all sounds from database
    sounds = sound_repo.get_sounds(num_sounds=100000)  # Get all
    total = len(sounds)
    
    if limit:
        sounds = sounds[:limit]
        print(f"[*] Processing {limit} of {total} sounds (limited)")
    else:
        print(f"[*] Processing all {total} sounds")
    
    processed = 0
    skipped = 0
    errors = 0
    
    for i, sound in enumerate(sounds):
        sound_id = sound[0]  # id
        filename = sound[2]  # Filename
        
        # Check if already processed
        if not force and repo.has_embedding(sound_id):
            skipped += 1
            continue
        
        # Build file path
        file_path = os.path.join(service.sounds_dir, filename)
        
        if not os.path.exists(file_path):
            print(f"[!] File not found: {filename}")
            errors += 1
            continue
        
        # Generate embedding
        embedding = service.generate_embedding(file_path)
        
        if embedding is not None:
            # Save to database
            emb_bytes = service.embedding_to_bytes(embedding)
            repo.save_embedding(sound_id, filename, emb_bytes, 'openl3', service.embedding_dim)
            processed += 1
            
            if processed % 50 == 0:
                print(f"[*] Progress: {processed} processed, {skipped} skipped, {errors} errors ({i+1}/{len(sounds)})")
        else:
            errors += 1
    
    print(f"\n[✓] Done! Processed: {processed}, Skipped: {skipped}, Errors: {errors}")
    return processed


def cluster_sounds(n_clusters: int = 50):
    """Cluster all sounds with embeddings."""
    print(f"[*] Clustering sounds into {n_clusters} clusters...")
    
    service = EmbeddingService()
    repo = EmbeddingRepository()
    
    # Get all embeddings
    embeddings = repo.get_all_embeddings()
    print(f"[*] Found {len(embeddings)} embeddings")
    
    if len(embeddings) < n_clusters:
        print(f"[!] Not enough embeddings ({len(embeddings)}) for {n_clusters} clusters")
        n_clusters = max(2, len(embeddings) // 10)
        print(f"[*] Adjusting to {n_clusters} clusters")
    
    # Run clustering
    assignments = service.cluster_embeddings(embeddings, n_clusters)
    
    # Save to database (with empty labels for now)
    labeled_assignments = [(sid, cid, f"Cluster {cid}") for sid, cid in assignments]
    repo.save_cluster_labels(labeled_assignments, 'kmeans')
    
    print(f"[✓] Clustering complete! {len(assignments)} sounds assigned to {n_clusters} clusters")
    
    # Print cluster sizes
    from collections import Counter
    cluster_sizes = Counter([cid for _, cid in assignments])
    print("\n[*] Cluster sizes:")
    for cid, count in cluster_sizes.most_common(10):
        print(f"    Cluster {cid}: {count} sounds")
    if len(cluster_sizes) > 10:
        print(f"    ... and {len(cluster_sizes) - 10} more clusters")


def find_similar(filename: str, top_k: int = 5):
    """Find sounds similar to the given filename."""
    print(f"[*] Finding sounds similar to: {filename}")
    
    service = EmbeddingService()
    repo = EmbeddingRepository()
    sound_repo = SoundRepository()
    
    # Find the sound in database
    sound = sound_repo.get_sound_by_name(filename)
    if not sound:
        print(f"[!] Sound not found in database: {filename}")
        return
    
    sound_id = sound[0]
    
    # Get its embedding
    emb_data = repo.get_embedding(sound_id)
    if not emb_data:
        print(f"[!] No embedding found for: {filename}")
        print("[*] Try running --generate first")
        return
    
    emb_bytes, model, dim = emb_data
    query_emb = service.bytes_to_embedding(emb_bytes, dim if dim else service.embedding_dim)
    
    # Get all embeddings
    all_embeddings = repo.get_all_embeddings()
    
    # Find similar (excluding self)
    all_embeddings = [(sid, fn, eb) for sid, fn, eb in all_embeddings if sid != sound_id]
    
    similar = service.find_similar(query_emb, all_embeddings, top_k)
    
    print(f"\n[✓] Top {len(similar)} similar sounds:")
    for i, (sid, fn, score) in enumerate(similar, 1):
        print(f"    {i}. {fn} (similarity: {score:.3f})")


def show_report():
    """Show cluster summary report."""
    print("[*] Cluster Summary Report\n")
    
    repo = EmbeddingRepository()
    
    # Stats
    processed = repo.get_processed_count()
    print(f"Total sounds with embeddings: {processed}")
    
    # Cluster summary
    summary = repo.get_cluster_summary()
    
    if not summary:
        print("\n[!] No clusters found. Run --cluster first.")
        return
    
    print(f"Total clusters: {len(summary)}\n")
    print("Top 20 clusters by size:")
    print("-" * 50)
    
    for cluster_id, label, count in summary[:20]:
        # Get sample sounds from cluster
        samples = repo.get_cluster(cluster_id)[:3]
        sample_names = [fn[:40] for _, fn in samples]
        
        print(f"\nCluster {cluster_id} ({count} sounds):")
        for name in sample_names:
            print(f"  - {name}")


def main():
    parser = argparse.ArgumentParser(description="Audio Embedding Processing Tool")
    
    parser.add_argument('--generate', action='store_true', 
                        help='Generate embeddings for all sounds')
    parser.add_argument('--cluster', action='store_true',
                        help='Cluster sounds by embedding similarity')
    parser.add_argument('--similar', type=str, metavar='FILENAME',
                        help='Find sounds similar to the given filename')
    parser.add_argument('--report', action='store_true',
                        help='Show cluster summary report')
    
    parser.add_argument('--limit', type=int, default=None,
                        help='Limit number of sounds to process (for testing)')
    parser.add_argument('--n-clusters', type=int, default=50,
                        help='Number of clusters for K-means (default: 50)')
    parser.add_argument('--top', type=int, default=5,
                        help='Number of similar sounds to show (default: 5)')
    parser.add_argument('--force', action='store_true',
                        help='Force regenerate embeddings even if they exist')
    
    args = parser.parse_args()
    
    if args.generate:
        generate_embeddings(limit=args.limit, force=args.force)
    elif args.cluster:
        cluster_sounds(n_clusters=args.n_clusters)
    elif args.similar:
        find_similar(args.similar, top_k=args.top)
    elif args.report:
        show_report()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
