"""Which sections an edition carries, and how to change that.

An edition used to be able to *add* a section and not to drop one. The only
mechanism was ``profiles:`` in a section's own front matter, which says "I
belong to these editions and no others". That answers the question from the
wrong end: to see what the customer edition contains you had to open all
thirty-eight section files and collect the answer, and to drop a chapter from
one edition you had to edit every file under it.

So an edition now declares what it carries, in the edition's own file:

.. code-block:: yaml

    sections:
      exclude: [dashboard-overview]        # this edition does not carry these
      include: [introduction, ...]         # or: this edition is exactly these

``exclude`` takes the whole branch, because excluding a chapter means excluding
what is under it. ``include`` keeps the ancestors of anything it names, so the
hierarchy and the numbering survive. Front matter still works and still wins:
a section written for one customer stays out of everyone else's edition
whatever an edition file says.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .model import _entry


def _path(root: Path | str, profile: str) -> Path:
    return Path(root) / "content" / "profiles" / f"{profile}.yaml"


def read(project) -> list[dict]:
    """Every section the outline names, and this edition's answer for it.

    Walks the outline rather than the built tree, because the built tree is
    what survived and this is a view of the decision itself.
    """
    prof = project.profile
    shipping = {n.id for n in project.nodes}
    numbers = {n.id: n.number for n in project.nodes}
    rows: list[dict] = []

    def walk(outline, depth: int, dropped_by: str | None):
        for entry in outline or []:
            sid, kids = _entry(entry)
            sec = project.sections.get(sid)
            declared = sec.profiles if sec is not None else None
            locked = declared is not None and prof.name not in declared
            carried = sid in shipping

            # A section is out for exactly one reason, and saying which one is
            # the difference between a setting and a puzzle. A child of a
            # dropped chapter is not itself a decision anybody took, so it says
            # whose decision it was.
            mine = sid in prof.exclude
            if locked:
                why = f"the section itself is only for: {', '.join(declared)}"
            elif mine:
                why = "left out of this edition"
            elif dropped_by:
                why = f"under {dropped_by}, which this edition leaves out"
            elif prof.include is not None and not carried:
                why = "not on this edition's list"
            elif prof.include is not None and sid not in prof.include:
                why = "kept because something under it is on the list"
            else:
                why = ""

            rows.append({
                "id": sid, "title": sec.title if sec is not None else sid,
                "number": numbers.get(sid, ""), "depth": depth,
                "carried": carried, "locked": locked, "why": why,
                # A child of a dropped chapter cannot be brought back on its
                # own: the chapter it lives in has to come back first.
                "settable": not locked and not dropped_by,
                "mode": "include" if prof.include is not None else "exclude",
            })
            walk(kids, depth + 1, dropped_by or (sid if mine else None))

    walk(project.config.get("outline", []), 0, None)
    return rows


def carry(root: Path | str, profile: str, section_id: str, carried: bool) -> str:
    """Put one section into this edition, or take it out. Returns what happened.

    Which list is edited follows the edition's existing mode, so an edition
    written as "everything except these" stays that, and one written as "exactly
    these" stays that too. Changing a setting should not quietly rewrite how the
    file is organised.
    """
    path = _path(root, profile)
    if not path.exists():
        raise ValueError(f"no such edition: {profile}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    picks = dict(data.get("sections") or {})
    include = picks.get("include")
    exclude = list(picks.get("exclude") or [])

    if include is not None:
        include = list(include)
        if carried and section_id not in include:
            include.append(section_id)
            what = f"{section_id} is now on the {profile} list"
        elif not carried and section_id in include:
            include.remove(section_id)
            what = f"{section_id} is off the {profile} list"
        else:
            return f"{profile} was already like that"
        picks["include"] = include
    else:
        if not carried and section_id not in exclude:
            exclude.append(section_id)
            what = f"{profile} no longer carries {section_id}"
        elif carried and section_id in exclude:
            exclude.remove(section_id)
            what = f"{profile} carries {section_id} again"
        else:
            return f"{profile} was already like that"
        picks["exclude"] = exclude

    picks = {k: v for k, v in picks.items() if v}
    _write(path, picks)
    return what


def reset(root: Path | str, profile: str) -> str:
    """Put an edition back to carrying the whole outline."""
    path = _path(root, profile)
    if not path.exists():
        raise ValueError(f"no such edition: {profile}")
    _write(path, {})
    return f"{profile} carries the whole document again"


HEADING = [
    "# What this edition carries. `exclude` drops a branch;",
    "# `include` makes the edition exactly what it lists.",
]


def _write(path: Path, picks: dict):
    """Replace the `sections:` block, leaving every other line where it was.

    These files are short and hand-written, with a comment at the top saying
    what the edition is for. Dumping the parsed document back would be correct
    YAML and would delete that.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.rstrip() == "sections:"), None)
    if start is None:
        keep, at = lines, len(lines)
    else:
        end = start + 1
        while end < len(lines) and (not lines[end].strip() or lines[end][:1].isspace()):
            end += 1
        # Take our own heading with the block. Left behind it accumulates a
        # fresh copy on every write; taken indiscriminately it would swallow a
        # comment the person wrote, so only the exact lines we emit are removed.
        while start and lines[start - 1] in HEADING:
            start -= 1
        keep, at = lines[:start] + lines[end:], start

    block: list[str] = []
    if picks:
        block += HEADING
        block.append("sections:")
        for key in ("include", "exclude"):
            if picks.get(key):
                block.append(f"  {key}:")
                block += [f"    - {sid}" for sid in picks[key]]
        block.append("")

    out = keep[:at] + block + keep[at:]
    text = "\n".join(out).rstrip("\n") + "\n"
    path.write_text(text, encoding="utf-8")
