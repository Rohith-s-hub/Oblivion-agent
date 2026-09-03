"""
agent/runtime.py — Patched & Stabilized Async Agent Runtime (Phase 2A)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from agent.plan_guard import (
    is_approval_message, claims_files_created,
    set_plan_approved, is_plan_approved,
    try_save_plan_from_llm_output,
    missing_files,
    existing_planned_files,
    rejection_message_for_missing,
    approval_directive,
    load_plan,
    clear_plan,
    workspace_root,
)
from agent.parser import parse_llm_output, ToolCall, FinalAnswer, is_garbage_output
from agent.brain import compress_conversation, needs_compression, summarize_via_llm
from tools.registry import dispatch
from agent.permissions import needs_approval as tier_needs_approval, classify_tool
from agent.models import get_context_limit, get_rate_delay


def _estimate_tokens(messages: list) -> int:
    total = 0
    for m in messages:
        c = m.get("content", "")
        if isinstance(c, str):
            total += len(c) // 4
    return total


def parse_and_save_plan(text: str, workspace_path: Path) -> bool:
    """Extracts plans structured as 1. <filename> and saves to plan.json."""
    plan_idx = text.find("PLAN:")
    if plan_idx == -1:
        plan_idx = text.find("Plan:")
    if plan_idx == -1:
        return False

    plan_text = text[plan_idx:]
    steps = []
    # Matches lines like: 1. filename - description
    for line in plan_text.splitlines():
        match = re.match(r"^\s*\d+[\s.)\]\[\-]+([\w./\-_]+\.\w+)\s*[-—:\s]*(.*)", line.strip())
        if match:
            file_path = match.group(1).strip()
            desc = match.group(2).strip()
            file_path = file_path.lstrip("./").lstrip("/")
            steps.append({"path": file_path, "purpose": desc})

    if steps:
        plan_dir = workspace_path / ".oblivion"
        plan_dir.mkdir(exist_ok=True, parents=True)
        with open(plan_dir / "plan.json", "w", encoding="utf-8") as f:
            json.dump({"steps": steps}, f, indent=2)
        return True
    return False


def _summarize_conversation(conversation: list, keep_recent: int = 4) -> list:
    if len(conversation) <= keep_recent + 1:
        return conversation

    first_user = conversation[0]
    recent = conversation[-keep_recent:]
    middle = conversation[1:-keep_recent]

    files_touched = set()
    tools_used = {}
    summary_parts = []
    for msg in middle:
        c = msg.get("content", "")
        if not isinstance(c, str):
            continue
        if c.startswith("OBSERVATION"):
            for m in re.finditer(r"(?:Written|Created|Edited|Read).+?([\w./\-_]+\.\w+)", c):
                files_touched.add(m.group(1))
            for m in re.finditer(r"(?:result of )(\w+)", c):
                t = m.group(1)
                tools_used[t] = tools_used.get(t, 0) + 1
        elif "THOUGHT:" in c:
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

    summary_msg = {"role": "user", "content": summary_text}
    return [first_user, summary_msg] + recent


from agent.paths import sessions_dir as _sessions_dir
SESSIONS_DIR = _sessions_dir()


def _log_event(session_id: int, kind: str, data: dict) -> None:
    try:
        path = SESSIONS_DIR / f"{session_id}.jsonl"
        entry = {"ts": time.time(), "kind": kind, **data}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass


@dataclass
class RuntimeCallbacks:
    on_token: Optional[Callable[[str], None]] = None
    on_llm_start: Optional[Callable[[int], Awaitable[None]]] = None
    on_llm_end:   Optional[Callable[[int, str, int], Awaitable[None]]] = None
    on_thought:   Optional[Callable[[str], Awaitable[None]]] = None
    on_tool_start: Optional[Callable[[str, dict], Awaitable[Any]]] = None
    on_tool_done:  Optional[Callable[[Any, str, int], Awaitable[None]]] = None
    on_final: Optional[Callable[[str], Awaitable[None]]] = None
    on_error: Optional[Callable[[str], Awaitable[None]]] = None
    on_parse_failure: Optional[Callable[[str], Awaitable[None]]] = None
    on_approve_tool: Optional[Callable[[str, dict], Awaitable[bool]]] = None


class AgentRuntime:
    def __init__(self, agent, session_id: int, max_iterations: int = 40):
        self.agent = agent
        self.session_id = session_id
        self.max_iterations = max_iterations
        self.session_state = {"auto_mode": False, "trusted_tools": set()}

    async def run_async(
        self,
        user_message: str,
        callbacks: RuntimeCallbacks,
    ) -> Optional[str]:
        cb = callbacks

        _clean_input = user_message.strip().lower()
        if _clean_input in ("yes", "y", "go", "proceed", "do it", "approved", "sure", "ok"):
            _last_asst = ""
            for _m in reversed(self.agent.conversation):
                if _m.get("role") == "assistant":
                    _last_asst = _m.get("content", "")
                    break
            if "PLAN:" in _last_asst or "Approve this plan?" in _last_asst:
                user_message = f"{user_message} (Plan approved. Proceed immediately to batch_edit to write all planned files.)"

        

        # PLAN APPROVAL: yes OR "create every file"
        if is_approval_message(user_message):
            try:
                _ws = workspace_root()
                for _m in reversed(self.agent.conversation):
                    if _m.get("role") == "assistant":
                        try_save_plan_from_llm_output(_m.get("content") or "", _ws)
                        break
                set_plan_approved(True, _ws)
                self._force_tool_strikes = 0
                self._session_write_count = 0
                _miss = missing_files(_ws)
                _plan = load_plan(_ws)
                if _miss:
                    _extra = approval_directive(_miss, _plan)
                    _extra += "\n\nCRITICAL: Call batch_edit or write_file. "
                    _extra += "FINAL_ANSWER without real tool writes is FORBIDDEN."
                    user_message = user_message + "\n\n" + _extra
            except Exception as _e:
                try:
                    _log_event(self.session_id, "plan_approval_hook_err", {"err": str(_e)})
                except Exception:
                    pass


        self.agent.conversation.append({"role": "user", "content": user_message})
        
        try:
            self.agent.refresh_prompt(user_message)
        except Exception:
            pass

        _log_event(self.session_id, "user_message", {"content": user_message})

        recent_calls: list[str] = []
        consecutive_reads = 0

        # ── STUCK-OUTPUT CIRCUIT BREAKERS ──────────────────────────────
        # Detects the "same chars/tokens forever" death spiral from the screenshot
        _prev_out_sizes: list[tuple[int, int]] = []   # [(chars, tokens), ...]
        _prev_out_hashes: list[str] = []               # content fingerprints
        _steps_without_write = 0                       # progress stall counter
        _last_written_files: set = set()
        _files_written_this_run: dict = {}             # path -> times written

        for i in range(self.max_iterations):
            step = i + 1

            if cb.on_llm_start:
                try:
                    await cb.on_llm_start(step)
                except Exception:
                    pass

            # Auto-compress history
            est_tokens = _estimate_tokens(self.agent.conversation)
            _ctx_limit = get_context_limit(self.agent.llm.model)
            _compress_at = max(6000, int(_ctx_limit * 0.60))
            if est_tokens > _compress_at and len(self.agent.conversation) > 6:
                self.agent.conversation = _summarize_conversation(self.agent.conversation, keep_recent=4)

            # Re-read or sync plan
            ws_dir = Path(os.getenv("WORKSPACE_DIR", ".")).resolve()
            
            messages = [
                {"role": "system", "content": self.agent.system_prompt}
            ] + self.agent.conversation

            _delay = get_rate_delay(self.agent.llm.model)
            if _delay > 0:
                time.sleep(_delay)

            llm_output = await self._stream_llm(messages, cb)
            if llm_output is None:
                return None

            if is_garbage_output(llm_output):
                self.agent.conversation.append({
                    "role": "user",
                    "content": "Your last response was blank or corrupted. Please summarize actions.",
                })
                continue

            # Parse and save active plan to disk if detected in output stream
            parse_and_save_plan(llm_output, ws_dir)

            self.agent.conversation.append({"role": "assistant", "content": llm_output})
            # Persist plan whenever model emits one
            try:
                try_save_plan_from_llm_output(llm_output or "", workspace_root())
            except Exception:
                pass


            # ═══════════════════════════════════════════════════════════
            # STUCK-OUTPUT DETECTOR (fixes identical 1465-token death loop)
            # ═══════════════════════════════════════════════════════════
            import hashlib as _hashlib
            _out_chars = len(llm_output or "")
            _out_tokens = _out_chars // 4
            _out_hash = _hashlib.md5((llm_output or "")[:2000].encode("utf-8", errors="ignore")).hexdigest()

            _prev_out_sizes.append((_out_chars, _out_tokens))
            _prev_out_hashes.append(_out_hash)
            if len(_prev_out_sizes) > 5:
                _prev_out_sizes.pop(0)
                _prev_out_hashes.pop(0)

            # Trap 1: identical token count 3x in a row (your screenshot bug)
            _size_stuck = (
                len(_prev_out_sizes) >= 3
                and _prev_out_sizes[-1][1] == _prev_out_sizes[-2][1] == _prev_out_sizes[-3][1]
                and _prev_out_sizes[-1][1] > 100  # ignore tiny outputs
            )
            # Trap 2: near-identical content hash 2x in a row
            _content_stuck = (
                len(_prev_out_hashes) >= 2
                and _prev_out_hashes[-1] == _prev_out_hashes[-2]
            )
            # Trap 3: char count within ±30 of previous 3 outputs
            _near_size_stuck = False
            if len(_prev_out_sizes) >= 3:
                c1, c2, c3 = _prev_out_sizes[-1][0], _prev_out_sizes[-2][0], _prev_out_sizes[-3][0]
                _near_size_stuck = abs(c1 - c2) <= 30 and abs(c2 - c3) <= 30 and c1 > 500

            if _size_stuck or _content_stuck or _near_size_stuck:
                _log_event(self.session_id, "stuck_output_loop", {
                    "step": step,
                    "chars": _out_chars,
                    "tokens": _out_tokens,
                    "size_stuck": _size_stuck,
                    "content_stuck": _content_stuck,
                    "near_size_stuck": _near_size_stuck,
                })
                # Check what files are still missing from the plan
                _missing_now = []
                try:
                    _pf = ws_dir / ".oblivion" / "plan.json"
                    if _pf.exists():
                        _pd = json.loads(_pf.read_text(encoding="utf-8"))
                        _missing_now = [
                            s["path"] for s in _pd.get("steps", [])
                            if not (ws_dir / s["path"]).exists()
                        ]
                except Exception:
                    pass

                if _missing_now:
                    # Force the model onto a DIFFERENT file — break the repeat pattern
                    _next_file = _missing_now[0]
                    _break_msg = (
                        f"SYSTEM INTERRUPT: You are stuck generating the same ~{_out_tokens}-token "
                        f"response repeatedly. STOP repeating.\n\n"
                        f"MISSING FILES: {', '.join(_missing_now)}\n"
                        f"Your NEXT action MUST be batch_edit or write_file for: `{_next_file}`\n"
                        f"Write completely NEW content. Do NOT repeat your previous output."
                    )
                    self.agent.conversation.append({"role": "user", "content": _break_msg})
                    _prev_out_sizes.clear()
                    _prev_out_hashes.clear()
                    continue
                else:
                    # Nothing missing — force finish
                    _done_msg = (
                        f"All planned files exist on disk. "
                        f"Give FINAL_ANSWER summarizing what was built. Do NOT call more tools."
                    )
                    self.agent.conversation.append({"role": "user", "content": _done_msg})
                    _prev_out_sizes.clear()
                    _prev_out_hashes.clear()
                    continue

            
            # Sync system prompt to show updated plan progress checkboxes in system prompt
            self.agent.refresh_prompt(user_message)

            if cb.on_llm_end:
                try:
                    await cb.on_llm_end(step, llm_output, len(llm_output) // 4)
                except Exception:
                    pass

            
            parsed = parse_llm_output(llm_output)

            # ═══ FORCE_TOOL_GATE_V1 ═══════════════════════════════════════
            # Missing planned files => model MUST call batch_edit/write_file.
            try:
                _ws_ft = workspace_root()
                try_save_plan_from_llm_output(llm_output or "", _ws_ft)
                _miss_ft = missing_files(_ws_ft)
            except Exception:
                _miss_ft = []

            # Only force writes AFTER user approved the plan (said yes).
            # Plan-only turns must be allowed to FINAL_ANSWER without tools.
            if _miss_ft and is_plan_approved(_ws_ft):
                from agent.parser import ToolCall as _TC
                _is_write = False
                if isinstance(parsed, _TC):
                    _tn = (getattr(parsed, "tool", None) or "")
                    _is_write = _tn in ("batch_edit", "write_file", "edit_file")

                if not _is_write:
                    if not hasattr(self, "_force_tool_strikes"):
                        self._force_tool_strikes = 0
                    self._force_tool_strikes += 1
                    _next = _miss_ft[0]
                    _batch = ", ".join(_miss_ft[:3])
                    _rest = ", ".join(_miss_ft)
                    try:
                        _log_event(self.session_id, "force_tool_reject", {
                            "step": step,
                            "strikes": self._force_tool_strikes,
                            "missing": _miss_ft[:10],
                            "parsed_type": type(parsed).__name__,
                        })
                    except Exception:
                        pass

                    _msg = "\n".join([
                        "SYSTEM REJECT: No file-write tool call detected.",
                        "Disk still missing %d planned file(s)." % len(_miss_ft),
                        "You MUST reply in EXACTLY this format:",
                        "",
                        "THOUGHT: writing next files",
                        'ACTION: {"tool": "batch_edit", "args": {"edits": [{"path": "%s", "content": "<full file source>"}]}}' % _next,
                        "",
                        "Write these NOW (2-3 per batch): %s" % _batch,
                        "All remaining: %s" % _rest,
                        "FORBIDDEN: FINAL_ANSWER, plain English only, markdown without ACTION.",
                        "Strike %d/8." % self._force_tool_strikes,
                    ])

                    if self.agent.conversation and self.agent.conversation[-1].get("role") == "assistant":
                        self.agent.conversation.pop()
                    self.agent.conversation.append({"role": "user", "content": _msg})

                    if self._force_tool_strikes >= 8:
                        _give_up = (
                            "Stopped after 8 non-write responses. Still missing: %s. "
                            "Type yes to retry, or simplify the plan." % _rest
                        )
                        if cb.on_final:
                            try:
                                await cb.on_final(_give_up)
                            except Exception:
                                pass
                        self._force_tool_strikes = 0
                        return _give_up
                    continue
                else:
                    self._force_tool_strikes = 0
            # ═══ END FORCE_TOOL_GATE_V1 ═══════════════════════════════════





            # Final Answer verification
            if isinstance(parsed, FinalAnswer):
                # NUCLEAR ANTI-HALLUCINATION GATE
                try:
                    _ws = workspace_root()
                    try_save_plan_from_llm_output(getattr(parsed, "content", "") or "", _ws)
                    _plan = load_plan(_ws)
                    _miss = missing_files(_ws) if _plan else []
                    _have = existing_planned_files(_ws) if _plan else []
                    _writes = getattr(self, "_session_write_count", 0)
                    _content = getattr(parsed, "content", "") or ""
                    _claims = claims_files_created(_content)
                    _approved = is_plan_approved(_ws) if _plan else False

                    if _claims and _writes < 1 and (_miss or not _have):
                        _log_event(self.session_id, "hallucination_no_writes", {
                            "writes": _writes, "missing": list(_miss)[:20],
                        })
                        _rej = (
                            "SYSTEM REJECT — HALLUCINATION.\n"
                            "You claimed files were created but no successful write_file/batch_edit ran.\n"
                            "existing: " + (", ".join(_have[:15]) if _have else "(none)") + "\n"
                            "missing: " + (", ".join(_miss) if _miss else "(none)") + "\n"
                            "Call batch_edit or write_file NOW. FINAL_ANSWER is forbidden until disk has the files."
                        )
                        if self.agent.conversation and self.agent.conversation[-1].get("role") == "assistant":
                            self.agent.conversation.pop()
                        self.agent.conversation.append({"role": "user", "content": _rej})
                        self._force_tool_strikes = 0
                        continue

                    if _approved and _miss:
                        _log_event(self.session_id, "final_blocked_missing", {"missing": _miss})
                        self.agent.conversation.append({
                            "role": "user",
                            "content": rejection_message_for_missing(_miss, _have),
                        })
                        continue

                    if _claims and _miss:
                        self.agent.conversation.append({
                            "role": "user",
                            "content": rejection_message_for_missing(_miss, _have),
                        })
                        continue

                    if _plan and not _miss and _have:
                        clear_plan(_ws)
                except Exception as _ng:
                    try:
                        _log_event(self.session_id, "nuclear_gate_err", {"err": str(_ng)})
                    except Exception:
                        pass
                # ═══ HARD DISK GATE — no hallucinated complete ═══
                try:
                    _ws = workspace_root()
                    try_save_plan_from_llm_output(getattr(parsed, "content", None) or llm_output or "", _ws)
                    _miss = missing_files(_ws)
                    _have = existing_planned_files(_ws)
                    if _miss and not is_plan_approved(_ws):
                        _miss = []
                    if _miss:
                        _log_event(self.session_id, "final_answer_blocked_missing", {"missing": _miss, "have": _have})
                        self.agent.conversation.append({
                            "role": "user",
                            "content": rejection_message_for_missing(_miss, _have),
                        })
                        try:
                            self.agent.refresh_prompt(user_message)
                        except Exception:
                            pass
                        continue
                    elif load_plan(_ws):
                        clear_plan(_ws)
                except Exception as _gate_err:
                    try:
                        _log_event(self.session_id, "final_gate_err", {"err": str(_gate_err)})
                    except Exception:
                        pass
                _log_event(self.session_id, "final_answer", {"content": parsed.content})
                if cb.on_final:
                    try:
                        await cb.on_final(parsed.content)
                    except Exception:
                        pass
                return parsed.content

            # Tool Calls execution
            if isinstance(parsed, ToolCall):
                tool_name = parsed.tool
                tool_args = parsed.args or {}

                if parsed.thought and cb.on_thought:
                    try:
                        await cb.on_thought(parsed.thought)
                    except Exception:
                        pass

                if tool_name == "finish":
                    return tool_args.get("summary", "Complete.")

                handle = None
                if cb.on_tool_start:
                    try:
                        handle = await cb.on_tool_start(tool_name, tool_args)
                    except Exception:
                        pass

                # ── Loop detection (tool-name + soft args) ─────────────
                # Exact-arg match (original)
                sig = f"{tool_name}:{json.dumps(tool_args, sort_keys=True, default=str)[:200]}"
                recent_calls.append(sig)
                if len(recent_calls) > 5:
                    recent_calls.pop(0)

                _exact_loop = len(recent_calls) >= 3 and recent_calls[-1] == recent_calls[-2] == recent_calls[-3]
                # Same tool 4x in a row even with different args (write_file spam etc.)
                _tool_only = [c.split(":")[0] for c in recent_calls]
                _same_tool_loop = len(_tool_only) >= 4 and len(set(_tool_only[-4:])) == 1

                if _exact_loop or _same_tool_loop:
                    _log_event(self.session_id, "loop_detected", {
                        "tool": tool_name, "exact": _exact_loop, "same_tool": _same_tool_loop,
                    })
                    # Tell model what's missing instead of generic "stop"
                    _miss = []
                    try:
                        _pf = ws_dir / ".oblivion" / "plan.json"
                        if _pf.exists():
                            _pd = json.loads(_pf.read_text(encoding="utf-8"))
                            _miss = [s["path"] for s in _pd.get("steps", []) if not (ws_dir / s["path"]).exists()]
                    except Exception:
                        pass
                    if _miss:
                        _msg = (
                            f"LOOP DETECTED on `{tool_name}`. You already did this. "
                            f"Move on to the NEXT missing file: `{_miss[0]}`. "
                            f"Remaining: {', '.join(_miss)}. "
                            f"Call batch_edit/write_file for a file you have NOT written yet."
                        )
                    else:
                        _msg = (
                            f"LOOP DETECTED on `{tool_name}`. All planned files exist. "
                            f"Give FINAL_ANSWER now. Do NOT call {tool_name} again."
                        )
                    self.agent.conversation.append({"role": "user", "content": _msg})
                    recent_calls.clear()
                    continue

                # ── PRE-DISPATCH RESCUE HOOKS ──────────────────────
                # Hook A: edit_file on non-existent file → auto-suggest write_file
                if tool_name == "edit_file":
                    _tgt = (tool_args or {}).get("path", "")
                    if _tgt and not (ws_dir / _tgt).exists():
                        _log_event(self.session_id, "edit_file_missing_rescue", {"path": _tgt})
                        self.agent.conversation.append({
                            "role": "user",
                            "content": (
                                f"OBSERVATION: `edit_file` FAILED — `{_tgt}` does not exist on disk.\n"
                                f"You cannot EDIT a file that was never created.\n\n"
                                f"CORRECTION: Call `write_file` with the FULL content of `{_tgt}` to CREATE it. "
                                f"Do NOT retry edit_file on this path."
                            ),
                        })
                        if cb.on_tool_done:
                            try:
                                await cb.on_tool_done(handle, f"Auto-blocked: {_tgt} does not exist. Use write_file to create.", 0)
                            except Exception:
                                pass
                        continue

                # Hook B: block writing the same file twice in one run
                if tool_name in ("write_file", "batch_edit"):
                    _targets = []
                    if tool_name == "write_file":
                        _p = (tool_args or {}).get("path", "")
                        if _p:
                            _targets.append(_p)
                    else:
                        for _e in (tool_args or {}).get("edits", []) or []:
                            if isinstance(_e, dict) and _e.get("path"):
                                _targets.append(_e["path"])

                    _dupes = [p for p in _targets if _files_written_this_run.get(p, 0) >= 1]
                    if _dupes:
                        _log_event(self.session_id, "duplicate_write_blocked", {"paths": _dupes})
                        # Find next missing file to redirect to
                        _next_miss = []
                        try:
                            _pf = ws_dir / ".oblivion" / "plan.json"
                            if _pf.exists():
                                _pd = json.loads(_pf.read_text(encoding="utf-8"))
                                _next_miss = [s["path"] for s in _pd.get("steps", [])
                                              if not (ws_dir / s["path"]).exists()]
                        except Exception:
                            pass
                        _msg = (
                            f"BLOCKED: You already wrote `{', '.join(_dupes)}` in this run. "
                            f"Do NOT rewrite the same file.\n"
                        )
                        if _next_miss:
                            _msg += f"Missing files still pending: {', '.join(_next_miss[:5])}\nWrite `{_next_miss[0]}` next."
                        else:
                            _msg += "All planned files exist. Give FINAL_ANSWER now."
                        self.agent.conversation.append({"role": "user", "content": _msg})
                        if cb.on_tool_done:
                            try:
                                await cb.on_tool_done(handle, f"Blocked duplicate write: {_dupes}", 0)
                            except Exception:
                                pass
                        continue

                approved = True
                result = None
                _needs_approval, _reason = tier_needs_approval(tool_name, tool_args, self.session_state)

                if _needs_approval:
                    if cb.on_approve_tool:
                        try:
                            approved = await cb.on_approve_tool(tool_name, tool_args)
                        except Exception:
                            approved = False
                        if not approved:
                            result = f"Denied: {tool_name}"
                    else:
                        if _reason == "destructive":
                            approved = False
                            result = "Blocked destructive action."

                t0 = time.perf_counter()
                if approved and result is None:
                    try:
                        result = await asyncio.to_thread(dispatch, tool_name, tool_args)
                    except Exception as e:
                        result = f"Error running {tool_name}: {e}"
                elif not approved and result is None:
                    result = "User denied permission."
                ms = int((time.perf_counter() - t0) * 1000)

                # Clamp very large observations safely!
                if len(result) > 4000:
                    result = (
                        f"{result[:1500]}\n\n"
                        f"... [TRUNCATED {len(result) - 3000} CHARS OF LARGE TOOL OBSERVATION TO PREVENT BLINDNESS] ...\n\n"
                        f"{result[-1500:]}"
                    )

                if cb.on_tool_done:
                    try:
                        await cb.on_tool_done(handle, result, ms)
                    except Exception:
                        pass

                # ── Progress stall detector + write ledger ─────────────
                _wrote_something = False
                _write_ok = result and "Error" not in str(result)[:100] and "not found" not in str(result).lower()

                if tool_name in ("write_file", "batch_edit", "edit_file"):
                    if _write_ok:
                        _wrote_something = True
                        _steps_without_write = 0
                        # Extract paths and mark them as written
                        _paths_written = []
                        if tool_name == "write_file" and tool_args.get("path"):
                            _paths_written.append(tool_args["path"])
                        elif tool_name == "batch_edit":
                            for _ed in (tool_args.get("edits") or []):
                                if isinstance(_ed, dict) and _ed.get("path"):
                                    _paths_written.append(_ed["path"])
                        elif tool_name == "edit_file" and tool_args.get("path"):
                            _paths_written.append(tool_args["path"])

                        for _pw in _paths_written:
                            _last_written_files.add(_pw)
                            _files_written_this_run[_pw] = _files_written_this_run.get(_pw, 0) + 1
                    else:
                        _steps_without_write += 1
                else:
                    _steps_without_write += 1

                if _steps_without_write >= 5:
                    _miss = []
                    try:
                        _pf2 = ws_dir / ".oblivion" / "plan.json"
                        if _pf2.exists():
                            _pd2 = json.loads(_pf2.read_text(encoding="utf-8"))
                            _miss = [s["path"] for s in _pd2.get("steps", []) if not (ws_dir / s["path"]).exists()]
                    except Exception:
                        pass
                    if _miss:
                        result = (
                            (result or "") + f"\n\nSYSTEM: No files written in {_steps_without_write} steps. "
                            f"STOP exploring. Write the next missing file NOW: `{_miss[0]}`. "
                            f"Still missing: {', '.join(_miss)}"
                        )
                    _steps_without_write = 0

                
                # ledger successful writes
                if tool_name in ("write_file", "batch_edit") and result and "error" not in str(result).lower()[:80]:
                    if not hasattr(self, "_files_written_this_run"):
                        self._files_written_this_run = {}
                    if tool_name == "write_file" and tool_args.get("path"):
                        self._files_written_this_run[tool_args["path"]] = self._files_written_this_run.get(tool_args["path"], 0) + 1
                    elif tool_name == "batch_edit":
                        for e in (tool_args.get("edits") or []):
                            if isinstance(e, dict) and e.get("path"):
                                self._files_written_this_run[e["path"]] = self._files_written_this_run.get(e["path"], 0) + 1

                
                if tool_name in ("write_file", "batch_edit", "edit_file"):
                    _okw = result and "error" not in str(result).lower()[:100]
                    if _okw and "not found" not in str(result).lower()[:120]:
                        self._session_write_count = getattr(self, "_session_write_count", 0) + 1

                self.agent.conversation.append({
                    "role": "user",
                    "content": (
                        f"OBSERVATION (result of {tool_name}):\n{result}\n\n"
                        "Continue: next THOUGHT + ACTION, or FINAL_ANSWER."
                    ),
                })
                continue

            # Parse failures
            self.agent.conversation.append({
                "role": "user",
                "content": "Invalid response layout. Respond strictly with Form A (ACTION) or Form B (FINAL_ANSWER).",
            })

        return "Safety budget of execution iterations reached."


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


def plan_task(goal: str, max_files: int = 10) -> str:
    """Break a multi-file task into atomic file-level steps."""
    return f"""PLANNER ACTIVATED — decompose this goal into atomic file-level steps:

GOAL: {goal}

Respond with a numbered plan in EXACTLY this format:

PLAN:
1. <filename> — <one-line description of what this file does>
2. <filename> — <description>
3. ...

RULES:
- Each step = exactly ONE file (no batching)
- Order matters: dependencies first (e.g. package.json before src/main.jsx)
- Max {max_files} files in plan
- After listing the plan, ask user: "Approve this plan? Reply yes/no or suggest changes"
- Do NOT write any code yet. ONLY the plan.
"""
