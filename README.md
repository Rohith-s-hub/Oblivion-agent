# OBLIVION

**Terminal AI Coding Agent with Voice, RAG, and Multi-Model Support**

*Powered by M.E.E.R.A. (Multi-modal Engineering and Reasoning Assistant)*

[![PyPI version](https://img.shields.io/pypi/v/oblivion-agent.svg)](https://pypi.org/project/oblivion-agent/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![GitHub](https://img.shields.io/badge/github-Rohith--s--hub-blue.svg)](https://github.com/Rohith-s-hub/Oblivion-agent)

*"Code is conversation. Make it natural."* - Meera

---

## Table of Contents

- [What is Oblivion?](#what-is-oblivion)
- [Why Oblivion?](#why-oblivion)
- [Features](#features)
- [Quick Start](#quick-start)
- [Supported Models](#supported-models)
- [Slash Commands](#slash-commands)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Voice Setup](#voice-setup)
- [Claude Desktop Integration (MCP)](#claude-desktop-integration-mcp)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [CLI Subcommands](#cli-subcommands)
- [Troubleshooting](#troubleshooting)
- [Version History](#version-history)
- [Development](#development)
- [Contributing](#contributing)
- [Credits and License](#credits-and-license)

---

## What is Oblivion?

Oblivion is a **terminal-based AI coding assistant** that lives inside your codebase, understands it semantically, and helps you build software through natural conversation - typed or spoken.

Meet **Meera** (M.E.E.R.A. - Multi-modal Engineering and Reasoning Assistant), the AI personality that powers Oblivion. She reads your code, writes files, runs commands, searches semantically, remembers your project conventions, and speaks back to you with a natural voice.

**Oblivion is the shell. Meera is the mind.**

### Who is this for?

- **Solo developers** who want an AI pair-programmer in their terminal
- **Students** learning to code who want an interactive tutor
- **Teams** wanting a self-hosted, privacy-respecting coding assistant
- **Anyone** tired of copy-pasting between ChatGPT and their editor

---

## Why Oblivion?

| Feature | Oblivion | Cursor/Copilot | Claude Desktop | ChatGPT |
|---------|----------|----------------|----------------|---------|
| Runs in terminal | Yes | No | No | No |
| Voice input + output | Yes | No | No | No |
| Multi-model with auto-fallback | Yes | Partial | No | No |
| Symbol-aware code search | Yes | Yes | No | No |
| Semantic codebase search | Yes | Yes | No | No |
| Persistent project memory | Yes | No | No | No |
| MCP server (for Claude) | Yes | No | N/A | No |
| Self-updating (/update) | Yes | Yes | No | No |
| Free to run | Yes | No | No | No |
| Open source (MIT) | Yes | No | No | No |
| pip-installable | Yes | No | No | No |

---

## Features

### Voice In and Out

Press **Ctrl+T** to talk to Meera. She transcribes your speech via **Whisper** (OpenAI speech-to-text, runs locally), processes your request, and speaks her response back using **Edge TTS** (free Microsoft neural voices) or **ElevenLabs** (premium human-like voices).

- Press-to-talk mode (Ctrl+T to start, Ctrl+T to stop)
- Automatic silence detection
- Indian English accent optimized (biased toward coding terms and Indian names)
- 8 voice personas: Aria, Jenny, Sonia, Natasha, Emma, Michelle, Guy, Ryan
- Voice settings via `/meera on|off|test|persona <name>|rate +20%|name <your_name>`

### 13 LLM Backends with Auto-Fallback

Oblivion talks to **13 language models** across 7 providers. If one rate-limits or goes down, the next in the chain takes over silently. You never notice.

**The fallback chain (tried in order):**

1. Your manually selected `/model` choice (always tried first)
2. Qwen3 Coder 480B via OpenRouter (FREE, 1M context)
3. OpenAI GPT-OSS 120B via OpenRouter (FREE)
4. Meta Llama 3.3 70B via OpenRouter (FREE)
5. Qwen3 Coder 480B via Ollama Cloud (FREE)
6. Groq Llama 3.3 70B (FREE, blazing fast)
7. Groq GPT-OSS 120B (FREE)
8. Gemini 2.5 Flash (FREE, 1M context)
9. Cerebras Llama 3.3 70B (FREE)

Failed models get a **5-minute cooldown** before being retried. UI shows a yellow notification when a swap happens.

### Hybrid Code Search (3-Layer)

When you ask "where is the authentication logic?", Oblivion uses a 3-layer search:

1. **Exact symbol lookup** (instant, SQLite FTS5) - finds functions/classes by exact name
2. **Full-text search** (FTS5 on signatures + docstrings + code) - finds mentions
3. **Semantic embedding search** (ChromaDB + all-minilm) - finds conceptually related code

Results merged, deduplicated, and ranked by confidence. Symbol matches always win over semantic matches.

### AST-Aware Code Chunking

Oblivion uses **Abstract Syntax Tree parsing** to split code semantically:

- **Python**: functions, classes, methods, module headers (ast module)
- **JavaScript/TypeScript**: functions, arrow functions, classes, React components (regex)
- **HTML**: section/main/header/footer/article blocks
- **CSS**: rule blocks (selector + body)
- **Markdown**: heading-based sections
- **Other files**: 50-line overlapping blocks (fallback)

Each chunk knows its type, name, signature, line range, docstring, and parent class.

### 22 Tools

**File Operations (6):** read_file, write_file, edit_file, insert_after, list_dir, file_exists

**Code Navigation (5):** search_code, find_symbol, list_symbols, find_callers, project_map

**Shell and Build (5):** run_bash, start_server, list_servers, stop_server, create_dir

**Intelligence (4):** verify_code, remember, recall, plan_task

**Workspace (2):** new_workspace, grep_files

### Safety: Approval Gates

Every destructive operation shows a diff preview and waits for explicit approval:

- File writes: full unified diff (green = added, red = removed)
- File edits: before/after with line numbers
- Shell commands: exact command preview
- Dangerous commands (rm -rf, git push --force, DROP TABLE): hardcoded extra confirmation

Press Y or Enter to approve, N or Escape to deny.

### Persistent Project Memory

Meera automatically saves project conventions to `MEMORY.md` in your workspace root. Next session, she reads it first and applies those lessons. Over time she becomes an expert on YOUR specific codebase.

Memory categorized: conventions, architecture, gotchas, preferences, general.
Commands: `/memory show|stats|edit|clear`

### Session History (Ctrl+G)

Press **Ctrl+G** to open a floating overlay with all past conversations. Shows session ID, message preview, count, and timestamp. Arrow keys to navigate, Enter to load, Escape to close. Loaded sessions become active so new messages continue them.

### Knowledge Packs (13 built-in)

| Pack | What it teaches Meera |
|------|----------------------|
| react | Hooks, state, component patterns, common errors |
| nextjs | App Router, server components, data fetching, ISR |
| vue | Composition API, Pinia, Vue Router, reactivity |
| tailwind | Utility patterns, responsive design, dark mode |
| typescript | Type patterns, generics, discriminated unions |
| django | ORM, views, serializers, migrations, signals |
| flask | Blueprints, SQLAlchemy, request context |
| fastapi | Pydantic, dependency injection, async, middleware |
| docker | Multi-stage builds, layer caching, compose |
| security | Auth, JWT, CSRF, XSS, SQL injection prevention |
| testing | pytest, vitest, mocking, fixtures, TDD |
| database | SQL optimization, N+1, indexing, transactions |
| debugging | Stack trace reading, profiling, common errors |
| deployment | CI/CD, Nginx, Vercel, Netlify |

Auto-loaded based on workspace (package.json, requirements.txt) and user intent. Max 2 packs at once to control token budget.

### Self-Updating (/update)

Check for newer versions and upgrade in-app:

- `/update` - check PyPI for newer version
- `/update install` - run pip install --upgrade in-app
- `/update changelog` - GitHub release notes link

Upgrade runs in background thread so UI stays responsive.

### MCP Server (Claude Desktop Integration)

Oblivion exposes **10 read-only tools** via Model Context Protocol. Claude Desktop, Cursor, Zed can use Oblivion code understanding without launching the TUI.

Run: `oblivion mcp` to start the stdio MCP server.

### Cyberpunk TUI

Built with [Textual](https://textual.textualize.io/):

- Animated boot sequence with typewriter effect
- Braille spinner animations for active tools
- Status bar (model, workspace, tokens, messages, step count)
- Auto-refreshing file tree panel
- Agent log panel with real-time tool tracking
- Slash command autocomplete dropdown
- Cyberpunk color palette: muted blues, golds, grays

---

## Quick Start

### Install

Basic install (text mode, no voice):

    pip install oblivion-agent

With voice support (adds Whisper + sounddevice, ~1.5GB Whisper model on first use):

    pip install "oblivion-agent[voice]"

With premium ElevenLabs voice:

    pip install "oblivion-agent[all]"

### First Run

    oblivion

Setup wizard walks you through:

1. Pick a provider (Gemini recommended - free, 1500 req/day)
2. Paste your API key (signup links provided)
3. Enable voice (optional)

Config saved to `~/.oblivion/config.env`. Edit anytime.

### Talk to Meera

Type naturally:

    > where is the ReAct loop?
    > add error handling to the parser
    > build me a landing page with HTML, CSS, JS
    > refactor authentication to use JWT
    > what does this codebase do?

Or press **Ctrl+T** and speak. She transcribes, thinks, acts, and replies by voice.

---

## Supported Models

Oblivion supports 13 LLMs across 7 providers. Switch anytime with `/model <name>`.

### Free Models

| Name | Provider | Model | Context | Speed |
|------|----------|-------|---------|-------|
| qwen-coder | Ollama Cloud | Qwen3 Coder 480B | 1M | Medium |
| gemini-flash | Google | Gemini 2.5 Flash | 1M | Fast |
| gemini-pro | Google | Gemini 2.5 Pro | 2M | Medium |
| groq-llama | Groq | Llama 3.3 70B | 128K | Blazing |
| groq-deepseek | Groq | DeepSeek R1 Distill 70B | 128K | Blazing |
| groq-gpt-oss | Groq | GPT-OSS 120B | 128K | Blazing |
| qwen3-coder-or | OpenRouter | Qwen3 Coder 480B | 1M | Fast |
| nemotron-ultra | OpenRouter | NVIDIA Nemotron 3 Ultra 550B | 1M | Medium |
| gpt-oss-or | OpenRouter | OpenAI GPT-OSS 120B | 131K | Fast |
| llama-3.3-or | OpenRouter | Meta Llama 3.3 70B | 131K | Fast |

### Paid Models

| Name | Provider | Model | Cost |
|------|----------|-------|------|
| claude-sonnet | Anthropic | Claude Sonnet 4 | $3/$15 per 1M tokens |
| gpt-4o | OpenAI | GPT-4o | $2.50/$10 per 1M tokens |
| deepseek | DeepSeek | DeepSeek V3 | $0.14 per 1M tokens |

### Adding API Keys

Add to `~/.oblivion/config.env`:

    GEMINI_API_KEY=AIzaSy...         # aistudio.google.com/apikey
    GROQ_API_KEY=gsk_...             # console.groq.com/keys
    OPENROUTER_API_KEY=sk-or-v1-...  # openrouter.ai/keys
    ANTHROPIC_API_KEY=sk-ant-...     # console.anthropic.com
    OPENAI_API_KEY=sk-...            # platform.openai.com
    DEEPSEEK_API_KEY=sk-...          # platform.deepseek.com

---

## Slash Commands

Type `/` in the input box to see the autocomplete dropdown.

### General

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/clear` | Clear chat history |
| `/quit` | Exit Oblivion |
| `/stats` | Token usage, session info, model details |

### Models

| Command | Description |
|---------|-------------|
| `/model` | List all available models with status |
| `/model <name>` | Switch LLM (e.g. `/model gemini-flash`) |
| `/model reset` | Clear exhausted-models cache |

### Workspace

| Command | Description |
|---------|-------------|
| `/workspace` | Show current workspace path |
| `/workspace <path>` | Switch to a different directory |
| `/newproject <name>` | Create ~/Projects/name/ and switch to it |
| `/openproject <name>` | Open an existing project |
| `/projects` | List all projects in ~/Projects/ |

### Code Intelligence

| Command | Description |
|---------|-------------|
| `/index` | Re-index workspace (incremental) |
| `/index status` | Show chunk count and index path |
| `/index force` | Full re-index (re-embed everything) |
| `/verify <path>` | Syntax-check a file |
| `/memory` | View workspace memory (MEMORY.md) |
| `/memory stats` | Memory file statistics |
| `/memory clear` | Delete all project memory |

### Voice (Meera)

| Command | Description |
|---------|-------------|
| `/voice` | Start voice recording (same as Ctrl+T) |
| `/voice status` | Show Whisper model + recording state |
| `/voice devices` | List audio input devices |
| `/voice model <size>` | Switch Whisper model (tiny/small/medium/large) |
| `/meera` | M.E.E.R.A. status (provider, voice, name) |
| `/meera on` | Enable voice replies |
| `/meera off` | Disable voice replies |
| `/meera stop` | Stop current speech |
| `/meera test` | Test current voice |
| `/meera persona <name>` | Switch voice (aria/jenny/sonia/natasha/emma/michelle) |
| `/meera name <name>` | Change how Meera addresses you |
| `/meera rate +20%` | Adjust speech rate |

### Sessions

| Command | Description |
|---------|-------------|
| `/save <name>` | Save current session to disk |
| `/load <name>` | Resume a saved session |
| `/sessions` | List all saved sessions |
| **Ctrl+G** | Open session history picker (floating overlay) |

### Automation

| Command | Description |
|---------|-------------|
| `/auto build` | Detect project type and run build pipeline |
| `/auto test` | Run tests (pytest/vitest/npm test) |
| `/auto serve` | Install deps + start dev server |
| `/auto clean` | Remove build artifacts and caches |
| `/auto check` | Run linting and type checking |
| `/continue` | Resume previous task with fresh iteration budget |

### Updates

| Command | Description |
|---------|-------------|
| `/update` | Check PyPI for newer version |
| `/update install` | Upgrade to latest via pip (in-app) |
| `/update changelog` | Show release notes link |

### File Watcher

| Command | Description |
|---------|-------------|
| `/watch` | Toggle file watcher (auto-reindex) |
| `/watch on` | Enable auto-reindex |
| `/watch off` | Disable auto-reindex |
| `/watch status` | Show watcher state |

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| **Ctrl+T** | Toggle voice recording (press-to-talk) |
| **Ctrl+G** | Open session history picker |
| **Ctrl+P** | Open Textual command palette |
| **Ctrl+L** | Clear chat panel |
| **Ctrl+N** | New session |
| **Ctrl+R** | Reset conversation |
| **Ctrl+H** | Show help |
| **Ctrl+Q** | Quit |

---

## Voice Setup

Voice is optional but powerful.

### Requirements

- `ffmpeg` installed: `sudo apt install ffmpeg` (Linux) / `brew install ffmpeg` (macOS)
- Working microphone
- ~1.5GB free disk for Whisper small model (downloaded on first use)

### Install with Voice

    pip install "oblivion-agent[voice]"           # Whisper + sound libs
    pip install "oblivion-agent[premium-voice]"   # ElevenLabs (optional)

### Test it

Inside Oblivion: `/meera test` - should hear her speak.

### Press-to-Talk Flow

1. Press **Ctrl+T** - recording starts
2. Speak your message
3. Press **Ctrl+T** again - recording stops, transcribes
4. Text appears in input box - review or edit
5. Press **Enter** to submit
6. Meera processes and speaks her answer back

---

## Claude Desktop Integration (MCP)

Oblivion ships an MCP server. Claude Desktop can use Oblivion 10 read-only tools directly.

### Setup (one-time)

1. Install Oblivion: `pip install oblivion-agent`

2. Find Claude Desktop config file:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Linux: `~/.config/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%/Claude/claude_desktop_config.json`

3. Add this JSON:

        {
          "mcpServers": {
            "oblivion": {
              "command": "oblivion",
              "args": ["mcp"],
              "env": { "WORKSPACE_DIR": "/absolute/path/to/your/project" }
            }
          }
        }

4. Restart Claude Desktop. Done!

### Exposed Tools (read-only)

| Tool | What it does |
|------|--------------|
| read_file | Read any file in workspace |
| list_dir | List directory contents |
| grep_files | Exact-text search across files |
| file_exists | Check if path exists |
| search_code | Hybrid semantic + symbol search |
| find_symbol | Exact function/class lookup |
| list_symbols | Outline a file (every function/class) |
| find_callers | Find every reference to a symbol |
| project_map | Tree view of workspace |
| recall | Read project memory (MEMORY.md) |

Write tools (write_file, edit_file, run_bash) NOT exposed via MCP for safety.

### Testing MCP Setup

    npx -y @modelcontextprotocol/inspector oblivion mcp

Opens browser UI to test every tool individually.

---

## Architecture

### High-Level Flow

    You --voice/text--> Oblivion TUI --> AgentRuntime --> LLM (Gemini/Groq/...)
                              |                |
                              |                +--> Tool dispatch (22 tools)
                              |
                              +--> Meera voice --> ElevenLabs/Edge TTS --> speaker

### The ReAct Loop

Agent loop (`agent/runtime.py`) is a clean ReAct (Reasoning + Acting) cycle:

1. LLM produces THOUGHT + ACTION (JSON tool call) or FINAL_ANSWER
2. Parser extracts structured output (`agent/parser.py`)
3. Tool executes via dispatch (with approval if destructive)
4. Result becomes next OBSERVATION in the conversation
5. Loop until FINAL_ANSWER or max iterations

**Safety features:**

- Loop detection (same tool+args 3x in row = forced stop)
- Exploration guard (5 read-only calls in row = forced action)
- Conversation compression (auto-summarize after 10 messages)
- Garbage output detection (catches model context overflow)
- Max iteration budget (40 default, 50 for complex tasks)

### File Layout

    ~/.oblivion/                    Config directory
      config.env                    API keys and settings
      agent.db                      Session history (SQLite)
      symbols.db                    Code symbol index (SQLite + FTS5)
      sessions/                     Per-session JSONL event logs
      file_hashes.json              Incremental indexing tracker

    ~/.cache/oblivion/              Cache directory
      chroma/                       Vector embeddings (ChromaDB)
      whisper/                      Whisper model weights (~1.5GB)

    <workspace>/MEMORY.md           Per-project memory file

### Package Structure

    agent/
      core.py             Agent class + system prompt
      runtime.py          Async ReAct loop (AgentRuntime)
      llm.py              LLMClient with auto-fallback
      parser.py           Extracts THOUGHT/ACTION/FINAL_ANSWER
      rag.py              ChromaDB + embeddings + indexing
      code_chunker.py     AST-aware code chunking
      symbol_index.py     SQLite symbol index (FTS5)
      brain.py            Memory + verification + planning + compression
      models.py           Model registry (13 models)
      voice.py            Whisper STT + VoiceRecorder
      friday.py           M.E.E.R.A. TTS (ElevenLabs + Edge TTS)
      watcher.py          File watcher (watchdog)
      paths.py            Centralized path resolution
      setup_wizard.py     First-run interactive setup
      updater.py          PyPI version checker + self-upgrade

    tools/                22 tool implementations
    mcp_server/           Model Context Protocol server
    knowledge/            13 domain knowledge packs
    ui/app.py             Textual TUI (~2100 lines)
    db/store.py           SQLite session storage

---

## Configuration

All config in `~/.oblivion/config.env`. Key settings:

    # LLM
    DEFAULT_MODEL=gemini/gemini-2.5-flash
    GEMINI_API_KEY=your-key-here

    # Voice
    FRIDAY_ENABLED=true
    FRIDAY_NAME=boss
    FRIDAY_VOICE=aria
    OBLIVION_PRELOAD_VOICE=1

    # Safety
    REQUIRE_APPROVAL_FOR_WRITE=true
    REQUIRE_APPROVAL_FOR_BASH=true

    # Workspace
    WORKSPACE_DIR=/path/to/your/project

    # Performance
    MAX_ITERATIONS=40
    MAX_TOKENS=1500
    TEMPERATURE=0.05
    PARALLEL_EMBEDDINGS=8
    EMBED_MODEL=all-minilm

### Environment Overrides (for containers/CI)

    OBLIVION_HOME=/custom/path       Override ~/.oblivion
    OBLIVION_CACHE=/custom/cache     Override ~/.cache/oblivion

---

## CLI Subcommands

    oblivion                Launch the TUI (default)
    oblivion mcp            Run as MCP server (for Claude Desktop)
    oblivion init           Re-run the setup wizard
    oblivion --version      Print version
    oblivion --help         Print help

---

## Troubleshooting

### "bad value(s) in fds_to_keep"

Set `OBLIVION_PRELOAD_VOICE=1` in `~/.oblivion/config.env`. Whisper must load before Textual takes over the terminal.

### "GeminiException 503 UNAVAILABLE"

Gemini overloaded. Auto-fallback should swap to next model. If not, `/model groq-llama` to manually switch.

### "Watcher failed to start: inotify limit reached"

    echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
    sudo sysctl -p

### Voice not working

1. Check ffmpeg: `sudo apt install ffmpeg` / `brew install ffmpeg`
2. Check mic: `/voice devices` inside Oblivion
3. Check Whisper: `/voice status`
4. Ensure `pip install "oblivion-agent[voice]"` was used

### Models showing 401 errors

API key invalid/expired. Get new one:

- Gemini: https://aistudio.google.com/apikey
- Groq: https://console.groq.com/keys
- OpenRouter: https://openrouter.ai/keys

Update `~/.oblivion/config.env` with the new key.

### Voice transcription gets my name wrong

Edit `initial_prompt` in `agent/voice.py` to bias Whisper toward your vocabulary.

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| v0.1.0 | Jun 2026 | Working agent + diff approval + RAG |
| v0.5.0 | Jun 2026 | Anti-hallucination (forces read_file) |
| v1.0.0 | Jun 2026 | OBLIVION rebrand + cyberpunk theme |
| v1.5.0 | Jun 2026 | Voice input (Whisper medium) |
| v1.6.0 | Jun 2026 | M.E.E.R.A. voice personality (Edge TTS) |
| v1.7.0 | Jun 2026 | ElevenLabs premium voice |
| v2.0.0 | Jun 2026 | BRAIN: Memory + Verify + Planning |
| v2.2.0 | Jun 2026 | Gemini + RAG cap + sliding context |
| v2.5.0 | Jun 2026 | Status bar + /demo command |
| v2.6.0 | Jun 2026 | Distribution ready: pip-installable |
| v2.7.0 | Jun 2026 | Centralized paths + migration + setup wizard |
| v2.8.0 | Jun 2026 | Session history sidebar (Ctrl+G) |
| v2.9.0 | Jun 2026 | MCP server + subcommand CLI |
| v2.10.0 | Jun 2026 | OpenRouter (4 free models) + /update command |
| v2.10.1 | Jun 2026 | /update autocomplete fix |

---

## Development

### Setup from source

    git clone https://github.com/Rohith-s-hub/Oblivion-agent.git
    cd Oblivion-agent
    uv sync
    uv run python -m ui.app

### Run tests

    uv run pytest

### Build wheel

    uv build

### Publish to PyPI

    UV_PUBLISH_TOKEN=$(cat ~/.oblivion/.pypi_token) uv publish

---

## Contributing

Contributions welcome!

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/amazing-thing`)
3. Make your changes
4. Test with `uv run python -m ui.app`
5. Commit with descriptive messages
6. Push and open a Pull Request

### Code style

- Python 3.11+ features welcome
- Type hints encouraged
- Docstrings on all public functions
- Surgical patches preferred over file rewrites (especially `ui/app.py` ~2100 lines)

### Adding a new model

1. Add entry to `agent/models.py` MODELS dict
2. Add to `agent/llm.py` FALLBACK_CHAIN if free
3. Test with `/model <name>` inside Oblivion
4. Update `.env.example` with the API key env var

### Adding a new tool

1. Implement in `tools/` (new file or existing)
2. Add schema + function to `tools/registry.py`
3. Add to system prompt tool descriptions in `agent/core.py`
4. Test the tool manually first, then via the agent

---

## Credits and License

### License

MIT - see [LICENSE](LICENSE).

### Built by

**R. Rohit** (BSc CS, Sivakasi, India) - over a series of intense hacking sessions, with collaboration from Claude (Anthropic).

### Powered by

- [litellm](https://github.com/BerriAI/litellm) - unified LLM API
- [Textual](https://textual.textualize.io/) - TUI framework
- [ChromaDB](https://www.trychroma.com/) - vector embeddings
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) - speech-to-text
- [edge-tts](https://github.com/rany2/edge-tts) - free Microsoft TTS
- [ElevenLabs](https://elevenlabs.io/) - premium voice synthesis
- [MCP SDK](https://github.com/anthropics/mcp) - Model Context Protocol
- [OpenRouter](https://openrouter.ai/) - unified model gateway

---

## Achievements

- **Published on PyPI** as [oblivion-agent](https://pypi.org/project/oblivion-agent/)
- **Open source** on [GitHub](https://github.com/Rohith-s-hub/Oblivion-agent)
- **3 PyPI releases in 24 hours** (v2.9.0, v2.10.0, v2.10.1)
- **13 LLM backends** with auto-fallback
- **22 tools** for the AI to call
- **10 MCP tools** exposed for Claude Desktop
- **13 knowledge packs** built-in
- **Built from scratch** on a Lenovo V15 (13GB RAM, no GPU)
- **Self-updating** via in-app `/update install`
- **MIT licensed** - free for everyone

---

**Star the repo if Oblivion helped you ship something cool!**

[GitHub](https://github.com/Rohith-s-hub/Oblivion-agent) | [PyPI](https://pypi.org/project/oblivion-agent/) | [Issues](https://github.com/Rohith-s-hub/Oblivion-agent/issues)

*"Code is conversation. Make it natural."* - Meera

