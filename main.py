from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from agent.core import Agent
from db.store import init_db, create_session, save_message

console = Console()


def main():
    init_db()
    session_id = create_session()

    console.print(Panel(
        "[bold cyan]AI Coding Agent[/bold cyan]\n"
        "[dim]Powered by qwen3-coder via Ollama[/dim]\n\n"
        "[green]exit[/green] — quit  |  [green]reset[/green] — new session  |  [green]history[/green] — show messages",
        title="Agent Ready",
        border_style="cyan"
    ))
    console.print(f"[dim]Session: {session_id}[/dim]\n")

    agent = Agent()

    while True:
        try:
            user_input = Prompt.ask("\n[bold green]You[/bold green]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input.strip():
            continue

        cmd = user_input.lower().strip()

        if cmd in ("exit", "quit", "bye"):
            console.print("[dim]Goodbye![/dim]")
            break

        if cmd == "reset":
            agent.reset()
            session_id = create_session()
            console.print("[yellow]Conversation reset.[/yellow]")
            continue

        if cmd == "history":
            for msg in agent.conversation:
                color = "green" if msg["role"] == "user" else "blue"
                console.print(f"[{color}]{msg['role'].upper()}:[/{color}] {msg['content'][:200]}")
            continue

        save_message(session_id, "user", user_input)
        response = agent.run(user_input)
        save_message(session_id, "assistant", response)


if __name__ == "__main__":
    main()
