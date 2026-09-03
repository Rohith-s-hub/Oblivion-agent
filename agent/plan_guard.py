"""
plan_guard.py — Disk-backed plan enforcement.
The LLM cannot finalize a build until every planned file exists on disk.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional


def workspace_root() -> Path:
    return Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()


def plan_path(ws: Optional[Path] = None) -> Path:
    ws = ws or workspace_root()
    return ws / ".oblivion" / "plan.json"


def ensure_oblivion_dir(ws: Optional[Path] = None) -> Path:
    ws = ws or workspace_root()
    d = ws / ".oblivion"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_plan(steps: list[dict], goal: str = "", ws: Optional[Path] = None) -> Path:
    """steps = [{path, purpose}, ...]"""
    ws = ws or workspace_root()
    ensure_oblivion_dir(ws)
    p = plan_path(ws)
    data = {
        "goal": goal,
        "steps": steps,
        "buildOrder": [s["path"] for s in steps],
        "approved": False,
    }
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def load_plan(ws: Optional[Path] = None) -> Optional[dict]:
    p = plan_path(ws or workspace_root())
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_plan(ws: Optional[Path] = None) -> None:
    p = plan_path(ws or workspace_root())
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass


def missing_files(ws: Optional[Path] = None) -> list[str]:
    ws = ws or workspace_root()
    plan = load_plan(ws)
    if not plan:
        return []
    missing = []
    for step in plan.get("steps") or []:
        rel = (step.get("path") or "").strip().lstrip("./")
        if not rel:
            continue
        if not (ws / rel).exists():
            missing.append(rel)
    return missing


def existing_planned_files(ws: Optional[Path] = None) -> list[str]:
    ws = ws or workspace_root()
    plan = load_plan(ws)
    if not plan:
        return []
    out = []
    for step in plan.get("steps") or []:
        rel = (step.get("path") or "").strip().lstrip("./")
        if rel and (ws / rel).exists():
            out.append(rel)
    return out


def parse_plan_from_text(text: str) -> list[dict]:
    """
    Extract file list from model plan output.
    Supports:
      1. src/App.jsx — description
      1. `src/App.jsx` - description
      - src/App.jsx — description
    """
    if not text:
        return []
    steps = []
    seen = set()

    # Prefer region after PLAN / PROJECT PLAN / Files to create
    region = text
    for marker in ("Files to create:", "PROJECT PLAN", "PLAN:", "Plan:"):
        idx = text.find(marker)
        if idx != -1:
            region = text[idx:]
            break

    patterns = [
        # 1. path — desc   OR  1) path - desc
        re.compile(
            r"^\s*\d+\s*[\.\)\]]\s*`?([A-Za-z0-9_./\-]+?\.[A-Za-z0-9]+)`?\s*[-—:–]\s*(.+?)\s*$",
            re.MULTILINE,
        ),
        # 1. path   (no desc)
        re.compile(
            r"^\s*\d+\s*[\.\)\]]\s*`?([A-Za-z0-9_./\-]+?\.[A-Za-z0-9]+)`?\s*$",
            re.MULTILINE,
        ),
        # - path — desc
        re.compile(
            r"^\s*[-*]\s*`?([A-Za-z0-9_./\-]+?\.[A-Za-z0-9]+)`?\s*[-—:–]\s*(.+?)\s*$",
            re.MULTILINE,
        ),
    ]

    for pat in patterns:
        for m in pat.finditer(region):
            path = m.group(1).strip().lstrip("./")
            purpose = m.group(2).strip() if m.lastindex and m.lastindex >= 2 else ""
            # filter junk
            if path.lower() in ("e.g.", "example", "filename"):
                continue
            if "/" not in path and path.count(".") == 1 and not path.endswith(
                (".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".html", ".md", ".svg")
            ):
                # allow bare package.json etc
                if path not in ("package.json", "index.html", "vite.config.js", "vite.config.ts",
                                "tailwind.config.js", "tsconfig.json", "README.md"):
                    continue
            if path not in seen:
                seen.add(path)
                steps.append({"path": path, "purpose": purpose})
        if len(steps) >= 3:
            break

    return steps


def try_save_plan_from_llm_output(text: str, ws: Optional[Path] = None) -> bool:
    # preserve approved
    """If text looks like a plan, persist it. Returns True if saved."""
    if not text:
        return False
    lower = text.lower()
    looks_like_plan = any(
        k in lower
        for k in (
            "project plan",
            "files to create",
            "approve this plan",
            "\nplan:",
            "estimated files",
        )
    )
    # Also accept numbered file lists of 5+
    steps = parse_plan_from_text(text)
    if not steps:
        return False
    if not looks_like_plan and len(steps) < 5:
        return False

    goal = ""
    gm = re.search(r"Goal:\s*(.+)", text, re.IGNORECASE)
    if gm:
        goal = gm.group(1).strip()[:200]

    _prev = load_plan(ws)
    _was_approved = bool((_prev or {}).get("approved"))
    save_plan(steps, goal=goal, ws=ws)
    if _was_approved:
        set_plan_approved(True, ws=ws)  # preserve approved
    return True


def rejection_message_for_missing(missing: list[str], existing: list[str]) -> str:
    next_file = missing[0]
    # Write next 3 in one batch hint
    batch = missing[:3]
    return (
        "SYSTEM REJECTION — HALLUCINATION BLOCKED.\n"
        f"You claimed the build is complete, but DISK CHECK FAILED.\n\n"
        f"✅ On disk ({len(existing)}): {', '.join(existing[:12]) or 'none'}\n"
        f"❌ Missing ({len(missing)}): {', '.join(missing)}\n\n"
        f"You MUST call batch_edit or write_file NOW for these files:\n"
        + "\n".join(f"  - {p}" for p in batch)
        + (f"\n  - ... and {len(missing)-3} more" if len(missing) > 3 else "")
        + f"\n\nStart with `{next_file}`.\n"
        "FORBIDDEN: FINAL_ANSWER until every missing file exists on disk.\n"
        "FORBIDDEN: saying you created files you did not write."
    )


def approval_directive(missing: list[str], plan: Optional[dict] = None) -> str:
    total = len((plan or {}).get("steps") or missing)
    lines = "\n".join(f"  {i+1}. {p}" for i, p in enumerate(missing))
    return (
        "SYSTEM DIRECTIVE: Plan APPROVED. Execute the build.\n"
        f"Total planned files: {total}. Still missing: {len(missing)}.\n\n"
        "Write ALL missing files using batch_edit (2–4 files per call) or write_file.\n"
        "Order (dependencies first when possible):\n"
        f"{lines}\n\n"
        "Rules:\n"
        "1. ONLY batch_edit / write_file until disk has every file above.\n"
        "2. Do NOT FINAL_ANSWER early.\n"
        "3. Do NOT claim a file is created unless the tool OBSERVATION says written.\n"
        "4. Do NOT use edit_file on files that do not exist yet.\n"
        "5. Do NOT rewrite files already on disk — skip them, write the next missing one.\n"
        f"START NOW with: `{missing[0] if missing else 'FINAL_ANSWER'}`"
    )


def plan_status_block(ws: Optional[Path] = None) -> str:
    """Inject into system prompt every step."""
    ws = ws or workspace_root()
    plan = load_plan(ws)
    if not plan or not plan.get("steps"):
        return ""
    lines = ["## ACTIVE BUILD PLAN (DISK-ENFORCED — NOT OPTIONAL)"]
    if plan.get("goal"):
        lines.append(f"Goal: {plan['goal']}")
    miss = []
    for i, step in enumerate(plan["steps"], 1):
        rel = step["path"]
        ok = (ws / rel).exists()
        mark = "✅" if ok else "❌"
        if not ok:
            miss.append(rel)
        purpose = step.get("purpose") or ""
        lines.append(f"  {i}. {mark} `{rel}` {('— ' + purpose) if purpose else ''}")
    lines.append("")
    if miss:
        lines.append(f"PROGRESS: {len(plan['steps']) - len(miss)}/{len(plan['steps'])} on disk.")
        lines.append(f"NEXT FILE TO WRITE: `{miss[0]}`")
        lines.append("You may NOT output FINAL_ANSWER while any ❌ remains.")
    else:
        lines.append("PROGRESS: ALL FILES ON DISK. You may FINAL_ANSWER.")
    lines.append("")
    return "\n".join(lines)


def set_plan_approved(approved: bool = True, ws=None) -> None:
    """Mark plan as user-approved so runtime may force writes."""
    ws = ws or workspace_root()
    plan = load_plan(ws)
    if not plan:
        return
    plan["approved"] = bool(approved)
    ensure_oblivion_dir(ws)
    plan_path(ws).write_text(__import__("json").dumps(plan, indent=2), encoding="utf-8")


def is_plan_approved(ws=None) -> bool:
    plan = load_plan(ws or workspace_root())
    if not plan:
        return False
    return bool(plan.get("approved"))


def is_approval_message(text: str) -> bool:
    """yes OR voice like create every file / full project."""
    if not text:
        return False
    t = text.strip().lower()
    if t in (
        "yes", "y", "go", "proceed", "do it", "approved", "sure", "ok",
        "build", "start", "retry", "continue", "/continue",
    ):
        return True
    keys = (
        "create every", "create each", "create all", "write every", "write all",
        "build every", "build all", "build it", "full project", "start building",
        "make every", "make all", "generate every", "generate all",
        "implement the plan", "execute the plan", "do the plan",
        "every single file", "all the files", "all files in the plan",
    )
    return any(k in t for k in keys)


def claims_files_created(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    markers = (
        "successfully built", "created/modified", "created:", "files created",
        "project is complete", "scaffolded", "i have created", "i've created",
        "all files", "written to disk", "build complete",
    )
    return any(m in t for m in markers)
