"""
Brain upgrade: Planning, Verification, and Memory.

Three new capabilities:
1. PLAN   - structured execution plans for complex tasks
2. VERIFY - syntax/test checks after code writes
3. MEMORY - persistent workspace knowledge (MEMORY.md)
"""
import os
import subprocess
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

# ── MEMORY ────────────────────────────────────────────────────────────────────
def get_memory_path() -> Path:
    """MEMORY.md lives in workspace root."""
    workspace = Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()
    return workspace / "MEMORY.md"


def load_memory() -> str:
    """Read MEMORY.md content. Empty string if no memory yet."""
    p = get_memory_path()
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def remember(note: str, category: str = "general") -> str:
    """Append a note to MEMORY.md under a category."""
    p = get_memory_path()
    timestamp = __import__("datetime").datetime.now().strftime("%Y-%m-%d")

    # Read existing
    existing = load_memory()
    sections: dict[str, list[str]] = {}
    current_section = None

    for line in existing.splitlines():
        if line.startswith("## "):
            current_section = line[3:].strip().lower()
            sections[current_section] = []
        elif current_section is not None:
            sections[current_section].append(line)

    # Add new note
    category = category.lower()
    if category not in sections:
        sections[category] = []
    sections[category].append(f"- ({timestamp}) {note}")

    # Rebuild
    out_lines = [
        "# Project Memory",
        "",
        "_Notes and conventions remembered by Oblivion across sessions._",
        "",
    ]
    for sec_name in sorted(sections.keys()):
        out_lines.append(f"## {sec_name.title()}")
        out_lines.append("")
        for entry in sections[sec_name]:
            if entry.strip():
                out_lines.append(entry)
        out_lines.append("")

    p.write_text("\n".join(out_lines), encoding="utf-8")
    return f"Remembered ({category}): {note}"


def recall(category: str = None) -> str:
    """Get memory, optionally filtered by category."""
    content = load_memory()
    if not content:
        return "No memory yet. The agent learns over time using remember()."

    if category is None:
        return content

    # Filter by section
    category = category.lower()
    lines = content.splitlines()
    capture = False
    out = []
    for line in lines:
        if line.startswith("## "):
            capture = line[3:].strip().lower() == category
        if capture:
            out.append(line)
    return "\n".join(out) if out else f"No memory in category: {category}"


def get_memory_summary() -> dict:
    """Quick stats about memory file."""
    p = get_memory_path()
    if not p.exists():
        return {"exists": False, "notes": 0, "categories": 0}
    content = load_memory()
    notes = content.count("\n- ")
    categories = content.count("\n## ")
    return {
        "exists": True,
        "notes": notes,
        "categories": categories,
        "size_bytes": len(content.encode("utf-8")),
        "path": str(p),
    }


# ── VERIFICATION ──────────────────────────────────────────────────────────────
def verify_code(path: str, language: str = "auto") -> dict:
    """
    Run a syntax check on a file.
    Returns {ok: bool, message: str, details: str}.
    """
    workspace = Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()
    p = workspace / path if not Path(path).is_absolute() else Path(path)

    if not p.exists():
        return {"ok": False, "message": f"File not found: {path}", "details": ""}

    # Auto-detect language
    if language == "auto":
        suffix = p.suffix.lower()
        lang_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".jsx": "javascript", ".tsx": "typescript",
            ".json": "json", ".sh": "bash", ".yaml": "yaml", ".yml": "yaml",
        }
        language = lang_map.get(suffix, "unknown")

    if language == "python":
        return _verify_python(p)
    elif language in ("javascript", "typescript"):
        return _verify_js(p)
    elif language == "json":
        return _verify_json(p)
    elif language == "bash":
        return _verify_bash(p)
    elif language in ("yaml", "yml"):
        return _verify_yaml(p)
    else:
        return {
            "ok": True,
            "message": f"No verifier for {language}, skipping",
            "details": ""
        }


