"""
agent/runtime.py — Unified Async Agent Runtime (Phase 2A)

Single source of truth for the agent's THOUGHT → ACTION → OBSERVATION loop.
Both the CLI and the TUI delegate to AgentRuntime.run_async().

The runtime emits events via callbacks so the UI layer can:
  - render streamed tokens
  - render tool calls + results
  - request approval for write/edit/bash
  - render the final answer
  - trigger voice playback
without ever touching the core loop logic.

Side benefits baked in:
  - Per-session JSONL log at ~/.oblivion/sessions/<session_id>.jsonl
  - Tool timing (ms) surfaced via on_tool_done callback
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from agent.parser import parse_llm_output, ToolCall, FinalAnswer, is_garbage_output
from agent.brain import compress_conversation, needs_compression, summarize_via_llm
from tools.registry import dispatch


def _estimate_tokens(messages: list) -> int:
    """Rough token count: ~4 chars = 1 token."""
    total = 0
    for m in messages:
        c = m.get("content", "")
        if isinstance(c, str):
            total += len(c) // 4
    return total


def _summarize_conversation(conversation: list, keep_recent: int = 4) -> list:
    """Compress conversation: keep first user msg + summarize middle + keep last N turns.
    
    Returns new conversation list. Original is unchanged.
    """
    if len(conversation) <= keep_recent + 1:
        return conversation  # too short to summarize

    first_user = conversation[0]  # the original user task
    recent = conversation[-keep_recent:]  # last N turns
    middle = conversation[1:-keep_recent]  # to be summarized

    # Extract key facts from middle
    summary_parts = []
    files_touched = set()
    tools_used = {}
    for msg in middle:
        c = msg.get("content", "")
        if not isinstance(c, str):
            continue
        # Tool observations
        if c.startswith("OBSERVATION"):
            # Extract filenames
            import re
            for m in re.finditer(r"(?:Written|Created|Edited|Read).+?([\w./\-_]+\.\w+)", c):
                files_touched.add(m.group(1))
            for m in re.finditer(r"(?:result of )(\w+)", c):
                t = m.group(1)
                tools_used[t] = tools_used.get(t, 0) + 1
        # Agent THOUGHTs
        elif "THOUGHT:" in c:
            import re
            m = re.search(r"THOUGHT:\s*(.+?)(?:\n|ACTION|FINAL)", c, re.DOTALL)
            if m:
                summary_parts.append(m.group(1).strip()[:120])

    summary_text = "PREVIOUS CONVERSATION SUMMARY (compressed to save tokens):\n"
    if files_touched:
        summary_text += "Files already touched: " + ", ".join(sorted(files_touched)[:15]) + "\n"
    if tools_used:
        summary_text += "Tools used so far: " + ", ".join(f"{k}({v})" for k, v in sorted(tools_used.items())) + "\n"
    if summary_parts:
        summary_text += "Key decisions:\n" + "\n".join(f"- {s}" for s in summary_parts[-8:]) + "\n"
    summary_text += "\nResume from current state. Do NOT redo what is listed above."

    summary_msg = {"role": "user", "content": summary_text}

    return [first_user, summary_msg] + recent

# ── Session log ──────────────────────────────────────────────────────────────
from agent.paths import sessions_dir as _sessions_dir
SESSIONS_DIR = _sessions_dir()


def _log_event(session_id: int, kind: str, data: dict) -> None:
    """Append one JSON line to the session log. Best-effort; never raises."""
    try:
        path = SESSIONS_DIR / f"{session_id}.jsonl"
        entry = {"ts": time.time(), "kind": kind, **data}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass


# ── Callback contract ────────────────────────────────────────────────────────
@dataclass
class RuntimeCallbacks:
    """All UI hooks. Any callback can be None — runtime will no-op it."""

    # Streaming: called per token while the LLM is producing output
    on_token: Optional[Callable[[str], None]] = None

    # Step lifecycle
    on_llm_start: Optional[Callable[[int], Awaitable[None]]] = None        # step_idx
    on_llm_end:   Optional[Callable[[int, str, int], Awaitable[None]]] = None  # step_idx, output, tokens

    # Tool lifecycle
    on_thought:   Optional[Callable[[str], Awaitable[None]]] = None        # thought text
    on_tool_start: Optional[Callable[[str, dict], Awaitable[Any]]] = None  # name, args -> handle (e.g. ActivityItem)
    on_tool_done:  Optional[Callable[[Any, str, int], Awaitable[None]]] = None  # handle, result, ms

    # Final / errors
    on_final: Optional[Callable[[str], Awaitable[None]]] = None
    on_error: Optional[Callable[[str], Awaitable[None]]] = None
    on_parse_failure: Optional[Callable[[str], Awaitable[None]]] = None

    # APPROVAL — UI must implement this for write/edit/bash safety
    # Returns True to approve, False to deny. If None, auto-approves.
    on_approve_tool: Optional[Callable[[str, dict], Awaitable[bool]]] = None


# ── Runtime ──────────────────────────────────────────────────────────────────
class AgentRuntime:
    """The single agent loop. UI-agnostic."""

    def __init__(self, agent, session_id: int, max_iterations: int = 20):
        """
        agent: an instance of agent.core.Agent (we use agent.llm, agent.system_prompt, agent.conversation)
        session_id: int from db.store.create_session
        """
        self.agent = agent
        self.session_id = session_id
        self.max_iterations = max_iterations

    async def run_async(
        self,
        user_message: str,
        callbacks: RuntimeCallbacks,
    ) -> Optional[str]:
        """Run one full user-turn. Returns the final-answer text, or None on error."""
        cb = callbacks

        self.agent.conversation.append({"role": "user", "content": user_message})
        # Refresh system prompt with knowledge packs relevant to this user request
        try:
            self.agent.refresh_prompt(user_message)
        except Exception:
            pass  # best-effort; never break the loop
        _log_event(self.session_id, "user_message", {"content": user_message})

        # LOOP DETECTION: track recent tool calls to catch the agent repeating itself
        recent_calls: list[str] = []
        consecutive_reads = 0  # exploration loop guard

        for i in range(self.max_iterations):
            step = i + 1

            if cb.on_llm_start:
                try:
                    await cb.on_llm_start(step)
                except Exception:
                    pass

            # AUTO-SUMMARIZATION: if conversation is getting big, compress middle
            est_tokens = _estimate_tokens(self.agent.conversation)
            if est_tokens > 6000 and len(self.agent.conversation) > 6:
                original_count = len(self.agent.conversation)
                self.agent.conversation = _summarize_conversation(self.agent.conversation, keep_recent=4)
                new_count = len(self.agent.conversation)
                new_tokens = _estimate_tokens(self.agent.conversation)
                _log_event(self.session_id, "summarized", {
                    "before_msgs": original_count, "after_msgs": new_count,
                    "before_tokens": est_tokens, "after_tokens": new_tokens,
                })
                if cb.on_thought:
                    try:
                        await cb.on_thought(
                            "[context compressed: " + str(original_count) + " msgs / " +
                            str(est_tokens) + " tok -> " + str(new_count) + " msgs / " +
                            str(new_tokens) + " tok]"
                        )
                    except Exception:
                        pass

            # ── CONTEXT COMPRESSION ───────────────────────────────────────
            # If conversation grew too long, summarize the middle so we don't blow
            # past the LLM context window.
            if needs_compression(self.agent.conversation):
                try:
                    def _summary_fn(text):
                        return summarize_via_llm(self.agent.llm, text)
                    before_count = len(self.agent.conversation)
                    self.agent.conversation = compress_conversation(
                        self.agent.conversation,
                        summarize_fn=_summary_fn,
                    )
                    after_count = len(self.agent.conversation)
                    _log_event(self.session_id, "context_compressed", {
                        "step": step,
                        "before_msgs": before_count,
                        "after_msgs": after_count,
                    })
                except Exception as e:
                    _log_event(self.session_id, "compression_error", {
                        "step": step, "error": str(e)[:200],
                    })

            messages = [
                {"role": "system", "content": self.agent.system_prompt}
            ] + self.agent.conversation

            # RATE LIMIT GUARD: small delay to stay under free-tier RPM limits
            # Gemini free: 10 req/min. With 1.5s delay we max out at 40 req/min (safe).
            import time as _time
            _time.sleep(1.5)

            # Stream LLM output to UI via callback
            llm_output = await self._stream_llm(messages, cb)
            if llm_output is None:
                return None

            self.agent.conversation.append({"role": "assistant", "content": llm_output})
            _log_event(self.session_id, "llm_output", {"step": step, "chars": len(llm_output)})

            if cb.on_llm_end:
                try:
                    await cb.on_llm_end(step, llm_output, len(llm_output) // 4)
                except Exception:
                    pass

            # Parse
            parsed = parse_llm_output(llm_output)

            # ─── Final answer
            if isinstance(parsed, FinalAnswer):
                _log_event(self.session_id, "final_answer", {"content": parsed.content})
                if cb.on_final:
                    try:
                        await cb.on_final(parsed.content)
                    except Exception:
                        pass
                return parsed.content

            # ─── Tool call
            if isinstance(parsed, ToolCall):
                tool_name = parsed.tool
                tool_args = parsed.args or {}

                if parsed.thought and cb.on_thought:
                    try:
                        await cb.on_thought(parsed.thought)
                    except Exception:
                        pass

                # 'finish' tool: short-circuit to final
                if tool_name == "finish":
                    summary = tool_args.get("summary", "Task complete.")
                    _log_event(self.session_id, "finish", {"summary": summary})
                    if cb.on_final:
                        try:
                            await cb.on_final(summary)
                        except Exception:
                            pass
                    return summary

                # Notify tool start, get a handle the UI can update later
                handle = None
                if cb.on_tool_start:
                    try:
                        handle = await cb.on_tool_start(tool_name, tool_args)
                    except Exception:
                        handle = None

                _log_event(self.session_id, "tool_start", {
                    "step": step, "tool": tool_name, "args": tool_args,
                })

                # LOOP DETECTION: if same tool+args called 3 times in a row, force the agent to stop
                call_signature = f"{tool_name}:{json.dumps(tool_args, sort_keys=True, default=str)[:200]}"
                recent_calls.append(call_signature)
                if len(recent_calls) > 3:
                    recent_calls.pop(0)
                if len(recent_calls) == 3 and recent_calls[0] == recent_calls[1] == recent_calls[2]:
                    loop_msg = (
                        f"LOOP DETECTED: You called {tool_name} with identical arguments 3 times. "
                        f"This is wasting time. STOP repeating. Either: (a) try a DIFFERENT tool/argument, "
                        f"or (b) give FINAL_ANSWER with what you know so far. Do NOT call {tool_name} again."
                    )
                    self.agent.conversation.append({"role": "user", "content": loop_msg})
                    _log_event(self.session_id, "loop_detected", {"tool": tool_name, "signature": call_signature})
                    recent_calls.clear()
                    continue

                # APPROVAL for sensitive tools
                approved = True
                needs_approval = tool_name in ("write_file", "edit_file", "run_bash")

                # HARD SAFETY: rm -rf and other destructive bash always need approval
                if tool_name == "run_bash":
                    try:
                        from tools.bash import is_dangerous_command
                        if is_dangerous_command(tool_args.get("command", "")):
                            needs_approval = True
                            _log_event(self.session_id, "danger_detected", {
                                "command": tool_args.get("command", "")[:200]
                            })
                    except ImportError:
                        pass

                if needs_approval:
                    if cb.on_approve_tool:
                        try:
                            approved = await cb.on_approve_tool(tool_name, tool_args)
                        except Exception:
                            approved = False
                    else:
                        # No approval callback registered = treat as denied for safety
                        approved = False
                        result = "BLOCKED: " + tool_name + " requires approval but no approval handler is registered."

                # Execute
                t0 = time.perf_counter()
                if not approved:
                    result = f"User denied {tool_name}."
                else:
                    try:
                        result = await asyncio.to_thread(dispatch, tool_name, tool_args)
                    except Exception as e:
                        result = f"Error running {tool_name}: {e}"
                ms = int((time.perf_counter() - t0) * 1000)

                _log_event(self.session_id, "tool_done", {
                    "step": step, "tool": tool_name, "ms": ms,
                    "result_preview": (result or "")[:200],
                })

                if cb.on_tool_done:
                    try:
                        await cb.on_tool_done(handle, result, ms)
                    except Exception:
                        pass

                # Feed observation back into conversation
                self.agent.conversation.append({
                    "role": "user",
                    "content": (
                        f"OBSERVATION (result of {tool_name}):\n{result}\n\n"
                        "Continue: next THOUGHT + ACTION, or FINAL_ANSWER."
                    ),
                })

                # EXPLORATION LOOP GUARD: count read-only calls in a row
                READ_ONLY_TOOLS = {
                    "read_file", "list_dir", "grep_files", "file_exists",
                    "search_code", "find_symbol", "list_symbols",
                    "find_callers", "project_map", "recall",
                }
                if tool_name in READ_ONLY_TOOLS:
                    consecutive_reads += 1
                else:
                    consecutive_reads = 0

                if consecutive_reads >= 5:
                    _log_event(self.session_id, "exploration_loop", {
                        "step": step, "reads_count": consecutive_reads,
                    })
                    self.agent.conversation.append({
                        "role": "user",
                        "content": (
                            "EXPLORATION LIMIT REACHED. You have made "
                            + str(consecutive_reads)
                            + " read/search calls in a row without writing any code. "
                            "STOP exploring. You have enough context. Either:\n"
                            "(a) Write the NEXT file with write_file, OR\n"
                            "(b) Give FINAL_ANSWER with what you've learned so far.\n"
                            "Do NOT call another read/search tool until you do one of the above."
                        ),
                    })
                    consecutive_reads = 0

                continue

            # ─── Parser failure
            _log_event(self.session_id, "parse_failure", {"raw": llm_output[:300]})
            if cb.on_parse_failure:
                try:
                    await cb.on_parse_failure(llm_output)
                except Exception:
                    pass
            self.agent.conversation.append({
                "role": "user",
                "content": (
                    "Invalid format. Use THOUGHT: then ACTION: {json} or "
                    "THOUGHT: then FINAL_ANSWER: text"
                ),
            })

        # Loop budget exhausted
        msg = (
            "Hit the " + str(self.max_iterations) + "-iteration budget without finishing.\n\n"
            "Progress is preserved in the conversation. Type /continue to resume with a fresh budget, "
            "or give a new instruction to refocus the work."
        )
        _log_event(self.session_id, "max_iterations", {"limit": self.max_iterations})
        if cb.on_final:
            try:
                await cb.on_final(msg)
            except Exception:
                pass
        return msg

    # ── Internal: bridge LLM streaming into async land ───────────────────────
    async def _stream_llm(self, messages: list, cb: RuntimeCallbacks) -> Optional[str]:
        loop = asyncio.get_event_loop()
        token_queue: asyncio.Queue = asyncio.Queue()

        def on_token_threadsafe(tok: str):
            try:
                loop.call_soon_threadsafe(token_queue.put_nowait, tok)
            except Exception:
                pass

        async def consume_tokens():
            while True:
                try:
                    tok = await asyncio.wait_for(token_queue.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    if llm_task.done():
                        break
                    continue
                if tok is None:
                    break
                if cb.on_token:
                    try:
                        cb.on_token(tok)
                    except Exception:
                        pass

        try:
            llm_task = asyncio.create_task(
                asyncio.to_thread(self.agent.llm.chat_stream, messages, on_token_threadsafe)
            )
            consumer_task = asyncio.create_task(consume_tokens())
            output = await llm_task
            await consumer_task
            return output
        except Exception as e:
            if cb.on_error:
                try:
                    await cb.on_error(str(e))
                except Exception:
                    pass
            return None
