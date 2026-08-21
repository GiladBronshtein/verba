"""Run the whole thing, and stop only where a person is genuinely needed.

Every piece of this system already worked on its own: crawl, survey, fill the
gaps, fix the writing, apply the differences, adopt the pictures, check the
rules. What it asked for in return was attention, one decision at a time, and
that is the wrong trade for work that is mostly mechanical.

This runs the loop. What makes it safe to leave alone is not confidence, it is
measurement: every step is applied, the rules are counted again, and a step that
made the document worse is put straight back. The system is allowed to be wrong,
it is not allowed to leave the document worse than it found it.

Three things it will not do:

* write to the platform, ever, for any reason;
* accept a figure from a screen that landed somewhere else, or a name it cannot
  justify from the evidence;
* decide something a person owns. Those are collected and handed back.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


class _tee:
    """Send anything printed inside this block to a logger as well.

    The logger is often `print`, and `print` writes to `sys.stdout`, which
    inside this block is this object: emitting a line would hand it straight
    back and the whole thing recurses until the interpreter gives up. So the
    real stdout is put back for the duration of each emit.
    """

    def __init__(self, emit, indent: str = ""):
        self.emit, self.indent, self.buf = emit, indent, ""
        self.real = None

    def _say(self, line: str):
        import sys
        saved = sys.stdout
        if self.real is not None:
            sys.stdout = self.real
        try:
            self.emit(line)
        finally:
            sys.stdout = saved

    def write(self, chunk: str):
        self.buf += chunk
        while "\n" in self.buf:
            line, _, self.buf = self.buf.partition("\n")
            if line.strip():
                self._say(self.indent + line.rstrip())

    def flush(self):
        if self.buf.strip():
            self._say(self.indent + self.buf.rstrip())
        self.buf = ""

    def __enter__(self):
        import contextlib, sys
        self.real = sys.stdout
        self._redirect = contextlib.redirect_stdout(self)
        self._redirect.__enter__()
        return self

    def __exit__(self, *exc):
        self.flush()
        return self._redirect.__exit__(*exc)


@dataclass
class Step:
    name: str
    did: str = ""
    errors_before: int = 0
    errors_after: int = 0
    reverted: bool = False
    note: str = ""

    @property
    def better(self) -> int:
        return self.errors_before - self.errors_after

    def to_dict(self) -> dict:
        return {**self.__dict__, "better": self.better}


@dataclass
class Auto:
    root: Path
    steps: list = field(default_factory=list)
    for_you: list = field(default_factory=list)
    rounds_run: int = 0

    # ------------------------------------------------------------------
    def run(self, rounds: int = 3, crawl: bool = True, log=None) -> dict:
        emit = log or (lambda *_: None)
        start = self._errors()
        emit(f"the document breaks {start} rule(s) today"
             if start else "the document breaks no rules today")
        emit("looking for anything else that needs doing")

        for r in range(1, rounds + 1):
            self.rounds_run = r
            emit("")
            emit(f"round {r}")
            before = self._errors()

            if crawl and r == 1:
                self._step("look at the live system", self._crawl_what_is_needed, emit)

            done_before = len([x for x in self.steps if x.did])
            # Yours first. A note is the one piece of work in this system that
            # somebody actually asked for, so it does not queue behind the
            # housekeeping.
            self._step("do what you asked for", self._notes, emit)
            self._step("clear what a failed write left behind", self._strays, emit)
            self._step("fill the gaps the crawl can answer", self._sweep, emit)
            self._step("fix the writing", self._tidy, emit)
            self._step("apply the differences", self._drift, emit)
            self._step("use the pictures the crawl took", self._images, emit)

            # Not "the rules are clean": a document can break no rules and still
            # have a dozen differences from the live system sitting unapplied.
            # The loop stops when a round does nothing, which is the only
            # honest definition of finished.
            did_something = len([x for x in self.steps if x.did]) > done_before
            after = self._errors()
            if not did_something:
                emit("  this round changed nothing, so another would not either")
                break
            emit(f"  round {r} done, {after} finding(s) left")

        self._collect_what_is_left(emit)
        return self.report(start, emit)

    # ------------------------------------------------------------------
    def _step(self, name: str, fn, emit) -> None:
        """Do one thing, count the rules again, and undo it if it went backwards."""
        before = self._errors()
        step = Step(name=name, errors_before=before)
        try:
            # Snapshot the content itself rather than trusting the history to
            # hand it back: `entries()` keeps the metadata and drops the text,
            # so a revert built on it silently restores nothing.
            snapshot = self._snapshot()
            step.did = fn(emit) or ""
        except Exception as e:
            step.note = f"could not run: {e}"
            emit(f"  {name}: {step.note}")
            self.steps.append(step)
            return

        step.errors_after = self._errors()
        if not step.did:
            emit(f"  {name}: nothing to do")
            self.steps.append(step)
            return

        if step.errors_after > step.errors_before:
            # The whole basis for leaving this alone. A pass that introduces
            # findings is a pass that made the document worse, whatever it
            # believed it was doing.
            undone = self._restore(snapshot)
            # A decision recorded by a step that was then undone leaves the
            # document without the change and the record saying it was approved,
            # so every later run skips it and it can never be reconsidered.
            self._forget_decisions_since(snapshot)
            step.reverted = True
            step.note = (f"put back: it added "
                         f"{step.errors_after - step.errors_before} finding(s)")
            emit(f"  {name}: {step.did}")
            emit(f"    reverted {undone} change(s), because the rules got worse "
                 f"({step.errors_before} to {step.errors_after})")
            step.errors_after = self._errors()
        else:
            emit(f"  {name}: {step.did}"
                 + (f", {step.better} finding(s) fewer" if step.better else ""))
        self.steps.append(step)

    # -- the passes ------------------------------------------------------
    def _crawl_what_is_needed(self, emit) -> str:
        from .survey import Survey
        p = self._project()
        sv = Survey.run(p, self.root)
        worth = sv.screens_worth_crawling()
        if not worth:
            emit("    the last crawl still answers everything, so not crawling")
            return ""
        emit(f"    {len(worth)} screen(s) would tell us something new")
        # The crawl is the slow step and it reports on stdout. Watching a blank
        # panel for two minutes is how someone decides a thing has hung, so its
        # output goes where the person is looking.
        if not self._capture(worth, emit):
            self.for_you.append({
                "what": "the crawl could not run",
                "why": "see the log above",
                "do": "check the connection under Setup, then run it again"})
            return ""
        return f"{len(worth)} screen(s) captured"

    def _notes(self, emit) -> str:
        """Work through what you wrote down, and say what happened to each."""
        from .notes import Notes, resolve, FIXED, STUCK
        notes = Notes.load(self.root)
        todo = notes.open_notes()
        if not todo:
            return ""

        fixed, stuck, recapture = 0, 0, []
        for note in todo:
            status, what = resolve(note, self._project(), self.root, log=emit)
            if status.startswith("recapture:"):
                screen = status.split(":", 1)[1]
                recapture.append((note, screen))
                emit(f"    {note.text[:60]}: needs {screen} captured again")
                continue
            notes.close(note, what, status)
            if status == FIXED:
                fixed += 1
                emit(f"    {note.text[:56]}: {what[:60]}")
            else:
                stuck += 1
                emit(f"    {note.text[:56]}: could not, {what[:52]}")
                self.for_you.append({
                    "what": f"you wrote: {note.text}",
                    "why": what,
                    "do": what if len(what) > 40 else
                          "say which section, or make the note more specific"})

        # a note about a picture is answered by going and looking again
        if recapture:
            screens = sorted({s for _, s in recapture})
            emit(f"    capturing {len(screens)} screen(s) a note asked about")
            if self._capture(screens, emit):
                for note, screen in recapture:
                    notes.close(note, f"{screen} captured again", FIXED)
                    fixed += 1
            else:
                for note, screen in recapture:
                    notes.close(note, f"{screen} could not be captured", STUCK)
                    stuck += 1

        bits = []
        if fixed:
            bits.append(f"{fixed} of your note(s) done")
        if stuck:
            bits.append(f"{stuck} handed back")
        return ", ".join(bits)

    def _capture(self, screens: list, emit) -> bool:
        """Crawl exactly these screens. Returns whether it ran."""
        try:
            from .cli import cmd_capture
            import argparse
            args = argparse.Namespace(
                root=str(self.root), profile=None, screens=",".join(screens),
                section=None, headed=False, no_mask=False, replay_steps=False,
                heal=True, sweep=False)
            with _tee(emit, indent="      "):
                cmd_capture(args)
            return True
        except Exception as e:
            emit(f"      the crawl could not run: {e}")
            return False

    def _strays(self, emit) -> str:
        """Remove a block that is nothing but the wreckage of an earlier write.

        The Introduction's whole body was the line `description: "TODO: describe
        this."`, in backticks, as prose. No writer can fill that in, because
        there is nothing there to describe: it is a fragment of YAML that
        escaped into the text. It cannot be crawled away either, and every pass
        that offered to fix it was offering something it could not do.
        """
        import re as _re
        from .history import History
        artifact = _re.compile(
            r"^`?\s*description:\s*[\"']?TODO:\s*describe this\.?[\"']?\s*`?$",
            _re.I)
        p = self._project()
        h = History(self.root)
        cleared = 0

        for node in p.nodes:
            sec = node.section
            if sec is None:
                continue
            text = sec.path.read_text(encoding="utf-8")
            kept, dropped = [], 0
            for line in text.splitlines(keepends=True):
                if artifact.match(line.strip()):
                    dropped += 1
                    continue
                kept.append(line)
            if not dropped:
                continue
            after = "".join(kept)
            # only if it still reads as a section
            from .model import parse_section
            try:
                if parse_section(after, sec.path).id != sec.id:
                    continue
            except Exception:
                continue
            sec.path.write_text(after, encoding="utf-8")
            h.record(sec.id, sec.path, text, after, actor="auto",
                     action="cleared", note="a fragment left by an earlier write")
            cleared += dropped

        return f"{cleared} stray line(s) removed" if cleared else ""

    def _sweep(self, emit) -> str:
        from .sweep import Sweep
        from .decisions import Decisions
        from .knowledge import Knowledge
        p = self._project()
        sw = Sweep(p, self.root, Decisions.load(self.root), Knowledge.load(self.root))
        proposals = sw.run(None, log=None)
        if not proposals:
            return ""
        written = 0
        for pr in list(proposals):
            if self._accept_proposal(pr):
                written += 1
        return f"{written} section(s) written" if written else ""

    def _tidy(self, emit) -> str:
        from .tidy import Tidy
        from .history import History
        from .knowledge import Knowledge
        p = self._project()
        edits = Tidy(p, self.root).run(None, log=None)
        if not edits:
            return ""
        out = Tidy.apply(self.root, self._project(), History(self.root),
                         Knowledge.load(self.root))
        for f in out.get("failed", []):
            self.for_you.append({"what": "a writing fix could not be written",
                                 "why": f, "do": "open the section and look"})
        n = len(out.get("written", []))
        return f"{n} section(s) rewritten" if n else ""

    def _drift(self, emit) -> str:
        """Apply each difference on its own, and keep only the ones that help.

        Reverting the whole step because one change was bad throws away every
        good change beside it. Each is measured by itself: the one that made the
        rules worse goes back, the rest stay.
        """
        from .decisions import Decisions
        rep = self._drift_report(self._project())
        if rep is None:
            return ""
        decisions = Decisions.load(self.root)
        applied = rejected = 0

        for change in rep.changes:
            c = self._as_dict(change)
            if c.get("change") == "image" or not c.get("applicable"):
                continue
            if decisions.verdict_for(c):
                continue
            before = self._errors()
            snap = self._snapshot()
            if not self._apply_change(c, decisions):
                continue
            if self._errors() > before:
                self._restore(snap)
                try:
                    decisions.record(c, "declined",
                                     "applying this added a rule finding")
                except Exception:
                    pass
                rejected += 1
            else:
                applied += 1

        bits = []
        if applied:
            bits.append(f"{applied} difference(s) applied")
        if rejected:
            bits.append(f"{rejected} refused for making the rules worse")
        return ", ".join(bits)

    def _images(self, emit) -> str:
        from .sweep import Sweep
        from .decisions import Decisions
        from .knowledge import Knowledge
        p = self._project()
        sw = Sweep(p, self.root, Decisions.load(self.root), Knowledge.load(self.root))
        sw.run(None, log=None, write_text=False)
        used = 0
        for pr in sw.proposals:
            if pr.kind == "image" and self._accept_proposal(pr):
                used += 1
        return f"{used} picture(s) updated" if used else ""

    # -- the plumbing ----------------------------------------------------
    def _project(self):
        from .project import Project
        return Project.load(self.root)

    def _errors(self) -> int:
        from .lint import lint, summarise
        try:
            return summarise(lint(self._project()))["error"]
        except Exception:
            return 999

    def _forget_decisions_since(self, snapshot: dict) -> None:
        """Drop approvals for changes that are not actually in the document."""
        from .decisions import Decisions
        rep = self._drift_report(self._project())
        if rep is None:
            return
        decisions = Decisions.load(self.root)
        changed = False
        for change in rep.changes:
            c = self._as_dict(change)
            d = decisions.verdict_for(c)
            if d and d.verdict == "approved":
                # still being reported as a difference, so it is not applied
                decisions.items.pop(d.id, None)
                changed = True
        if changed:
            decisions.save()

    def _snapshot(self) -> dict:
        """Every section file as it stands, keyed by path."""
        out = {}
        for node in self._project().nodes:
            if node.section is None or not node.section.path:
                continue
            try:
                out[node.section.path] = node.section.path.read_text(encoding="utf-8")
            except OSError:
                pass
        return out

    def _restore(self, snapshot: dict) -> int:
        """Put back exactly what was there, and say so in the history."""
        if not snapshot:
            return 0
        from .history import History
        h = History(self.root)
        # by path, so the record names the section rather than the file
        by_path = {n.section.path: n.section.id
                   for n in self._project().nodes if n.section}
        undone = 0
        for path, text in snapshot.items():
            try:
                if not path.exists() or path.read_text(encoding="utf-8") == text:
                    continue
                current = path.read_text(encoding="utf-8")
                path.write_text(text, encoding="utf-8")
                undone += 1
                h.record(by_path.get(path, path.stem), path, current, text, actor="auto",
                         action="put back",
                         note="this step made the rule findings worse")
            except OSError:
                pass
        return undone

    def _drift_report(self, project):
        from .drift import analyse
        from .capture import latest_capture
        run = latest_capture(self.root / "capture")
        if not run:
            return None
        try:
            return analyse(project, run)
        except Exception:
            return None

    # The same shape the console builds, so a decision recorded here is
    # recognised there and the other way round. `applicable` is not on the
    # change itself: it is a judgement about what can be carried out, and it
    # lived only in the console, so this loop saw None and applied nothing.
    APPLICABLE = ("renamed", "added", "removed", "image")

    def _as_dict(self, change) -> dict:
        if isinstance(change, dict):
            return change
        line = change.line() if callable(getattr(change, "line", None)) \
            else getattr(change, "line", "")
        return {
            "section": change.section, "screen": change.screen,
            "kind": change.kind, "change": change.change,
            "label": change.label, "became": change.became,
            "confidence": change.confidence,
            "note": getattr(change, "note", ""), "line": line,
            "applicable": change.change in self.APPLICABLE,
        }

    def _apply_change(self, c: dict, decisions) -> bool:
        """Make one drift change, and record both the edit and the decision."""
        from .console import actions
        from .history import History
        from .capture import latest_capture
        p = self._project()
        sec = p.sections.get(c.get("section", ""))
        if sec is None:
            return False
        before = sec.path.read_text(encoding="utf-8")
        try:
            actions.apply_change(p, c, latest_capture(self.root / "capture"))
        except Exception:
            return False
        after = sec.path.read_text(encoding="utf-8")
        if after == before:
            return False
        History(self.root).record(sec.id, sec.path, before, after,
                                  actor="auto", action=c.get("change", "apply"),
                                  note=c.get("line", ""))
        try:
            decisions.record(c, "approved", "")
        except Exception:
            pass
        return True

    def _accept_proposal(self, pr) -> bool:
        """Write one sweep proposal: a description filled in, or a picture used."""
        import shutil
        from datetime import date
        from .history import History
        from .model import parse_section
        from .sweep import Sweep
        from .assets import refresh_derived

        pid = pr.id if hasattr(pr, "id") else pr.get("id")
        kind = pr.kind if hasattr(pr, "kind") else pr.get("kind")
        p = self._project()
        h = History(self.root)

        if kind == "image":
            name = pr.asset if hasattr(pr, "asset") else pr.get("asset")
            run = pr.run if hasattr(pr, "run") else pr.get("run")
            src = self.root / "capture" / run / "screenshots" / name
            if not src.exists():
                return False
            shutil.copyfile(src, p.asset_path(name))
            p.assets.registry.setdefault(name, {}).update(
                {"source": str(src), "replaced_on": date.today().isoformat()})
            p.assets.save()
            h.record_asset(name, f"{run}/{name}", note="used by the autonomous run")
            try:
                refresh_derived(p.assets, name,
                                capture_dir=self.root / "capture" / run)
            except Exception:
                pass
            Sweep.drop(self.root, pid)
            return True

        sid = pr.section if hasattr(pr, "section") else pr.get("section")
        after = pr.after if hasattr(pr, "after") else pr.get("after")
        sec = p.sections.get(sid)
        if sec is None or not after:
            return False
        try:
            parsed = parse_section(after, sec.path)
            if parsed.id != sec.id:
                return False
        except Exception:
            return False
        before = sec.path.read_text(encoding="utf-8")
        sec.path.write_text(after, encoding="utf-8")
        h.record(sec.id, sec.path, before, after, actor="auto",
                 action="fill gaps", note="written by the autonomous run")
        Sweep.drop(self.root, pid)
        return True

    # ------------------------------------------------------------------
    def _collect_what_is_left(self, emit) -> None:
        """What a person still owns, with why it is theirs and what to do."""
        from .lint import lint, remedy
        from .survey import Survey

        for f in lint(self._project()):
            if f.level != "error":
                continue
            r = remedy(f.rule)
            self.for_you.append({
                "what": f"{f.section}: {f.message}".strip(": "),
                "why": r["why"],
                "do": r["label"] if r["action"] != "none" else
                      "this one needs you to decide what is right"})

        sv = Survey.run(self._project(), self.root)
        for g in sv.gaps:
            if g.kind == "redirects":
                self.for_you.append({
                    "what": g.what, "why": "a screen that is not a distinct screen",
                    "do": "remove it from content/screens.yaml, or give it steps "
                          "that reach something of its own"})
            elif g.kind == "undocumented":
                self.for_you.append({
                    "what": g.what, "why": "nothing describes it",
                    "do": "add a section for it, or leave it out on purpose"})

    def report(self, started_with: int, emit) -> dict:
        left = self._errors()
        out = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "rounds": self.rounds_run,
            "errors_before": started_with,
            "errors_after": left,
            "steps": [s.to_dict() for s in self.steps],
            "for_you": self.for_you,
        }
        path = self.root / "review" / "auto.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2, ensure_ascii=False),
                        encoding="utf-8")

        emit("")
        did = [s for s in self.steps if s.did and not s.reverted]
        if did:
            emit(f"{len(did)} thing(s) done over {self.rounds_run} round(s)")
            for s in did:
                emit(f"  {s.name}: {s.did}")
        else:
            emit("nothing needed doing: the document already matches the live "
                 "system and breaks no rules")
        undone = [s for s in self.steps if s.reverted]
        for s in undone:
            emit(f"  {s.name}: {s.note}")
        emit("")
        if started_with or left:
            emit(f"rule findings: {started_with} to {left}")
        if self.for_you:
            emit(f"{len(self.for_you)} thing(s) still yours to decide")
        return out
