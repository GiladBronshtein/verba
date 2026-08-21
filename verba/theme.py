"""The document's colours and type sizes, as data rather than as code.

This used to be one frozen dataclass holding one company's brand, which meant
the only way to document a different product was to edit the source. A theme is
now a named file: the engine ships several, a project picks one in
``content/theme.yaml``, and anything it does not mention falls back to the
default rather than to nothing.

    verba themes              what is available, and what each is for
    verba themes --use ink    pick one
    verba themes --show       the resolved values, after overrides

A project can also override single tokens without forking a whole theme, which
is the common case: a company has one brand colour and no opinion about the
other nineteen.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

CONFIG = "content/theme.yaml"
BUILTIN = Path(__file__).resolve().parent.parent / "themes"

# Notes are drawn marks, never emoji: an emoji is a colour bitmap whose design
# belongs to whoever made the font, it changes between machines, and it sits on
# the baseline differently from the type around it. The names here are keys into
# the glyph set, and a label with no mark simply gets none.
DEFAULT_NOTE_MARKS = {
    "Note": "note", "Tip": "note", "Important": "warning",
    "Warning": "warning", "Caution": "warning", "Key Concept": "pin",
    "Example": "clipboard", "Access Scope": "lock", "Settings": "gear",
}


@dataclass(frozen=True)
class Theme:
    """One document's palette and scale. Every field has a usable default."""
    name: str = "slate"
    label: str = "Slate"
    about: str = "A neutral, professional default. Reads as a manual, not a brochure."
    font: str = "Inter"

    # Colours are hex without the hash, because that is what python-docx wants
    # and the web renderers can add one more cheaply than the other can strip it.
    navy_hero: str = "16203A"     # the cover field
    navy_deep: str = "1B2549"     # body text and major headings
    brand_blue: str = "3137DB"    # the accent: rules, sub-headings, links
    lavender: str = "EBEFFC"      # tinted panel behind a callout
    periwinkle: str = "5E97FF"    # the accent, lightened for dark grounds
    white: str = "FFFFFF"
    grey_mid: str = "A1A1A1"
    grey_dark: str = "6E6E6E"
    red_err: str = "E03939"
    green_ok: str = "1F9D55"
    amber: str = "B7791F"

    size_h1: float = 24
    size_h2: float = 13
    size_h3: float = 12
    size_h4: float = 10
    size_body: float = 10
    size_small: float = 9
    size_caption: float = 8.5
    size_chrome: float = 8

    note_marks: dict = field(default_factory=lambda: dict(DEFAULT_NOTE_MARKS))
    note_accent: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    def hex(self, token: str) -> str:
        return getattr(self, token)

    @property
    def note_icons(self) -> dict:
        """Kept so the renderers read one name for this across versions."""
        return self.note_marks

    def accent_for(self, label: str) -> str:
        """The rule colour for a callout, falling back to the brand accent."""
        return self.note_accent.get(label, self.brand_blue)

    # ------------------------------------------------------------------
    @classmethod
    def named(cls, name: str) -> "Theme":
        """One of the themes the engine ships with."""
        path = BUILTIN / f"{name}.yaml"
        if not path.exists():
            raise ValueError(f"no such theme: {name}. try one of: "
                             f"{', '.join(available())}")
        return cls._from(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, name)

    @classmethod
    def _from(cls, data: dict, name: str) -> "Theme":
        fields = {f for f in cls.__dataclass_fields__ if f not in
                  ("note_marks", "note_accent")}
        kw = {k: v for k, v in data.items() if k in fields}
        kw["name"] = data.get("name", name)
        marks = dict(DEFAULT_NOTE_MARKS)
        marks.update(data.get("note_marks") or {})
        return cls(note_marks=marks, note_accent=dict(data.get("note_accent") or {}),
                   **kw)

    @classmethod
    def load(cls, root: Path | str = ".") -> "Theme":
        """The theme this project uses, with its own overrides applied.

        A project that says nothing gets the default, so a new workspace renders
        a reasonable document before anybody has made a single design decision.
        """
        path = Path(root) / CONFIG
        if not path.exists():
            return cls.named("slate")
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        base = cls.named(cfg.get("use", "slate"))
        over = {k: v for k, v in (cfg.get("tokens") or {}).items()
                if k in cls.__dataclass_fields__ and k not in
                ("note_marks", "note_accent")}
        if cfg.get("note_accent"):
            base = replace(base, note_accent={**base.note_accent,
                                             **cfg["note_accent"]})
        return replace(base, **over) if over else base


def available() -> list[str]:
    return sorted(p.stem for p in BUILTIN.glob("*.yaml"))


def table() -> list[dict]:
    """Every theme with the two things you choose between: its look and its point."""
    out = []
    for name in available():
        t = Theme.named(name)
        out.append({"name": name, "label": t.label, "about": t.about,
                    "swatch": [t.brand_blue, t.navy_deep, t.lavender,
                               t.periwinkle, t.grey_mid]})
    return out


THEME = Theme()
