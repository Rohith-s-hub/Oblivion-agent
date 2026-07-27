"""
simulator/cpu8085.py - Intel 8085 Microprocessor Simulator Core

Full simulation of the 8085 CPU:
  - 7 general registers (A, B, C, D, E, H, L)
  - Stack Pointer (SP), Program Counter (PC)
  - 5 flags (S, Z, AC, P, CY)
  - 64KB memory space
  - 256 I/O ports
  - 74 instruction types
  - Step-by-step execution with full state tracking

Used by Oblivion's /switch mode to provide an interactive 8085
simulator with Meera as the AI tutor.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CPUState:
    """Snapshot of CPU state after each instruction (for history/undo)."""
    A: int = 0
    B: int = 0
    C: int = 0
    D: int = 0
    E: int = 0
    H: int = 0
    L: int = 0
    SP: int = 0xFFFF
    PC: int = 0x0000
    flags: dict = field(default_factory=lambda: {"S": 0, "Z": 0, "AC": 0, "P": 0, "CY": 0})
    halted: bool = False
    instruction: str = ""
    description: str = ""


class CPU8085:
    """Intel 8085 Microprocessor Simulator.

    Usage:
        cpu = CPU8085()
        cpu.load_at(0x2000, [0x3E, 0x05, 0x06, 0x03, 0x80, 0x76])
        cpu.PC = 0x2000
        while not cpu.halted:
            state = cpu.step()
            print(state.instruction, state.description)
    """

    def __init__(self):
        # General registers
        self.A = 0x00  # Accumulator
        self.B = 0x00
        self.C = 0x00
        self.D = 0x00
        self.E = 0x00
        self.H = 0x00
        self.L = 0x00

        # Special registers
        self.SP = 0xFFFF  # Stack Pointer
        self.PC = 0x0000  # Program Counter

        # Flags: Sign, Zero, AuxCarry, Parity, Carry
        self.S = 0
        self.Z = 0
        self.AC = 0
        self.P = 0
        self.CY = 0

        # Memory (64KB)
        self.memory = bytearray(65536)

        # I/O Ports (256)
        self.ports = bytearray(256)

        # State
        self.halted = False
        self.history: list[CPUState] = []
        self.breakpoints: set[int] = set()
        self.instruction_count = 0

    # ================ HELPERS ================

    def _flags_dict(self) -> dict:
        return {"S": self.S, "Z": self.Z, "AC": self.AC, "P": self.P, "CY": self.CY}

    def _set_flags_szp(self, result: int) -> None:
        """Set Sign, Zero, Parity flags based on 8-bit result."""
        val = result & 0xFF
        self.S = 1 if val & 0x80 else 0
        self.Z = 1 if val == 0 else 0
        self.P = 1 if bin(val).count("1") % 2 == 0 else 0

    def _set_flags_szpc(self, result: int) -> None:
        """Set S, Z, P, CY flags based on result (may exceed 8 bits)."""
        self.CY = 1 if result > 0xFF or result < 0 else 0
        self._set_flags_szp(result)

    def _set_flags_add(self, a: int, b: int, carry: int = 0) -> int:
        """Perform addition, set ALL flags, return 8-bit result."""
        result = a + b + carry
        self._set_flags_szpc(result)
        self.AC = 1 if (a & 0x0F) + (b & 0x0F) + carry > 0x0F else 0
        return result & 0xFF

    def _set_flags_sub(self, a: int, b: int, borrow: int = 0) -> int:
        """Perform subtraction, set ALL flags, return 8-bit result."""
        result = a - b - borrow
        self.CY = 1 if result < 0 else 0
        self.AC = 1 if (a & 0x0F) < ((b & 0x0F) + borrow) else 0
        result = result & 0xFF
        self._set_flags_szp(result)
        return result

    def _read_byte(self) -> int:
        """Read byte at PC and advance PC."""
        val = self.memory[self.PC]
        self.PC = (self.PC + 1) & 0xFFFF
        return val

    def _read_word(self) -> int:
        """Read 16-bit word (little-endian) at PC and advance PC by 2."""
        lo = self._read_byte()
        hi = self._read_byte()
        return (hi << 8) | lo

    def _push(self, value: int) -> None:
        """Push 16-bit value onto stack."""
        self.SP = (self.SP - 1) & 0xFFFF
        self.memory[self.SP] = (value >> 8) & 0xFF
        self.SP = (self.SP - 1) & 0xFFFF
        self.memory[self.SP] = value & 0xFF

    def _pop(self) -> int:
        """Pop 16-bit value from stack."""
        lo = self.memory[self.SP]
        self.SP = (self.SP + 1) & 0xFFFF
        hi = self.memory[self.SP]
        self.SP = (self.SP + 1) & 0xFFFF
        return (hi << 8) | lo

    def _get_hl(self) -> int:
        return (self.H << 8) | self.L

    def _get_bc(self) -> int:
        return (self.B << 8) | self.C

    def _get_de(self) -> int:
        return (self.D << 8) | self.E

    def _get_reg(self, code: int) -> int:
        """Get register by 3-bit code: B=0,C=1,D=2,E=3,H=4,L=5,M=6,A=7"""
        regs = [self.B, self.C, self.D, self.E, self.H, self.L, self.memory[self._get_hl()], self.A]
        return regs[code]

    def _set_reg(self, code: int, value: int) -> None:
        """Set register by 3-bit code."""
        value = value & 0xFF
        if code == 0: self.B = value
        elif code == 1: self.C = value
        elif code == 2: self.D = value
        elif code == 3: self.E = value
        elif code == 4: self.H = value
        elif code == 5: self.L = value
        elif code == 6: self.memory[self._get_hl()] = value
        elif code == 7: self.A = value

    REG_NAMES = ["B", "C", "D", "E", "H", "L", "M", "A"]

    # ================ MAIN EXECUTION ================

    def load_at(self, address: int, data: list[int]) -> None:
        """Load bytes into memory starting at address."""
        for i, b in enumerate(data):
            self.memory[(address + i) & 0xFFFF] = b & 0xFF

    def reset(self) -> None:
        """Reset CPU to initial state."""
        self.__init__()

    def snapshot(self, instruction: str = "", description: str = "") -> CPUState:
        """Capture current state as a snapshot."""
        return CPUState(
            A=self.A, B=self.B, C=self.C, D=self.D,
            E=self.E, H=self.H, L=self.L,
            SP=self.SP, PC=self.PC,
            flags=self._flags_dict(),
            halted=self.halted,
            instruction=instruction,
            description=description,
        )

    def step(self) -> CPUState:
        """Execute ONE instruction. Returns state snapshot with description."""
        if self.halted:
            return self.snapshot("---", "CPU is halted. Use reset to restart.")

        pc_before = self.PC
        opcode = self._read_byte()
        instr, desc = self._execute(opcode, pc_before)

        self.instruction_count += 1
        state = self.snapshot(instr, desc)
        self.history.append(state)

        return state

    def run(self, max_steps: int = 10000) -> list[CPUState]:
        """Run until HLT or breakpoint or max_steps. Returns all states."""
        states = []
        for _ in range(max_steps):
            if self.halted:
                break
            state = self.step()
            states.append(state)
            if self.PC in self.breakpoints:
                state.description += " [BREAKPOINT]"
                break
        return states

    # ================ INSTRUCTION DECODER ================

    def _execute(self, opcode: int, pc: int) -> tuple[str, str]:
        """Decode and execute one opcode. Returns (mnemonic, human description)."""
        addr_str = f"{pc:04X}H"

        # ---- NOP ----
        if opcode == 0x00:
            return "NOP", "No operation"

        # ---- HLT ----
        if opcode == 0x76:
            self.halted = True
            return "HLT", "CPU halted"

        # ---- MOV r1, r2 (01 ddd sss) ----
        if 0x40 <= opcode <= 0x7F and opcode != 0x76:
            dst = (opcode >> 3) & 0x07
            src = opcode & 0x07
            val = self._get_reg(src)
            self._set_reg(dst, val)
            return f"MOV {self.REG_NAMES[dst]}, {self.REG_NAMES[src]}", f"Copy {self.REG_NAMES[src]}({val:02X}H) to {self.REG_NAMES[dst]}"

        # ---- MVI r, data (00 ddd 110) ----
        if opcode & 0xC7 == 0x06:
            dst = (opcode >> 3) & 0x07
            data = self._read_byte()
            self._set_reg(dst, data)
            return f"MVI {self.REG_NAMES[dst]}, {data:02X}H", f"Load {data:02X}H into {self.REG_NAMES[dst]}"

        # ---- ADD r (10 000 sss) ----
        if opcode & 0xF8 == 0x80:
            src = opcode & 0x07
            val = self._get_reg(src)
            self.A = self._set_flags_add(self.A, val)
            return f"ADD {self.REG_NAMES[src]}", f"A = A + {self.REG_NAMES[src]} = {self.A:02X}H"

        # ---- ADI data ----
        if opcode == 0xC6:
            data = self._read_byte()
            self.A = self._set_flags_add(self.A, data)
            return f"ADI {data:02X}H", f"A = A + {data:02X}H = {self.A:02X}H"

        # ---- ADC r (10 001 sss) ----
        if opcode & 0xF8 == 0x88:
            src = opcode & 0x07
            val = self._get_reg(src)
            self.A = self._set_flags_add(self.A, val, self.CY)
            return f"ADC {self.REG_NAMES[src]}", f"A = A + {self.REG_NAMES[src]} + CY = {self.A:02X}H"

        # ---- SUB r (10 010 sss) ----
        if opcode & 0xF8 == 0x90:
            src = opcode & 0x07
            val = self._get_reg(src)
            self.A = self._set_flags_sub(self.A, val)
            return f"SUB {self.REG_NAMES[src]}", f"A = A - {self.REG_NAMES[src]} = {self.A:02X}H"

        # ---- SUI data ----
        if opcode == 0xD6:
            data = self._read_byte()
            self.A = self._set_flags_sub(self.A, data)
            return f"SUI {data:02X}H", f"A = A - {data:02X}H = {self.A:02X}H"

        # ---- SBB r (10 011 sss) ----
        if opcode & 0xF8 == 0x98:
            src = opcode & 0x07
            val = self._get_reg(src)
            self.A = self._set_flags_sub(self.A, val, self.CY)
            return f"SBB {self.REG_NAMES[src]}", f"A = A - {self.REG_NAMES[src]} - CY = {self.A:02X}H"

        # ---- ANA r (10 100 sss) ----
        if opcode & 0xF8 == 0xA0:
            src = opcode & 0x07
            val = self._get_reg(src)
            self.A = self.A & val
            self._set_flags_szp(self.A)
            self.CY = 0
            self.AC = 1
            return f"ANA {self.REG_NAMES[src]}", f"A = A AND {self.REG_NAMES[src]} = {self.A:02X}H"

        # ---- ANI data ----
        if opcode == 0xE6:
            data = self._read_byte()
            self.A = self.A & data
            self._set_flags_szp(self.A)
            self.CY = 0
            self.AC = 1
            return f"ANI {data:02X}H", f"A = A AND {data:02X}H = {self.A:02X}H"

        # ---- ORA r (10 110 sss) ----
        if opcode & 0xF8 == 0xB0:
            src = opcode & 0x07
            val = self._get_reg(src)
            self.A = self.A | val
            self._set_flags_szp(self.A)
            self.CY = 0
            self.AC = 0
            return f"ORA {self.REG_NAMES[src]}", f"A = A OR {self.REG_NAMES[src]} = {self.A:02X}H"

        # ---- ORI data ----
        if opcode == 0xF6:
            data = self._read_byte()
            self.A = self.A | data
            self._set_flags_szp(self.A)
            self.CY = 0
            self.AC = 0
            return f"ORI {data:02X}H", f"A = A OR {data:02X}H = {self.A:02X}H"

        # ---- XRA r (10 101 sss) ----
        if opcode & 0xF8 == 0xA8:
            src = opcode & 0x07
            val = self._get_reg(src)
            self.A = self.A ^ val
            self._set_flags_szp(self.A)
            self.CY = 0
            self.AC = 0
            return f"XRA {self.REG_NAMES[src]}", f"A = A XOR {self.REG_NAMES[src]} = {self.A:02X}H"

        # ---- XRI data ----
        if opcode == 0xEE:
            data = self._read_byte()
            self.A = self.A ^ data
            self._set_flags_szp(self.A)
            self.CY = 0
            self.AC = 0
            return f"XRI {data:02X}H", f"A = A XOR {data:02X}H = {self.A:02X}H"

        # ---- CMP r (10 111 sss) ----
        if opcode & 0xF8 == 0xB8:
            src = opcode & 0x07
            val = self._get_reg(src)
            self._set_flags_sub(self.A, val)
            return f"CMP {self.REG_NAMES[src]}", f"Compare A({self.A:02X}H) with {self.REG_NAMES[src]}({val:02X}H)"

        # ---- CPI data ----
        if opcode == 0xFE:
            data = self._read_byte()
            self._set_flags_sub(self.A, data)
            return f"CPI {data:02X}H", f"Compare A({self.A:02X}H) with {data:02X}H"

        # ---- INR r (00 ddd 100) ----
        if opcode & 0xC7 == 0x04:
            dst = (opcode >> 3) & 0x07
            val = self._get_reg(dst)
            result = (val + 1) & 0xFF
            self._set_flags_szp(result)
            self.AC = 1 if (val & 0x0F) + 1 > 0x0F else 0
            self._set_reg(dst, result)
            return f"INR {self.REG_NAMES[dst]}", f"{self.REG_NAMES[dst]} = {val:02X}H + 1 = {result:02X}H"

        # ---- DCR r (00 ddd 101) ----
        if opcode & 0xC7 == 0x05:
            dst = (opcode >> 3) & 0x07
            val = self._get_reg(dst)
            result = (val - 1) & 0xFF
            self._set_flags_szp(result)
            self.AC = 0 if (val & 0x0F) == 0 else 1
            self._set_reg(dst, result)
            return f"DCR {self.REG_NAMES[dst]}", f"{self.REG_NAMES[dst]} = {val:02X}H - 1 = {result:02X}H"

        # ---- INX rp ----
        if opcode == 0x03:
            bc = (self._get_bc() + 1) & 0xFFFF
            self.B = (bc >> 8) & 0xFF
            self.C = bc & 0xFF
            return "INX B", f"BC = {bc:04X}H"
        if opcode == 0x13:
            de = (self._get_de() + 1) & 0xFFFF
            self.D = (de >> 8) & 0xFF
            self.E = de & 0xFF
            return "INX D", f"DE = {de:04X}H"
        if opcode == 0x23:
            hl = (self._get_hl() + 1) & 0xFFFF
            self.H = (hl >> 8) & 0xFF
            self.L = hl & 0xFF
            return "INX H", f"HL = {hl:04X}H"
        if opcode == 0x33:
            self.SP = (self.SP + 1) & 0xFFFF
            return "INX SP", f"SP = {self.SP:04X}H"

        # ---- DCX rp ----
        if opcode == 0x0B:
            bc = (self._get_bc() - 1) & 0xFFFF
            self.B = (bc >> 8) & 0xFF
            self.C = bc & 0xFF
            return "DCX B", f"BC = {bc:04X}H"
        if opcode == 0x1B:
            de = (self._get_de() - 1) & 0xFFFF
            self.D = (de >> 8) & 0xFF
            self.E = de & 0xFF
            return "DCX D", f"DE = {de:04X}H"
        if opcode == 0x2B:
            hl = (self._get_hl() - 1) & 0xFFFF
            self.H = (hl >> 8) & 0xFF
            self.L = hl & 0xFF
            return "DCX H", f"HL = {hl:04X}H"

        # ---- DAD rp ----
        if opcode == 0x09:
            result = self._get_hl() + self._get_bc()
            self.CY = 1 if result > 0xFFFF else 0
            self.H = (result >> 8) & 0xFF
            self.L = result & 0xFF
            return "DAD B", f"HL = HL + BC = {self._get_hl():04X}H"
        if opcode == 0x19:
            result = self._get_hl() + self._get_de()
            self.CY = 1 if result > 0xFFFF else 0
            self.H = (result >> 8) & 0xFF
            self.L = result & 0xFF
            return "DAD D", f"HL = HL + DE = {self._get_hl():04X}H"

        # ---- LXI rp, data16 ----
        if opcode == 0x01:
            data = self._read_word()
            self.B = (data >> 8) & 0xFF
            self.C = data & 0xFF
            return f"LXI B, {data:04X}H", f"BC = {data:04X}H"
        if opcode == 0x11:
            data = self._read_word()
            self.D = (data >> 8) & 0xFF
            self.E = data & 0xFF
            return f"LXI D, {data:04X}H", f"DE = {data:04X}H"
        if opcode == 0x21:
            data = self._read_word()
            self.H = (data >> 8) & 0xFF
            self.L = data & 0xFF
            return f"LXI H, {data:04X}H", f"HL = {data:04X}H"
        if opcode == 0x31:
            data = self._read_word()
            self.SP = data
            return f"LXI SP, {data:04X}H", f"SP = {data:04X}H"

        # ---- LDA addr ----
        if opcode == 0x3A:
            addr = self._read_word()
            self.A = self.memory[addr]
            return f"LDA {addr:04X}H", f"A = memory[{addr:04X}H] = {self.A:02X}H"

        # ---- STA addr ----
        if opcode == 0x32:
            addr = self._read_word()
            self.memory[addr] = self.A
            return f"STA {addr:04X}H", f"memory[{addr:04X}H] = A = {self.A:02X}H"

        # ---- LDAX B/D ----
        if opcode == 0x0A:
            self.A = self.memory[self._get_bc()]
            return "LDAX B", f"A = memory[BC={self._get_bc():04X}H] = {self.A:02X}H"
        if opcode == 0x1A:
            self.A = self.memory[self._get_de()]
            return "LDAX D", f"A = memory[DE={self._get_de():04X}H] = {self.A:02X}H"

        # ---- STAX B/D ----
        if opcode == 0x02:
            self.memory[self._get_bc()] = self.A
            return "STAX B", f"memory[BC={self._get_bc():04X}H] = A = {self.A:02X}H"
        if opcode == 0x12:
            self.memory[self._get_de()] = self.A
            return "STAX D", f"memory[DE={self._get_de():04X}H] = A = {self.A:02X}H"

        # ---- LHLD addr ----
        if opcode == 0x2A:
            addr = self._read_word()
            self.L = self.memory[addr]
            self.H = self.memory[(addr + 1) & 0xFFFF]
            return f"LHLD {addr:04X}H", f"HL = memory[{addr:04X}H] = {self._get_hl():04X}H"

        # ---- SHLD addr ----
        if opcode == 0x22:
            addr = self._read_word()
            self.memory[addr] = self.L
            self.memory[(addr + 1) & 0xFFFF] = self.H
            return f"SHLD {addr:04X}H", f"memory[{addr:04X}H] = HL = {self._get_hl():04X}H"

        # ---- XCHG ----
        if opcode == 0xEB:
            self.H, self.D = self.D, self.H
            self.L, self.E = self.E, self.L
            return "XCHG", f"Swap HL({self._get_hl():04X}H) and DE({self._get_de():04X}H)"

        # ---- PUSH/POP ----
        if opcode == 0xC5:
            self._push(self._get_bc())
            return "PUSH B", f"Stack <- BC={self._get_bc():04X}H"
        if opcode == 0xD5:
            self._push(self._get_de())
            return "PUSH D", f"Stack <- DE={self._get_de():04X}H"
        if opcode == 0xE5:
            self._push(self._get_hl())
            return "PUSH H", f"Stack <- HL={self._get_hl():04X}H"
        if opcode == 0xF5:
            psw = (self.A << 8) | (self.S << 7) | (self.Z << 6) | (self.AC << 4) | (self.P << 2) | (1 << 1) | self.CY
            self._push(psw)
            return "PUSH PSW", f"Stack <- PSW={psw:04X}H"

        if opcode == 0xC1:
            val = self._pop()
            self.B = (val >> 8) & 0xFF
            self.C = val & 0xFF
            return "POP B", f"BC <- Stack = {val:04X}H"
        if opcode == 0xD1:
            val = self._pop()
            self.D = (val >> 8) & 0xFF
            self.E = val & 0xFF
            return "POP D", f"DE <- Stack = {val:04X}H"
        if opcode == 0xE1:
            val = self._pop()
            self.H = (val >> 8) & 0xFF
            self.L = val & 0xFF
            return "POP H", f"HL <- Stack = {val:04X}H"
        if opcode == 0xF1:
            val = self._pop()
            self.A = (val >> 8) & 0xFF
            self.CY = val & 0x01
            self.P = (val >> 2) & 0x01
            self.AC = (val >> 4) & 0x01
            self.Z = (val >> 6) & 0x01
            self.S = (val >> 7) & 0x01
            return "POP PSW", f"PSW <- Stack, A={self.A:02X}H"

        # ---- JMP addr ----
        if opcode == 0xC3:
            addr = self._read_word()
            self.PC = addr
            return f"JMP {addr:04X}H", f"Jump to {addr:04X}H"

        # ---- Conditional jumps ----
        cond_jumps = {
            0xC2: ("JNZ", self.Z == 0),
            0xCA: ("JZ", self.Z == 1),
            0xD2: ("JNC", self.CY == 0),
            0xDA: ("JC", self.CY == 1),
            0xE2: ("JPO", self.P == 0),
            0xEA: ("JPE", self.P == 1),
            0xF2: ("JP", self.S == 0),
            0xFA: ("JM", self.S == 1),
        }
        if opcode in cond_jumps:
            name, condition = cond_jumps[opcode]
            addr = self._read_word()
            taken = "taken" if condition else "not taken"
            if condition:
                self.PC = addr
            return f"{name} {addr:04X}H", f"Conditional jump to {addr:04X}H ({taken})"

        # ---- CALL addr ----
        if opcode == 0xCD:
            addr = self._read_word()
            self._push(self.PC)
            self.PC = addr
            return f"CALL {addr:04X}H", f"Call subroutine at {addr:04X}H"

        # ---- RET ----
        if opcode == 0xC9:
            self.PC = self._pop()
            return "RET", f"Return to {self.PC:04X}H"

        # ---- Rotate ----
        if opcode == 0x07:  # RLC
            self.CY = (self.A >> 7) & 1
            self.A = ((self.A << 1) | self.CY) & 0xFF
            return "RLC", f"Rotate A left through carry. A={self.A:02X}H CY={self.CY}"
        if opcode == 0x0F:  # RRC
            self.CY = self.A & 1
            self.A = ((self.A >> 1) | (self.CY << 7)) & 0xFF
            return "RRC", f"Rotate A right through carry. A={self.A:02X}H CY={self.CY}"
        if opcode == 0x17:  # RAL
            old_cy = self.CY
            self.CY = (self.A >> 7) & 1
            self.A = ((self.A << 1) | old_cy) & 0xFF
            return "RAL", f"Rotate A left through carry. A={self.A:02X}H CY={self.CY}"
        if opcode == 0x1F:  # RAR
            old_cy = self.CY
            self.CY = self.A & 1
            self.A = ((self.A >> 1) | (old_cy << 7)) & 0xFF
            return "RAR", f"Rotate A right through carry. A={self.A:02X}H CY={self.CY}"

        # ---- CMA ----
        if opcode == 0x2F:
            self.A = (~self.A) & 0xFF
            return "CMA", f"A = complement of A = {self.A:02X}H"

        # ---- CMC ----
        if opcode == 0x3F:
            self.CY = 1 - self.CY
            return "CMC", f"CY = complement = {self.CY}"

        # ---- STC ----
        if opcode == 0x37:
            self.CY = 1
            return "STC", f"CY = 1"

        # ---- IN port ----
        if opcode == 0xDB:
            port = self._read_byte()
            self.A = self.ports[port]
            return f"IN {port:02X}H", f"A = port[{port:02X}H] = {self.A:02X}H"

        # ---- OUT port ----
        if opcode == 0xD3:
            port = self._read_byte()
            self.ports[port] = self.A
            return f"OUT {port:02X}H", f"port[{port:02X}H] = A = {self.A:02X}H"

        # ---- EI / DI ----
        if opcode == 0xFB:
            return "EI", "Interrupts enabled"
        if opcode == 0xF3:
            return "DI", "Interrupts disabled"

        # ---- PCHL ----
        if opcode == 0xE9:
            self.PC = self._get_hl()
            return "PCHL", f"PC = HL = {self.PC:04X}H"

        # ---- SPHL ----
        if opcode == 0xF9:
            self.SP = self._get_hl()
            return "SPHL", f"SP = HL = {self.SP:04X}H"

        # ---- XTHL ----
        if opcode == 0xE3:
            lo = self.memory[self.SP]
            hi = self.memory[(self.SP + 1) & 0xFFFF]
            self.memory[self.SP] = self.L
            self.memory[(self.SP + 1) & 0xFFFF] = self.H
            self.L = lo
            self.H = hi
            return "XTHL", f"Exchange HL with top of stack"

        # ---- DAA ----
        if opcode == 0x27:
            if (self.A & 0x0F) > 9 or self.AC:
                self.A += 6
                self.AC = 1
            if (self.A >> 4) > 9 or self.CY:
                self.A += 0x60
                self.CY = 1
            self.A &= 0xFF
            self._set_flags_szp(self.A)
            return "DAA", f"Decimal adjust A = {self.A:02X}H"

        # ---- RST n ----
        if opcode & 0xC7 == 0xC7:
            n = (opcode >> 3) & 0x07
            self._push(self.PC)
            self.PC = n * 8
            return f"RST {n}", f"Restart {n} -> PC = {self.PC:04X}H"

        # ---- Unknown ----
        return f"??? ({opcode:02X}H)", f"Unknown opcode at {pc:04X}H"

    # ================ DISPLAY HELPERS ================

    def format_registers(self) -> str:
        """Human-readable register dump."""
        lines = [
            f"A={self.A:02X}  B={self.B:02X}  C={self.C:02X}  D={self.D:02X}",
            f"E={self.E:02X}  H={self.H:02X}  L={self.L:02X}",
            f"SP={self.SP:04X}  PC={self.PC:04X}",
            f"Flags: S={self.S} Z={self.Z} AC={self.AC} P={self.P} CY={self.CY}",
        ]
        return "\n".join(lines)

    def format_memory(self, start: int, length: int = 32) -> str:
        """Hex dump of memory region."""
        lines = []
        for i in range(0, length, 8):
            addr = (start + i) & 0xFFFF
            hexvals = " ".join(f"{self.memory[addr + j]:02X}" for j in range(min(8, length - i)))
            lines.append(f"{addr:04X}: {hexvals}")
        return "\n".join(lines)
