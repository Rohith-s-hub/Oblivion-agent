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
from agent.runtime import AgentRuntime, RuntimeCallbacks
from tools.registry import dispatch
from tools.diff import make_diff
from db.store import init_db, create_session, save_message, load_session, list_sessions
from agent.watcher import FileWatcher
from agent.models import MODELS, get_current_model_info, check_api_key, list_models_table
try:
    from agent.voice import (
        VoiceRecorder, transcribe, get_whisper_model, list_input_devices,
        VOICE_AVAILABLE,
    )
except ImportError:
    VOICE_AVAILABLE = False
    VoiceRecorder = None
    transcribe = lambda *a, **kw: ""
    get_whisper_model = lambda *a, **kw: None
    list_input_devices = lambda: []
from agent import friday
import threading
import numpy as np


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
ACCENT_COLORS = ["#7b8cde", "#9aa0b8", "#3e4560", "#febc2e"]


SLASH_COMMANDS = [
    ("/help",         "Show all slash commands"),
    ("/continue",     "Resume task from where you left off"),
    ("/models",       "Show all available models & status"),
    ("/addmodel",     "Add a new LLM model & API key: /addmodel <name> <id> [key]"),
    ("/model",        "List or switch LLM model"),
    ("/model reset",  "Clear exhausted-models cache (retry all)"),
    ("/clear",        "Clear chat history"),
    ("/index",        "Re-index changed files (incremental)"),
    ("/index status", "Show current chunk count"),
    ("/watch",        "Toggle file watcher (auto-reindex)"),
    ("/watch status", "Show watcher status"),
    ("/voice",        "Start voice recording (same as F2)"),
    ("/voice record", "Same as F2 — start recording"),
    ("/voice status", "Show voice settings"),
    ("/voice devices", "List audio input devices"),
    ("/voice model medium", "Switch Whisper model"),
    ("/meera",                  "M.E.E.R.A. status"),
    ("/meera on",               "Enable voice replies (MEERA mode)"),
    ("/meera off",              "Disable voice replies"),
    ("/meera stop",             "Stop current speech"),
    ("/meera test",             "Test current voice"),
    ("/meera persona aria",     "Aria - warm professional (default)"),
    ("/meera persona jenny",    "Jenny - friendly conversational"),
    ("/meera persona sonia",    "Sonia - British refined"),
    ("/meera persona natasha",  "Natasha - Australian energetic"),
    ("/meera persona emma",     "Emma - warm storyteller"),
    ("/meera persona michelle", "Michelle - mature professional"),
    ("/meera name boss",        "Change how Meera addresses you"),
    ("/meera rate +20%",        "Speech rate (+/- percent)"),
    ("/mcp",                    "MCP Web Connector & status"),
    ("/mcp share",              "⚡ Instant Claude.ai / Web Connector (HTTPS)"),
    ("/mcp on",                 "Start local MCP SSE server"),
    ("/mcp off",                "Stop MCP server and web tunnel"),
    ("/mcp tier standard",       "Set tier: standard (safe + file edits)"),
    ("/mcp tier full",           "Set tier: full (bash + git + tests)"),
    ("/mcp tier safe",           "Set tier: safe (read-only mode)"),
    ("/workspace",    "Show / set workspace directory"),
    ("/newproject <name>",      "Create ~/Projects/<name>/ and switch into it"),
    ("/openproject <name>",     "Switch workspace to an existing project"),
    ("/projects",               "List all projects in ~/Projects/"),
    ("/model",        "List or switch LLM model"),
    ("/model reset",  "Clear exhausted-models cache (retry all)"),
]

# Auto-append every model from the registry so the dropdown always shows ALL options.
_REG = MODELS
try:
    _model_entries = []
    for _name, _info in _REG.items():
        _desc = _info.get("description", "")[:50]
        _cost = _info.get("cost", "")
        _label = f"Switch to {_name} ({_cost})"[:55]
        _model_entries.append((f"/model {_name}", _label))
    SLASH_COMMANDS_MODEL_APPEND = _model_entries
except Exception:
    SLASH_COMMANDS_MODEL_APPEND = []

# Re-extend the main list with the dynamic model entries
SLASH_COMMANDS = [
    ("/help",         "Show all slash commands"),
    ("/continue",     "Resume task from where you left off"),
    ("/models",       "Show all available models & status"),
    ("/clear",        "Clear chat history"),
    ("/index",        "Re-index changed files (incremental)"),
    ("/index status", "Show current chunk count"),
    ("/watch",        "Toggle file watcher (auto-reindex)"),
    ("/watch status", "Show watcher status"),
    ("/voice",        "Start voice recording (same as F2)"),
    ("/voice record", "Same as F2 — start recording"),
    ("/voice status", "Show voice settings"),
    ("/voice devices", "List audio input devices"),
    ("/voice model medium", "Switch Whisper model"),
    ("/meera",                  "M.E.E.R.A. status"),
    ("/meera on",               "Enable voice replies (MEERA mode)"),
    ("/meera off",              "Disable voice replies"),
    ("/meera stop",             "Stop current speech"),
    ("/meera test",             "Test current voice"),
    ("/meera persona aria",     "Aria - warm professional (default)"),
    ("/meera persona jenny",    "Jenny - friendly conversational"),
    ("/meera persona sonia",    "Sonia - British refined"),
    ("/meera persona natasha",  "Natasha - Australian energetic"),
    ("/meera persona emma",     "Emma - warm storyteller"),
    ("/meera persona michelle", "Michelle - mature professional"),
    ("/meera name boss",        "Change how Meera addresses you"),
    ("/meera rate +20%",        "Speech rate (+/- percent)"),
    ("/mcp",                    "MCP Web Connector & status"),
    ("/mcp share",              "⚡ Instant Claude.ai / Web Connector (HTTPS)"),
    ("/mcp on",                 "Start local MCP SSE server"),
    ("/mcp off",                "Stop MCP server and web tunnel"),
    ("/mcp tier standard",       "Set tier: standard (safe + file edits)"),
    ("/mcp tier full",           "Set tier: full (bash + git + tests)"),
    ("/mcp tier safe",           "Set tier: safe (read-only mode)"),
    ("/workspace",    "Show / set workspace directory"),
    ("/newproject <name>",      "Create ~/Projects/<name>/ and switch into it"),
    ("/openproject <name>",     "Switch workspace to an existing project"),
    ("/projects",               "List all projects in ~/Projects/"),
    ("/model",        "List or switch LLM model"),
    ("/model reset",  "Clear exhausted-models cache (retry all)"),
    ("/save",         "Save current session"),
    ("/load",         "Resume a saved session"),
    ("/sessions",     "List all saved sessions"),
    ("/stats",        "Show conversation stats"),
    ("/trust",        "Show/manage trust groups (edit, all-mutate, workspace, server)"),
    ("/trust edit",   "Pre-approve write_file, edit_file, insert_after this session"),
    ("/trust reset",  "Clear trust list (all mutations prompt again)"),
    ("/auto",         "Toggle AUTO mode (mutations auto-approve, destructive still prompt)"),
    ("/auto --persist", "AUTO mode saved to config.env across restarts"),
    ("/vision <path> [prompt]", "Analyze image/screenshot mockup & generate code"),
    ("/wake",              "Wake word status (Hey Meera detection)"),
    ("/wake on",           "Enable wake word listener"),
    ("/wake off",          "Disable wake word listener"),
    ("/wake status",       "Show wake word status"),
    ("/wake sensitivity 0.5", "Adjust wake word sensitivity (0.0-1.0)"),
    ("/rates",             "Show LLM rate limits + fallback chain status"),
    ("/switch",       "Switch to 8085 Microprocessor Simulator"),
    ("/quit",         "Exit Oblivion"),
    ("/update",       "Check PyPI for newer Oblivion version"),
    ("/update install", "Upgrade to latest Oblivion via pip"),
    ("/update changelog", "Show what's new in latest release"),
]

# ── Auto-extend SLASH_COMMANDS with every model from the registry ──
# This way new models added to agent/models.py automatically appear in autocomplete
try:
    for _mname, _minfo in _MODEL_REGISTRY.items():
        _cost = _minfo.get("cost", "")
        _provider = _minfo.get("provider", "")
        _label = f"Switch to {_mname} [{_provider}] {_cost}"[:60]
        SLASH_COMMANDS.append((f"/model {_mname}", _label))
except Exception:
    pass


# ── Approval Modal ────────────────────────────────────────────────────────────
class ApprovalModal(ModalScreen[bool]):
    """Cyberpunk-themed approval modal for destructive ops."""

    BINDINGS = [
        ("y", "approve", "Approve"),
        ("enter", "approve", "Approve"),
        ("n", "deny", "Deny"),
        ("escape", "deny", "Cancel"),
    ]

    def __init__(self, title: str, body: str, diff_text: str = ""):
        super().__init__()
        self.title_text = title
        self.body_text = body
        self.diff_text = diff_text

    def compose(self) -> ComposeResult:
        op_type = "OPERATION"
        target = ""
        tt = self.title_text.lower()
        if "create" in tt:
            op_type = "CREATE FILE"
        elif "write" in tt:
            op_type = "WRITE FILE"
        elif "edit" in tt:
            op_type = "EDIT FILE"
        elif "run shell" in tt or "command" in tt:
            op_type = "RUN COMMAND"

        import re as _re
        m = _re.search(r"[?:]?\s*([\w/.\-]+\.\w+|\$.*)", self.title_text)
        if m:
            target = m.group(1).strip()
        else:
            target = self.title_text.rstrip("?").strip()

        info_text = (
            "[#7b8cde]\u25c6 TYPE   [/#7b8cde] [bold white]" + op_type + "[/bold white]\n"
            "[#7b8cde]\u25c6 TARGET [/#7b8cde] [bold #9aa0b8]" + target + "[/bold #9aa0b8]\n"
            "[#7b8cde]\u25c6 DETAIL [/#7b8cde] [dim white]" + self.body_text + "[/dim white]"
        )

        with Container(id="modal-container"):
            yield Label(
                "[bold #7b8cde]CONFIRM ACTION[/bold #7b8cde]",
                id="modal-header",
            )
            yield Static(info_text, id="modal-info")

            if self.diff_text:
                yield Label(
                    "[bold #3e4560]\u25e2 DIFF PREVIEW \u25e3[/bold #3e4560]",
                    id="modal-diff-label",
                )
                yield Static(self._format_diff(), id="modal-diff")

            yield Static(
                "[bold #7b8cde][Y][/bold #7b8cde] [white]or[/white] "
                "[bold #7b8cde][ENTER][/bold #7b8cde]  [dim]approve[/dim]"
                "        "
                "[bold #febc2e][N][/bold #febc2e] [white]or[/white] "
                "[bold #febc2e][ESC][/bold #febc2e]  [dim]deny[/dim]",
                id="modal-hints",
            )

            with Horizontal(id="modal-buttons"):
                yield Button("\u25cb  approve", id="btn-approve")
                yield Button("\u25cb  deny", id="btn-deny")

    def _format_diff(self) -> Text:
        text = Text()
        lines = self.diff_text.splitlines()
        max_lines = 25
        truncated = False
        if len(lines) > max_lines:
            extra = len(lines) - max_lines
            lines = lines[:max_lines]
            truncated_msg = "... (" + str(extra) + " more lines)"
        for line in lines:
            if line.startswith("+++") or line.startswith("---"):
                text.append(line + "\n", style="bold white on grey15")
            elif line.startswith("@@"):
                text.append(line + "\n", style="bold cyan on grey11")
            elif line.startswith("+"):
                text.append(line + "\n", style="bold green")
            elif line.startswith("-"):
                text.append(line + "\n", style="bold red")
            else:
                text.append(line + "\n", style="dim white")
        return text

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-approve")

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:
        self.dismiss(False)





