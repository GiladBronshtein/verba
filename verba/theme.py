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
# Inside the package. It used to point one level up, at a directory beside the
# package rather than in it, which worked from a checkout and worked for a
# vendored copy and shipped nothing at all in a real install.
BUILTIN = Path(__file__).resolve().parent / "themes"

# Where a project keeps a palette of its own. A house palette belongs to the
# document, not to the engine: it is the one design decision that cannot be
# general, and putting it in the engine means every project carries every other
# project's brand.
PROJECT_THEMES = ("themes", "content/themes")

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
    # The name of a theme that was asked for and could not be found. Set when
    # the default has been substituted, so the substitution can be reported
    # rather than silently accepted: a document that quietly renders in the
    # wrong palette is worse than one that says it did.
    missing: str = ""

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
    def find(cls, name: str, root: Path | str = ".") -> Path | None:
        """Where this theme's file is: the project's own first, then the engine's."""
        for folder in PROJECT_THEMES:
            path = Path(root) / folder / f"{name}.yaml"
            if path.exists():
                return path
        path = BUILTIN / f"{name}.yaml"
        return path if path.exists() else None

    @classmethod
    def named(cls, name: str, root: Path | str = ".") -> "Theme":
        """A theme by name, from the project or from the engine."""
        path = cls.find(name, root)
        if path is None:
            raise ValueError(f"no such theme: {name}. try one of: "
                             f"{', '.join(available(root))}")
        return cls._from(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, name)

    @staticmethod
    def _hex(value):
        """A colour, however a person wrote it down.

        content/theme.yaml invites the reader to paste their brand colour, and
        every design tool on earth hands it over with a hash on the front.
        Doing that reported no lint error and then died inside python-docx with
        `invalid literal for int() with base 16: '#3'`.
        """
        if isinstance(value, str):
            v = value.strip().lstrip("#").strip()
            if len(v) == 3 and all(c in "0123456789abcdefABCDEF" for c in v):
                v = "".join(c * 2 for c in v)     # #abc is a colour too
            return v.upper() if len(v) == 6 and all(
                c in "0123456789abcdefABCDEF" for c in v) else value
        return value

    @classmethod
    def _from(cls, data: dict, name: str) -> "Theme":
        fields = {f for f in cls.__dataclass_fields__ if f not in
                  ("note_marks", "note_accent")}
        kw = {k: cls._hex(v) for k, v in data.items() if k in fields}
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
            return cls.named("slate", root)
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        wanted = cfg.get("use", "slate")
        try:
            base = cls.named(wanted, root)
        except ValueError:
            # A missing palette is not a reason to fail a publish. Somebody is
            # trying to ship a document and the thing that is wrong is the
            # colour of its headings: render it in the default, say so where it
            # will be read, and let the rules carry the complaint. A traceback
            # out of a release is the worst possible way to learn this.
            base = replace(cls.named("slate", root), missing=str(wanted))
        over = {k: cls._hex(v) for k, v in (cfg.get("tokens") or {}).items()
                if k in cls.__dataclass_fields__ and k not in
                ("note_marks", "note_accent")}
        if cfg.get("note_accent"):
            base = replace(base, note_accent={**base.note_accent,
                                             **cfg["note_accent"]})
        return replace(base, **over) if over else base


def available(root: Path | str = ".") -> list[str]:
    """Every theme this project can choose, its own included."""
    names = {p.stem for p in BUILTIN.glob("*.yaml")}
    for folder in PROJECT_THEMES:
        names |= {p.stem for p in (Path(root) / folder).glob("*.yaml")}
    return sorted(names)


def table(root: Path | str = ".") -> list[dict]:
    """Every theme with the two things you choose between: its look and its point."""
    out = []
    for name in available(root):
        t = Theme.named(name, root)
        out.append({"name": name, "label": t.label, "about": t.about,
                    "swatch": [t.brand_blue, t.navy_deep, t.lavender,
                               t.periwinkle, t.grey_mid]})
    return out


THEME = Theme()
