"""
tools/search_code.py — Phase 2B.3 hybrid search

Search strategy (in order, merged + deduped by file:line):
  1. Exact symbol match           confidence = 1.00
  2. FTS full-text on symbols     confidence = 0.95 (capped, sorted by FTS rank)
  3. Embedding semantic search    confidence = 1 - distance (Chroma cosine)

Result format keeps backward compatibility — file/line/preview — and adds
source + confidence so the LLM can prioritize matches.
"""
import os
from pathlib import Path

from agent.rag import search_code as rag_search, index_stats
from agent import symbol_index as _symbols


def _current_workspace() -> str:
    return str(Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve())


def _looks_like_symbol(query: str) -> bool:
    """Heuristic: short identifier-like strings = likely a symbol name."""
    q = query.strip()
    if len(q) == 0 or len(q) > 60:
        return False
    if " " in q:
        return False
    # allow _ . :: (for methods)
    return all(c.isalnum() or c in "_." for c in q)


def search_code(query: str, n_results: int = 5) -> str:
    """Hybrid code search — symbol → FTS → semantic embedding.

    Returns formatted results with file:line + similarity score + source.
    """
    stats = index_stats()
    ws = _current_workspace()

    merged = []  # list of dicts: {file, start_line, end_line, source, confidence, preview, signature}
    seen = set()  # dedupe key: (file, start_line, end_line)

    def add(item: dict):
        key = (item["file"], item.get("start_line", 0), item.get("end_line", 0))
        if key in seen:
            return
        seen.add(key)
        merged.append(item)

    # ── 1. Exact symbol match (instant, highest confidence) ────────────────
    if _looks_like_symbol(query):
        for h in _symbols.find_symbol(ws, query.strip(), exact=True)[:n_results]:
            add({
                "file": h["file"],
                "start_line": h["start_line"],
                "end_line": h["end_line"],
                "source": "exact_symbol",
                "confidence": 1.00,
                "signature": h.get("signature", ""),
                "preview": h.get("signature", "") + (
                    f"\n  \"{h['docstring'].splitlines()[0][:140]}\"" if h.get("docstring") else ""
                ),
                "name": h.get("name", ""),
                "type": h.get("type", ""),
            })

    # ── 2. FTS full-text on symbols (name + signature + docstring + code) ──
    if len(merged) < n_results:
        for h in _symbols.search_symbols_fts(ws, query, limit=n_results * 2):
            add({
                "file": h["file"],
                "start_line": h["start_line"],
                "end_line": h["end_line"],
                "source": "fts_symbol",
                "confidence": 0.95,
                "signature": h.get("signature", ""),
                "preview": f"{h.get('type','')} {h.get('name','')}  {h.get('signature','')[:120]}",
                "name": h.get("name", ""),
                "type": h.get("type", ""),
            })

    # ── 3. Embedding semantic (existing rag_search) ────────────────────────
    if len(merged) < n_results and stats["total_chunks"] > 0:
        for r in rag_search(query, n_results=n_results * 2):
            distance = r.get("distance", 1.0) or 1.0
            confidence = max(0.0, min(0.94, 1.0 - distance))  # cap below FTS so symbol always wins
            preview_lines = r["text"].split("\n")[:6]
            add({
                "file": r["file"],
                "start_line": r["start_line"],
                "end_line": r["end_line"],
                "source": "semantic",
                "confidence": confidence,
                "signature": "",
                "preview": "\n".join(preview_lines),
                "name": "",
                "type": "",
            })

    if not merged:
        if stats["total_chunks"] == 0:
            return (
                "❌ Codebase has no indexed chunks yet.\n"
                "Run: from agent.rag import index_codebase; index_codebase()"
            )
        return f"No results found for: {query}"

    # ── Rank: confidence DESC, then source priority ────────────────────────
    source_order = {"exact_symbol": 0, "fts_symbol": 1, "semantic": 2}
    merged.sort(key=lambda x: (-x["confidence"], source_order.get(x["source"], 9)))
    merged = merged[:n_results]

    # ── Format ─────────────────────────────────────────────────────────────
    out = [f"Found {len(merged)} match(es) for: '{query}'  (workspace: {Path(ws).name})", ""]
    for i, r in enumerate(merged, 1):
        tag = f"[{r['source']}]".ljust(14)
        out.append(
            f"━━━ {i}. {tag} {r['file']}:{r['start_line']}-{r['end_line']}  "
            f"(confidence: {r['confidence']:.2f})"
        )
        if r.get("preview"):
            out.append(r["preview"])
        out.append("")
    out.append("Tip: read_file(\"<path>\") for full context, find_callers(\"<name>\") for impact.")
    return "\n".join(out)
