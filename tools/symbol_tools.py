"""
tools/symbol_tools.py — Phase 2B.3

Four new tools the LLM can call for fast, exact code navigation:
  - find_symbol(name)        — exact lookup, returns file:line + signature + docstring
  - list_symbols(file)       — outline view of a file
  - find_callers(symbol)     — every reference to a symbol
  - project_map(max_depth=3) — tree view of workspace structure

These complement (not replace) search_code() which remains for fuzzy/semantic queries.
All operate against the live WORKSPACE_DIR (read fresh each call).
"""
from __future__ import annotations

import os
from pathlib import Path

from agent import symbol_index as _symbols


def _current_workspace() -> str:
    """Always read fresh — handles /openproject mid-session."""
    return str(Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve())


# ── 1. find_symbol ──────────────────────────────────────────────────────────
def find_symbol(name: str) -> str:
    """Find a function/class/method by EXACT name in the current workspace.

    Returns a formatted string with each hit's location, signature, parent class,
    and docstring preview. If no exact match, falls back to LIKE substring search.
    """
    if not name or not name.strip():
        return "Error: empty symbol name"

    ws = _current_workspace()
    hits = _symbols.find_symbol(ws, name.strip(), exact=True)

    note = ""
    if not hits:
        hits = _symbols.find_symbol(ws, name.strip(), exact=False)
        note = " (substring match)"

    if not hits:
        return (
            f"No symbol named '{name}' found in workspace.\n"
            f"Try: list_symbols(\"<file>\") to outline a file, or search_code(\"{name}\") for fuzzy."
        )

    lines = [f"Found {len(hits)} symbol(s){note} for '{name}':", ""]
    for h in hits[:15]:
        parent = f" (in class {h['parent']})" if h.get("parent") else ""
        lines.append(
            f"  ━━━ {h['type']:10s} {h['name']}{parent}"
        )
        lines.append(f"      {h['file']}:{h['start_line']}-{h['end_line']}")
        if h.get("signature"):
            lines.append(f"      {h['signature']}")
        if h.get("docstring"):
            doc = h["docstring"].splitlines()[0][:140]
            lines.append(f"      \"{doc}\"")
        lines.append("")
    if len(hits) > 15:
        lines.append(f"  ... +{len(hits) - 15} more")
    return "\n".join(lines)


# ── 2. list_symbols ─────────────────────────────────────────────────────────
def list_symbols(file: str) -> str:
    """Outline a file: every function/class/method in declaration order.

    Useful for understanding a file's structure before reading or editing it.
    """
    if not file or not file.strip():
        return "Error: empty file path"

    ws = _current_workspace()
    entries = _symbols.list_symbols_in_file(ws, file.strip())
    if not entries:
        return (
            f"No symbols indexed for '{file}'.\n"
            f"Either the file doesn't exist, isn't indexed, or has no extractable symbols.\n"
            f"Try: read_file(\"{file}\") to inspect raw content."
        )

    lines = [f"Outline of '{file}' — {len(entries)} symbol(s):", ""]
    for e in entries:
        indent = "    " if e.get("parent") else "  "
        parent_tag = f" (in {e['parent']})" if e.get("parent") else ""
        sig = e.get("signature") or ""
        sig_short = (sig[:80] + "…") if len(sig) > 80 else sig
        lines.append(
            f"{indent}{e['type']:10s} {e['name']:30s}  L{e['start_line']}-{e['end_line']}"
        )
        if sig_short:
            lines.append(f"{indent}  {sig_short}")
    return "\n".join(lines)


# ── 3. find_callers ─────────────────────────────────────────────────────────
def find_callers(symbol_name: str) -> str:
    """Find every chunk in the workspace whose code references the symbol.

    Excludes the chunk that DEFINES the symbol. Useful for impact analysis
    before renaming, or for understanding how a function is used.
    """
    if not symbol_name or not symbol_name.strip():
        return "Error: empty symbol_name"

    ws = _current_workspace()
    callers = _symbols.find_callers(ws, symbol_name.strip(), exclude_definitions=True)

    if not callers:
        return (
            f"No callers found for '{symbol_name}'.\n"
            f"This could mean: (a) the symbol is unused, (b) it's only called from\n"
            f"non-indexed files, or (c) the name is spelled differently in callers."
        )

    total_hits = sum(len(c.get("hits", [])) for c in callers)
    lines = [
        f"Found {total_hits} reference(s) to '{symbol_name}' across {len(callers)} location(s):",
        "",
    ]
    for c in callers[:20]:
        parent = f" (in {c.get('parent')})" if c.get("parent") else ""
        lines.append(
            f"  ━━━ {c['file']}:{c['start_line']}-{c['end_line']}  "
            f"[{c['type']} {c.get('name', '')}{parent}]"
        )
        for hit in c.get("hits", [])[:5]:
            lines.append(f"      L{hit['line']}: {hit['text']}")
        lines.append("")
    if len(callers) > 20:
        lines.append(f"  ... +{len(callers) - 20} more locations")
    return "\n".join(lines)


# ── 4. project_map ──────────────────────────────────────────────────────────
_SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules", ".chroma",
    "dist", "build", "target", "out", ".next", ".nuxt",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "coverage", "htmlcov", ".coverage",
    ".idea", ".vscode", "__MACOSX",
    "logs", "tmp", "temp", "cache",
}


def project_map(max_depth: int = 3) -> str:
    """Render a tree of the current workspace (folders + files).

    Respects common SKIP_DIRS (.git, node_modules, __pycache__, etc).
    Hard limit ~200 entries to keep responses readable for the LLM.
    """
    try:
        max_depth = max(1, min(int(max_depth), 6))
    except Exception:
        max_depth = 3

    root = Path(_current_workspace())
    if not root.exists() or not root.is_dir():
        return f"Error: workspace not found: {root}"

    MAX_ENTRIES = 200
    out = [f"📁 {root.name}/  [{root}]", ""]
    entry_count = [0]
    truncated = [False]

    def walk(p: Path, prefix: str, depth: int):
        if depth >= max_depth or entry_count[0] >= MAX_ENTRIES:
            return
        try:
            items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except (PermissionError, OSError):
            return
        # Filter
        items = [
            i for i in items
            if not i.name.startswith(".") or i.name in {".env", ".gitignore"}
        ]
        items = [i for i in items if not (i.is_dir() and i.name in _SKIP_DIRS)]

        for i, item in enumerate(items):
            if entry_count[0] >= MAX_ENTRIES:
                truncated[0] = True
                return
            is_last = (i == len(items) - 1)
            connector = "└── " if is_last else "├── "
            if item.is_dir():
                out.append(f"{prefix}{connector}📁 {item.name}/")
                entry_count[0] += 1
                walk(item, prefix + ("    " if is_last else "│   "), depth + 1)
            else:
                size = ""
                try:
                    s = item.stat().st_size
                    if s < 1024:
                        size = f" ({s}B)"
                    elif s < 1024 * 1024:
                        size = f" ({s // 1024}KB)"
                    else:
                        size = f" ({s // (1024*1024)}MB)"
                except OSError:
                    pass
                out.append(f"{prefix}{connector}{item.name}{size}")
                entry_count[0] += 1

    walk(root, "", 0)
    out.append("")
    out.append(f"[{entry_count[0]} entries, depth {max_depth}{'  — TRUNCATED, increase max_depth or narrow scope' if truncated[0] else ''}]")
    return "\n".join(out)
