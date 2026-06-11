"""
search_code: semantic search over the indexed codebase using RAG.
"""
from agent.rag import search_code as rag_search, index_stats


def search_code(query: str, n_results: int = 5) -> str:
    """
    Search the indexed codebase for code/text semantically similar to query.
    Returns formatted results.
    """
    stats = index_stats()
    if stats["total_chunks"] == 0:
        return (
            "❌ Codebase is not indexed yet. "
            "Run: `uv run python scripts/index.py` to index it."
        )

    results = rag_search(query, n_results=n_results)
    if not results:
        return f"No results found for: {query}"

    output = [f"Found {len(results)} matches for: '{query}'\n"]

    for i, r in enumerate(results, 1):
        score = 1.0 - r["distance"]  # convert distance to similarity
        output.append(
            f"━━━ Result {i} ━━━ "
            f"{r['file']}:{r['start_line']}-{r['end_line']} "
            f"(similarity: {score:.2f})"
        )
        # Show first 15 lines of the chunk
        snippet_lines = r["text"].split("\n")[:6]  # just preview - agent MUST read_file for actual code
        output.append("\n".join(snippet_lines))
        output.append("")

    return "\n".join(output)
