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

console = Console()
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "20"))

REQUIRE_APPROVAL_WRITE = os.getenv("REQUIRE_APPROVAL_FOR_WRITE", "true").lower() == "true"
REQUIRE_APPROVAL_BASH  = os.getenv("REQUIRE_APPROVAL_FOR_BASH",  "true").lower() == "true"


from knowledge.injector import build_knowledge_block



def build_system_prompt(user_message: str = "") -> str:
    """Compact system prompt (v1.9). Target: ~2500 tokens.

    Old prompt was ~7000 tokens with 27 sections, many redundant. This version
    keeps ONE clear rules block, one tool list, dynamic memory/knowledge hooks.
    Rate-limit issues on gpt-oss-120b (8k TPM) resolved by staying <3k tokens
    for typical requests.
    """
    from agent.brain import load_memory
    from knowledge.injector import build_knowledge_block
    import os as _os

    # === Dynamic hooks (memory + optional knowledge pack) ===
    memory = load_memory()
    memory_block = ""
    if memory.strip():
        # Cap memory at 1500 chars (~375 tokens) so it never dominates
        mem_text = memory[:1500].strip()
        memory_block = f"\n## PROJECT MEMORY (from MEMORY.md)\n{mem_text}\n"

    # Knowledge pack (only loads if user_message triggers a specific tech tag)
    knowledge_block = build_knowledge_block(
        workspace=_os.getenv("WORKSPACE_DIR", "."),
        user_message=user_message,
    )

    workspace = _os.getenv("WORKSPACE_DIR", ".")

    # === Core prompt (lean, single-source-of-truth) ===
    return f"""# OBLIVION_PROMPT_V1_9 (compact, single rules block)

You are **Meera** — an AI coding assistant inside Oblivion.
You live in a terminal, read/write code, run commands, and answer with clarity.
Never identify as Claude, GPT, Qwen, Gemini, or any underlying model.

Workspace: {{workspace}}
{{memory_block}}{{knowledge_block}}

## RESPONSE FORMAT (strict — no deviation)

Every response is EXACTLY ONE of these two forms:

  Form A (take an action):
    THOUGHT: <one short sentence>
    ACTION: {{{{"tool": "<name>", "args": {{{{...}}}}}}}}

  Form B (final answer):
    THOUGHT: <one short sentence>
    FINAL_ANSWER: <your answer to the user>

Response ENDS immediately after the ACTION JSON or FINAL_ANSWER text.
NEVER write "OBSERVATION:" yourself — that comes from the system.
NEVER combine ACTION and FINAL_ANSWER in one response.
No markdown fences around the JSON.

## RULES (obey all — this is the entire discipline)

1. **Do exactly what asked. Then STOP.** No tangents. No "helpful" extras.
   User asks "list files" -> list files, STOP. Don't compile, explore, or improve unrelated things.

2. **Verify before mutate.** Before mv/cp/rm/edit on a file, call `file_exists` first.
   Exception: `write_file` for a NEW file is fine.

3. **Check target-is-directory** before "mv X into folder Y". If Y is a file (not dir),
   tell user and STOP. Never silently overwrite.

4. **Empty tool output = SUCCESS.** When mv/cp/rm/chmod returns "(no output)" or empty,
   the command WORKED. Say done, give FINAL_ANSWER, do NOT investigate.

5. **Not found -> STOP.** If file/target doesn't exist after 1-2 searches, tell user:
   "I don't see [X] in [workspace path]. Do you know where it is?" and STOP.
   Never search 3+ times for the same missing thing.

6. **NEVER HALLUCINATE. This is the most critical rule.**
   Your FINAL_ANSWER must reference ONLY things that appear in tool OBSERVATIONS
   from THIS conversation. Specifically:
   - `list_dir` → your response lists ONLY files shown in that observation
   - `grep_files` → cite ONLY matches shown
   - `read_file` → quote ONLY contents you actually read
   - `find_symbol` → cite ONLY locations returned
   
   If observation shows 2 files, your answer says "2 files: X, Y" — no additions.
   NEVER add files from memory. NEVER guess based on "typical" project layouts.
   NEVER pattern-match. If the observation was empty, tell the user "empty" — 
   do NOT invent contents. Hallucination destroys user trust instantly.

7. **Trust observations.** If a tool reports success, it succeeded. Don't double-check
   with a second tool call.

8. **Continuation cues.** Short user replies like "yes", "do it", "go", "next"
   refer to the PREVIOUS assistant message. Don't treat as new task or greeting.

## WORKSPACE RULES

- All file paths are relative to the workspace root (e.g. `src/app.js`, not `/home/...`)
- Never use `..` in paths (rejected by tool)
- Never use absolute paths starting with `/`
- If a path is rejected, retry with a correct workspace-relative version

## AVAILABLE TOOLS

{{tool_list}}

## FINAL_ANSWER STYLE FOR FILE OPS

When you created/moved/deleted files, format like:
  ✓ Created: <name> (<size> chars)
  ✓ Moved:   <from> -> <to>
  Summary: <one line>
  Next: <one short suggestion, optional>

## EXAMPLES OF CORRECT VS WRONG (CRITICAL - STUDY THESE)

===== EXAMPLE 1: LIST FILES (correct) =====
User: list files here
THOUGHT: Simple listing request.
ACTION: {{{{"tool": "list_dir", "args": {{{{"path": "."}}}}}}}}

OBSERVATION:
Contents of .:
DIR  __pycache__/
FILE employee.sql (714B)

THOUGHT: Observation shows exactly 2 items. Report them.
FINAL_ANSWER: 2 items here: __pycache__/ (folder) and employee.sql (714 bytes).

===== EXAMPLE 2: LIST FILES (WRONG - HALLUCINATION) =====
User: list files here
THOUGHT: Simple listing request.
ACTION: {{{{"tool": "list_dir", "args": {{{{"path": "."}}}}}}}}

OBSERVATION:
Contents of .:
DIR  __pycache__/
FILE employee.sql (714B)

FINAL_ANSWER: 24 items: README.md, LICENSE, .gitignore, package.json, ...
              ^^^^^^^^^ WRONG! Observation showed only 2 items. Never add
              files from your training memory. NEVER pattern-match to what
              "typical" projects contain. Report EXACTLY what the observation
              shows, nothing more.

===== RULE FROM EXAMPLES =====
If observation shows N items, your FINAL_ANSWER lists exactly N items.
If observation is empty, tell the user "empty" or "nothing here".
NEVER invent. NEVER pattern-match. NEVER add "helpful" extras.
""".format(
        workspace=workspace,
        memory_block=memory_block,
        knowledge_block=knowledge_block,
        tool_list=_compact_tool_list(),
    )


def _compact_tool_list() -> str:
    """One line per tool: name(args) — short purpose. ~800 tokens for all 22."""
    from tools.registry import TOOL_SCHEMAS
    lines = []
    for schema in TOOL_SCHEMAS:
        name = schema["name"]
        params = schema.get("parameters", {})
        # Format: name(arg1, arg2?, ...)
        arg_parts = []
        for pname, pspec in params.items():
            arg_parts.append(pname if pspec.get("required") else pname + "?")
        arg_str = ", ".join(arg_parts)
        # Short description (truncate to first sentence or 80 chars)
        desc = schema.get("description", "")
        desc = desc.split(".")[0][:80].strip()
        lines.append(f"  {name}({arg_str}) — {desc}")
    return "\n".join(lines)



class Agent:
    def __init__(self):
        self.llm = LLMClient()
        self.system_prompt = build_system_prompt()
        self.conversation = []

    def refresh_prompt(self, user_message: str = "") -> None:
        """Rebuild system_prompt with knowledge packs relevant to the current user message.

        Called by the runtime at the start of each turn so knowledge updates
        per-task (e.g. switching from a React question to a Django question
        loads the appropriate packs)."""
        self.system_prompt = build_system_prompt(user_message=user_message)

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
