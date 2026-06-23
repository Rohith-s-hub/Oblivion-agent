# OBLIVION

Terminal AI coding agent with voice, RAG, and multi-model support.
Powered by Meera.

## Install

    pip install oblivion-agent

With voice:

    pip install "oblivion-agent[voice]"

## First Run

    oblivion

A setup wizard will ask for your LLM provider (Gemini recommended, free).

## Features

- Voice in (Whisper) and out (Edge TTS / ElevenLabs)
- 9 LLM backends with auto-fallback (Gemini, Groq, Claude, GPT-4o, DeepSeek, Ollama, Cerebras)
- Hybrid code search: exact symbol + full-text + semantic embeddings
- 22 tools: filesystem, bash, symbol navigation, code verification, project memory
- Built-in knowledge packs (React, Django, FastAPI, Docker, security, more)
- Cyberpunk TUI with slash commands, file watcher, status bar
- Workspace memory persists across sessions (MEMORY.md per project)

## Slash Commands

- /help - all commands
- /model - switch LLM
- /voice - voice settings
- /meera on|off|test - toggle voice replies
- /index - reindex workspace
- /openproject <name> - switch project
- /newproject <name> - create project
- /memory - view workspace memory
- /stats - session info

## Config

Lives at ~/.oblivion/config.env

## License

MIT
