"""
Textual TUI for the AI Coding Agent.
Run: uv run python -m ui.app
"""
import asyncio
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll, Container
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Header, Footer, Input, Static, RichLog, Tree, Button, Label, Markdown
)
from textual.widget import Widget
from rich.markdown import Markdown as RichMarkdown
from rich.syntax import Syntax
from rich.panel import Panel
from rich.text import Text

from agent.core import Agent
from agent.parser import parse_llm_output, ToolCall, FinalAnswer
from tools.registry import dispatch
from tools.diff import make_diff
from db.store import init_db, create_session, save_message


# ── Approval Modal ────────────────────────────────────────────────────────────
class ApprovalModal(ModalScreen[bool]):
    """Modal dialog asking the user to approve an action."""

    BINDINGS = [
        ("y", "approve", "Approve"),
        ("n", "deny", "Deny"),
        ("escape", "deny", "Cancel"),
    ]

    def __init__(self, title: str, body: str, diff_text: str = ""):
        super().__init__()
        self.title_text = title
        self.body_text = body
        self.diff_text = diff_text

    def compose(self) -> ComposeResult:
        with Container(id="modal-container"):
            yield Label(f"[bold yellow]⚠️  {self.title_text}[/bold yellow]", id="modal-title")
            yield Static(self.body_text, id="modal-body")
            if self.diff_text:
                yield Static(self._format_diff(), id="modal-diff")
            with Horizontal(id="modal-buttons"):
                yield Button("✓ Approve (y)", variant="success", id="btn-approve")
                yield Button("✗ Deny (n)", variant="error", id="btn-deny")

    def _format_diff(self) -> Text:
        text = Text()
        for line in self.diff_text.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                text.append(line + "\n", style="bold white")
            elif line.startswith("@@"):
                text.append(line + "\n", style="bold cyan")
            elif line.startswith("+"):
                text.append(line + "\n", style="bold green")
            elif line.startswith("-"):
                text.append(line + "\n", style="bold red")
            else:
                text.append(line + "\n", style="dim")
        return text

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-approve")

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:
        self.dismiss(False)


# ── Activity Item Widget ──────────────────────────────────────────────────────
class ActivityItem(Static):
    """A single tool activity line in the activity log."""

    def __init__(self, tool_name: str, args: dict, status: str = "running"):
        super().__init__()
        self.tool_name = tool_name
        self.args = args
        self.status = status
        self.result = ""
        self.update_display()

    def update_display(self):
        icons = {"running": "⏳", "done": "✓", "error": "✗", "pending": "⏸"}
        colors = {"running": "yellow", "done": "green", "error": "red", "pending": "magenta"}
        icon = icons.get(self.status, "•")
        color = colors.get(self.status, "white")

        # Short args display
        args_str = ", ".join(f"{k}={repr(v)[:30]}" for k, v in self.args.items())
        if len(args_str) > 60:
            args_str = args_str[:60] + "..."

        line = f"[{color}]{icon}[/{color}] [bold]{self.tool_name}[/bold]({args_str})"
        if self.result and self.status == "done":
            preview = self.result.strip().split("\n")[0][:60]
            line += f"\n     [dim]→ {preview}[/dim]"
        elif self.result and self.status == "error":
            line += f"\n     [red]→ {self.result[:60]}[/red]"

        self.update(line)

    def set_done(self, result: str):
        self.status = "done" if not result.startswith("Error") else "error"
        self.result = result
        self.update_display()


