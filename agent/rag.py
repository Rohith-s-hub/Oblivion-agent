"""
RAG (Retrieval Augmented Generation) for the AI agent.
Indexes the codebase and lets the agent search semantically.

Uses:
  - Ollama nomic-embed-text for embeddings (local, fast, parallel)
  - ChromaDB for vector storage (embedded, no server)
"""
import os
import hashlib
import asyncio
from pathlib import Path
from typing import Optional
import chromadb
from chromadb.config import Settings
import httpx
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
WORKSPACE = Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()
INDEX_DIR = Path.home() / ".ai-agent" / "chroma"
EMBED_MODEL = os.getenv("EMBED_MODEL", "all-minilm")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
PARALLEL_EMBEDDINGS = int(os.getenv("PARALLEL_EMBEDDINGS", "8"))

INDEX_DIR.mkdir(parents=True, exist_ok=True)

INDEXABLE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".vue",
    ".md", ".txt", ".yaml", ".yml", ".toml",
    ".html", ".css", ".json", ".sh", ".sql",
}

SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules", ".chroma",
    "dist", "build", "target", "out", ".next", ".nuxt",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "coverage", "htmlcov", ".coverage",
    ".idea", ".vscode", "__MACOSX",
    "logs", "tmp", "temp", "cache",
}

SKIP_FILE_PATTERNS = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock",
    "poetry.lock", "Cargo.lock", "Gemfile.lock", "composer.lock",
}

MAX_FILE_SIZE = 100_000


