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
  - Per-session JSONL log at ~/.ai-agent/sessions/<session_id>.jsonl
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

from agent.parser import parse_llm_output, ToolCall, FinalAnswer
from tools.registry import dispatch

# ── Session log ──────────────────────────────────────────────────────────────
SESSIONS_DIR = Path.home() / ".ai-agent" / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


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
        _log_event(self.session_id, "user_message", {"content": user_message})

        for i in range(self.max_iterations):
            step = i + 1

            if cb.on_llm_start:
                try:
                    await cb.on_llm_start(step)
                except Exception:
                    pass

            messages = [
                {"role": "system", "content": self.agent.system_prompt}
            ] + self.agent.conversation

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

                # APPROVAL for sensitive tools
                approved = True
                if tool_name in ("write_file", "edit_file", "run_bash"):
                    if cb.on_approve_tool:
                        try:
                            approved = await cb.on_approve_tool(tool_name, tool_args)
                        except Exception:
                            approved = False

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
        msg = "Reached maximum iterations without completing the task."
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
