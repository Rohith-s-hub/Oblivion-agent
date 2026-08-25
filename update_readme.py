import os
from pathlib import Path

readme_path = Path("README.md")

content = """# OBLIVION AI 🔮
### Open-Source Terminal AI Coding Agent with Voice, 3-Layer RAG, and MCP Server

[![PyPI version](https://img.shields.io/pypi/v/oblivion-agent.svg?color=8b5cf6)](https://pypi.org/project/oblivion-agent/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-22d3ee.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Downloads](https://img.shields.io/pypi/dm/oblivion-agent?color=67e8f9)](https://pypi.org/project/oblivion-agent/)

> *"Code is conversation. Make it natural."* — **M.E.E.R.A.**

Oblivion AI is a terminal-native, open-source AI coding agent built as a privacy-respecting, zero-cost alternative to proprietary tools like **Cursor, Copilot, and Claude Code**. It lives inside your terminal, understands your local codebase semantically, executes multi-file edits atomically, and responds via text or natural voice.

---

## 🌟 Key Highlights

* 🤖 **M.E.E.R.A. Core:** Powered by Multi-modal Engineering and Reasoning Assistant.
* ⚡ **Multi-Model Resilience:** Auto-fallback chain across **Ollama Cloud, Gemini 2.5, and Groq** with smart rate-limit cooldowns.
* 🎙️ **Voice I/O & Wake Word:** Background listening (`Hey Jarvis`), silence auto-stop (3s pause), and 8 neural voice personas via Edge-TTS / ElevenLabs.
* 🔍 **3-Layer Hybrid Search:** Instant exact symbol lookup (SQLite FTS5) + Full-text search + Vector semantic embeddings (ChromaDB).
* 🔌 **Built-in MCP Server:** Exposes 10 read-only code intelligence tools directly to **Claude Desktop, Cursor, and Zed**.
* 🛡️ **3-Tier Safety System:** Read, Mutate, and Destructive tiers with unified diff previews before execution.
* 🧰 **38 Agent Tools:** Full Git suite, test runners, multi-file atomic `batch_edit`, DuckDuckGo web search, PyPI/npm lookup, and background server management.
* 📟 **Intel 8085 CPU Emulator:** Built-in microprocessor simulator and assembler.

---

## 🎬 Live Demo

[![asciicast](https://asciinema.org/a/JWUP4sCednONtw0l.svg)](https://asciinema.org/a/JWUP4sCednONtw0l)

*Experience Oblivion AI in action: Multi-file generation, terminal UI, and real-time tool tracking.*

---

## ⚡ Quick Start

### Installation

```bash
# Basic text-only install
pip install oblivion-agent

# With local Voice STT + Neural TTS support (Recommended)
pip install "oblivion-agent[voice]"

# With premium ElevenLabs voice support
pip install "oblivion-agent[all]"
Run Oblivion AI
Bash

# Launch Terminal UI (TUI)
oblivion

# Launch MCP Server (for Claude Desktop / Cursor)
oblivion mcp

# Open MCP Inspector in Browser
oblivion inspect
🏗️ 3-Layer Hybrid Search Architecture
text

                    ┌─────────────────────────────────────────┐
                    │            USER QUERY                   │
                    │   "Where is parse_llm_output defined?"  │
                    └────────────────────┬────────────────────┘
                                         │
                   ┌─────────────────────┼─────────────────────┐
                   │                     │                     │
                   ▼                     ▼                     ▼
        ┌───────────────────┐ ┌────────────────────┐ ┌───────────────────┐
        │  LAYER 1: SYMBOL  │ │  LAYER 2: FTS5 TEXT│ │ LAYER 3: VECTOR   │
        │   SQLite Table    │ │   SQLite FTS5      │ │ ChromaDB + minilm │
        │  Exact Names Only │ │ Full-Text Match    │ │ Concept Matcher   │
        └─────────┬─────────┘ └─────────┬──────────┘ └─────────┬─────────┘
                  │                     │                      │
                  └─────────────────────┼──────────────────────┘
                                        │
                                        ▼
                   ┌─────────────────────────────────────────┐
                   │          MERGE & RANK ENGINE            │
                   │  1. Deduplicates exact line ranges      │
                   │  2. Symbol matches ALWAYS win rank #1    │
                   │  3. Merges vector context for fallback  │
                   └─────────────────────────────────────────┘
🔌 Claude Desktop MCP Integration
Connect Oblivion's code intelligence directly into Claude Desktop by adding this to your claude_desktop_config.json:

JSON

{
  "mcpServers": {
    "oblivion": {
      "command": "oblivion",
      "args": ["mcp"],
      "env": {
        "WORKSPACE_DIR": "/absolute/path/to/your/project"
      }
    }
  }
}
👨‍💻 Creator & Community
Oblivion AI was designed and built by Rohith R. (@Rohith-s-hub), a BSc Computer Science student from Tamil Nadu, India.

🌐 Website: oblivion.run.place
🐙 GitHub: @Rohith-s-hub
💼 LinkedIn: Rohith Rajkumar
📦 PyPI: oblivion-agent
📄 License
Distributed under the MIT License. Free for personal, academic, and commercial use.
"""

readme_path.write_text(content, encoding="utf-8")
print("✅ README.md successfully updated!")
