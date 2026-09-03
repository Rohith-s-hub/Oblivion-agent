import os
import re
import json
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from agent.llm import LLMClient
from agent.parser import parse_llm_output, ToolCall, FinalAnswer
from tools.registry import get_tool_descriptions, dispatch
from tools.diff import make_diff, print_diff, print_new_file, ask_approval

console = Console()
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "20"))

REQUIRE_APPROVAL_WRITE = os.getenv("REQUIRE_APPROVAL_FOR_WRITE", "true").lower() == "true"
REQUIRE_APPROVAL_BASH  = os.getenv("REQUIRE_APPROVAL_FOR_BASH",  "true").lower() == "true"


def build_system_prompt(user_message: str = "") -> str:
    """Compact system prompt (v2.0 - Stabilized for full-stack tasks)."""
    from agent.brain import load_memory
    from knowledge.injector import build_knowledge_block

    # === Dynamic hooks (memory + optional knowledge pack) ===
    memory = load_memory()
    memory_block = ""
    if memory.strip():
        mem_text = memory[:1500].strip()
        memory_block = f"\n## PROJECT MEMORY (from MEMORY.md)\n{mem_text}\n"

    # Knowledge pack (only loads if user_message triggers a specific tech tag)
    knowledge_block = build_knowledge_block(
        workspace=os.getenv("WORKSPACE_DIR", "."),
        user_message=user_message,
    )

    workspace = os.getenv("WORKSPACE_DIR", ".")
    workspace_name = Path(workspace).name or workspace

    # Dynamic Active Plan Injection from plan.json
    active_plan_block = ""
    try:
        plan_file = Path(workspace) / ".oblivion" / "plan.json"
        if plan_file.exists():
            plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
            steps = plan_data.get("steps", [])
            if steps:
                active_plan_block = "\n## ACTIVE PROJECT PLAN (STRICT PERSISTENCE)\n"
                for idx, step in enumerate(steps, 1):
                    p_path = step["path"]
                    # Clean relative paths
                    full_p = Path(workspace) / p_path
                    status_emoji = "✅" if full_p.exists() else "⏳"
                    active_plan_block += f"  {idx}. {status_emoji} `{p_path}` — {step['purpose']}\n"
                active_plan_block += (
                    "\n🚨 SYSTEM RULES:\n"
                    "- Every file marked with ⏳ MUST be physical written using write_file or batch_edit.\n"
                    "- Do NOT output a FINAL_ANSWER until all plan steps are marked as ✅.\n"
                )
    except Exception:
        pass

    # === Core prompt (lean, single-source-of-truth) ===
    
    # Disk-enforced active plan (plan_guard)
    active_plan_block = ""
    try:
        from agent.plan_guard import plan_status_block
        active_plan_block = plan_status_block()
        if active_plan_block:
            active_plan_block = "\n" + active_plan_block + "\n"
    except Exception:
        active_plan_block = ""

    return f"""# OBLIVION_PROMPT_V2_0

You are **Meera** — an AI coding assistant inside Oblivion.
Never identify as Claude, GPT, Qwen, Gemini, or any underlying model.
Never quote raw absolute file paths in conversation or greetings. Refer to the project by its folder name.

Workspace: {workspace}
{memory_block}{knowledge_block}{active_plan_block}

## RESPONSE FORMAT (strict — no deviation)

Every response is EXACTLY ONE of these two forms:

  Form A (take an action):
    THOUGHT: <one short sentence>
    ACTION: {{"tool": "<name>", "args": {{...}}}}

  Form B (final answer):
    THOUGHT: <one short sentence>
    FINAL_ANSWER: <your answer to the user>

Response ENDS immediately after the ACTION JSON or FINAL_ANSWER text.
NEVER write "OBSERVATION:" yourself — that comes from the system.
NEVER combine ACTION and FINAL_ANSWER in one response.
No markdown fences around the JSON.


## ANTI-HALLUCINATION (ABSOLUTE)
- NEVER say you created a file unless a tool OBSERVATION in THIS turn confirmed it was written.
- NEVER say "17 files" or "project complete" unless ACTIVE BUILD PLAN shows all ✅.
- If ACTIVE BUILD PLAN has any ❌, your only valid actions are batch_edit or write_file.
- FINAL_ANSWER while ❌ remains will be REJECTED by the system.

## PLAN-FIRST WORKFLOW (MANDATORY — DO NOT SKIP)

For ANY multi-file build request (website, app, project, "create me...", "build me..."):

**PHASE 1 — SHOW THE PLAN (no code yet):**
Your FIRST response MUST be a FINAL_ANSWER containing the plan in this EXACT format:
📋 PROJECT PLAN

Goal: <one-line summary>

Files to create:

package.json — dependencies + scripts
vite.config.js — Vite React config
index.html — HTML entry
src/main.jsx — React entry point
src/App.jsx — router shell
src/index.css — global styles
src/components/Navbar.jsx — top navigation
src/pages/Home.jsx — landing page
... (list ALL files, numbered)
Tech: React + Vite + React Router + Tailwind
Estimated files: <N>

Approve this plan? Reply yes to build, or tell me what to change.

text


Then STOP. Do NOT call any tool. Wait for user reply.

**PHASE 2 — EXECUTE (only after user says yes/go/proceed):**
1. Your NEXT action MUST be `batch_edit` or `write_file`.
2. Write files in the EXACT order listed in your plan.
3. FORBIDDEN: `new_workspace`, `switch_workspace`, `create_dir`.
4. FORBIDDEN: `edit_file` on files that don't exist yet — use `write_file` to CREATE them first.
5. NEVER write the same file twice — check your plan before each call.

## FILE CREATION vs EDITING (CRITICAL)

- `write_file(path, content)`  → CREATE new file OR OVERWRITE existing file
- `edit_file(path, old_text, new_text)` → ONLY for files that ALREADY exist on disk
- `batch_edit(edits=[{{path, content}}])` → CREATE multiple new files at once

If unsure whether a file exists, use `write_file` — it creates OR overwrites safely.
NEVER call `edit_file` on a file you have not yet written in this session.

## STRICT REACT & VITE ARCHITECTURAL BLUEPRINT

When creating React applications (Vite / React Router / Tailwind):

### Standard Folder Structure (ALWAYS USE THIS EXACT PATTERN):
project-root/
├── index.html          # Entry HTML with <div id="root"></div> and <script type="module" src="/src/main.jsx"></script>
├── package.json        # Dependencies: react, react-dom, react-router-dom, lucide-react
├── vite.config.js      # Vite React plugin config
├── src/
│   ├── main.jsx        # ReactDOM.createRoot rendering <App /> wrapped in <BrowserRouter>
│   ├── App.jsx         # Main router shell with <Navbar />, <Routes>, <Footer />
│   ├── index.css       # Tailwind / Global CSS variables
│   ├── components/     # Reusable UI components (Navbar.jsx, Footer.jsx)
│   ├── pages/          # Page views matching routes (Home.jsx, About.jsx, Contact.jsx)
│   └── data/           # Mock data stores (mockData.js)

### React Execution Rules:
1. Never mix .jsx and .tsx extensions. Use .jsx for JS or .tsx for TS consistently.
2. Wrap routes in BrowserRouter inside main.jsx.
3. Atomic Batching (MAX 3 BATCHES FOR FULL SITE):
   - Batch 1 (Scaffold): package.json, vite.config.js, index.html, src/index.css, src/main.jsx
   - Batch 2 (Core Shell): src/App.jsx, src/components/Navbar.jsx, src/components/Footer.jsx, src/data/mockData.js
   - Batch 3 (All Pages): src/pages/Home.jsx, src/pages/About.jsx, src/pages/Products.jsx, src/pages/Contact.jsx

## RULES (obey all)

1. **EXECUTION IS PARAMOUNT. FINISH WHAT YOU START.**
   - Do NOT give `FINAL_ANSWER` until ALL files in active plan are created on disk.
   - Ignore past chat noise and complete the files.

2. **WEBSITE GENERATION:**
   - Call `batch_edit` for 2-3 files at a time to stay under output token limits.
   - Strictly apply design rules in `webdev` knowledge pack.

3. **DEBUGGING PROTOCOL:**
   When an error occurs: Read the file, inspect project map, check imports, apply fix. Never guess.

## AVAILABLE TOOLS

{_compact_tool_list()}

## FINAL_ANSWER STYLE FOR FILE OPS

When files are mutated:
  ✓ Created/Modified: <name> (<size> chars)
  Summary: <one line>
"""


