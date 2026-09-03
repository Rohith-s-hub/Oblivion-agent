"""
tools/batch_edit.py - Atomic multi-file editing tool for Oblivion AI.
Applies edits to multiple files IMMEDIATELY to disk.
"""
from __future__ import annotations

import os
import json
from pathlib import Path


def _get_workspace() -> Path:
    return Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()


def _safe_path(rel_path: str) -> Path:
    """Resolve path safely within workspace."""
    ws = _get_workspace()
    clean = str(rel_path).strip().lstrip("/")
    full = (ws / clean).resolve()
    try:
        full.relative_to(ws)
    except ValueError:
        raise ValueError(f"Path '{rel_path}' escapes workspace root {ws}")
    return full


def batch_edit(edits: list) -> str:
    """
    Apply multiple file edits IMMEDIATELY to disk.

    edits: list of dicts, each with:
      {"path": "src/App.jsx", "content": "..."} for full file creation/overwrite
      OR
      {"path": "src/App.jsx", "old_text": "...", "new_text": "..."} for surgical edit
    """
    if not edits or not isinstance(edits, list):
        return "Error: edits must be a non-empty list of edit objects."

    applied = []
    errors = []

    for i, edit in enumerate(edits, 1):
        if not isinstance(edit, dict):
            errors.append(f"Edit #{i}: invalid edit object (must be dict)")
            continue

        path_str = edit.get("path", "").strip()
        if not path_str:
            errors.append(f"Edit #{i}: missing 'path'")
            continue

        try:
            full_path = _safe_path(path_str)
        except ValueError as e:
            errors.append(f"Edit #{i} ({path_str}): {e}")
            continue

        # Case 1: Full content write / creation
        if "content" in edit:
            content_str = edit["content"]
            try:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content_str, encoding="utf-8")
                applied.append(f"  ✓ Created: {path_str} ({len(content_str)} chars)")
            except Exception as e:
                errors.append(f"  ✗ {path_str}: failed to write: {e}")

        # Case 2: Surgical replacement (old_text -> new_text)
        elif "old_text" in edit and "new_text" in edit:
            old_text = edit["old_text"]
            new_text = edit["new_text"]

            if not full_path.exists():
                # If file doesn't exist, treat new_text as full content
                try:
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(new_text, encoding="utf-8")
                    applied.append(f"  ✓ Created: {path_str} ({len(new_text)} chars)")
                except Exception as e:
                    errors.append(f"  ✗ {path_str}: failed to create: {e}")
            else:
                try:
                    orig = full_path.read_text(encoding="utf-8")
                    if old_text in orig:
                        updated = orig.replace(old_text, new_text, 1)
                        full_path.write_text(updated, encoding="utf-8")
                        applied.append(f"  ✓ Edited: {path_str}")
                    else:
                        errors.append(f"  ✗ {path_str}: old_text not found in file")
                except Exception as e:
                    errors.append(f"  ✗ {path_str}: failed to edit: {e}")
        else:
            errors.append(f"Edit #{i} ({path_str}): must provide 'content' OR 'old_text'+'new_text'")

    lines = []
    if applied:
        lines.append(f"✅ BATCH EDIT SUCCESS: {len(applied)} file(s) WRITTEN TO DISK:")
        lines.extend(applied)
    if errors:
        lines.append(f"\n⚠️ ERRORS ({len(errors)}):")
        lines.extend(errors)

    if not lines:
        return "No files were written."

    return "\n".join(lines)


def batch_apply(previews_json: str) -> str:
    """Legacy helper for backward compatibility."""
    return "batch_edit already applies files directly to disk."
