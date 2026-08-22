"""Things you noticed, and what the next run does about them.

Everything else in this system finds its own work: the rules, the crawl, the
survey. None of that helps with the thing you spotted on page 12 that no rule
describes, and telling a person to go and edit the section themselves is the
answer this system exists to avoid.

So a note is a sentence. "Figure 4.3 shows a real customer name." "The sidebar
section says three modules and there are two." It is written down where you saw
it, and the next run picks it up, works out which section it is about, decides
what kind of fix it needs, and does it.

A note is only ever closed by something that actually happened. If the run
cannot work out what to do, the note stays open and says why, because a list
that quietly forgets is worse than no list.
"""
from __future__ import annotations

from .atomic import write_json
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

STORE = "review/notes.json"

OPEN = "open"
FIXED = "fixed"
STUCK = "stuck"


@dataclass
class Note:
    id: str
    text: str
    section: str = ""          # if you knew it, or the run worked it out
    figure: str = ""           # a picture, if that is what you meant
    status: str = OPEN
    at: str = ""
    tried: int = 0
    outcome: str = ""          # what was done, or why it could not be
    history: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Notes:
    root: Path
    items: list = field(default_factory=list)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, root: Path | str = ".") -> "Notes":
        root = Path(root)
        path = root / STORE
        items = []
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                items = [Note(**n) for n in raw.get("notes", [])]
            except Exception:
                items = []
        return cls(root=root, items=items)

    def save(self):
        path = self.root / STORE
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, {"notes": [n.to_dict() for n in self.items]})

    # ------------------------------------------------------------------
    def add(self, text: str, section: str = "", figure: str = "") -> Note:
        text = (text or "").strip()
        if not text:
            raise ValueError("a note needs something written in it")
        n = Note(id=f"n{len(self.items) + 1:03d}-{_slug(text)}",
                 text=text, section=section, figure=figure,
                 at=datetime.now().isoformat(timespec="seconds"))
        self.items.append(n)
        self.save()
        return n

    def open_notes(self) -> list:
        return [n for n in self.items if n.status == OPEN]

    def close(self, note: Note, outcome: str, status: str = FIXED):
        note.status = status
        note.outcome = outcome
        note.tried += 1
        note.history.append({"at": datetime.now().isoformat(timespec="seconds"),
                             "status": status, "outcome": outcome})
        self.save()

    def reopen(self, note_id: str) -> bool:
        for n in self.items:
            if n.id == note_id:
                n.status = OPEN
                n.outcome = ""
                self.save()
                return True
        return False

    def drop(self, note_id: str) -> bool:
        before = len(self.items)
        self.items = [n for n in self.items if n.id != note_id]
        self.save()
        return len(self.items) < before

    def summary(self) -> dict:
        return {"total": len(self.items),
                "open": len([n for n in self.items if n.status == OPEN]),
                "fixed": len([n for n in self.items if n.status == FIXED]),
                "stuck": len([n for n in self.items if n.status == STUCK])}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower())[:28].strip("-") or "note"


# ---------------------------------------------------------------------------
ASK = """Someone reading this documentation wrote this down:

    "{note}"

{where}

This is the section they are most likely talking about, exactly as it is
written. Line numbers are for your reference only:

{section}

This is what the crawler last read from the live screens this section covers:

{evidence}

Work out what they meant and answer with one instruction:

  REPLACE <exact text from the section> >> <what it should say>
      Use when the wording is wrong or out of date. The text on the left has to
      appear in the section exactly as written above, once, character for
      character. Keep it short: one phrase or one sentence, not a paragraph.

  DROP <exact text from the section>
      Use when something should not be there at all.

  RECAPTURE <screen id>
      Use when the complaint is about a picture: it shows the wrong screen, an
      old layout, or a real customer name. Pick from the screens listed above.

  CANNOT <why>
      Use when the note is about something you cannot see from here, or when it
      needs a decision that is not yours: a judgement about scope, an opinion
      about tone, or a fact the evidence does not settle. Say plainly what a
      person would need to decide.

House rules for anything you write: no em dashes, no addresses or route paths,
no HTTP or API detail, and never name one account, publisher or partner.

Answer with the single instruction and nothing else.
"""


def resolve(note: Note, project, root: Path, log=None) -> tuple[str, str]:
    """Work out what a note means and carry it out.

    Returns (status, what happened).
    """
    emit = log or (lambda *_: None)
    from .console import assist

    node = _best_section(note, project)
    if node is None:
        return STUCK, ("could not tell which section this is about. Say which "
                       "one, or mention its title in the note")

    sec = node.section
    note.section = sec.id
    body = sec.to_markdown()
    evidence, screens = _evidence(sec, root)

    where = f"They were looking at section {node.number} {sec.title}."
    if note.figure:
        where += f" They mentioned the picture {note.figure}."

    prompt = ASK.format(note=note.text, where=where,
                        section=_numbered(body), evidence=evidence)
    result = assist.run_model(prompt, timeout=300)
    if not result.ok:
        return STUCK, f"the writer could not be reached: {(result.error or '')[:120]}"

    return _carry_out(result.output or "", note, sec, node, screens, root, emit)


