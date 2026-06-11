"""
OBLIVION - AI Coding Agent
Cyberpunk-themed TUI with slash commands.
"""
import asyncio
import os
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll, Container
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Header, Footer, Input, Static, RichLog, Tree, Button, Label, OptionList
)
from textual.widgets.option_list import Option
from rich.markdown import Markdown as RichMarkdown
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich.console import Group

from agent.core import Agent
from agent.parser import parse_llm_output, ToolCall, FinalAnswer
from tools.registry import dispatch
from tools.diff import make_diff
from db.store import init_db, create_session, save_message, load_session, list_sessions


# ── Cyberpunk ASCII Banner ────────────────────────────────────────────────────
BANNER = r"""
 ██████╗ ██████╗ ██╗     ██╗██╗   ██╗██╗ ██████╗ ███╗   ██╗
██╔═══██╗██╔══██╗██║     ██║██║   ██║██║██╔═══██╗████╗  ██║
██║   ██║██████╔╝██║     ██║██║   ██║██║██║   ██║██╔██╗ ██║
██║   ██║██╔══██╗██║     ██║╚██╗ ██╔╝██║██║   ██║██║╚██╗██║
╚██████╔╝██████╔╝███████╗██║ ╚████╔╝ ██║╚██████╔╝██║ ╚████║
 ╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝
"""

TAGLINE = "▓▓▓  N E U R A L   C O D E   A G E N T   v 1 . 2 . 0  ▓▓▓"

# Braille spinner frames - smooth rotation
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Pulsing dot frames for status bar
PULSE_FRAMES = ["●", "◉", "○", "◌", "○", "◉"]

# Rotating accent colors for active state
ACCENT_COLORS = ["#00ff9f", "#00d9ff", "#b537f2", "#ff006e"]


SLASH_COMMANDS = [
    ("/help",       "Show all slash commands"),
    ("/clear",      "Clear chat history"),
    ("/index",      "Re-index current workspace"),
    ("/index status", "Show current chunk count"),
    ("/workspace",  "Show / set workspace directory"),
    ("/model",      "Show / set LLM model"),
    ("/save",       "Save current session"),
    ("/load",       "Resume a saved session"),
    ("/sessions",   "List all saved sessions"),
    ("/stats",      "Show conversation stats"),
    ("/quit",       "Exit Oblivion"),
]


# ── Approval Modal ────────────────────────────────────────────────────────────
class ApprovalModal(ModalScreen[bool]):
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
            yield Label(f"[bold red on black]⚠  {self.title_text}[/bold red on black]", id="modal-title")
            yield Static(self.body_text, id="modal-body")
            if self.diff_text:
                yield Static(self._format_diff(), id="modal-diff")
            with Horizontal(id="modal-buttons"):
                yield Button("✓ APPROVE (y)", variant="success", id="btn-approve")
                yield Button("✗ DENY (n)", variant="error", id="btn-deny")

    def _format_diff(self) -> Text:
        text = Text()
        for line in self.diff_text.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                text.append(line + "\n", style="bold white on grey15")
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

    def action_approve(self) -> None: self.dismiss(True)
    def action_deny(self) -> None: self.dismiss(False)


# ── Activity Item ─────────────────────────────────────────────────────────────
class ActivityItem(Static):
    _frame_idx = 0

    def __init__(self, tool_name: str, args: dict, status: str = "running"):
        super().__init__()
        self.tool_name = tool_name
        self.args = args
        self.status = status
        self.result = ""
        self.update_display()

    def _spinner_frame(self) -> str:
        ActivityItem._frame_idx = (ActivityItem._frame_idx + 1) % len(SPINNER_FRAMES)
        return SPINNER_FRAMES[ActivityItem._frame_idx]

    def update_display(self):
        icons  = {"running": self._spinner_frame(), "done": "●", "error": "✗", "pending": "◐"}
        colors = {"running": "yellow", "done": "green", "error": "red", "pending": "magenta"}
        icon = icons.get(self.status, "·")
        color = colors.get(self.status, "white")

        args_str = ", ".join(f"{k}={repr(v)[:30]}" for k, v in self.args.items())
        if len(args_str) > 55:
            args_str = args_str[:55] + "…"

        line = f"[{color}]{icon}[/{color}] [bold]{self.tool_name}[/bold]([dim cyan]{args_str}[/dim cyan])"
        if self.result and self.status == "done":
            preview = self.result.strip().split("\n")[0][:55]
            line += f"\n  [dim green]└→[/dim green] [dim]{preview}[/dim]"
        elif self.result and self.status == "error":
            line += f"\n  [dim red]└→[/dim red] [red]{self.result[:55]}[/red]"

        self.update(line)

    def set_done(self, result: str):
        self.status = "done" if not result.startswith("Error") else "error"
        self.result = result
        self.update_display()


