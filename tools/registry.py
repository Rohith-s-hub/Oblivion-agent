from tools.filesystem import read_file, write_file, list_dir, grep_files, file_exists, create_dir
from tools.bash import run_bash
from tools.edit_file import edit_file, insert_after
from tools.search_code import search_code

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
        "name": "run_bash",
        "description": "Run a shell command. Asks for approval.",
        "parameters": {
            "command": {"type": "string", "description": "Shell command", "required": True},
            "timeout": {"type": "integer", "description": "Max seconds (default 30)", "required": False},
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
    "run_bash":     run_bash,
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
