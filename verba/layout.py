"""How the document is laid out on the page, as settings rather than as code.

Three things decided where the ink went before this existed, and only one of
them was a setting:

* the sheet was the literal ``A4``, written into the PDF renderer three times
  and into the DOCX renderer once more as ``21 x 29.7cm``;
* the margins were read from ``content/typography.yaml`` by the PDF and ignored
  by the DOCX, which used 25mm of its own, so the two outputs of the same build
  were laid out differently and nothing said which was the document;
* ``content/doc.yaml`` carried a ``build.page: A4`` key that no code read at
  all, which is the worst of the three: it looks like the choice is yours.

Now there is one page setup, both renderers read it, and this module is what
reads and writes it. The console and the command line both come through here,
so they cannot disagree about what the document is set in.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .typography import PAPERS, Typography, rewrite_block

DOC = "content/doc.yaml"

# What a person is actually choosing between, with the reason it matters. The
# console draws this rather than carrying its own copy of the list.
FIELDS = [
    ("paper", "Paper", "page", "The sheet. Sets the PDF and the DOCX together."),
    ("side", "Side margins", "page", "White space at the left and right edge, in mm."),
    ("edge", "Edge", "page", "From the paper edge to the header and footer text, in mm."),
    ("header_band", "Header band", "page", "The height the running header occupies, its rule included."),
    ("footer_band", "Footer band", "page", "The same for the footer."),
    ("gap", "Gap", "page", "Air between the header rule and the first line of text."),
    ("align", "Alignment", "text", "left or justify."),
    ("hyphens", "Hyphenation", "text", "on or off. Justified text needs it, or the word spacing rivers."),
    ("screenshot_width_cm", "Figure width", "build", "How wide a screenshot prints, in cm."),
    ("toc_depth", "Contents depth", "build", "Deepest level listed on the contents page."),
]


def _doc_path(root) -> Path:
    return Path(root) / DOC


def _build_cfg(root) -> dict:
    path = _doc_path(root)
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.exists() else {}
    return cfg.get("build") or {}


def read(root: Path | str = ".") -> dict:
    """Everything that decides where the ink goes, and what it may be set to."""
    typo = Typography.load(root)
    page, text, build = typo.page, typo.text, _build_cfg(root)
    width = float(build.get("screenshot_width_cm", 15.0))
    return {
        "paper": page.paper_name,
        "papers": [{"name": n, "mm": f"{w:g} x {h:g} mm"} for n, (w, h) in PAPERS.items()],
        "side": page.side, "edge": page.edge,
        "header_band": page.header_band, "footer_band": page.footer_band,
        "gap": page.gap,
        "align": text.align, "hyphens": text.hyphens,
        "screenshot_width_cm": width,
        "toc_depth": int(build.get("toc_depth", 3)),
        # Derived, and worth showing: these are the numbers that tell you
        # whether a setting is sane, and neither is one you type.
        "sheet_mm": f"{page.width_mm:g} x {page.height_mm:g}",
        "text_width_mm": round(page.text_width_mm, 1),
        "text_width_cm": round(page.text_width_mm / 10, 1),
        "margin_top": round(page.margin_top, 1),
        "margin_bottom": round(page.margin_bottom, 1),
        "figure_overflows": width * 10 > page.text_width_mm + 0.5,
        "fields": [{"key": k, "label": l, "group": g, "why": w} for k, l, g, w in FIELDS],
    }


def plan_build(root: Path | str = ".", page=None, **changes) -> dict:
    """What the build settings would become, without writing them.

    A figure is checked against the column it has to fit in rather than against
    a fixed number, because 15cm fits A4 comfortably and runs off an A5 page.
    The column is the one being *chosen*, not the one on disk: changing the
    paper and the figure width together has to be judged as one change.
    """
    root = Path(root)
    typo = Typography.load(root)
    page = page if page is not None else typo.page
    current = _build_cfg(root)
    write: dict = {}

    for key, raw in changes.items():
        if raw is None or raw == "":
            continue
        if key == "screenshot_width_cm":
            try:
                value = round(float(raw), 2)
            except (TypeError, ValueError):
                raise ValueError(f"figure width is a measurement in cm, not {raw!r}")
            if value <= 0:
                raise ValueError("a figure has to have a width")
            limit = page.text_width_mm / 10
            if value > limit + 0.05:
                raise ValueError(
                    f"a {value:g}cm figure does not fit the {limit:.1f}cm column on "
                    f"{page.paper_name} at {page.side:g}mm margins")
        elif key == "toc_depth":
            try:
                value = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"contents depth is a whole number, not {raw!r}")
            if not 1 <= value <= 4:
                raise ValueError("contents depth runs from 1 to 4")
        else:
            raise ValueError(f"not a build setting: {key}")
        if current.get(key) != value:
            write[key] = value

    return write


def _commit_build(root: Path | str, write: dict):
    if not write:
        return
    path = _doc_path(root)
    path.write_text(rewrite_block(path.read_text(encoding="utf-8"), "build", write),
                    encoding="utf-8")


def set_build(root: Path | str = ".", **changes) -> list[str]:
    """Write the document build settings, refusing what would not print."""
    write = plan_build(root, **changes)
    _commit_build(root, write)
    return sorted(write)


def apply(root: Path | str = ".", **changes) -> list[str]:
    """Set anything on this panel, wherever the file for it happens to be.

    The person is changing how the document looks. Which of two files a given
    setting is stored in is this module's problem, not theirs.
    """
    root = Path(root)
    typo = Typography.load(root)
    groups = {k: g for k, _, g, _ in FIELDS}
    unknown = [k for k in changes if k not in groups]
    if unknown:
        raise ValueError(f"not a layout setting: {', '.join(sorted(unknown))}")

    page_args = {k: v for k, v in changes.items() if groups[k] == "page"}
    text_args = {k: v for k, v in changes.items() if groups[k] == "text"}
    build_args = {k: v for k, v in changes.items() if groups[k] == "build"}

    # Everything is judged before anything is written. The panel posts the whole
    # form at once, so a refusal partway through used to leave the document set
    # on a sheet nobody had agreed to: the paper was already saved by the time
    # the figure width was rejected. Either the whole change lands or none of it
    # does.
    #
    # The figure is checked against the page being chosen rather than the page
    # on disk, so moving to A5 and narrowing the figures in the same edit is one
    # coherent change rather than two that contradict each other in sequence.
    page, page_touched = typo.plan_page(**page_args)
    text, text_touched = typo.plan_text(**text_args)
    build_write = plan_build(root, page=page, **build_args)

    if not (page_touched or text_touched or build_write):
        return []

    typo.page, typo.text = page, text
    if page_touched or text_touched:
        typo.save()
    _commit_build(root, build_write)
    return page_touched + text_touched + sorted(build_write)