# ── Main App ──────────────────────────────────────────────────────────────────
class AgentApp(App):
    """The main TUI application."""

    CSS = """
    Screen {
        background: $surface;
    }

    #main-container {
        height: 100%;
    }

    #chat-panel {
        width: 65%;
        border: round $primary;
        padding: 0 1;
    }

    #side-panel {
        width: 35%;
    }

    #activity-panel {
        height: 70%;
        border: round $accent;
        padding: 0 1;
    }

    #workspace-panel {
        height: 30%;
        border: round $secondary;
        padding: 0 1;
    }

    #input-box {
        dock: bottom;
        height: 3;
        border: round $success;
        margin: 0 1;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $boost;
        color: $text;
        padding: 0 1;
    }

    ApprovalModal {
        align: center middle;
    }

    #modal-container {
        width: 80%;
        max-width: 100;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $warning;
        padding: 1 2;
    }

    #modal-title {
        margin-bottom: 1;
    }

    #modal-body {
        margin-bottom: 1;
        padding: 0 1;
    }

    #modal-diff {
        margin-bottom: 1;
        padding: 1;
        background: $boost;
        max-height: 20;
        overflow-y: auto;
    }

    #modal-buttons {
        height: 3;
        align: center middle;
    }

    #modal-buttons Button {
        margin: 0 1;
    }

    ActivityItem {
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+r", "reset", "Reset"),
        Binding("ctrl+n", "new_session", "New Session"),
        Binding("ctrl+l", "clear_chat", "Clear Chat"),
    ]

    TITLE = "🤖 AI Coding Agent"
    SUB_TITLE = "qwen3-coder:480b-cloud"

    iteration_count = reactive(0)

    def __init__(self):
        super().__init__()
        self.agent = Agent()
        self.session_id = None
        self.activity_items: list[ActivityItem] = []
        self.agent_busy = False
        self.current_status = "Idle"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="main-container"):
            # Left: Chat panel
            with Vertical(id="chat-panel"):
                yield Label("[bold cyan]💬 Conversation[/bold cyan]")
                yield RichLog(id="chat-log", wrap=True, highlight=True, markup=True)

            # Right: Activity + Workspace
            with Vertical(id="side-panel"):
                with Vertical(id="activity-panel"):
                    yield Label("[bold magenta]🔧 Activity[/bold magenta]")
                    yield VerticalScroll(id="activity-scroll")

                with Vertical(id="workspace-panel"):
                    yield Label("[bold green]📁 Workspace[/bold green]")
                    yield Tree("ai-agent/", id="workspace-tree")

        yield Input(placeholder="Ask the agent anything...", id="input-box")
        yield Static(self._status_text(), id="status-bar")
        yield Footer()

    def _status_text(self) -> str:
        msgs = len(self.agent.conversation) if self.agent else 0
        return (
            f"[bold]{self.current_status}[/bold]  |  "
            f"Session: {self.session_id or '-'}  |  "
            f"Msgs: {msgs}  |  "
            f"Step: {self.iteration_count}  |  "
            f"Ctrl+Q quit"
        )

    def update_status(self):
        self.query_one("#status-bar", Static).update(self._status_text())

    async def on_mount(self) -> None:
        # Initialize DB and session
        init_db()
        self.session_id = create_session()
        self.update_status()

        # Populate workspace tree
        self._populate_tree()

        # Greet the user
        log = self.query_one("#chat-log", RichLog)
        log.write(Panel(
            "[bold cyan]🤖 Agent ready![/bold cyan]\n\n"
            "Type your request below. The agent will:\n"
            "  • Think step-by-step\n"
            "  • Use tools (read/write/edit/bash)\n"
            "  • Ask approval before making changes\n\n"
            "[dim]Try: 'list files', 'read main.py', 'create test.py that prints hi'[/dim]",
            title="Welcome",
            border_style="cyan",
        ))

        # Focus input
        self.query_one("#input-box", Input).focus()

    def _populate_tree(self):
        """Fill workspace tree with files/dirs."""
        tree = self.query_one("#workspace-tree", Tree)
        tree.clear()
        root = tree.root
        root.expand()

        workspace = Path(".").resolve()
        skip = {".git", "__pycache__", ".venv", "node_modules"}

        def add_path(parent_node, path: Path, depth: int = 0):
            if depth > 3:
                return
            try:
                items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
                for item in items:
                    if item.name.startswith(".") or item.name in skip:
                        continue
                    if item.is_dir():
                        node = parent_node.add(f"📁 {item.name}/")
                        add_path(node, item, depth + 1)
                    else:
                        parent_node.add_leaf(f"📄 {item.name}")
            except PermissionError:
                pass

        add_path(root, workspace)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = event.value.strip()
        if not user_input or self.agent_busy:
            return

        # Clear input
        event.input.value = ""

        # Log user message immediately
        log = self.query_one("#chat-log", RichLog)
        log.write(Panel(user_input, title="[bold green]You[/bold green]", border_style="green"))

        # Show immediate "thinking" indicator
        log.write("[bold yellow]⏳ Agent is thinking...[/bold yellow]")

        # Update status bar
        self.current_status = "💭 Thinking..."
        self.update_status()

        save_message(self.session_id, "user", user_input)

        # Run agent in background
        self.agent_busy = True
        self.run_worker(self._run_agent(user_input), exclusive=True)

    async def _run_agent(self, user_message: str):
        """Run the agent loop, updating UI as it progresses."""
        log = self.query_one("#chat-log", RichLog)
        activity_scroll = self.query_one("#activity-scroll", VerticalScroll)

        self.agent.conversation.append({"role": "user", "content": user_message})

        MAX_ITERATIONS = 20

        for i in range(MAX_ITERATIONS):
            self.iteration_count = i + 1
            self.current_status = f"🧠 LLM thinking (step {i+1})..."
            self.update_status()

            # Add live spinner activity item
            spinner = ActivityItem("llm.chat", {"step": i + 1}, "running")
            await activity_scroll.mount(spinner)
            activity_scroll.scroll_end(animate=False)

            messages = [
                {"role": "system", "content": self.agent.system_prompt}
            ] + self.agent.conversation

            # Call LLM (non-streaming for simplicity; we will stream in next phase)
            try:
                llm_output = await asyncio.to_thread(
                    self.agent.llm.chat, messages, False
                )
                spinner.set_done(f"({len(llm_output)} chars)")
            except Exception as e:
                spinner.set_done(f"Error: {e}")
                log.write(f"[red]LLM error: {e}[/red]")
                break

            self.agent.conversation.append({"role": "assistant", "content": llm_output})
            parsed = parse_llm_output(llm_output)

            # ── Final Answer ──────────────────────────────────────────────────
            if isinstance(parsed, FinalAnswer):
                log.write(Panel(
                    RichMarkdown(parsed.content),
                    title="[bold blue]🤖 Agent[/bold blue]",
                    border_style="blue",
                ))
                save_message(self.session_id, "assistant", parsed.content)
                break

            # ── Tool Call ─────────────────────────────────────────────────────
            if isinstance(parsed, ToolCall):
                if parsed.thought:
                    thought_display = parsed.thought
                    if len(thought_display) > 300:
                        thought_display = thought_display[:300] + "..."
                    log.write(f"[cyan]💭[/cyan] [italic]{thought_display}[/italic]")

                # Handle finish
                if parsed.tool == "finish":
                    summary = parsed.args.get("summary", "Done.")
                    log.write(Panel(summary, title="[green]✓ Done[/green]", border_style="green"))
                    save_message(self.session_id, "assistant", summary)
                    break

                # Add activity item
                item = ActivityItem(parsed.tool, parsed.args, "running")
                await activity_scroll.mount(item)
                activity_scroll.scroll_end(animate=False)
                self.activity_items.append(item)

                # Update status
                self.current_status = f"🔧 {parsed.tool}..."
                self.update_status()

                # Special handling for write_file / edit_file / run_bash
                result = await self._handle_tool(parsed.tool, parsed.args, item)

                # Update activity item
                item.set_done(result)

                # Feed observation back
                self.agent.conversation.append({
                    "role": "user",
                    "content": (
                        f"OBSERVATION (result of {parsed.tool}):\n{result}\n\n"
                        f"Continue: next THOUGHT + ACTION, or FINAL_ANSWER."
                    ),
                })

                # Refresh workspace tree if file changed
                if parsed.tool in ("write_file", "edit_file", "create_dir"):
                    self._populate_tree()

                continue

            # ── Unparseable ───────────────────────────────────────────────────
            log.write("[yellow]⚠️  Could not parse LLM output, retrying...[/yellow]")
            self.agent.conversation.append({
                "role": "user",
                "content": "Invalid format. Use THOUGHT: then ACTION: {json} or FINAL_ANSWER: text"
            })

        self.agent_busy = False
        self.iteration_count = 0
        self.current_status = "✅ Idle"
        self.update_status()

    async def _handle_tool(self, tool_name: str, args: dict, item: ActivityItem) -> str:
        """Dispatch tool, with TUI approval modals for dangerous tools."""

        # write_file → show preview + approve
        if tool_name == "write_file":
            path = args.get("path", "")
            content = args.get("content", "")
            p = Path(path)

            if p.exists():
                original = p.read_text(encoding="utf-8", errors="ignore")
                diff = make_diff(original, content, path)
                title = f"Write to {path}?"
                body = f"This will modify {len(content)} bytes."
            else:
                diff = make_diff("", content, path)
                title = f"Create new file: {path}?"
                body = f"New file with {len(content.splitlines())} lines."

            item.status = "pending"
            item.update_display()

            approved = await self.push_screen_wait(ApprovalModal(title, body, diff))
            if not approved:
                return "User denied write_file."
            return dispatch("write_file", args)

        # edit_file → show diff + approve
        if tool_name == "edit_file":
            path = args.get("path", "")
            old = args.get("old_text", "")
            new = args.get("new_text", "")

            p = Path(path)
            if not p.exists():
                return f"Error: File not found: {path}"

            original = p.read_text(encoding="utf-8", errors="ignore")
            if old not in original:
                return f"Error: old_text not found in {path}"

            updated = original.replace(old, new, 1)
            diff = make_diff(original, updated, path)

            item.status = "pending"
            item.update_display()

            approved = await self.push_screen_wait(ApprovalModal(
                f"Edit {path}?",
                f"Replace {len(old.splitlines())} line(s) with {len(new.splitlines())} line(s).",
                diff,
            ))
            if not approved:
                return "User denied edit_file."
            return dispatch("edit_file", args)

        # run_bash → approve command
        if tool_name == "run_bash":
            command = args.get("command", "")

            item.status = "pending"
            item.update_display()

            approved = await self.push_screen_wait(ApprovalModal(
                "Run shell command?",
                f"$ {command}",
                "",
            ))
            if not approved:
                return "User denied run_bash."
            return dispatch("run_bash", args)

        # Safe tools — dispatch directly
        return await asyncio.to_thread(dispatch, tool_name, args)

    # ── Actions ───────────────────────────────────────────────────────────────
    def action_reset(self) -> None:
        self.agent.reset()
        self._clear_activity()
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        log.write("[yellow]🔄 Conversation reset.[/yellow]")
        self.update_status()

    def action_new_session(self) -> None:
        self.session_id = create_session()
        self.agent.reset()
        self._clear_activity()
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        log.write(f"[green]📝 New session started: {self.session_id}[/green]")
        self.update_status()

    def action_clear_chat(self) -> None:
        self.query_one("#chat-log", RichLog).clear()
        self._clear_activity()

    def _clear_activity(self):
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        for item in list(self.activity_items):
            try:
                item.remove()
            except Exception:
                pass
        self.activity_items.clear()


def main():
    app = AgentApp()
    app.run()


if __name__ == "__main__":
    main()
