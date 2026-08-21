"""The pass a crawl makes over its own work.

A crawl that stops at "here is what changed" leaves the reader with homework:
images sitting in a capture folder, and `TODO: describe this.` markers that were
honest when written and are now answerable, because the evidence just arrived.

The sweep closes that. For every section the crawl touched it asks two questions:

* is the picture in the document still the picture the product shows;
* is there anything left unwritten that the new evidence can now answer.

Everything it produces is a proposal. Nothing here writes to a section, because
the person approving is the point of the whole arrangement.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .naming import is_not_a_control

STORE = "review/proposals.json"
TODO = re.compile(r"TODO:\s*describe this", re.I)

# Below this the pictures are the same screen and replacing one is churn.
IMAGE_DIFFERS = 0.18


@dataclass
class Proposal:
    id: str
    section: str
    kind: str                      # image | text
    title: str
    detail: str = ""
    before: str = ""
    after: str = ""
    asset: str = ""
    run: str = ""
    at: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def count_todos(section) -> int:
    n = 0
    for b in section.blocks:
        if TODO.search(b.text or ""):
            n += 1
        for it in b.items:
            if isinstance(it, dict):
                n += sum(1 for v in it.values() if isinstance(v, str) and TODO.search(v))
            elif TODO.search(str(it)):
                n += 1
    return n


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def stale_images(project, capture_root: Path, section) -> list[dict]:
    """Images whose captured version genuinely differs from what ships."""
    from .capture import merged_inventory
    from .imaging import distance, fingerprint_file

    merged, _ = merged_inventory(capture_root)
    origins = merged.get("_runs", {})
    out = []
    for name in section.screenshots():
        current = project.asset_path(name)
        if not current.exists():
            continue
        for screen_id in section.screens:
            run = origins.get(screen_id)
            if not run:
                continue
            fresh = capture_root / run / "screenshots" / name
            if not fresh.exists():
                continue
            if _sha(fresh) == _sha(current):
                continue
            try:
                d = distance(fingerprint_file(current), fingerprint_file(fresh))
            except Exception:
                d = 1.0
            if d >= IMAGE_DIFFERS:
                out.append({"asset": name, "run": run, "distance": round(d, 3)})
            break
    return out


FRONT = re.compile(r"^---\n(.*?)\n---\n", re.S)


def _restore_front_matter(text: str, sec) -> tuple[str, bool]:
    """Put back the identity fields the writer had no business changing.

    Returns the text and whether anything had to be restored.
    """
    m = FRONT.match(text)
    if not m:
        return text, False
    head = m.group(1)
    changed = False
    for key, want in (("id", sec.id),):
        line = re.compile(rf"^{key}:\s*(.*)$", re.M)
        found = line.search(head)
        if found is None:
            head = f"{key}: {want}\n" + head
            changed = True
        elif found.group(1).strip().strip("'\"") != str(want):
            head = line.sub(f"{key}: {want}", head, count=1)
            changed = True
    if not changed:
        return text, False
    return f"---\n{head}\n---\n" + text[m.end():], True


def _same_content(before: str, after: str, path) -> bool:
    """Do these two say the same thing, whatever the quoting?

    A round trip through the model reformats the YAML: single quotes become
    double, a plain scalar gains quotes, key order can shift. None of that is a
    change to the document, and a diff that shows only that wastes the one
    thing this system is careful with, which is the reviewer's attention.
    """
    from .model import parse_section
    try:
        a, b = parse_section(before, path), parse_section(after, path)
    except Exception:
        return before.strip() == after.strip()

    def shape(sec):
        return [(blk.kind, blk.text or "",
                 [sorted(i.items()) if isinstance(i, dict) else str(i)
                  for i in (blk.items or [])],
                 sorted((blk.attrs or {}).items()))
                for blk in sec.blocks]

    return shape(a) == shape(b) and a.title == b.title


def _all_names(section) -> list[str]:
    """Every name a list entry declares, described or not."""
    out = []
    for b in section.blocks:
        for it in (b.items or []):
            if not isinstance(it, dict):
                continue
            nm = str(it.get("field") or it.get("name") or it.get("action")
                     or it.get("column") or it.get("term") or "")
            if nm and nm not in out:
                out.append(nm)
    return out


def _unwritten_names(section) -> list[str]:
    """The names that still lack a description, in the order they appear."""
    out = []
    for b in section.blocks:
        for it in (b.items or []):
            if not isinstance(it, dict):
                continue
            for value in it.values():
                if isinstance(value, str) and TODO.search(value):
                    name = (it.get("field") or it.get("name") or it.get("action")
                            or it.get("column") or it.get("term") or "")
                    if name and str(name) not in out:
                        out.append(str(name))
                    break
    return out


ASK = """This screen belongs to a section of the documentation called
"{title}". These names appear on it and have no description yet:

