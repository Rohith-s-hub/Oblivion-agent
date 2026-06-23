"""
agent/symbol_index.py — SQLite-backed symbol index (Phase 2B.2)

A lightweight, durable index of every function, class, method, and section
across all indexed workspaces. Lives at ~/.oblivion/symbols.db.

Powers the upcoming hybrid search (Phase 2B.3):
  - exact symbol lookup (instant)
  - FTS5 full-text on name + signature + docstring
  - find_callers via simple grep over indexed code

Schema:
  symbols(workspace, file, type, name, signature, parent, docstring,
          start_line, end_line, code)

This module never raises on operational errors — best-effort everywhere.
If sqlite FTS5 isn't compiled in (rare), we silently fall back to LIKE.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

# Avoid circular import — chunker is independent
from agent.code_chunker import Chunk

from agent.paths import symbols_db
DB_PATH = symbols_db()


# ── Connection helper ───────────────────────────────────────────────────────
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _has_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_test USING fts5(x)"
        )
        conn.execute("DROP TABLE IF EXISTS _fts5_test")
        return True
    except sqlite3.OperationalError:
        return False


# ── Schema ──────────────────────────────────────────────────────────────────
def init_db() -> None:
    """Create tables if missing. Idempotent."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS symbols (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace   TEXT NOT NULL,
                file        TEXT NOT NULL,
                type        TEXT NOT NULL,
                name        TEXT NOT NULL,
                signature   TEXT,
                parent      TEXT,
                docstring   TEXT,
                start_line  INTEGER,
                end_line    INTEGER,
                code        TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ws_name ON symbols(workspace, name)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ws_file ON symbols(workspace, file)"
        )

        if _has_fts5(conn):
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
                    name, signature, docstring, code,
                    content='symbols', content_rowid='id',
                    tokenize='porter'
                )
            """)
            # Triggers to keep FTS in sync
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS symbols_ai AFTER INSERT ON symbols BEGIN
                    INSERT INTO symbols_fts(rowid, name, signature, docstring, code)
                    VALUES (new.id, new.name, new.signature, new.docstring, new.code);
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS symbols_ad AFTER DELETE ON symbols BEGIN
                    INSERT INTO symbols_fts(symbols_fts, rowid, name, signature, docstring, code)
                    VALUES('delete', old.id, old.name, old.signature, old.docstring, old.code);
                END
            """)
        conn.commit()


# Call init_db at import so callers don't have to remember
init_db()


# ── Write API ───────────────────────────────────────────────────────────────
def clear_file(workspace: str, file: str) -> int:
    """Delete all symbols for a file in a workspace. Returns count removed."""
    try:
        with _connect() as conn:
            cur = conn.execute(
                "DELETE FROM symbols WHERE workspace=? AND file=?",
                (workspace, file),
            )
            conn.commit()
            return cur.rowcount or 0
    except Exception:
        return 0


def clear_workspace(workspace: str) -> int:
    """Delete all symbols for a workspace."""
    try:
        with _connect() as conn:
            cur = conn.execute("DELETE FROM symbols WHERE workspace=?", (workspace,))
            conn.commit()
            return cur.rowcount or 0
    except Exception:
        return 0


