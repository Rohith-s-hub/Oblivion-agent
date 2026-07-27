"""ui/sim_screen.py - 8085 Simulator v4 (Professional Edition)"""
from __future__ import annotations
from textual.app import ComposeResult
from textual.screen import Screen
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Footer, Button, TextArea, Label, RichLog, Input
from simulator.cpu8085 import CPU8085, CPUState
from simulator.assembler import Assembler8085

SIM_CSS = """
SimScreen {
    background: #0a0a0f;
    layout: vertical;
    overflow: hidden;
}

#sim-header {
    height: 2;
    background: #0f0a14;
    color: #7b8cde;
    padding: 0 2;
    overflow: hidden;
}

#sim-main {
    height: 1fr;
    overflow: hidden;
}

#sim-left {
    width: 35%;
    height: 100%;
    overflow: hidden;
}

#sim-code-panel {
    height: 1fr;
    border: tall #1e2130;
    padding: 0 1;
    background: #0d0f14;
    overflow: hidden;
}

#sim-right {
    width: 65%;
    height: 100%;
    overflow: hidden;
}

#sim-reg-row {
    height: 9;
    overflow: hidden;
}

#sim-registers {
    width: 50%;
    height: 100%;
    border: tall #febc2e;
    padding: 0 1;
    background: #0d0f14;
    overflow: hidden;
}

#sim-flags-io {
    width: 50%;
    height: 100%;
    border: tall #ff006e;
    padding: 0 1;
    background: #0d0f14;
    overflow: hidden;
}

#sim-memory {
    height: 11;
    border: tall #00d9ff;
    padding: 0 1;
    background: #0d0f14;
    overflow: hidden;
}

#sim-output {
    height: 1fr;
    border: tall #00ff9f;
    padding: 0 1;
    background: #0d0f14;
    overflow-y: auto;
}

#sim-bottom {
    height: auto;
    max-height: 6;
    overflow: hidden;
}

#sim-controls {
    height: 3;
    background: #0f0a14;
    padding: 0 1;
    overflow: hidden;
}

#sim-controls Button {
    margin: 0 1;
    min-width: 8;
}

#sim-meera-box {
    height: 3;
    background: #0f0a14;
    padding: 0 1;
    overflow: hidden;
}

#sim-meera-input {
    height: 3;
    border: round #3e4560;
    background: #0a0a0f;
    color: #7b8cde;
}

#sim-code {
    height: 1fr;
}
"""

DEFPROG = "ORG 2000H\n; Add two numbers\nMVI A, 05H   ; Load 5\nMVI B, 03H   ; Load 3\nADD B         ; A=A+B\nSTA 3000H    ; Store result\nHLT           ; Stop"

