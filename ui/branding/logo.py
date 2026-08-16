"""
Oblivion AI ASCII Logo - Clean Minimal Design

Focus: readability + iconic silhouette
NO complex ASCII art (breaks in centered rendering)
YES: clean geometric shapes + bold typography
"""
from __future__ import annotations


# ═══ COLOR PALETTE ════════════════════════════════════════════════════════════

LOGO_COLORS = {
    "violet":       "#8b5cf6",
    "violet_light": "#a78bfa",
    "cyan":         "#22d3ee",
    "cyan_light":   "#67e8f9",
    "beam":         "#f5f3ff",
    "text":         "#e0e7ff",
    "muted":        "#7c8399",
    "code_left":    "#8b5cf6",
    "code_right":   "#22d3ee",
}


# ═══ THE LOGO - Big Block Text Version ═══════════════════════════════════════

# Simple, iconic. NO complex art - just gradient text + minimal accents
LOGO_LINES = [
    ("[#8b5cf6]  ██████╗ ██████╗ ██╗     ██╗██╗   ██╗██╗ ██████╗ ███╗   ██╗[/]     [#22d3ee]█████╗ ██╗[/]", None),
    ("[#8b5cf6] ██╔═══██╗██╔══██╗██║     ██║██║   ██║██║██╔═══██╗████╗  ██║[/]    [#22d3ee]██╔══██╗██║[/]", None),
    ("[#a78bfa] ██║   ██║██████╔╝██║     ██║██║   ██║██║██║   ██║██╔██╗ ██║[/]    [#67e8f9]███████║██║[/]", None),
    ("[#a78bfa] ██║   ██║██╔══██╗██║     ██║╚██╗ ██╔╝██║██║   ██║██║╚██╗██║[/]    [#67e8f9]██╔══██║██║[/]", None),
    ("[#c4b5fd] ╚██████╔╝██████╔╝███████╗██║ ╚████╔╝ ██║╚██████╔╝██║ ╚████║[/]    [#a5f3fc]██║  ██║██║[/]", None),
    ("[#c4b5fd]  ╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝[/]     [#a5f3fc]╚═╝  ╚═╝╚═╝[/]", None),
]

# Tagline styled like the logo: <  A I  C O D I N G  A G E N T  />
TAGLINE_LINE = "                    [#8b5cf6]< [/][#7c8399]A I   C O D I N G   A G E N T[/] [#22d3ee]/>[/]"


# ═══ ICON (small, for embedding in headers) ═══════════════════════════════════

ICON_SMALL = "[#8b5cf6]◉[/][#22d3ee]◉[/]"


def render_logo() -> list[str]:
    """
    Return list of pre-styled lines for the logo.
    Each line is already a Rich/Textual markup string.
    Caller should write each line to the RichLog.
    """
    lines = [line for line, _ in LOGO_LINES]
    lines.append("")  # blank
    lines.append(TAGLINE_LINE)
    return lines


def render_boot_sequence() -> list[tuple[str, float]]:
    """
    Return boot messages as (text, delay) tuples.
    """
    return [
        ("[#7c8399]▸[/] [#a78bfa]Initializing neural pathways...[/]",   0.15),
        ("[#7c8399]▸[/] [#a78bfa]Loading model weights...[/]",          0.12),
        ("[#7c8399]▸[/] [#c4b5fd]Mounting vector database...[/]",       0.10),
        ("[#7c8399]▸[/] [#c4b5fd]Activating tool registry...[/]",       0.10),
        ("[#7c8399]▸[/] [#67e8f9]Establishing neural link...[/]",       0.15),
        ("[#7c8399]▸[/] [bold #22d3ee]✓ All systems online[/]",         0.30),
        ("", 0.1),
    ]


# ═══ EXPORTS ══════════════════════════════════════════════════════════════════

__all__ = [
    "LOGO_LINES",
    "TAGLINE_LINE",
    "LOGO_COLORS",
    "ICON_SMALL",
    "render_logo",
    "render_boot_sequence",
]
