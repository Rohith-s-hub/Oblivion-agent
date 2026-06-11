import os
import sqlite3
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path(os.getenv("DB_PATH", "~/.ai-agent/agent.db")).expanduser()


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