def _carry_out(answer: str, note: Note, sec, node, screens, root: Path, emit):

    line = next((line.strip() for line in answer.splitlines() if line.strip()), "")
    if not line:
        return STUCK, "the writer answered with nothing"

    verb, _, rest = line.partition(" ")
    verb = verb.upper()

    if verb == "CANNOT":
        return STUCK, rest.strip() or "the writer could not work out what to do"

    if verb == "RECAPTURE":
        screen = rest.strip().strip("`'\"")
        if screen not in screens:
            screen = screens[0] if screens else ""
        if not screen:
            return STUCK, "this is about a picture, and the section maps to no screen"
        return "recapture:" + screen, f"needs a fresh capture of {screen}"

    body = sec.path.read_text(encoding="utf-8")

    if verb == "REPLACE":
        if ">>" not in rest:
            return STUCK, "the writer did not say what to replace it with"
        old, _, new = rest.partition(">>")
        old, new = _unquote(old), _unquote(new)
        if not old or body.count(old) != 1:
            return STUCK, (f"could not find that text once and only once "
                           f"({body.count(old)} match(es))")
        after = body.replace(old, new, 1)
        return _write(sec, body, after, root,
                      f"replaced {old[:40]!r} with {new[:40]!r}")

    if verb == "DROP":
        old = _unquote(rest)
        if not old or body.count(old) != 1:
            return STUCK, (f"could not find that text once and only once "
                           f"({body.count(old)} match(es))")
        after = body.replace(old, "", 1)
        return _write(sec, body, after, root, f"removed {old[:50]!r}")

    return STUCK, f"the writer answered with something unexpected: {line[:80]}"


def _write(sec, before: str, after: str, root: Path, what: str):
    from .history import History
    from .model import parse_section
    if after.strip() == before.strip():
        return STUCK, "that change would not alter anything"
    try:
        if parse_section(after, sec.path).id != sec.id:
            return STUCK, "the change would break the section"
    except Exception as e:
        return STUCK, f"the change would not parse: {e}"
    sec.path.write_text(after, encoding="utf-8")
    History(root).record(sec.id, sec.path, before, after, actor="note",
                         action="from a note", note=what)
    return FIXED, what


# ---------------------------------------------------------------------------
def _best_section(note: Note, project):
    """The section a note is about: the one named, or the closest match."""
    if note.section:
        for n in project.nodes:
            if n.section is not None and n.id == note.section:
                return n

    text = note.text.lower()

    # "figure 4.3" is not section 4.3. Figures are numbered per chapter in the
    # order they appear, so the third figure of chapter 4 can sit in 4.2.3 and
    # has nothing to do with the section called 4.3. Reading one as the other
    # sends the fix to the wrong page.
    fig = re.search(r"\b(?:figure|fig\.?|image|picture|screenshot)\s*"
                    r"(\d+)\.(\d+)\b", text)
    if fig:
        owner = _section_of_figure(project, int(fig.group(1)), int(fig.group(2)))
        if owner is not None:
            return owner

    # a number like 4.2.3, which is how people refer to a section
    m = re.search(r"\b(\d+(?:\.\d+){1,3})\b", note.text)
    if m:
        for n in project.nodes:
            if n.section is not None and n.number == m.group(1):
                return n

    # a figure name, which belongs to whichever section shows it
    if note.figure:
        for n in project.nodes:
            if n.section is not None and note.figure in n.section.screenshots():
                return n

    # otherwise the title with the most words in common
    best, score = None, 0
    words = {w for w in re.findall(r"[a-z]{4,}", text)}
    for n in project.nodes:
        if n.section is None:
            continue
        title = {w for w in re.findall(r"[a-z]{4,}", n.section.title.lower())}
        hit = len(words & title)
        if hit > score:
            best, score = n, hit
    return best if score else None


def _section_of_figure(project, chapter: int, index: int):
    """Which section holds figure N.M, counting the way the document numbers them."""
    counter: dict[int, int] = {}
    for node in project.nodes:
        if node.section is None:
            continue
        try:
            ch = int(str(node.number).split(".")[0])
        except ValueError:
            continue
        for block in node.section.blocks:
            if block.kind != "screenshot":
                continue
            # a captionless crop renders as a detail and is not numbered
            if not block.attrs.get("caption"):
                continue
            counter[ch] = counter.get(ch, 0) + 1
            if ch == chapter and counter[ch] == index:
                return node
    return None


def _evidence(sec, root: Path) -> tuple[str, list]:
    from .capture import merged_inventory
    merged, _ = merged_inventory(root / "capture")
    lines, screens = [], []
    for sid in sec.screens:
        rec = merged.get("screens", {}).get(sid)
        if not rec:
            continue
        screens.append(sid)
        lines.append(f"  {sid}:")
        for kind, values in (rec.get("elements") or {}).items():
            for v in list(values)[:18]:
                lines.append(f"    {v} ({kind})")
    return ("\n".join(lines) or "  (nothing was captured for this section)"), screens


def _numbered(body: str) -> str:
    return "\n".join(f"{i:>4} | {line}"
                     for i, line in enumerate(body.splitlines(), 1))


def _unquote(s: str) -> str:
    s = s.strip()
    for q in ('"', "'", "`"):
        if len(s) > 1 and s.startswith(q) and s.endswith(q):
            s = s[1:-1]
    return s.strip()
