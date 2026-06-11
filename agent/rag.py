"""
RAG with incremental indexing.

Tracks file hashes in ~/.ai-agent/file_hashes.json.
Only re-embeds files whose content has changed.
"""
import os
import json
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import chromadb
from chromadb.config import Settings
import httpx
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
WORKSPACE = Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()
INDEX_DIR = Path.home() / ".ai-agent" / "chroma"
HASH_FILE = Path.home() / ".ai-agent" / "file_hashes.json"
EMBED_MODEL = os.getenv("EMBED_MODEL", "all-minilm")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
PARALLEL_EMBEDDINGS = int(os.getenv("PARALLEL_EMBEDDINGS", "8"))

INDEX_DIR.mkdir(parents=True, exist_ok=True)
HASH_FILE.parent.mkdir(parents=True, exist_ok=True)

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


# ── Hash tracking ─────────────────────────────────────────────────────────────
def _load_hashes() -> dict:
    """Load saved file hashes per workspace."""
    if not HASH_FILE.exists():
        return {}
    try:
        return json.loads(HASH_FILE.read_text())
    except Exception:
        return {}


def _save_hashes(hashes: dict) -> None:
    HASH_FILE.write_text(json.dumps(hashes, indent=2))


def file_hash(content: str) -> str:
    return hashlib.md5(content.encode("utf-8", errors="ignore")).hexdigest()


# ── Embeddings ────────────────────────────────────────────────────────────────
def get_embedding(text: str, max_retries: int = 2) -> list[float]:
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
    workers = max_workers or PARALLEL_EMBEDDINGS
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(get_embedding, texts))


# ── Chroma ────────────────────────────────────────────────────────────────────
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


# ── Per-file indexing (used by both full + watcher) ──────────────────────────
def _delete_chunks_for_file(collection, rel_path: str) -> int:
    """Remove all existing chunks for a file before re-indexing it."""
    try:
        existing = collection.get(where={"file": rel_path})
        if existing and existing.get("ids"):
            collection.delete(ids=existing["ids"])
            return len(existing["ids"])
    except Exception:
        pass
    return 0


def index_single_file(filepath: Path, root: Path = None) -> dict:
    """
    Index ONE file (used by file watcher).
    Returns {chunks_added, deleted, status}.
    """
    root = root or WORKSPACE
    collection = get_collection()
    rel_path = str(filepath.relative_to(root))

    # File deleted?
    if not filepath.exists():
        deleted = _delete_chunks_for_file(collection, rel_path)
        hashes = _load_hashes()
        ws_key = str(root)
        if ws_key in hashes and rel_path in hashes[ws_key]:
            del hashes[ws_key][rel_path]
            _save_hashes(hashes)
        return {"status": "deleted", "deleted": deleted, "chunks_added": 0}

    # Skip ignored files
    if not should_index(filepath):
        return {"status": "skipped", "deleted": 0, "chunks_added": 0}

    try:
        content = filepath.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {"status": "error", "deleted": 0, "chunks_added": 0}

    # Check hash - unchanged?
    h = file_hash(content)
    hashes = _load_hashes()
    ws_key = str(root)
    if ws_key not in hashes:
        hashes[ws_key] = {}

    if hashes[ws_key].get(rel_path) == h:
        return {"status": "unchanged", "deleted": 0, "chunks_added": 0}

    # Changed - delete old chunks + re-embed
    deleted = _delete_chunks_for_file(collection, rel_path)
    chunks = chunk_file(content, rel_path)
    if not chunks:
        hashes[ws_key][rel_path] = h
        _save_hashes(hashes)
        return {"status": "empty", "deleted": deleted, "chunks_added": 0}

    texts = [c["text"] for c in chunks]
    embeddings = get_embeddings_parallel(texts)

    ids, embs, docs, metas = [], [], [], []
    for chunk, emb in zip(chunks, embeddings):
        if emb:
            ids.append(f"{rel_path}::{chunk['start_line']}-{chunk['end_line']}")
            embs.append(emb)
            docs.append(chunk["text"])
            metas.append({
                "file": rel_path,
                "start_line": chunk["start_line"],
                "end_line": chunk["end_line"],
            })

    if ids:
        collection.upsert(ids=ids, embeddings=embs, documents=docs, metadatas=metas)

    hashes[ws_key][rel_path] = h
    _save_hashes(hashes)

    return {"status": "indexed", "deleted": deleted, "chunks_added": len(ids)}