# ── Embeddings (single + batch) ───────────────────────────────────────────────
def get_embedding(text: str, max_retries: int = 2) -> list[float]:
    """Get embedding vector with retry + truncation on errors."""
    if len(text) > 25000:
        text = text[:25000]
    for attempt in range(max_retries + 1):
        try:
            response = httpx.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text},
                timeout=60,
            )
            response.raise_for_status()
            return response.json()["embedding"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 500 and attempt < max_retries:
                text = text[:len(text) // 2]
                continue
            if attempt == max_retries:
                return []
        except Exception:
            if attempt == max_retries:
                return []
    return []


def get_embeddings_parallel(texts: list[str], max_workers: int = None) -> list[list[float]]:
    """Get embeddings for multiple texts in parallel using a thread pool."""
    workers = max_workers or PARALLEL_EMBEDDINGS
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(get_embedding, texts))


# ── Chroma Setup ──────────────────────────────────────────────────────────────
_client = None
_collection = None


def get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(
            path=str(INDEX_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        _collection = _client.get_or_create_collection(
            name="codebase",
            metadata={"description": "Indexed code chunks", "hnsw:space": "cosine"},
        )
    return _collection


# ── Chunking ──────────────────────────────────────────────────────────────────
def chunk_file(content: str, filename: str, max_lines: int = 50) -> list[dict]:
    lines = content.splitlines()
    chunks = []
    overlap = 10

    i = 0
    while i < len(lines):
        chunk_lines = lines[i:i + max_lines]
        chunk_text = "\n".join(chunk_lines)
        if chunk_text.strip():
            chunks.append({
                "text": f"File: {filename}\nLines {i+1}-{i+len(chunk_lines)}:\n\n{chunk_text}",
                "start_line": i + 1,
                "end_line": i + len(chunk_lines),
                "file": filename,
            })
        i += max_lines - overlap

    return chunks


def should_index(path: Path) -> bool:
    if path.name in SKIP_FILE_PATTERNS:
        return False
    if path.suffix not in INDEXABLE_EXTENSIONS:
        return False
    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            return False
    except OSError:
        return False
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    if ".min." in path.name:
        return False
    for part in path.parts:
        if part.startswith(".") and part not in {".github", ".gitlab"}:
            return False
    return True


def file_hash(content: str) -> str:
    return hashlib.md5(content.encode("utf-8", errors="ignore")).hexdigest()


# ── Indexing (parallel) ───────────────────────────────────────────────────────
def index_codebase(root: Path = None, verbose: bool = True) -> dict:
    """
    Walk the codebase, chunk files, embed in PARALLEL, and store in Chroma.
    """
    root = root or WORKSPACE
    collection = get_collection()
    stats = {"files_scanned": 0, "files_indexed": 0, "chunks_added": 0, "skipped": 0}

    # ── PHASE 1: Collect all chunks ───────────────────────────────────────────
    all_chunks = []  # list of (chunk_id, text, metadata)

    if verbose:
        print(f"📂 Scanning files...")

    for filepath in root.rglob("*"):
        if not filepath.is_file():
            continue
        if not should_index(filepath):
            continue

        stats["files_scanned"] += 1
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            stats["skipped"] += 1
            continue

        rel_path = str(filepath.relative_to(root))
        chunks = chunk_file(content, rel_path)

        for chunk in chunks:
            chunk_id = f"{rel_path}::{chunk['start_line']}-{chunk['end_line']}"
            all_chunks.append((
                chunk_id,
                chunk["text"],
                {
                    "file": rel_path,
                    "start_line": chunk["start_line"],
                    "end_line": chunk["end_line"],
                },
            ))

    if verbose:
        print(f"📊 Collected {len(all_chunks)} chunks from {stats['files_scanned']} files")
        print(f"🚀 Embedding in parallel (workers={PARALLEL_EMBEDDINGS})...")

    if not all_chunks:
        return stats

    # ── PHASE 2: Embed all chunks in parallel ─────────────────────────────────
    BATCH = 32  # process in batches to avoid memory spikes
    total_batches = (len(all_chunks) + BATCH - 1) // BATCH

    for batch_idx in range(total_batches):
        batch = all_chunks[batch_idx * BATCH:(batch_idx + 1) * BATCH]
        texts = [c[1] for c in batch]

        embeddings = get_embeddings_parallel(texts)

        # Filter out failed embeddings
        ids, embs, docs, metas = [], [], [], []
        for (chunk_id, text, meta), emb in zip(batch, embeddings):
            if emb:
                ids.append(chunk_id)
                embs.append(emb)
                docs.append(text)
                metas.append(meta)
            else:
                stats["skipped"] += 1

        if ids:
            try:
                collection.upsert(
                    ids=ids,
                    embeddings=embs,
                    documents=docs,
                    metadatas=metas,
                )
                stats["chunks_added"] += len(ids)
            except Exception as e:
                if verbose:
                    print(f"  ✗ Batch error: {e}")
                stats["skipped"] += len(ids)

        if verbose:
            done = min((batch_idx + 1) * BATCH, len(all_chunks))
            pct = done / len(all_chunks) * 100
            print(f"  [{batch_idx+1}/{total_batches}] {done}/{len(all_chunks)} chunks ({pct:.0f}%)")

    # Count files that had at least one chunk indexed successfully
    indexed_files = set()
    for cid, _, meta in all_chunks:
        indexed_files.add(meta["file"])
    stats["files_indexed"] = len(indexed_files)

    return stats


# ── Searching ─────────────────────────────────────────────────────────────────
def search_code(query: str, n_results: int = 5) -> list[dict]:
    collection = get_collection()
    if collection.count() == 0:
        return []

    query_emb = get_embedding(query)
    if not query_emb:
        return []

    results = collection.query(query_embeddings=[query_emb], n_results=n_results)

    output = []
    for i in range(len(results["ids"][0])):
        output.append({
            "file": results["metadatas"][0][i]["file"],
            "start_line": results["metadatas"][0][i]["start_line"],
            "end_line": results["metadatas"][0][i]["end_line"],
            "text": results["documents"][0][i],
            "distance": results["distances"][0][i] if results.get("distances") else 0,
        })
    return output


def index_stats() -> dict:
    collection = get_collection()
    return {
        "total_chunks": collection.count(),
        "index_path": str(INDEX_DIR),
    }


def clear_index():
    global _client, _collection
    if _client is None:
        get_collection()
    try:
        _client.delete_collection("codebase")
    except Exception:
        pass
    _collection = None
    return "Index cleared."
