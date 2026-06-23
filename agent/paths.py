"""
agent/paths.py — Centralized path resolution for Oblivion.

ALL paths used by the agent flow through here. This makes the package
pip-installable on any user's machine (no hardcoded ~/ai-agent assumptions).

Layout:
  ~/.oblivion/              ← config dir (env, db, sessions)
    config.env              ← user config (was ~/ai-agent/.env)
    agent.db                ← session history sqlite
    symbols.db              ← code symbol index sqlite
    sessions/               ← per-session JSONL logs
    file_hashes.json        ← incremental indexing tracker
    exhausted_models.txt    ← deprecated, no longer written
  ~/.cache/oblivion/        ← large cached data
    chroma/                 ← vector embeddings
    whisper/                ← whisper model weights (~1.5GB)

Environment overrides (for power users / containers):
  OBLIVION_HOME             override ~/.oblivion
  OBLIVION_CACHE            override ~/.cache/oblivion
"""
from __future__ import annotations

import os
from pathlib import Path


def _resolve(env_key: str, default: Path) -> Path:
    """Resolve a path: env var takes priority, else use default. Always returns a Path."""
    val = os.getenv(env_key)
    if val:
        return Path(val).expanduser().resolve()
    return default


# ── Top-level dirs (created lazily on first access) ──────────────────────────
def oblivion_home() -> Path:
    """~/.oblivion/ — config, db, sessions, hash tracker."""
    p = _resolve("OBLIVION_HOME", Path.home() / ".oblivion")
    p.mkdir(parents=True, exist_ok=True)
    return p


def oblivion_cache() -> Path:
    """~/.cache/oblivion/ — large caches (chroma, whisper)."""
    p = _resolve("OBLIVION_CACHE", Path.home() / ".cache" / "oblivion")
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── Specific files / subdirs ─────────────────────────────────────────────────
def config_env() -> Path:
    """~/.oblivion/config.env — user's API keys and settings."""
    return oblivion_home() / "config.env"


def agent_db() -> Path:
    """~/.oblivion/agent.db — session history database."""
    return oblivion_home() / "agent.db"


def symbols_db() -> Path:
    """~/.oblivion/symbols.db — code symbol index."""
    return oblivion_home() / "symbols.db"


def sessions_dir() -> Path:
    """~/.oblivion/sessions/ — per-session JSONL event logs + saved chats."""
    p = oblivion_home() / "sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def hash_file() -> Path:
    """~/.oblivion/file_hashes.json — incremental indexing tracker."""
    return oblivion_home() / "file_hashes.json"


def chroma_dir() -> Path:
    """~/.cache/oblivion/chroma/ — vector embeddings database."""
    p = oblivion_cache() / "chroma"
    p.mkdir(parents=True, exist_ok=True)
    return p


def whisper_dir() -> Path:
    """~/.cache/oblivion/whisper/ — Whisper model weights cache."""
    p = oblivion_cache() / "whisper"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── Migration helper ─────────────────────────────────────────────────────────
def migrate_from_legacy() -> dict:
    """Move data from old ~/.ai-agent/ + ~/ai-agent/.env to new locations.

    Idempotent: safe to call multiple times. Only moves files that exist
    in legacy locations AND don't already exist in the new location.

    Returns dict of {what_moved: new_path} for logging.
    """
    moved = {}
    legacy_data = Path.home() / ".ai-agent"
    legacy_env = Path.home() / "ai-agent" / ".env"

    # Move ~/ai-agent/.env → ~/.oblivion/config.env (if user has it)
    if legacy_env.exists() and not config_env().exists():
        try:
            config_env().write_text(legacy_env.read_text(encoding="utf-8"))
            moved["config.env"] = str(config_env())
        except Exception:
            pass

    # Move ~/.ai-agent/agent.db → ~/.oblivion/agent.db
    src = legacy_data / "agent.db"
    if src.exists() and not agent_db().exists():
        try:
            agent_db().write_bytes(src.read_bytes())
            moved["agent.db"] = str(agent_db())
        except Exception:
            pass

    # Move ~/.ai-agent/symbols.db → ~/.oblivion/symbols.db
    src = legacy_data / "symbols.db"
    if src.exists() and not symbols_db().exists():
        try:
            symbols_db().write_bytes(src.read_bytes())
            moved["symbols.db"] = str(symbols_db())
        except Exception:
            pass

    # Move file_hashes.json
    src = legacy_data / "file_hashes.json"
    if src.exists() and not hash_file().exists():
        try:
            hash_file().write_text(src.read_text(encoding="utf-8"))
            moved["file_hashes.json"] = str(hash_file())
        except Exception:
            pass

    # Move ~/.ai-agent/sessions/* → ~/.oblivion/sessions/*
    src_sessions = legacy_data / "sessions"
    if src_sessions.exists() and src_sessions.is_dir():
        dest = sessions_dir()
        for f in src_sessions.iterdir():
            if f.is_file() and not (dest / f.name).exists():
                try:
                    (dest / f.name).write_bytes(f.read_bytes())
                    moved["sessions/" + f.name] = str(dest / f.name)
                except Exception:
                    pass

    # Move ~/.ai-agent/chroma → ~/.cache/oblivion/chroma  (large, only if missing)
    src_chroma = legacy_data / "chroma"
    dst_chroma = chroma_dir()
    if src_chroma.exists() and not any(dst_chroma.iterdir()):
        try:
            import shutil
            shutil.copytree(str(src_chroma), str(dst_chroma), dirs_exist_ok=True)
            moved["chroma/"] = str(dst_chroma)
        except Exception:
            pass

    # Move ~/.ai-agent/whisper → ~/.cache/oblivion/whisper
    src_whisper = legacy_data / "whisper"
    dst_whisper = whisper_dir()
    if src_whisper.exists() and not any(dst_whisper.iterdir()):
        try:
            import shutil
            shutil.copytree(str(src_whisper), str(dst_whisper), dirs_exist_ok=True)
            moved["whisper/"] = str(dst_whisper)
        except Exception:
            pass

    return moved


# ── First-run check ──────────────────────────────────────────────────────────
def is_first_run() -> bool:
    """True if user has no config.env yet (fresh install)."""
    return not config_env().exists()


def load_config_env() -> None:
    """Load ~/.oblivion/config.env into os.environ if it exists.

    Called early at app startup (before agent/llm init). Uses python-dotenv
    if available, else does a simple KEY=VALUE parse so we don't hard-require
    the dependency at this layer.
    """
    p = config_env()
    if not p.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(p, override=False)
        return
    except ImportError:
        pass
    # Fallback: simple parse
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception:
        pass


# ── Convenience: dump current resolution for debugging ──────────────────────
def describe() -> dict:
    """Return current path resolution (for /paths command or debug)."""
    return {
        "oblivion_home":   str(oblivion_home()),
        "oblivion_cache":  str(oblivion_cache()),
        "config_env":      str(config_env()),
        "agent_db":        str(agent_db()),
        "symbols_db":      str(symbols_db()),
        "sessions_dir":    str(sessions_dir()),
        "hash_file":       str(hash_file()),
        "chroma_dir":      str(chroma_dir()),
        "whisper_dir":     str(whisper_dir()),
        "is_first_run":    is_first_run(),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(describe(), indent=2))
