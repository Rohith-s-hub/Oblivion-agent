import subprocess
import os
from dotenv import load_dotenv

load_dotenv()

BLOCKED = {"rm -rf /", "rm -rf ~", ":(){ :|:& };:", "mkfs", "dd if=/dev/zero", "sudo rm -rf"}


def run_bash(command: str, timeout: int = 30) -> str:
    if any(b in command.lower() for b in BLOCKED):
        return f"Blocked command: {command}"
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=os.getenv("WORKSPACE_DIR", ".")
        )
        parts = []
        if result.stdout.strip():
            parts.append(result.stdout.strip())
        if result.stderr.strip():
            parts.append(f"[stderr]\n{result.stderr.strip()}")
        if result.returncode != 0:
            parts.append(f"[exit code: {result.returncode}]")
        return "\n".join(parts) if parts else "(no output)"
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"
