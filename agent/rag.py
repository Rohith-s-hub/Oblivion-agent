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

# Phase 2B.2: AST chunker + symbol index
from agent.code_chunker import chunk_code, Chunk
from agent import symbol_index as _symbols

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
    """Phase 2B.2: delegate to AST-aware chunker (agent/code_chunker.py).

    Returns dicts in the legacy shape so the rest of rag.py is unchanged:
      {text, start_line, end_line, file}
    PLUS extra keys consumers can use:
      {type, name, signature, parent, docstring, _chunk_obj}
    """
    chunks = chunk_code(content, filename)
    out = []
    for c in chunks:
        out.append({
            "text": c.to_embedding_text(),
            "start_line": c.start_line,
            "end_line": c.end_line,
            "file": c.file,
            "type": c.type,
            "name": c.name,
            "signature": c.signature,
            "parent": c.parent or "",
            "docstring": c.docstring or "",
            "_chunk_obj": c,
        })
    return out


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
    Phase 2B.2: also populates the SQLite symbol index.
    Returns {chunks_added, deleted, status}.
    """
    root = root or WORKSPACE
    collection = get_collection()
    rel_path = str(filepath.relative_to(root))

    # File deleted?
    if not filepath.exists():
        deleted = _delete_chunks_for_file(collection, rel_path)
        try:
            _symbols.clear_file(str(root), rel_path)
        except Exception:
            pass
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
        try:
            _symbols.clear_file(str(root), rel_path)
        except Exception:
            pass
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
            meta = {
                "file": rel_path,
                "start_line": chunk["start_line"],
                "end_line": chunk["end_line"],
            }
            # Phase 2B.2: enrich metadata with AST info
            for k in ("type", "name", "signature", "parent"):
                v = chunk.get(k)
                if v:
                    meta[k] = v
            metas.append(meta)

    if ids:
        collection.upsert(ids=ids, embeddings=embs, documents=docs, metadatas=metas)

    # Phase 2B.2: also populate SQLite symbol index
    try:
        chunk_objs = [c["_chunk_obj"] for c in chunks if "_chunk_obj" in c]
        _symbols.add_symbols(str(root), rel_path, chunk_objs)
    except Exception:
        pass

    hashes[ws_key][rel_path] = h
    _save_hashes(hashes)

    return {"status": "indexed", "deleted": deleted, "chunks_added": len(ids)}


def index_codebase(root: Path = None, verbose: bool = True, force: bool = False) -> dict:
    """
    Walk codebase and index only CHANGED files (via hash comparison).
    Phase 2B.2: also rebuilds the SQLite symbol index for changed files.
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
        try:
            _symbols.clear_workspace(str(root))
        except Exception:
            pass

    # Collect chunks that need embedding
    to_embed = []                       # list of (chunk_id, text, metadata)
    files_changed = []                  # rel_paths changed this run
    chunks_by_file: dict[str, list] = {}  # rel_path -> chunk dicts (for symbol index)

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
        chunks_by_file[rel_path] = chunks
        for chunk in chunks:
            chunk_id = f"{rel_path}::{chunk['start_line']}-{chunk['end_line']}"
            meta = {
                "file": rel_path,
                "start_line": chunk["start_line"],
                "end_line": chunk["end_line"],
            }
            for k in ("type", "name", "signature", "parent"):
                v = chunk.get(k)
                if v:
                    meta[k] = v
            to_embed.append((chunk_id, chunk["text"], meta))

        hashes[ws_key][rel_path] = h
        files_changed.append(rel_path)

    # Detect deleted files - remove their chunks and symbols
    indexed_files = set(hashes[ws_key].keys())
    on_disk = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and should_index(p)}
    removed_files = indexed_files - on_disk
    for rel in removed_files:
        deleted = _delete_chunks_for_file(collection, rel)
        stats["deleted"] += deleted
        try:
            _symbols.clear_file(str(root), rel)
        except Exception:
            pass
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

    # Phase 2B.2: rebuild SQLite symbol rows for every changed file
    symbols_added = 0
    for rel in files_changed:
        chunks = chunks_by_file.get(rel, [])
        chunk_objs = [c["_chunk_obj"] for c in chunks if "_chunk_obj" in c]
        try:
            symbols_added += _symbols.add_symbols(str(root), rel, chunk_objs)
        except Exception:
            pass
    if verbose and symbols_added:
        print(f"🧠 Symbol index updated: +{symbols_added} symbols across {len(files_changed)} files")

    stats["files_indexed"] = len(files_changed)
    stats["symbols_added"] = symbols_added
    _save_hashes(hashes)
    return stats


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
