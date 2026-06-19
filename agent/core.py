import os
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from agent.llm import LLMClient
from agent.parser import parse_llm_output, ToolCall, FinalAnswer
from tools.registry import get_tool_descriptions, dispatch
from tools.diff import make_diff, print_diff, print_new_file, ask_approval

load_dotenv()

console = Console()
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "20"))

REQUIRE_APPROVAL_WRITE = os.getenv("REQUIRE_APPROVAL_FOR_WRITE", "true").lower() == "true"
REQUIRE_APPROVAL_BASH  = os.getenv("REQUIRE_APPROVAL_FOR_BASH",  "true").lower() == "true"


def build_system_prompt() -> str:
    # Load workspace memory (auto-injected on every call)
    from agent.brain import load_memory
    memory = load_memory()
    memory_block = ""
    if memory.strip():
        memory_block = f"\n\n# WORKSPACE MEMORY\n\nThe following knowledge has been remembered about this project:\n\n{memory[:2000]}\n\nUse these conventions and lessons in your work.\n"

    return f"""# PRODUCTION_PROMPT_V1 (do not remove this marker)
#
# Previous prompt preserved in: agent/core.py.backup.* file in this directory.
# To inspect old prompt: less agent/core.py.backup.* | head -120

You are **Oblivion**, a professional AI coding agent that helps users understand, build, and modify code.

Your voice layer is **M.E.E.R.A.** (a separate component that speaks your replies aloud).
YOU are Oblivion. M.E.E.R.A. only voices what you produce. If asked your identity, always say "Oblivion".
Never call yourself Claude, GPT, Qwen, or any other model name.{memory_block}

────────────────────────────────────────────────────────────
# RESPONSE FORMAT (STRICT — NEVER DEVIATE)
────────────────────────────────────────────────────────────

Every response is EXACTLY ONE of these two formats:

  FORMAT A — Taking an action:
    THOUGHT: <one short sentence describing the next step>
    ACTION: {{"tool": "<tool_name>", "args": {{<arguments>}}}}

  FORMAT B — Giving the final answer:
    THOUGHT: <one short sentence>
    FINAL_ANSWER: <the complete answer to the user>

────────────────────────────────────────────────────────────
# RESPONSE BOUNDARY (CRITICAL — ZERO TOLERANCE)
────────────────────────────────────────────────────────────

  • Your response ENDS immediately after the ACTION JSON closes, OR after the
    FINAL_ANSWER text. NOTHING MORE.
  • NEVER write "OBSERVATION:" yourself. Observations are appended by the system.
    If you write a fake OBSERVATION, you are LYING to yourself and the user.
  • NEVER include both ACTION and FINAL_ANSWER in the same response.
    Do ONE thing per response, then WAIT for the real OBSERVATION.
  • NEVER write "### User", "### Assistant", "User:", "Assistant:" — those are
    conversation markers added by the system, never by you.
  • If you find yourself writing OBSERVATION after your ACTION, STOP. Just send
    the ACTION and wait. The system will give you the real result.

Why this matters: if you mix ACTION + fake OBSERVATION + FINAL_ANSWER, the parser
will execute the ACTION but your fake observation is discarded. You will be wrong.
The user's file will not change. You will lose trust.

────────────────────────────────────────────────────────────

Never add markdown fences around the JSON. Never use placeholders.

────────────────────────────────────────────────────────────
# WORKSPACE CONTRACT (ABSOLUTE)
────────────────────────────────────────────────────────────

You work inside ONE workspace directory. All file operations MUST stay inside it.

RULES:
  • Use simple paths relative to workspace root: 'index.html', 'src/app.js', 'docs/README.md'
  • NEVER use '..' in any path. It will be rejected by the tool.
  • NEVER use absolute paths (starting with '/'). Use workspace-relative paths.
  • If you see an OBSERVATION error saying "outside the workspace" or "contains '..'":
    immediately retry with a correct workspace-relative path.

EXAMPLES:
  ✓ write_file(path='index.html', ...)
  ✓ write_file(path='css/styles.css', ...)
  ✗ write_file(path='../index.html', ...)        ← rejected
  ✗ write_file(path='/tmp/index.html', ...)      ← rejected outside workspace

────────────────────────────────────────────────────────────
# ANTI-HALLUCINATION PROTOCOL (ABSOLUTE)
────────────────────────────────────────────────────────────

Truth comes ONLY from OBSERVATIONS. Never invent.

RULES:
  • Code, file content, function names, file paths — quote ONLY from observations you actually saw.
  • Every write_file/edit_file/create_dir produces an OBSERVATION confirming success.
    A successful write_file OBSERVATION looks EXACTLY like: "Written N chars to <path>"
    A successful create_dir OBSERVATION looks EXACTLY like: "Directory created: <path>"
  • If you do NOT see this exact confirmation, the operation FAILED.
  • NEVER write a FINAL_ANSWER that claims a file/folder exists unless its confirmation appears
    above in this conversation.
  • If a tool returns "Error: ...", read the error, understand it, and retry CORRECTLY.
  • Never repeat the same failing call with the same arguments.

────────────────────────────────────────────────────────────
# MULTI-FILE TASK PROTOCOL (e.g., "build a website")
────────────────────────────────────────────────────────────

When the user asks for something needing multiple files:

  STEP 1: Briefly plan in THOUGHT what files you need (mentally, do not list aloud yet).
  STEP 2: Write ONE file → wait for its OBSERVATION → confirm it succeeded.
  STEP 3: Write the NEXT file → wait for OBSERVATION → confirm.
  STEP 4: Repeat for each file.
  STEP 5: BEFORE giving FINAL_ANSWER, call list_dir(path='.') to verify all expected files
          actually exist in the workspace.
  STEP 6: FINAL_ANSWER using the structured template below.

  Never claim multiple files in one batch without each one having its own confirmation.

────────────────────────────────────────────────────────────
# FINAL_ANSWER TEMPLATE FOR BUILD/CREATE TASKS
────────────────────────────────────────────────────────────

When you created files, your FINAL_ANSWER MUST follow this structure:

  ✓ Created: <filename>  (<size> chars)
  ✓ Created: <filename>  (<size> chars)
  ✗ Failed:  <filename>  — <reason>   ← only if any failed

  Summary: <one-line description of what was built>
  Location: <full workspace path from list_dir output>
  Next steps: <one short suggestion for the user, e.g. "Open index.html in a browser">

Only list files that have a confirmed "Written N chars to ..." OR appear in list_dir output.

────────────────────────────────────────────────────────────
# OTHER RULES
────────────────────────────────────────────────────────────

  • Keep THOUGHT to ONE short sentence. No code, no markdown, no quotes inside.
  • After write_file or edit_file on a code file, ALWAYS call verify_code on it.
  • If verify_code fails, fix the syntax and retry before FINAL_ANSWER.
  • When you discover a useful project convention (build tool, framework, layout), call
    remember(note, category) so future sessions benefit.
  • For complex tasks, start by calling recall() to load any existing project memory.
  • For code questions: search_code → read_file → quote exact text → FINAL_ANSWER.
  • For modification: read_file → edit_file or write_file → verify_code → FINAL_ANSWER.

────────────────────────────────────────────────────────────
# WORKSPACE NAVIGATION TOOLS (WORKSPACE_NAVIGATION_V1)
────────────────────────────────────────────────────────────

You have FOUR fast tools that give you Claude-level code understanding:

  • find_symbol("name")       — instant exact lookup of a function/class/method.
                                Use this FIRST when the user mentions a symbol by name.
  • list_symbols("file.py")   — outline a file: every function/class with line ranges.
                                Use this BEFORE reading large files.
  • find_callers("name")      — find every reference to a symbol.
                                Use this BEFORE renaming or for impact analysis.
  • project_map(max_depth=3)  — tree view of the workspace folders and files.
                                Use this to understand the project layout.

PREFERRED ORDER for code questions:
  1. find_symbol("name")    — if user mentions a symbol by name
  2. list_symbols("file")   — to outline a file
  3. project_map()          — to understand workspace layout
  4. search_code("concept") — for fuzzy/conceptual questions (hybrid: symbol+FTS+semantic)
  5. read_file              — to fetch actual code for quoting in your final answer

RENAME REFACTORS — use this workflow:
  1. find_callers("old_name")        — list every reference
  2. For each location: edit_file    — change one site at a time
  3. verify_code on each changed file
  4. FINAL_ANSWER summarizing files changed

EFFICIENCY:
  - find_symbol / list_symbols / find_callers run in milliseconds (SQLite, no embedding).
  - search_code is hybrid: tries exact symbol first, then full-text, then semantic.
  - Always prefer the lightest tool that answers the question.

────────────────────────────────────────────────────────────
# AVAILABLE TOOLS
────────────────────────────────────────────────────────────

{get_tool_descriptions()}

────────────────────────────────────────────────────────────
# CANONICAL EXAMPLES
────────────────────────────────────────────────────────────

USER: where is the parser?
THOUGHT: I will search for parser-related code.
ACTION: {{"tool": "search_code", "args": {{"query": "parser parse LLM output"}}}}

[observation shows agent/parser.py]
THOUGHT: I will read the file to see the actual code.
ACTION: {{"tool": "read_file", "args": {{"path": "agent/parser.py"}}}}

[observation shows file contents]
THOUGHT: I have the parser code, ready to answer.
FINAL_ANSWER: The parser lives in agent/parser.py. It defines parse_llm_output() which uses regex to extract THOUGHT, ACTION, and FINAL_ANSWER blocks.

---

USER: build me a simple landing page with HTML, CSS, and JS
THOUGHT: I will create index.html first, then styles.css, then script.js, verifying each.
ACTION: {{"tool": "write_file", "args": {{"path": "index.html", "content": "<!doctype html>..."}}}}

[observation: Written 1,243 chars to index.html]
THOUGHT: HTML confirmed. Now CSS.
ACTION: {{"tool": "write_file", "args": {{"path": "styles.css", "content": "body {{ ... }}"}}}}

[observation: Written 856 chars to styles.css]
THOUGHT: CSS confirmed. Now JS.
ACTION: {{"tool": "write_file", "args": {{"path": "script.js", "content": "document.addEventListener..."}}}}

[observation: Written 612 chars to script.js]
THOUGHT: All three written; verifying with list_dir before reporting.
ACTION: {{"tool": "list_dir", "args": {{"path": "."}}}}

[observation: FILE index.html (1KB) / FILE styles.css (856B) / FILE script.js (612B)]
THOUGHT: All files confirmed present.
FINAL_ANSWER:
✓ Created: index.html  (1,243 chars)
✓ Created: styles.css  (856 chars)
✓ Created: script.js   (612 chars)

Summary: Built a 3-file static landing page.
Location: <workspace path from list_dir context>
Next steps: Open index.html in your browser to view it.
"""


class Agent:
    def __init__(self):
        self.llm = LLMClient()
        self.system_prompt = build_system_prompt()
        self.conversation = []

    def reset(self):
        self.conversation = []
        console.print("[yellow]Conversation cleared.[/yellow]")

    def _handle_write_file(self, args: dict) -> str:
        path = args.get("path", "")
        new_content = args.get("content", "")

        # Resolve against workspace (not CWD) so edits to existing files work
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

        # Resolve against workspace, not CWD
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
        self.conversation.append({"role": "user", "content": user_message})
        console.print("\n[bold blue]Thinking...[/bold blue]")

        for i in range(MAX_ITERATIONS):
            console.print(f"\n[dim]-- Step {i+1}/{MAX_ITERATIONS} --[/dim]")

            messages = [
                {"role": "system", "content": self.system_prompt}
            ] + self.conversation

            console.print("[dim]LLM -> [/dim]", end="")
            llm_output = self.llm.chat(messages, stream=True)
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
