"""
tools/web_search.py - Web search for Oblivion.

Gives Meera access to current information:
  - DuckDuckGo instant answers (free, no API key)
  - Web page content fetching + cleaning
  - Stack Overflow search (free API)
  - Package version lookup (PyPI + npm)

No API keys required for basic search.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path


# ── Shared HTTP helper ────────────────────────────────────────────────────────
def _fetch(url: str, timeout: int = 10, headers: dict = None) -> tuple[bool, str]:
    """Fetch URL content. Returns (success, content)."""
    try:
        req = urllib.request.Request(url)
        req.add_header(
            "User-Agent",
            "Mozilla/5.0 (compatible; Oblivion-Agent/3.0; +https://github.com/Rohith-s-hub/Oblivion-agent)"
        )
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            encoding = resp.headers.get_content_charset("utf-8")
            return True, raw.decode(encoding, errors="ignore")
    except Exception as e:
        return False, str(e)


def _clean_html(html: str, max_chars: int = 4000) -> str:
    """Strip HTML tags and clean up text content."""
    # Remove script and style blocks entirely
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<nav[^>]*>.*?</nav>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<header[^>]*>.*?</header>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<footer[^>]*>.*?</footer>", " ", html, flags=re.DOTALL | re.IGNORECASE)

    # Convert block elements to newlines
    html = re.sub(r"<(?:br|p|div|h[1-6]|li|tr)[^>]*>", "\n", html, flags=re.IGNORECASE)

    # Strip remaining tags
    html = re.sub(r"<[^>]+>", "", html)

    # Decode common HTML entities
    html = html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    html = html.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")

    # Clean whitespace
    lines = []
    for line in html.split("\n"):
        line = line.strip()
        if len(line) > 20:  # Skip very short lines (nav items etc)
            lines.append(line)

    text = "\n".join(lines)

    # Remove repeated whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)

    return text[:max_chars].strip()


# ── DuckDuckGo Search ─────────────────────────────────────────────────────────
def web_search(query: str, n_results: int = 5) -> str:
    """
    Search the web using DuckDuckGo.
    Returns titles, URLs, and snippets for top results.
    No API key required.

    Use this when:
    - User asks about something that might be outdated in training data
    - Looking for latest docs, package versions, error solutions
    - Need current information (news, releases, changelogs)
    """
    if not query or not query.strip():
        return "Error: search query cannot be empty."

    n_results = min(max(1, n_results), 10)

    # DuckDuckGo HTML search (no JS required)
    encoded = urllib.parse.quote_plus(query.strip())
    url = f"https://html.duckduckgo.com/html/?q={encoded}"

    ok, html = _fetch(url, timeout=15)
    if not ok:
        return f"Search failed: {html}\nTry a different query or check internet connection."

    # Parse results from DDG HTML
    results = []

    # Extract result blocks
    blocks = re.findall(
        r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.+?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(.+?)</a>',
        html, re.DOTALL
    )

    for href, title, snippet in blocks[:n_results]:
        title = re.sub(r"<[^>]+>", "", title).strip()
        snippet = re.sub(r"<[^>]+>", "", snippet).strip()
        # Decode HTML entities
        title = title.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
        snippet = snippet.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')

        # DDG redirect URL -> extract real URL
        real_url = href
        if "uddg=" in href:
            try:
                real_url = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
            except Exception:
                pass

        if title and real_url:
            results.append({
                "title": title[:120],
                "url": real_url,
                "snippet": snippet[:300],
            })

    if not results:
        # Fallback: try to extract any links
        links = re.findall(r'href="(https?://[^"]+)"', html)
        links = [l for l in links if "duckduckgo" not in l][:3]
        if links:
            return (
                f"Search returned no structured results for: {query}\n"
                f"Found these URLs:\n" + "\n".join(f"  {l}" for l in links)
            )
        return (
            f"No results found for: {query}\n"
            "Try rephrasing or use a more specific query."
        )

    lines = [f"🔍 Web search: \"{query}\"", f"   {len(results)} results\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}")
        lines.append(f"   {r['url']}")
        if r["snippet"]:
            lines.append(f"   {r['snippet']}")
        lines.append("")

    lines.append(
        "Use fetch_page(url) to read the full content of any result above."
    )

    return "\n".join(lines)


def fetch_page(url: str, max_chars: int = 4000) -> str:
    """
    Fetch and read a web page, returning clean text content.
    Use after web_search to read the full content of a result.

    Useful for:
    - Reading documentation pages
    - Getting full Stack Overflow answers
    - Reading GitHub READMEs
    - Checking package changelogs
    """
    if not url or not url.strip():
        return "Error: URL cannot be empty."

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    ok, content = _fetch(url, timeout=15)
    if not ok:
        return f"Failed to fetch {url}: {content}"

    # Check if it's HTML
    if "<html" in content[:500].lower() or "<!doctype" in content[:100].lower():
        text = _clean_html(content, max_chars=max_chars)
        if not text.strip():
            return f"Page fetched but no readable content found at {url}"
        return f"📄 Content from {url}:\n\n{text}"

    # Plain text (markdown, txt, etc.)
    text = content[:max_chars].strip()
    return f"📄 Content from {url}:\n\n{text}"


# ── Stack Overflow Search ─────────────────────────────────────────────────────
def search_stackoverflow(query: str, n_results: int = 3) -> str:
    """
    Search Stack Overflow for answers to coding questions.
    Returns top questions with answers. No API key needed.

    Best for:
    - Error messages
    - How-to coding questions
    - Library usage examples
    """
    if not query or not query.strip():
        return "Error: query cannot be empty."

    n_results = min(max(1, n_results), 5)
    encoded = urllib.parse.quote_plus(query.strip())

    # Stack Exchange API v2.3 - free, no key needed (has rate limits)
    url = (
        f"https://api.stackexchange.com/2.3/search/advanced"
        f"?order=desc&sort=relevance&q={encoded}"
        f"&site=stackoverflow&pagesize={n_results}"
        f"&filter=withbody&accepted=True"
    )

    ok, raw = _fetch(url, timeout=15)
    if not ok:
        return f"Stack Overflow search failed: {raw}"

    try:
        data = json.loads(raw)
    except Exception:
        return "Failed to parse Stack Overflow response."

    items = data.get("items", [])
    if not items:
        return (
            f"No Stack Overflow results for: {query}\n"
            f"Try web_search for broader results."
        )

    lines = [f"📚 Stack Overflow: \"{query}\"\n"]

    for i, item in enumerate(items, 1):
        title = item.get("title", "").replace("&quot;", '"').replace("&#39;", "'")
        link = item.get("link", "")
        score = item.get("score", 0)
        answers = item.get("answer_count", 0)
        accepted = item.get("accepted_answer_id")

        lines.append(f"{i}. {title}")
        lines.append(f"   Score: {score} | Answers: {answers}" +
                     (" | ✓ Has accepted answer" if accepted else ""))
        lines.append(f"   {link}")

        # Get first answer body if available
        body = item.get("body", "")
        if body:
            clean = _clean_html(body, max_chars=500)
            if clean:
                lines.append(f"   Answer preview: {clean[:400]}")
        lines.append("")

    return "\n".join(lines)


# ── Package Version Lookup ────────────────────────────────────────────────────
def lookup_package(package: str, registry: str = "auto") -> str:
    """
    Look up a package version and info from PyPI or npm.

    package: package name (e.g. 'fastapi', 'react', 'textual')
    registry: 'pypi' | 'npm' | 'auto' (auto-detects from workspace)

    Returns: latest version, description, homepage, install command.
    """
    if not package or not package.strip():
        return "Error: package name cannot be empty."

    package = package.strip().lower()

    # Auto-detect registry
    if registry == "auto":
        ws = Path(os.getenv("WORKSPACE_DIR", "."))
        if (ws / "package.json").exists():
            registry = "npm"
        elif (ws / "requirements.txt").exists() or (ws / "pyproject.toml").exists():
            registry = "pypi"
        else:
            registry = "pypi"  # default

    if registry == "pypi":
        return _lookup_pypi(package)
    elif registry == "npm":
        return _lookup_npm(package)
    else:
        return f"Unknown registry: {registry}. Use 'pypi' or 'npm'."


def _lookup_pypi(package: str) -> str:
    url = f"https://pypi.org/pypi/{package}/json"
    ok, raw = _fetch(url, timeout=10)
    if not ok:
        return f"PyPI lookup failed for '{package}': {raw}"

    try:
        data = json.loads(raw)
    except Exception:
        return f"Failed to parse PyPI response for '{package}'"

    info = data.get("info", {})
    if not info:
        return f"Package '{package}' not found on PyPI."

    name = info.get("name", package)
    version = info.get("version", "?")
    summary = info.get("summary", "No description")
    home = info.get("home_page") or info.get("project_url", "")
    requires_python = info.get("requires_python", "")
    license_ = info.get("license", "")

    # Get recent versions
    releases = list(data.get("releases", {}).keys())[-5:]

    lines = [
        f"📦 PyPI: {name}",
        f"   Latest version: {version}",
        f"   Description:    {summary[:150]}",
    ]
    if requires_python:
        lines.append(f"   Python:         {requires_python}")
    if license_:
        lines.append(f"   License:        {license_[:50]}")
    if home:
        lines.append(f"   Homepage:       {home}")
    if releases:
        lines.append(f"   Recent:         {', '.join(releases)}")
    lines.append(f"   Install:        pip install {name}=={version}")

    return "\n".join(lines)


def _lookup_npm(package: str) -> str:
    url = f"https://registry.npmjs.org/{package}/latest"
    ok, raw = _fetch(url, timeout=10)
    if not ok:
        return f"npm lookup failed for '{package}': {raw}"

    try:
        data = json.loads(raw)
    except Exception:
        return f"Failed to parse npm response for '{package}'"

    name = data.get("name", package)
    version = data.get("version", "?")
    description = data.get("description", "No description")
    homepage = data.get("homepage", "")
    license_ = data.get("license", "")
    engines = data.get("engines", {})

    lines = [
        f"📦 npm: {name}",
        f"   Latest version: {version}",
        f"   Description:    {description[:150]}",
    ]
    if license_:
        lines.append(f"   License:        {license_}")
    if engines:
        lines.append(f"   Engines:        {json.dumps(engines)[:80]}")
    if homepage:
        lines.append(f"   Homepage:       {homepage}")
    lines.append(f"   Install:        npm install {name}@{version}")

    return "\n".join(lines)