# ── Main App ──────────────────────────────────────────────────────────────────
class OblivionApp(App):
    CSS = """
    Screen {
        background: #0a0a0f;
    }
    
    Header {
        background: #1a0a2e;
        color: #00ff9f;
    }
    
    Footer {
        background: #1a0a2e;
        color: #ff006e;
    }

    #main-container { height: 100%; }

    #chat-panel {
        width: 65%;
        border: round #ff006e;
        padding: 0 1;
        background: #0a0a0f;
    }

    #side-panel { width: 35%; }

    #activity-panel {
        height: 60%;
        border: round #00ff9f;
        padding: 0 1;
        background: #0f0a14;
    }

    #workspace-panel {
        height: 40%;
        border: round #b537f2;
        padding: 0 1;
        background: #0f0a14;
    }

    #input-box {
        dock: bottom;
        height: 3;
        border: round #00d9ff;
        margin: 0 1;
        background: #0a0a0f;
        color: #00ff9f;
    }

    Input:focus {
        border: round #00ff9f;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: #1a0a2e;
        color: #00ff9f;
        padding: 0 1;
    }

    ApprovalModal { align: center middle; }

    #modal-container {
        width: 80%;
        max-width: 100;
        height: auto;
        max-height: 80%;
        background: #0a0a0f;
        border: thick #ff006e;
        padding: 1 2;
    }

    #modal-title { margin-bottom: 1; }
    #modal-body { margin-bottom: 1; padding: 0 1; color: #ffffff; }

    #modal-diff {
        margin-bottom: 1;
        padding: 1;
        background: #1a0a2e;
        max-height: 20;
        overflow-y: auto;
    }

    #modal-buttons { height: 3; align: center middle; }
    #modal-buttons Button { margin: 0 1; }

    ActivityItem { margin-bottom: 1; color: #ffffff; }

    Label { color: #00ff9f; }
    
    Tree { background: #0f0a14; color: #00d9ff; }
    Tree:focus { background: #0f0a14; }

    #slash-suggestions {
        dock: bottom;
        offset: 1 -5;
        height: auto;
        max-height: 14;
        width: 65;
        margin: 0;
        background: #0f0a14;
        border: round #00ff9f;
        display: none;
    }

    #slash-suggestions.visible {
        display: block;
    }

    #slash-suggestions > .option-list--option-highlighted {
        background: #ff006e;
        color: #ffffff;
    }

    #slash-suggestions > .option-list--option {
        color: #00d9ff;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+r", "reset", "Reset"),
        Binding("ctrl+n", "new_session", "New"),
        Binding("ctrl+l", "clear_chat", "Clear"),
        Binding("ctrl+h", "show_help", "Help"),
    ]

    TITLE = "◢◤ OBLIVION ◥◣"
    SUB_TITLE = "▓ qwen3-coder:480b ▓ neural code agent ▓"

    iteration_count = reactive(0)

    def __init__(self):
        super().__init__()
        self.agent = Agent()
        self.session_id = None
        self.activity_items: list[ActivityItem] = []
        self.agent_busy = False
        self.current_status = "READY"
        self._pulse_idx = 0
        self._spinner_idx = 0
        self._accent_idx = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="main-container"):
            with Vertical(id="chat-panel"):
                yield Label("[bold #ff006e]◢ NEURAL LINK ◣[/bold #ff006e]")
                yield RichLog(id="chat-log", wrap=True, highlight=True, markup=True)

            with Vertical(id="side-panel"):
                with Vertical(id="activity-panel"):
                    yield Label("[bold #00ff9f]◢ PROCESS MONITOR ◣[/bold #00ff9f]")
                    yield VerticalScroll(id="activity-scroll")

                with Vertical(id="workspace-panel"):
                    yield Label("[bold #b537f2]◢ FILESYSTEM ◣[/bold #b537f2]")
                    yield Tree("◆ root/", id="workspace-tree")

        yield Input(placeholder="◢ Enter command or /help for slash commands…", id="input-box")
        yield OptionList(id="slash-suggestions")
        yield Static(self._status_text(), id="status-bar")
        yield Footer()

    def _status_text(self) -> str:
        msgs = len(self.agent.conversation) if self.agent else 0
        workspace = os.path.basename(os.getenv("WORKSPACE_DIR", ".")) or "/"
        model = os.getenv("DEFAULT_MODEL", "qwen3-coder:480b-cloud").split("/")[-1][:25]

        # Pulsing dot when busy, static when idle
        if self.agent_busy:
            self._pulse_idx = (self._pulse_idx + 1) % len(PULSE_FRAMES)
            pulse = f"[#ff006e]{PULSE_FRAMES[self._pulse_idx]}[/#ff006e]"
            status_color = "#ffea00"
        else:
            pulse = "[#00ff9f]●[/#00ff9f]"
            status_color = "#00ff9f"

        return (
            f"{pulse} [bold {status_color}]{self.current_status}[/bold {status_color}]"
            f"  [dim]│[/dim]  [#00d9ff]◆ {workspace}[/#00d9ff]"
            f"  [dim]│[/dim]  [#b537f2]⬢ {model}[/#b537f2]"
            f"  [dim]│[/dim]  [#ff006e]session {self.session_id or '-'}[/#ff006e]"
            f"  [dim]│[/dim]  msg {msgs}  step {self.iteration_count}"
            f"  [dim]│[/dim]  [dim]^Q quit ^H help[/dim]"
        )

    def update_status(self):
        try:
            self.query_one("#status-bar", Static).update(self._status_text())
        except Exception:
            pass

    async def on_mount(self) -> None:
        init_db()
        self.session_id = create_session()
        self.update_status()
        self._populate_tree()

        # Drive animations - 100ms tick rate (10fps)
        self.set_interval(0.1, self._animate_tick)

        log = self.query_one("#chat-log", RichLog)

        # Typewriter intro - banner appears line by line with delays
        self.run_worker(self._typewriter_intro(log), exclusive=False)

        self.query_one("#input-box", Input).focus()

    async def _typewriter_intro(self, log) -> None:
        """Show banner with typewriter effect."""
        # Boot sequence messages
        boot_msgs = [
            ("[dim #00ff9f]▸ Initializing neural pathways...[/dim #00ff9f]", 0.05),
            ("[dim #00ff9f]▸ Loading qwen3-coder weights...[/dim #00ff9f]", 0.05),
            ("[dim #00ff9f]▸ Mounting vector database...[/dim #00ff9f]", 0.05),
            ("[dim #00ff9f]▸ Activating tool registry...[/dim #00ff9f]", 0.05),
            ("[dim #00ff9f]▸ Establishing neural link...[/dim #00ff9f]", 0.1),
            ("[bold #00ff9f]▸ ALL SYSTEMS ONLINE[/bold #00ff9f]", 0.2),
            ("", 0.1),
        ]

        for msg, delay in boot_msgs:
            log.write(msg)
            await asyncio.sleep(delay)

        # Banner - reveal line by line
        for line in BANNER.splitlines():
            if line.strip():
                log.write(Align.center(Text(line, style="bold #00ff9f")))
                await asyncio.sleep(0.04)

        await asyncio.sleep(0.2)
        log.write(Align.center(Text(TAGLINE, style="bold #ff006e")))
        await asyncio.sleep(0.3)
        log.write("")

        # System info panel
        log.write(Panel(
            "[#00ff9f]◢ NEURAL INTERFACE ACTIVE[/#00ff9f]\n\n"
            "[white]Model:[/white]      [#00d9ff]" + os.getenv("DEFAULT_MODEL", "?").split("/")[-1] + "[/#00d9ff]\n"
            "[white]Workspace:[/white]  [#b537f2]" + os.getenv("WORKSPACE_DIR", ".") + "[/#b537f2]\n"
            "[white]Session:[/white]    [#ff006e]#" + str(self.session_id) + "[/#ff006e]\n\n"
            "[dim]┌─ Quick Start ─────────────────────────────┐[/dim]\n"
            "[dim]│[/dim]  [#00ff9f]/[/#00ff9f]              show slash commands\n"
            "[dim]│[/dim]  [italic]'list files in agent/'[/italic]      natural lang\n"
            "[dim]│[/dim]  [italic]'where is the ReAct loop?'[/italic]  semantic search\n"
            "[dim]└───────────────────────────────────────────┘[/dim]",
            title="[bold #00ff9f]◢ SYSTEM ONLINE ◣[/bold #00ff9f]",
            border_style="#00ff9f",
        ))

    def _animate_tick(self) -> None:
        """Called every 100ms to drive animations."""
        # Refresh status bar (drives pulse)
        if self.agent_busy:
            self.update_status()

        # Refresh running activity items (drives spinners)
        for item in self.activity_items:
            if item.status == "running" or item.status == "pending":
                item.update_display()

    def _populate_tree(self):
        tree = self.query_one("#workspace-tree", Tree)
        tree.clear()
        root = tree.root
        root.expand()

        workspace = Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()
        skip = {".git", "__pycache__", ".venv", "node_modules", "dist", "build", ".chroma"}

        def add_path(parent_node, path: Path, depth: int = 0):
            if depth > 3:
                return
            try:
                items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
                for item in items:
                    if item.name.startswith(".") or item.name in skip:
                        continue
                    if item.is_dir():
                        node = parent_node.add(f"◆ {item.name}/")
                        add_path(node, item, depth + 1)
                    else:
                        parent_node.add_leaf(f"◇ {item.name}")
            except PermissionError:
                pass

        add_path(root, workspace)

    # ── Slash Command Handler ─────────────────────────────────────────────────
    async def handle_slash(self, cmd: str) -> bool:
        """Returns True if command was handled."""
        log = self.query_one("#chat-log", RichLog)
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if command == "/help":
            log.write(Panel(
                "[bold #00ff9f]◢ SLASH COMMANDS ◣[/bold #00ff9f]\n\n"
                "[#00d9ff]/help[/#00d9ff]                  Show this help\n"
                "[#00d9ff]/clear[/#00d9ff]                 Clear chat history\n"
                "[#00d9ff]/index[/#00d9ff]                 Re-index current workspace\n"
                "[#00d9ff]/index status[/#00d9ff]          Show chunk count\n"
                "[#00d9ff]/workspace[/#00d9ff]             Show current workspace\n"
                "[#00d9ff]/workspace <path>[/#00d9ff]      Switch workspace\n"
                "[#00d9ff]/model[/#00d9ff]                 Show current model\n"
                "[#00d9ff]/model <name>[/#00d9ff]          Switch LLM model\n"
                "[#00d9ff]/save <name>[/#00d9ff]           Save session\n"
                "[#00d9ff]/load <name>[/#00d9ff]           Resume saved session\n"
                "[#00d9ff]/sessions[/#00d9ff]              List saved sessions\n"
                "[#00d9ff]/stats[/#00d9ff]                 Show conversation stats\n"
                "[#00d9ff]/quit[/#00d9ff]                  Exit Oblivion",
                title="[bold #ff006e]HELP[/bold #ff006e]",
                border_style="#ff006e",
            ))
            return True

        if command == "/clear":
            log.clear()
            self._clear_activity()
            log.write("[#00ff9f]◢ Neural link cleared. Ready for new directives.[/#00ff9f]")
            return True

        if command == "/index":
            if arg == "status":
                from agent.rag import index_stats
                stats = index_stats()
                log.write(Panel(
                    f"[#00ff9f]Total chunks indexed:[/#00ff9f] {stats['total_chunks']}\n"
                    f"[#00ff9f]Storage path:[/#00ff9f] [dim]{stats['index_path']}[/dim]",
                    title="[#b537f2]INDEX STATUS[/#b537f2]",
                    border_style="#b537f2",
                ))
            else:
                log.write("[#ff006e]◢ Re-indexing workspace... (this may take a minute)[/#ff006e]")
                self.current_status = "▓ INDEXING"
                self.update_status()
                from agent.rag import index_codebase, clear_index
                clear_index()
                stats = await asyncio.to_thread(index_codebase, None, False)
                self.current_status = "▓ READY"
                self.update_status()
                log.write(Panel(
                    f"[#00ff9f]✓ Indexed[/#00ff9f] {stats['files_indexed']} files, "
                    f"{stats['chunks_added']} chunks "
                    f"([#ff006e]{stats['skipped']} skipped[/#ff006e])",
                    border_style="#00ff9f",
                ))
            return True

        if command == "/workspace":
            if not arg:
                log.write(f"[#00ff9f]Current workspace:[/#00ff9f] {os.getenv('WORKSPACE_DIR', '.')}")
            else:
                expanded = os.path.expanduser(arg)
                if not os.path.isdir(expanded):
                    log.write(f"[#ff006e]✗ Not a directory: {expanded}[/#ff006e]")
                    return True
                os.environ["WORKSPACE_DIR"] = expanded
                # Persist to .env
                env_path = Path.home() / "ai-agent" / ".env"
                if env_path.exists():
                    lines = env_path.read_text().splitlines()
                    new_lines = [l for l in lines if not l.startswith("WORKSPACE_DIR=")]
                    new_lines.append(f"WORKSPACE_DIR={expanded}")
                    env_path.write_text("\n".join(new_lines) + "\n")
                log.write(f"[#00ff9f]✓ Workspace set to:[/#00ff9f] {expanded}")
                log.write("[#ff006e]◢ Run /index to index the new workspace[/#ff006e]")
                self._populate_tree()
                self.update_status()
            return True

        if command == "/model":
            if not arg:
                log.write(f"[#00ff9f]Current model:[/#00ff9f] {os.getenv('DEFAULT_MODEL', '?')}")
            else:
                # Add ollama/ prefix if not present
                if "/" not in arg:
                    arg = f"ollama/{arg}"
                os.environ["DEFAULT_MODEL"] = arg
                env_path = Path.home() / "ai-agent" / ".env"
                if env_path.exists():
                    lines = env_path.read_text().splitlines()
                    new_lines = [l for l in lines if not l.startswith("DEFAULT_MODEL=")]
                    new_lines.append(f"DEFAULT_MODEL={arg}")
                    env_path.write_text("\n".join(new_lines) + "\n")
                self.agent = Agent()  # reload with new model
                log.write(f"[#00ff9f]✓ Switched to:[/#00ff9f] {arg}")
                self.update_status()
            return True

        if command == "/save":
            if not arg:
                log.write("[#ff006e]Usage: /save <name>[/#ff006e]")
                return True
            save_dir = Path.home() / ".ai-agent" / "sessions"
            save_dir.mkdir(parents=True, exist_ok=True)
            import json
            (save_dir / f"{arg}.json").write_text(
                json.dumps(self.agent.conversation, indent=2)
            )
            log.write(f"[#00ff9f]✓ Saved session:[/#00ff9f] {arg}")
            return True

        if command == "/load":
            if not arg:
                log.write("[#ff006e]Usage: /load <name>[/#ff006e]")
                return True
            save_path = Path.home() / ".ai-agent" / "sessions" / f"{arg}.json"
            if not save_path.exists():
                log.write(f"[#ff006e]✗ Session not found: {arg}[/#ff006e]")
                return True
            import json
            self.agent.conversation = json.loads(save_path.read_text())
            log.write(f"[#00ff9f]✓ Loaded session:[/#00ff9f] {arg} ({len(self.agent.conversation)} messages)")
            return True

        if command == "/sessions":
            save_dir = Path.home() / ".ai-agent" / "sessions"
            if not save_dir.exists() or not list(save_dir.iterdir()):
                log.write("[dim]No saved sessions yet. Use /save <name>[/dim]")
            else:
                sessions = sorted(save_dir.glob("*.json"))
                lines = [f"[#00d9ff]{s.stem}[/#00d9ff]  [dim]({s.stat().st_size}B)[/dim]" for s in sessions]
                log.write(Panel(
                    "\n".join(lines),
                    title="[#b537f2]SAVED SESSIONS[/#b537f2]",
                    border_style="#b537f2",
                ))
            return True

        if command == "/stats":
            log.write(Panel(
                f"[#00ff9f]Session ID:[/#00ff9f] {self.session_id}\n"
                f"[#00ff9f]Messages:[/#00ff9f] {len(self.agent.conversation)}\n"
                f"[#00ff9f]Model:[/#00ff9f] {os.getenv('DEFAULT_MODEL', '?')}\n"
                f"[#00ff9f]Workspace:[/#00ff9f] {os.getenv('WORKSPACE_DIR', '?')}",
                title="[#b537f2]STATS[/#b537f2]",
                border_style="#b537f2",
            ))
            return True

        if command == "/quit":
            self.exit()
            return True

        log.write(f"[#ff006e]✗ Unknown command: {command}[/#ff006e]  Type [#00ff9f]/help[/#00ff9f]")
        return True

    def on_input_changed(self, event: Input.Changed) -> None:
        """Show slash command suggestions as the user types."""
        text = event.value
        suggestions = self.query_one("#slash-suggestions", OptionList)

        if text.startswith("/"):
            # Filter commands by what user typed
            query = text.lower()
            matches = [
                (cmd, desc) for cmd, desc in SLASH_COMMANDS
                if cmd.startswith(query)
            ]
            if matches:
                suggestions.clear_options()
                for cmd, desc in matches:
                    # Two-column formatting: command (cyan) + description (dim)
                    label = f"[bold #00ff9f]{cmd:<18}[/bold #00ff9f] [dim]{desc}[/dim]"
                    suggestions.add_option(Option(label, id=cmd))
                suggestions.highlighted = 0
                suggestions.add_class("visible")
            else:
                suggestions.remove_class("visible")
        else:
            suggestions.remove_class("visible")

    async def on_key(self, event) -> None:
        """Handle arrow keys + Tab to navigate suggestions."""
        suggestions = self.query_one("#slash-suggestions", OptionList)
        input_widget = self.query_one("#input-box", Input)

        if not suggestions.has_class("visible"):
            return

        if event.key == "down":
            if suggestions.highlighted is None:
                suggestions.highlighted = 0
            elif suggestions.highlighted < suggestions.option_count - 1:
                suggestions.highlighted += 1
            event.stop()
            event.prevent_default()

        elif event.key == "up":
            if suggestions.highlighted is None:
                suggestions.highlighted = suggestions.option_count - 1
            elif suggestions.highlighted > 0:
                suggestions.highlighted -= 1
            event.stop()
            event.prevent_default()

        elif event.key == "tab":
            # Autocomplete to highlighted option
            if suggestions.highlighted is not None:
                opt = suggestions.get_option_at_index(suggestions.highlighted)
                if opt.id:
                    input_widget.value = opt.id + " "
                    input_widget.cursor_position = len(input_widget.value)
                    suggestions.remove_class("visible")
            event.stop()
            event.prevent_default()

        elif event.key == "enter":
            # If suggestion box is visible AND user hasn't typed past the suggestion,
            # autocomplete instead of submitting
            current = input_widget.value.strip()
            if suggestions.highlighted is not None:
                opt = suggestions.get_option_at_index(suggestions.highlighted)
                # Only auto-complete on Enter if user is still typing the slash command
                # (not if they've typed args like "/index status")
                if opt.id and current == opt.id.split()[0][:len(current)]:
                    # User typed e.g. "/i" and /index is highlighted -> autocomplete
                    if current != opt.id:
                        input_widget.value = opt.id
                        input_widget.cursor_position = len(input_widget.value)
                        suggestions.remove_class("visible")
                        event.stop()
                        event.prevent_default()
                        return
            # Otherwise let Input.Submitted fire normally

        elif event.key == "escape":
            suggestions.remove_class("visible")
            event.stop()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        # Hide suggestions on submit
        try:
            self.query_one("#slash-suggestions", OptionList).remove_class("visible")
        except Exception:
            pass

        user_input = event.value.strip()
        if not user_input or self.agent_busy:
            return

        event.input.value = ""

        # ── Slash command? ────────────────────────────────────────────────────
        if user_input.startswith("/"):
            # Just "/" alone? Treat as request to see commands
            if user_input == "/":
                await self.handle_slash("/help")
                return
            await self.handle_slash(user_input)
            return

        log = self.query_one("#chat-log", RichLog)
        log.write(Panel(
            f"[#ffffff]{user_input}[/#ffffff]",
            title="[bold #ff006e]◢ INPUT[/bold #ff006e]",
            border_style="#ff006e",
        ))
        log.write("[bold yellow]◌ Processing...[/bold yellow]")
        self.current_status = "▓ THINKING"
        self.update_status()

        save_message(self.session_id, "user", user_input)
        self.agent_busy = True
        self.run_worker(self._run_agent(user_input), exclusive=True)

    async def _run_agent(self, user_message: str):
        log = self.query_one("#chat-log", RichLog)
        activity_scroll = self.query_one("#activity-scroll", VerticalScroll)

        self.agent.conversation.append({"role": "user", "content": user_message})
        MAX_ITERATIONS = 20

        for i in range(MAX_ITERATIONS):
            self.iteration_count = i + 1
            self.current_status = f"▓ LLM step {i+1}"
            self.update_status()

            spinner = ActivityItem("llm.chat", {"step": i + 1}, "running")
            await activity_scroll.mount(spinner)
            activity_scroll.scroll_end(animate=False)

            messages = [{"role": "system", "content": self.agent.system_prompt}] + self.agent.conversation

            try:
                token_queue: asyncio.Queue = asyncio.Queue()
                loop = asyncio.get_event_loop()
                token_count = {"n": 0}

                def on_token(tok: str):
                    loop.call_soon_threadsafe(token_queue.put_nowait, tok)

                async def consume_tokens():
                    accum = ""
                    while True:
                        try:
                            tok = await asyncio.wait_for(token_queue.get(), timeout=0.05)
                        except asyncio.TimeoutError:
                            if llm_task.done():
                                break
                            continue
                        if tok is None:
                            break
                        accum += tok
                        token_count["n"] += 1
                        spinner.result = f"streaming… {token_count['n']} tokens"
                        spinner.update_display()
                        if "\n" in accum or len(accum) > 80:
                            log.write(f"[dim #00d9ff]{accum}[/dim #00d9ff]")
                            accum = ""
                    if accum:
                        log.write(f"[dim #00d9ff]{accum}[/dim #00d9ff]")

                llm_task = asyncio.create_task(
                    asyncio.to_thread(self.agent.llm.chat_stream, messages, on_token)
                )
                consumer_task = asyncio.create_task(consume_tokens())
                llm_output = await llm_task
                await consumer_task
                spinner.set_done(f"{len(llm_output)} chars, {token_count['n']} tokens")
            except Exception as e:
                spinner.set_done(f"Error: {e}")
                log.write(f"[#ff006e]✗ LLM error: {e}[/#ff006e]")
                break

            self.agent.conversation.append({"role": "assistant", "content": llm_output})
            parsed = parse_llm_output(llm_output)

            if isinstance(parsed, FinalAnswer):
                log.write(Panel(
                    RichMarkdown(parsed.content),
                    title="[bold #00ff9f]◢ OBLIVION ◣[/bold #00ff9f]",
                    border_style="#00ff9f",
                ))
                save_message(self.session_id, "assistant", parsed.content)
                break

            if isinstance(parsed, ToolCall):
                if parsed.thought:
                    thought = parsed.thought[:200] + "…" if len(parsed.thought) > 200 else parsed.thought
                    log.write(f"[#b537f2]◇[/#b537f2] [italic dim]{thought}[/italic dim]")

                if parsed.tool == "finish":
                    summary = parsed.args.get("summary", "Done.")
                    log.write(Panel(summary, title="[#00ff9f]◢ DONE[/#00ff9f]", border_style="#00ff9f"))
                    save_message(self.session_id, "assistant", summary)
                    break

                item = ActivityItem(parsed.tool, parsed.args, "running")
                await activity_scroll.mount(item)
                activity_scroll.scroll_end(animate=False)
                self.activity_items.append(item)
                self.current_status = f"▓ {parsed.tool}"
                self.update_status()

                result = await self._handle_tool(parsed.tool, parsed.args, item)
                item.set_done(result)

                self.agent.conversation.append({
                    "role": "user",
                    "content": f"OBSERVATION (result of {parsed.tool}):\n{result}\n\nContinue: next THOUGHT + ACTION, or FINAL_ANSWER.",
                })

                if parsed.tool in ("write_file", "edit_file", "create_dir"):
                    self._populate_tree()
                continue

            log.write("[#ff006e]✗ Could not parse output, retrying…[/#ff006e]")
            self.agent.conversation.append({
                "role": "user",
                "content": "Invalid format. Use THOUGHT: then ACTION: {json} or FINAL_ANSWER: text"
            })

        self.agent_busy = False
        self.iteration_count = 0
        self.current_status = "▓ READY"
        self.update_status()

    async def _handle_tool(self, tool_name: str, args: dict, item: ActivityItem) -> str:
        if tool_name == "write_file":
            path = args.get("path", "")
            content = args.get("content", "")
            p = Path(path)
            if p.exists():
                original = p.read_text(encoding="utf-8", errors="ignore")
                diff = make_diff(original, content, path)
                title, body = f"Write to {path}?", f"Modify {len(content)} bytes."
            else:
                diff = make_diff("", content, path)
                title, body = f"Create {path}?", f"New file: {len(content.splitlines())} lines."
            item.status = "pending"
            item.update_display()
            approved = await self.push_screen_wait(ApprovalModal(title, body, diff))
            return dispatch("write_file", args) if approved else "User denied write_file."

        if tool_name == "edit_file":
            path = args.get("path", "")
            old, new = args.get("old_text", ""), args.get("new_text", "")
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
                f"Replace {len(old.splitlines())} line(s) with {len(new.splitlines())}.",
                diff,
            ))
            return dispatch("edit_file", args) if approved else "User denied edit_file."

        if tool_name == "run_bash":
            command = args.get("command", "")
            item.status = "pending"
            item.update_display()
            approved = await self.push_screen_wait(ApprovalModal(
                "Run shell command?", f"$ {command}", "",
            ))
            return dispatch("run_bash", args) if approved else "User denied run_bash."

        return await asyncio.to_thread(dispatch, tool_name, args)

    def action_reset(self) -> None:
        self.agent.reset()
        self._clear_activity()
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        log.write("[#00ff9f]◢ Neural link reset.[/#00ff9f]")
        self.update_status()

    def action_new_session(self) -> None:
        self.session_id = create_session()
        self.agent.reset()
        self._clear_activity()
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        log.write(f"[#00ff9f]◢ New session: {self.session_id}[/#00ff9f]")
        self.update_status()

    def action_clear_chat(self) -> None:
        self.query_one("#chat-log", RichLog).clear()
        self._clear_activity()

    def action_show_help(self) -> None:
        self.run_worker(self.handle_slash("/help"), exclusive=False)

    def _clear_activity(self):
        for item in list(self.activity_items):
            try:
                item.remove()
            except Exception:
                pass
        self.activity_items.clear()


def main():
    app = OblivionApp()
    app.run()


if __name__ == "__main__":
    main()
