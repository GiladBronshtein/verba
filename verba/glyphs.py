"""Monochrome marks for the printed document, in place of emoji.

Sections and note boxes carry an emoji in the content, which is a perfectly
reasonable thing to type and a poor thing to print. An emoji is a colour bitmap
whose design belongs to whoever made the font: it changes between machines, it
sits on the baseline differently from the type around it, and beside a Google
Sans heading in the document's accent colour it reads as clip art.

These are the same meanings drawn as one-colour outlines that inherit the text
colour and scale with the type. The content is untouched: the substitution
happens at render time, so the emoji stays in the Markdown where it is easy to
read and easy to change.
"""
from __future__ import annotations

# 24px grid, stroked, no fill. currentColor keeps them on the heading's colour.
_PATHS = {
    "note":      "M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z",
    "pin":       "M12 17v5M9 3h6l-1 6 3 3v2H7v-2l3-3z",
    "warning":   "M12 3 2 20h20L12 3zM12 9v6M12 18h.01",
    "lock":      "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
    "gear":      "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 9 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z",
    "link":      "M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7",
    "globe":     "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zM2 12h20M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20z",
    "money":     "M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6",
    "clipboard": "M9 3h6v3H9zM8 5H6v16h12V5h-2M9 12h6M9 16h4",
    "list":      "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
    "chart":     "M3 3v18h18M7 15l4-5 3 3 5-7",
    "users":     "M16 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 20v-2a4 4 0 0 0-3-3.9",
    "search":    "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
    "shield":    "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
    "play":      "M6 3l14 9-14 9z",
    "book":      "M4 4h11a3 3 0 0 1 3 3v13a2 2 0 0 0-2-2H4zM4 4v14",
}

# What the content already uses, mapped to a drawn mark.
EMOJI = {
    "\U0001F4A1": "note",       "\U0001F4A1️": "note",
    "\U0001F4CC": "pin",
    "⚠": "warning",        "⚠️": "warning",
    "\U0001F512": "lock",
    "⚙": "gear",           "⚙️": "gear",
    "\U0001F517": "link",
    "\U0001F310": "globe",
    "\U0001F4B0": "money",
    "\U0001F4CB": "clipboard",  "\U0001F4DD": "clipboard",
    "\U0001F4CA": "chart",      "\U0001F4C8": "chart",
    "\U0001F465": "users",      "\U0001F464": "users",
    "\U0001F50D": "search",     "\U0001F50E": "search",
    "\U0001F6E1": "shield",     "\U0001F6E1️": "shield",
    "▶": "play",           "▶️": "play",
    "\U0001F4D6": "book",       "\U0001F4DA": "book",
    "\U0001F4C1": "clipboard",  "\U0001F4C4": "clipboard",
    "\U0001F680": "play",       "✅": "shield",
    "\U0001F6E0": "gear",       "\U0001F6E0️": "gear",
}

SIZE = "1.02em"


def svg(name: str, size: str = SIZE, cls: str = "gly") -> str:
    path = _PATHS.get(name)
    if not path:
        return ""
    return (f'<svg class="{cls}" viewBox="0 0 24 24" width="{size}" height="{size}" '
            f'fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'<path d="{path}"/></svg>')


def for_emoji(ch: str, size: str = SIZE) -> str:
    """The mark that replaces an emoji, or nothing if it has no equivalent."""
    if not ch:
        return ""
    key = ch.strip()
    name = EMOJI.get(key) or EMOJI.get(key.rstrip("️"))
    return svg(name, size) if name else ""


CSS = """
.gly{display:inline-block;vertical-align:-0.14em;margin-right:0.34em;
  stroke-width:1.8;flex:none}
h1 .gly,h2 .gly,h3 .gly{stroke-width:2}
"""
