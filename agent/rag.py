"""
RAG (Retrieval Augmented Generation) for the AI agent.
Indexes the codebase and lets the agent search semantically.

Uses:
  - Ollama nomic-embed-text for embeddings (local, fast)
  - ChromaDB for vector storage (embedded, no server)
"""
import os
import hashlib
from pathlib import Path
from typing import Optional
import chromadb
from chromadb.config import Settings
import httpx
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
WORKSPACE = Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()
INDEX_DIR = Path.home() / ".ai-agent" / "chroma"
EMBED_MODEL = "nomic-embed-text"
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

INDEX_DIR.mkdir(parents=True, exist_ok=True)

# Files to index
INDEXABLE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
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
MAX_FILE_SIZE = 100_000  # 100KB per file


# ── Embeddings via Ollama ─────────────────────────────────────────────────────
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


# ── Chroma Setup ──────────────────────────────────────────────────────────────
_client = None
_collection = None


def get_collection():
    """Get or create the Chroma collection."""
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
    """
    Split file content into overlapping chunks.
    Returns list of {text, start_line, end_line} dicts.
    """
    lines = content.splitlines()
    chunks = []
    overlap = 10

    i = 0
    while i < len(lines):
        chunk_lines = lines[i:i + max_lines]
        chunk_text = "\n".join(chunk_lines)

        if chunk_text.strip():  # Skip empty chunks
            chunks.append({
                "text": f"File: {filename}\nLines {i+1}-{i+len(chunk_lines)}:\n\n{chunk_text}",
                "start_line": i + 1,
                "end_line": i + len(chunk_lines),
                "file": filename,
            })

        i += max_lines - overlap  # Slide window with overlap

    return chunks


# ── Indexing ──────────────────────────────────────────────────────────────────
def should_index(path: Path) -> bool:
    """Check if a file should be indexed."""
    if path.name in SKIP_FILE_PATTERNS:
        return False
    if path.suffix not in INDEXABLE_EXTENSIONS:
        return False
    if path.stat().st_size > MAX_FILE_SIZE:
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
    """Quick hash to detect file changes."""
    return hashlib.md5(content.encode("utf-8", errors="ignore")).hexdigest()


def index_codebase(root: Path = None, verbose: bool = True) -> dict:
    """
    Walk the codebase, chunk files, embed, and store in Chroma.
    Returns stats dict.
    """
    root = root or WORKSPACE
    collection = get_collection()

    stats = {"files_scanned": 0, "files_indexed": 0, "chunks_added": 0, "skipped": 0}

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

        if not chunks:
            continue

        # Embed and store each chunk
        ids = []
        embeddings = []
        documents = []
        metadatas = []

        for idx, chunk in enumerate(chunks):
            chunk_id = f"{rel_path}::{chunk['start_line']}-{chunk['end_line']}"
            emb = get_embedding(chunk["text"])
            if not emb:
                continue

            ids.append(chunk_id)
            embeddings.append(emb)
            documents.append(chunk["text"])
            metadatas.append({
                "file": rel_path,
                "start_line": chunk["start_line"],
                "end_line": chunk["end_line"],
            })

        if ids:
            # Upsert (insert or update)
            try:
                collection.upsert(
                    ids=ids,
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas,
                )
                stats["files_indexed"] += 1
                stats["chunks_added"] += len(ids)
                if verbose:
                    print(f"  ✓ Indexed {rel_path} ({len(ids)} chunks)")
            except Exception as e:
                print(f"  ✗ Error indexing {rel_path}: {e}")
                stats["skipped"] += 1

    return stats


# ── Searching ─────────────────────────────────────────────────────────────────
def search_code(query: str, n_results: int = 5) -> list[dict]:
    """
    Semantic search across the indexed codebase.
    Returns list of {file, start_line, end_line, text, distance}.
    """
    collection = get_collection()

    if collection.count() == 0:
        return []

    query_emb = get_embedding(query)
    if not query_emb:
        return []

    results = collection.query(
        query_embeddings=[query_emb],
        n_results=n_results,
    )

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
    """Get stats about the current index."""
    collection = get_collection()
    return {
        "total_chunks": collection.count(),
        "index_path": str(INDEX_DIR),
    }


def clear_index():
    """Wipe the index. Use before re-indexing."""
    global _client, _collection
    if _client is None:
        get_collection()
    try:
        _client.delete_collection("codebase")
    except Exception:
        pass
    _collection = None
    return "Index cleared."
