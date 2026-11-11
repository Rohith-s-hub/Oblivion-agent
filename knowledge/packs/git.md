# Git & GitHub Knowledge Pack

## Core Workflow

    git status                      # see what's changed
    git add <file>                  # stage specific file
    git add .                       # stage everything
    git commit -m "message"         # commit staged changes
    git push origin <branch>        # push to remote
    git pull origin <branch>        # fetch + merge from remote

## Commit Messages (discipline matters)

- One logical change per commit — don't bundle unrelated edits.
- Format: short imperative summary (≤50 chars), blank line, then detail if needed.
  GOOD: "Fix null pointer in checkout flow"
  BAD:  "fixed stuff" / "wip" / "asdf"

## Branching

    git branch                      # list branches
    git checkout -b feature/name    # create + switch to new branch
    git checkout main               # switch back
    git branch -d feature/name      # delete merged branch
    git push origin --delete feature/name   # delete remote branch

- Never commit directly to `main`/`master` on a team project — branch, then PR.
- Branch naming: `feature/x`, `fix/x`, `chore/x` — keep it descriptive and short.

## Merge Conflicts (the actual fix, not "just resolve it")

1. `git pull` or `git merge` fails with conflict markers in files:
<<<<<<< HEAD
your version

their version

branch-name

2. Open each conflicted file, manually decide which lines survive (or combine them), delete ALL conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`).
3. `git add <file>` for each resolved file.
4. `git commit` (no -m needed — it auto-fills a merge commit message).
5. If things go sideways: `git merge --abort` cancels and returns to pre-merge state.

## Rebasing (use carefully)

    git rebase main                 # replay your branch's commits on top of main

- Rewrites history — NEVER rebase a branch that others have already pulled/pushed to, only rebase local/personal branches.
- Conflict during rebase: fix the file, `git add <file>`, then `git rebase --continue` (not `git commit`).
- Abort anytime: `git rebase --abort`.

## Undoing Mistakes (pick the right tool)

| Situation | Command | Effect |
|---|---|---|
| Undo uncommitted changes to a file | `git checkout -- <file>` | Discards local edits, back to last commit |
| Unstage a file (kept edits) | `git restore --staged <file>` | Removes from staging, edits remain |
| Undo last commit, keep changes staged | `git reset --soft HEAD~1` | Commit gone, changes still staged |
| Undo last commit, keep changes unstaged | `git reset --mixed HEAD~1` (default) | Commit gone, changes in working dir |
| Undo last commit, DISCARD changes | `git reset --hard HEAD~1` | ⚠️ Destructive — changes gone permanently |
| Undo a commit that's already pushed/shared | `git revert <commit-hash>` | Safe — creates a NEW commit that undoes it, preserves history |
| Recover a "lost" commit | `git reflog` then `git checkout <hash>` | Reflog keeps a safety net for ~90 days |

RULE: If the commit has been pushed and others may have pulled it, use `revert`, never `reset --hard` — rewriting shared history breaks everyone else's repo.

## .gitignore Essentials

Always ignore, per stack:
Node

node_modules/
dist/
.env
.env.local

Python

pycache/
*.pyc
venv/
.venv/
*.egg-info/

General

.DS_Store
*.log
.vscode/

If a file is already tracked and you add it to .gitignore afterward, it stays tracked — remove it first:
    git rm --cached <file>

## GitHub-Specific Workflow

### Creating a repo from local code
    git init
    git add .
    git commit -m "Initial commit"
    git branch -M main
    git remote add origin https://github.com/<user>/<repo>.git
    git push -u origin main

### Pull Requests
- Push your feature branch, then open a PR on GitHub comparing it to `main`.
- Write a PR description: what changed, why, how to test — not just "updates".
- Small, focused PRs get reviewed faster and cause fewer conflicts than giant ones.

### README essentials (what a good one includes)
- Project name + one-line description
- Install/setup steps (copy-pasteable commands)
- Usage example
- Tech stack
- License (if open source)

### Common GitHub Errors

| Error | Cause | Fix |
|---|---|---|
| `Permission denied (publickey)` | SSH key not set up | Use HTTPS remote, or add SSH key to GitHub account settings |
| `Updates were rejected because the remote contains work...` | Remote has commits you don't have locally | `git pull origin <branch>` first, resolve conflicts, then push |
| `fatal: not a git repository` | Ran git command outside a repo | `cd` into the repo folder, or `git init` if it's new |
| Large file push rejected (>100MB) | GitHub's file size limit | Use Git LFS, or remove the file from history with `git filter-repo` |
| Accidentally committed a secret/API key | Committed sensitive data | Rotate the key immediately, then scrub history (`git filter-repo` or BFG) — a normal revert does NOT remove it from history |

## Safety Rules
- NEVER `git push --force` to `main`/`master` or any shared branch — use `--force-with-lease` on your own feature branch only if absolutely needed.
- NEVER commit `.env` files or API keys — check `.gitignore` BEFORE the first commit of a new project.
- Before any destructive command (`reset --hard`, `push --force`, `clean -fd`), confirm with the user first if there's any ambiguity about what's being discarded.
