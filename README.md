<div align="center">

# 🌀 OBLIVION AI

### The Open-Source Terminal AI Coding Agent — Voice-Native, Self-Hosted, Zero Lock-In

**A privacy-first, zero-cost alternative to Cursor, GitHub Copilot, and Claude Code — running entirely in your terminal.**

[![PyPI version](https://img.shields.io/pypi/v/oblivion-agent.svg?color=8b5cf6)](https://pypi.org/project/oblivion-agent/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-22d3ee.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Total Downloads](https://static.pepy.tech/badge/oblivion-agent)](https://pepy.tech/project/oblivion-agent)
[![Weekly Downloads](https://img.shields.io/pypi/dw/oblivion-agent?color=67e8f9&label=downloads%2Fweek)](https://pypi.org/project/oblivion-agent/)
[![Built with Textual](https://img.shields.io/badge/TUI-Textual-blueviolet)](https://github.com/Textualize/textual)

*"Code is conversation. Make it natural."* — **M.E.E.R.A.**

[Quick Start](#-quick-start) • [Why Oblivion](#-why-oblivion) • [Architecture](#️-architecture) • [Comparison](#-oblivion-vs-the-rest) • [MCP Integration](#-mcp-server-integration) • [Roadmap](#-roadmap)

</div>

---

## 🧭 What is Oblivion?

**Oblivion AI** is a terminal-native, fully open-source AI coding agent built around **M.E.E.R.A.** (Multi-modal Engineering and Reasoning Assistant) — an autonomous ReAct-style engineering partner that lives in your CLI, understands your codebase semantically, edits multiple files atomically, and talks back with a real voice if you want it to.

It was built on the premise that the best coding agent shouldn't require a subscription, a cloud account, or your code leaving your machine to be genuinely useful. Oblivion runs against free and local LLM backends by default, indexes your repository with a three-layer hybrid search engine, and exposes its own code-intelligence tools to *other* editors over MCP — so it plays well with the tools you already use instead of competing with them.

---

## ⚡ Quick Start

```bash
# Basic text-only install
pip install oblivion-agent

# With local Voice STT + Neural TTS support (recommended)
pip install "oblivion-agent[voice]"

# With premium ElevenLabs voice support
pip install "oblivion-agent[all]"
```

```bash
# Launch the Terminal UI
oblivion

# Launch the MCP server (for Claude Desktop / Cursor / Zed)
oblivion mcp

# Open the MCP Inspector in your browser
oblivion inspect
```

No API keys required to get started — Oblivion's default fallback chain runs on free-tier and local models out of the box.

---

## 🌟 Why Oblivion

| | |
|---|---|
| 🤖 **M.E.E.R.A. Core** | A ReAct-loop reasoning engine, not a single-shot autocomplete — plans, calls tools, observes results, and iterates. |
| ⚡ **13-Model Fallback Chain** | Auto-cascades across Ollama Cloud, Gemini, Groq, OpenRouter and more with smart rate-limit cooldowns, so you rarely hit a dead end. |
| 🎙️ **Real Voice I/O** | Wake-word activation ("Hey Jarvis"), silence-based auto-stop, and 8 neural voice personas via Edge-TTS / ElevenLabs. |
| 🔍 **3-Layer Hybrid Search** | Exact symbol lookup (SQLite FTS5) + full-text search + vector semantic embeddings (ChromaDB) with AST-aware chunking. |
| 🔌 **Built-in MCP Server** | Exposes 10 read-only code-intelligence tools directly to Claude Desktop, Cursor, and Zed — Oblivion augments your other tools too. |
| 🛡️ **3-Tier Safety System** | Read / Mutate / Destructive action tiers, with unified diff previews before anything touches disk. |
| 🧰 **38 Agent Tools** | Full Git suite, test runners, atomic multi-file `batch_edit`, web search, PyPI/npm lookups, background server management. |
| 📚 **14 Domain Knowledge Packs** | Auto-detected, context-aware packs (React, Next.js, Django, Security, and more), capped at 2 per request to stay lean. |
| 💻 **Runs on Modest Hardware** | Developed and validated end-to-end on a 13GB RAM laptop with no GPU. |
| 📟 **Bonus: Intel 8085 Emulator** | A full microprocessor simulator and assembler, tucked inside the same TUI. |

---

## 🆚 Oblivion vs. The Rest

| Capability | **Oblivion AI** | Cursor | GitHub Copilot | Claude Code |
|---|:---:|:---:|:---:|:---:|
| Open source | ✅ MIT | ❌ | ❌ | ❌ |
| Cost to run | **Free** (local/free-tier LLMs) | Subscription | Subscription | Usage-based |
| Runs fully in terminal | ✅ | ❌ (IDE fork) | ❌ (IDE plugin) | ✅ |
| Multi-model fallback chain | ✅ 13 backends | ❌ single provider | ❌ single provider | ❌ single provider |
| Local-model support | ✅ Ollama | ❌ | ❌ | ❌ |
| Native voice I/O | ✅ wake-word + TTS/STT | ❌ | ❌ | ❌ |
| Hybrid symbol + semantic search | ✅ 3-layer (FTS5 + ChromaDB) | Semantic only | Limited | Semantic only |
| Exposes its own MCP server | ✅ 10 tools | ❌ | ❌ | ❌ |
| Tiered write-safety with diff previews | ✅ 3-tier | Partial | ❌ | ✅ |
| Data leaves your machine | Optional (local mode available) | Yes | Yes | Yes |

*Oblivion doesn't aim to replace every workflow — it aims to be the agent that works the same way whether you have a $0 budget or an enterprise API key, and hands its own code intelligence to whichever other tool you're already using.*

---

## 🏗️ Architecture

### 3-Layer Hybrid Search Engine

**Query:** `"Where is parse_llm_output defined?"`

The same query fans out to all three layers in parallel, then gets merged into one ranked result:

| Layer | Engine | What it catches |
|---|---|---|
| **1 — Symbol** | SQLite table | Exact function/class/variable names — always ranked first when matched |
| **2 — Full-text** | SQLite FTS5 | Literal text matches anywhere in the codebase |
| **3 — Vector** | ChromaDB + MiniLM | Conceptual/semantic matches, even with no shared keywords |

**Merge & rank:** exact line ranges are deduplicated → symbol hits always win rank #1 → vector context fills in as fallback for anything the first two layers missed.

### Reasoning & Execution Loop

1. **User prompt** goes to **M.E.E.R.A.**, which runs a ReAct loop — reason, act, observe, repeat.
2. M.E.E.R.A. selects from its **38 tools** and routes the request through the **13-model fallback chain** (Ollama Cloud → Gemini → Groq → …) for the actual completion.
3. Any tool call that touches your code passes through the **3-tier safety gate** — Read / Mutate / Destructive.
4. Read-tier actions run immediately. Mutate and Destructive actions generate a **diff preview** first, and only execute (atomically, via `batch_edit`) once approved.

**Tech stack:** Python 3.11+, [Textual](https://github.com/Textualize/textual) TUI framework with cyberpunk styling, SQLite (FTS5), ChromaDB, faster-whisper (STT), Edge-TTS / ElevenLabs (TTS), Model Context Protocol (MCP).

**Scale (v3.1.0, Aug 2026):** ~45 Python files · ~12,000+ lines of code · 4,000+ downloads on PyPI · 38 tools (22 read-tier, 13 mutate-tier, 1 destructive, 1 special) · 6-model smart-cooldown fallback for the default configuration, expandable to 13 supported backends.

---

## 🔌 MCP Server Integration

Oblivion isn't just a standalone agent — it also *serves* its code-intelligence layer to other editors over the Model Context Protocol. Add this to your `claude_desktop_config.json` to give Claude Desktop, Cursor, or Zed direct access to Oblivion's 3-layer search and symbol index:

```json
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
```

This exposes 10 read-only tools — symbol lookup, semantic search, file structure inspection, and more — so your existing editor gets Oblivion's understanding of the codebase without needing to run the full agent inside it.

---

## 🎙️ Voice-First Workflow

- **Wake-word activation:** say *"Hey Jarvis"* to start a session hands-free.
- **Silence-based auto-stop:** a 3-second pause automatically ends your utterance — no push-to-talk needed.
- **8 neural voice personas** via Edge-TTS (free) or ElevenLabs (premium), so M.E.E.R.A. can sound however you want it to.
- Built on `faster-whisper` for local speech-to-text, keeping voice interaction private by default.

---

## 🛡️ Safety Model

Every action Oblivion can take falls into one of three tiers, and nothing in the Mutate or Destructive tiers runs without a **unified diff preview** first:

| Tier | Examples | Confirmation |
|---|---|---|
| **Read** (22 tools) | File search, symbol lookup, git log, test discovery | None needed |
| **Mutate** (13 tools) | Multi-file `batch_edit`, git commit, dependency install | Diff preview shown |
| **Destructive** (1 tool) | File/branch deletion | Explicit confirmation required |

---

## 🗺️ Roadmap

- Jarvis-style voice personality: barge-in interruption, proactive unprompted commentary, emotion-aware tone adjustment
- Continued expansion of the free-model fallback chain (Kimi K2, GLM-5.2, Qwen3-Coder and beyond)
- Refactor of the TUI dashboard into smaller, more maintainable modules
- Deeper MCP tool surface for third-party editor integrations

---

## 📄 License

Distributed under the **MIT License** — free for personal, academic, and commercial use.

---

## 👨‍💻 Creator & Community

Oblivion AI is designed and built by **R. Rohith** ([@Rohith-s-hub](https://github.com/Rohith-s-hub)), a final-year B.Sc. Computer Science student from Tamil Nadu, India.

- 🌐 **Website:** [oblivion.run.place](https://oblivion.run.place)
- 🐙 **GitHub:** [@Rohith-s-hub](https://github.com/Rohith-s-hub)
- 💼 **LinkedIn:** [Rohith Rajkumar](https://www.linkedin.com/in/rohith-rajkumar-040676315)
- 📦 **PyPI:** [oblivion-agent](https://pypi.org/project/oblivion-agent/)

<div align="center">

⭐ **If Oblivion saves you a subscription or two, consider starring the repo.** ⭐

</div>
## Author
**Rohith R** (Rohith Rajkumar) — AI Integrated Fullstack Developer · B.Sc CS · Sivakasi, India  
Creator of **Oblivion AI** (M.E.E.R.A.) — open-source terminal AI coding agent.

- LinkedIn: https://www.linkedin.com/in/rohith-rajkumar-040676315/
- Blog: https://rohithblog.vercel.app/
- GitHub: https://github.com/Rohith-s-hub/
- PyPI: https://pypi.org/project/oblivion-agent/
- Site: https://oblivion.run.place/

```bash
pip install oblivion-agent
oblivion
```
