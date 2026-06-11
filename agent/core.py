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
    return f"""You are an expert AI coding agent. Help users understand and modify code.

# RESPONSE FORMAT (STRICT)

Each response MUST be EXACTLY one of these two formats:

Format A (taking an action):
THOUGHT: <one short sentence about what you will do>
ACTION: {{"tool": "<tool_name>", "args": {{<arguments>}}}}

Format B (giving final answer):
THOUGHT: <one short sentence>
FINAL_ANSWER: <your complete answer to the user, using real data from observations>

# CRITICAL RULES

1. NEVER make up code, file contents, or function names. ONLY use what you saw in OBSERVATIONS.
2. NEVER include backticks, code blocks, or markdown in your THOUGHT field.
3. NEVER repeat the same tool call with the same args twice.
4. KEEP THOUGHT SHORT - one sentence maximum.

# WORKFLOW FOR CODE QUESTIONS

When user asks where/how/what does X do:
  Step 1: search_code(query="X") to find relevant files
  Step 2: read_file(path="...") on the TOP result to see actual code
  Step 3: FINAL_ANSWER with quotes from the actual file (cite file:line)

When user asks to MODIFY code:
  Step 1: read_file to see current content
  Step 2: edit_file or write_file with the change
  Step 3: FINAL_ANSWER summarizing what changed

# AVAILABLE TOOLS

{get_tool_descriptions()}

# EXAMPLES

User: where is the parser?
THOUGHT: I will search for parser-related code.
ACTION: {{"tool": "search_code", "args": {{"query": "parser parse LLM output"}}}}

After observation showing agent/parser.py:
THOUGHT: Now I will read the file to see actual content.
ACTION: {{"tool": "read_file", "args": {{"path": "agent/parser.py"}}}}

After seeing the file:
THOUGHT: I have the parser code, I can answer now.
FINAL_ANSWER: The parser is in agent/parser.py. It defines parse_llm_output() which uses regex to extract THOUGHT, ACTION, and FINAL_ANSWER blocks from LLM text.
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
        p = Path(path)

        if p.exists() and p.is_file():
            try:
                original = p.read_text(encoding="utf-8")
            except Exception:
                original = ""

            diff_str = make_diff(original, new_content, filename=path)

            if not diff_str.strip():
                return "No changes detected - file already has this content."

            print_diff(diff_str, filename=path)

            if REQUIRE_APPROVAL_WRITE:
                if not ask_approval(f"write to {path}"):
                    return "Write cancelled by user."
        else:
            print_new_file(new_content, filename=path)

            if REQUIRE_APPROVAL_WRITE:
                if not ask_approval(f"create {path}"):
                    return "File creation cancelled by user."

        return dispatch("write_file", args)

    def _handle_edit_file(self, args: dict) -> str:
        path = args.get("path", "")
        old_text = args.get("old_text", "")
        new_text = args.get("new_text", "")

        p = Path(path)
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
        print_diff(diff_str, filename=path)

        if REQUIRE_APPROVAL_WRITE:
            if not ask_approval(f"edit {path}"):
                return "Edit cancelled by user."

        return dispatch("edit_file", args)

    def _handle_bash(self, args: dict) -> str:
        command = args.get("command", "")
        console.print(Panel(
            f"[bold yellow]Command:[/bold yellow] [white]{command}[/white]",
            title="[yellow]Run Shell Command?[/yellow]",
            border_style="yellow",
        ))
        if REQUIRE_APPROVAL_BASH:
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
