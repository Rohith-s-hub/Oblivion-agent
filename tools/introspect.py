"""
tools/introspect.py — Auto-generate tool schemas from function signatures.

Replaces hand-maintained TOOL_SCHEMAS dicts by reading each tool function's
actual signature (via inspect.signature) and docstring, so adding a new tool
only requires writing the function itself — no separate schema entry to
keep in sync by hand.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable, get_type_hints

# Python type -> JSON-schema-ish type string (matches your existing TOOL_SCHEMAS format)
_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _python_type_to_schema_type(annotation: Any) -> str:
    """Map a Python type annotation to the string type your schemas use."""
    if annotation is inspect.Parameter.empty:
        return "string"  # sane default for untyped params
    return _TYPE_MAP.get(annotation, "string")


def _first_docstring_line(func: Callable) -> str:
    """Use the first non-empty line of the docstring as the description."""
    doc = inspect.getdoc(func) or ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
    return f"{func.__name__} (no description)"


def build_tool_def(name: str, func: Callable) -> dict:
    """Introspect ONE function and return its schema dict."""
    sig = inspect.signature(func)
    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}

    parameters = {}
    for pname, param in sig.parameters.items():
        if pname in ("self", "cls"):
            continue
        annotation = hints.get(pname, param.annotation)
        param_type = _python_type_to_schema_type(annotation)
        has_default = param.default is not inspect.Parameter.empty
        parameters[pname] = {
            "type": param_type,
            "required": not has_default,
        }

    return {
        "name": name,
        "description": _first_docstring_line(func),
        "parameters": parameters,
    }


def build_tool_defs(tool_functions: dict[str, Callable]) -> list[dict]:
    """
    Introspect every function in TOOL_FUNCTIONS and return the full list
    of schema dicts — same shape as the old hand-written TOOL_SCHEMAS.
    """
    defs = []
    for name, func in tool_functions.items():
        if not callable(func):
            continue
        try:
            defs.append(build_tool_def(name, func))
        except Exception as e:
            # Never let one bad signature break the whole registry
            defs.append({
                "name": name,
                "description": f"(schema introspection failed: {e})",
                "parameters": {},
            })
    return defs
