"""ui/sim_screen.py - 8085 Simulator Screen v3"""
from __future__ import annotations
from textual.app import ComposeResult
from textual.screen import Screen
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Footer, Button, TextArea, Label, RichLog, Input
from simulator.cpu8085 import CPU8085
from simulator.assembler import Assembler8085

DEFPROG = "ORG 2000H\nMVI A, 05H   ; Load 5\nMVI B, 03H   ; Load 3\nADD B         ; A=A+B\nSTA 3000H    ; Store result\nHLT"

SIM_CSS = """
SimScreen { background: #0d0f14; }
#sim-header { height: 3; background: #13162a; color: #7b8cde; padding: 0 2; }
#sim-main { height: 1fr; }
#sim-code-panel { width: 40%; border: round #7b8cde; padding: 0 1; background: #0b0d13; }
#sim-right { width: 60%; }
#sim-registers { height: 35%; border: round #febc2e; padding: 1; background: #0b0d13; }
#sim-memory { height: 30%; border: round #3e4560; padding: 0 1; background: #0b0d13; }
#sim-output { height: 35%; border: round #1db954; padding: 0 1; background: #0b0d13; }
#sim-controls { height: 3; background: #13162a; padding: 0 1; }
#sim-controls Button { margin: 0 1; min-width: 12; }
#sim-meera-box { height: 4; border: round #7b8cde; background: #0b0d13; padding: 0 1; }
#sim-meera-input { height: 3; border: round #3e4560; background: #0d0f14; color: #7b8cde; }
#sim-code { height: 1fr; }
"""