# ── Session Picker Modal (Ctrl+P) ────────────────────────────────────────────
class SessionPicker(ModalScreen):
    """Floating overlay listing past sessions. Click or Enter to load."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("ctrl+g", "dismiss", "Close"),
    ]

    def __init__(self):
        super().__init__()
        self.sessions = []

    def compose(self) -> ComposeResult:
        from db.store import list_sessions_enriched
        self.sessions = list_sessions_enriched(limit=100)

        with Container(id="session-picker-container"):
            yield Label(
                f"[bold #7b8cde]◆ SESSION HISTORY[/bold #7b8cde]  "
                f"[dim]({len(self.sessions)} total)[/dim]",
                id="session-picker-header",
            )

            opts = OptionList(id="session-picker-list")
            for s in self.sessions:
                # Format: #ID  preview                   N msgs · date
                date_short = (s["updated_at"] or "")[:16]
                label = (
                    f"[bold #febc2e]#{s['id']:>4}[/bold #febc2e]  "
                    f"[white]{s['preview']:<60}[/white]  "
                    f"[dim #9aa0b8]{s['messages']:>3} msg · {date_short}[/dim #9aa0b8]"
                )
                opts.add_option(Option(label, id=str(s["id"])))
            yield opts

            yield Static(
                "[dim]↑↓ navigate · Enter to load · Esc to close[/dim]",
                id="session-picker-hint",
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """User picked a session — return its ID to the caller."""
        try:
            session_id = int(event.option.id)
            self.dismiss(session_id)
        except (ValueError, TypeError):
            self.dismiss(None)

    def action_dismiss(self) -> None:
        self.dismiss(None)


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
        icons  = {"running": self._spinner_frame(), "done": "✓", "error": "✕", "pending": "◌"}
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
    theme = "ansi-dark"
    CSS = """
    
    Tree {
        background: #09090b;
        color: #f8fafc;
    }
    Tree:focus {
        background: #09090b;
    }
    Tree > .tree--cursor {
        background: #181820;
        color: #22d3ee;
        text-style: bold;
    }
    Tree > .tree--guides {
        color: #27272a;
    }

    Screen {
        background: #09090b;
        color: #f8fafc;
    }
    
    Header {
        background: #09090b;
        color: #a78bfa;
        dock: top;
        height: 1;
    }
    
    Footer {
        background: #121218;
        color: #71717a;
        dock: bottom;
        height: 1;
    }

    #main-container { 
        height: 100%; 
        background: #09090b;
    }

    #chat-panel {
        width: 65%;
        border: round #27272a;
        padding: 0 1;
        background: #09090b;
    }
    #chat-panel:focus-within {
        border: round #8b5cf6;
    }

    #side-panel { width: 35%; }

    #activity-panel {
        height: 55%;
        border: round #27272a;
        padding: 0 1;
        background: #09090b;
    }
    #activity-panel:focus-within {
        border: round #22d3ee;
    }

    #files-panel {
        height: 45%;
        border: round #27272a;
        padding: 0 1;
        background: #09090b;
    }
    #files-panel:focus-within {
        border: round #8b5cf6;
    }

    #input-box {
        dock: bottom;
        border: round #27272a;
        background: #121218;
        color: #f8fafc;
        margin-top: 0;
    }
    #input-box:focus {
        border: round #8b5cf6;
        color: #ffffff;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: #09090b;
        color: #f8fafc;
    }

    #slash-suggestions {
        layer: overlay;
        dock: bottom;
        margin-bottom: 3;
        margin-left: 2;
        width: 60;
        max-height: 10;
        background: #121218;
        border: round #8b5cf6;
        display: none;
    }
    #slash-suggestions.visible {
        display: block;
    }
    #slash-suggestions > .option-list--option-highlighted {
        background: #8b5cf6;
        color: #ffffff;
        text-style: bold;
    }

    /* Modals & Dialogs */
    ApprovalModal {
        align: center middle;
        background: rgba(9, 9, 11, 0.85); /* Dark dimming overlay */
    }
    #modal-container {
        width: 76;
        height: auto;
        background: #121218;
        border: round #8b5cf6;
        padding: 2 4;
        margin: 0;
        align: center middle;
    }
    #modal-header {
        text-align: center;
        text-style: bold;
        color: #67e8f9;
        margin-bottom: 1;
        width: 100%;
    }
    #modal-info {
        width: 100%;
        margin-bottom: 1;
        background: #09090b;
        padding: 1 2;
        border: round #27272a;
    }
    #modal-diff-label {
        color: #a78bfa;
        text-style: bold;
        margin-top: 1;
        width: 100%;
    }
    #modal-diff {
        width: 100%;
        max-height: 12;
        background: #09090b;
        padding: 1 2;
        border: round #27272a;
        overflow-y: scroll;
        margin-bottom: 1;
    }
    #modal-hints {
        text-align: center;
        color: #71717a;
        margin-bottom: 1;
        width: 100%;
    }
    #modal-buttons {
        align: center middle;
        height: 3;
        width: 100%;
    }
    #btn-approve {
        background: #10b981;
        color: #09090b;
        text-style: bold;
        border: none;
        margin-right: 4;
        min-width: 16;
    }
    #btn-approve:hover {
        background: #34d399;
    }
    #btn-deny {
        background: #ef4444;
        color: #ffffff;
        text-style: bold;
        border: none;
        min-width: 16;
    }
    #btn-deny:hover {
        background: #f87171;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+r", "reset", "Reset"),
        Binding("ctrl+n", "new_session", "New"),
        Binding("ctrl+l", "clear_chat", "Clear"),
        Binding("ctrl+h", "show_help", "Help"),
        Binding("ctrl+t", "toggle_voice", "Talk"),
        Binding("ctrl+g", "open_history", "History"),
    ]

    TITLE = "◢◤ OBLIVION ◥◣"
    # Dynamically updated in on_mount / after model switches
    SUB_TITLE = "▓ neural code agent ▓"

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
        self.watcher: FileWatcher | None = None
        self.auto_watch_enabled = True
        self._watcher_events: list = []
        # Voice state
        self.voice_recorder: VoiceRecorder | None = None
        self.voice_recording = False
        self.voice_stop_event: threading.Event | None = None
        self.voice_audio_level = 0.0
        self.voice_status = "idle"
        # ── M.E.E.R.A. waveform state (Pattern G) ──
        self.meera_speaking = False
        self.meera_wave_phase = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="main-container"):
            with Vertical(id="chat-panel"):
                yield Label("[bold #a78bfa]◆ CHAT[/bold #a78bfa]")
                yield RichLog(id="chat-log", wrap=True, highlight=True, markup=True)

            with Vertical(id="side-panel"):
                with Vertical(id="activity-panel"):
                    yield Label("[bold #7b8cde]◢ AGENT LOG ◣[/bold #7b8cde]")
                    yield VerticalScroll(id="activity-scroll")

                with Vertical(id="workspace-panel"):
                    yield Label("[bold #a78bfa]📂 FILES[/bold #a78bfa]")
                    yield Tree("◆ root/", id="workspace-tree")

        yield Input(placeholder="❯ Enter command, /help, or Ctrl+T to talk…", id="input-box")
        yield OptionList(id="slash-suggestions")
        yield Static(self._status_text(), id="status-bar")
        yield Footer()

    def _status_text(self) -> str:
        msgs = len(self.agent.conversation) if self.agent else 0
        workspace = os.path.basename(os.getenv("WORKSPACE_DIR", ".")) or "root"

        # Model display
        default_model = os.getenv("DEFAULT_MODEL", "none").split("/")[-1][:18]
        model_display = default_model
        try:
            last_used = getattr(self.agent.llm, "last_used_model", None)
            if last_used:
                last_short = last_used.split("/")[-1][:18]
                if last_short != default_model:
                    model_display = f"{default_model}→{last_short}"
        except Exception:
            pass

        # Token stats formatted in K
        try:
            tokens = self.agent.llm.get_token_stats()
            t_total = tokens["total"]
            tok_str = f"{t_total/1000:.1f}k" if t_total >= 1000 else str(t_total)
        except Exception:
            tok_str = "0"

        # Rate-limited indicator badge
        exhausted_badge = ""
        try:
            exh = self.agent.llm.get_exhausted_models()
            if exh:
                exhausted_badge = f" [bold #09090b on #f59e0b] ⚠ {len(exh)} RATE-LIMITED [/]"
        except Exception:
            pass

        # AUTO mode indicator
        auto_badge = ""
        try:
            st = self._runtime_state()
            if st.get("auto_mode"):
                auto_badge = "[bold #09090b on #f59e0b] AUTO [/] "
        except Exception:
            pass

        # Lualine Powerline Status Segments
        if self.agent_busy:
            state_seg = f"{auto_badge}[bold #09090b on #f59e0b] 🧠 THINKING [/]"
        else:
            state_seg = f"{auto_badge}[bold #09090b on #10b981] ⚡ READY [/]"

        model_seg = f"[bold #e0e7ff on #27272a] 🤖 {model_display} [/]"
        ws_seg = f"[bold #67e8f9 on #181820] 📂 {workspace} [/]"
        stats_seg = f"[#a1a1aa on #09090b] msg:{msgs} │ tok:{tok_str} │ step:{self.iteration_count} [/]"
        hint_seg = f"[dim #71717a on #09090b] ^Q quit │ ^H help [/]"

        return f"{state_seg}{model_seg}{ws_seg}{stats_seg}{exhausted_badge} {hint_seg}"


    def _render_waveform(self) -> str:
        """Pattern G: cyan waveform for M.E.E.R.A. — flat when idle, pulsing when speaking."""
        width = 16
        if not self.meera_speaking:
            return "  [#9aa0b8]M.E.E.R.A. " + ("▁" * width) + "[/#9aa0b8]"
        bars = "▁▂▃▄▅▆▇█▇▆▅▄▃▂"
        phase = self.meera_wave_phase
        out = []
        for i in range(width):
            # Two overlaid sine-ish waves for organic pulse
            v = ((i * 3 + phase) % len(bars))
            w = ((i + phase * 2) % len(bars))
            out.append(bars[(v + w) % len(bars)])
        return "  [bold #9aa0b8]M.E.E.R.A. " + "".join(out) + "[/bold #9aa0b8]"

    def _meera_done(self):
        """Called from speak thread to stop the waveform animation."""
        try:
            self.meera_speaking = False
            self.update_status()
        except Exception:
            pass

    def _meera_tick(self):
        """Pattern G: advance waveform phase + repaint when speaking."""
        if self.meera_speaking:
            self.meera_wave_phase = (self.meera_wave_phase + 1) % 10000
            self.update_status()

    def _check_workspace_change(self):
        """Poll for workspace changes and refresh tree + status if changed."""
        try:
            current = os.environ.get("WORKSPACE_DIR", "")
            if current != getattr(self, "_last_known_workspace", ""):
                self._last_known_workspace = current
                self._populate_tree()
                self.update_status()
        except Exception:
            pass

    def update_status(self):
        try:
            self.query_one("#status-bar", Static).update(self._status_text())
        except Exception:
            pass
        # Also update the window title bar with current model
        try:
            self._update_sub_title()
        except Exception:
            pass

    def _update_sub_title(self):
        """Update the window title bar to show live current model."""
        try:
            import os as _os
            model_id = _os.environ.get("DEFAULT_MODEL", "unknown")
            # Take last part after / for readability
            short = model_id.split("/")[-1][:30]
            self.sub_title = f"▓ {short} ▓ neural code agent ▓"
        except Exception:
            pass

    def _speak_async(self, text: str):
        """Play TTS in a background thread so it doesn't block the UI or Agent."""
        try:
            from agent import friday
            if friday.is_enabled():
                import threading
                threading.Thread(target=friday.speak, args=(text,), daemon=True).start()
        except Exception:
            pass

    async def on_mount(self) -> None:
        # NUCLEAR FIX: restore workspace HERE - after all imports/init done
        try:
            from agent.paths import load_last_workspace
            _last_ws = load_last_workspace()
            if _last_ws:
                import os as _osm
                _osm.environ["WORKSPACE_DIR"] = _last_ws
        except Exception:
            pass

        init_db()
        # Clean up sessions from previous launches that had 0 messages
        try:
            from db.store import cleanup_empty_sessions
            cleanup_empty_sessions()
        except Exception:
            pass
        self.session_id = create_session()
        self.update_status()
        self._populate_tree()

        # Wire LLM fallback notifications into the chat log
        from agent.llm import LLMClient
        def _on_fallback(msg: str):
            """Fallback retries go to Agent Log panel, NOT chat.
            Users don't need to see every retry attempt."""
            try:
                scroll = self.query_one("#activity-scroll", VerticalScroll)
                dim_msg = Static(f"[dim #3e4560]↻ {msg}[/dim #3e4560]")
                self.call_from_thread(self._mount_watcher_item, scroll, dim_msg)
            except Exception:
                pass
        LLMClient.on_fallback_notify = _on_fallback

        # Drive animations - 100ms tick rate (10fps)
        self.set_interval(0.1, self._animate_tick)
        # M.E.E.R.A. waveform tick (Pattern G)
        self.set_interval(0.1, self._meera_tick)
        # Auto-refresh tree if workspace changed externally (e.g. by agent)
        self._last_known_workspace = os.environ.get("WORKSPACE_DIR", "")
        self.set_interval(2.0, self._check_workspace_change)

        # Wire TTS completion callback for hands-free auto-listening on questions
        try:
            from agent import friday
            def _handle_speech_done(spoken_text: str):
                # If Meera asked a question and voice/wake is active, auto-trigger recording!
                if spoken_text and "?" in spoken_text:
                    def _auto_record():
                        if not self.voice_recording and not self.agent_busy:
                            self.run_worker(self._start_voice_recording(), exclusive=False)
                    self.call_from_thread(_auto_record)

            friday.set_on_speech_done_callback(_handle_speech_done)
        except Exception:
            pass

        # Start file watcher
        if self.auto_watch_enabled:
            self._start_watcher()

        # Background Whisper warm-up (non-blocking)
        def _bg_warmup_whisper():
            try:
                from agent.voice import get_whisper_model, clear_model
                from pathlib import Path as _P
                if (_P.home() / ".oblivion" / ".whisper_force_reload").exists():
                    clear_model()
                    try:
                        (_P.home() / ".oblivion" / ".whisper_force_reload").unlink()
                    except Exception:
                        pass
                get_whisper_model()  # loads VOICE_MODEL=tiny.en from env
            except Exception:
                pass
        import threading
        threading.Thread(target=_bg_warmup_whisper, daemon=True).start()

        # Start wake word detector if enabled in config
        try:
            import os as _osw
            if _osw.environ.get("WAKE_WORD_ENABLED", "false").lower() == "true":
                self._start_wake_word()
        except Exception:
            pass

        # Process watcher events every 500ms
        self.set_interval(0.5, self._drain_watcher_events)

        log = self.query_one("#chat-log", RichLog)

        # Typewriter intro - banner appears line by line with delays
        self.run_worker(self._typewriter_intro(log), exclusive=False)

        self.query_one("#input-box", Input).focus()

    async def _typewriter_intro(self, log) -> None:
        """Show Oblivion AI boot + logo with typewriter effect."""
        from ui.branding.logo import render_logo, render_boot_sequence

        # Boot messages
        for msg, delay in render_boot_sequence():
            log.write(msg)
            await asyncio.sleep(min(float(delay) * 0.35, 0.12))

        log.write("")

        # Logo - render_logo() returns a list of pre-styled lines
        # OR a single string (both handled)
        logo_out = render_logo()
        if isinstance(logo_out, list):
            lines_to_write = logo_out
        else:
            lines_to_write = logo_out.split("\n")

        for line in lines_to_write:
            log.write(line)
            await asyncio.sleep(0.01)

        log.write("")
        await asyncio.sleep(0.08)

        # M.E.E.R.A. greeting — short + cached + never blocks UI
        if friday.is_enabled():
            try:
                import threading as _tg
                def _boot_voice():
                    try:
                        # Warm common phrases once (instant later)
                        if hasattr(friday, "warmup_tts"):
                            friday.warmup_tts()
                        greeting = f"Good to see you, {friday.get_name()}. M.E.E.R.A. online."
                        friday.speak(greeting, blocking=False, auto_summarize=False)
                    except Exception:
                        pass
                _tg.Thread(target=_boot_voice, name="meera-boot-voice", daemon=True).start()
            except Exception:
                pass

        # ── Personalized welcome card (Claude Code style) ─────────────
        _user_name = os.getenv("FRIDAY_NAME", "boss")
        _model_id = os.getenv("DEFAULT_MODEL", "unknown")
        _model_short = _model_id.split("/")[-1][:30]
        # Re-read WORKSPACE_DIR fresh (in case restore just happened)
        _workspace = os.getenv("WORKSPACE_DIR", ".")
        _workspace_display = _workspace.replace(os.path.expanduser("~"), "~")


        # Get recent sessions for "Recent activity" panel
        recent_sessions_text = ""
        try:
            from db.store import get_recent_sessions
            recent = get_recent_sessions(limit=4)
            if recent:
                _lines = []
                for sess in recent:
                    ts = sess.get("ago", "?")
                    preview = sess.get("preview", "")[:35]
                    _lines.append(f"[#a78bfa]{ts:>7}[/#a78bfa]  [#e0e7ff]{preview}[/#e0e7ff]")
                recent_sessions_text = "\n".join(_lines)
            else:
                recent_sessions_text = "[dim #7c8399]No previous sessions[/dim #7c8399]"
        except Exception:
            recent_sessions_text = "[dim #7c8399]Session history unavailable[/dim #7c8399]"

        # Welcome panel with M.E.E.R.A. Assistant Identity
        wake_status = "Active ('Hey Meera')" if os.getenv("WAKE_WORD_ENABLED", "false").lower() == "true" else "Standby (press Ctrl+T or /wake on)"

        welcome_content = (
            f"[#e0e7ff]Welcome back, [bold #67e8f9]{_user_name}[/bold #67e8f9][/#e0e7ff]\n\n"
            f"[#a78bfa]AI Persona:[/#a78bfa]  [bold #67e8f9]M.E.E.R.A.[/bold #67e8f9] [dim](Engineering & Reasoning Assistant)[/dim]\n"
            f"[#a78bfa]LLM Model:[/#a78bfa]   [#e0e7ff]{_model_short}[/#e0e7ff]\n"
            f"[#a78bfa]Workspace:[/#a78bfa]   [#67e8f9]{_workspace_display}[/#67e8f9]\n"
            f"[#a78bfa]Voice Mode:[/#a78bfa]  [#e0e7ff]{wake_status}[/#e0e7ff]"
        )

        log.write(Panel(
            welcome_content,
            title="[bold #8b5cf6]◢ M.E.E.R.A. ONLINE ◣[/bold #8b5cf6]",
            border_style="#8b5cf6",
            padding=(1, 2),
        ))

        # Recent activity panel
        if recent_sessions_text:
            log.write(Panel(
                recent_sessions_text + "\n\n[dim #7c8399]... Ctrl+G for full history[/dim #7c8399]",
                title="[bold #22d3ee]◢ RECENT ACTIVITY ◣[/bold #22d3ee]",
                border_style="#22d3ee",
                padding=(0, 2),
            ))

        # Quick tips panel
        log.write(Panel(
            "[#a78bfa]/[/#a78bfa]           [dim]show slash commands[/dim]\n"
            "[#a78bfa]Ctrl+T[/#a78bfa]      [dim]talk to Meera (voice)[/dim]\n"
            "[#a78bfa]Ctrl+G[/#a78bfa]      [dim]session history[/dim]\n"
            "[#a78bfa]Ctrl+Q[/#a78bfa]      [dim]quit[/dim]",
            title="[bold #67e8f9]◢ QUICK START ◣[/bold #67e8f9]",
            border_style="#67e8f9",
            padding=(0, 2),
        ))

    def _animate_tick(self) -> None:
        """Called every 100ms to drive animations."""
        if self.agent_busy:
            self.update_status()
        for item in self.activity_items:
            if item.status == "running" or item.status == "pending":
                item.update_display()

    def _start_watcher(self):
        """Start file watcher for current workspace."""
        if self.watcher is not None:
            self.watcher.stop()
        self.watcher = FileWatcher(callback=self._on_file_event)
        self.watcher.start()

    def _stop_watcher(self):
        if self.watcher is not None:
            self.watcher.stop()
            self.watcher = None

    def _on_file_event(self, evt: dict):
        """Callback from file watcher (runs in background thread).
        We queue the event; the UI thread drains it via _drain_watcher_events."""
        self._watcher_events.append(evt)

    def _drain_watcher_events(self):
        """Show file change events in the activity panel."""
        if not self._watcher_events:
            return

        try:
            scroll = self.query_one("#activity-scroll", VerticalScroll)
        except Exception:
            return

        while self._watcher_events:
            evt = self._watcher_events.pop(0)
            etype = evt.get("type", "?")
            fname = evt.get("file", "?")
            status = evt.get("status", "?")

            # Only show interesting events
            if status in ("unchanged", "skipped"):
                continue

            icons = {"modified": "✎", "created": "✚", "deleted": "✗", "error": "⚠"}
            colors = {"modified": "#9aa0b8", "created": "#7b8cde", "deleted": "#febc2e", "error": "#febc2e"}
            icon = icons.get(etype, "·")
            color = colors.get(etype, "white")

            short = Path(fname).name if fname else "?"
            detail = ""
            if evt.get("chunks_added"):
                detail = f" [dim](+{evt['chunks_added']} chunks)[/dim]"
            elif evt.get("deleted"):
                detail = f" [dim](-{evt['deleted']} chunks)[/dim]"
            if evt.get("error"):
                detail = f" [red]{evt['error'][:40]}[/red]"

            item = Static(f"[{color}]{icon}[/{color}] [dim]auto-index:[/dim] [bold]{short}[/bold]{detail}")
            try:
                self.run_worker(self._mount_watcher_item(scroll, item), exclusive=False)
            except Exception:
                pass

    async def _mount_watcher_item(self, scroll, item):
        await scroll.mount(item)
        scroll.scroll_end(animate=False)

    def _trigger_bg_reindex(self, workspace_path):
        """Phase 2B.3: fire-and-forget background reindex after workspace switch.
        Shows a one-line progress note in the chat log when done.
        Skips if a reindex is already in progress to avoid thread storms.
        """
        if getattr(self, "_oblivion_bg_reindex", False):
            return
        self._oblivion_bg_reindex = True

        log = None
        try:
            log = self.query_one("#chat-log", RichLog)
        except Exception:
            pass

        def worker():
            try:
                if log is not None:
                    self.call_from_thread(
                        log.write,
                        "[#9aa0b8]↻ Background reindex started…[/#9aa0b8]",
                    )
                from agent.rag import index_codebase
                from pathlib import Path as _P
                stats = index_codebase(root=_P(str(workspace_path)), force=False, verbose=False)
                if log is not None:
                    self.call_from_thread(
                        log.write,
                        f"[#7b8cde]↻ Reindex done:[/#7b8cde] "
                        f"{stats.get('files_indexed',0)} files, "
                        f"+{stats.get('chunks_added',0)} chunks, "
                        f"+{stats.get('symbols_added',0)} symbols",
                    )
            except Exception as e:
                if log is not None:
                    self.call_from_thread(
                        log.write,
                        f"[#febc2e]Reindex failed: {e}[/#febc2e]",
                    )
            finally:
                self._oblivion_bg_reindex = False

        import threading as _th
        _th.Thread(target=worker, daemon=True).start()

    def _populate_tree(self):
        tree = self.query_one("#workspace-tree", Tree)
        tree.clear()
        root = tree.root

        # Update root label to show current workspace name
        try:
            import os as _os
            ws_path = Path(_os.environ.get("WORKSPACE_DIR", ".")).expanduser().resolve()
            ws_name = ws_path.name or str(ws_path)
            root.label = f"📂 {ws_name}/"
        except Exception:
            pass

        root.expand()

        workspace = Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()
        # GUARD: if saved workspace was deleted (e.g. /tmp cleanup), fall back gracefully
        if not workspace.exists() or not workspace.is_dir():
            # When user's saved workspace is missing, fall back to a safe default
            fallback = Path.home() / "Projects"
            fallback.mkdir(parents=True, exist_ok=True)
            try:
                log = self.query_one("#chat-log", RichLog)
                log.write(f"[#febc2e]⚠ Saved workspace missing: {workspace}[/#febc2e]")
                log.write(f"[#7b8cde]→ Falling back to: {fallback}[/#7b8cde]")
            except Exception:
                pass
            workspace = fallback.resolve()
            os.environ["WORKSPACE_DIR"] = str(workspace)
            try:
                self._update_env("WORKSPACE_DIR", str(workspace))
            except Exception:
                pass
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
                        node = parent_node.add(f"▾ {item.name}/")
                        add_path(node, item, depth + 1)
                    else:
                        parent_node.add_leaf(f"  📄 {item.name}")
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

        if command == "/mcp":
            from mcp_server.manager import get_mcp_status, start_server, start_tunnel, stop_all
            from rich.panel import Panel
            from rich.table import Table

            sub = arg.strip().lower()

            if sub in ("off", "stop"):
                stop_all()
                log.write(Panel("[#febc2e]⛔ Oblivion MCP Server and Web Connectors stopped.[/#febc2e]", title="[#7b8cde]MCP Manager[/#7b8cde]", border_style="#3e4560"))
                return True

            if sub.startswith("tier "):
                new_tier = sub.split(maxsplit=1)[1].strip()
                if new_tier not in ("safe", "standard", "full"):
                    log.write("[#febc2e]Usage: /mcp tier safe | standard | full[/#febc2e]")
                    return True
                stop_all()
                start_server(tier=new_tier)
                log.write(f"[#67e8f9]✓ Tool tier switched to {new_tier.upper()}[/#67e8f9]")

            if sub in ("share", "web", "connect"):
                log.write("[#7b8cde]⚡ Initializing Oblivion Web Connector & HTTPS Tunnel...[/#7b8cde]")
                st = await asyncio.to_thread(start_server)
                tun_url = await asyncio.to_thread(start_tunnel, st["port"])
            elif sub in ("on", "start"):
                st = await asyncio.to_thread(start_server)
            
            # Render Status Card
            st = get_mcp_status()
            
            t = Table.grid(padding=(0, 1))
            t.add_column(style="bold #7b8cde", width=18)
            t.add_column(style="#9aa0b8")

            srv_badge = "[bold #67e8f9]● ACTIVE (ONLINE)[/bold #67e8f9]" if st["running"] else "[dim]○ STOPPED[/dim]"
            t.add_row("Status:", srv_badge)
            t.add_row("Tool Tier:", f"[#febc2e]{st['tier'].upper()}[/#febc2e] ({st['tools_count']} tools available)")
            
            if st["running"]:
                t.add_row("Local SSE:", f"[#67e8f9]{st['local_sse_url']}[/#67e8f9]")
                t.add_row("Auth Token:", f"[dim]{st['token']}[/dim]")

            if st["tunnel_active"]:
                t.add_row("Web Connector:", f"[bold #67e8f9]{st['web_connector_url']}[/bold #67e8f9]")
                t.add_row("Claude.ai Setup:", "[dim]Add SSE Connector ➔ Paste Web Connector URL[/dim]")
            elif st["running"]:
                t.add_row("Web Tunnel:", "[dim]Not shared. Run [bold]/mcp share[/bold] to expose for claude.ai[/dim]")

            card_body = t
            title = "[bold #7b8cde]🌐 OBLIVION MCP & WEB CONNECTOR[/bold #7b8cde]"
            log.write(Panel(card_body, title=title, border_style="#7b8cde", subtitle="[dim]/mcp share | /mcp on | /mcp off | /mcp tier[/dim]"))
            return True

        if command in ("/addmodel", "/add-model"):
            from agent.models import MODELS, register_custom_model
            from agent.paths import save_config_key
            from rich.panel import Panel

            parts = arg.strip().split()
            if len(parts) < 2:
                help_lines = [
                    "[#febc2e]Usage: /addmodel <short_name> <litellm_model_id> [API_KEY_OR_ENV=KEY][/#febc2e]",
                    "",
                    "[dim]Examples:",
                    "  /addmodel openrouter-claude openrouter/anthropic/claude-3.5-sonnet sk-or-v1-xxxx",
                    "  /addmodel groq-llama groq/llama-3.3-70b-versatile gsk_xxxx",
                    "  /addmodel qwen-local ollama/qwen2.5-coder:7b[/dim]"
                ]
                log.write(Panel("\n".join(help_lines), title="[#7b8cde]/addmodel Help[/#7b8cde]", border_style="#3e4560"))
                return True

            short_name = parts[0].lower().strip()
            model_id = parts[1].strip()
            raw_key_arg = parts[2].strip() if len(parts) > 2 else ""

            env_key_name = ""
            api_key_val = ""

            if raw_key_arg:
                if "=" in raw_key_arg:
                    k_parts = raw_key_arg.split("=", 1)
                    env_key_name = k_parts[0].upper().strip()
                    api_key_val = k_parts[1].strip()
                else:
                    api_key_val = raw_key_arg
                    if api_key_val.startswith("gsk_"):
                        env_key_name = "GROQ_API_KEY"
                    elif api_key_val.startswith("sk-or-"):
                        env_key_name = "OPENROUTER_API_KEY"
                    elif api_key_val.startswith("AIza"):
                        env_key_name = "GEMINI_API_KEY"
                    elif "deepseek" in model_id:
                        env_key_name = "DEEPSEEK_API_KEY"
                    elif "anthropic" in model_id or api_key_val.startswith("sk-ant-"):
                        env_key_name = "ANTHROPIC_API_KEY"
                    else:
                        env_key_name = "OPENAI_API_KEY"

            if env_key_name and api_key_val:
                os.environ[env_key_name] = api_key_val
                try:
                    save_config_key(env_key_name, api_key_val)
                except Exception:
                    pass

            provider = model_id.split("/")[0] if "/" in model_id else "ollama"
            label = f"{short_name.capitalize()} ({provider})"
            register_custom_model(short_name, model_id, label=label, provider=provider)

            m_cmd = f"/model {short_name}"
            if not any(c[0] == m_cmd for c in SLASH_COMMANDS):
                SLASH_COMMANDS.append((m_cmd, f"Switch to {short_name} ({model_id})"))

            out_lines = [f"[#67e8f9]✓ Registered model: [bold]{short_name}[/bold] ({model_id})[/#67e8f9]"]
            if env_key_name:
                out_lines.append(f"[dim]Saved key to {env_key_name}[/dim]")
            out_lines.append(f"[#7b8cde]Switch now: [bold]/model {short_name}[/bold][/#7b8cde]")

            log.write(Panel("\n".join(out_lines), title="[#7b8cde]Model Added[/#7b8cde]", border_style="#67e8f9"))
            return True

        if command == "/continue":
            log.write("[#9aa0b8]Resuming task with fresh iteration budget...[/#9aa0b8]")
            self.run_worker(
                self._run_agent("Continue the previous task from where you left off. Use the conversation history to know what files are already done and what still needs to be built."),
                exclusive=True,
            )
            return True

        if command == "/auto":
            from tools.auto import auto_build, auto_test, auto_serve, auto_clean, auto_check
            log = self.query_one("#chat-log", RichLog)
            if not arg:
                log.write("[#7b8cde]Usage: /auto build | test | serve | clean | check[/#7b8cde]")
                return True
            sub = arg.strip().lower()
            log.write(f"[dim]Running /auto {sub}...[/dim]")
            try:
                if sub == "build": result = auto_build()
                elif sub == "test": result = auto_test()
                elif sub == "serve": result = auto_serve()
                elif sub == "clean": result = auto_clean()
                elif sub == "check": result = auto_check()
                else: result = "Unknown: /auto " + sub
                log.write(Panel(result, title="[#7b8cde]/auto " + sub + "[/#7b8cde]", border_style="#3e4560"))
            except Exception as e:
                log.write(f"Error: {e}")
            return True

        if command == "/vision":
            # Multimodal Vision Command: /vision <image_path> [optional prompt]
            parts = arg.strip().split(maxsplit=1)
            if not parts or not parts[0]:
                log.write("[#febc2e]Usage: /vision <image_path> [prompt][/#febc2e]")
                log.write("[dim]Example: /vision ~/mockup.png Recreate this UI in HTML/CSS[/dim]")
                return True

            img_path = parts[0].strip()
            user_prompt = parts[1].strip() if len(parts) > 1 else "Analyze this image in detail and recreate the UI/code structure shown."

            try:
                from agent.vision import encode_image_to_data_url, format_multimodal_message, is_vision_supported
            except ImportError as e:
                log.write(f"[#febc2e]⚠ Vision module error: {e}[/#febc2e]")
                return True

            current_model = os.getenv("DEFAULT_MODEL", "")
            if not is_vision_supported(current_model):
                log.write(f"[#febc2e]ℹ Model '{current_model}' may not support vision. Switching to gemma4:31b-cloud...[/#febc2e]")
                os.environ["DEFAULT_MODEL"] = "ollama/gemma4:31b-cloud"
                self.update_status()

            success, data_url_or_err, mime_type = encode_image_to_data_url(img_path)
            if not success:
                log.write(f"[#febc2e]✗ {data_url_or_err}[/#febc2e]")
                return True

            log.write(Panel(
                f"[bold #67e8f9]📷 VISION INPUT ATTACHED[/bold #67e8f9]\n"
                f"[dim]Image:[/#7c8399] {img_path} ({mime_type})\n"
                f"[dim]Prompt:[/#7c8399] {user_prompt}",
                title="[#8b5cf6]◢ MULTIMODAL ANALYSIS ◣[/#8b5cf6]",
                border_style="#8b5cf6",
            ))

            # Format multimodal message and append to conversation
            multi_msg = format_multimodal_message(user_prompt, data_url_or_err)
            self.agent.conversation.append(multi_msg)

            log.write("[dim #7b8cde]⯿ M.E.E.R.A is analyzing image...[/dim #7b8cde]")
            self.current_status = "▓ ANALYZING IMAGE"
            self.update_status()

            try:
                from db.store import save_message
                save_message(self.session_id, "user", f"[Vision: {img_path}] {user_prompt}")
            except Exception:
                pass

            self.agent_busy = True
            self.run_worker(self._run_agent(user_prompt), exclusive=True)
            return True

        if command == "/wake":
            # Manage wake word detection
            arg_lower = arg.lower().strip()
            try:
                from agent.wake_word import (
                    is_available, is_wake_word_enabled, get_status,
                    disable_wake_word,
                )
            except ImportError:
                log.write(
                    "[#febc2e]⚠ Wake word module unavailable.[/#febc2e] "
                    "Install: [bold]uv pip install openwakeword[/bold]"
                )
                return True

            if not is_available():
                log.write(
                    "[#febc2e]⚠ openwakeword not installed.[/#febc2e]\n"
                    "Install: [bold]uv pip install openwakeword[/bold]"
                )
                return True

            if arg_lower.startswith("model "):
                model_name = arg_lower.split(" ", 1)[1].strip()
                if model_name:
                    os.environ["WAKE_WORD_MODEL"] = model_name
                    try:
                        self._update_env("WAKE_WORD_MODEL", model_name)
                    except Exception:
                        pass
                    if is_wake_word_enabled():
                        disable_wake_word()
                        self._start_wake_word()
                    log.write(f"[#67e8f9]✓ Wake word model set to '{model_name}'[/#67e8f9]")
                return True

            if not arg_lower or arg_lower == "status":
                st = get_status()
                lines = ["[bold #67e8f9]═══ WAKE WORD STATUS ═══[/bold #67e8f9]", ""]
                lines.append(f"[bold]Listening:[/bold]    " +
                             ("[green]● YES[/green]" if st["listening"] else "[dim]○ no[/dim]"))
                lines.append(f"[bold]Wake words:[/bold]  {', '.join(st['wake_words'])}")
                lines.append(f"[bold]Engine:[/bold]      {st.get('engine', '?')}  [dim]{st.get('hint','')}[/dim]")
                lines.append(f"[bold]Sensitivity:[/bold] {st['sensitivity']}")
                lines.append("")
                lines.append(f"[dim]Available models: {', '.join(st['available_models'])}[/dim]")
                lines.append("")
                lines.append("[dim]Commands:[/dim]")
                lines.append("[dim]  /wake on          - enable listening[/dim]")
                lines.append("[dim]  /wake off         - disable listening[/dim]")
                lines.append("[dim]  /wake sensitivity 0.7  - adjust (0.0-1.0)[/dim]")
                log.write("\n".join(lines))
                return True

            if arg_lower == "on":
                if is_wake_word_enabled():
                    log.write("[#7c8399]Wake word already active[/#7c8399]")
                else:
                    started = self._start_wake_word()
                    if not started:
                        log.write("[#febc2e]⚠ Failed to start wake word[/#febc2e]")
                return True

            if arg_lower == "off":
                disable_wake_word()
                log.write("[#7c8399]🎤 Wake word disabled[/#7c8399]")
                return True

            if arg_lower.startswith("sensitivity "):
                try:
                    val = float(arg_lower.split(" ", 1)[1].strip())
                    if 0.0 <= val <= 1.0:
                        import os as _os
                        _os.environ["WAKE_WORD_SENSITIVITY"] = str(val)
                        # Update env file too
                        try:
                            self._update_env("WAKE_WORD_SENSITIVITY", str(val))
                        except Exception:
                            pass
                        log.write(f"[#67e8f9]✓ Sensitivity set to {val}[/#67e8f9]")
                        log.write("[dim]Restart wake word with /wake off then /wake on[/dim]")
                    else:
                        log.write("[#febc2e]Sensitivity must be 0.0 to 1.0[/#febc2e]")
                except ValueError:
                    log.write("[#febc2e]Invalid number. Example: /wake sensitivity 0.7[/#febc2e]")
                return True

            log.write(f"[#febc2e]Unknown /wake action: {arg}[/#febc2e]")
            log.write("[dim]Use: /wake, /wake on, /wake off, /wake sensitivity 0.7[/dim]")
            return True

        if command == "/rates":
            # Show detailed rate limit status
            try:
                exh = self.agent.llm.get_exhausted_models()
                from agent.llm import FALLBACK_CHAIN

                lines = ["[bold #67e8f9]═══ RATE LIMIT STATUS ═══[/bold #67e8f9]", ""]

                lines.append("[bold]Fallback Chain (in order):[/bold]")
                for i, mid in enumerate(FALLBACK_CHAIN, 1):
                    is_exhausted = any(e["model"] == mid for e in exh)
                    status = "[red]⏸ exhausted[/red]" if is_exhausted else "[green]✓ available[/green]"
                    delay = get_rate_delay(mid)
                    rpm = int(60 / delay) if delay > 0 else "unlimited"
                    lines.append(f"  {i}. {mid[:45]:<45}  {status}  ({rpm} RPM)")

                if exh:
                    lines.append("")
                    lines.append("[bold]Currently rate-limited:[/bold]")
                    for e in exh:
                        mins = e["retry_in"] // 60
                        secs = e["retry_in"] % 60
                        ctype = e.get("cooldown_type", "default")
                        lines.append(
                            f"  • {e['model']:<45}  retry in {mins}m {secs}s  [{ctype}]"
                        )

                lines.append("")
                lines.append("[bold]Current model:[/bold]  " + os.getenv("DEFAULT_MODEL", "?"))
                last_used = getattr(self.agent.llm, "last_used_model", None)
                if last_used and last_used != os.getenv("DEFAULT_MODEL"):
                    lines.append(f"[bold]Last actually used:[/bold]  {last_used}")

                log.write("\n".join(lines))
            except Exception as e:
                log.write(f"[red]Error getting rate status: {e}[/red]")
            return True

        if command == "/help":
            log.write(Panel(
                "[bold #7b8cde]◢ SLASH COMMANDS ◣[/bold #7b8cde]\n\n"
                "[#9aa0b8]/help[/#9aa0b8]                  Show this help\n"
                "[#9aa0b8]/clear[/#9aa0b8]                 Clear chat history\n"
                "[#9aa0b8]/index[/#9aa0b8]                 Re-index current workspace\n"
                "[#9aa0b8]/index status[/#9aa0b8]          Show chunk count\n"
                "[#9aa0b8]/workspace[/#9aa0b8]             Show current workspace\n"
                "[#9aa0b8]/workspace <path>[/#9aa0b8]      Switch workspace\n"
                "[#9aa0b8]/newproject <name>[/#9aa0b8]     Create ~/Projects/<name>/ and switch into it\n"
                "[#9aa0b8]/openproject <name>[/#9aa0b8]    Open an existing project in ~/Projects/\n"
                "[#9aa0b8]/projects[/#9aa0b8]              List all projects in ~/Projects/\n"
                "[#9aa0b8]/newproject <name>[/#9aa0b8]     Create ~/Projects/<name>/ and switch into it\n"
                "[#9aa0b8]/openproject <name>[/#9aa0b8]    Open an existing project in ~/Projects/\n"
                "[#9aa0b8]/projects[/#9aa0b8]              List all projects in ~/Projects/\n"
                "[#9aa0b8]/model[/#9aa0b8]                 Show current model\n"
                "[#9aa0b8]/model <name>[/#9aa0b8]          Switch LLM model\n"
                "[#9aa0b8]/save <name>[/#9aa0b8]           Save session\n"
                "[#9aa0b8]/load <name>[/#9aa0b8]           Resume saved session\n"
                "[#9aa0b8]/sessions[/#9aa0b8]              List saved sessions\n"
                "[#9aa0b8]/stats[/#9aa0b8]                 Show conversation stats\n"
                "[#9aa0b8]/quit[/#9aa0b8]                  Exit Oblivion",
                title="[bold #febc2e]HELP[/bold #febc2e]",
                border_style="#febc2e",
            ))
            return True

        if command == "/clear":
            log.clear()
            self._clear_activity()
            log.write("[#7b8cde]◢ Neural link cleared. Ready for new directives.[/#7b8cde]")
            return True

        if command == "/index":
            if arg == "status":
                from agent.rag import index_stats
                stats = index_stats()
                log.write(Panel(
                    f"[#7b8cde]Total chunks indexed:[/#7b8cde] {stats['total_chunks']}\n"
                    f"[#7b8cde]Storage path:[/#7b8cde] [dim]{stats['index_path']}[/dim]",
                    title="[#3e4560]INDEX STATUS[/#3e4560]",
                    border_style="#3e4560",
                ))
            elif arg == "force":
                log.write("[#febc2e]◢ Force re-indexing entire workspace...[/#febc2e]")
                self.current_status = "INDEXING"
                self.update_status()
                from agent.rag import index_codebase
                stats = await asyncio.to_thread(index_codebase, None, False, True)
                self.current_status = "READY"
                self.update_status()
                log.write(Panel(
                    f"[#7b8cde]✓ Full reindex:[/#7b8cde] {stats['files_indexed']} files, "
                    f"{stats['chunks_added']} chunks",
                    border_style="#7b8cde",
                ))
            else:
                log.write("[#9aa0b8]◢ Incremental indexing (only changed files)...[/#9aa0b8]")
                self.current_status = "INDEXING"
                self.update_status()
                from agent.rag import index_codebase
                stats = await asyncio.to_thread(index_codebase, None, False, False)
                self.current_status = "READY"
                self.update_status()
                log.write(Panel(
                    f"[#7b8cde]✓ {stats['files_indexed']} changed[/#7b8cde]  "
                    f"[dim]{stats['files_unchanged']} unchanged[/dim]  "
                    f"[#9aa0b8]+{stats['chunks_added']} chunks[/#9aa0b8]  "
                    f"[#febc2e]-{stats['deleted']} removed[/#febc2e]",
                    border_style="#7b8cde",
                ))
            return True

        if command == "/workspace":
            if not arg:
                log.write(f"[#7b8cde]Current workspace:[/#7b8cde] {os.getenv('WORKSPACE_DIR', '.')}")
            else:
                expanded = os.path.expanduser(arg)
                if not os.path.isdir(expanded):
                    log.write(f"[#febc2e]✗ Not a directory: {expanded}[/#febc2e]")
                    return True
                os.environ["WORKSPACE_DIR"] = expanded
                # Persist to .env
                from agent.paths import config_env as _cfg
                env_path = _cfg()
                lines = env_path.read_text().splitlines() if env_path.exists() else []
                new_lines = [l for l in lines if not l.startswith("WORKSPACE_DIR=")]
                new_lines.append(f"WORKSPACE_DIR={expanded}")
                env_path.write_text("\n".join(new_lines) + "\n")
                log.write(f"[#7b8cde]✓ Workspace set to:[/#7b8cde] {expanded}")
                log.write("[#febc2e]◢ Run /index to index the new workspace[/#febc2e]")
                self._populate_tree()
                self.update_status()
                # Restart watcher pointed at new workspace
                if self.auto_watch_enabled:
                    self._stop_watcher()
                    # Need to update WORKSPACE in rag module
                    import agent.rag as rag_mod
                    rag_mod.WORKSPACE = Path(expanded).resolve()
                    self.watcher = FileWatcher(
                        workspace=Path(expanded).resolve(),
                        callback=self._on_file_event,
                    )
                    self.watcher.start()
                    log.write(f"[#7b8cde]◢ Watching {expanded} for changes[/#7b8cde]")
                # Polish: also trigger background reindex like /openproject does
                try:
                    self._trigger_bg_reindex(Path(expanded).resolve())
                except Exception:
                    pass
            return True

        if command == "/newproject":
            if not arg:
                log.write("[#febc2e]✗ Usage: /newproject <name>  or  /newproject <path>[/#febc2e]")
                log.write("[dim]Examples:[/dim]")
                log.write("[dim]  /newproject myapp             → ~/Projects/myapp[/dim]")
                log.write("[dim]  /newproject ~/key1            → ~/key1[/dim]")
                log.write("[dim]  /newproject ~/Desktop/foo     → ~/Desktop/foo[/dim]")
                log.write("[dim]  /newproject /tmp/test         → /tmp/test[/dim]")
                return True

            raw = arg.strip()
            from agent.paths import oblivion_home as _ob_home
            self_dir = _ob_home()

            # Decide: is this a PATH (anywhere) or a NAME (goes in ~/Projects/)?
            is_path = (
                raw.startswith("/") or
                raw.startswith("~") or
                raw.startswith("./") or
                raw.startswith("../") or
                "/" in raw
            )

            if is_path:
                new_project = Path(raw).expanduser().resolve()
                display_name = new_project.name
            else:
                # Bare name → ~/Projects/<name>
                projects_root = Path.home() / "Projects"
                projects_root.mkdir(parents=True, exist_ok=True)
                name = raw.replace(" ", "-")
                if name.startswith(".") or "\\" in name:
                    log.write(f"[#febc2e]✗ Invalid project name: {arg}[/#febc2e]")
                    log.write("[dim]Use a simple name like 'my-app', or provide a full path.[/dim]")
                    return True
                new_project = (projects_root / name).resolve()
                display_name = name

            # Safety: refuse if it lands INSIDE the agent source dir
            try:
                new_project.relative_to(self_dir)
                log.write("[#febc2e]✗ Refused: that path is inside the agent source dir.[/#febc2e]")
                log.write("[dim]Pick a location outside ~/.oblivion[/dim]")
                return True
            except ValueError:
                pass

            # Safety: refuse system directories
            forbidden = ["/etc", "/usr", "/bin", "/sbin", "/sys", "/proc", "/boot", "/root"]
            for f in forbidden:
                if str(new_project).startswith(f + "/") or str(new_project) == f:
                    log.write(f"[#febc2e]✗ Refused: {f} is a protected system directory.[/#febc2e]")
                    return True

            if new_project.exists():
                if not new_project.is_dir():
                    log.write(f"[#febc2e]✗ Path exists but is not a directory: {new_project}[/#febc2e]")
                    return True
                log.write(f"[#ffea00]⚠ Already exists:[/#ffea00] {new_project}")
                log.write("[dim]Switching workspace to it (no new folder created).[/dim]")
            else:
                try:
                    new_project.mkdir(parents=True, exist_ok=False)
                except Exception as e:
                    log.write(f"[#febc2e]✗ Could not create directory: {e}[/#febc2e]")
                    return True

            # ── Switch workspace ──
            os.environ["WORKSPACE_DIR"] = str(new_project)
            self._update_env("WORKSPACE_DIR", str(new_project))
            try:
                import agent.rag as rag_mod
                rag_mod.WORKSPACE = new_project
            except Exception:
                pass
            try:
                import tools.filesystem as fs_mod
                fs_mod.WORKSPACE = new_project
            except Exception:
                pass

            log.write(Panel(
                f"[#7b8cde]✓ New workspace ready:[/#7b8cde] [bold]{display_name}[/bold]\n"
                f"[#9aa0b8]Location:[/#9aa0b8] [dim]{new_project}[/dim]\n"
                f"[#7b8cde]Workspace switched.[/#7b8cde] Oblivion will now build here.",
                title="[#3e4560]◢ NEW WORKSPACE ◣[/#3e4560]",
                border_style="#7b8cde",
            ))
            if self.auto_watch_enabled:
                self._stop_watcher()
                self.watcher = FileWatcher(workspace=new_project, callback=self._on_file_event)
                self.watcher.start()
            self._populate_tree()
            self.update_status()
            self._trigger_bg_reindex(new_project)
            return True

        if command == "/openproject":
            if not arg:
                log.write("[#febc2e]✗ Usage: /openproject <name-or-path>[/#febc2e]")
                log.write("[dim]Examples:  /openproject myapp   |  /openproject ~/Projects/foo   |  /openproject ~/code[/dim]")
                return True

            raw = arg.strip()
            projects_root = Path.home() / "Projects"

            # Accept either: name inside ~/Projects/, OR absolute/~-prefixed path
            if raw.startswith("/") or raw.startswith("~") or raw.startswith("./") or raw.startswith("../"):
                target = Path(raw).expanduser().resolve()
            else:
                # Try ~/Projects/<name> first, fall back to absolute resolve
                p_proj = (projects_root / raw).resolve()
                if p_proj.exists() and p_proj.is_dir():
                    target = p_proj
                else:
                    # Maybe user typed a bare name that happens to be a directory in CWD or home
                    p_alt = Path(raw).expanduser().resolve()
                    target = p_alt

            if not target.exists() or not target.is_dir():
                log.write(f"[#febc2e]✗ Not found: {target}[/#febc2e]")
                log.write("[dim]Use /projects to list ~/Projects/ entries, or pass an absolute path.[/dim]")
                return True
            os.environ["WORKSPACE_DIR"] = str(target)
            self._update_env("WORKSPACE_DIR", str(target))
            try:
                import agent.rag as rag_mod
                rag_mod.WORKSPACE = target
            except Exception:
                pass
            try:
                import tools.filesystem as fs_mod
                fs_mod.WORKSPACE = target
            except Exception:
                pass
            log.write(Panel(
                f"[#7b8cde]✓ Opened project:[/#7b8cde] [bold]{arg}[/bold]\n"
                f"[#9aa0b8]Location:[/#9aa0b8] [dim]{target}[/dim]",
                title="[#3e4560]◢ PROJECT OPENED ◣[/#3e4560]",
                border_style="#7b8cde",
            ))
            if self.auto_watch_enabled:
                self._stop_watcher()
                self.watcher = FileWatcher(workspace=target, callback=self._on_file_event)
                self.watcher.start()
            self._populate_tree()
            self.update_status()
            self._trigger_bg_reindex(target)
            return True

        if command == "/projects":
            projects_root = Path.home() / "Projects"
            if not projects_root.exists():
                log.write(f"[dim]~/Projects/ does not exist yet. Use /newproject <name> to create one.[/dim]")
                return True
            folders = sorted([p for p in projects_root.iterdir() if p.is_dir() and not p.name.startswith(".")])
            if not folders:
                log.write("[dim]~/Projects/ is empty. Use /newproject <name> to create one.[/dim]")
                return True
            current_ws = Path(os.getenv("WORKSPACE_DIR", "")).resolve()
            lines = []
            for p in folders:
                marker = "[#7b8cde]★[/#7b8cde]" if p.resolve() == current_ws else " "
                lines.append(f"{marker} [bold]{p.name}[/bold]  [dim]{p}[/dim]")
            log.write(Panel(
                "\n".join(lines) + "\n\n[dim]★ = current workspace.  Use /openproject <name> to switch.[/dim]",
                title=f"[#3e4560]◢ PROJECTS ({len(folders)}) ◣[/#3e4560]",
                border_style="#3e4560",
            ))
            return True

        if command in ("/model", "/models"):
            # Quick subcommand: clear the exhausted-models cache
            if arg.strip().lower() in ("reset", "reset-exhausted", "clear-exhausted"):
                try:
                    self.agent.llm.reset_exhausted_models()
                    log.write("[#7b8cde]Cleared exhausted-models cache. All fallback models will be retried.[/#7b8cde]")
                except Exception as e:
                    log.write(f"[#febc2e]Could not reset: {e}[/#febc2e]")
                return True

            if not arg:
                # Show table of all models
                current = get_current_model_info()
                lines = [f"[dim]Current:[/dim] [bold {current['color']}]{current['name']}[/bold {current['color']}]  [#9aa0b8]{current['id']}[/#9aa0b8]"]
                lines.append("")
                lines.append("[bold]Available models:[/bold]")
                lines.append("")
                for m in list_models_table():
                    marker = "[#7b8cde]★[/#7b8cde]" if m["id"] == current["id"] else " "
                    ok, _ = check_api_key(m["name"])
                    key_status = "" if ok else "  [#febc2e](no key)[/#febc2e]"
                    lines.append(
                        f"{marker} [bold {m.get('color', '#7b8cde')}]{m['name']:<15}[/bold {m.get('color', '#7b8cde')}] "
                        f"[#9aa0b8]{m.get('cost', ''):<20}[/#9aa0b8] "
                        f"[dim]{m['description']}[/dim]{key_status}"
                    )
                lines.append("")
                lines.append("[dim]Use:[/dim] [#7b8cde]/model <name>[/#7b8cde]  to switch")
                log.write(Panel(
                    "\n".join(lines),
                    title="[bold #3e4560]◢ MODEL REGISTRY ◣[/bold #3e4560]",
                    border_style="#3e4560",
                ))
                return True

            # Switch to a model
            model_name = arg.strip()

            # Try short name first
            if model_name in MODELS:
                info = MODELS[model_name]
                # Check API key
                ok, msg = check_api_key(model_name)
                if not ok:
                    log.write(Panel(
                        f"[#febc2e]✗ Cannot switch to {model_name}[/#febc2e]\n\n{msg}",
                        title="[#febc2e]API KEY MISSING[/#febc2e]",
                        border_style="#febc2e",
                    ))
                    return True

                full_id = info["id"]
                os.environ["DEFAULT_MODEL"] = full_id

                from agent.paths import config_env as _cfg
                env_path = _cfg()
                lines = env_path.read_text().splitlines() if env_path.exists() else []
                new_lines = [l for l in lines if not l.startswith("DEFAULT_MODEL=")]
                new_lines.append(f"DEFAULT_MODEL={full_id}")
                env_path.write_text("\n".join(new_lines) + "\n")

                # No need to reload agent - LLMClient.model is dynamic now
                log.write(Panel(
                    f"[bold {info['color']}]✓ Switched to: {model_name}[/bold {info['color']}]\n\n"
                    f"[#9aa0b8]Model:[/#9aa0b8]   {info['id']}\n"
                    f"[#9aa0b8]Speed:[/#9aa0b8]   {info['speed']}\n"
                    f"[#9aa0b8]Cost:[/#9aa0b8]    {info['cost']}\n"
                    f"[dim]{info['description']}[/dim]",
                    title="[bold #7b8cde]MODEL SWITCHED[/bold #7b8cde]",
                    border_style=info['color'],
                ))
                self.update_status()
                return True

            # Try raw model id (e.g. "ollama/qwen3-coder:480b-cloud")
            if "/" in model_name:
                os.environ["DEFAULT_MODEL"] = model_name
                from agent.paths import config_env as _cfg
                env_path = _cfg()
                lines = env_path.read_text().splitlines() if env_path.exists() else []
                new_lines = [l for l in lines if not l.startswith("DEFAULT_MODEL=")]
                new_lines.append(f"DEFAULT_MODEL={model_name}")
                env_path.write_text("\n".join(new_lines) + "\n")
                log.write(f"[#7b8cde]✓ Switched to (raw):[/#7b8cde] {model_name}")
                self.update_status()
                return True

            # Unknown short name
            available = ", ".join(MODELS.keys())
            log.write(f"[#febc2e]✗ Unknown model: {model_name}[/#febc2e]")
            log.write(f"[dim]Available: {available}[/dim]")
            log.write(f"[dim]Or use full id: /model groq/llama-3.3-70b-versatile[/dim]")
            return True

        if command == "/save":
            if not arg:
                log.write("[#febc2e]Usage: /save <name>[/#febc2e]")
                return True
            from agent.paths import sessions_dir as _sess
            save_dir = _sess()
            import json
            (save_dir / f"{arg}.json").write_text(
                json.dumps(self.agent.conversation, indent=2)
            )
            log.write(f"[#7b8cde]✓ Saved session:[/#7b8cde] {arg}")
            return True

        if command == "/load":
            if not arg:
                log.write("[#febc2e]Usage: /load <name>[/#febc2e]")
                return True
            from agent.paths import sessions_dir as _sess
            save_path = _sess() / f"{arg}.json"
            if not save_path.exists():
                log.write(f"[#febc2e]✗ Session not found: {arg}[/#febc2e]")
                return True
            import json
            self.agent.conversation = json.loads(save_path.read_text())
            log.write(f"[#7b8cde]✓ Loaded session:[/#7b8cde] {arg} ({len(self.agent.conversation)} messages)")
            return True

        if command == "/sessions":
            from agent.paths import sessions_dir as _sess
            save_dir = _sess()
            if not list(save_dir.iterdir()):
                log.write("[dim]No saved sessions yet. Use /save <name>[/dim]")
            else:
                sessions = sorted(save_dir.glob("*.json"))
                lines = [f"[#9aa0b8]{s.stem}[/#9aa0b8]  [dim]({s.stat().st_size}B)[/dim]" for s in sessions]
                log.write(Panel(
                    "\n".join(lines),
                    title="[#3e4560]SAVED SESSIONS[/#3e4560]",
                    border_style="#3e4560",
                ))
            return True

        if command == "/stats":
            current = get_current_model_info()
            tokens = self.agent.llm.get_token_stats()
            log.write(Panel(
                f"[#7b8cde]Session ID:[/#7b8cde]    {self.session_id}\n"
                f"[#7b8cde]Messages:[/#7b8cde]      {len(self.agent.conversation)}\n"
                f"[#7b8cde]Model:[/#7b8cde]         [bold {current['color']}]{current['name']}[/bold {current['color']}] [dim]({current['id']})[/dim]\n"
                f"[#7b8cde]Cost tier:[/#7b8cde]     {current['cost']}\n"
                f"[#7b8cde]Workspace:[/#7b8cde]     {os.getenv('WORKSPACE_DIR', '?')}\n"
                f"\n"
                f"[#7b8cde]Tokens in:[/#7b8cde]     {tokens['input']:,}\n"
                f"[#7b8cde]Tokens out:[/#7b8cde]    {tokens['output']:,}\n"
                f"[#7b8cde]Total tokens:[/#7b8cde]  {tokens['total']:,}",
                title="[#3e4560]SESSION STATS[/#3e4560]",
                border_style="#3e4560",
            ))
            return True

        if command == "/watch":
            if arg == "off":
                self._stop_watcher()
                self.auto_watch_enabled = False
                log.write("[#febc2e]◢ Auto-watch disabled[/#febc2e]")
            elif arg == "on" or arg == "":
                self.auto_watch_enabled = True
                self._start_watcher()
                status = "watching" if self.watcher and self.watcher.is_running() else "stopped"
                log.write(f"[#7b8cde]◢ Auto-watch enabled ({status})[/#7b8cde]")
            elif arg == "status":
                running = self.watcher.is_running() if self.watcher else False
                log.write(Panel(
                    f"[#7b8cde]Auto-watch:[/#7b8cde] {'ON' if self.auto_watch_enabled else 'OFF'}\n"
                    f"[#7b8cde]Watcher running:[/#7b8cde] {'yes' if running else 'no'}\n"
                    f"[#7b8cde]Workspace:[/#7b8cde] {os.getenv('WORKSPACE_DIR', '?')}",
                    title="[#3e4560]WATCHER STATUS[/#3e4560]",
                    border_style="#3e4560",
                ))
            else:
                log.write("[#febc2e]Usage: /watch [on|off|status][/#febc2e]")
            return True

        if command == "/meera":
            from agent import friday as fri
            if arg == "" or arg == "status":
                log.write(Panel(
                    f"[#7b8cde]Enabled:[/#7b8cde] {fri.is_enabled()}\n"
                    f"[#7b8cde]Voice:[/#7b8cde]    {fri.get_voice()}\n"
                    f"[#7b8cde]Name:[/#7b8cde]     {fri.get_name()}\n"
                    f"[#7b8cde]Rate:[/#7b8cde]     {fri.get_rate()}\n"
                    f"[#7b8cde]Volume:[/#7b8cde]   {fri.get_volume()}\n"
                    f"\n[dim]Personas:[/dim] {', '.join(getattr(fri, 'EDGE_VOICES', getattr(fri, 'VOICES', {})).keys())}",
                    title="[#3e4560]M.E.E.R.A. STATUS[/#3e4560]",
                    border_style="#3e4560",
                ))
                return True
            if arg in ("on", "enable"):
                os.environ["FRIDAY_ENABLED"] = "true"
                self._update_env("FRIDAY_ENABLED", "true")
                log.write("[#7b8cde]M.E.E.R.A. enabled.[/#7b8cde]")
                fri.speak(f"Online, {fri.get_name()}.")
                return True
            if arg in ("off", "disable"):
                os.environ["FRIDAY_ENABLED"] = "false"
                self._update_env("FRIDAY_ENABLED", "false")
                fri.stop_speaking()
                log.write("[#febc2e]M.E.E.R.A. silenced.[/#febc2e]")
                return True
            if arg == "stop":
                fri.stop_speaking()
                log.write("[dim]Speech interrupted.[/dim]")
                return True
            if arg == "test":
                name = fri.get_name()
                phrase = f"Good day, {name}. M.E.E.R.A. systems online. Voice {fri.get_voice()} responding."
                log.write(f"[#9aa0b8]🔊 {phrase}[/#9aa0b8]")
                fri.speak(phrase)
                return True
            if arg.startswith("persona "):
                persona = arg.replace("persona ", "", 1).strip().lower()
                if persona in getattr(fri, 'EDGE_VOICES', getattr(fri, 'VOICES', {})):
                    os.environ["FRIDAY_VOICE"] = persona
                    self._update_env("FRIDAY_VOICE", persona)
                    log.write(f"[#7b8cde]Voice persona: {persona} ({getattr(fri, 'EDGE_VOICES', getattr(fri, 'VOICES', {}))[persona]})[/#7b8cde]")
                    fri.speak(f"Voice updated, {fri.get_name()}.")
                else:
                    log.write(f"[#febc2e]Unknown persona. Try: {', '.join(getattr(fri, 'EDGE_VOICES', getattr(fri, 'VOICES', {})).keys())}[/#febc2e]")
                return True
            if arg.startswith("name "):
                new_name = arg.replace("name ", "", 1).strip()
                if new_name:
                    os.environ["FRIDAY_NAME"] = new_name
                    self._update_env("FRIDAY_NAME", new_name)
                    log.write(f"[#7b8cde]Now calling you: {new_name}[/#7b8cde]")
                    fri.speak(f"As you wish, {new_name}.")
                return True
            if arg.startswith("rate "):
                rate = arg.replace("rate ", "", 1).strip()
                if not rate.endswith("%"):
                    rate = rate + "%"
                if not (rate.startswith("+") or rate.startswith("-")):
                    rate = "+" + rate
                os.environ["FRIDAY_RATE"] = rate
                self._update_env("FRIDAY_RATE", rate)
                log.write(f"[#7b8cde]Speech rate: {rate}[/#7b8cde]")
                fri.speak(f"Speech rate adjusted, {fri.get_name()}.")
                return True
            log.write("[#febc2e]Usage: /friday [on|off|stop|test|status|persona <name>|name <text>|rate <±N%>][/#febc2e]")
            return True

        if command == "/voice":
            if arg == "" or arg == "record":
                # Same as F2
                self.action_toggle_voice()
                return True
            if arg == "devices":
                devices = list_input_devices()
                lines = [
                    f"{'★' if d['default'] else ' '} [{d['index']}] {d['name']} ({d['channels']} ch)"
                    for d in devices
                ]
                log.write(Panel(
                    "\n".join(lines) or "[dim]No input devices found.[/dim]",
                    title="[#3e4560]AUDIO INPUT DEVICES[/#3e4560]",
                    border_style="#3e4560",
                ))
                return True
            if arg.startswith("model "):
                model_name = arg.replace("model ", "", 1).strip()
                from agent import voice
                voice.clear_model()
                from agent.paths import config_env as _cfg
                env_path = _cfg()
                lines = env_path.read_text().splitlines() if env_path.exists() else []
                new_lines = [l for l in lines if not l.startswith("VOICE_MODEL=")]
                new_lines.append(f"VOICE_MODEL={model_name}")
                env_path.write_text("\n".join(new_lines) + "\n")
                os.environ["VOICE_MODEL"] = model_name
                log.write(f"[#7b8cde]✓ Whisper model set to: {model_name}[/#7b8cde]")
                log.write("[dim]Will load on next voice recording.[/dim]")
                return True
            if arg == "status":
                current_model = os.getenv("VOICE_MODEL", "small")
                log.write(Panel(
                    f"[#7b8cde]Whisper model:[/#7b8cde]  {current_model}\n"
                    f"[#7b8cde]Status:[/#7b8cde]         {self.voice_status}\n"
                    f"[#7b8cde]Recording:[/#7b8cde]      {'YES' if self.voice_recording else 'no'}\n"
                    f"[#7b8cde]Hotkey:[/#7b8cde]         F2 (start / stop)",
                    title="[#3e4560]VOICE STATUS[/#3e4560]",
                    border_style="#3e4560",
                ))
                return True
            log.write("[#febc2e]Usage: /voice [record|devices|status|model <name>][/#febc2e]")
            return True

        if command == "/memory":
            from agent.brain import load_memory, get_memory_summary, get_memory_path
            if arg == "" or arg == "show":
                content = load_memory()
                if not content.strip():
                    log.write(Panel(
                        "[dim]No memory yet for this workspace.[/dim]\n\n"
                        "Memory grows as the agent learns project conventions.\n"
                        "It writes to MEMORY.md in your workspace root.",
                        title="[#3e4560]MEMORY[/#3e4560]",
                        border_style="#3e4560",
                    ))
                else:
                    # Show truncated for chat panel
                    preview = content if len(content) < 2000 else content[:2000] + "\n\n...(truncated)"
                    log.write(Panel(
                        preview,
                        title="[#3e4560]WORKSPACE MEMORY[/#3e4560]",
                        border_style="#3e4560",
                    ))
                return True
            if arg == "stats":
                stats = get_memory_summary()
                if not stats["exists"]:
                    log.write("[dim]No MEMORY.md yet[/dim]")
                else:
                    log.write(Panel(
                        f"[#7b8cde]Notes:[/#7b8cde]      {stats['notes']}\n"
                        f"[#7b8cde]Categories:[/#7b8cde] {stats['categories']}\n"
                        f"[#7b8cde]Size:[/#7b8cde]       {stats['size_bytes']:,} bytes\n"
                        f"[#7b8cde]Path:[/#7b8cde]       {stats['path']}",
                        title="[#3e4560]MEMORY STATS[/#3e4560]",
                        border_style="#3e4560",
                    ))
                return True
            if arg == "edit":
                p = get_memory_path()
                if not p.exists():
                    p.write_text("# Project Memory\n\n_Notes remembered by Oblivion._\n\n", encoding="utf-8")
                log.write(f"[#7b8cde]Memory file: {p}[/#7b8cde]")
                log.write("[dim]Open it in your editor to manually edit.[/dim]")
                return True
            if arg == "clear":
                p = get_memory_path()
                if p.exists():
                    p.unlink()
                log.write("[#febc2e]Memory cleared.[/#febc2e]")
                return True
            log.write("[#febc2e]Usage: /memory [show|stats|edit|clear][/#febc2e]")
            return True

        if command == "/verify":
            from agent.brain import verify_code as vc
            if not arg:
                log.write("[#febc2e]Usage: /verify <path>[/#febc2e]")
                return True
            result = vc(arg.strip())
            if result["ok"]:
                log.write(Panel(
                    f"[#7b8cde]{result['message']}[/#7b8cde]",
                    title=f"[#7b8cde]VERIFIED: {arg}[/#7b8cde]",
                    border_style="#7b8cde",
                ))
            else:
                log.write(Panel(
                    f"[#febc2e]{result['message']}[/#febc2e]\n\n"
                    f"[dim]{result['details']}[/dim]",
                    title=f"[#febc2e]FAILED: {arg}[/#febc2e]",
                    border_style="#febc2e",
                ))
            return True

        if command == "/update":
            from agent.updater import current_version, has_update, install_update, changelog_url, latest_version
            sub = arg.strip().lower()

            if sub == "" or sub == "check":
                log.write("[dim]Checking PyPI for newer version...[/dim]")
                cur = current_version()
                update = has_update()
                if update is None:
                    latest = latest_version()
                    lv = latest['version'] if latest else 'unknown'
                    log.write(Panel(
                        f"[#7b8cde]Current:[/#7b8cde] {cur}\n"
                        f"[#7b8cde]Latest:[/#7b8cde]  {lv}\n\n"
                        f"[#7b8cde]✓ You're on the latest version.[/#7b8cde]",
                        title="[#7b8cde]UPDATE CHECK[/#7b8cde]",
                        border_style="#7b8cde",
                    ))
                else:
                    log.write(Panel(
                        f"[#febc2e]✨ Update available![/#febc2e]\n\n"
                        f"[#7b8cde]Current:[/#7b8cde]      {update['current']}\n"
                        f"[#7b8cde]Latest:[/#7b8cde]       [bold #febc2e]{update['latest']}[/bold #febc2e]\n"
                        f"[#7b8cde]Released:[/#7b8cde]     {update['release_date']}\n"
                        f"[#7b8cde]Changelog:[/#7b8cde]    {changelog_url(update['latest'])}\n\n"
                        f"[dim]Run [bold #7b8cde]/update install[/bold #7b8cde] to upgrade now.[/dim]",
                        title="[bold #febc2e]◆ NEW VERSION AVAILABLE ◆[/bold #febc2e]",
                        border_style="#febc2e",
                    ))
                return True

            if sub == "install" or sub == "upgrade":
                update = has_update()
                if update is None:
                    log.write("[#7b8cde]✓ Already on latest version, nothing to install.[/#7b8cde]")
                    return True
                log.write(Panel(
                    f"[#febc2e]Installing oblivion-agent {update['latest']}...[/#febc2e]\n"
                    f"[dim]This may take 30-60 seconds. Running pip install --upgrade.[/dim]",
                    border_style="#febc2e",
                ))
                # Run pip install in a thread to avoid blocking UI
                import threading as _th
                def _do_install():
                    result = install_update()
                    if result["ok"]:
                        msg = (
                            f"[#7b8cde]✓ Upgraded to {result['new_version']}![/#7b8cde]\n\n"
                            f"[#febc2e]⚠ Restart Oblivion to use the new version:[/#febc2e]\n"
                            f"  1. Type [bold]/quit[/bold]\n"
                            f"  2. Run [bold]oblivion[/bold] again"
                        )
                        self.call_from_thread(log.write, Panel(
                            msg,
                            title="[#7b8cde]✓ UPDATE COMPLETE[/#7b8cde]",
                            border_style="#7b8cde",
                        ))
                    else:
                        tail = result["output"][-400:] if len(result["output"]) > 400 else result["output"]
                        self.call_from_thread(log.write, Panel(
                            f"[#febc2e]✗ Update failed[/#febc2e]\n\n[dim]{tail}[/dim]\n\n"
                            f"[dim]Try manually: pip install --upgrade oblivion-agent[/dim]",
                            title="[#febc2e]UPDATE FAILED[/#febc2e]",
                            border_style="#febc2e",
                        ))
                _th.Thread(target=_do_install, daemon=True).start()
                return True

            if sub == "changelog":
                log.write(Panel(
                    f"[#7b8cde]Current version:[/#7b8cde] {current_version()}\n\n"
                    f"[#7b8cde]Changelog:[/#7b8cde] {changelog_url()}\n"
                    f"[#7b8cde]All releases:[/#7b8cde] https://github.com/Rohith-s-hub/Oblivion-agent/releases",
                    title="[#3e4560]CHANGELOG[/#3e4560]",
                    border_style="#3e4560",
                ))
                return True

            log.write("[#febc2e]Usage: /update [check|install|changelog][/#febc2e]")
            return True

        if command == "/trust":
            # /trust             -> show current trust state
            # /trust edit        -> pre-approve edit_file/write_file/insert_after
            # /trust all-mutate  -> pre-approve every mutate-tier tool
            # /trust workspace   -> pre-approve create_dir/new_workspace
            # /trust server      -> pre-approve start_server/stop_server
            # /trust reset       -> clear trusted set
            from agent.permissions import expand_trust_group, TRUST_GROUPS, TOOL_TIERS
            state = self._runtime_state() if hasattr(self, "_runtime_state") else {}
            trusted = state.get("trusted_tools", set())
            arg_stripped = arg.strip()

            if arg_stripped == "" or arg_stripped == "show":
                if trusted:
                    lines = ["[bold #7b8cde]Currently trusted (bypass approval):[/bold #7b8cde]"]
                    for t in sorted(trusted):
                        lines.append(f"  \u2022 {t}")
                else:
                    lines = ["[dim]No tools trusted this session.[/dim]"]
                lines.append("")
                lines.append("[dim]Groups: " + ", ".join(sorted(TRUST_GROUPS.keys())) + "[/dim]")
                lines.append("[dim]Usage: /trust <group>  |  /trust reset[/dim]")
                log.write(Panel("\n".join(lines), title="[#3e4560]TRUST[/#3e4560]", border_style="#3e4560"))
                return True

            if arg_stripped == "reset":
                self._set_trusted(set())
                log.write("[#7b8cde]Trust list cleared. All mutations will prompt again.[/#7b8cde]")
                return True

            group_tools = expand_trust_group(arg_stripped)
            if not group_tools:
                log.write(f"[#febc2e]Unknown trust group: {arg_stripped}[/#febc2e]  Available: " + ", ".join(sorted(TRUST_GROUPS.keys())))
                return True

            self._set_trusted(trusted | group_tools)
            log.write(f"[#7b8cde]\u2713 Trusted {len(group_tools)} tools for this session:[/#7b8cde] " + ", ".join(sorted(group_tools)))
            log.write("[dim]These will auto-approve. Destructive commands still prompt.[/dim]")
            return True

        if command == "/auto":
            # /auto            -> toggle auto-mode (session only)
            # /auto --persist  -> save to config.env
            arg_stripped = arg.strip()
            state = self._runtime_state() if hasattr(self, "_runtime_state") else {}
            currently = state.get("auto_mode", False)
            new_state = not currently

            self._set_auto(new_state)

            if new_state:
                log.write(Panel(
                    "[bold #febc2e]AUTO MODE ON[/bold #febc2e]\n\n"
                    "Mutations (write, edit, create) will auto-approve.\n"
                    "[bold #ff006e]Destructive commands (rm -rf, dd, git push --force) STILL prompt.[/bold #ff006e]\n\n"
                    "[dim]Type /auto again to turn off.[/dim]",
                    title="[#febc2e]AUTO[/#febc2e]",
                    border_style="#febc2e",
                ))
                if arg_stripped == "--persist":
                    self._update_env("OBLIVION_AUTO_MODE", "true")
                    log.write("[dim]Persisted to config.env - remembered across restarts.[/dim]")
            else:
                log.write("[#7b8cde]AUTO mode OFF. Approval prompts restored.[/#7b8cde]")
                if arg_stripped == "--persist" or "OBLIVION_AUTO_MODE" in (self._read_config() if hasattr(self, "_read_config") else ""):
                    self._update_env("OBLIVION_AUTO_MODE", "false")
            self.update_status()
            return True

        if command == "/switch":
            from ui.sim_screen import SimScreen
            log.write("[#7b8cde]Switching to 8085 Simulator mode...[/#7b8cde]")
            log.write("[dim]Press ESC or click Back to return to Oblivion.[/dim]")
            self.push_screen(SimScreen())
            return True

        if command == "/quit":
            self._stop_watcher()
            if self.voice_stop_event is not None:
                self.voice_stop_event.set()
            try:
                from agent import friday as fri
                fri.stop_speaking()
            except Exception:
                pass
            self.exit()
            return True

        log.write(f"[#febc2e]✗ Unknown command: {command}[/#febc2e]  Type [#7b8cde]/help[/#7b8cde]")
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
                    label = f"[bold #7b8cde]{cmd:<18}[/bold #7b8cde] [dim]{desc}[/dim]"
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
        log.write(f"[bold #febc2e]YOU:[/bold #febc2e] {user_input}")
        log.write("[dim #7b8cde]⯿ M.E.E.R.A is thinking...[/dim #7b8cde]")
        self.current_status = "▓ THINKING"
        self.update_status()

        save_message(self.session_id, "user", user_input)
        self.agent_busy = True
        self.run_worker(self._run_agent(user_input), exclusive=True)

    async def _run_agent(self, user_message: str):
        """Phase 2A: delegates the loop to AgentRuntime; TUI just renders + approves."""
        log = self.query_one("#chat-log", RichLog)
        activity_scroll = self.query_one("#activity-scroll", VerticalScroll)

        # Read iteration budget from env (was hardcoded to 20, ignoring .env!)
        max_iter = int(os.getenv("MAX_ITERATIONS", "30"))
        # Detect complex tasks and auto-bump the budget
        complex_keywords = [
            "build", "create a", "make a", "scaffold", "set up", "setup",
            "clone", "implement", "develop", "generate a", "full",
            "complete", "entire", "whole", "website", "app", "application",
            "project", "react", "vue", "django", "flask", "fastapi",
            "netflix", "twitter", "spotify", "instagram", "dashboard",
        ]
        lower = user_message.lower()
        if any(kw in lower for kw in complex_keywords):
            max_iter = max(max_iter, 50)  # complex tasks get 50 iterations
        runtime = AgentRuntime(self.agent, self.session_id, max_iterations=max_iter)
        # Sync app-level trust/auto state into this runtime instance
        self._last_runtime = runtime
        app_state = getattr(self, "_app_session_state", None)
        if app_state:
            runtime.session_state["auto_mode"] = app_state.get("auto_mode", False)
            runtime.session_state["trusted_tools"] = set(app_state.get("trusted_tools", set()))
        # Load persisted auto-mode from config.env if present
        import os as _os_tier
        if _os_tier.getenv("OBLIVION_AUTO_MODE", "").lower() == "true":
            runtime.session_state["auto_mode"] = True

        # ── Callbacks ────────────────────────────────────────────────────────
        spinner_box = {"item": None, "tokens": 0}

        async def on_llm_start(step: int):
            self.iteration_count = step
            self.current_status = f"▓ LLM step {step}"
            self.update_status()
            item = ActivityItem("llm.chat", {"step": step}, "running")
            await activity_scroll.mount(item)
            activity_scroll.scroll_end(animate=False)
            spinner_box["item"] = item
            spinner_box["tokens"] = 0

        def on_token(tok: str):
            spinner_box["tokens"] += 1
            it = spinner_box["item"]
            if it is not None:
                it.result = f"streaming… {spinner_box['tokens']} tokens"
                try:
                    it.update_display()
                except Exception:
                    pass

        async def on_llm_end(step: int, output: str, tokens: int):
            it = spinner_box["item"]
            if it is not None:
                it.set_done(f"{len(output)} chars, {spinner_box['tokens']} tokens")

        async def on_thought(thought: str):
            """THOUGHTs are internal reasoning debug. Silent by default.
            Users see ANSWERS not reasoning. Log to Agent Log as breadcrumb."""
            try:
                scroll = self.query_one("#activity-scroll", VerticalScroll)
                t = thought[:120] + "…" if len(thought) > 120 else thought
                dim_thought = Static(f"[dim #3e4560]◇ {t}[/dim #3e4560]")
                self.call_from_thread(self._mount_watcher_item, scroll, dim_thought)
            except Exception:
                pass

        async def on_tool_start(tool_name: str, args: dict):
            # JARVIS-STYLE VOICE FEEDBACK: Speak asynchronously while working
            import random
            if tool_name == "batch_edit":
                self._speak_async(random.choice(["Building the files now, boss.", "Drafting the code.", "Right away, boss."]))
            elif tool_name in ["search_code", "grep_files"]:
                self._speak_async(random.choice(["Scanning the codebase.", "Looking that up now.", "Searching."]))
            elif tool_name == "plan_task":
                self._speak_async("Formulating a plan.")
            elif tool_name == "open_preview":
                self._speak_async("Opening the live preview in your browser.")
            elif tool_name == "run_bash":
                self._speak_async("Executing terminal command.")

            # CLAUDE-CODE-STYLE PROGRESS: narrate meaningful actions in chat
            try:
                if tool_name == "write_file":
                    _p = args.get("path", "?")
                    _sz = len(args.get("content", ""))
                    log.write(f"[bold #7b8cde]✦[/bold #7b8cde] [#e0e7ff]Writing [bold]{_p}[/bold] [dim]({_sz} chars)[/dim]...[/#e0e7ff]")
                elif tool_name == "batch_edit":
                    _edits = args.get("edits", [])
                    log.write(f"[bold #7b8cde]✦[/bold #7b8cde] [#e0e7ff]Writing [bold]{len(_edits)} files[/bold] in batch...[/#e0e7ff]")
                    for _e in _edits[:12]:
                        if isinstance(_e, dict):
                            _pp = _e.get("path", "?")
                            _cc = _e.get("content") or _e.get("new_text") or ""
                            _sz2 = len(_cc) if isinstance(_cc, str) else 0
                            log.write(f"[dim #7c8399]   → {_pp}[/dim #7c8399] [dim]({_sz2} chars)[/dim]")
                elif tool_name == "edit_file":
                    _p = args.get("path", "?")
                    log.write(f"[bold #7b8cde]✦[/bold #7b8cde] [#e0e7ff]Editing [bold]{_p}[/bold]...[/#e0e7ff]")
                elif tool_name == "run_bash":
                    _cmd = args.get("command", "?")[:60]
                    log.write(f"[dim #67e8f9]▸[/dim #67e8f9] [#e0e7ff]Running:[/#e0e7ff] [dim]{_cmd}[/dim]")
                elif tool_name in ("switch_workspace", "new_workspace"):
                    _pp = args.get("path") or args.get("name", "?")
                    log.write(f"[dim #22d3ee]⇄[/dim #22d3ee] [#e0e7ff]Workspace →[/#e0e7ff] [bold]{_pp}[/bold]")
                elif tool_name == "git_commit":
                    _msg = args.get("message", "?")[:60]
                    log.write(f"[dim #67e8f9]✓[/dim #67e8f9] [#e0e7ff]Committing:[/#e0e7ff] [dim]{_msg}[/dim]")
                elif tool_name == "create_dir":
                    _pp = args.get("path", "?")
                    log.write(f"[dim #a78bfa]+[/dim #a78bfa] [#e0e7ff]Creating dir [bold]{_pp}[/bold][/#e0e7ff]")
                elif tool_name == "run_tests":
                    log.write(f"[dim #67e8f9]▸[/dim #67e8f9] [#e0e7ff]Running tests...[/#e0e7ff]")
            except Exception:
                pass  # never let narration break the agent

            item = ActivityItem(tool_name, args, "running")
            item.tool_name = tool_name  # remember for post-execution hooks
            await activity_scroll.mount(item)
            activity_scroll.scroll_end(animate=False)
            self.activity_items.append(item)
            self.current_status = f"▓ {tool_name}"
            self.update_status()
            return item

        async def on_tool_done(handle, result: str, ms: int):
            if handle is not None:
                handle.result = f"{result}  [dim]({ms}ms)[/dim]"
                handle.set_done(handle.result)
            # If the agent just switched workspace, refresh UI panel + watcher
            if handle is not None and getattr(handle, "tool_name", "") == "new_workspace":
                if "Workspace" in (result or "") and "switched" in (result or ""):
                    try:
                        new_ws = Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()
                        log.write(Panel(
                            f"[#7b8cde]✓ Workspace is now:[/#7b8cde] [dim]{new_ws}[/dim]",
                            title="[#3e4560]◢ WORKSPACE SWITCHED ◣[/#3e4560]",
                            border_style="#7b8cde",
                        ))
                        if self.auto_watch_enabled:
                            self._stop_watcher()
                            self.watcher = FileWatcher(workspace=new_ws, callback=self._on_file_event)
                            self.watcher.start()
                        self._populate_tree()
                        self.update_status()
                        self._trigger_bg_reindex(new_ws)
                    except Exception as e:
                        log.write(f"[#febc2e]⚠ UI refresh after workspace switch failed: {e}[/#febc2e]")

        async def on_approve_tool(tool_name: str, args: dict) -> bool:
            # Reuse the existing TUI ApprovalModal flow via _handle_tool helpers
            path = args.get("path", "")
            if tool_name == "write_file":
                content = args.get("content", "")
                try:
                    from tools.filesystem import _safe_path, _PathError
                    p = _safe_path(path)
                except _PathError as e:
                    log.write(f"[#febc2e]✗ {e}[/#febc2e]")
                    return False
                except Exception as e:
                    log.write(f"[#febc2e]✗ resolve error: {e}[/#febc2e]")
                    return False
                if p.exists():
                    original = p.read_text(encoding="utf-8", errors="ignore")
                    diff = make_diff(original, content, path)
                    title, body = f"Write to {path}?", f"Modify {len(content)} bytes."
                else:
                    diff = make_diff("", content, path)
                    title, body = f"Create {path}?", f"New file: {len(content.splitlines())} lines."
                return await self.push_screen_wait(ApprovalModal(title, body, diff))

            if tool_name == "edit_file":
                old, new = args.get("old_text", ""), args.get("new_text", "")
                try:
                    from tools.filesystem import _safe_path, _PathError
                    p = _safe_path(path)
                except _PathError as e:
                    log.write(f"[#febc2e]✗ {e}[/#febc2e]")
                    return False
                except Exception as e:
                    log.write(f"[#febc2e]✗ resolve error: {e}[/#febc2e]")
                    return False
                if not p.exists():
                    log.write(f"[#febc2e]✗ File not found: {path}[/#febc2e]")
                    return False
                original = p.read_text(encoding="utf-8", errors="ignore")
                if old not in original:
                    log.write(f"[#febc2e]✗ old_text not found in {path}[/#febc2e]")
                    return False
                updated = original.replace(old, new, 1)
                diff = make_diff(original, updated, path)
                return await self.push_screen_wait(ApprovalModal(
                    f"Edit {path}?",
                    f"Replace {len(old.splitlines())} line(s) with {len(new.splitlines())}.",
                    diff,
                ))

            if tool_name == "run_bash":
                command = args.get("command", "")
                return await self.push_screen_wait(ApprovalModal(
                    "Run shell command?", f"$ {command}", "",
                ))

            return True

        async def on_final(content: str):
            log.write(Panel(
                RichMarkdown(content),
                title="[bold #7b8cde]M.E.E.R.A[/bold #7b8cde]",
                border_style="#7b8cde",
            ))
            save_message(self.session_id, "assistant", content)
            if friday.is_enabled():
                def speak_summary():
                    try:
                        spoken = content[:200].replace('*','').replace('#','').replace('`','').strip()
                        if spoken:
                            self.call_from_thread(self._show_friday_speech, spoken)
                            friday.speak(spoken, blocking=True)
                            self.call_from_thread(self._meera_done)
                    except Exception as e:
                        print(f"FRIDAY error: {e}")
                        try:
                            self.call_from_thread(self._meera_done)
                        except Exception:
                            pass
                threading.Thread(target=speak_summary, daemon=True).start()

        async def on_error(msg: str):
            log.write(f"[#febc2e]✗ LLM error: {msg}[/#febc2e]")

        async def on_parse_failure(raw: str):
            # Route to Agent Log (dim, subtle) instead of Chat (bold, alarming)
            # Users don't need to see every parse retry - it's noise
            try:
                scroll = self.query_one("#activity-scroll", VerticalScroll)
                dim_msg = Static("[dim #febc2e]⟳ parser retry (model output malformed)[/dim #febc2e]")
                self._mount_watcher_item_sync(scroll, dim_msg)
            except Exception:
                pass

        # ── Run the unified runtime ──────────────────────────────────────────
        cbs = RuntimeCallbacks(
            on_llm_start=on_llm_start,
            on_token=on_token,
            on_llm_end=on_llm_end,
            on_thought=on_thought,
            on_tool_start=on_tool_start,
            on_tool_done=on_tool_done,
            on_approve_tool=on_approve_tool,
            on_final=on_final,
            on_error=on_error,
            on_parse_failure=on_parse_failure,
        )

        try:
            await runtime.run_async(user_message, cbs)
        finally:
            # Repopulate FILES panel after any write/edit/create
            try:
                self._populate_tree()
            except Exception:
                pass
            self.agent_busy = False
            self.iteration_count = 0
            self.current_status = "▓ READY"
            self.update_status()

    async def _handle_tool(self, tool_name: str, args: dict, item: ActivityItem) -> str:
        if tool_name == "write_file":
            path = args.get("path", "")
            content = args.get("content", "")

            # Resolve against active workspace, not the Oblivion install dir
            try:
                from tools.filesystem import _safe_path, _PathError
                p = _safe_path(path)
            except _PathError as e:
                return f"Error: {e}"
            except Exception as e:
                return f"Error resolving path {path}: {e}"

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

            # Resolve against active workspace, not the Oblivion install dir
            try:
                from tools.filesystem import _safe_path, _PathError
                p = _safe_path(path)
            except _PathError as e:
                return f"Error: {e}"
            except Exception as e:
                return f"Error resolving path {path}: {e}"

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
        log.write("[#7b8cde]◢ Neural link reset.[/#7b8cde]")
        self.update_status()

    def action_new_session(self) -> None:
        self.session_id = create_session()
        self.agent.reset()
        self._clear_activity()
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        log.write(f"[#7b8cde]◢ New session: {self.session_id}[/#7b8cde]")
        self.update_status()

    def action_clear_chat(self) -> None:
        self.query_one("#chat-log", RichLog).clear()
        self._clear_activity()


    def action_open_history(self) -> None:
        """Ctrl+P — show session history picker overlay."""
        async def _on_pick(session_id):
            if session_id is None:
                return
            await self._load_past_session(session_id)
        self.push_screen(SessionPicker(), _on_pick)

    async def _load_past_session(self, session_id: int) -> None:
        """Replace current conversation with a past session and make it active."""
        from db.store import load_session, get_session_stats
        log = self.query_one("#chat-log", RichLog)

        try:
            history = load_session(session_id)
            stats = get_session_stats(session_id)
        except Exception as e:
            log.write(f"[#febc2e]✗ Failed to load session #{session_id}: {e}[/#febc2e]")
            return

        # Replace agent conversation
        self.agent.conversation = list(history)
        self.session_id = session_id
        self._clear_activity()
        log.clear()

        # Render replay header
        log.write(Panel(
            f"[bold #7b8cde]◆ RESUMED SESSION #{session_id}[/bold #7b8cde]\n\n"
            f"[#9aa0b8]Name:[/#9aa0b8]     {stats['name']}\n"
            f"[#9aa0b8]Messages:[/#9aa0b8] {stats['messages']}\n"
            f"[#9aa0b8]Updated:[/#9aa0b8]  {stats['updated_at']}",
            title="[#febc2e]→ LOADED[/#febc2e]",
            border_style="#7b8cde",
        ))

        # Replay the messages (compact view)
        for msg in history:
            role = msg.get("role", "?")
            text = msg.get("content", "")[:300]
            if role == "user":
                log.write(f"[bold #febc2e]YOU:[/bold #febc2e] {text}")
            elif role == "assistant":
                # Strip if it looks like an OBSERVATION wrapper
                if text.startswith("OBSERVATION"):
                    continue
                log.write(Panel(
                    text,
                    title="[#7b8cde]M.E.E.R.A[/#7b8cde]",
                    border_style="#7b8cde",
                ))
        self.update_status()

    def action_show_help(self) -> None:
        self.run_worker(self.handle_slash("/help"), exclusive=False)

    def _start_wake_word(self) -> bool:
        """Start background wake word listener ("Hey Meera" → record)."""
        try:
            from agent.wake_word import enable_wake_word, is_available
        except ImportError:
            return False

        if not is_available():
            log = self.query_one("#chat-log", RichLog)
            log.write(
                "[#febc2e]⚠  Wake word requires openwakeword.[/#febc2e] "
                "Install: [bold]uv pip install openwakeword[/bold]"
            )
            return False

        def _on_wake_from_thread():
            """Called from wake word thread when "Hey Meera" detected."""
            def _trigger():
                # Natural, conversational wake-word response
                import random, time
                now = time.time()
                last_wake = getattr(self, "_last_wake_time", 0)
                self._last_wake_time = now

                # If woken up again within 30s, use short subtle follow-up
                if now - last_wake < 30.0:
                    short_greetings = ["Yes, boss?", "Listening.", "mm-hmm?", "Go ahead."]
                    self._speak_async(random.choice(short_greetings))
                else:
                    natural_greetings = [
                        "Yes, boss?",
                        "I'm listening, boss.",
                        "Go ahead, boss.",
                        "What can I do for you, boss?",
                        "Listening, boss."
                    ]
                    self._speak_async(random.choice(natural_greetings))
                # Then trigger voice recording (same as Ctrl+T)
                if not self.voice_recording:
                    self.run_worker(self._start_voice_recording(), exclusive=False)
            # Must schedule on main thread (Textual not thread-safe)
            self.call_from_thread(_trigger)

        def _on_wake_error(msg: str):
            def _log():
                try:
                    log = self.query_one("#chat-log", RichLog)
                    log.write(f"[#febc2e]⚠ wake word: {msg}[/#febc2e]")
                except Exception:
                    pass
            self.call_from_thread(_log)

        started = enable_wake_word(
            on_wake=_on_wake_from_thread,
            on_error=_on_wake_error,
        )

        if started:
            log = self.query_one("#chat-log", RichLog)
            log.write(
                "[#67e8f9]🎤 Wake word active — say [bold]'Hey Meera'[/bold] to talk[/#67e8f9]"
            )
        return started

    def _stop_wake_word(self) -> None:
        """Stop background wake word listener."""
        try:
            from agent.wake_word import disable_wake_word
            disable_wake_word()
            log = self.query_one("#chat-log", RichLog)
            log.write("[#7c8399]🎤 Wake word disabled[/#7c8399]")
        except Exception:
            pass



    def _pause_wake_for_record(self) -> bool:
        self._wake_was_on_before_record = False
        try:
            from agent.wake_word import is_wake_word_enabled, disable_wake_word
            self._wake_was_on_before_record = bool(is_wake_word_enabled())
            disable_wake_word()
        except Exception:
            try:
                from agent.wake_word import disable_wake_word
                disable_wake_word()
            except Exception:
                pass
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        import time as _t
        _t.sleep(0.4)
        return bool(getattr(self, "_wake_was_on_before_record", False))


    def _resume_wake_after_record(self) -> None:
        """Restart wake only if it was on before this recording."""
        if not getattr(self, "_wake_was_on_before_record", False):
            return
        self._wake_was_on_before_record = False
        try:
            import time as _t
            _t.sleep(0.4)
            self._start_wake_word()
        except Exception:
            pass


    def action_toggle_voice(self) -> None:
        """Ctrl+T hotkey - start/stop voice recording."""
        if not VOICE_AVAILABLE:
            log = self.query_one("#chat-log", RichLog)
            log.write(
                "[#febc2e]⚠  Voice not installed.[/#febc2e] "
                "Install with: [bold]pip install \"oblivion-agent[voice]\"[/bold]"
            )
            return
        if self.voice_recording:
            # Stop current recording
            self._stop_voice_recording()
        else:
            # Start new recording
            self.run_worker(self._start_voice_recording(), exclusive=False)

    async def _start_voice_recording(self):
        """Ctrl+T / wake -> exclusive mic record -> fast STT."""
        log = self.query_one("#chat-log", RichLog)

        if getattr(self, "voice_recording", False) or getattr(self, "_voice_busy", False):
            log.write("[dim]Already listening...[/dim]")
            return
        self._voice_busy = True

        try:
            self._pause_wake_for_record()
        except Exception:
            pass

        self.voice_recording = True
        self.voice_status = "recording"
        self.voice_stop_event = threading.Event()
        self.current_status = "RECORDING (Ctrl+T to stop)"
        self.update_status()

        log.write(Panel(
            "[bold #febc2e]>>> RECORDING <<<[/bold #febc2e]\n"
            "Speak now... press [bold #7b8cde]Ctrl+T[/bold #7b8cde] again to STOP",
            title="[#febc2e]VOICE INPUT[/#febc2e]",
            border_style="#febc2e",
        ))

        def on_level(rms):
            self.voice_audio_level = rms

        def on_status(s):
            self.voice_status = s

        def record_thread():
            text = ""
            try:
                from agent.voice import VoiceRecorder, transcribe
                recorder = VoiceRecorder(on_level=on_level, on_status=on_status)
                self.voice_recorder = recorder

                def watch_stop():
                    ev = self.voice_stop_event
                    if ev is not None:
                        ev.wait()
                    try:
                        recorder.stop()
                    except Exception:
                        pass
                threading.Thread(target=watch_stop, daemon=True).start()

                audio = recorder.record()

                def _mark_tx():
                    self.voice_recording = False
                    self.current_status = "TRANSCRIBING"
                    try:
                        self.update_status()
                    except Exception:
                        pass
                    try:
                        self.query_one("#chat-log", RichLog).write(
                            "[#9aa0b8]>>> Transcribing audio... <<<[/#9aa0b8]"
                        )
                    except Exception:
                        pass
                try:
                    self.call_from_thread(_mark_tx)
                except Exception:
                    pass

                if audio is not None and len(audio) > 0:
                    text = transcribe(audio) or ""
                else:
                    st = str(getattr(self, "voice_status", "") or "")
                    if st.startswith("error:"):
                        text = "__ERROR__:" + st[6:].strip()
                    else:
                        text = ""
            except Exception as e:
                text = "__ERROR__:" + str(e)

            try:
                self.call_from_thread(self._apply_transcription, text)
            except Exception:
                self._voice_busy = False
                self.voice_recording = False

        threading.Thread(target=record_thread, daemon=True, name="voice-record").start()

    def _stop_voice_recording(self):
        """Stop the current recording (Ctrl+T while recording)."""
        if self.voice_stop_event is not None:
            self.voice_stop_event.set()
        try:
            if getattr(self, "voice_recorder", None) is not None:
                self.voice_recorder.stop()
        except Exception:
            pass
        # UI status flip happens in record_thread when record() returns

    def _on_voice_done(self, text: str):
        """Called when transcription completes. Fills input box."""
        # Schedule UI update on main thread
        self.call_from_thread(self._apply_transcription, text)

    def _show_friday_speech(self, text: str):
        """Pattern A: voice-only. Activates waveform; no chat panel duplicate."""
        try:
            self.meera_speaking = True
            self.update_status()
        except Exception:
            pass

    def _update_env(self, key: str, value: str):
        """Persist a key=value to ~/.oblivion/config.env."""
        from agent.paths import config_env as _cfg
        env_path = _cfg()
        lines = env_path.read_text().splitlines() if env_path.exists() else []
        new_lines = [l for l in lines if not l.startswith(f"{key}=")]
        new_lines.append(f"{key}={value}")
        env_path.write_text("\n".join(new_lines) + "\n")

    def _apply_transcription(self, text: str):
        log = self.query_one("#chat-log", RichLog)
        input_widget = self.query_one("#input-box", Input)

        self.voice_recording = False
        self._voice_busy = False
        self.voice_recorder = None
        self.current_status = "READY"
        self.update_status()
        try:
            self._resume_wake_after_record()
        except Exception:
            pass

        if text.startswith("__ERROR__:"):
            err = text[len("__ERROR__:"):].strip()
            log.write(Panel(
                f"[#febc2e]Voice error: {err}[/#febc2e]\n"
                f"[dim]Tip: /wake off then Ctrl+T[/dim]",
                border_style="#febc2e",
            ))
            return

        if not text.strip():
            log.write("[dim]No speech detected.[/dim]")
            return

        # Auto-submit the transcribed text (recording already stopped on silence)
        clean_text = text.strip()

        log.write(Panel(
            f"[#7b8cde]\"{clean_text}\"[/#7b8cde]",
            title="[#7b8cde]◢ TRANSCRIBED ◣[/#7b8cde]",
            border_style="#7b8cde",
        ))

        # Clear input box and submit immediately
        input_widget.value = ""

        try:
            self.query_one("#slash-suggestions", OptionList).remove_class("visible")
        except Exception:
            pass

        if clean_text.startswith("/"):
            self.run_worker(self.handle_slash(clean_text), exclusive=False)
        else:
            log.write(f"[bold #febc2e]YOU:[/bold #febc2e] {clean_text}")
            log.write("[dim #7b8cde]⯿ M.E.E.R.A is thinking...[/dim #7b8cde]")
            self.current_status = "▓ THINKING"
            self.update_status()
            save_message(self.session_id, "user", clean_text)
            self.agent_busy = True
            self.run_worker(self._run_agent(clean_text), exclusive=True)

    def _clear_activity(self):
        for item in list(self.activity_items):
            try:
                item.remove()
            except Exception:
                pass
        self.activity_items.clear()


