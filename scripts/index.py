"""
One-time codebase indexer. Run this whenever your codebase changes significantly.

Usage:
    uv run python scripts/index.py           # Index current workspace
    uv run python scripts/index.py --clear   # Clear index and re-index
    uv run python scripts/index.py --stats   # Show current index stats
"""
import sys
import time
from agent.rag import index_codebase, index_stats, clear_index, WORKSPACE


def main():
    args = sys.argv[1:]

    if "--stats" in args:
        stats = index_stats()
        print(f"📊 Index stats:")
        print(f"   Total chunks: {stats['total_chunks']}")
        print(f"   Location:     {stats['index_path']}")
        return

    if "--clear" in args:
        print("🗑️  Clearing index...")
        print(clear_index())

    print(f"🔍 Indexing codebase: {WORKSPACE}")
    print(f"   (This may take 30-60 seconds for ~50 files)\n")

    start = time.time()
    stats = index_codebase(verbose=True)
    elapsed = time.time() - start

    print(f"\n✅ Indexing complete in {elapsed:.1f}s")
    print(f"   Files scanned: {stats['files_scanned']}")
    print(f"   Files indexed: {stats['files_indexed']}")
    print(f"   Chunks added:  {stats['chunks_added']}")
    print(f"   Skipped:       {stats['skipped']}")


if __name__ == "__main__":
    main()
