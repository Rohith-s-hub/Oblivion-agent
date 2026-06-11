import os
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

WORKSPACE = Path(os.getenv("WORKSPACE_DIR", ".")).resolve()


def _safe_path(path: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not str(resolved).startswith(str(WORKSPACE)):
        resolved = (WORKSPACE / path).resolve()
    return resolved


def read_file(path: str) -> str:
    p = _safe_path(path)
    if not p.exists():
        return f"Error: File not found: {path}"
    if not p.is_file():
        return f"Error: Not a file: {path}"
    if p.stat().st_size > 1_000_000:
        return f"Error: File too large."
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Error: File is binary: {path}"


def write_file(path: str, content: str) -> str:
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Written {len(content):,} chars to {path}"


def list_dir(path: str) -> str:
    p = _safe_path(path)
    if not p.exists():
        return f"Error: Path not found: {path}"
    if not p.is_dir():
        return f"Error: Not a directory: {path}"
    entries = []
    for item in sorted(p.iterdir()):
        if item.is_dir():
            entries.append(f"DIR  {item.name}/")
        else:
            size = item.stat().st_size
            size_str = f"{size}B" if size < 1024 else f"{size//1024}KB"
            entries.append(f"FILE {item.name} ({size_str})")
    return f"Contents of {path}:\n" + "\n".join(entries) if entries else f"(empty: {path})"


def grep_files(pattern: str, path: str, file_pattern: str = "*") -> str:
    p = _safe_path(path)
    if not p.exists():
        return f"Error: Path not found: {path}"
    matches = []
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv"}

    def search_file(filepath):
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(content.splitlines(), 1):
                if re.search(pattern, line, re.IGNORECASE):
                    rel = filepath.relative_to(WORKSPACE)
                    matches.append(f"{rel}:{lineno}: {line.strip()}")
                    if len(matches) >= 50:
                        return
        except Exception:
            pass

    if p.is_file():
        search_file(p)
    else:
        for fp in p.rglob(file_pattern):
            if fp.is_file() and not any(d in fp.parts for d in skip_dirs):
                search_file(fp)
                if len(matches) >= 50:
                    break

    return "\n".join(matches) if matches else f"No matches for '{pattern}' in {path}"


def file_exists(path: str) -> str:
    p = _safe_path(path)
    if p.exists():
        return f"Exists ({'directory' if p.is_dir() else 'file'}): {path}"
    return f"Does not exist: {path}"


def create_dir(path: str) -> str:
    _safe_path(path).mkdir(parents=True, exist_ok=True)
    return f"Directory created: {path}"