def add_symbols(workspace: str, file: str, chunks: list[Chunk]) -> int:
    """
    Replace all symbols for (workspace, file) with the given chunks.
    Returns number of symbols inserted.
    """
    if not chunks:
        clear_file(workspace, file)
        return 0
    try:
        with _connect() as conn:
            conn.execute(
                "DELETE FROM symbols WHERE workspace=? AND file=?",
                (workspace, file),
            )
            rows = [
                (
                    workspace,
                    file,
                    c.type,
                    c.name or "",
                    c.signature or "",
                    c.parent or "",
                    c.docstring or "",
                    c.start_line,
                    c.end_line,
                    c.code or "",
                )
                for c in chunks
            ]
            conn.executemany("""
                INSERT INTO symbols
                  (workspace, file, type, name, signature, parent, docstring,
                   start_line, end_line, code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            conn.commit()
            return len(rows)
    except Exception:
        return 0


# ── Read API ────────────────────────────────────────────────────────────────
def find_symbol(workspace: str, name: str, exact: bool = True) -> list[dict]:
    """Find symbols by name in a workspace."""
    try:
        with _connect() as conn:
            if exact:
                cur = conn.execute("""
                    SELECT file, type, name, signature, parent, docstring,
                           start_line, end_line
                    FROM symbols
                    WHERE workspace=? AND name=?
                    ORDER BY file, start_line
                    LIMIT 50
                """, (workspace, name))
            else:
                cur = conn.execute("""
                    SELECT file, type, name, signature, parent, docstring,
                           start_line, end_line
                    FROM symbols
                    WHERE workspace=? AND name LIKE ?
                    ORDER BY file, start_line
                    LIMIT 50
                """, (workspace, f"%{name}%"))
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


def list_symbols_in_file(workspace: str, file: str) -> list[dict]:
    """Outline a file: every symbol in declaration order."""
    try:
        with _connect() as conn:
            cur = conn.execute("""
                SELECT type, name, signature, parent, start_line, end_line
                FROM symbols
                WHERE workspace=? AND file=?
                ORDER BY start_line
            """, (workspace, file))
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


def find_callers(workspace: str, symbol_name: str, exclude_definitions: bool = True) -> list[dict]:
    """
    Find every chunk in the workspace whose code references `symbol_name`.
    Excludes the chunk that DEFINES it (matched by name) when exclude_definitions=True.
    """
    if not symbol_name:
        return []
    try:
        with _connect() as conn:
            cur = conn.execute("""
                SELECT file, type, name, signature, start_line, end_line, code
                FROM symbols
                WHERE workspace=?
                  AND code LIKE ?
                ORDER BY file, start_line
                LIMIT 200
            """, (workspace, f"%{symbol_name}%"))
            results = []
            for r in cur.fetchall():
                d = dict(r)
                if exclude_definitions and d.get("name") == symbol_name:
                    continue
                # Show only the line(s) inside this chunk that mention the symbol
                hits = []
                for i, line in enumerate(d["code"].splitlines(), start=d["start_line"]):
                    if symbol_name in line:
                        hits.append({"line": i, "text": line.strip()[:200]})
                        if len(hits) >= 5:
                            break
                d["hits"] = hits
                d.pop("code", None)  # don't return huge bodies
                results.append(d)
            return results
    except Exception:
        return []


def search_symbols_fts(workspace: str, query: str, limit: int = 20) -> list[dict]:
    """Full-text search on name + signature + docstring + code via FTS5."""
    if not query:
        return []
    try:
        with _connect() as conn:
            # Quote query for FTS5 to avoid syntax errors on special chars
            safe_q = '"' + query.replace('"', '""') + '"'
            cur = conn.execute("""
                SELECT s.file, s.type, s.name, s.signature, s.parent,
                       s.start_line, s.end_line,
                       bm25(symbols_fts) AS rank
                FROM symbols_fts
                JOIN symbols s ON s.id = symbols_fts.rowid
                WHERE symbols_fts MATCH ?
                  AND s.workspace = ?
                ORDER BY rank
                LIMIT ?
            """, (safe_q, workspace, limit))
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        # FTS5 unavailable or query malformed → fallback LIKE on name + docstring
        try:
            with _connect() as conn:
                cur = conn.execute("""
                    SELECT file, type, name, signature, parent, start_line, end_line
                    FROM symbols
                    WHERE workspace=?
                      AND (name LIKE ? OR docstring LIKE ? OR signature LIKE ?)
                    ORDER BY file, start_line
                    LIMIT ?
                """, (workspace, f"%{query}%", f"%{query}%", f"%{query}%", limit))
                return [dict(r) for r in cur.fetchall()]
        except Exception:
            return []


def symbol_stats(workspace: str) -> dict:
    """Aggregate counts for status displays."""
    try:
        with _connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM symbols WHERE workspace=?", (workspace,)
            ).fetchone()[0]
            files = conn.execute(
                "SELECT COUNT(DISTINCT file) FROM symbols WHERE workspace=?", (workspace,)
            ).fetchone()[0]
            by_type = {
                r["type"]: r["c"]
                for r in conn.execute("""
                    SELECT type, COUNT(*) AS c
                    FROM symbols WHERE workspace=?
                    GROUP BY type
                """, (workspace,)).fetchall()
            }
            return {
                "total_symbols": total,
                "files_with_symbols": files,
                "by_type": by_type,
                "db_path": str(DB_PATH),
            }
    except Exception:
        return {"total_symbols": 0, "files_with_symbols": 0, "by_type": {}, "db_path": str(DB_PATH)}
