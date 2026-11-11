"""
tools/web_diagnostics.py — Automated website health checks.

One tool, diagnose_website(), that catches the exact failure classes real users
hit but can't describe technically: HTML/CSS class mismatches (styles silently
not applying), dead/wrong image services, broken local links, and missing
linked files. Designed to be called PROACTIVELY whenever a user reports a
vague website problem ("looks wrong", "images are off", "broken") — the model
should run this FIRST instead of guessing or asking the user for technical
specifics they won't have.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


def _current_workspace() -> str:
    """Always read fresh — handles /openproject mid-session."""
    return str(Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve())


# Image services known to silently return WRONG/unrelated content
# (as opposed to erroring — that's what makes these dangerous)
_DEAD_OR_MISLEADING_IMAGE_HOSTS = {
    "source.unsplash.com": "DEPRECATED — Unsplash shut this down; it now returns unrelated fallback images regardless of query. Replace with loremflickr.com/{w}/{h}/{keywords}.",
    "picsum.photos": "NO KEYWORD SUPPORT — Picsum's 'seed' is a random-selection ID, not a content search; using it for named items (e.g. seed/pizza) returns ARBITRARY unrelated photos. Replace with loremflickr.com/{w}/{h}/{keywords} for anything content-specific.",
}


def _find_html_files(ws: Path) -> list[Path]:
    skip_dirs = {"node_modules", ".git", "dist", "build", ".venv", "venv", "__pycache__"}
    return [
        p for p in ws.rglob("*.html")
        if not any(part in skip_dirs for part in p.parts)
    ]


def _find_css_files(ws: Path) -> list[Path]:
    skip_dirs = {"node_modules", ".git", "dist", "build", ".venv", "venv", "__pycache__"}
    return [
        p for p in ws.rglob("*.css")
        if not any(part in skip_dirs for part in p.parts)
    ]


def _extract_html_classes(html: str) -> set[str]:
    classes = set()
    for match in re.finditer(r'class="([^"]+)"', html):
        classes.update(match.group(1).split())
    return classes


def _extract_css_classes(css: str) -> set[str]:
    # Matches .classname followed by whitespace, comma, dot, colon, or brace
    return set(re.findall(r'\.([a-zA-Z0-9_-]+)(?=[\s,.:{])', css))


def _extract_linked_files(html: str, html_path: Path) -> list[tuple[str, Path]]:
    """Return [(raw_href_or_src, resolved_local_path), ...] for local file refs."""
    results = []
    base_dir = html_path.parent
    for attr, tag_pattern in (
        ("href", r'<link[^>]+href="([^"]+)"'),
        ("src", r'<(?:script|img)[^>]+src="([^"]+)"'),
    ):
        for match in re.finditer(tag_pattern, html):
            ref = match.group(1)
            # Skip external URLs, data URIs, and anchors
            if ref.startswith(("http://", "https://", "data:", "#", "//")):
                continue
            resolved = (base_dir / ref).resolve()
            results.append((ref, resolved))
    return results


def _extract_image_srcs(html: str) -> list[str]:
    return re.findall(r'<img[^>]+src="([^"]+)"', html)


def _check_tailwind_pipeline(ws: Path) -> list[str]:
    """If this looks like a Tailwind project, verify its build config is complete.
    Returns a list of problem strings (empty if fine or not a Tailwind project)."""
    problems = []
    pkg_json = ws / "package.json"
    if not pkg_json.exists():
        return problems
    try:
        import json as _json
        pkg = _json.loads(pkg_json.read_text(encoding="utf-8"))
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        if "tailwindcss" not in deps:
            return problems  # not a Tailwind project, nothing to check
    except Exception:
        return problems

    has_tw_config = any((ws / f"tailwind.config.{ext}").exists() for ext in ("js", "cjs", "mjs", "ts"))
    has_postcss_config = any((ws / f"postcss.config.{ext}").exists() for ext in ("js", "cjs", "mjs"))

    # Tailwind v4 doesn't require tailwind.config.js/postcss.config.js in the same way
    # (it uses @import "tailwindcss" + a Vite plugin) — only flag for v3.x
    tw_version = deps.get("tailwindcss", "")
    is_v3 = tw_version.startswith("^3") or tw_version.startswith("3") or tw_version.startswith("~3")

    if is_v3 and not has_tw_config:
        problems.append(
            "tailwind.config.js is MISSING — Tailwind v3 requires this file with a `content:` array. "
            "Without it, ALL Tailwind utility classes compile to NOTHING — every className silently does "
            "nothing, which looks like dozens of individual component bugs but is ONE root cause."
        )
    if is_v3 and not has_postcss_config:
        problems.append(
            "postcss.config.js is MISSING — without it, Vite never runs Tailwind's PostCSS transform at all, "
            "so @tailwind directives in your CSS never get compiled into real styles."
        )
    return problems


def diagnose_website(target_file: str = "") -> str:
    """Run automated health checks on the current website project.

    Catches issues a non-technical user can't describe precisely:
    - HTML classes with NO matching CSS rule (styles silently not applying —
      the #1 cause of "the layout looks broken/plain" reports)
    - Images pointing at known-dead or non-content-aware placeholder services
      (source.unsplash.com, picsum.photos used for named/specific content)
    - <link>/<script src>/<img src> pointing at local files that don't exist on disk
    - CSS classes defined but never used in any HTML (informational, not an error)

    Call this FIRST whenever a user reports a vague website problem — before
    asking them technical questions they won't be able to answer, and before
    guessing at a fix. Then use the output to make TARGETED fixes.

    Args:
        target_file: optional — limit the check to one specific HTML file
                      (relative path). If empty, scans the whole workspace.
    """
    ws = Path(_current_workspace())

    if target_file:
        html_files = [ (ws / target_file).resolve() ]
        if not html_files[0].exists():
            return f"Error: {target_file} not found in workspace."
    else:
        html_files = _find_html_files(ws)

    if not html_files:
        return "No HTML files found in this workspace — nothing to diagnose."

    css_files = _find_css_files(ws)
    all_css_classes: set[str] = set()
    css_read_errors = []
    for css_path in css_files:
        try:
            all_css_classes |= _extract_css_classes(css_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception as e:
            css_read_errors.append(f"{css_path.relative_to(ws)}: {e}")

    report_sections = []

    # ── Check 1: HTML classes with no matching CSS rule ──────────────────
    unstyled_by_file: dict[str, set[str]] = {}
    for html_path in html_files:
        try:
            html = html_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            report_sections.append(f"⚠️  Could not read {html_path.relative_to(ws)}: {e}")
            continue

        html_classes = _extract_html_classes(html)
        missing = html_classes - all_css_classes
        if missing:
            unstyled_by_file[str(html_path.relative_to(ws))] = missing

    if unstyled_by_file:
        report_sections.append("🔴 CRITICAL — HTML classes with NO matching CSS rule (styles silently not applying):")
        for fname, classes in unstyled_by_file.items():
            report_sections.append(f"  {fname}: {', '.join(sorted(classes))}")
        report_sections.append(
            "  → FIX: Read the HTML to see how each class is used, then ADD the missing rules to the linked CSS file. "
            "This is almost always why a page looks unstyled/plain/broken despite CSS being linked correctly."
        )
    else:
        report_sections.append("✅ All HTML classes have matching CSS rules.")

    # ── Check 2: dead/misleading image services ───────────────────────────
    bad_image_hits: dict[str, list[str]] = {}
    for html_path in html_files:
        try:
            html = html_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        srcs = _extract_image_srcs(html)
        for src in srcs:
            for host, reason in _DEAD_OR_MISLEADING_IMAGE_HOSTS.items():
                if host in src:
                    bad_image_hits.setdefault(str(html_path.relative_to(ws)), []).append(f"{src}  —  {reason}")

    if bad_image_hits:
        report_sections.append("\n🟠 IMAGE SOURCE ISSUES (will show wrong/unrelated photos):")
        for fname, hits in bad_image_hits.items():
            report_sections.append(f"  {fname}:")
            for h in hits:
                report_sections.append(f"    - {h}")
        report_sections.append(
            "  → FIX: Replace with https://loremflickr.com/{width}/{height}/{specific-keywords} — "
            "e.g. loremflickr.com/300/300/pizza,margherita — using keywords derived from the actual item name."
        )
    else:
        report_sections.append("\n✅ No known-broken image services detected.")

    # ── Check 3: broken local file links ──────────────────────────────────
    broken_links: dict[str, list[str]] = {}
    for html_path in html_files:
        try:
            html = html_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for raw_ref, resolved in _extract_linked_files(html, html_path):
            if not resolved.exists():
                broken_links.setdefault(str(html_path.relative_to(ws)), []).append(raw_ref)

    if broken_links:
        report_sections.append("\n🔴 BROKEN LOCAL FILE LINKS (file referenced but does not exist on disk):")
        for fname, refs in broken_links.items():
            report_sections.append(f"  {fname}: {', '.join(refs)}")
        report_sections.append("  → FIX: Either create the missing file, or correct the path/filename in the HTML.")
    else:
        report_sections.append("\n✅ All local <link>/<script>/<img> references resolve to real files.")

    if css_read_errors:
        report_sections.append("\n⚠️  Could not read some CSS files:")
        report_sections.extend(f"  {e}" for e in css_read_errors)

    # ── Check 4: Tailwind build pipeline integrity ────────────────────────
    tw_problems = _check_tailwind_pipeline(ws)
    if tw_problems:
        report_sections.append("\n🔴 CRITICAL — BUILD PIPELINE ISSUES (will cause widespread silent styling failure):")
        for p in tw_problems:
            report_sections.append(f"  - {p}")
        report_sections.append(
            "  → FIX: Create the missing config file(s) BEFORE touching any component code. "
            "This is almost certainly the root cause if you're seeing broken/unstyled/misaligned "
            "elements across MULTIPLE components rather than one isolated spot."
        )

    header = f"WEBSITE DIAGNOSTIC REPORT — {len(html_files)} HTML file(s), {len(css_files)} CSS file(s) scanned\n" + "=" * 60 + "\n"
    return header + "\n".join(report_sections)
