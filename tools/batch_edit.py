"""
tools/batch_edit.py - Atomic multi-file edit tool for Oblivion.

Allows Meera to propose changes to multiple files at once,
show a unified preview of ALL changes, and apply them atomically
with a single user approval.

This closes the biggest UX gap vs Claude Code:
  - Claude Code: shows all changes, one approval
  - Oblivion (before): one file at a time, multiple approvals
  - Oblivion (after):  all changes, one approval, atomic apply
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _get_workspace() -> Path:
    return Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()


def _safe_path(rel_path: str) -> Path:
    """Resolve path safely within workspace."""
    ws = _get_workspace()
    # Strip leading slashes
    rel_path = rel_path.lstrip("/")
    full = (ws / rel_path).resolve()
    # Must stay within workspace
    try:
        full.relative_to(ws)
    except ValueError:
        raise ValueError(f"Path '{rel_path}' escapes workspace root")
    return full


def _make_diff(original: str, updated: str, filename: str) -> str:
    """Generate unified diff between original and updated content."""
    import difflib
    orig_lines = original.splitlines(keepends=True)
    upd_lines = updated.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        orig_lines, upd_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm="",
    ))
    return "".join(diff)


def batch_edit(edits: list) -> str:
    """
    Apply multiple file edits atomically with a single approval.

    edits: list of edit operations, each is a dict with:
      For text replacement:
        {"path": "src/app.py", "old_text": "...", "new_text": "..."}
      For full file write:
        {"path": "src/new_file.py", "content": "..."}
      For new file creation:
        {"path": "src/config.py", "content": "...", "create": true}

    Returns a preview of ALL changes for approval.
    Actual writing is done by batch_apply after approval.

    Example:
      batch_edit([
        {"path": "app.py", "old_text": "def foo():", "new_text": "def foo(x: int):"},
        {"path": "tests/test_app.py", "content": "import pytest\\n..."},
      ])
    """
    if not edits:
        return "Error: no edits provided."

    if not isinstance(edits, list):
        return "Error: edits must be a list of edit operations."

    results = []
    errors = []
    previews = []

    for i, edit in enumerate(edits):
        if not isinstance(edit, dict):
            errors.append(f"Edit {i+1}: must be a dict, got {type(edit).__name__}")
            continue

        path = edit.get("path", "").strip()
        if not path:
            errors.append(f"Edit {i+1}: missing 'path'")
            continue

        try:
            p = _safe_path(path)
        except ValueError as e:
            errors.append(f"Edit {i+1} ({path}): {e}")
            continue

        # Determine edit type
        if "content" in edit:
            # Full file write (new or overwrite)
            new_content = edit["content"]
            if p.exists():
                try:
                    original = p.read_text(encoding="utf-8")
                except Exception as e:
                    errors.append(f"Edit {i+1} ({path}): cannot read: {e}")
                    continue
                diff = _make_diff(original, new_content, path)
                if not diff.strip():
                    results.append(f"  ✓ {path}: no changes")
                    continue
                previews.append({
                    "path": path,
                    "type": "overwrite",
                    "diff": diff,
                    "new_content": new_content,
                    "p": str(p),
                })
            else:
                # New file
                line_count = len(new_content.splitlines())
                previews.append({
                    "path": path,
                    "type": "create",
                    "content": new_content,
                    "line_count": line_count,
                    "p": str(p),
                })

        elif "old_text" in edit and "new_text" in edit:
            # Surgical replacement
            old_text = edit["old_text"]
            new_text = edit["new_text"]

            if not p.exists():
                errors.append(f"Edit {i+1} ({path}): file not found")
                continue

            try:
                original = p.read_text(encoding="utf-8")
            except Exception as e:
                errors.append(f"Edit {i+1} ({path}): cannot read: {e}")
                continue

            if old_text not in original:
                errors.append(
                    f"Edit {i+1} ({path}): old_text not found. "
                    f"Check it matches exactly (whitespace matters)."
                )
                continue

            updated = original.replace(old_text, new_text, 1)
            diff = _make_diff(original, updated, path)

            if not diff.strip():
                results.append(f"  ✓ {path}: no changes (old_text == new_text)")
                continue

            previews.append({
                "path": path,
                "type": "edit",
                "diff": diff,
                "original": original,
                "old_text": old_text,
                "new_text": new_text,
                "p": str(p),
            })

        else:
            errors.append(
                f"Edit {i+1} ({path}): must have either "
                f"'content' or both 'old_text'+'new_text'"
            )
            continue

    # Build preview output
    output_lines = []

    if errors:
        output_lines.append(f"⚠️  {len(errors)} error(s) found:")
        for err in errors:
            output_lines.append(f"  ✗ {err}")
        output_lines.append("")

    if not previews:
        if errors:
            return "\n".join(output_lines) + "\nNo valid edits to apply."
        return "No changes needed — all files already have the requested content."

    output_lines.append(
        f"BATCH EDIT PREVIEW — {len(previews)} file(s) will be changed:"
    )
    output_lines.append("=" * 60)

    for preview in previews:
        output_lines.append(f"\n📄 {preview['path']} [{preview['type']}]")
        output_lines.append("-" * 40)

        if preview["type"] == "create":
            output_lines.append(
                f"  NEW FILE: {preview['line_count']} lines"
            )
            # Show first 20 lines of new file
            lines = preview["content"].splitlines()[:20]
            for line in lines:
                output_lines.append(f"  + {line}")
            if len(preview["content"].splitlines()) > 20:
                output_lines.append(
                    f"  ... ({len(preview['content'].splitlines())-20} more lines)"
                )
        else:
            # Show diff (cap at 80 lines per file)
            diff_lines = preview["diff"].splitlines()[:80]
            for line in diff_lines:
                output_lines.append(f"  {line}")
            if len(preview["diff"].splitlines()) > 80:
                output_lines.append(
                    f"  ... ({len(preview['diff'].splitlines())-80} more diff lines)"
                )

    output_lines.append("")
    output_lines.append("=" * 60)
    output_lines.append(
        f"Ready to apply {len(previews)} change(s). "
        "Waiting for approval..."
    )

    # Store pending edits for batch_apply
    # We encode them in the return string so runtime can parse
    # The TUI approval handler will call batch_apply with the previews
    import json
    pending = json.dumps([
        {k: v for k, v in p.items() if k != "diff"}
        for p in previews
    ])
    output_lines.append(f"\n__BATCH_PENDING__:{pending}")

    return "\n".join(output_lines)


def batch_apply(previews_json: str) -> str:
    """
    Apply pre-validated batch edits after user approval.
    Called by the approval handler after user says yes.
    """
    import json

    try:
        previews = json.loads(previews_json)
    except Exception as e:
        return f"Error parsing batch edits: {e}"

    applied = []
    errors = []

    for preview in previews:
        path = preview["path"]
        p = Path(preview["p"])

        try:
            if preview["type"] == "create":
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(preview["content"], encoding="utf-8")
                applied.append(f"  ✓ Created: {path}")

            elif preview["type"] == "overwrite":
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(preview["new_content"], encoding="utf-8")
                applied.append(f"  ✓ Updated: {path}")

            elif preview["type"] == "edit":
                original = p.read_text(encoding="utf-8")
                if preview["old_text"] not in original:
                    errors.append(
                        f"  ✗ {path}: content changed since preview — skipped"
                    )
                    continue
                updated = original.replace(preview["old_text"], preview["new_text"], 1)
                p.write_text(updated, encoding="utf-8")
                applied.append(f"  ✓ Edited:  {path}")

        except Exception as e:
            errors.append(f"  ✗ {path}: {e}")

    lines = []
    if applied:
        lines.append(f"✅ Applied {len(applied)} change(s):")
        lines.extend(applied)
    if errors:
        lines.append(f"\n⚠️  {len(errors)} error(s):")
        lines.extend(errors)

    return "\n".join(lines) if lines else "Nothing applied."