# ── Full indexing (incremental) ───────────────────────────────────────────────
def index_codebase(root: Path = None, verbose: bool = True, force: bool = False) -> dict:
    """
    Walk codebase and index only CHANGED files (via hash comparison).
    Pass force=True to re-embed everything regardless.
    """
    root = root or WORKSPACE
    collection = get_collection()
    stats = {
        "files_scanned": 0, "files_indexed": 0, "files_unchanged": 0,
        "chunks_added": 0, "skipped": 0, "deleted": 0,
    }

    hashes = _load_hashes()
    ws_key = str(root)
    if ws_key not in hashes:
        hashes[ws_key] = {}

    if force:
        if verbose:
            print("⚡ Force mode: re-embedding everything")
        hashes[ws_key] = {}

    # Collect chunks that need embedding
    to_embed = []  # list of (chunk_id, text, metadata)
    files_changed = []

    if verbose:
        print(f"📂 Scanning files...")

    for filepath in root.rglob("*"):
        if not filepath.is_file() or not should_index(filepath):
            continue
        stats["files_scanned"] += 1

        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            stats["skipped"] += 1
            continue

        rel_path = str(filepath.relative_to(root))
        h = file_hash(content)

        # Hash unchanged? Skip.
        if hashes[ws_key].get(rel_path) == h:
            stats["files_unchanged"] += 1
            continue

        # Changed - delete old chunks for this file
        deleted = _delete_chunks_for_file(collection, rel_path)
        stats["deleted"] += deleted

        # Add new chunks to embed queue
        chunks = chunk_file(content, rel_path)
        for chunk in chunks:
            chunk_id = f"{rel_path}::{chunk['start_line']}-{chunk['end_line']}"
            to_embed.append((
                chunk_id,
                chunk["text"],
                {"file": rel_path, "start_line": chunk["start_line"], "end_line": chunk["end_line"]},
            ))

        hashes[ws_key][rel_path] = h
        files_changed.append(rel_path)

    # Detect deleted files - remove their chunks
    indexed_files = set(hashes[ws_key].keys())
    on_disk = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and should_index(p)}
    removed_files = indexed_files - on_disk
    for rel in removed_files:
        deleted = _delete_chunks_for_file(collection, rel)
        stats["deleted"] += deleted
        del hashes[ws_key][rel]
        if verbose:
            print(f"  🗑️  Removed deleted file: {rel}")

    if verbose:
        print(f"📊 {len(files_changed)} files changed, {stats['files_unchanged']} unchanged")
        if not to_embed:
            print("✓ Nothing to embed - everything up to date!")

    if to_embed:
        if verbose:
            print(f"🚀 Embedding {len(to_embed)} chunks in parallel (workers={PARALLEL_EMBEDDINGS})...")

        BATCH = 32
        total_batches = (len(to_embed) + BATCH - 1) // BATCH

        for batch_idx in range(total_batches):
            batch = to_embed[batch_idx * BATCH:(batch_idx + 1) * BATCH]
            texts = [c[1] for c in batch]
            embeddings = get_embeddings_parallel(texts)

            ids, embs, docs, metas = [], [], [], []
            for (cid, text, meta), emb in zip(batch, embeddings):
                if emb:
                    ids.append(cid)
                    embs.append(emb)
                    docs.append(text)
                    metas.append(meta)
                else:
                    stats["skipped"] += 1

            if ids:
                collection.upsert(ids=ids, embeddings=embs, documents=docs, metadatas=metas)
                stats["chunks_added"] += len(ids)

            if verbose:
                done = min((batch_idx + 1) * BATCH, len(to_embed))
                print(f"  [{batch_idx+1}/{total_batches}] {done}/{len(to_embed)} ({done/len(to_embed)*100:.0f}%)")

    stats["files_indexed"] = len(files_changed)
    _save_hashes(hashes)
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
    hashes = _load_hashes()
    ws_key = str(WORKSPACE)
    return {
        "total_chunks": collection.count(),
        "tracked_files": len(hashes.get(ws_key, {})),
        "index_path": str(INDEX_DIR),
        "hash_file": str(HASH_FILE),
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

    # Clear hashes for this workspace
    hashes = _load_hashes()
    ws_key = str(WORKSPACE)
    if ws_key in hashes:
        del hashes[ws_key]
        _save_hashes(hashes)

    return "Index cleared."