def _compact_tool_list() -> str:
    from tools.registry import TOOL_SCHEMAS
    lines = []
    for schema in TOOL_SCHEMAS:
        name = schema["name"]
        params = schema.get("parameters", {})
        arg_parts = []
        for pname, pspec in params.items():
            arg_parts.append(pname if pspec.get("required") else pname + "?")
        arg_str = ", ".join(arg_parts)
        desc = schema.get("description", "").split(".")[0][:80].strip()
        lines.append(f"  {name}({arg_str}) — {desc}")
    return "\n".join(lines)


def squeeze_observation(result: str) -> str:
    """Clamps very large outputs to prevent context memory pollution."""
    if len(result) > 4000:
        return (
            f"{result[:1500]}\n\n"
            f"... [TRUNCATED {len(result) - 3000} CHARS OF LARGE TOOL OUTPUT TO PRESERVE CONTEXT] ...\n\n"
            f"{result[-1500:]}"
        )
    return result


class Agent:
    def __init__(self):
        self.llm = LLMClient()
        self.system_prompt = build_system_prompt()
        self.conversation = []

    def refresh_prompt(self, user_message: str = "") -> None:
        self.system_prompt = build_system_prompt(user_message=user_message)

    def reset(self):
        self.conversation = []
        console.print("[yellow]Conversation cleared.[/yellow]")

    def _handle_write_file(self, args: dict) -> str:
        path = args.get("path", "")
        new_content = args.get("content", "")

        try:
            from tools.filesystem import _safe_path, _PathError
            p = _safe_path(path)
        except _PathError as e:
            return f"Error: {e}"
        except Exception:
            p = Path(path)

        _in_tui = os.getenv("OBLIVION_TUI", "0") == "1"

        if p.exists() and p.is_file():
            try:
                original = p.read_text(encoding="utf-8")
            except Exception:
                original = ""

            diff_str = make_diff(original, new_content, filename=path)

            if not diff_str.strip():
                return "No changes detected - file already has this content."

            if not _in_tui:
                print_diff(diff_str, filename=path)

            if REQUIRE_APPROVAL_WRITE and not _in_tui:
                if not ask_approval(f"write to {path}"):
                    return "Write cancelled by user."
        else:
            if not _in_tui:
                print_new_file(new_content, filename=path)

            if REQUIRE_APPROVAL_WRITE and not _in_tui:
                if not ask_approval(f"create {path}"):
                    return "File creation cancelled by user."

        return dispatch("write_file", args)

    def _handle_edit_file(self, args: dict) -> str:
        path = args.get("path", "")
        old_text = args.get("old_text", "")
        new_text = args.get("new_text", "")

        try:
            from tools.filesystem import _safe_path, _PathError
            p = _safe_path(path)
        except _PathError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error resolving path {path}: {e}"

        if not p.exists():
            return f"Error: File not found: {path}"

        try:
            original = p.read_text(encoding="utf-8")
        except Exception as e:
            return f"Error reading file: {e}"

        if old_text not in original:
            return f"Error: old_text not found in {path}. Check that it matches exactly."

        updated = original.replace(old_text, new_text, 1)
        diff_str = make_diff(original, updated, filename=path)

        _in_tui = os.getenv("OBLIVION_TUI", "0") == "1"
        if not _in_tui:
            print_diff(diff_str, filename=path)

        if REQUIRE_APPROVAL_WRITE and not _in_tui:
            if not ask_approval(f"edit {path}"):
                return "Edit cancelled by user."

        return dispatch("edit_file", args)

    def _handle_bash(self, args: dict) -> str:
        command = args.get("command", "")
        _in_tui = os.getenv("OBLIVION_TUI", "0") == "1"
        if not _in_tui:
            console.print(Panel(
                f"[bold yellow]Command:[/bold yellow] [white]{command}[/white]",
                title="[yellow]Run Shell Command?[/yellow]",
                border_style="yellow",
            ))
        if REQUIRE_APPROVAL_BASH and not _in_tui:
            if not ask_approval("run this command"):
                return "Command cancelled by user."
        return dispatch("run_bash", args)

    def run(self, user_message: str) -> str:
        # CONTEXT PROTECTION: Clear memory on new independent requests (prevents repeating old answers!)
        _clean_msg = user_message.strip().lower()
        is_continuation = _clean_msg in ("yes", "y", "go", "proceed", "do it", "approved", "sure", "ok", "continue", "/continue")
        if not is_continuation and len(self.conversation) > 0:
            # Check if history relates to build tasks. If not, refresh clean workspace bounds.
            self.conversation = []

        self.conversation.append({"role": "user", "content": user_message})
        console.print("\n[bold blue]Thinking...[/bold blue]")

        _prev_sizes: list[int] = []
        _prev_hashes: list[str] = []

        for i in range(MAX_ITERATIONS):
            console.print(f"\n[dim]-- Step {i+1}/{MAX_ITERATIONS} --[/dim]")

            # Refresh plan checkboxes into system prompt each step
            try:
                self.refresh_prompt(user_message)
            except Exception:
                pass

            messages = [
                {"role": "system", "content": self.system_prompt}
            ] + self.conversation

            console.print("[dim]LLM -> [/dim]", end="")
            llm_output = self.llm.chat(messages, stream=True)

            # ── Same-size death loop detector ──────────────────────────
            import hashlib as _hl
            _sz = len(llm_output or "")
            _hx = _hl.md5((llm_output or "")[:2000].encode("utf-8", errors="ignore")).hexdigest()
            _prev_sizes.append(_sz)
            _prev_hashes.append(_hx)
            if len(_prev_sizes) > 4:
                _prev_sizes.pop(0)
                _prev_hashes.pop(0)

            _stuck = (
                (len(_prev_sizes) >= 3 and abs(_prev_sizes[-1] - _prev_sizes[-2]) <= 30
                 and abs(_prev_sizes[-2] - _prev_sizes[-3]) <= 30 and _sz > 500)
                or (len(_prev_hashes) >= 2 and _prev_hashes[-1] == _prev_hashes[-2])
            )
            if _stuck:
                console.print("[red]⚠ Stuck output loop detected — forcing recovery[/red]")
                # Find missing plan files
                _miss = []
                try:
                    import json as _json
                    from pathlib import Path as _P
                    _ws = _P(__import__("os").getenv("WORKSPACE_DIR", ".")).resolve()
                    _pf = _ws / ".oblivion" / "plan.json"
                    if _pf.exists():
                        _miss = [s["path"] for s in _json.loads(_pf.read_text()).get("steps", [])
                                 if not (_ws / s["path"]).exists()]
                except Exception:
                    pass
                if _miss:
                    self.conversation.append({"role": "assistant", "content": llm_output})
                    self.conversation.append({
                        "role": "user",
                        "content": (
                            f"SYSTEM INTERRUPT: You repeated the same ~{_sz}-char output. STOP.\n"
                            f"Write this file NOW with write_file/batch_edit: `{_miss[0]}`\n"
                            f"Still missing: {', '.join(_miss)}"
                        ),
                    })
                    _prev_sizes.clear()
                    _prev_hashes.clear()
                    continue
                else:
                    console.print(Panel("All planned files done (loop broken).",
                                        title="[green]Done[/green]", border_style="green"))
                    return "Build complete. All planned files are on disk."

            self.conversation.append({"role": "assistant", "content": llm_output})

            parsed = parse_llm_output(llm_output)

            if isinstance(parsed, FinalAnswer):
                console.print()
                console.print(Panel(
                    Markdown(parsed.content),
                    title="[green]Done[/green]",
                    border_style="green",
                ))
                return parsed.content

            if isinstance(parsed, ToolCall):
                tool_name = parsed.tool
                tool_args = parsed.args

                if parsed.thought:
                    console.print(f"\n[cyan]{parsed.thought}[/cyan]")

                console.print(
                    f"[magenta]{tool_name}[/magenta]"
                    f"({', '.join(f'{k}={repr(v)[:40]}' for k, v in tool_args.items())})"
                )

                if tool_name == "finish":
                    summary = tool_args.get("summary", "Task complete.")
                    console.print(Panel(summary, title="[green]Done[/green]", border_style="green"))
                    return summary

                if tool_name == "write_file":
                    result = self._handle_write_file(tool_args)
                elif tool_name == "edit_file":
                    result = self._handle_edit_file(tool_args)
                elif tool_name == "run_bash":
                    result = self._handle_bash(tool_args)
                else:
                    result = dispatch(tool_name, tool_args)

                # Compress and logs observation values securely
                result = squeeze_observation(result)
                display = result[:600] + "\n[dim]...(truncated)[/dim]" if len(result) > 600 else result
                console.print(f"[green]Result:[/green] {display}")

                self.conversation.append({
                    "role": "user",
                    "content": (
                        f"OBSERVATION (result of {tool_name}):\n"
                        f"{result}\n\n"
                        f"Continue: give your next THOUGHT + ACTION, or FINAL_ANSWER if done."
                    ),
                })
                continue

            console.print("[yellow]Could not parse output. Asking LLM to retry...[/yellow]")
            self.conversation.append({
                "role": "user",
                "content": (
                    "Your last response was not in the correct format. "
                    "Use THOUGHT: then ACTION: {json} or THOUGHT: then FINAL_ANSWER: text"
                ),
            })

        return "Reached maximum iterations without completing the task."