def main():
    # ── Subcommand dispatcher ─────────────────────────────────────────────
    # Usage:
    #   oblivion              -> launch TUI (default)
    #   oblivion mcp          -> run as MCP server (stdio)
    #   oblivion init         -> force-run setup wizard
    #   oblivion --version    -> print version
    #   oblivion --help       -> print help
    import sys as _sys

    argv = _sys.argv[1:]
    if argv:
        cmd = argv[0].lower()
        if cmd in ("--version", "-v", "version"):
            try:
                from importlib.metadata import version
                print("oblivion-agent " + version("oblivion-agent"))
            except Exception:
                print("oblivion-agent (dev)")
            return
        if cmd in ("--help", "-h", "help"):
            print("Oblivion - terminal AI coding agent")
            print()
            print("Usage:")
            print("  oblivion              Launch the TUI (default)")
            print("  oblivion demo         60-second guided tour (no API key needed)")
            print("  oblivion mcp          Run as MCP server (for Claude Desktop, etc.)")
            print("  oblivion inspect      Open MCP Inspector in browser (requires npx)")
            print("  oblivion init         Re-run the setup wizard")
            print("  oblivion --version    Print version")
            print()
            print("Config:  ~/.oblivion/config.env")
            print("Docs:    https://github.com/rohit/oblivion-agent")
            return
        if cmd == "mcp":
            from mcp_server.server import main as mcp_main
            mcp_main(argv[1:])
            return
        if cmd == "inspect":
            # Launch official MCP Inspector against our own server
            # (opens browser UI to test all 10 tools interactively)
            import shutil, subprocess, os as _os2
            if not shutil.which("npx"):
                print("ERROR: npx not found on PATH.")
                print()
                print("The MCP Inspector requires Node.js (which ships with npx).")
                print("Install:")
                print("  Linux/WSL:  sudo apt install nodejs npm")
                print("  macOS:      brew install node")
                print("  Windows:    https://nodejs.org/en/download")
                print()
                print("Then re-run: oblivion inspect")
                return
            print("[oblivion] Launching MCP Inspector...")
            print("[oblivion] Your MCP server will be exposed at http://localhost:6274")
            print("[oblivion] Browser will open automatically. Press Ctrl+C to stop.")
            print()
            try:
                subprocess.run(
                    ["npx", "-y", "@modelcontextprotocol/inspector",
                     "oblivion", "mcp"],
                    check=False,
                )
            except KeyboardInterrupt:
                print("\n[oblivion] Inspector stopped.")
            return
        if cmd == "init":
            from agent.setup_wizard import run_wizard
            run_wizard()
            print("\nLaunching Oblivion...\n")
            # fall through to TUI launch

    # ── Default: launch the TUI ───────────────────────────────────────────
    # Mark TUI mode so handlers/tools skip CLI-only Rich output & input prompts
    import os as _os
    _os.environ["OBLIVION_TUI"] = "1"

    # First-run setup wizard + legacy migration + config load
    # Runs ONLY if ~/.oblivion/config.env doesn't exist yet
    try:
        from agent.setup_wizard import maybe_run
        maybe_run()
    except Exception as _e:
        print(f"[Oblivion] Setup wizard skipped: {_e}")

    # Restore last workspace from previous session (if valid).
    # Config loading may set WORKSPACE_DIR initially; this overrides it with the last active dir.
    try:
        from agent.paths import load_last_workspace
        _last_ws = load_last_workspace()
        if _last_ws:
            os.environ["WORKSPACE_DIR"] = _last_ws
    except Exception:
        pass

    # Whisper is now loaded LAZILY on first Ctrl+T press instead of at startup.
    # This shaves ~5-10 seconds off boot time. First voice press has a small
    # one-time delay (~3-5s) while the model loads, then it's cached.
    # Users can opt back into preload with OBLIVION_PRELOAD_VOICE=1.
    import os
    if os.getenv("OBLIVION_PRELOAD_VOICE", "0") == "1" and VOICE_AVAILABLE:
        try:
            print("[Oblivion] Pre-loading Whisper model (one-time)...")
            get_whisper_model()
            print("[Oblivion] Voice ready.")
        except Exception as e:
            print(f"[Oblivion] Voice unavailable: {e}")
            print("[Oblivion] (Continuing without voice - text input still works)")
    elif not VOICE_AVAILABLE:
        print("[Oblivion] Voice not installed (pip install oblivion-agent[voice]). Text mode.")

    app = OblivionApp()
    app.run()


if __name__ == "__main__":
    main()
