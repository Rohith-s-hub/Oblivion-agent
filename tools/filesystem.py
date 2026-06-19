import os
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

WORKSPACE = Path(os.getenv("WORKSPACE_DIR", ".")).resolve()


class _PathError(Exception):
    """Raised when a path violates workspace boundary."""
    pass


def _safe_path(path: str) -> Path:
    """Resolve a path strictly inside WORKSPACE.

    Refuses:
      - any path segment equal to '..'
      - absolute paths that resolve outside WORKSPACE
      - paths that resolve outside WORKSPACE via symlinks
    Always returns a Path INSIDE WORKSPACE, or raises _PathError.
    """
    if not isinstance(path, str) or not path.strip():
        raise _PathError("Empty path provided.")

    raw = path.strip()
    # 1) Reject any '..' segment outright (most common LLM mistake)
    parts = Path(raw).parts
    if ".." in parts:
        raise _PathError(
            f"Path '{raw}' contains '..' which would escape the workspace "
            f"'{WORKSPACE}'. Use a path relative to the workspace root "
            f"(e.g., 'index.html' or 'src/main.py')."
        )

    # 2) Resolve relative to WORKSPACE if not absolute
    p_in = Path(raw).expanduser()
    candidate = p_in if p_in.is_absolute() else (WORKSPACE / p_in)

    # 3) Resolve fully (follows symlinks) and verify containment
    try:
        resolved = candidate.resolve()
    except Exception as e:
        raise _PathError(f"Cannot resolve path '{raw}': {e}")

    try:
        resolved.relative_to(WORKSPACE)
    except ValueError:
        raise _PathError(
            f"Path '{raw}' resolves to '{resolved}' which is outside the "
            f"workspace '{WORKSPACE}'. All file operations must stay inside "
            f"the workspace. Use a path like 'filename.ext' or 'subdir/file.ext'."
        )

    return resolved


def read_file(path: str) -> str:
    try:
        p = _safe_path(path)
    except _PathError as e:
        return f"Error: {e}"
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
    try:
        p = _safe_path(path)
    except _PathError as e:
        return f"Error: {e}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Written {len(content):,} chars to {path}"


def list_dir(path: str) -> str:
    try:
        p = _safe_path(path)
    except _PathError as e:
        return f"Error: {e}"
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
    try:
        p = _safe_path(path)
    except _PathError as e:
        return f"Error: {e}"
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
    try:
        p = _safe_path(path)
    except _PathError as e:
        return f"Error: {e}"
    if p.exists():
        return f"Exists ({'directory' if p.is_dir() else 'file'}): {path}"
    return f"Does not exist: {path}"


def create_dir(path: str) -> str:
    try:
        p = _safe_path(path)
    except _PathError as e:
        return f"Error: {e}"
    p.mkdir(parents=True, exist_ok=True)
    return f"Directory created: {path}"


# ─────────────────────────────────────────────────────────────────────────────
# new_workspace — creates a folder ANYWHERE (with safety guards) and switches
# the active workspace to it. Used by the agent when user says things like:
#   "create a new workspace called todo"
#   "make a workspace outside in home called myapp"
# ─────────────────────────────────────────────────────────────────────────────
def new_workspace(name: str, location: str = "") -> str:
    """Create a new workspace folder and switch into it.

    Args:
      name: folder name (e.g. "myapp")
      location: optional parent directory. Special keywords:
                ""             → defaults to ~/Projects/
                "~" / "home"   → home directory (~)
                "desktop"      → ~/Desktop
                "outside"      → home directory (~)
                "projects"     → ~/Projects (default)
                anything else  → treated as a path (~ expanded)
    """
    import os as _os
    from pathlib import Path as _Path

    home = _Path.home()
    self_dir = (home / "ai-agent").resolve()

    # Sanitize name
    name = (name or "").strip().replace(" ", "-")
    if not name or name.startswith(".") or "/" in name or "\\" in name:
        return f"Error: Invalid workspace name '{name}'. Use a simple name like 'my-app'."

    # Resolve location keyword
    loc = (location or "").strip().lower()
    if loc in ("", "projects", "default"):
        parent = home / "Projects"
    elif loc in ("~", "home", "outside", "home folder", "in home"):
        parent = home
    elif loc in ("desktop", "~/desktop"):
        parent = home / "Desktop"
    elif loc in ("documents", "~/documents"):
        parent = home / "Documents"
    elif loc in ("downloads", "~/downloads"):
        parent = home / "Downloads"
    else:
        # Treat as a path
        parent = _Path(location).expanduser().resolve()

    try:
        parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return f"Error: Could not access parent dir {parent}: {e}"

    new_ws = (parent / name).resolve()

    # Safety: refuse inside agent source dir
    try:
        new_ws.relative_to(self_dir)
        return f"Error: Refused — that path is inside the agent source dir."
    except ValueError:
        pass

    # Safety: refuse system dirs
    forbidden = ["/etc", "/usr", "/bin", "/sbin", "/sys", "/proc", "/boot", "/root"]
    for f in forbidden:
        if str(new_ws).startswith(f + "/") or str(new_ws) == f:
            return f"Error: Refused — {f} is a protected system directory."

    if new_ws.exists():
        if not new_ws.is_dir():
            return f"Error: {new_ws} exists but is not a directory."
        # Already exists — just switch
        action = "switched to existing"
    else:
        try:
            new_ws.mkdir(parents=True, exist_ok=False)
            action = "created and switched to"
        except Exception as e:
            return f"Error: Could not create {new_ws}: {e}"

    # Switch active workspace
    _os.environ["WORKSPACE_DIR"] = str(new_ws)

    # Update WORKSPACE in this module too (so subsequent tool calls use it)
    global WORKSPACE
    try:
        WORKSPACE = new_ws
    except Exception:
        pass

    # Update rag too
    try:
        import agent.rag as rag_mod
        rag_mod.WORKSPACE = new_ws
    except Exception:
        pass

    # Persist to .env
    try:
        env_path = home / "ai-agent" / ".env"
        if env_path.exists():
            env_lines = env_path.read_text().splitlines()
            env_lines = [l for l in env_lines if not l.startswith("WORKSPACE_DIR=")]
            env_lines.append(f"WORKSPACE_DIR={new_ws}")
            env_path.write_text("\n".join(env_lines) + "\n")
    except Exception:
        pass

    return f"Workspace {action}: {new_ws}\nName: {name}\nThe UI workspace panel will refresh automatically. All subsequent file operations will use this new workspace."
