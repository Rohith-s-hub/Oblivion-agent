"""
agent/demo.py - First-run demo / guided tour.

Runs when user types: oblivion demo
Prints a colorful walkthrough explaining Oblivion features without
needing API keys or full TUI launch. Final message: how to actually start.
"""
from __future__ import annotations

import os
import sys
import time


def _color(text, code):
    if os.getenv("NO_COLOR") or not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def _green(t):   return _color(t, "1;32")
def _cyan(t):    return _color(t, "1;36")
def _yellow(t):  return _color(t, "1;33")
def _magenta(t): return _color(t, "1;35")
def _dim(t):     return _color(t, "2")
def _bold(t):    return _color(t, "1")


BANNER = """
 \u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2557   \u2588\u2588\u2557\u2588\u2588\u2557\u2588\u2588\u2557   \u2588\u2588\u2557\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2557   \u2588\u2588\u2557
\u2588\u2588\u2554\u2550\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2551
\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2554\u2588\u2588\u2557 \u2588\u2588\u2551
\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551   \u2588\u2588\u2551\u255a\u2588\u2588\u2557 \u2588\u2588\u2554\u255d\u2588\u2588\u2551\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551\u255a\u2588\u2588\u2557\u2588\u2588\u2551
\u255a\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2551 \u255a\u2588\u2588\u2588\u2588\u2554\u255d \u2588\u2588\u2551\u255a\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2551 \u255a\u2588\u2588\u2588\u2588\u2551
 \u255a\u2550\u2550\u2550\u2550\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u2550\u2550\u255d  \u255a\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u255d \u255a\u2550\u255d  \u255a\u2550\u2550\u2550\u255d
"""


def _delay(seconds: float = 0.6):
    """Sleep unless --fast flag is set."""
    if "--fast" not in sys.argv:
        time.sleep(seconds)


def run_demo() -> None:
    """Print the guided demo. No API keys needed."""
    print(_cyan(BANNER))
    print(_dim("                  Welcome to the Oblivion Tour\n"))
    _delay(1.0)

    print(_bold("This 60-second tour shows what Oblivion can do."))
    print(_dim("(Press Ctrl+C anytime to exit)\n"))
    _delay(1.5)

    # === STEP 1 ===
    print(_magenta("\n\u25c6 STEP 1 / 6: Multi-Model AI"))
    print(_dim("\u2500" * 60))
    print()
    print("Oblivion supports " + _bold("13 LLMs") + " across 7 providers:")
    print()
    print(_dim("  Free:") + " Gemini 2.5 Flash, Groq Llama 3.3, Qwen3 Coder 480B,")
    print(_dim("        ") + " GPT-OSS, NVIDIA Nemotron 550B, and more")
    print(_dim("  Paid:") + " Claude Sonnet 4, GPT-4o, DeepSeek V3")
    print()
    print(_green("  Switch anytime: ") + _bold("/model gemini-flash"))
    print(_green("  Auto-fallback:  ") + "If one fails, next in chain takes over silently")
    _delay(2.0)

    # === STEP 2 ===
    print(_magenta("\n\u25c6 STEP 2 / 6: Voice In + Out (M.E.E.R.A.)"))
    print(_dim("\u2500" * 60))
    print()
    print("Press " + _bold("Ctrl+T") + " to talk to Meera (the AI personality).")
    print("She transcribes your speech via Whisper, processes your")
    print("request, and replies with a natural voice.")
    print()
    print(_dim("  Free:    ") + "Microsoft Edge TTS (no API key needed)")
    print(_dim("  Premium: ") + "ElevenLabs (set ELEVENLABS_API_KEY)")
    _delay(2.0)

    # === STEP 3 ===
    print(_magenta("\n\u25c6 STEP 3 / 6: Hybrid Code Search"))
    print(_dim("\u2500" * 60))
    print()
    print("Ask: " + _yellow("\"where is the authentication logic?\""))
    print()
    print("Oblivion uses a 3-layer search to find the answer:")
    print(_green("  1. Exact symbol lookup") + " (SQLite FTS5, instant)")
    print(_green("  2. Full-text search") + " (signatures + docstrings)")
    print(_green("  3. Semantic embeddings") + " (ChromaDB + AST chunking)")
    print()
    print("Results ranked by confidence. Symbol matches always win.")
    _delay(2.0)

    # === STEP 4 ===
    print(_magenta("\n\u25c6 STEP 4 / 6: 22 Tools, Real Code Changes"))
    print(_dim("\u2500" * 60))
    print()
    print("Meera can: " + _dim("read, write, edit, grep, run bash, search,"))
    print("           " + _dim("verify code, manage servers, remember,..."))
    print()
    print(_yellow("Every destructive op shows a diff and asks Y/n first.") + " No surprises.")
    print()
    print(_dim("  Example: ") + _yellow("\"create a Flask app with a /health endpoint\""))
    print("  \u2192 Meera writes the file, shows diff, you approve")
    _delay(2.0)

    # === STEP 5 ===
    print(_magenta("\n\u25c6 STEP 5 / 6: Claude Desktop Integration (MCP)"))
    print(_dim("\u2500" * 60))
    print()
    print("Oblivion ships an MCP server. Claude Desktop can use")
    print("Oblivion's 10 read-only tools (search, find_symbol, etc.)")
    print("on YOUR codebase, without launching the TUI.")
    print()
    print(_green("  Start the server: ") + _bold("oblivion mcp"))
    print(_green("  Setup guide:      ") + _dim("see README"))
    _delay(2.0)

    # === STEP 6 ===
    print(_magenta("\n\u25c6 STEP 6 / 6: Self-Updating"))
    print(_dim("\u2500" * 60))
    print()
    print("Inside the TUI:")
    print(_green("  /update         ") + "Check PyPI for newer version")
    print(_green("  /update install ") + "Upgrade in one click (no terminal exit)")
    print()
    print("Stay current with zero friction.")
    _delay(2.0)

    # === FINAL ===
    print("\n" + _green("\u2550" * 60))
    print(_bold(_green("  Tour Complete!")) + " " + _dim("Ready to actually try it?"))
    print(_green("\u2550" * 60))
    print()
    print(_bold("Start Oblivion:"))
    print("  " + _cyan("$ oblivion"))
    print()
    print(_bold("If it's your first launch, the setup wizard will:"))
    print("  1. Help you pick a free LLM provider (Gemini recommended)")
    print("  2. Save your API key to ~/.oblivion/config.env")
    print("  3. Optionally enable voice")
    print()
    print(_yellow("\u2605 If Oblivion looks cool, give it a star:"))
    print("  " + _cyan("https://github.com/Rohith-s-hub/Oblivion-agent"))
    print()
    print(_dim("\"Code is conversation. Make it natural.\"") + _dim(" - Meera"))
    print()


if __name__ == "__main__":
    try:
        run_demo()
    except KeyboardInterrupt:
        print("\n\nTour exited. Run " + _bold("oblivion") + " to start.\n")
        sys.exit(0)