{names}

Here is what the crawler read from the live screen:

{evidence}
{notes}
Write one description for each name you can answer from that evidence.

Rules:
  * one line per name, formatted exactly as `name :: description`
  * the description says what the control is for, in one sentence, no full stop
    needed, no em dashes, no URLs, no HTTP or API detail
  * describe only what the evidence supports. If a name is a stray value rather
    than a real control (a bare number, a set of initials, a timestamp), answer
    it as `name :: SKIP` and nothing else
  * if you cannot tell what something does, answer `name :: SKIP`
  * output nothing but those lines
"""


def _ask_for_descriptions(sec, node, wanted, inv, notes, emit) -> dict:
    from .console import assist
    import json as _json

    evidence = _json.dumps(inv, indent=2, ensure_ascii=False)[:9000]
    prompt = ASK.format(
        title=f"{node.number} {sec.title}",
        names="\n".join(f"  - {n}" for n in wanted),
        evidence=evidence,
        notes=f"\n{notes}\n" if notes else "")

    result = assist.run_model(prompt, timeout=240)
    if not result.ok:
        emit(f"    the writer could not be reached: {(result.error or '')[:80]}")
        return {}

    answers, declined = {}, []
    for line in (result.output or "").splitlines():
        if "::" not in line:
            continue
        name, _, desc = line.partition("::")
        name, desc = name.strip().lstrip("-* ").strip(), desc.strip()
        if not name or not desc:
            continue
        if desc.upper().startswith("SKIP"):
            # Not a control. A bare number, a set of initials, a timestamp:
            # something the crawler mistook for a field. It can never be
            # described, so leaving the marker means the document can never be
            # clean. It is offered for removal instead.
            if name in wanted:
                declined.append(name)
            continue
        # the reply is prose from a model; the house rules still apply to it
        desc = desc.replace("\u2014", ", ").strip().rstrip(".")
        if name in wanted and desc:
            answers[name] = desc
    if declined:
        emit(f"    {len(declined)} name(s) are not real controls, offering removal")
    return answers, declined


def _splice(text: str, answers: dict) -> tuple[str, int]:
    """Put each answer where its marker is, touching nothing else.

    Line surgery rather than a YAML round trip. The file keeps its ordering,
    its comments and its quoting, and the only thing that changes is the
    descriptions that were waiting to be written.
    """
    lines = text.splitlines(keepends=True)
    current, filled = None, 0
    name_key = re.compile(r"^(\s*-?\s*)(field|name|action|column|term):\s*(.+?)\s*$")
    desc_key = re.compile(r"^(\s*)description:\s*(.+?)\s*$")

    for i, line in enumerate(lines):
        m = name_key.match(line)
        if m:
            current = m.group(3).strip().strip("'\"")
            continue
        d = desc_key.match(line)
        if d and current and TODO.search(d.group(2)):
            answer = answers.get(current)
            if answer:
                lines[i] = f"{d.group(1)}description: {_quote(answer)}\n"
                filled += 1
                current = None
    return "".join(lines), filled


def _drop_items(text: str, names: list[str]) -> tuple[str, int]:
    """Remove list entries the writer identified as not being controls.

    An entry is only removed while its description is still unwritten. Anything
    a person has already described is theirs, whatever the writer thinks of the
    name.
    """
    if not names:
        return text, 0
    wanted = set(names)
    lines = text.splitlines(keepends=True)
    name_key = re.compile(r"^(\s*)-\s*(field|name|action|column|term):\s*(.+?)\s*$")
    out, i, dropped = [], 0, 0

    while i < len(lines):
        m = name_key.match(lines[i])
        if not m:
            out.append(lines[i]); i += 1
            continue
        indent, label = m.group(1), m.group(3).strip().strip("'\"")
        # gather the whole entry: its first line plus the deeper-indented lines
        block = [lines[i]]
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if not nxt.strip():
                block.append(nxt); j += 1; continue
            lead = len(nxt) - len(nxt.lstrip())
            if lead <= len(indent) and nxt.lstrip().startswith("-"):
                break
            if lead <= len(indent) and nxt.lstrip().startswith("```"):
                break
            block.append(nxt); j += 1
        joined = "".join(block)
        if label in wanted:
            dropped += 1
        else:
            out.extend(block)
        i = j
    return "".join(out), dropped


def _sha_of(path) -> str:
    import hashlib
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def _landed_where_asked(root: Path, screen_id: str, record: dict) -> bool:
    """Did the crawl of this screen finish on the page it was aiming for?"""
    from .drift import _plausible
    import yaml as _yaml
    path = Path(root) / "content" / "screens.yaml"
    if not path.exists():
        return True
    try:
        raw = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return True
    screens = raw.get("screens", raw) if isinstance(raw, dict) else raw
    expected = next((s.get("url") for s in (screens or [])
                     if isinstance(s, dict) and s.get("id") == screen_id), "")
    landed = record.get("url", "")
    if not expected or not landed:
        return True
    return _plausible(expected, landed)


def _insert_figure(text: str, shot: str, title: str) -> str:
    """Put the figure after the section's opening prose.

    Not at the top: a picture before a word of explanation is a screenshot
    dump. Not at the very end either, where nobody looks. After the paragraph
    that introduces the screen, which is where every hand-written section in
    this document puts it.
    """
    lines = text.splitlines(keepends=True)
    body_starts = 0
    fences = 0
    for i, line in enumerate(lines):
        if line.startswith("---"):
            fences += 1
            if fences == 2:
                body_starts = i + 1
                break

    figure = f"\n![{title}]({shot} =14.0cm)\n"

    # after the first paragraph of prose, or straight after the front matter if
    # the section opens with something else
    blank_seen = False
    for i in range(body_starts, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("```") or stripped.startswith("!["):
            return "".join(lines[:i]) + figure + "\n" + "".join(lines[i:])
        if not stripped and blank_seen:
            return "".join(lines[:i]) + figure + "".join(lines[i:])
        if stripped:
            blank_seen = True
    return text.rstrip("\n") + "\n" + figure


def _quote(value: str) -> str:
    """Quote a description so YAML reads it as one string.

    A value holding a colon and a space is the mistake that keeps arriving, and
    it turns a helpful sentence into a parse error the reviewer has to fix.
    """
    if ": " in value or value.startswith(("'", '"', "|", ">", "&", "*", "!", "@", "`")):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


class Sweep:
    """Runs the review and keeps the proposals it produced."""

    def __init__(self, project, root: Path, decisions=None, knowledge=None):
        self.project = project
        self.root = Path(root)
        self.decisions = decisions
        self.knowledge = knowledge
        self.proposals: list[Proposal] = []
        self.skipped: list[str] = []
        # what this run was actually in a position to judge, as (section, kind).
        # Anything outside it survives in the store: a sweep over one section
        # must not throw away another section's unreviewed proposal.
        self.examined: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------
    def run(self, section_ids: list[str] | None = None, log=None,
            write_text: bool = True) -> list[Proposal]:
        emit = log or (lambda *_: None)
        capture_root = self.root / "capture"
        targets = [n for n in self.project.nodes
                   if n.section is not None
                   and (not section_ids or n.id in section_ids)]
        emit(f"reviewing {len(targets)} section(s) against the crawl")

        for node in targets:
            sec = node.section
            label = f"{node.number} {sec.title}"
            self.examined.add((sec.id, "image"))
            if write_text:
                self.examined.add((sec.id, "text"))

            for item in stale_images(self.project, capture_root, sec):
                self.proposals.append(Proposal(
                    id=f"img-{sec.id}-{item['asset']}",
                    section=sec.id, kind="image",
                    title=f"{label}: the picture has changed",
                    detail=f"{item['asset']} differs from the captured version "
                           f"(visual difference {item['distance']})",
                    asset=item["asset"], run=item["run"],
                    at=datetime.now().isoformat(timespec="seconds")))
                emit(f"  {label}: {item['asset']} looks different now")

            fig = self._missing_figure(sec, node, emit)
            if fig:
                self.proposals.append(fig)

            todos = count_todos(sec)
            # Entries named by a placeholder or a tooltip usually carry a
            # description, so the unwritten count is zero and this used to skip
            # them entirely: sixty two of them sat in the document unreachable.
            if not todos:
                continue
            if not write_text:
                self.skipped.append(f"{label}: {todos} unwritten, text pass skipped")
                continue
            if todos:
                emit(f"  {label}: {todos} unwritten description(s), asking the writer")
            proposal = self._write_missing(sec, node, emit)
            if proposal:
                self.proposals.append(proposal)

        self.save()
        emit(f"done: {len(self.proposals)} proposal(s)")
        return self.proposals

    # ------------------------------------------------------------------
    def _missing_figure(self, sec, node, emit) -> Proposal | None:
        # ASSET-03 forbids the same picture in two sections, so proposing one
        # image to two of them would trade a missing figure for a build error.
        """A section that describes a screen and shows no picture of it.

        The crawl has usually already taken the picture: it is sitting in a
        capture folder because nothing in the document referred to it. Asking
        for another crawl to produce a file that exists is the sort of thing
        that makes people stop trusting a tool.
        """
        if sec.screenshots() or not sec.screens:
            return None
        if not hasattr(self, "_claimed"):
            self._claimed: set[str] = set()
        used = {n for node2 in self.project.nodes if node2.section
                for n in node2.section.screenshots()}
        # Identical bytes under two names is a build error, and the way it
        # happens is a screen that redirected: dashboard.main lands on /supply,
        # so its "capture" is a picture of the publishers list. Adding that to a
        # section about the sidebar would caption the wrong screen, which is
        # worse than showing nothing.
        used_hashes = {_sha_of(self.project.asset_path(n))
                       for n in used if self.project.asset_path(n).exists()}

        from .capture import merged_inventory
        merged, _ = merged_inventory(self.root / "capture")
        origins = merged.get("_runs", {})

        for screen_id in sec.screens:
            run = origins.get(screen_id)
            if not run:
                continue
            record = merged.get("screens", {}).get(screen_id) or {}
            shot = record.get("shot")
            if not shot:
                continue
            src = self.root / "capture" / run / "screenshots" / shot
            if not src.exists():
                continue
            if not _landed_where_asked(self.root, screen_id, record):
                emit(f"  {node.number} {sec.title}: the crawl of {screen_id} "
                     f"ended up somewhere else, so its picture is of another "
                     f"screen. Not offered.")
                continue
            if _sha_of(src) in used_hashes:
                emit(f"  {node.number} {sec.title}: the only picture of "
                     f"{screen_id} is the same image another section already "
                     f"shows, so this screen needs its own capture")
                continue
            if shot in used or shot in self._claimed:
                emit(f"  {node.number} {sec.title}: the only picture of "
                     f"{screen_id} already belongs to another section, so this "
                     f"one needs its own capture")
                continue

            before = sec.to_markdown()
            after = _insert_figure(before, shot, sec.title)
            if after == before:
                continue

            from .model import parse_section
            try:
                parsed = parse_section(after, sec.path)
            except Exception as e:
                self.skipped.append(f"{sec.id}: adding a figure did not parse: {e}")
                return None

            self._claimed.add(shot)
            emit(f"  {node.number} {sec.title}: has a screen and no picture of it, "
                 f"and {shot} is already captured")
            return Proposal(
                id=f"fig-{sec.id}",
                section=sec.id, kind="text",
                title=f"{node.number} {sec.title}: add the picture of this screen",
                detail=f"{shot} was captured for {screen_id} and nothing in the "
                       f"document refers to it",
                before=before, after=after,
                at=datetime.now().isoformat(timespec="seconds"))
        return None

    # ------------------------------------------------------------------
    def _write_missing(self, sec, node, emit) -> Proposal | None:
        """Ask for the missing descriptions, not for the file back.

        The obvious design is to hand the writer the section and take the
        rewritten section as the answer. It does not survive contact: the reply
        comes back with the YAML re-serialised, sometimes with the id rewritten,
        sometimes as a partial file, and each of those failures threw away every
        good description in the reply along with the bad. Thirty nine markers
        sat unwritten across repeated crawls that way, and nothing said so.

        So the question is now narrow: here are the names that lack a
        description, here is what the crawl saw, answer the ones you can. The
        answers are spliced in here, where the structure is already known and
        cannot be damaged by anything the model does. A name it declines to
        answer keeps its marker, which is the honest outcome and a visible one.
        """
        from .console import assist
        from .capture import merged_inventory

        merged, _ = merged_inventory(self.root / "capture")
        inv = {sid: merged["screens"][sid] for sid in sec.screens
               if sid in merged.get("screens", {})}
        if not inv:
            self.skipped.append(f"{sec.id}: no crawl evidence, left alone")
            emit("    no evidence for this section, leaving the markers alone")
            return None

        wanted = _unwritten_names(sec)

        # Entries named by a placeholder or a tooltip are not this pass's work.
        # Removing them loses the description, which is often the only sentence
        # written about that control. `tidy` decides what each one really is.
        misnamed: list[str] = []

        if not wanted:
            return None

        # Some names need no judgement. A bare number, a zero-width space, a
        # pair of initials from an avatar: the crawler mistook a value for a
        # field, and no evidence will ever make it a control. Deciding these
        # here rather than asking is cheaper, and it is repeatable, which
        # matters more: a model asked the same question twice can answer it
        # differently, and these kept surviving that.
        junk = [n for n in wanted if is_not_a_control(n)]
        wanted = [n for n in wanted if n not in junk]
        junk = list(dict.fromkeys(junk + misnamed))
        if junk:
            emit(f"    {len(junk)} name(s) are plainly not controls: "
                 + ", ".join(repr(j) for j in junk[:4]))

        notes = ""
        if self.knowledge is not None:
            notes = self.knowledge.bundle_for(sec.id, self.decisions)
        elif self.decisions is not None:
            notes = self.decisions.notes_for(sec.id)

        answers, declined = ({}, [])
        if wanted:
            answers, declined = _ask_for_descriptions(
                sec, node, wanted, inv, notes, emit)
        declined = list(dict.fromkeys(junk + declined))
        if not answers and not declined:
            self.skipped.append(f"{sec.id}: the writer answered none of "
                                f"{len(wanted)} name(s)")
            emit(f"    the writer could not answer any of {len(wanted)} name(s)")
            return None

        before = sec.to_markdown()
        after, filled = _splice(before, answers)
        after, dropped = _drop_items(after, declined)
        if not filled and not dropped:
            self.skipped.append(f"{sec.id}: nothing could be spliced in")
            return None

        # the result must still be a section, and still be this section
        from .model import parse_section
        try:
            parsed = parse_section(after, sec.path)
        except Exception as e:
            self.skipped.append(f"{sec.id}: the filled section did not parse: {e}")
            emit(f"    the filled section did not parse, discarded: {e}")
            return None
        if parsed.id != sec.id:
            self.skipped.append(f"{sec.id}: the id changed while splicing")
            return None

        remaining = count_todos(parsed)
        parts = []
        if filled:
            parts.append(f"{filled} description(s) written")
        if dropped:
            parts.append(f"{dropped} entry that is not a real control removed"
                         if dropped == 1 else
                         f"{dropped} entries that are not real controls removed")
        emit(f"    proposal ready, {', '.join(parts)}, {remaining} left honest")
        return Proposal(
            id=f"txt-{sec.id}",
            section=sec.id, kind="text",
            title=f"{node.number} {sec.title}: "
                  + (" and ".join(parts) if parts else "descriptions written"),
            detail=", ".join(parts) + f". {remaining} marker(s) left as TODO",
            before=before, after=after,
            at=datetime.now().isoformat(timespec="seconds"))

    # ------------------------------------------------------------------
    def save(self):
        """Write this run's proposals, keeping the ones it never looked at."""
        path = self.root / STORE
        path.parent.mkdir(parents=True, exist_ok=True)
        kept = [x for x in self.load(self.root).get("proposals", [])
                if (x.get("section"), x.get("kind")) not in self.examined]
        mine = [p.to_dict() for p in self.proposals]
        seen = {p["id"] for p in mine}
        merged = mine + [x for x in kept if x.get("id") not in seen]
        path.write_text(json.dumps({
            "at": datetime.now().isoformat(timespec="seconds"),
            "proposals": merged,
            "skipped": self.skipped,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def load(root: Path) -> dict:
        path = Path(root) / STORE
        if not path.exists():
            return {"proposals": [], "skipped": [], "at": ""}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"proposals": [], "skipped": [], "at": ""}

    @staticmethod
    def drop(root: Path, proposal_id: str):
        data = Sweep.load(root)
        data["proposals"] = [p for p in data["proposals"] if p.get("id") != proposal_id]
        (Path(root) / STORE).write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
