"""One pass over the whole document that fixes the writing.

The mechanical pass could tell that "Enter publisher name" is not the name of a
control. It could not tell what to do about it, so it did the only thing it
knew: delete. That is wrong twice over. Deleting loses the description, which is
often the only sentence anyone has written about that control. And it arrives as
ten separate proposals, each saying "3 entries removed", which is a list of
chores rather than a conclusion.

A person doing this work does not delete. They look at the entry, look at the
section around it, and decide:

* this is help text for a field already documented, so fold it in and drop it;
* this is the only record of a control nobody named, so give it its real name;
* this is a placeholder for a field right there, so note it and drop it;
* this is a stray value, so it goes.

That judgement needs the section in view and the crawl evidence beside it, which
is what this asks for. It comes back as a list of operations rather than a
rewritten file, because a rewritten file arrives with the YAML reformatted and
one bad line discards every good decision in it. The operations are applied
here, where the structure cannot be damaged.

Everything lands as a single proposal covering the whole document, with one
diff per section and one decision to make.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .naming import is_not_a_control, why_not

STORE = "review/tidy.json"


@dataclass
class Edit:
    section: str
    number: str
    title: str
    before: str
    after: str
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


PROMPT = """You are tidying one section of this technical documentation.

Section: {title}

These entries are documented correctly. Do not touch them:
{good}

These entries are named by something that is not the name of a control. Each one
is a placeholder that sits inside an empty field, a sentence from a tooltip, or a
heading that groups fields. Their descriptions are often the only thing anyone
has written about that control, so they are not simply deleted:
{bad}

This is what the crawler read from the live screen. The names here are the real
names of the controls:
{evidence}

For each of the badly named entries, decide one of:

  DROP <name> | <why>
      Its description repeats something already covered by one of the correct
      entries above. Say which one.

  RENAME <name> >> <real name> | <why>
      It is the only record of a real control, and the evidence or its own
      description tells you what that control is called. Give it the name a
      person would see on the screen.

  KEEP <name> | <why>
      It is genuinely a control that happens to read oddly. Rare.

Rules for a name you write:
  * it is what the screen shows, in sentence case, no trailing punctuation
  * never a whole sentence, never instruction text, never a bare value
  * never the name of one account, publisher or partner. A back link reading
    "Back to Test Publisher 11" is called "Back to the partner", because every
    reader has a different one
  * if the evidence does not tell you the real name and the description does
    not either, use DROP rather than inventing one

