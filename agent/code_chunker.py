"""
agent/code_chunker.py — AST-aware code chunking (Phase 2B.1)

Splits source files into semantically meaningful chunks instead of
fixed-size line blocks. Each chunk knows what it is (function/class/
section/etc), its name, signature, line range, and docstring.

Used by agent/rag.py and agent/symbol_index.py.

Language coverage:
  Python    — full AST (functions, classes, methods, module header)
  JS/TS/JSX/TSX — regex (functions, arrow fns, classes, React components)
  HTML      — section/main/header/footer/article/nav blocks
  CSS       — rule blocks
  Markdown  — heading hierarchy
  Other     — 50-line block fallback (matches legacy chunker behavior)

Pure module: no I/O, no Chroma, no embeddings. Just text in, chunks out.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


# ── Public data type ─────────────────────────────────────────────────────────
@dataclass
class Chunk:
    """A semantically meaningful unit of code."""

    file: str                        # "agent/parser.py"
    type: str                        # function | class | method | section | rule | heading | block | module_header
    name: str                        # "parse_llm_output" or "" for anonymous
    signature: str                   # first line of def/class, or section selector
    start_line: int                  # 1-based, inclusive
    end_line: int                    # 1-based, inclusive
    code: str                        # full text of the chunk (with file/line header for embedding)
    docstring: str = ""              # extracted docstring if any
    parent: Optional[str] = None     # parent class name if this is a method

    def to_dict(self) -> dict:
        return asdict(self)

    def to_embedding_text(self) -> str:
        """Format the chunk for embedding (file + lines + code)."""
        header = f"File: {self.file}\n"
        header += f"Type: {self.type}"
        if self.name:
            header += f" — {self.name}"
        if self.parent:
            header += f" (in class {self.parent})"
        header += f"\nLines {self.start_line}-{self.end_line}:\n\n"
        return header + self.code


# ── Top-level dispatcher ─────────────────────────────────────────────────────
def chunk_code(content: str, filepath: str) -> list[Chunk]:
    """
    Chunk a file based on its extension.
    Always returns at least one chunk for non-empty content.
    Never raises — falls back to line-based chunking on any error.
    """
    if not content or not content.strip():
        return []

    ext = Path(filepath).suffix.lower()
    try:
        if ext == ".py":
            return _chunk_python(content, filepath)
        if ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
            return _chunk_javascript(content, filepath)
        if ext in (".html", ".htm"):
            return _chunk_html(content, filepath)
        if ext == ".css":
            return _chunk_css(content, filepath)
        if ext in (".md", ".markdown"):
            return _chunk_markdown(content, filepath)
    except Exception:
        # ANY chunker failure -> fallback. Robustness first.
        return _chunk_fallback(content, filepath)

    return _chunk_fallback(content, filepath)


# ── Python (AST) ─────────────────────────────────────────────────────────────
def _chunk_python(content: str, filepath: str) -> list[Chunk]:
    """Use ast module to split by top-level functions, classes, methods."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        # Broken Python? Fall back to line blocks so we still index it.
        return _chunk_fallback(content, filepath)

    lines = content.splitlines()
    chunks: list[Chunk] = []

    # Track which lines belong to top-level defs/classes so we can
    # produce a "module header" chunk for everything ELSE (imports, constants).
    consumed_lines: set[int] = set()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            chunk = _python_func_chunk(node, lines, filepath, parent=None)
            chunks.append(chunk)
            for ln in range(chunk.start_line, chunk.end_line + 1):
                consumed_lines.add(ln)

        elif isinstance(node, ast.ClassDef):
            # 1) Class-as-a-whole chunk (gives RAG full context of class + all methods)
            class_chunk = _python_class_chunk(node, lines, filepath)
            chunks.append(class_chunk)
            for ln in range(class_chunk.start_line, class_chunk.end_line + 1):
                consumed_lines.add(ln)

            # 2) Per-method chunks (so individual methods are findable)
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_chunk = _python_func_chunk(
                        member, lines, filepath, parent=node.name
                    )
                    method_chunk.type = "method"
                    chunks.append(method_chunk)

    # Module header: everything not consumed (imports, top-level constants, __main__)
    header_lines: list[tuple[int, str]] = []
    for i, line in enumerate(lines, start=1):
        if i not in consumed_lines and line.strip():
            header_lines.append((i, line))

    if header_lines:
        # Group consecutive line ranges into one header chunk
        start = header_lines[0][0]
        end = header_lines[-1][0]
        header_code = "\n".join(line for _, line in header_lines)
        chunks.append(Chunk(
            file=filepath,
            type="module_header",
            name="<module>",
            signature="(module-level imports, constants, __main__)",
            start_line=start,
            end_line=end,
            code=header_code,
        ))

    # If somehow no chunks (empty module?), fallback
    if not chunks:
        return _chunk_fallback(content, filepath)

    return chunks


