import json
import re
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
    """
    Extract a complete JSON object starting at position `start`.
    Handles nested braces correctly by counting open/close.
    """
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
    import re
    # Strip anything that looks like quoted system prompt
    thought = re.sub(r'^["\']?\\n\\n.*?(?=The user|I |Let me|First|Now|Based)', '', thought, flags=re.DOTALL)
    # Strip leading newlines/quotes
    thought = thought.strip().strip('"').strip("'").strip()
    return thought


# HARDENED_PARSER_V1
# - Strips fake OBSERVATION/User/Assistant blocks the LLM tries to inject
# - ACTION beats FINAL_ANSWER (never let LLM hallucinate completion)
# - Strict ACTION pattern (must be followed by JSON)
_HALLUCINATION_COUNT = 0


def _get_hallucination_count() -> int:
    return _HALLUCINATION_COUNT


def _strip_fake_observations(text: str) -> str:
    """Remove any OBSERVATION/User:/Assistant: blocks the LLM tries to inject.
    Real observations are appended by the agent loop, NEVER by the LLM."""
    # Cut at the FIRST fake injection marker
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


def parse_llm_output(text: str):
    global _HALLUCINATION_COUNT

    # Strip <think>...</think> blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # CRITICAL: strip fake injected observations BEFORE looking for actions/answers
    cleaned = _strip_fake_observations(text)

    # Detect hallucination attempt: did stripping change the text?
    if cleaned != text:
        _HALLUCINATION_COUNT += 1

    text = cleaned

    # ── THOUGHT ──────────────────────────────────────────────────────────────
    thought = ""
    m = re.search(r"THOUGHT:\s*(.+?)(?=\nACTION:|\nFINAL_ANSWER:|$)", text, re.IGNORECASE | re.DOTALL)
    if m:
        thought = clean_thought(m.group(1))

    # ── ACTION FIRST (BEATS FINAL_ANSWER) ────────────────────────────────────
    # Strict pattern: ACTION: followed by optional whitespace + opening brace
    action_match = re.search(r"ACTION:\s*(?=\{)", text, re.IGNORECASE)
    if action_match:
        brace_start = text.find("{", action_match.end())
        if brace_start != -1:
            json_str = extract_json_object(text, brace_start)
            if json_str:
                try:
                    data = json.loads(json_str)
                    if "tool" in data:
                        # If FINAL_ANSWER ALSO appears later, count as hallucination
                        if re.search(r"FINAL_ANSWER:", text[brace_start:], re.IGNORECASE):
                            _HALLUCINATION_COUNT += 1
                        return ToolCall(
                            tool=data.get("tool", ""),
                            args=data.get("args", {}),
                            thought=thought,
                        )
                except json.JSONDecodeError:
                    pass

    # ── FINAL_ANSWER (only if no ACTION was parsed) ──────────────────────────
    for pattern in [r"FINAL_ANSWER:\s*(.+)", r"ANSWER:\s*(.+)", r"DONE:\s*(.+)"]:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            content = match.group(1).strip()
            # Also strip any fake continuation inside FINAL_ANSWER itself
            content = _strip_fake_observations(content)
            # STRIP LEAKED FORMAT MARKERS (so UI never shows "THOUGHT:" or "ACTION:")
            content = re.sub(r"^\s*THOUGHT\s*:.*?(?=\n\n|\Z)", "", content, flags=re.IGNORECASE | re.DOTALL).strip()
            content = re.sub(r"^\s*ACTION\s*:.*?(?=\n\n|\Z)", "", content, flags=re.IGNORECASE | re.DOTALL).strip()
            return FinalAnswer(content=content)

    # ── Fallback: scan entire text for any JSON with "tool" key ──────────────
    brace_pos = 0
    while True:
        brace_pos = text.find("{", brace_pos)
        if brace_pos == -1:
            break
        json_str = extract_json_object(text, brace_pos)
        if json_str:
            try:
                data = json.loads(json_str)
                if "tool" in data:
                    return ToolCall(
                        tool=data.get("tool", ""),
                        args=data.get("args", {}),
                        thought=thought,
                    )
            except json.JSONDecodeError:
                pass
        brace_pos += 1

    # ── No ACTION found — treat as final answer if there is content ──────────
    if len(text) > 20 and "ACTION" not in text.upper():
        # Strip leaked THOUGHT: prefix even in fallback mode
        # Handles both "THOUGHT: ...\n..." AND "THOUGHT: ..." (no newline, whole thing is thought)
        cleaned_text = text
        # Pattern A: THOUGHT: followed by content then a newline then more content
        m = re.match(r"\s*THOUGHT\s*:\s*(.+?)\n(.+)", cleaned_text, re.IGNORECASE | re.DOTALL)
        if m:
            # Keep only the part AFTER the thought line
            cleaned_text = m.group(2).strip()
        else:
            # Pattern B: entire text is "THOUGHT: ..." — strip the prefix, keep the content
            m2 = re.match(r"\s*THOUGHT\s*:\s*(.+)", cleaned_text, re.IGNORECASE | re.DOTALL)
            if m2:
                cleaned_text = m2.group(1).strip()
        if not cleaned_text.strip():
            cleaned_text = text
        return FinalAnswer(content=cleaned_text)

    return None


def is_garbage_output(text: str) -> bool:
    """Detect when LLM produces non-sense repetitive characters (context overflow symptom).
    
    Examples of garbage:
      "====================" (repeated equals)
      "////////////////////" (repeated slashes)
      "                    " (just whitespace)
    """
    if not text or len(text) < 20:
        return False
    # Strip whitespace
    stripped = text.strip()
    if not stripped:
        return True
    # Check if >70% is a single repeating char
    from collections import Counter
    counts = Counter(stripped)
    most_common_char, most_common_count = counts.most_common(1)[0]
    ratio = most_common_count / len(stripped)
    if ratio > 0.7 and most_common_char in "=-_/\\|#*~.":
        return True
    return False
