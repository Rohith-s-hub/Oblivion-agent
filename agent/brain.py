"""
Brain upgrade: Planning, Verification, and Memory.
"""
import os
import subprocess
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


def get_memory_path() -> Path:
    workspace = Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()
    return workspace / "MEMORY.md"


def load_memory() -> str:
    p = get_memory_path()
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def remember(note: str, category: str = "general") -> str:
    p = get_memory_path()
    timestamp = __import__("datetime").datetime.now().strftime("%Y-%m-%d")

    existing = load_memory()
    sections: dict[str, list[str]] = {}
    current_section = None

    for line in existing.splitlines():
        if line.startswith("## "):
            current_section = line[3:].strip().lower()
            sections[current_section] = []
        elif current_section is not None:
            sections[current_section].append(line)

    category = category.lower()
    if category not in sections:
        sections[category] = []
    sections[category].append(f"- ({timestamp}) {note}")

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
    content = load_memory()
    if not content:
        return "No memory yet. Use remember() to teach the agent."

    if category is None:
        return content

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


def verify_code(path: str, language: str = "auto") -> dict:
    workspace = Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()
    p = workspace / path if not Path(path).is_absolute() else Path(path)

    if not p.exists():
        return {"ok": False, "message": f"File not found: {path}", "details": ""}

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
        return {"ok": True, "message": f"No verifier for {language}", "details": ""}


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
    except Exception as e:
        return {"ok": False, "message": f"Verify error: {e}", "details": ""}


def _verify_js(p: Path) -> dict:
    import shutil
    if not shutil.which("node"):
        return {"ok": True, "message": "node missing, skipping check", "details": ""}
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
    except Exception as e:
        return {"ok": False, "message": "JSON invalid", "details": str(e)[:500]}


def _verify_bash(p: Path) -> dict:
    import shutil
    if not shutil.which("bash"):
        return {"ok": True, "message": "bash missing, skipping", "details": ""}
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
        return {"ok": True, "message": "pyyaml missing, skipping", "details": ""}
    except Exception as e:
        return {"ok": False, "message": "YAML invalid", "details": str(e)[:500]}


@dataclass
class Plan:
    goal: str
    steps: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    estimate: str = ""
    approved: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


KEEP_LAST_N = int(os.getenv("CONTEXT_KEEP_LAST_N", "6"))
SUMMARIZE_THRESHOLD = int(os.getenv("CONTEXT_SUMMARIZE_THRESHOLD", "10"))


def needs_compression(messages: list) -> bool:
    if len(messages) <= SUMMARIZE_THRESHOLD:
        return False
    total = sum(len(m.get("content", "")) // 4 for m in messages)
    return total > 8000


def compress_conversation(
    messages: list,
    summarize_fn: Optional[Callable[[str], str]] = None,
) -> list:
    if not needs_compression(messages):
        return messages

    if len(messages) < 2:
        return messages

    first = messages[0]
    last_n = messages[-KEEP_LAST_N:]
    middle = messages[1:-KEEP_LAST_N]

    if not middle:
        return messages

    middle_text = "\n\n".join(
        f"[{m.get('role', '?').upper()}]: {m.get('content', '')[:500]}"
        for m in middle
    )

    if summarize_fn:
        try:
            summary = summarize_fn(middle_text)
        except Exception:
            summary = f"[Previous {len(middle)} messages truncated to save tokens]"
    else:
        summary = f"[Previous {len(middle)} messages truncated to save tokens]"

    summary_msg = {
        "role": "system",
        "content": f"## CONVERSATION SUMMARY (so far)\n\n{summary}\n\n## RECENT MESSAGES:",
    }

    return [first, summary_msg] + last_n


def summarize_via_llm(llm_client, text: str) -> str:
    prompt = f"""Summarize the following conversation history in 3-5 bullet points.
Focus on: what was attempted, what was decided, what files were created/modified, what errors occurred.

CONVERSATION:
{text[:6000]}

SUMMARY (bullets only, no preamble):"""

    try:
        if hasattr(llm_client, "chat"):
            response = llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                stream=False,
            )
            return response.strip() if response else "[Summary unavailable]"
    except Exception as e:
        return f"[Summary failed: {type(e).__name__}]"
    return "[Summary unavailable]"
