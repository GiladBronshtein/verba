"""Which typefaces the outputs are set in.

One registry, `content/typography.yaml`, feeds four renderers that resolve fonts
in completely different ways:

* the **PDF** is printed by Chromium, so it takes a CSS stack and can pull a
  webfont if the face is served from Google Fonts;
* the **HTML preview** takes the same stack;
* the **DOCX** can only name one family and hope the reader has it, so a face
  also declares what Word should fall back to;
* the **console** is a web page and takes the stack again.

A face is only worth offering if it actually resolves on this machine. Two
checks exist: a fast one that reads what is installed, and `verify`, which asks
Chromium itself, because Chromium is what prints the document.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG = "content/typography.yaml"

# A face whose first family resolves is present. Later entries are fallbacks and
# prove nothing about the choice the person made.
FONT_DIRS = ("~/Library/Fonts", "/Library/Fonts", "/System/Library/Fonts",
             "/System/Library/Fonts/Supplemental")


@dataclass
class Face:
    key: str
    label: str
    body: list = field(default_factory=list)
    mono: list = field(default_factory=list)
    docx: str = "Calibri"
    docx_fallback: str = "Arial"
    body_pt: float = 10.5
    line: float = 1.55
    tighten: float = 0.0
    webfont: str = ""
    note: str = ""

    # --------------------------------------------------------------
    @property
    def primary(self) -> str:
        return self.body[0] if self.body else "sans-serif"

    def css_body(self) -> str:
        return ", ".join(_quote(f) for f in self.body)

    def css_mono(self) -> str:
        return ", ".join(_quote(f) for f in self.mono)

    def css_body_attr(self) -> str:
        """The same stack, safe inside an HTML style attribute.

        `css_body()` quotes multi-word families with double quotes, which end
        the attribute they are written into. Chromium's header and footer
        templates are HTML strings, so a stack pasted in there silently
        truncates the whole declaration: the font goes, and so does every rule
        after it, which is how a running header ends up in Times and jammed
        against the left margin.
        """
        return self.css_body().replace('"', "'")

    def css_import(self) -> str:
        return f"@import url('{self.webfont}');\n" if self.webfont else ""

    def tracking(self) -> str:
        """Letter spacing as an em value. Large x-height faces need tightening
        at body size or the line looks loose beside the old Calibri setting."""
        return f"{self.tighten:.3f}em" if self.tighten else "normal"


def _quote(family: str) -> str:
    # generic keywords and the -apple-system keyword must stay unquoted
    if family.startswith("-") or family in {
            "sans-serif", "serif", "monospace", "system-ui", "cursive"}:
        return family
    return f'"{family}"' if " " in family else family


@lru_cache(maxsize=1)
def installed_families() -> frozenset[str]:
    """Families this machine can render, lower cased.

    `fc-list` is authoritative and present on most macOS setups through
    Homebrew. Without it the font directories are read by filename, which
    catches the common `FamilyName-Weight.ttf` convention and little else. That
    is deliberately a hint, not a verdict: `verify()` is the verdict.
    """
    found: set[str] = set()
    try:
        out = subprocess.run(["fc-list", "--format", "%{family}\\n"],
                             capture_output=True, text=True, timeout=20)
        for line in out.stdout.splitlines():
            for name in line.split(","):
                if name.strip():
                    found.add(name.strip().lower())
    except Exception:
        pass
    if found:
        return frozenset(found)

    for d in FONT_DIRS:
        p = Path(d).expanduser()
        if not p.is_dir():
            continue
        for f in p.glob("*.[ot]t[fc]"):
            stem = re.split(r"[-_]", f.stem)[0]
            spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem)
            found.add(spaced.lower())
    return frozenset(found)


TEXT_DEFAULTS = {"align": "left", "hyphens": "on"}


@dataclass
class Text:
    """How body text is set. A choice, not a constant."""
    align: str = "left"
    hyphens: str = "on"

    @property
    def css_align(self) -> str:
        return "justify" if str(self.align).lower().startswith("just") else "left"

    @property
    def css_hyphens(self) -> str:
        return "auto" if str(self.hyphens).lower() in ("on", "true", "auto", "yes") \
            else "manual"


# Sheet sizes, in millimetres. Every name here is one Chromium also accepts as
# a `format`, so the CSS `@page size` and the print call cannot disagree.
PAPERS = {
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
}

PAGE_DEFAULTS = {"paper": "A4", "side": 18, "edge": 12, "header_band": 8,
                 "footer_band": 7, "gap": 9}


@dataclass
class Page:
    """Where the ink goes on the sheet, in millimetres.

    The sheet itself is a setting. It used to be the literal `A4` written into
    three places in the PDF renderer, while `content/doc.yaml` carried a
    `build.page` key that nothing read: changing it moved nothing, which is
    worse than not offering the choice at all.
    """
    paper: str = "A4"
    side: float = 18
    edge: float = 12
    header_band: float = 8
    footer_band: float = 7
    gap: float = 9

    @property
    def paper_name(self) -> str:
        """The canonical spelling, so `letter` and `Letter` are one setting."""
        want = str(self.paper).strip().lower()
        for name in PAPERS:
            if name.lower() == want:
                return name
        return "A4"

    @property
    def width_mm(self) -> float:
        return PAPERS[self.paper_name][0]

    @property
    def height_mm(self) -> float:
        return PAPERS[self.paper_name][1]

    @property
    def text_width_mm(self) -> float:
        """How wide a line actually runs. A figure wider than this overflows."""
        return self.width_mm - 2 * self.side

    @property
    def margin_top(self) -> float:
        """Room for the header band and the air under it.

        Chromium prints the header into the top margin. If this only covers the
        band, the rule under the header lands on the first line of text.
        """
        return self.edge + self.header_band + self.gap

    @property
    def margin_bottom(self) -> float:
        return self.edge + self.footer_band + self.gap * 0.7


_YAML_BOOLS = {"on", "off", "yes", "no", "true", "false", "y", "n"}


def _scalar(value) -> str:
    """A value as YAML would have to read it back.

    `on` is a boolean in YAML 1.1, which is what PyYAML implements, so writing
    `hyphens: on` and reading it again yields `True` and the setting stops being
    the word the person chose. Anything that could be mistaken for a boolean is
    quoted.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    s = str(value)
    return f'"{s}"' if (not s or s != s.strip() or s.lower() in _YAML_BOOLS) else s