def _verify_python(p: Path) -> dict:
    try:
        result = subprocess.run(
            ["python3", "-m", "py_compile", str(p)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return {"ok": True, "message": "Python syntax OK", "details": ""}
        return {
            "ok": False,
            "message": "Python syntax error",
            "details": result.stderr.strip()[:500],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Verify timeout", "details": ""}
    except Exception as e:
        return {"ok": False, "message": f"Verify error: {e}", "details": ""}


def _verify_js(p: Path) -> dict:
    if not _has_command("node"):
        return {"ok": True, "message": "node not installed, skipping JS check", "details": ""}
    try:
        result = subprocess.run(
            ["node", "--check", str(p)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return {"ok": True, "message": "JS syntax OK", "details": ""}
        return {
            "ok": False,
            "message": "JS syntax error",
            "details": result.stderr.strip()[:500],
        }
    except Exception as e:
        return {"ok": False, "message": f"Verify error: {e}", "details": ""}


def _verify_json(p: Path) -> dict:
    try:
        json.loads(p.read_text(encoding="utf-8"))
        return {"ok": True, "message": "JSON valid", "details": ""}
    except json.JSONDecodeError as e:
        return {"ok": False, "message": "JSON invalid", "details": str(e)[:500]}
    except Exception as e:
        return {"ok": False, "message": f"Verify error: {e}", "details": ""}


def _verify_bash(p: Path) -> dict:
    if not _has_command("bash"):
        return {"ok": True, "message": "bash not found, skipping", "details": ""}
    try:
        result = subprocess.run(
            ["bash", "-n", str(p)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return {"ok": True, "message": "Bash syntax OK", "details": ""}
        return {"ok": False, "message": "Bash syntax error", "details": result.stderr.strip()[:500]}
    except Exception as e:
        return {"ok": False, "message": f"Verify error: {e}", "details": ""}


def _verify_yaml(p: Path) -> dict:
    try:
        import yaml
        yaml.safe_load(p.read_text(encoding="utf-8"))
        return {"ok": True, "message": "YAML valid", "details": ""}
    except ImportError:
        return {"ok": True, "message": "pyyaml not installed, skipping", "details": ""}
    except Exception as e:
        return {"ok": False, "message": "YAML invalid", "details": str(e)[:500]}


def _has_command(name: str) -> bool:
    import shutil
    return shutil.which(name) is not None


# ── PLANNING ──────────────────────────────────────────────────────────────────
@dataclass
class Plan:
    goal: str
    steps: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    estimate: str = ""
    approved: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# Keywords that indicate a complex task needing planning
COMPLEX_KEYWORDS = [
    "refactor", "rewrite", "restructure", "redesign", "architecture",
    "migrate", "convert", "translate", "port",
    "add error handling", "add tests", "add logging",
    "across all", "in all files", "throughout", "everywhere",
    "implement", "build a", "create a system",
]


def looks_complex(user_message: str) -> bool:
    """Heuristic: should this task trigger planning mode?"""
    msg = user_message.lower()
    # Long message hints at complexity
    if len(msg.split()) > 25:
        return True
    # Contains complex keywords
    for kw in COMPLEX_KEYWORDS:
        if kw in msg:
            return True
    return False


def format_plan_panel(plan: Plan) -> str:
    """Format plan for display in chat (rich markup)."""
    lines = [
        f"[bold #00ff9f]Goal:[/bold #00ff9f] {plan.goal}",
        "",
        "[bold #00ff9f]Steps:[/bold #00ff9f]",
    ]
    for i, step in enumerate(plan.steps, 1):
        lines.append(f"  {i}. {step}")

    if plan.risks:
        lines.append("")
        lines.append("[bold #ff006e]Risks:[/bold #ff006e]")
        for r in plan.risks:
            lines.append(f"  ⚠ {r}")

    if plan.estimate:
        lines.append("")
        lines.append(f"[bold #b537f2]Estimate:[/bold #b537f2] {plan.estimate}")

    return "\n".join(lines)


def format_plan_speech(plan: Plan, name: str = "boss") -> str:
    """Short version for FRIDAY to speak."""
    n_steps = len(plan.steps)
    parts = [f"Got a plan, {name}."]
    parts.append(f"{n_steps} step{'s' if n_steps != 1 else ''}.")
    if plan.risks:
        parts.append(f"{len(plan.risks)} risk{'s' if len(plan.risks) != 1 else ''} to note.")
    parts.append("Plan's on screen for review. Approve when ready.")
    return " ".join(parts)
