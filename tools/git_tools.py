"""
tools/git_tools.py - Git awareness tools for Oblivion.

Gives Meera full git knowledge:
  - Current branch, staged/unstaged/untracked files
  - Diff vs HEAD or between commits
  - Recent commit history
  - Stage + commit atomically
  - Branch management
  - Safe undo (keeps working changes)

All operations are workspace-relative and safe.
Destructive operations (force push etc) are blocked here -
they go through run_bash with destructive tier approval.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _get_workspace() -> Path:
    return Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()


def _run_git(args: list[str], cwd: Path = None, timeout: int = 15) -> tuple[bool, str]:
    """Run a git command. Returns (success, output)."""
    cwd = cwd or _get_workspace()
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout.strip()
        err = result.stderr.strip()
        if result.returncode != 0:
            return False, err or output
        return True, output
    except FileNotFoundError:
        return False, "git not found. Install git: sudo apt install git"
    except subprocess.TimeoutExpired:
        return False, "git command timed out"
    except Exception as e:
        return False, f"git error: {e}"


def _is_git_repo(path: Path = None) -> bool:
    """Check if workspace is a git repository."""
    path = path or _get_workspace()
    ok, _ = _run_git(["rev-parse", "--git-dir"], cwd=path)
    return ok


def git_status() -> str:
    """
    Show current git status: branch, staged, unstaged, untracked files.
    Use this before any git operation to understand current state.
    """
    ws = _get_workspace()

    if not _is_git_repo(ws):
        return (
            "Not a git repository.\n"
            "Initialize with: git init\n"
            f"Workspace: {ws}"
        )

    lines = []

    # Current branch
    ok, branch = _run_git(["branch", "--show-current"], ws)
    if ok and branch:
        lines.append(f"Branch: {branch}")
    else:
        # Detached HEAD
        ok2, ref = _run_git(["rev-parse", "--short", "HEAD"], ws)
        lines.append(f"Branch: (detached HEAD at {ref if ok2 else '?'})")

    # Upstream tracking
    ok, upstream = _run_git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        ws
    )
    if ok and upstream:
        # Ahead/behind
        ok2, ab = _run_git(
            ["rev-list", "--left-right", "--count", f"HEAD...{upstream}"],
            ws
        )
        if ok2 and ab:
            parts = ab.split()
            if len(parts) == 2:
                ahead, behind = parts
                lines.append(f"Tracking: {upstream} (ahead {ahead}, behind {behind})")
            else:
                lines.append(f"Tracking: {upstream}")

    lines.append("")

    # Staged files
    ok, staged = _run_git(["diff", "--cached", "--name-status"], ws)
    if ok and staged:
        lines.append("Staged (ready to commit):")
        for line in staged.split("\n"):
            if line.strip():
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    status_code, fname = parts
                    status_map = {
                        "A": "  + added:   ",
                        "M": "  ~ modified:",
                        "D": "  - deleted: ",
                        "R": "  > renamed: ",
                    }
                    prefix = status_map.get(status_code[0], "  ? ")
                    lines.append(f"{prefix}{fname}")
    else:
        lines.append("Staged: nothing")

    lines.append("")

    # Unstaged changes
    ok, unstaged = _run_git(["diff", "--name-status"], ws)
    if ok and unstaged:
        lines.append("Unstaged changes:")
        for line in unstaged.split("\n"):
            if line.strip():
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    status_code, fname = parts
                    status_map = {
                        "M": "  ~ modified:",
                        "D": "  - deleted: ",
                    }
                    prefix = status_map.get(status_code[0], "  ? ")
                    lines.append(f"{prefix}{fname}")
    else:
        lines.append("Unstaged: clean")

    lines.append("")

    # Untracked files
    ok, untracked = _run_git(
        ["ls-files", "--others", "--exclude-standard"],
        ws
    )
    if ok and untracked:
        untracked_list = untracked.split("\n")[:10]  # cap at 10
        lines.append(f"Untracked ({len(untracked_list)} shown):")
        for f in untracked_list:
            if f.strip():
                lines.append(f"  ? {f}")
    else:
        lines.append("Untracked: none")

    # Last commit
    ok, last = _run_git(
        ["log", "-1", "--pretty=format:%h %s (%ar by %an)"],
        ws
    )
    if ok and last:
        lines.append("")
        lines.append(f"Last commit: {last}")

    return "\n".join(lines)


def git_diff(path: str = "", staged: bool = False) -> str:
    """
    Show git diff. 
    - path: specific file to diff (empty = entire workspace)
    - staged: True to show staged diff, False for unstaged
    Use this before committing to review changes.
    """
    ws = _get_workspace()

    if not _is_git_repo(ws):
        return "Not a git repository."

    args = ["diff"]
    if staged:
        args.append("--cached")
    args.extend(["--stat", "--patch", "--no-color"])
    if path:
        args.extend(["--", path])

    ok, output = _run_git(args, ws)
    if not ok:
        return f"git diff failed: {output}"
    if not output.strip():
        label = "staged" if staged else "unstaged"
        return f"No {label} changes" + (f" in {path}" if path else "") + "."

    # Cap output to avoid flooding context
    lines = output.split("\n")
    if len(lines) > 200:
        output = "\n".join(lines[:200]) + f"\n\n... ({len(lines)-200} more lines truncated)"

    return output


def git_log(n: int = 10, path: str = "") -> str:
    """
    Show recent git commits.
    - n: number of commits to show (default 10)
    - path: filter to commits touching this file (optional)
    """
    ws = _get_workspace()

    if not _is_git_repo(ws):
        return "Not a git repository."

    n = min(max(1, n), 50)  # clamp 1-50

    args = [
        "log",
        f"-{n}",
        "--pretty=format:%C(yellow)%h%Creset %C(cyan)%ar%Creset %C(white)%an%Creset%n  %s%n  %C(dim)%D%Creset",
        "--no-color",
    ]
    if path:
        args.extend(["--", path])

    # Use simpler format without color codes
    args = [
        "log",
        f"-{n}",
        "--pretty=format:commit %h | %ar | %an%n  msg: %s%n  refs: %D",
    ]
    if path:
        args.extend(["--", path])

    ok, output = _run_git(args, ws)
    if not ok:
        return f"git log failed: {output}"
    if not output.strip():
        return "No commits yet." + (f" (or {path} not tracked)" if path else "")

    return output


def git_commit(message: str, add_all: bool = False) -> str:
    """
    Stage and commit changes.
    - message: commit message (required)
    - add_all: if True, stages ALL modified tracked files first (git add -u)
    
    Does NOT force push. Does NOT push to remote.
    Use run_bash for git push (requires explicit approval).
    """
    ws = _get_workspace()

    if not _is_git_repo(ws):
        return "Not a git repository."

    if not message or not message.strip():
        return "Error: commit message cannot be empty."

    # Stage all modified tracked files if requested
    if add_all:
        ok, out = _run_git(["add", "-u"], ws)
        if not ok:
            return f"git add -u failed: {out}"

    # Check if there's anything staged
    ok, staged = _run_git(["diff", "--cached", "--name-only"], ws)
    if not ok:
        return f"git diff --cached failed: {staged}"
    if not staged.strip():
        return (
            "Nothing staged to commit.\n"
            "Stage files first with run_bash: git add <file>\n"
            "Or use git_commit with add_all=True to stage all modified files."
        )

    # Commit
    ok, out = _run_git(["commit", "-m", message.strip()], ws)
    if not ok:
        return f"git commit failed: {out}"

    # Show what was committed
    ok2, show = _run_git(["log", "-1", "--stat", "--no-color"], ws)
    if ok2:
        return f"✓ Committed successfully.\n\n{show}"
    return f"✓ Committed successfully.\n{out}"


def git_branch(action: str = "list", name: str = "") -> str:
    """
    Manage git branches.
    - action: 'list' | 'create' | 'switch' | 'delete'
    - name: branch name (required for create/switch/delete)
    """
    ws = _get_workspace()

    if not _is_git_repo(ws):
        return "Not a git repository."

    if action == "list":
        ok, out = _run_git(["branch", "-a", "--no-color"], ws)
        if not ok:
            return f"git branch failed: {out}"
        return out or "No branches found."

    if not name or not name.strip():
        return f"Error: branch name required for action '{action}'."

    name = name.strip()

    if action == "create":
        ok, out = _run_git(["checkout", "-b", name], ws)
        if not ok:
            return f"Failed to create branch '{name}': {out}"
        return f"✓ Created and switched to branch: {name}"

    if action == "switch":
        ok, out = _run_git(["checkout", name], ws)
        if not ok:
            return f"Failed to switch to branch '{name}': {out}"
        return f"✓ Switched to branch: {name}"

    if action == "delete":
        ok, out = _run_git(["branch", "-d", name], ws)
        if not ok:
            # Try to give helpful message
            return (
                f"Failed to delete branch '{name}': {out}\n"
                "Note: use run_bash with 'git branch -D {name}' to force delete "
                "(requires approval)"
            )
        return f"✓ Deleted branch: {name}"

    return f"Unknown action '{action}'. Use: list, create, switch, delete"


def git_undo(mode: str = "soft") -> str:
    """
    Safely undo the last commit.
    - mode: 'soft' (default) = undo commit but keep changes staged
            'mixed' = undo commit and unstage changes (keep files)
    
    NEVER does hard reset or force push.
    Use run_bash for those (requires explicit destructive approval).
    """
    ws = _get_workspace()

    if not _is_git_repo(ws):
        return "Not a git repository."

    if mode not in ("soft", "mixed"):
        return "Error: mode must be 'soft' or 'mixed'. Use run_bash for hard reset."

    # Show what we're about to undo
    ok, last = _run_git(
        ["log", "-1", "--pretty=format:commit %h: %s"],
        ws
    )
    if not ok:
        return "No commits to undo."

    ok, out = _run_git(["reset", f"--{mode}", "HEAD~1"], ws)
    if not ok:
        return f"git reset failed: {out}"

    return (
        f"✓ Undone ({mode} reset): {last}\n"
        f"Changes are {'staged' if mode == 'soft' else 'unstaged but preserved'}.\n"
        "Use git_commit to re-commit with a different message, "
        "or run_bash for git push."
    )