def rewrite_block(text: str, block: str, values: dict) -> str:
    """Set scalar keys inside one top-level mapping, leaving the prose alone.

    These files are written to be read: `page:` in typography.yaml carries four
    paragraphs explaining what each margin covers, and doc.yaml's `lint.allow`
    exists so a suppression stays reviewable. Round-tripping either through
    PyYAML would dump correct YAML and delete every word of that. So only the
    value lines move, matched in place.
    """
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if re.match(rf"^{re.escape(block)}:\s*(#.*)?$", ln)), None)
    if start is None:
        body = "".join(f"\n  {k}: {_scalar(v)}" for k, v in values.items())
        return text.rstrip("\n") + f"\n\n{block}:{body}\n"

    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end][:1].isspace()):
        end += 1
    body = lines[start + 1:end]

    # Blank lines after the last setting belong between blocks, not inside one,
    # so appended keys go above them.
    trailing = 0
    while body and not body[-1].strip():
        body.pop()
        trailing += 1

    for key, value in values.items():
        pattern = re.compile(rf"^(\s+){re.escape(key)}:.*$")
        for i, ln in enumerate(body):
            m = pattern.match(ln)
            if m:
                body[i] = f"{m.group(1)}{key}: {_scalar(value)}"
                break
        else:
            body.append(f"  {key}: {_scalar(value)}")

    body.extend([""] * trailing)
    out = "\n".join(lines[:start + 1] + body + lines[end:])
    return out + "\n" if text.endswith("\n") else out


