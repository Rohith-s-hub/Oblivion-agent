import os
import sqlite3
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

from agent.paths import agent_db as _agent_db
DB_PATH = Path(os.getenv("DB_PATH")).expanduser() if os.getenv("DB_PATH") else _agent_db()


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER REFERENCES sessions(id),
            role TEXT,
            content TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    c.commit()
    c.close()


def create_session(name: str = None) -> int:
    c = _conn()
    name = name or f"Session {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    cur = c.execute("INSERT INTO sessions (name) VALUES (?)", (name,))
    c.commit()
    sid = cur.lastrowid
    c.close()
    return sid


def save_message(session_id: int, role: str, content: str):
    c = _conn()
    c.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)", (session_id, role, content))
    c.execute("UPDATE sessions SET updated_at = datetime('now') WHERE id = ?", (session_id,))
    c.commit()
    c.close()


def load_session(session_id: int) -> list:
    c = _conn()
    rows = c.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()
    c.close()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def list_sessions() -> list:
    c = _conn()
    rows = c.execute("SELECT id, name, created_at, updated_at FROM sessions ORDER BY updated_at DESC").fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_session_preview(session_id: int, max_chars: int = 60) -> str:
    """Get the first user message from a session (for display in sidebar)."""
    c = _conn()
    row = c.execute(
        "SELECT content FROM messages WHERE session_id = ? AND role = 'user' ORDER BY id LIMIT 1",
        (session_id,)
    ).fetchone()
    c.close()
    if not row:
        return "(empty session)"
    text = row["content"].strip().replace("\n", " ")
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
    return text


def get_session_stats(session_id: int) -> dict:
    """Return message count + last activity for a session."""
    c = _conn()
    count = c.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ?",
        (session_id,)
    ).fetchone()[0]
    sess = c.execute(
        "SELECT name, created_at, updated_at FROM sessions WHERE id = ?",
        (session_id,)
    ).fetchone()
    c.close()
    if not sess:
        return {"messages": 0, "name": "?", "created_at": "?", "updated_at": "?"}
    return {
        "messages": count,
        "name": sess["name"],
        "created_at": sess["created_at"],
        "updated_at": sess["updated_at"],
    }


def rename_session(session_id: int, new_name: str) -> bool:
    """Rename a session. Returns True on success."""
    try:
        c = _conn()
        c.execute("UPDATE sessions SET name = ? WHERE id = ?", (new_name.strip(), session_id))
        c.commit()
        c.close()
        return True
    except Exception:
        return False


def delete_session(session_id: int) -> bool:
    """Delete a session and all its messages. Returns True on success."""
    try:
        c = _conn()
        c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        c.commit()
        c.close()
        return True
    except Exception:
        return False


def list_sessions_enriched(limit: int = 50) -> list:
    """List sessions WITH preview + message count, ordered by most recent.

    Returns: [{id, name, preview, messages, created_at, updated_at}, ...]
    """
    c = _conn()
    rows = c.execute("""
        SELECT s.id, s.name, s.created_at, s.updated_at,
               (SELECT COUNT(*) FROM messages WHERE session_id = s.id) AS msg_count,
               (SELECT content FROM messages
                WHERE session_id = s.id AND role = 'user'
                ORDER BY id LIMIT 1) AS first_msg
        FROM sessions s
        ORDER BY s.updated_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    c.close()

    out = []
    for r in rows:
        first = (r["first_msg"] or "(empty)").strip().replace("\n", " ")
        if len(first) > 70:
            first = first[:70] + "..."
        out.append({
            "id": r["id"],
            "name": r["name"],
            "preview": first,
            "messages": r["msg_count"] or 0,
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        })
    return out


def auto_rename_session_from_first_message(session_id: int) -> str:
    """If session still has default 'Session YYYY-MM-DD HH:MM' name,
    rename it from the first user message. Returns the new name."""
    stats = get_session_stats(session_id)
    name = stats.get("name", "")
    # Only auto-rename if it still looks like the default timestamp name
    if not name.startswith("Session 20"):
        return name  # already custom-named
    preview = get_session_preview(session_id, max_chars=50)
    if preview == "(empty session)":
        return name
    # Clean preview into a title-ish string
    title = preview.split("?")[0].split(".")[0].split(",")[0].strip()
    if len(title) < 4:
        return name
    if len(title) > 50:
        title = title[:50]
    rename_session(session_id, title)
    return title


def cleanup_empty_sessions() -> int:
    """Delete sessions that have zero messages. Called at boot.
    Returns count deleted."""
    try:
        c = _conn()
        # Find sessions with no messages
        rows = c.execute("""
            SELECT s.id FROM sessions s
            LEFT JOIN messages m ON m.session_id = s.id
            WHERE m.id IS NULL
        """).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            c.execute(f"DELETE FROM sessions WHERE id IN ({placeholders})", ids)
            c.commit()
        c.close()
        return len(ids)
    except Exception:
        return 0

