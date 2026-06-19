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
        return FinalAnswer(content=text)

    return None
