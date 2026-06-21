from tools.filesystem import read_file, write_file, list_dir, grep_files, file_exists, create_dir, new_workspace
from tools.planner import plan_task
from tools.bash import run_bash
from tools.edit_file import edit_file, insert_after
from tools.search_code import search_code
from tools.symbol_tools import find_symbol, list_symbols, find_callers, project_map
from agent.brain import remember as _remember, recall as _recall, verify_code as _verify_code


def remember(note: str, category: str = "general") -> str:
    """Tool wrapper for remember()."""
    return _remember(note, category)


def recall(category: str = "") -> str:
    """Tool wrapper for recall()."""
    return _recall(category if category else None)


def verify_code(path: str, language: str = "auto") -> str:
    """Tool wrapper for verify_code() - returns formatted string."""
    result = _verify_code(path, language)
    if result["ok"]:
        return f"VERIFIED: {result['message']}"
    return f"FAILED: {result['message']}\n{result['details']}"

TOOL_SCHEMAS = [
    {
        "name": "search_code",
        "description": (
            "Semantically search the codebase. Returns the most relevant code chunks. "
            "Use this FIRST when answering questions about how/where something works in the project. "
            "Better than grep when the user asks conceptual questions."
        ),
        "parameters": {
            "query": {"type": "string", "description": "Natural language search query", "required": True},
            "n_results": {"type": "integer", "description": "Number of results (default 5)", "required": False},
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file.",
        "parameters": {
            "path": {"type": "string", "description": "Path to file", "required": True},
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Shows diff/preview and asks approval first.",
        "parameters": {
            "path": {"type": "string", "description": "Path to file", "required": True},
            "content": {"type": "string", "description": "Full content to write", "required": True},
        },
    },
    {
        "name": "edit_file",
        "description": "Surgically replace a section of a file. Safer than write_file for small changes.",
        "parameters": {
            "path": {"type": "string", "description": "Path to file", "required": True},
            "old_text": {"type": "string", "description": "Exact text to replace", "required": True},
            "new_text": {"type": "string", "description": "Replacement text", "required": True},
        },
    },
    {
        "name": "insert_after",
        "description": "Insert text immediately after a specific line/section in a file.",
        "parameters": {
            "path": {"type": "string", "description": "Path to file", "required": True},
            "after_text": {"type": "string", "description": "Insert after this exact text", "required": True},
            "insert_text": {"type": "string", "description": "Text to insert", "required": True},
        },
    },
    {
        "name": "list_dir",
        "description": "List files and directories in a path.",
        "parameters": {
            "path": {"type": "string", "description": "Directory path", "required": True},
        },
    },
    {
        "name": "grep_files",
        "description": "Exact text search across files. Use search_code for conceptual queries.",
        "parameters": {
            "pattern": {"type": "string", "description": "Regex pattern to search for", "required": True},
            "path": {"type": "string", "description": "Where to search", "required": True},
            "file_pattern": {"type": "string", "description": "File glob e.g. *.py", "required": False},
        },
    },
    {
        "name": "file_exists",
        "description": "Check if a file or directory exists.",
        "parameters": {
            "path": {"type": "string", "description": "Path to check", "required": True},
        },
    },
    {
        "name": "create_dir",
        "description": "Create a directory (and parents if needed).",
        "parameters": {
            "path": {"type": "string", "description": "Directory to create", "required": True},
        },
    },
    {
        "name": "new_workspace",
        "description": (
            "Create a NEW workspace folder ANYWHERE and switch the active workspace to it. "
            "Use this when the user says things like: 'create a new workspace', "
            "'make a workspace called X', 'new workspace outside', 'create a folder in home', "
            "'make a project in desktop'. "
            "The 'location' arg accepts keywords: 'home'/'outside' (= ~), 'desktop' (= ~/Desktop), "
            "'projects' (= ~/Projects, default), or any explicit path like '~/code'."
        ),
        "parameters": {
            "name": {"type": "string", "description": "Workspace folder name (e.g. 'myapp')", "required": True},
            "location": {"type": "string", "description": "Where to put it: 'home', 'desktop', 'projects', or a path", "required": False},
        },
    },
    {
        "name": "run_bash",
        "description": "Run a shell command. Asks for approval.",
        "parameters": {
            "command": {"type": "string", "description": "Shell command", "required": True},
            "timeout": {"type": "integer", "description": "Max seconds (default 30)", "required": False},
        },
    },
    {
        "name": "verify_code",
        "description": (
            "Run a syntax check on a file you just wrote or edited. "
            "Use this AFTER write_file or edit_file to confirm no syntax errors. "
            "Supports Python, JavaScript, TypeScript, JSON, Bash, YAML."
        ),
        "parameters": {
            "path": {"type": "string", "description": "Path to file to verify", "required": True},
            "language": {"type": "string", "description": "Language (auto-detected if omitted)", "required": False},
        },
    },
    {
        "name": "remember",
        "description": (
            "Save a lesson, convention, or important fact to project memory (MEMORY.md). "
            "Use this when you learn something useful for FUTURE sessions: "
            "code conventions, architecture decisions, gotchas, user preferences. "
            "Categories: 'conventions', 'architecture', 'gotchas', 'preferences', 'general'."
        ),
        "parameters": {
            "note": {"type": "string", "description": "Concise note to remember", "required": True},
            "category": {"type": "string", "description": "Category bucket", "required": False},
        },
    },
    {
        "name": "recall",
        "description": (
            "Read project memory (MEMORY.md). Useful at the start of a complex task "
            "to load conventions/lessons. Returns all memory or a single category."
        ),
        "parameters": {
            "category": {"type": "string", "description": "Optional category to filter", "required": False},
        },
    },
    {
        "name": "find_symbol",
        "description": (
            "Find a function/class/method by EXACT name across the workspace. "
            "Returns file:line + signature + docstring. INSTANT (no embedding). "
            "Use this FIRST when the user mentions a specific symbol by name."
        ),
        "parameters": {
            "name": {"type": "string", "description": "Symbol name (e.g. 'parse_llm_output')", "required": True},
        },
    },
    {
        "name": "list_symbols",
        "description": (
            "Outline a file: every function/class/method in declaration order with line ranges. "
            "Use this to understand a file's structure before reading or editing it."
        ),
        "parameters": {
            "file": {"type": "string", "description": "Workspace-relative path (e.g. 'agent/parser.py')", "required": True},
        },
    },
    {
        "name": "find_callers",
        "description": (
            "Find every chunk that references a symbol — excludes its definition. "
            "Essential for rename refactors and impact analysis before editing."
        ),
        "parameters": {
            "symbol_name": {"type": "string", "description": "Symbol to find references for", "required": True},
        },
    },
    {
        "name": "project_map",
        "description": (
            "Render a tree of the current workspace (folders + files). "
            "Use this to understand the project's layout. Respects .git, node_modules, etc."
        ),
        "parameters": {
            "max_depth": {"type": "integer", "description": "Tree depth (default 3, max 6)", "required": False},
        },
    },
    {
        "name": "plan_task",
        "description": (
            "BEFORE writing code for a multi-file task (build app, scaffold project, etc.), "
            "call this to get a structured plan. The plan must be approved by user before execution. "
            "Use this for ANY task that creates more than 2 files."
        ),
        "parameters": {
            "goal": {"type": "string", "description": "User's high-level goal", "required": True},
            "max_files": {"type": "integer", "description": "Max files in plan (default 10)", "required": False},
        },
    },
    {
        "name": "finish",
        "description": "Signal task is complete.",
        "parameters": {
            "summary": {"type": "string", "description": "What you did", "required": True},
        },
    },
]

TOOL_FUNCTIONS = {
    "search_code":  search_code,
    "read_file":    read_file,
    "write_file":   write_file,
    "edit_file":    edit_file,
    "insert_after": insert_after,
    "list_dir":     list_dir,
    "grep_files":   grep_files,
    "file_exists":  file_exists,
    "create_dir":   create_dir,
    "new_workspace": new_workspace,
    "run_bash":     run_bash,
    "verify_code":  verify_code,
    "find_symbol":   find_symbol,
    "list_symbols":  list_symbols,
    "find_callers":  find_callers,
    "project_map":   project_map,
    "remember":     remember,
    "recall":       recall,
    "plan_task":    plan_task,
}


def get_tool_descriptions() -> str:
    lines = []
    for tool in TOOL_SCHEMAS:
        params = ", ".join(
            f"{k}: {v['type']}{'?' if not v.get('required') else ''}"
            for k, v in tool["parameters"].items()
        )
        lines.append(f"  • {tool['name']}({params})")
        lines.append(f"    → {tool['description']}")
    return "\n".join(lines)


def dispatch(tool_name: str, args: dict) -> str:
    if tool_name not in TOOL_FUNCTIONS:
        return f"Error: Unknown tool '{tool_name}'"
    try:
        return str(TOOL_FUNCTIONS[tool_name](**args))
    except Exception as e:
        return f"Error running {tool_name}: {e}"
