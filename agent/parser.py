import json
import re
from collections import Counter
from dataclasses import dataclass


@dataclass
class ToolCall:
    tool: str
    args: dict
    thought: str = ""


@dataclass
class FinalAnswer:
    content: str


def extract_json_object(text: str, start: int) -> str | None:
    """Extract a complete JSON object starting at position start by tracking brace depth."""
    if start >= len(text) or text[start] != "{":
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape_next:
            escape_next = False
            continue

        if ch == "\\" and in_string:
            escape_next = True
            continue

        if ch == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i+1]

    return None


def clean_thought(thought: str) -> str:
    """Remove leaked system prompt fragments from thought text."""
    thought = re.sub(
        r'^["\']?\n\n.*?(?=The user|I\b|Let me|First|Now|Based)',
        '', thought, flags=re.DOTALL
    )
    return thought.strip().strip('"').strip("'").strip()


def _strip_fake_observations(text: str) -> str:
    """Cut off fake OBSERVATION/User/Assistant blocks injected by LLM."""
    markers = [
        r"\n\s*OBSERVATION\s*\(",
        r"\n\s*OBSERVATION:",
        r"\n\s*###\s*User",
        r"\n\s*###\s*Assistant",
        r"\n\s*User:",
        r"\n\s*Assistant:",
    ]
    earliest = len(text)
    for pat in markers:
        m = re.search(pat, text, re.IGNORECASE)
        if m and m.start() < earliest:
            earliest = m.start()
    return text[:earliest].rstrip()


def _robust_json_loads(json_str: str) -> dict | None:
    """Tolerant JSON parser that handles raw newlines, control chars, and minor syntax flaws."""
    if not json_str:
        return None

    try:
        data = json.loads(json_str, strict=False)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    try:
        cleaned = re.sub(r',\s*([}\]])', r'\1', json_str)
        data = json.loads(cleaned, strict=False)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    return None


def parse_llm_output(text: str):
    if not text or not text.strip():
        return None

    # Strip thinking blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # Strip Rich markup tags leaked into output
    _rich_patterns = [
        r"\[/[^\]]*\]",
        r"\[(?:dim|bold|italic|underline)(?:\s+[^\]]*)?\]",
        r"\[#[0-9a-fA-F]{3,8}(?:\s+[^\]]*)?\]",
    ]
    for pat in _rich_patterns:
        text = re.sub(pat, "", text)

    # Cut off fake observations
    text = _strip_fake_observations(text)

    # ── THOUGHT ──────────────────────────────────────────────────────────────
    thought = ""
    m = re.search(r"THOUGHT:\s*(.+?)(?=\nACTION:|ACTION:|\nFINAL_ANSWER:|$)", text, re.IGNORECASE | re.DOTALL)
    if m:
        thought = clean_thought(m.group(1))

    # ── ACTION FIRST (BEATS FINAL_ANSWER) ────────────────────────────────────
    # Handles ACTION:\n```json\n{...}\n``` or ACTION:\n{...}
    action_match = re.search(r"ACTION:\s*(?:```(?:json)?\s*)?(\{)", text, re.IGNORECASE)
    if action_match:
        brace_start = action_match.start(1)
        json_str = extract_json_object(text, brace_start)
        if json_str:
            data = _robust_json_loads(json_str)
            if data and "tool" in data:
                return ToolCall(
                    tool=data.get("tool", ""),
                    args=data.get("args", {}) if isinstance(data.get("args"), dict) else {},
                    thought=thought,
                )

    # ── FINAL_ANSWER (only if no ACTION was parsed) ──────────────────────────
    for pattern in [r"FINAL_ANSWER:\s*(.+)", r"ANSWER:\s*(.+)", r"DONE:\s*(.+)"]:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            content = match.group(1).strip()
            content = _strip_fake_observations(content)
            content = re.sub(r"^\s*THOUGHT\s*:.*?(?=\n\n|\Z)", "", content, flags=re.IGNORECASE | re.DOTALL).strip()
            content = re.sub(r"^\s*ACTION\s*:.*?(?=\n\n|\Z)", "", content, flags=re.IGNORECASE | re.DOTALL).strip()
            return FinalAnswer(content=content)

    # ── SMART RECOVERY: Auto-extract markdown code blocks for planned files ──
    if not re.search(r"FINAL_ANSWER:", text, re.IGNORECASE):
        code_block_match = re.search(
            r"(?:file|path)?:?\s*[`'\"]*([a-zA-Z0-9_./\-]+\.[a-zA-Z0-9]+)[`'\"]*.*?\n```(?:[a-zA-Z0-9]+\n)?(.*?)```",
            text, re.DOTALL | re.IGNORECASE
        )
        if not code_block_match:
            code_block_match = re.search(r"```(?:[a-zA-Z0-9]+\n)?(.*?)```", text, re.DOTALL)

        if code_block_match:
            target_file = None
            if code_block_match.lastindex and code_block_match.lastindex >= 2 and code_block_match.group(1):
                potential = code_block_match.group(1).strip()
                if "." in potential and not potential.startswith("http"):
                    target_file = potential

            if not target_file:
                try:
                    from agent.plan_guard import missing_files
                    missing = missing_files()
                    if missing:
                        target_file = missing[0]
                except Exception:
                    pass

            code_content = code_block_match.group(code_block_match.lastindex).strip() if code_block_match else ""
            if target_file and code_content and len(code_content) > 5:
                return ToolCall(
                    tool="write_file",
                    args={"path": target_file, "content": code_content},
                    thought=thought or f"Auto-writing {target_file} from code block",
                )

    # ── FALLBACK SCAN: Search entire text for any JSON with "tool" key ───────
    if not re.search(r"FINAL_ANSWER:", text, re.IGNORECASE):
        brace_pos = 0
        while True:
            brace_pos = text.find("{", brace_pos)
            if brace_pos == -1:
                break
            json_str = extract_json_object(text, brace_pos)
            if json_str:
                data = _robust_json_loads(json_str)
                if data and "tool" in data and isinstance(data.get("args"), dict):
                    return ToolCall(
                        tool=data.get("tool", ""),
                        args=data.get("args", {}),
                        thought=thought,
                    )
            brace_pos += 1

    # ── LAST RESORT: Treat as final answer if non-empty text ───────────────
    if len(text) > 15 and "ACTION" not in text.upper():
        cleaned_text = text
        m = re.match(r"\s*THOUGHT\s*:\s*(.+?)\n(.+)", cleaned_text, re.IGNORECASE | re.DOTALL)
        if m:
            cleaned_text = m.group(2).strip()
        else:
            m2 = re.match(r"\s*THOUGHT\s*:\s*(.+)", cleaned_text, re.IGNORECASE | re.DOTALL)
            if m2:
                cleaned_text = m2.group(1).strip()
        if not cleaned_text.strip():
            cleaned_text = text
        return FinalAnswer(content=cleaned_text)

    return None


def is_garbage_output(text: str) -> bool:
    if not text or len(text) < 20:
        return False
    stripped = text.strip()
    if not stripped:
        return True
    counts = Counter(stripped)
    most_common_char, most_common_count = counts.most_common(1)[0]
    ratio = most_common_count / len(stripped)
    if ratio > 0.7 and most_common_char in "=-_/\\|#*~.":
        return True
    return False