Output nothing but those lines, one per entry.
"""


@dataclass
class Tidy:
    project: object
    root: Path
    edits: list = field(default_factory=list)
    skipped: list = field(default_factory=list)

    # ------------------------------------------------------------------
    def run(self, section_ids: list[str] | None = None, log=None) -> list[Edit]:
        emit = log or (lambda *_: None)
        try:
            from .lint import _masked_values
            set_masked_values(_masked_values(self.project))
        except Exception:
            pass
        targets = [n for n in self.project.nodes
                   if n.section is not None
                   and (not section_ids or n.id in section_ids)
                   and _problem_names(n.section)]
        if not targets:
            emit("nothing to tidy: every entry is named like a control")
            return []

        emit(f"tidying {len(targets)} section(s)")
        for node in targets:
            sec = node.section
            label = f"{node.number} {sec.title}"
            bad = _problem_names(sec)
            emit(f"  {label}: {len(bad)} entry(ies) to decide on")
            ops = self._decide(sec, node, bad, emit)
            if not ops:
                self.skipped.append(f"{sec.id}: no decision could be made")
                continue
            before = sec.to_markdown()
            after, notes = _apply_ops(before, ops)
            if after == before:
                self.skipped.append(f"{sec.id}: the decisions changed nothing")
                continue
            if not self._valid(sec, after, emit):
                continue
            self.edits.append(Edit(section=sec.id, number=node.number,
                                   title=sec.title, before=before, after=after,
                                   notes=notes))
            emit(f"    {'; '.join(notes[:3])}"
                 + (f" and {len(notes) - 3} more" if len(notes) > 3 else ""))

        self.save()
        emit(f"done: {len(self.edits)} section(s) rewritten, "
             f"one decision to make")
        return self.edits

    # ------------------------------------------------------------------
    def _decide(self, sec, node, bad: list[str], emit) -> list[tuple]:
        from .capture import merged_inventory
        from .console import assist

        good = [f"  - {n}" for n in _good_names(sec)]
        badlines = []
        for name in bad:
            desc = _description_of(sec, name)
            reason = why_not(name) or (
                "the name of one account's row rather than of the control, so "
                "the reader is looking at a different one")
            badlines.append(f"  - {name}\n      its description says: {desc}"
                            f"\n      it is {reason}")

        merged, _ = merged_inventory(self.root / "capture")
        ev = []
        for sid in sec.screens:
            rec = merged.get("screens", {}).get(sid) or {}
            for form in (rec.get("forms") or {}).get("forms", []):
                for f in form.get("fields", []):
                    if f.get("name"):
                        ev.append(f"  - {f['name']} ({f.get('kind', 'field')})")
            for kind, values in (rec.get("elements") or {}).items():
                for v in values[:24]:
                    ev.append(f"  - {v} ({kind})")
        evidence = "\n".join(dict.fromkeys(ev)) or "  (nothing was captured)"

        prompt = PROMPT.format(title=f"{node.number} {sec.title}",
                               good="\n".join(good) or "  (none)",
                               bad="\n".join(badlines),
                               evidence=evidence)
        result = assist.run_model(prompt, timeout=300)
        if not result.ok:
            emit(f"    the writer could not be reached: {(result.error or '')[:90]}")
            return []
        return _parse_ops(result.output or "", bad)

    # ------------------------------------------------------------------
    def _valid(self, sec, after: str, emit) -> bool:
        from .model import parse_section
        try:
            parsed = parse_section(after, sec.path)
        except Exception as e:
            self.skipped.append(f"{sec.id}: the result did not parse: {e}")
            emit(f"    the result did not parse, discarded: {e}")
            return False
        if parsed.id != sec.id:
            self.skipped.append(f"{sec.id}: the id changed")
            return False
        left = [n for n in _problem_names(parsed)]
        if left:
            emit(f"    {len(left)} entry(ies) still badly named, kept for a person")
        return True

    # ------------------------------------------------------------------
    def save(self):
        path = self.root / STORE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "at": datetime.now().isoformat(timespec="seconds"),
            "edits": [e.to_dict() for e in self.edits],
            "skipped": self.skipped,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def load(root: Path) -> dict:
        path = Path(root) / STORE
        if not path.exists():
            return {"edits": [], "skipped": [], "at": ""}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"edits": [], "skipped": [], "at": ""}

    @staticmethod
    def apply(root: Path, project, history, knowledge=None, log=None) -> dict:
        """Write every decision at once, each recorded separately.

        One approval, but one history entry per section: a document-wide undo
        is not a thing anybody wants, and being able to put back exactly one
        section is.
        """
        emit = log or (lambda *_: None)
        from .model import parse_section
        data = Tidy.load(root)
        done, failed = [], []
        for e in data.get("edits", []):
            sec = project.sections.get(e["section"])
            if sec is None:
                failed.append(f"{e['section']}: no longer exists")
                continue
            if sec.to_markdown() != e["before"]:
                failed.append(f"{e['section']}: changed since this was prepared")
                continue
            try:
                parsed = parse_section(e["after"], sec.path)
                if parsed.id != sec.id:
                    raise ValueError("the id changed")
            except Exception as exc:
                failed.append(f"{e['section']}: {exc}")
                continue
            sec.path.write_text(e["after"], encoding="utf-8")
            history.record(sec.id, sec.path, e["before"], e["after"],
                           actor="assist", action="tidy",
                           note="; ".join(e.get("notes", [])[:3]) or "tidied")
            if knowledge is not None:
                try:
                    knowledge.record_accepted(sec.id, "tidy", e["after"])
                except Exception:
                    pass
            done.append(e["section"])
            emit(f"  {e['number']} {e['title']}: written")
        if done:
            Tidy.clear(root)
        return {"written": done, "failed": failed}

    @staticmethod
    def clear(root: Path):
        path = Path(root) / STORE
        if path.exists():
            path.unlink()


# ---------------------------------------------------------------------------
def _entries(section):
    for b in section.blocks:
        for it in (b.items or []):
            if isinstance(it, dict):
                nm = str(it.get("field") or it.get("name") or it.get("action")
                         or it.get("column") or it.get("term") or "")
                if nm:
                    yield nm, it


def _good_names(section) -> list[str]:
    return [n for n, _ in _entries(section) if not is_not_a_control(n)]


_MASKED: dict = {}


def set_masked_values(values) -> None:
    """The placeholders the crawler substitutes for real entity names.

    A name carrying one of these describes one account's row. "Back to Test
    Publisher 11" is what the button said on the screen somebody crawled, and
    the reader is looking at a different partner.
    """
    _MASKED["values"] = tuple(values or ())


def _carries_a_value(name: str) -> bool:
    return any(v in (name or "") for v in _MASKED.get("values", ()))


def _problem_names(section) -> list[str]:
    return [n for n, _ in _entries(section)
            if is_not_a_control(n) or _carries_a_value(n)]


def _description_of(section, name: str) -> str:
    for n, it in _entries(section):
        if n == name:
            return str(it.get("description", "")).strip() or "(nothing)"
    return "(nothing)"


OP = re.compile(r"^\s*(DROP|RENAME|KEEP)\s+(.+?)\s*(?:\|\s*(.*))?$", re.I)


def _parse_ops(text: str, wanted: list[str]) -> list[tuple]:
    """Read the decisions back, ignoring anything that is not one."""
    ops = []
    for line in text.splitlines():
        m = OP.match(line)
        if not m:
            continue
        verb, body, why = m.group(1).upper(), m.group(2).strip(), (m.group(3) or "").strip()
        if verb == "RENAME":
            if ">>" not in body:
                continue
            old, _, new = body.partition(">>")
            old, new = old.strip(), new.strip()
            if (old in wanted and new and not is_not_a_control(new)
                    and not _carries_a_value(new)):
                ops.append(("rename", old, new, why))
        elif verb == "DROP":
            if body in wanted:
                ops.append(("drop", body, "", why))
        elif verb == "KEEP":
            if body in wanted:
                ops.append(("keep", body, "", why))
    return ops


def _apply_ops(text: str, ops: list[tuple]) -> tuple[str, list[str]]:
    """Rename and remove entries by line surgery, touching nothing else."""
    renames = {old: new for kind, old, new, _ in ops if kind == "rename"}
    drops = {old for kind, old, _, _ in ops if kind == "drop"}
    notes = []

    lines = text.splitlines(keepends=True)
    key = re.compile(r"^(\s*)-\s*(field|name|action|column|term):\s*(.+?)\s*$")
    out, i = [], 0

    while i < len(lines):
        m = key.match(lines[i])
        if not m:
            out.append(lines[i]); i += 1
            continue
        indent, label, raw = m.group(1), m.group(2), m.group(3)
        name = raw.strip().strip("'\"")

        block = [lines[i]]
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= len(indent) \
                    and (nxt.lstrip().startswith("-") or nxt.lstrip().startswith("```")):
                break
            block.append(nxt); j += 1

        if name in drops:
            notes.append(f"removed {name[:40]}")
        elif name in renames:
            new = renames[name]
            block[0] = f"{indent}- {label}: {_quote(new)}\n"
            out.extend(block)
            notes.append(f"{name[:34]} is really {new}")
        else:
            out.extend(block)
        i = j
    return "".join(out), notes


def _quote(value: str) -> str:
    if ": " in value or value.startswith(("'", '"', "|", ">", "&", "*", "!", "@", "`", "#")):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value
