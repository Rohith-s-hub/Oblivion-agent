"""
simulator/assembler.py - 8085 Assembly Language Assembler
Converts 8085 assembly mnemonics into machine code bytes.
Supports labels, comments, ORG directive.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re


@dataclass
class AssemblyResult:
    bytes: list[int] = field(default_factory=list)
    origin: int = 0x0000
    labels: dict[str, int] = field(default_factory=dict)
    listing: str = ""
    errors: list[str] = field(default_factory=list)
    success: bool = True


REG_CODE = {"B": 0, "C": 1, "D": 2, "E": 3, "H": 4, "L": 5, "M": 6, "A": 7}
RP_CODE = {"B": 0, "D": 1, "H": 2, "SP": 3, "PSW": 3}

SINGLE_BYTE = {
    "NOP": 0x00, "HLT": 0x76, "RET": 0xC9,
    "RLC": 0x07, "RRC": 0x0F, "RAL": 0x17, "RAR": 0x1F,
    "CMA": 0x2F, "CMC": 0x3F, "STC": 0x37,
    "XCHG": 0xEB, "XTHL": 0xE3, "SPHL": 0xF9, "PCHL": 0xE9,
    "EI": 0xFB, "DI": 0xF3, "DAA": 0x27,
}

ALU_OPS = {"ADD": 0x80, "ADC": 0x88, "SUB": 0x90, "SBB": 0x98,
           "ANA": 0xA0, "ORA": 0xB0, "XRA": 0xA8, "CMP": 0xB8}
IMM_OPS = {"ADI": 0xC6, "ACI": 0xCE, "SUI": 0xD6, "SBI": 0xDE,
           "ANI": 0xE6, "ORI": 0xF6, "XRI": 0xEE, "CPI": 0xFE}
JMP_OPS = {"JMP": 0xC3, "JZ": 0xCA, "JNZ": 0xC2, "JC": 0xDA, "JNC": 0xD2,
           "JP": 0xF2, "JM": 0xFA, "JPE": 0xEA, "JPO": 0xE2}
CALL_OPS = {"CALL": 0xCD, "CZ": 0xCC, "CNZ": 0xC4, "CC": 0xDC, "CNC": 0xD4,
            "CP": 0xF4, "CM": 0xFC, "CPE": 0xEC, "CPO": 0xE4}
RET_OPS = {"RZ": 0xC8, "RNZ": 0xC0, "RC": 0xD8, "RNC": 0xD0,
           "RP": 0xF0, "RM": 0xF8, "RPE": 0xE8, "RPO": 0xE0}
TWO_BYTE = {"MVI", "ADI", "ACI", "SUI", "SBI", "ANI", "ORI", "XRI", "CPI", "IN", "OUT"}
THREE_BYTE = set(JMP_OPS) | set(CALL_OPS) | {"LXI", "LDA", "STA", "LHLD", "SHLD"}
ONE_BYTE_REG = {"MOV", "ADD", "ADC", "SUB", "SBB", "ANA", "ORA", "XRA", "CMP",
                "INR", "DCR", "PUSH", "POP", "STAX", "LDAX", "INX", "DCX", "DAD"}


def _parse_number(s):
    s = s.strip().upper()
    if not s:
        raise ValueError("Empty number")
    if s.endswith("H"):
        return int(s[:-1], 16)
    if s.startswith("0X"):
        return int(s, 16)
    return int(s)


class Assembler8085:
    def assemble(self, source):
        result = AssemblyResult()
        lines = source.strip().split(chr(10))
        origin = 0
        addr = origin
        labels = {}
        cleaned = []
        for ln, raw in enumerate(lines, 1):
            line = raw.split(";")[0].strip()
            if not line:
                cleaned.append(("", ln, raw.strip()))
                continue
            m = re.match(r"^ORG\s+(.+)$", line, re.IGNORECASE)
            if m:
                origin = _parse_number(m.group(1))
                addr = origin
                result.origin = origin
                cleaned.append(("ORG", ln, raw.strip()))
                continue
            m = re.match(r"^(\w+):\s*(.*)", line)
            if m:
                labels[m.group(1).upper()] = addr
                line = m.group(2).strip()
                if not line:
                    cleaned.append(("LABEL", ln, raw.strip()))
                    continue
            size = self._est(line)
            cleaned.append((line, ln, raw.strip()))
            addr += size
        result.labels = labels
        addr = origin
        listing = []
        mbytes = []
        for entry, ln, raw in cleaned:
            if entry in ("", "ORG", "LABEL"):
                listing.append(f"{'':>6s}  {raw}")
                continue
            try:
                code = self._enc(entry, addr, labels)
                hx = " ".join(f"{b:02X}" for b in code)
                listing.append(f"{addr:04X}: {hx:<12s}  {raw}")
                mbytes.extend(code)
                addr += len(code)
            except Exception as e:
                result.errors.append(f"Line {ln}: {e}")
                result.success = False
                listing.append(f"ERROR: {e}  -> {raw}")
        result.bytes = mbytes
        result.listing = chr(10).join(listing)
        return result

    def _est(self, line):
        p = line.upper().split()
        if not p:
            return 0
        m = p[0]
        if m in SINGLE_BYTE or m in ONE_BYTE_REG or m == "RST" or m in RET_OPS:
            return 1
        if m in TWO_BYTE:
            return 2
        if m in THREE_BYTE:
            return 3
        if m == "DB":
            return len([x for x in line[2:].split(",") if x.strip()])
        return 1

    def _resolve(self, op, labels):
        op = op.strip()
        if op.upper() in labels:
            return labels[op.upper()]
        return _parse_number(op)

    def _enc(self, line, addr, labels):
        p = line.upper().split(None, 1)
        if not p:
            return []
        mn = p[0]
        op = p[1].strip() if len(p) > 1 else ""
        if mn in SINGLE_BYTE:
            return [SINGLE_BYTE[mn]]
        if mn == "MOV":
            r = [x.strip() for x in op.split(",")]
            return [0x40 | (REG_CODE[r[0]] << 3) | REG_CODE[r[1]]]
        if mn == "MVI":
            r = [x.strip() for x in op.split(",")]
            return [0x06 | (REG_CODE[r[0]] << 3), _parse_number(r[1]) & 0xFF]
        if mn in ALU_OPS:
            return [ALU_OPS[mn] | REG_CODE[op.strip()]]
        if mn in IMM_OPS:
            return [IMM_OPS[mn], _parse_number(op) & 0xFF]
        if mn == "INR":
            return [0x04 | (REG_CODE[op.strip()] << 3)]
        if mn == "DCR":
            return [0x05 | (REG_CODE[op.strip()] << 3)]
        if mn == "INX":
            return [0x03 | (RP_CODE[op.strip()] << 4)]
        if mn == "DCX":
            return [0x0B | (RP_CODE[op.strip()] << 4)]
        if mn == "DAD":
            return [0x09 | (RP_CODE[op.strip()] << 4)]
        if mn == "LXI":
            r = [x.strip() for x in op.split(",")]
            v = self._resolve(r[1], labels)
            return [0x01 | (RP_CODE[r[0]] << 4), v & 0xFF, (v >> 8) & 0xFF]
        if mn == "PUSH":
            m2 = {"B": 0, "D": 1, "H": 2, "PSW": 3}
            return [0xC5 | (m2[op.strip()] << 4)]
        if mn == "POP":
            m2 = {"B": 0, "D": 1, "H": 2, "PSW": 3}
            return [0xC1 | (m2[op.strip()] << 4)]
        if mn == "LDAX":
            return [0x0A if op.strip() == "B" else 0x1A]
        if mn == "STAX":
            return [0x02 if op.strip() == "B" else 0x12]
        if mn == "LDA":
            v = self._resolve(op, labels)
            return [0x3A, v & 0xFF, (v >> 8) & 0xFF]
        if mn == "STA":
            v = self._resolve(op, labels)
            return [0x32, v & 0xFF, (v >> 8) & 0xFF]
        if mn == "LHLD":
            v = self._resolve(op, labels)
            return [0x2A, v & 0xFF, (v >> 8) & 0xFF]
        if mn == "SHLD":
            v = self._resolve(op, labels)
            return [0x22, v & 0xFF, (v >> 8) & 0xFF]
        if mn in JMP_OPS:
            v = self._resolve(op, labels)
            return [JMP_OPS[mn], v & 0xFF, (v >> 8) & 0xFF]
        if mn in CALL_OPS:
            v = self._resolve(op, labels)
            return [CALL_OPS[mn], v & 0xFF, (v >> 8) & 0xFF]
        if mn in RET_OPS:
            return [RET_OPS[mn]]
        if mn == "IN":
            return [0xDB, _parse_number(op) & 0xFF]
        if mn == "OUT":
            return [0xD3, _parse_number(op) & 0xFF]
        if mn == "RST":
            n = _parse_number(op)
            return [0xC7 | (n << 3)]
        if mn == "DB":
            return [_parse_number(v.strip()) & 0xFF for v in op.split(",")]
        raise ValueError(f"Unknown: {mn}")
