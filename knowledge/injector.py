"""
knowledge/injector.py - Build the knowledge-injection block for the system prompt.

Given a set of tech tags, load the corresponding knowledge packs
and format them into a compact block to inject into the system prompt.
"""
from __future__ import annotations

from pathlib import Path
from typing import Set, Optional, List

from knowledge.detector import detect_tech_stack, detect_from_request, describe_stack

PACKS_DIR = Path(__file__).parent / "packs"
MAX_PACKS = 2  # only top-2 to keep prompt under 12k tokens total
MAX_PACK_CHARS = 8000  # ~2k tokens per pack
MAX_TOTAL_CHARS = 16000  # ~4k tokens of knowledge MAX

PACK_PRIORITY = [
    "debugging",
    "database",
    "security",
    "testing",
    "react",
    "nextjs",
    "vue",
    "tailwind",
    "typescript",
    "django",
    "flask",
    "fastapi",
    "frappe",
    "python_general",
    "nodejs_backend",
    "deployment",
    "docker",
    "svelte",
]


def list_available_packs() -> List[str]:
    """Return names of all .md packs that exist."""
    if not PACKS_DIR.exists():
        return []
    return sorted(p.stem for p in PACKS_DIR.glob("*.md"))


def load_pack(name: str) -> Optional[str]:
    """Read one pack file, truncated to MAX_PACK_CHARS."""
    f = PACKS_DIR / f"{name}.md"
    if not f.exists():
        return None
    try:
        content = f.read_text(encoding="utf-8")
        if len(content) > MAX_PACK_CHARS:
            content = content[:MAX_PACK_CHARS] + "\n... (truncated for token budget) ..."
        return content
    except Exception:
        return None


def build_knowledge_block(
    workspace: str = None,
    user_message: str = "",
    extra_tags: Set[str] = None,
) -> str:
    """
    Detect tech stack + load relevant knowledge packs.

    Returns a formatted block ready to inject into the system prompt,
    or empty string if nothing to inject.
    """
    available = set(list_available_packs())
    if not available:
        return ""

    # USER INTENT WINS over workspace inference.
    # If user says "django", we load django even if workspace is React.
    user_tags = detect_from_request(user_message)
    workspace_tags = detect_tech_stack(workspace)

    # Pinned: anything the user explicitly mentioned + always-on packs
    pinned = (user_tags | {"debugging"}) & available

    # Filler: workspace inference, used to fill remaining slots
    filler = (workspace_tags - user_tags) & available

    if extra_tags:
        pinned |= (extra_tags & available)

    if not pinned and not filler:
        return ""

    # Build final ordered list:
    # 1. Pinned tags first, in priority order
    # 2. Then filler tags, in priority order
    ordered = []
    for t in PACK_PRIORITY:
        if t in pinned:
            ordered.append(t)
    for t in pinned:
        if t not in ordered:
            ordered.append(t)
    for t in PACK_PRIORITY:
        if t in filler and t not in ordered:
            ordered.append(t)
    for t in filler:
        if t not in ordered:
            ordered.append(t)

    tags = pinned | filler

    loaded = []
    total = 0
    for name in ordered[:MAX_PACKS]:
        pack = load_pack(name)
        if not pack:
            continue
        if total + len(pack) > MAX_TOTAL_CHARS:
            break
        loaded.append((name, pack))
        total += len(pack)

    if not loaded:
        return ""

    stack_label = describe_stack(tags)
    pack_names = ", ".join(name for name, _ in loaded)

    header = (
        "\n────────────────────────────────────────────────────────────\n"
        "# DOMAIN KNOWLEDGE (auto-loaded for: " + stack_label + ")\n"
        "# Packs loaded: " + pack_names + "\n"
        "────────────────────────────────────────────────────────────\n\n"
        "The following are battle-tested patterns and common-error fixes for the\n"
        "technologies detected in this workspace/request. USE this knowledge to make\n"
        "correct decisions BEFORE writing code. If a CRITICAL note here applies to\n"
        "your task, follow it exactly.\n\n"
    )

    body = "\n\n".join("## KNOWLEDGE PACK: " + name + "\n\n" + content for name, content in loaded)

    footer = (
        "\n\n────────────────────────────────────────────────────────────\n"
        "# END DOMAIN KNOWLEDGE\n"
        "────────────────────────────────────────────────────────────\n"
    )

    return header + body + footer


def get_loaded_pack_names(
    workspace: str = None,
    user_message: str = "",
) -> List[str]:
    """Return just the names of packs that WOULD be loaded (for /knowledge cmd)."""
    available = set(list_available_packs())
    user_tags = detect_from_request(user_message)
    workspace_tags = detect_tech_stack(workspace)
    pinned = (user_tags | {"debugging"}) & available
    filler = (workspace_tags - user_tags) & available
    ordered = []
    for t in PACK_PRIORITY:
        if t in pinned:
            ordered.append(t)
    for t in pinned:
        if t not in ordered:
            ordered.append(t)
    for t in PACK_PRIORITY:
        if t in filler and t not in ordered:
            ordered.append(t)
    for t in filler:
        if t not in ordered:
            ordered.append(t)
    return ordered[:MAX_PACKS]