@dataclass
class Typography:
    root: Path
    document: str = "calibri"
    console: str = "calibri"
    faces: dict = field(default_factory=dict)
    page: Page = field(default_factory=Page)
    text: Text = field(default_factory=Text)

    # --------------------------------------------------------------
    @classmethod
    def load(cls, root: Path | str = ".") -> "Typography":
        root = Path(root)
        path = root / CONFIG
        cfg = {}
        if path.exists():
            cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        faces = {}
        for key, raw in (cfg.get("faces") or {}).items():
            faces[key] = Face(key=key, label=raw.get("label", key),
                              **{k: v for k, v in raw.items() if k != "label"})
        raw_page = {**PAGE_DEFAULTS, **(cfg.get("page") or {})}
        raw_text = {**TEXT_DEFAULTS, **(cfg.get("text") or {})}
        t = cls(root=root, faces=faces, page=Page(**raw_page),
                text=Text(**{k: str(v) for k, v in raw_text.items()}),
                document=cfg.get("document", "calibri"),
                console=cfg.get("console", "calibri"))
        return t

    def save(self):
        path = self.root / CONFIG
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        # rewrite only the value lines, so the comments and the face
        # definitions a person wrote by hand survive
        for key, value in (("document", self.document), ("console", self.console)):
            pattern = re.compile(rf"^{key}:.*$", re.M)
            if pattern.search(text):
                text = pattern.sub(f"{key}: {value}", text, count=1)
            else:
                text += f"\n{key}: {value}\n"
        text = rewrite_block(text, "page", {
            "paper": self.page.paper_name, "side": self.page.side,
            "edge": self.page.edge, "header_band": self.page.header_band,
            "footer_band": self.page.footer_band, "gap": self.page.gap})
        text = rewrite_block(text, "text", {
            "align": self.text.align, "hyphens": self.text.hyphens})
        path.write_text(text, encoding="utf-8")

    # --------------------------------------------------------------
    def plan_page(self, **changes) -> tuple["Page", list[str]]:
        """Work out the page these changes would give, without writing it.

        Separate from `set_page` so a caller changing several things at once can
        find out that one of them is bad *before* any of them is on disk. The
        panel posts the whole form in one go, and a refusal that had already
        saved half the form would leave the document set on a sheet nobody
        chose.

        A margin is checked against the sheet it sits on rather than against a
        fixed ceiling, because 25mm is generous on A4 and most of the width of
        an A5 page.
        """
        from dataclasses import replace as _replace
        page = _replace(self.page)
        touched = []
        for key, raw in changes.items():
            if raw is None or raw == "":
                continue
            if key == "paper":
                match = next((n for n in PAPERS if n.lower() == str(raw).strip().lower()),
                             None)
                if match is None:
                    raise ValueError(f"no such paper size: {raw}. "
                                     f"try one of: {', '.join(PAPERS)}")
                if match != page.paper_name:
                    page.paper, touched = match, touched + ["paper"]
                continue
            if key not in ("side", "edge", "header_band", "footer_band", "gap"):
                raise ValueError(f"not a page setting: {key}")
            try:
                value = float(raw)
            except (TypeError, ValueError):
                raise ValueError(f"{key} is a measurement in millimetres, not {raw!r}")
            if value < 0:
                raise ValueError(f"{key} cannot be negative")
            if getattr(page, key) != value:
                setattr(page, key, value)
                touched.append(key)

        if page.text_width_mm < 60:
            raise ValueError(
                f"side margins of {page.side:g}mm leave {page.text_width_mm:g}mm "
                f"of {page.paper_name} to print on, which is not a column of text")
        if page.margin_top + page.margin_bottom > page.height_mm - 60:
            raise ValueError(
                "the header and footer bands leave no room for the body on "
                f"{page.paper_name}")
        return page, touched

    def set_page(self, **changes) -> list[str]:
        """Change the page setup, refusing anything that would not print."""
        page, touched = self.plan_page(**changes)
        if touched:
            self.page = page
            self.save()
        return touched

    def plan_text(self, align: str | None = None,
                  hyphens: str | None = None) -> tuple["Text", list[str]]:
        """The same, for how body text is set. Both are words, not booleans."""
        from dataclasses import replace as _replace
        text = _replace(self.text)
        touched = []
        if align:
            want = str(align).strip().lower()
            if want not in ("left", "justify"):
                raise ValueError("align is left or justify")
            if want != text.align:
                text.align, touched = want, touched + ["align"]
        if hyphens:
            want = str(hyphens).strip().lower()
            if want not in ("on", "off"):
                raise ValueError("hyphens is on or off")
            if want != text.hyphens:
                text.hyphens, touched = want, touched + ["hyphens"]
        return text, touched

    def set_text(self, **changes) -> list[str]:
        """Change how body text is set."""
        text, touched = self.plan_text(**changes)
        if touched:
            self.text = text
            self.save()
        return touched

    # --------------------------------------------------------------
    def face(self, which: str = "document") -> Face:
        key = self.document if which == "document" else self.console
        if key in self.faces:
            return self.faces[key]
        if self.faces:
            return next(iter(self.faces.values()))
        return Face(key="fallback", label="System",
                    body=["-apple-system", "sans-serif"], mono=["Menlo", "monospace"])

    def choose(self, which: str, key: str):
        if key not in self.faces:
            raise ValueError(f"no such typeface: {key}. "
                             f"try one of: {', '.join(sorted(self.faces))}")
        if which not in ("document", "console"):
            raise ValueError("which must be document or console")
        setattr(self, which, key)
        self.save()

    # --------------------------------------------------------------
    def available(self, face: Face) -> bool:
        """Is the face's own family here, rather than one of its fallbacks?"""
        if not face.body:
            return False
        if face.primary.startswith("-") or face.primary == "sans-serif":
            return True                      # the system stack is always here
        if face.webfont:
            return True                      # Chromium can fetch it
        return face.primary.lower() in installed_families()

    def table(self) -> list[dict]:
        return [{
            "key": f.key, "label": f.label, "primary": f.primary,
            "available": self.available(f), "webfont": bool(f.webfont),
            "note": f.note.strip(), "body_pt": f.body_pt,
            "is_document": f.key == self.document, "is_console": f.key == self.console,
            "url": f.webfont, "stack": f.css_body(),
        } for f in self.faces.values()]

    # --------------------------------------------------------------
    def verify(self, keys: list[str] | None = None, log=None) -> list[dict]:
        """Ask Chromium what it can actually resolve.

        `document.fonts.check()` is not usable here. For a local family it
        answers yes whenever the name can be resolved to *anything*, fallback
        included, so it reports Calibri as present on a machine that has never
        had it. The reliable test is metric comparison: render a string in the
        family with a sentinel behind it, and again in the sentinel alone. If
        the widths differ the family rendered. Two sentinels are used, because a
        face whose metrics happen to match one of them would otherwise read as
        missing.
        """
        from playwright.sync_api import sync_playwright
        emit = log or (lambda *_: None)
        targets = [self.faces[k] for k in (keys or self.faces) if k in self.faces]
        results = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.set_content("<html><body></body></html>")
            for f in targets:
                if f.webfont:
                    page.add_style_tag(url=f.webfont)
                    try:
                        page.evaluate("""(family) => document.fonts.load(`16px "${family}"`)
                                          .then(() => document.fonts.ready)""", f.primary)
                    except Exception:
                        pass
                ok = page.evaluate(MEASURE_JS, f.primary)
                results.append({"key": f.key, "label": f.label,
                                "primary": f.primary, "ok": bool(ok),
                                "source": "webfont" if f.webfont else "installed"})
                emit(f"  {'yes' if ok else 'no ':3} {f.label} ({f.primary})")
            browser.close()
        return results


MEASURE_JS = r"""
(family) => {
  if (family.startsWith('-') || family === 'sans-serif') return true;
  const probe = 'mmmmmmmmmmlliWWWQ0123456789';
  const c = document.createElement('canvas').getContext('2d');
  const width = (stack) => { c.font = `72px ${stack}`; return c.measureText(probe).width; };
  // A family that renders shifts the width away from the sentinel behind it.
  // Both sentinels must agree that nothing moved before it counts as missing.
  return ['monospace', 'serif'].some(
    (s) => width(`"${family}", ${s}`) !== width(s));
}
"""