class SimScreen(Screen):
    CSS = SIM_CSS
    BINDINGS = [Binding("escape", "go_back", "Back", priority=True)]

    def __init__(self):
        super().__init__()
        self.cpu = CPU8085()
        self.asm = Assembler8085()
        self.prev_state = None
        self.mem_start = 0x2000
        self.step_count = 0

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold #00ff9f]OBLIVION[/bold #00ff9f] [bold #7b8cde]8085 SIMULATOR[/bold #7b8cde]"
            "  [dim]| Click buttons below | Ask Meera for code[/dim]",
            id="sim-header",
        )
        with Horizontal(id="sim-main"):
            with Vertical(id="sim-left"):
                with Vertical(id="sim-code-panel"):
                    yield Label("[bold #7b8cde]ASSEMBLY CODE[/bold #7b8cde]")
                    yield TextArea(DEFPROG, id="sim-code")
            with Vertical(id="sim-right"):
                with Horizontal(id="sim-reg-row"):
                    with Vertical(id="sim-registers"):
                        yield Label("[bold #febc2e]REGISTERS[/bold #febc2e]")
                        yield Static(self._fmt_regs(), id="sim-reg-display")
                    with Vertical(id="sim-flags-io"):
                        yield Label("[bold #ff006e]FLAGS[/bold #ff006e]")
                        yield Static(self._fmt_flags(), id="sim-flags-display")
                with Vertical(id="sim-memory"):
                    yield Label("[bold #00d9ff]MEMORY[/bold #00d9ff]")
                    yield Static(self._fmt_mem(), id="sim-mem-display")
                with Vertical(id="sim-output"):
                    yield Label("[bold #00ff9f]EXECUTION TRACE[/bold #00ff9f]")
                    yield RichLog(id="sim-log", wrap=True, markup=True)
        with Vertical(id="sim-bottom"):
            with Horizontal(id="sim-controls"):
                yield Button("Load", id="btn-load", variant="primary")
                yield Button("Step", id="btn-step", variant="primary")
                yield Button("Run", id="btn-run", variant="success")
                yield Button("Reset", id="btn-reset", variant="warning")
                yield Button("Clear", id="btn-clear", variant="default")
                yield Button("Back", id="btn-back", variant="error")
            with Horizontal(id="sim-meera-box"):
                yield Label("[bold #00ff9f]MEERA:[/bold #00ff9f] ")
                yield Input(placeholder="Ask Meera to write assembly code...", id="sim-meera-input")
        yield Footer()

    def _fmt_regs(self):
        c = self.cpu
        p = self.prev_state
        def hl(name, val, old_val=None):
            color = "#00ff9f" if old_val is not None and val != old_val else "#e8e8e8"
            return f"[bold #febc2e]{name}[/bold #febc2e] [{color}]{val:02X}[/{color}]"
        def hl16(name, val, old_val=None):
            color = "#00ff9f" if old_val is not None and val != old_val else "#e8e8e8"
            return f"[bold #9aa0b8]{name}[/bold #9aa0b8] [{color}]{val:04X}[/{color}]"
        pa = p.A if p else None
        pb = p.B if p else None
        pc_ = p.C if p else None
        pd = p.D if p else None
        pe = p.E if p else None
        ph = p.H if p else None
        pl = p.L if p else None
        bc = (c.B << 8) | c.C
        de = (c.D << 8) | c.E
        hl_val = (c.H << 8) | c.L
        return (
            f"  {hl('A', c.A, pa)}\n\n"
            f"  {hl('B', c.B, pb)}  {hl('C', c.C, pc_)}  [dim]BC={bc:04X}[/dim]\n"
            f"  {hl('D', c.D, pd)}  {hl('E', c.E, pe)}  [dim]DE={de:04X}[/dim]\n"
            f"  {hl('H', c.H, ph)}  {hl('L', c.L, pl)}  [dim]HL={hl_val:04X}[/dim]\n\n"
            f"  {hl16('SP', c.SP)}  {hl16('PC', c.PC)}"
        )

    def _fmt_flags(self):
        c = self.cpu
        s = "[bold #ff006e]HALTED[/bold #ff006e]" if c.halted else "[bold #00ff9f]READY[/bold #00ff9f]" if c.instruction_count == 0 else "[bold #febc2e]RUNNING[/bold #febc2e]"
        flag_byte = (c.S << 7) | (c.Z << 6) | (c.AC << 4) | (c.P << 2) | (1 << 1) | c.CY
        fb = f"{flag_byte:08b}"
        def fc(name, val):
            color = "#00ff9f" if val else "#3e4560"
            return f"[{color}]{name}={val}[/{color}]"
        return (
            f"  {fc('S', c.S)}  {fc('Z', c.Z)}  {fc('AC', c.AC)}\n"
            f"  {fc('P', c.P)}  {fc('CY', c.CY)}\n\n"
            f"  [dim]Flag byte:[/dim] [#9aa0b8]{fb}[/#9aa0b8]\n\n"
            f"  Status: {s}\n"
            f"  [dim]Steps: {c.instruction_count}[/dim]"
        )

    def _fmt_mem(self, start=None, length=64):
        if start is None: start = self.mem_start
        out = []
        out.append("[dim]ADDR  00 01 02 03 04 05 06 07  ASCII[/dim]")
        for i in range(0, length, 8):
            a = (start + i) & 0xFFFF
            hexparts = []
            asciiparts = []
            for j in range(min(8, length - i)):
                val = self.cpu.memory[a + j]
                is_pc = (a + j) == self.cpu.PC
                if val != 0:
                    hexparts.append(f"[#00d9ff]{val:02X}[/#00d9ff]")
                elif is_pc:
                    hexparts.append(f"[bold #00ff9f]{val:02X}[/bold #00ff9f]")
                else:
                    hexparts.append(f"[#3e4560]{val:02X}[/#3e4560]")
                ch = chr(val) if 32 <= val < 127 else "."
                asciiparts.append(ch)
            hx = " ".join(hexparts)
            asc = "".join(asciiparts)
            mark = "[bold #00ff9f]>[/bold #00ff9f]" if a <= self.cpu.PC < a + 8 else " "
            out.append(f"{mark}[#3e4560]{a:04X}[/#3e4560]: {hx}  [dim]{asc}[/dim]")
        return "\n".join(out)

    def _refresh(self):
        try:
            self.query_one("#sim-reg-display", Static).update(self._fmt_regs())
            self.query_one("#sim-flags-display", Static).update(self._fmt_flags())
            self.query_one("#sim-mem-display", Static).update(self._fmt_mem())
            pass  # stack panel removed for cleaner layout
        except Exception as e: self.log(f"REFRESH ERROR: {e}")

    def _log(self, msg):
        try: self.query_one("#sim-log", RichLog).write(msg)
        except Exception as e: self.log(f"REFRESH ERROR: {e}")

    def _trace_step(self, state):
        self.step_count += 1
        changes = []
        if self.prev_state:
            p = self.prev_state
            if state.A != p.A: changes.append(f"A:{p.A:02X}\u2192{state.A:02X}")
            if state.B != p.B: changes.append(f"B:{p.B:02X}\u2192{state.B:02X}")
            if state.C != p.C: changes.append(f"C:{p.C:02X}\u2192{state.C:02X}")
            if state.D != p.D: changes.append(f"D:{p.D:02X}\u2192{state.D:02X}")
            if state.E != p.E: changes.append(f"E:{p.E:02X}\u2192{state.E:02X}")
            if state.H != p.H: changes.append(f"H:{p.H:02X}\u2192{state.H:02X}")
            if state.L != p.L: changes.append(f"L:{p.L:02X}\u2192{state.L:02X}")
        ch_str = "  ".join(changes) if changes else ""
        self._log(
            f"[dim]#{self.step_count:>3}[/dim] "
            f"[#00d9ff]{state.PC-1:04X}H[/#00d9ff] "
            f"[bold]{state.instruction:<18}[/bold] "
            f"[#00ff9f]{ch_str}[/#00ff9f]"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        b = event.button.id
        if b == "btn-load": self._do_load()
        elif b == "btn-step": self._do_step()
        elif b == "btn-run": self._do_run()
        elif b == "btn-reset": self._do_reset()
        elif b == "btn-clear":
            try: self.query_one("#sim-log", RichLog).clear()
            except Exception as e: self.log(f"REFRESH ERROR: {e}")
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
                    "Start with ORG 2000H. Use standard mnemonics. Add ; comments. End with HLT. "
                    "Output ONLY the assembly code.\n\nRequest: " + msg)
                resp = client.chat_stream([{"role": "user", "content": prompt}], on_token=None)
                code = resp.strip()
                clines = code.split("\n")
                clines = [l for l in clines if not l.strip().startswith("``")]
                code = "\n".join(clines)
                def _upd():
                    try:
                        ed = self.query_one("#sim-code", TextArea)
                        ed.clear()
                        ed.insert(code)
                        self._log("[bold #00ff9f]MEERA:[/bold #00ff9f] Code written to editor. Click Load.")
                    except Exception as e:
                        self._log(f"[#ff006e]Editor error: {e}[/#ff006e]")
                self.app.call_from_thread(_upd)
            except Exception as e:
                def _e(): self._log(f"[#ff006e]Meera error: {e}[/#ff006e]")
                self.app.call_from_thread(_e)
        threading.Thread(target=_ask, daemon=True).start()

    def _do_load(self):
        self._log("[dim]Assembling...[/dim]")
        try: source = self.query_one("#sim-code", TextArea).text
        except Exception:
            self._log("[#ff006e]Cannot read editor.[/#ff006e]"); return
        if not source.strip():
            self._log("[#ff006e]Editor empty.[/#ff006e]"); return
        self.cpu.reset()
        self.prev_state = None
        self.step_count = 0
        r = self.asm.assemble(source)
        if not r.success:
            for e in r.errors: self._log(f"[#ff006e]ERROR: {e}[/#ff006e]")
            return
        if not r.bytes:
            self._log("[#ff006e]0 bytes produced.[/#ff006e]"); return
        self.cpu.load_at(r.origin, r.bytes)
        self.cpu.PC = r.origin
        self.mem_start = r.origin
        bstr = " ".join(f"{b:02X}" for b in r.bytes)
        self._log(f"[bold #00ff9f]\u2713 Loaded {len(r.bytes)} bytes at {r.origin:04X}H[/bold #00ff9f]")
        self._log(f"[dim]Code: {bstr}[/dim]")
        if r.labels:
            lstr = ", ".join(f"{k}={v:04X}H" for k, v in r.labels.items())
            self._log(f"[dim]Labels: {lstr}[/dim]")
        self._log(f"[#00ff9f]Ready. Click Step or Run.[/#00ff9f]")
        self._refresh()

    def _do_step(self):
        if self.cpu.PC == 0 and self.cpu.instruction_count == 0:
            self._log("[#febc2e]Click Load first.[/#febc2e]"); return
        if self.cpu.halted:
            self._log("[#febc2e]CPU halted. Click Reset.[/#febc2e]"); return
        self.prev_state = self.cpu.snapshot()
        state = self.cpu.step()
        self._trace_step(state)
        self._refresh()

    def _do_run(self):
        if self.cpu.PC == 0 and self.cpu.instruction_count == 0:
            self._log("[#febc2e]Click Load first.[/#febc2e]"); return
        if self.cpu.halted:
            self._log("[#febc2e]CPU halted. Click Reset.[/#febc2e]"); return
        count = 0
        while not self.cpu.halted and count < 500:
            self.prev_state = self.cpu.snapshot()
            state = self.cpu.step()
            self._trace_step(state)
            count += 1
        self._log(f"[bold]Executed {count} instructions.[/bold]")
        self._refresh()

    def _do_reset(self):
        self.cpu.reset()
        self.prev_state = None
        self.step_count = 0
        self._log("[#febc2e]\u21bb CPU reset to initial state.[/#febc2e]")
        self._refresh()

    def action_go_back(self): self.app.pop_screen()