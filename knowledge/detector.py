"""
knowledge/detector.py - Workspace tech-stack detector

Scans a workspace and identifies which technologies are in use,
so we can load only the relevant knowledge packs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Set


def detect_tech_stack(workspace: str = None) -> Set[str]:
    """
    Scan workspace, return set of detected technology tags.

    Returns tags like: 'react', 'nextjs', 'vue', 'tailwind', 'typescript',
                       'django', 'flask', 'fastapi', 'frappe'

    The 'debugging' and 'deployment' tags are always included.
    """
    ws = Path(workspace or os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()
    # Empty by default — only add tags for what's actually detected in workspace.
    # (Previously always included 'debugging' + 'deployment' which bloated the
    # system prompt by ~700 tokens per request even when user asked "list files".)
    tags: Set[str] = set()

    # ── Node.js / JS frameworks ────────────────────────────────────────────
    pkg_json = ws / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            deps = {}
            deps.update(data.get("dependencies", {}))
            deps.update(data.get("devDependencies", {}))
            dep_names = set(deps.keys())

            if "react" in dep_names or "react-dom" in dep_names:
                tags.add("react")
            if "next" in dep_names:
                tags.add("nextjs")
                tags.add("react")
            if "vue" in dep_names or "@vue/runtime-dom" in dep_names:
                tags.add("vue")
            if "nuxt" in dep_names:
                tags.add("vue")
            if "svelte" in dep_names:
                tags.add("svelte")
            if "tailwindcss" in dep_names or "@tailwindcss/vite" in dep_names:
                tags.add("tailwind")
            if "typescript" in dep_names or (ws / "tsconfig.json").exists():
                tags.add("typescript")
            if "express" in dep_names or "fastify" in dep_names or "koa" in dep_names:
                tags.add("nodejs_backend")
        except Exception:
            pass


    # Detect TypeScript from .ts/.tsx file presence (catches projects without tsconfig)
    _SKIP_DIRS_TS = {
        "node_modules", "dist", "build", ".venv", "venv",
        "site-packages", "__pycache__", ".git", ".chroma",
        "vendor", "target", "out", ".next", ".nuxt",
    }
    if "typescript" not in tags:
        try:
            for p in ws.rglob("*.ts"):
                if any(part in _SKIP_DIRS_TS for part in p.parts):
                    continue
                tags.add("typescript")
                break
            if "typescript" not in tags:
                for p in ws.rglob("*.tsx"):
                    if any(part in _SKIP_DIRS_TS for part in p.parts):
                        continue
                    tags.add("typescript")
                    break
        except Exception:
            pass

    # ── Python frameworks ──────────────────────────────────────────────────
    py_files = list(ws.glob("requirements*.txt")) + list(ws.glob("pyproject.toml"))
    py_deps_text = ""
    for f in py_files:
        try:
            py_deps_text += f.read_text(encoding="utf-8", errors="ignore").lower() + "\n"
        except Exception:
            pass

    if py_deps_text:
        if "django" in py_deps_text:
            tags.add("django")
        if "flask" in py_deps_text:
            tags.add("flask")
        if "fastapi" in py_deps_text:
            tags.add("fastapi")
        if "frappe" in py_deps_text or (ws / "hooks.py").exists():
            tags.add("frappe")

    if list(ws.rglob("*.py"))[:3]:
        tags.add("python_general")

    # ── Web dev detection (only if HTML/CSS at workspace ROOT or src/) ──────
    # Deep nested HTML (like in mcp_server/ui/) doesn't count as "this is a
    # web project". Only files at root or in obvious web folders trigger it.
    _WEB_ROOT_HINTS = ["index.html", "main.css", "styles.css", "style.css",
                        "app.css", "public/index.html", "src/index.html",
                        "src/App.css", "src/index.css"]
    try:
        for hint in _WEB_ROOT_HINTS:
            if (ws / hint).exists():
                tags.add("webdev")
                break
    except Exception:
        pass

    return tags


def detect_from_request(user_message: str) -> Set[str]:
    """
    Look at the user's request text and pull out tech keywords.
    Catches cases where workspace is empty but user says
    'build me a react app'.
    """
    msg = (user_message or "").lower()
    tags: Set[str] = set()

    keyword_map = {
        "react":      ["react", "jsx", "tsx", "create-react", "vite react"],
        "nextjs":     ["next.js", "nextjs", "next js", "next 14", "next 15", "app router"],
        "vue":        ["vue", "nuxt", "vuejs", "composition api"],
        "tailwind":   ["tailwind", "tailwindcss", "utility css"],
        "typescript": ["typescript", "type-safe", " .ts ", " .tsx "],
        "django":     ["django", "drf", "django rest"],
        "flask":      ["flask"],
        "fastapi":    ["fastapi", "pydantic"],
        "frappe":     ["frappe", "erpnext", "doctype"],
        "deployment": ["deploy", "production", "nginx", "vercel", "netlify"],
        "docker":     ["docker", "dockerfile", "compose", "container", "image", "buildkit", "alpine", "dockerignore", "multi-stage"],
        "debugging":  ["debug", "broken", "error", "not working", "refused", "failed", "fix"],
        "security":   ["security", "auth", "authentication", "authorization", "jwt", "oauth", "password", "hash", "bcrypt", "argon2", "csrf", "xss", "sql injection", "owasp", "secret", "token", "vulnerability", "encrypt", "permission", "rbac", "session", "cookie", "cors", "https", "ssl", "tls", "exploit", "attack", "sanitize", "escape"],
        "testing":    ["test", "tests", "pytest", "vitest", "jest", "unit test", "integration test", "fixture", "mock", "coverage", "tdd", "assertion", "spec"],
        "database":   ["sql", "postgres", "postgresql", "sqlite", "alembic", "migration", "index", "query", "n+1", "deadlock", "schema", "table", "jsonb", "foreign key", "transaction"],
        "webdev":     ["website", "landing page", "web app", "webapp", "web site", "site", "portfolio", "homepage", "web page", "ecommerce", "e-commerce", "online store", "shop", "blog", "dashboard", "ui", "ux", "design", "responsive", "html", "css", "javascript", "frontend", "front-end", "static site", "static website", "html5", "css3", "single page", "spa"],
    }

    for tag, keywords in keyword_map.items():
        if any(k in msg for k in keywords):
            tags.add(tag)

    return tags


def describe_stack(tags: Set[str]) -> str:
    """Human-readable summary like 'React + TypeScript + Tailwind'."""
    if not tags:
        return "(no specific stack detected)"
    parts = []
    if "nextjs" in tags:
        parts.append("Next.js")
    elif "react" in tags:
        parts.append("React")
    if "vue" in tags:
        parts.append("Vue 3")
    if "svelte" in tags:
        parts.append("Svelte")
    if "typescript" in tags:
        parts.append("TypeScript")
    if "tailwind" in tags:
        parts.append("Tailwind")
    if "django" in tags:
        parts.append("Django")
    if "flask" in tags:
        parts.append("Flask")
    if "fastapi" in tags:
        parts.append("FastAPI")
    if "frappe" in tags:
        parts.append("Frappe")
    if "webdev" in tags and not parts:
        parts.append("Web (HTML/CSS/JS)")
    if not parts:
        return "(general)"
    return " + ".join(parts)