class SimScreen(Screen):
    CSS = SIM_CSS
    BINDINGS = [Binding("escape", "go_back", "Back", priority=True)]

    def __init__(self):
        super().__init__()
        self.cpu = CPU8085()
        self.asm = Assembler8085()

    def compose(self) -> ComposeResult:
        yield Static("[bold #7b8cde]8085 SIMULATOR[/bold #7b8cde]  [dim]Use buttons below | Ask Meera for code[/dim]", id="sim-header")
        with Horizontal(id="sim-main"):
            with Vertical(id="sim-code-panel"):
                yield Label("[bold #7b8cde]ASSEMBLY CODE[/bold #7b8cde]")
                yield TextArea(DEFPROG, id="sim-code")
            with Vertical(id="sim-right"):
                with Vertical(id="sim-registers"):
                    yield Label("[bold #febc2e]REGISTERS[/bold #febc2e]")
                    yield Static(self._fmt_regs(), id="sim-reg-display")
                with Vertical(id="sim-memory"):
                    yield Label("[bold #3e4560]MEMORY[/bold #3e4560]")
                    yield Static(self._fmt_mem(), id="sim-mem-display")
                with Vertical(id="sim-output"):
                    yield Label("[bold #1db954]EXECUTION LOG[/bold #1db954]")
                    yield RichLog(id="sim-log", wrap=True, markup=True)
        with Horizontal(id="sim-controls"):
            yield Button("Load", id="btn-load", variant="primary")
            yield Button("Step", id="btn-step", variant="primary")
            yield Button("Run", id="btn-run", variant="success")
            yield Button("Reset", id="btn-reset", variant="warning")
            yield Button("Back", id="btn-back", variant="error")
        with Horizontal(id="sim-meera-box"):
            yield Label("[bold #7b8cde]Meera:[/bold #7b8cde] ")
            yield Input(placeholder="Ask Meera to write assembly code...", id="sim-meera-input")
        yield Footer()

    def _fmt_regs(self):
        c = self.cpu
        s = "HALTED" if c.halted else "READY" if c.instruction_count == 0 else "RUNNING"
        return (f"A={c.A:02X}  B={c.B:02X}  C={c.C:02X}  D={c.D:02X}  E={c.E:02X}\n"
                f"H={c.H:02X}  L={c.L:02X}  SP={c.SP:04X}  PC={c.PC:04X}\n\n"
                f"FLAGS: S={c.S} Z={c.Z} AC={c.AC} P={c.P} CY={c.CY}\n\n"
                f"Instructions: {c.instruction_count}  Status: {s}")

    def _fmt_mem(self, start=0x2000, length=64):
        out = []
        for i in range(0, length, 8):
            a = (start + i) & 0xFFFF
            hx = " ".join(f"{self.cpu.memory[a+j]:02X}" for j in range(min(8, length-i)))
            mark = ">" if a <= self.cpu.PC < a + 8 else " "
            out.append(f"{mark}{a:04X}: {hx}")
        return "\n".join(out)

    def _refresh(self):
        try:
            self.query_one("#sim-reg-display", Static).update(self._fmt_regs())
            self.query_one("#sim-mem-display", Static).update(self._fmt_mem())
        except Exception: pass

    def _log(self, msg):
        try: self.query_one("#sim-log", RichLog).write(msg)
        except Exception: pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        b = event.button.id
        if b == "btn-load": self._do_load()
        elif b == "btn-step": self._do_step()
        elif b == "btn-run": self._do_run()
        elif b == "btn-reset": self._do_reset()
        elif b == "btn-back": self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "sim-meera-input": return
        msg = event.value.strip()
        if not msg: return
        event.input.value = ""
        self._log(f"[bold #febc2e]YOU:[/bold #febc2e] {msg}")
        self._log("[dim]Meera is thinking...[/dim]")
        import threading
        def _ask():
            try:
                from agent.paths import load_config_env
                load_config_env()
                from agent.llm import LLMClient
                client = LLMClient()
                prompt = ("You are an 8085 assembly expert. Write ONLY valid 8085 assembly. "
                    "Start with ORG 2000H. Use standard mnemonics. Add comments. End with HLT. "
                    "Output ONLY the assembly code, no explanation.\n\nRequest: " + msg)
                resp = client.chat_stream([{"role": "user", "content": prompt}], on_token=None)
                code = resp.strip()
                # Strip markdown fences if present
                clines = code.split("\n")
                clines = [l for l in clines if not l.strip().startswith("``")]
                code = "\n".join(clines)
                def _upd():
                    try:
                        ed = self.query_one("#sim-code", TextArea)
                        ed.clear()
                        ed.insert(code)
                        self._log("[bold #7b8cde]MEERA:[/bold #7b8cde] Code written. Press Load.")
                    except Exception as e:
                        self._log(f"[#ff5f57]Editor error: {e}[/#ff5f57]")
                self.app.call_from_thread(_upd)
            except Exception as e:
                def _e(): self._log(f"[#ff5f57]Meera error: {e}[/#ff5f57]")
                self.app.call_from_thread(_e)
        threading.Thread(target=_ask, daemon=True).start()

    def _do_load(self):
        self._log("[dim]Loading...[/dim]")
        try:
            editor = self.query_one("#sim-code", TextArea)
            source = editor.text
            self._log(f"[dim]Editor has {len(source)} chars, {source.count(chr(10))+1} lines[/dim]")
        except Exception as e:
            self._log(f"[#ff5f57]Cannot read editor: {e}[/#ff5f57]")
            return
        if not source.strip():
            self._log("[#ff5f57]Editor is empty. Write or paste assembly code first.[/#ff5f57]")
            return
        # Show first few lines of what we're assembling
        preview = source.strip().split(chr(10))[:3]
        for p in preview:
            self._log(f"[dim]  {p.strip()}[/dim]")
        self.cpu.reset()
        r = self.asm.assemble(source)
        if not r.success:
            for e in r.errors:
                self._log(f"[#ff5f57]ASM ERROR: {e}[/#ff5f57]")
            return
        if not r.bytes:
            self._log("[#ff5f57]Assembler produced 0 bytes. Check your code.[/#ff5f57]")
            return
        self.cpu.load_at(r.origin, r.bytes)
        self.cpu.PC = r.origin
        bstr = " ".join(f"{b:02X}" for b in r.bytes)
        self._log(f"[bold #1db954]Loaded {len(r.bytes)} bytes at {r.origin:04X}H[/bold #1db954]")
        self._log(f"[dim]Machine code: {bstr}[/dim]")
        if r.labels:
            lstr = ", ".join(f"{k}={v:04X}H" for k, v in r.labels.items())
            self._log(f"[dim]Labels: {lstr}[/dim]")
        self._log(f"[#1db954]PC set to {r.origin:04X}H. Ready to Step or Run.[/#1db954]")
        self._refresh()

    def _do_step(self):
        if self.cpu.PC == 0 and self.cpu.instruction_count == 0:
            self._log("[#febc2e]No program loaded. Click Load first.[/#febc2e]")
            return
        if self.cpu.halted:
            self._log("[#febc2e]CPU halted. Press Reset.[/#febc2e]"); return
        state = self.cpu.step()
        self._log(f"[#1db954]{state.PC-1:04X}H:[/#1db954] [bold]{state.instruction}[/bold]  [dim]{state.description}[/dim]")
        self._refresh()

    def _do_run(self):
        if self.cpu.PC == 0 and self.cpu.instruction_count == 0:
            self._log("[#febc2e]No program loaded. Click Load first.[/#febc2e]")
            return
        if self.cpu.halted:
            self._log("[#febc2e]CPU halted. Press Reset.[/#febc2e]"); return
        states = self.cpu.run(max_steps=500)
        for s in states:
            self._log(f"[#1db954]{s.PC-1:04X}H:[/#1db954] {s.instruction}  [dim]{s.description}[/dim]")
        self._log(f"[bold]Executed {len(states)} instructions.[/bold]")
        self._refresh()

    def _do_reset(self):
        self.cpu.reset()
        self._log("[#febc2e]CPU reset.[/#febc2e]")
        self._refresh()

    def action_go_back(self): self.app.pop_screen()