def _python_func_chunk(
    node: ast.AST, lines: list[str], filepath: str, parent: Optional[str]
) -> Chunk:
    start = node.lineno
    end = getattr(node, "end_lineno", start) or start
    code = "\n".join(lines[start - 1:end])
    signature = lines[start - 1].strip() if start - 1 < len(lines) else ""
    docstring = ast.get_docstring(node) or ""
    return Chunk(
        file=filepath,
        type="function",
        name=node.name,
        signature=signature,
        start_line=start,
        end_line=end,
        code=code,
        docstring=docstring,
        parent=parent,
    )


def _python_class_chunk(node: ast.ClassDef, lines: list[str], filepath: str) -> Chunk:
    start = node.lineno
    end = getattr(node, "end_lineno", start) or start
    code = "\n".join(lines[start - 1:end])
    signature = lines[start - 1].strip() if start - 1 < len(lines) else ""
    docstring = ast.get_docstring(node) or ""
    return Chunk(
        file=filepath,
        type="class",
        name=node.name,
        signature=signature,
        start_line=start,
        end_line=end,
        code=code,
        docstring=docstring,
    )


# ── JavaScript / TypeScript (regex) ──────────────────────────────────────────
_JS_PATTERNS = [
    # Named function declaration: function foo(...)
    (r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+(\w+)\s*\(", "function"),
    # Class declaration: class Foo
    (r"^\s*(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+(\w+)", "class"),
    # Arrow function: const foo = (...) => or const foo = async (...) =>
    (r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*[:=]\s*(?:async\s*)?\(", "function"),
    # React component (function with Capital first letter)
    (r"^\s*(?:export\s+(?:default\s+)?)?(?:function|const)\s+([A-Z]\w*)", "component"),
]


def _chunk_javascript(content: str, filepath: str) -> list[Chunk]:
    """Regex-based JS/TS chunker. Finds tops, ranges via brace counting."""
    lines = content.splitlines()
    chunks: list[Chunk] = []
    consumed: set[int] = set()

    i = 0
    while i < len(lines):
        line = lines[i]
        matched = False

        for pattern, kind in _JS_PATTERNS:
            m = re.match(pattern, line)
            if m:
                name = m.group(1)
                # Find end via brace balance (or paren for arrow that ends with semicolon)
                end = _find_js_block_end(lines, i)
                code = "\n".join(lines[i:end + 1])
                chunks.append(Chunk(
                    file=filepath,
                    type=kind,
                    name=name,
                    signature=line.strip(),
                    start_line=i + 1,
                    end_line=end + 1,
                    code=code,
                ))
                for ln in range(i + 1, end + 2):
                    consumed.add(ln)
                i = end + 1
                matched = True
                break

        if not matched:
            i += 1

    # Header chunk: imports, top-level statements
    header_lines = [(idx + 1, ln) for idx, ln in enumerate(lines)
                    if (idx + 1) not in consumed and ln.strip()]
    if header_lines:
        chunks.append(Chunk(
            file=filepath,
            type="module_header",
            name="<module>",
            signature="(imports, constants, top-level)",
            start_line=header_lines[0][0],
            end_line=header_lines[-1][0],
            code="\n".join(ln for _, ln in header_lines),
        ))

    if not chunks:
        return _chunk_fallback(content, filepath)
    return chunks


def _find_js_block_end(lines: list[str], start: int) -> int:
    """Find matching closing brace for a JS block starting at `start`."""
    depth = 0
    seen_brace = False
    for i in range(start, len(lines)):
        for ch in lines[i]:
            if ch == "{":
                depth += 1
                seen_brace = True
            elif ch == "}":
                depth -= 1
                if seen_brace and depth == 0:
                    return i
        # Arrow function on single line (no opening brace) -> ends at line end / semicolon
        if not seen_brace and i > start and (
            lines[i].rstrip().endswith(";") or lines[i].rstrip().endswith(",")
        ):
            return i
    return min(start + 100, len(lines) - 1)  # safety bound


# ── HTML ─────────────────────────────────────────────────────────────────────
_HTML_SECTION_TAGS = ("section", "main", "header", "footer", "article", "nav", "aside")


def _chunk_html(content: str, filepath: str) -> list[Chunk]:
    lines = content.splitlines()
    chunks: list[Chunk] = []
    consumed: set[int] = set()

    for tag in _HTML_SECTION_TAGS:
        pattern = re.compile(rf"<{tag}\b[^>]*>", re.IGNORECASE)
        close_pattern = re.compile(rf"</{tag}>", re.IGNORECASE)
        i = 0
        while i < len(lines):
            if pattern.search(lines[i]):
                start = i
                # Find matching close (simple, doesn't handle nesting of same tag)
                end = start
                for j in range(start, len(lines)):
                    if close_pattern.search(lines[j]):
                        end = j
                        break
                code = "\n".join(lines[start:end + 1])
                chunks.append(Chunk(
                    file=filepath,
                    type="section",
                    name=tag,
                    signature=lines[start].strip()[:120],
                    start_line=start + 1,
                    end_line=end + 1,
                    code=code,
                ))
                for ln in range(start + 1, end + 2):
                    consumed.add(ln)
                i = end + 1
            else:
                i += 1

    if not chunks:
        return _chunk_fallback(content, filepath)
    return chunks


# ── CSS ──────────────────────────────────────────────────────────────────────
def _chunk_css(content: str, filepath: str) -> list[Chunk]:
    """Split CSS by rule blocks: SELECTOR { ... }"""
    lines = content.splitlines()
    chunks: list[Chunk] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith("/*"):
            i += 1
            continue
        if "{" in line:
            selector = line.split("{")[0].strip()
            start = i
            depth = line.count("{") - line.count("}")
            end = i
            j = i
            while j < len(lines) and depth > 0:
                j += 1
                if j < len(lines):
                    depth += lines[j].count("{") - lines[j].count("}")
                    end = j
            code = "\n".join(lines[start:end + 1])
            chunks.append(Chunk(
                file=filepath,
                type="rule",
                name=selector[:80],
                signature=selector[:120],
                start_line=start + 1,
                end_line=end + 1,
                code=code,
            ))
            i = end + 1
        else:
            i += 1

    if not chunks:
        return _chunk_fallback(content, filepath)
    return chunks


# ── Markdown ─────────────────────────────────────────────────────────────────
def _chunk_markdown(content: str, filepath: str) -> list[Chunk]:
    lines = content.splitlines()
    chunks: list[Chunk] = []
    current_start = 0
    current_title = "(intro)"

    for i, line in enumerate(lines):
        if re.match(r"^#{1,6}\s+", line):
            # Close previous section
            if i > current_start:
                code = "\n".join(lines[current_start:i])
                if code.strip():
                    chunks.append(Chunk(
                        file=filepath,
                        type="heading",
                        name=current_title,
                        signature=current_title,
                        start_line=current_start + 1,
                        end_line=i,
                        code=code,
                    ))
            current_start = i
            current_title = line.lstrip("#").strip()[:120]

    # Final section
    if current_start < len(lines):
        code = "\n".join(lines[current_start:])
        if code.strip():
            chunks.append(Chunk(
                file=filepath,
                type="heading",
                name=current_title,
                signature=current_title,
                start_line=current_start + 1,
                end_line=len(lines),
                code=code,
            ))

    if not chunks:
        return _chunk_fallback(content, filepath)
    return chunks


# ── Fallback (legacy 50-line blocks) ─────────────────────────────────────────
def _chunk_fallback(content: str, filepath: str, max_lines: int = 50, overlap: int = 10) -> list[Chunk]:
    """Line-based chunking, matches your legacy chunk_file() behavior."""
    lines = content.splitlines()
    chunks: list[Chunk] = []
    i = 0
    while i < len(lines):
        block = lines[i:i + max_lines]
        text = "\n".join(block)
        if text.strip():
            chunks.append(Chunk(
                file=filepath,
                type="block",
                name="",
                signature=f"lines {i + 1}-{i + len(block)}",
                start_line=i + 1,
                end_line=i + len(block),
                code=text,
            ))
        i += max_lines - overlap
    return chunks
