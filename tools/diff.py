import difflib
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()


def make_diff(original: str, updated: str, filename: str = "file") -> str:
    """Generate a unified diff string between original and updated content."""
    original_lines = original.splitlines()
    updated_lines = updated.splitlines()

    diff = difflib.unified_diff(
        original_lines,
        updated_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm="",
    )
    return "\n".join(diff)


def print_diff(diff_str: str, filename: str = "file"):
    """Pretty-print a unified diff with color."""
    if not diff_str.strip():
        console.print("[dim]  (no changes)[/dim]")
        return

    output = Text()
    for line in diff_str.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            output.append(line + "\n", style="bold white")
        elif line.startswith("@@"):
            output.append(line + "\n", style="bold cyan")
        elif line.startswith("+"):
            output.append(line + "\n", style="bold green")
        elif line.startswith("-"):
            output.append(line + "\n", style="bold red")
        else:
            output.append(line + "\n", style="dim white")

    console.print(Panel(
        output,
        title=f"[yellow]Diff: {filename}[/yellow]",
        border_style="yellow",
        expand=False,
    ))


def print_new_file(content: str, filename: str):
    """Show preview of a brand new file being created."""
    lines = content.splitlines()
    numbered = "\n".join(f"{i+1:4}  {line}" for i, line in enumerate(lines))

    console.print(Panel(
        Text(numbered, style="green"),
        title=f"[green]New file: {filename}[/green]",
        border_style="green",
        expand=False,
    ))


def ask_approval(action: str) -> bool:
    """Ask user to approve a change. Returns True if approved."""
    console.print()
    response = input(f"  Apply {action}? [y/N]: ").strip().lower()
    return response in ("y", "yes")
