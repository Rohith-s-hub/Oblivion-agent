"""
edit_file: surgical find-and-replace inside a file.
Safer than write_file because it only changes specific sections.
"""
from pathlib import Path
from tools.filesystem import _safe_path, read_file


def edit_file(path: str, old_text: str, new_text: str) -> str:
    """
    Replace old_text with new_text inside the file at path.
    - old_text must match exactly (including whitespace/indentation)
    - Replaces only the FIRST occurrence
    - Returns error if old_text not found
    """
    p = _safe_path(path)

    if not p.exists():
        return f"Error: File not found: {path}"
    if not p.is_file():
        return f"Error: Not a file: {path}"

    try:
        original = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Error: File is binary: {path}"

    if old_text not in original:
        # Try to help debug — show similar lines
        lines = original.splitlines()
        old_lines = old_text.strip().splitlines()
        first_old_line = old_lines[0].strip() if old_lines else ""

        similar = [
            f"  line {i+1}: {line}"
            for i, line in enumerate(lines)
            if first_old_line.lower() in line.lower()
        ]

        hint = ""
        if similar:
            hint = "\nSimilar lines found:\n" + "\n".join(similar[:5])

        return (
            f"Error: old_text not found in {path}. "
            f"Make sure it matches exactly (including indentation).{hint}"
        )

    updated = original.replace(old_text, new_text, 1)
    p.write_text(updated, encoding="utf-8")

    # Count changed lines for summary
    old_lines = len(old_text.splitlines())
    new_lines = len(new_text.splitlines())

    return (
        f"Edited {path}: replaced {old_lines} line(s) with {new_lines} line(s)."
    )


def insert_after(path: str, after_text: str, insert_text: str) -> str:
    """
    Insert insert_text immediately after the first occurrence of after_text.
    """
    p = _safe_path(path)

    if not p.exists():
        return f"Error: File not found: {path}"

    original = p.read_text(encoding="utf-8")

    if after_text not in original:
        return f"Error: after_text not found in {path}"

    updated = original.replace(after_text, after_text + insert_text, 1)
    p.write_text(updated, encoding="utf-8")
    return f"Inserted {len(insert_text.splitlines())} line(s) after match in {path}"
