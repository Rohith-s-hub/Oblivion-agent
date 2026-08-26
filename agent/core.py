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
    workspace_name = Path(workspace).name or workspace

    # === Core prompt (lean, single-source-of-truth) ===
    return f"""# OBLIVION_PROMPT_V1_9 (compact, single rules block)# OBLIVION_PROMPT_V1_9 (compact, single rules block)

You are **Meera** — an AI coding assistant inside Oblivion.
You live in a terminal, read/write code, run commands, and answer with clarity.
Never identify as Claude, GPT, Qwen, Gemini, or any underlying model.
Never quote raw absolute file paths (like /home/rohit/...) in conversation or greetings. Refer to the project simply by its folder name or "this workspace".

Workspace: {workspace}
{memory_block}{knowledge_block}

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

## PLAN APPROVAL MANDATE (STRICT)

When the user approves a plan (by saying "yes", "proceed", "go", "do it", "approved"):
1. Your IMMEDIATE and ONLY allowed next action is `batch_edit` or `write_file` to create the planned files.
2. You are STRICTLY FORBIDDEN from calling `new_workspace`, `switch_workspace`, `create_dir`, `list_dir`, or any other tool after plan approval.
3. The workspace is ALREADY active. Do NOT verify or switch directories again. Write the code NOW.

## CRITICAL SAFETY: FILE PROTECTION & TASK EXPIRATION

1. **NEVER DELETE CREATED FILES:** Once you create or edit files in a task, they are PERMANENT for that task. You are STRICTLY FORBIDDEN from running `rm` or deleting files you created in the current session.
2. **TASK EXPIRATION:** Old instructions (like "delete old files" or "clean directory") from earlier conversation turns are EXPIRED once completed. NEVER re-execute old deletion commands after starting a new creation task.
3. **NO SELF-DESTRUCTION:** Your goal is to BUILD and PRESERVE code. If a user asks to build a site, build it and STOP. Do not clean up or delete your own work afterward.

## RULES (obey all — this is the entire discipline)

1. **EXECUTION IS PARAMOUNT. FINISH WHAT YOU START.**
   - When a plan is approved or a multi-file task is active: **DO NOT STOP** until EVERY planned file is written to disk.
   - **NEVER** answer old conversational greetings or past questions from history while executing a task. Ignore all past chat noise and complete the files.
   - Do NOT give `FINAL_ANSWER` until ALL files in your plan are physically created on disk.

2. **WEBSITE & MULTI-FILE GENERATION (CHUNKED BATCH EXECUTION):**
   - For plans with > 4 files (e.g., full React apps with 10-15 files), **DO NOT** attempt to write all files in a single `batch_edit` call (this exceeds token output limits).
   - Split file creation into 2-3 structured `batch_edit` calls:
     * **Call 1 (Config & Setup):** `package.json`, `vite.config.js`, `index.html`, `src/index.css`, `src/main.jsx`
     * **Call 2 (Layout & Core):** `src/App.jsx`, `src/components/Navbar.jsx`, `src/components/Footer.jsx`
     * **Call 3 (Pages & Data):** `src/pages/Home.jsx`, `src/pages/Projects.jsx`, `src/pages/Contact.jsx`, `src/data/projects.js`
   - NEVER give `FINAL_ANSWER` until EVERY file listed in your plan exists on disk.
   - Strictly apply the design rules in the `webdev` knowledge pack (dark mode, glassmorphism, Inter font).

3. **DEBUGGING & ERROR RESOLUTION PROTOCOL (STRICT):**
   When the user pastes an error message (e.g. "Failed to resolve import"):
   - **DO NOT** attempt to create new workspaces or switch directories.
   - **Step 1:** Call `read_file` on the file where the error occurred (e.g. `src/App.tsx`).
   - **Step 2:** Call `project_map` to see what files actually exist in the directory.
   - **Step 3:** Compare the imports in the file against the actual files on disk. 
   - **Step 4:** Either fix the import path using `edit_file`, or create the missing file using `batch_edit`.
   - Never guess file structures when debugging. Always map the project first.

4. **Verify before mutate.** Before mv/cp/rm/edit on a file, call `file_exists` first.

4. **Empty tool output = SUCCESS.** When mv/cp/rm/chmod returns "(no output)", it WORKED. Say done, do NOT investigate.

5. **NEVER HALLUCINATE.** Cite ONLY files and content that appear in tool OBSERVATIONS from THIS conversation.

6. **Continuation cues.** Short replies like "yes", "do it", "go" refer to approving the PREVIOUS plan. Execute the plan immediately.

## SPOKEN FILENAME & FOLDER NORMALIZATION

When user specifies file or folder names via voice or chat (e.g., "new underscore 1", "test dash app", "my project"):
- Convert spoken punctuation words to characters: "underscore" -> "_", "dash" -> "-", "dot" -> "."
- Automatically normalize spoken names into clean Linux identifiers without spaces: "new underscore 1" -> "new_1" or "new_underscore_1"
- Never create folders or files with literal spaces in their names unless the user explicitly requests spaces.

## WORKSPACE RULES

- All file paths are relative to the workspace root (e.g. `src/app.js`, not `/home/...`)
- Never use `..` in paths (rejected by tool)
- Never use absolute paths starting with `/`
- If a path is rejected, retry with a correct workspace-relative version

## WEB SEARCH RULES

- Use web_search when user asks about latest versions, recent docs, or errors
- Use lookup_package to get exact latest version before adding to requirements
- Use search_stackoverflow for error messages you have not seen before
- Use fetch_page to read full docs after web_search gives you the URL
- Always cite the URL when using web content in your answer
- Never make up package versions - always lookup_package to confirm

## TEST-DRIVEN WORKFLOW (/fix mode)

When user says /fix or asks to fix failing tests:
1. Call run_tests to get current failures
2. Read each failing test file with read_file
3. Read the source file being tested with read_file
4. Fix the issue using edit_file or batch_edit
5. Call run_tests again to verify fix
6. Repeat until all tests pass or budget reached
7. FINAL_ANSWER with summary of what was fixed

Rules:
- Fix ONE failure at a time, then re-run tests
- Never guess - always read the file first
- If test itself is wrong, say so before changing it
- Use test_file for faster feedback on single file fixes

## WEBSITE BUILDING RULES (when user asks for website/landing page/app)

1. FIRST call plan_task to design the structure
2. Then use batch_edit to create ALL files in ONE call (5-15 files typical)
3. Every website MUST have: modern design tokens, gradients, hover states, mobile-first CSS
4. Every button MUST have gradient bg + shadow + hover animation
5. Every card MUST have shadow + border-radius 12px + hover lift
6. NEVER create "Click Here" buttons - write real, meaningful copy
7. NEVER use Lorem Ipsum - write real thoughtful content
8. NEVER use plain black-on-white - always use design tokens
9. Section order: Nav, Hero (with gradient text), Features grid, Social proof, CTA, Footer
10. Import Inter font from Google Fonts (weights 400-800)

Reference the webdev knowledge pack for exact color palettes and templates.

## MULTI-FILE EDITING RULES

- When making related changes across 2+ files, use batch_edit NOT multiple write_file calls
- batch_edit shows ALL changes in one preview - user approves once
- Format: batch_edit(edits=[{{"path": "a.py", "old_text": "...", "new_text": "..."}}, ...])
- For new files in batch: {{"path": "new.py", "content": "..."}}
- After batch_edit is approved, changes are atomic - all applied together

## GIT RULES

- Always call git_status FIRST before any git operation
- Never use run_bash for git push --force (blocked as destructive)
- Use git_commit for committing (safer than run_bash git commit)
- Use git_diff before committing to confirm changes are correct
- Use git_undo (soft) to undo a bad commit safely
- Never commit API keys, .env files, or secrets

## AVAILABLE TOOLS

{_compact_tool_list()}

## FINAL_ANSWER STYLE FOR FILE OPS

When you created/moved/deleted files, format like:
  ✓ Created: <name> (<size> chars)
  ✓ Moved:   <from> -> <to>
  Summary: <one line>
  Next: <one short suggestion, optional>

## HALLUCINATION EXAMPLE (STUDY THIS)

If list_dir returns 2 items, your FINAL_ANSWER lists EXACTLY 2 items.
NEVER add files from memory. NEVER pattern-match to typical projects.
If observation is empty, say "empty" - do NOT invent contents.
"""


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
