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
        import contextlib
        import sys
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


REVIEWS = "review/section-review.json"

# A review that says nothing is wrong says so in many ways. These are the words
# it uses when it has actually found something, and requiring one of them keeps
# a rewrite from being triggered by "no issues found".
WORTH = ("contradict", "omits", "omitted", "missing", "no longer", "incorrect",
         "wrong", "outdated", "does not match", "not present", "renamed",
         "should be", "inaccurate", "stale")


def _worth_fixing(report: str) -> bool:
    body = (report or "").strip().lower()
    if not body or len(body) < 25:
        return False
    if any(p in body[:160] for p in
           ("no issues", "nothing to report", "no problems", "accurate and",
            "correctly describes", "no discrepanc")):
        return False
    return any(w in body for w in WORTH)


def _first_point(report: str) -> str:
    for line in (report or "").splitlines():
        s = line.strip(" -*\t")
        if len(s) > 20:
            return s[:150]
    return (report or "").strip()[:150]


def _load_reviews(root) -> dict:
    import json
    try:
        return json.loads((Path(root) / REVIEWS).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_reviews(root, data: dict):
    from .atomic import write_json
    write_json(Path(root) / REVIEWS, data)


MATCHES = "review/picture-match.json"


def _picture_digest(root, name: str) -> str:
    """A short fingerprint of the picture a verdict was about."""
    import hashlib
    for folder in ("content/assets", "content/assets/icons"):
        path = Path(root) / folder / name
        if path.exists():
            return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return ""


def _verdict_still_about(root, name: str, verdict: dict) -> bool:
    """Is this verdict about the picture that is there now?

    A verdict with no fingerprint is from before they were recorded and is
    trusted, because throwing away every existing judgement to introduce a
    field would cost more than it is worth. One that names a different picture
    is stale: the screen has been photographed since, and nobody has looked at
    what came back.
    """
    was = (verdict or {}).get("of")
    if not was:
        return True
    return was == _picture_digest(root, name)


def _load_matches(root) -> dict:
    import json
    try:
        return json.loads((Path(root) / MATCHES).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_matches(root, data: dict):
    from .atomic import write_json
    write_json(Path(root) / MATCHES, data)


def _figures_of(text: str) -> list[str]:
    """Every figure a section shows, in order."""
    import re as _re
    return _re.findall(r"^!\[[^\]]*\]\(([^)\s]+)", text, flags=_re.M)


def _keeps_every_figure(before: str, after: str) -> bool:
    """Did a rewrite hold on to every picture the section had?

    A model asked to reconcile a section against the crawl is being asked about
    labels and sentences. It is not being asked whether the section should have
    pictures, and it must not answer that question by leaving them out.

    It did. One rewrite took a section from thirteen figures to two, and because
    a missing figure only produces an INFO finding, the measurement that guards
    every other step waved it through: errors before, errors after, no change,
    keep it. Fourteen pictures left the document that way.
    """
    return set(_figures_of(before)) <= set(_figures_of(after))


def _drop_figure(text: str, filename: str) -> str:
    """Remove one figure line, and the blank line it leaves behind."""
    out, skipped = [], False
    for line in text.splitlines(keepends=True):
        if not skipped and line.lstrip().startswith("![") and filename in line:
            skipped = True
            continue
        out.append(line)
    if not skipped:
        return text
    # collapse the double blank a removed line leaves
    joined = "".join(out)
    while "\n\n\n" in joined:
        joined = joined.replace("\n\n\n", "\n\n")
    return joined


def _once(items: list) -> list:
    """The same thing, handed back once.

    Every round re-lints and re-decides, so a finding a person owns is added
    again on each pass. Four findings over two rounds were reported as nine
    things to decide, which reads as the list growing while the loop claims to
    be shortening it.
    """
    seen, out = set(), []
    for it in items:
        key = str(it.get("what", ""))[:160]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _is_a_persons_signature(finding) -> bool:
    """A finding only a person can close by being a person.

    Accepting a section is the one thing in this system that means something
    precisely because a machine cannot do it. Sending these to the decider
    costs a model call each to be told what the rule already says, and prints
    "left for a person" once per section per round, which is how a real signal
    turns back into noise. They belong in front of a person, unasked about.
    """
    from .lint import remedy
    return (remedy(finding.rule) or {}).get("action") == "verify"


def _worth_deciding(finding) -> bool:
    """An INFO the system could actually act on, rather than merely mention."""
    if finding.level != "info":
        return False
    from .lint import remedy
    return (remedy(finding.rule) or {}).get("action") not in (None, "", "none", "open")


@dataclass
class Auto:
    root: Path
    steps: list = field(default_factory=list)
    for_you: list = field(default_factory=list)
    rounds_run: int = 0

    # ------------------------------------------------------------------
    def run(self, rounds: int = 3, crawl: bool = True, log=None,
            calls: int | None = None) -> dict:
        emit = log or (lambda *_: None)
        # A ceiling on how often this run may ask a model, and a tally of what
        # it did ask. Twenty-one call sites, one per section per round on a
        # large document plus one per picture, and until now the only place
        # that number appeared was somebody's invoice.
        from .budget import Budget
        from .console.assist import metering
        self.budget = metering(Budget.for_run(calls))
        start = self._errors()
        emit(f"the document breaks {start} rule(s) today"
             if start else "the document breaks no rules today")
        emit("looking for anything else that needs doing")

        for r in range(1, rounds + 1):
            self.rounds_run = r
            emit("")
            emit(f"round {r}")

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
            self._step("replace pictures nobody has checked",
                       self._replace_unchecked_pictures, emit)
            self._step("look at the pictures nobody has checked",
                       self._look_at_pictures, emit)
            self._step("read each section against what the crawl saw",
                       self._review_against_evidence, emit)
            self._step("check each picture is of what its section describes",
                       self._check_pictures_match, emit)
            self._step("decide what nothing else could settle",
                       self._settle_the_rest, emit)
            self._step("rewrite what the rules object to", self._polish, emit)

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
        """Do one thing, then check both that it did not break a rule and that
        it did not do something no rule measures.

        The count alone was the whole basis for leaving a step's work in place,
        and three separate steps damaged a document without moving it: a
        rewrite that dropped eleven figures, and two pairs of steps that undid
        each other forever at a constant count. So the shape of the document is
        taken as well, and a step that changes it in a way no step is allowed
        to is put back regardless of what the count says.
        """
        from .invariants import Shape, broken
        before = self._errors()
        step = Step(name=name, errors_before=before)
        try:
            # Snapshot the content itself rather than trusting the history to
            # hand it back: `entries()` keeps the metadata and drops the text,
            # so a revert built on it silently restores nothing.
            snapshot = self._snapshot()
            shape = Shape.of(self._project())
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

        damage = broken(shape, Shape.of(self._project()))
        if damage or step.errors_after > step.errors_before:
            # A pass that introduces findings is a pass that made the document
            # worse, whatever it believed it was doing. So is one that took
            # something out that no rule counts.
            undone = self._restore(snapshot)
            # A decision recorded by a step that was then undone leaves the
            # document without the change and the record saying it was approved,
            # so every later run skips it and it can never be reconsidered.
            self._forget_decisions_since(snapshot)
            step.reverted = True
            if damage:
                step.note = "put back: " + damage[0]
                emit(f"  {name}: {step.did}")
                emit(f"    reverted {undone} change(s). No rule would have "
                     f"caught this:")
                for line in damage[:4]:
                    emit(f"      {line}")
                self.for_you.append({
                    "what": f"a step was put back: {damage[0]}",
                    "why": f"{name} changed the document in a way nothing "
                           f"measures, so it was undone rather than trusted.",
                    "do": "Nothing, unless it keeps happening. Then this is a bug."})
            else:
                step.note = (f"put back: it added "
                             f"{step.errors_after - step.errors_before} finding(s)")
                emit(f"  {name}: {step.did}")
                emit(f"    reverted {undone} change(s), because the rules got "
                     f"worse ({step.errors_before} to {step.errors_after})")
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
        from .notes import FIXED, STUCK, Notes, resolve
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
            import argparse

            from .cli import cmd_capture
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
        from .decisions import Decisions
        from .knowledge import Knowledge
        from .sweep import Sweep
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
        from .history import History
        from .knowledge import Knowledge
        from .tidy import Tidy
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
        self._describe_blocked = ""       # why descriptions could not be written

        for change in rep.changes:
            c = self._as_dict(change)
            if c.get("change") == "image" or not c.get("applicable"):
                continue
            verdict = decisions.verdict_for(c)
            # Only a decline stops a change. An approval is permission to make
            # it, not a record that it was made: a change that is still in the
            # drift report after being approved never landed, and skipping it
            # because somebody once said yes is how it stays undone forever.
            # One such approval here dated from a step that was applied and then
            # undone, and no run since had looked at it.
            if (verdict is not None and verdict.binding
                    and verdict.verdict == "declined"):
                continue
            before = self._errors()
            snap = self._snapshot()
            if not self._apply_change(c, decisions):
                continue
            if self._errors() > before:
                # A control the product gained arrives with no description, and
                # an unwritten description is itself a finding. Measured alone,
                # a difference that is exactly right therefore looks worse than
                # not applying it, so the one change most worth making was the
                # one change that could never survive. Describe what was just
                # added, then judge the pair.
                described = self._describe(c.get("section"), emit)
                if described and self._errors() <= before:
                    applied += 1
                    continue
                self._restore(snap)
                try:
                    decisions.record(c, "declined",
                                     "applying this added a rule finding",
                                     by="auto")
                except Exception:
                    pass
                rejected += 1
            else:
                applied += 1

        bits = []
        if applied:
            bits.append(f"{applied} difference(s) applied")
        if rejected:
            # "made the rules worse" is true and unhelpful on its own. The
            # usual cause is that the change adds a control and there is no way
            # to reach a model to describe it, which is a thing a person can
            # act on rather than a verdict about their document.
            why = self._describe_blocked
            bits.append(f"{rejected} refused because what they add "
                        f"cannot be described" + (f" ({why})" if why else ""))
        return ", ".join(bits)

    def _assist(self, section_id, task: str, emit, note: str) -> bool:
        """Run one writing task on one section and keep the result.

        Every writing action the console offers a person is also something the
        loop can do unattended. The difference is only that the loop measures
        the rules afterwards and puts the change back if they got worse, which
        is a stricter test than a person clicking Accept on a diff.
        """
        if not section_id:
            return False
        from .console import assist
        from .decisions import Decisions
        from .history import History
        from .knowledge import Knowledge
        from .lint import lint
        from .model import parse_section

        ok, why = assist.available()
        if not ok:
            self._describe_blocked = why
            return False
        try:
            p = self._project()
            sec = p.sections.get(section_id)
            if sec is None:
                return False
            inv = self._inventory_for(sec)
            findings = [{"rule": f.rule, "level": f.level, "message": f.message,
                         "detail": f.detail}
                        for f in lint(p) if section_id in (f.section or "")]
            notes = Knowledge.load(self.root).bundle_for(
                section_id, Decisions.load(self.root))
            prompt = assist.build_prompt(task, p, sec, inv, [], findings, notes)
            result = assist.run_model(prompt, log=None)
            if not result.ok:
                self._describe_blocked = (result.error or "")[:120]
                return False
            proposed = assist.clean_output(result.output)
            if not (result.output or "").strip():
                self._describe_blocked = "the model returned nothing"
                return False
            parsed = parse_section(proposed, sec.path)
            if parsed.id != sec.id:
                self._describe_blocked = "the reply changed the section id"
                return False
            before = sec.path.read_text(encoding="utf-8")
            if proposed.strip() == before.strip():
                return False
            if not _keeps_every_figure(before, proposed):
                emit(f"      {task} on {section_id} would drop a figure, rejected")
                return False
            sec.path.write_text(proposed, encoding="utf-8")
            History(self.root).record(sec.id, sec.path, before, proposed,
                                      actor="auto", action=task, note=note)
            emit(f"      {note}: {section_id}")
            return True
        except Exception as e:
            self._describe_blocked = str(e)[:120]
            emit(f"      could not rewrite {section_id}: {e}")
            return False

    def _polish(self, emit) -> str:
        """Rewrite the sections whose findings say a rewrite is the fix.

        Every rule finding carries the action that clears it, and for the style
        rules that action is "rewrite to house style". The loop never ran it, so
        "fix what can be fixed" left findings standing whose own remedy the
        system was holding in its hand. Measured and reverted like anything
        else, which is what makes it safe to do without being asked.
        """
        from .lint import lint, remedy
        wants: dict[str, str] = {}
        for f in lint(self._project()):
            act = remedy(f.rule).get("action") or ""
            if not act.startswith("assist:") or not f.section:
                continue
            sid = f.section.split(" ", 1)[-1].strip()
            if sid in self._project().sections:
                wants.setdefault(sid, act.split(":", 1)[1])
        if not wants:
            return ""
        done = 0
        for sid, task in wants.items():
            if self._assist(sid, task, emit, "rewrote to house style"):
                done += 1
        return f"{done} section(s) rewritten" if done else ""

    def _describe(self, section_id, emit) -> bool:
        """Write the descriptions one section is now missing, from the evidence.

        Run the moment a difference is applied rather than as a later pass,
        because a later pass is too late: the change has been judged and put
        back by then.
        """
        return self._assist(section_id, "fill_todos", emit,
                            "described what was added to")

    def _inventory_for(self, sec) -> dict:
        """The newest capture of each screen this section is bound to."""
        try:
            from .console.server import merged_inventory
            merged, _ = merged_inventory(self.root / "capture")
            return {sid: merged["screens"][sid] for sid in sec.screens
                    if sid in merged.get("screens", {})}
        except Exception:
            return {}

    def _review_against_evidence(self, emit) -> str:
        """Read each section against what the crawl actually saw, and correct it.

        Everything else in this loop compares one narrow thing: a label to a
        label, a picture to a section, a rule to a sentence. None of it reads
        what a section *says* and asks whether the screen bears it out. A
        section can name every column correctly, show the right picture, break
        no rule, and still describe a control that is no longer there or leave
        out the one thing the screen is for.

        So each section is reviewed against its own evidence, and where the
        review finds something substantive the section is reconciled with the
        crawl and the result measured. A section already reviewed against the
        capture it is being compared to is skipped, because nothing has changed
        since and the second answer costs the same as the first.
        """
        from .console import assist
        from .history import History
        from .lint import lint
        from .model import parse_section

        proj = self._project()
        ok, why = assist.available()
        if not ok:
            self._describe_blocked = why
            return ""

        run = ""
        try:
            from .capture import latest_capture
            newest = latest_capture(self.root / "capture")
            run = newest.name if newest else ""
        except Exception:
            pass

        seen = _load_reviews(self.root)
        corrected, looked = 0, 0
        for node in proj.nodes:
            sec = node.section
            if sec is None or not sec.screens:
                continue
            if seen.get(sec.id, {}).get("run") == run:
                continue                       # already read against this capture
            inv = self._inventory_for(sec)
            if not inv:
                continue                       # nothing to hold it against

            findings = [{"rule": f.rule, "level": f.level, "message": f.message,
                         "detail": f.detail}
                        for f in lint(proj) if sec.id in (f.section or "")]
            prompt = assist.build_prompt("review", proj, sec, inv, [], findings, "")
            res = assist.run_model(prompt, log=None)
            if not res.ok:
                self._describe_blocked = (res.error or "")[:120]
                break
            looked += 1
            report = (res.output or "").strip()
            seen[sec.id] = {"run": run, "report": report[:1200]}

            if not _worth_fixing(report):
                continue

            emit(f"      {node.number} {sec.title}: {_first_point(report)}")
            errors_before = self._errors()
            snapshot = self._snapshot()
            before = sec.path.read_text(encoding="utf-8")
            fix = assist.build_prompt("reconcile", proj, sec, inv, [], findings,
                                      "A review of this section found:\n" + report)
            out = assist.run_model(fix, log=None)
            if not out.ok:
                continue
            proposed = assist.clean_output(out.output)
            try:
                parsed = parse_section(proposed, sec.path)
            except Exception:
                continue
            if parsed.id != sec.id or proposed.strip() == before.strip():
                continue
            if not _keeps_every_figure(before, proposed):
                lost = sorted(set(_figures_of(before)) - set(_figures_of(proposed)))
                emit(f"        rejected: the rewrite would drop "
                     f"{len(lost)} figure(s)")
                continue
            sec.path.write_text(proposed, encoding="utf-8")
            if self._errors() > errors_before:
                self._restore(snapshot)
                emit("        put back: the correction broke a rule")
                proj = self._project()
                continue
            History(self.root).record(
                sec.id, sec.path, before, proposed, actor="auto", action="review",
                note=f"corrected against the crawl: {_first_point(report)[:110]}")
            corrected += 1
            proj = self._project()

        _save_reviews(self.root, seen)
        if corrected:
            return f"{corrected} section(s) corrected against the crawl"
        return f"{looked} section(s) read against the crawl" if looked else ""

    def _check_pictures_match(self, emit) -> str:
        """Is each picture actually of the thing its section describes?

        Every other rule about a picture asks where it came from or what is
        written in it. None of them asks the question a reader answers in a
        second: is this a picture of what I am reading about? A chapter called
        Dashboard Overview illustrated by the demand partners list passes the
        lot.

        This reports rather than changes anything. Which picture a section
        should show is a decision about the document, and the honest output is
        to say clearly that these two do not go together.
        """
        from .console import assist

        proj = self._project()
        already = self._matched if hasattr(self, "_matched") else set()
        verdicts = _load_matches(self.root)
        checked = 0
        for node in proj.nodes:
            sec = node.section
            if sec is None:
                continue
            for b in sec.blocks:
                if b.kind != "screenshot":
                    continue
                name = b.attrs.get("file", "")
                if not name or not proj.assets.exists(name):
                    continue
                key = (sec.id, name)
                if key in already:
                    continue
                already.add(key)
                text = " ".join(x.text for x in sec.blocks if x.kind == "paragraph")
                res = assist.matches_section(
                    proj.asset_path(name), node.number, sec.title, text,
                    caption=b.attrs.get("caption", ""))
                if not res.ok:
                    self._describe_blocked = (res.error or "")[:120]
                    self._matched = already
                    return ""
                fits, what = assist.read_match(res.output)
                checked += 1
                # Written down rather than only reported. A verdict that lives
                # in a log is a thing somebody has to read; a verdict in the
                # store is a finding, and a finding is something the loop can
                # settle on its own.
                verdicts[f"{sec.id}|{name}"] = {
                    "fits": fits, "what": what,
                    "when": datetime.now().strftime("%Y-%m-%d"),
                    # Which picture was judged. A verdict is about an image,
                    # not about a filename, and the filename outlives the
                    # image every time the screen is photographed again. Two
                    # rules now read these, so a wrong one that never expired
                    # would quietly silence a rule forever, and nothing would
                    # ever look at it again.
                    "of": _picture_digest(self.root, name),
                }
                if not fits:
                    emit(f"      {node.number} {sec.title}: the picture shows {what}")
        _save_matches(self.root, verdicts)
        self._matched = already
        return f"{checked} picture(s) checked against their section" if checked else ""

    def _stop_capturing(self, name: str, why: str, emit) -> bool:
        """Take one named crop out of the screen registry.

        A picture the crawl makes that nothing shows is work being done for
        nobody, and it reports itself as unreferenced after every single run.
        There was no move for it: the decider could drop a figure from a
        section or swap one for another, and this picture is in no section, so
        every round ended in "left for a person" and the person was handed a
        crawl setting they had no way to recognise as one.

        Edited as text, one entry at a time. Loading this file and dumping it
        back is four lines and loses every comment in it, including the block
        at the top explaining that credentials come from the environment. A
        registry nobody can read any more is a worse outcome than an unused
        crop, and the first version of this did exactly that.

        Only named elements. A screen's main photograph is what the screen is
        for, and a screen that photographs nothing should be deleted by a
        person, not quietly emptied by this.
        """
        import yaml

        from .history import History
        path = self.root / "content" / "screens.yaml"
        try:
            before = path.read_text(encoding="utf-8")
            data = yaml.safe_load(before) or {}
        except Exception as e:
            emit(f"      could not read the screen registry: {e}")
            return False

        owner = ""
        for screen in data.get("screens", []) or []:
            if any((e or {}).get("name") == name
                   for e in (screen.get("elements") or [])):
                owner = screen.get("id", "")
                break
        if not owner:
            emit(f"      {name} is not a named crop, so it is not the crawl's "
                 f"to stop")
            return False

        lines = before.splitlines(keepends=True)
        start = next((i for i, ln in enumerate(lines) if name in ln), None)
        if start is None:
            return False
        # A list item is its own dash line plus every deeper line under it.
        while start > 0 and not lines[start].lstrip().startswith("-"):
            start -= 1
        indent = len(lines[start]) - len(lines[start].lstrip())
        end = start + 1
        while end < len(lines):
            stripped = lines[end].strip()
            if stripped and (len(lines[end]) - len(lines[end].lstrip())) <= indent:
                break
            end += 1
        after = "".join(lines[:start] + lines[end:])

        try:
            checked = yaml.safe_load(after) or {}
            still = [e.get("name") for s in (checked.get("screens") or [])
                     for e in (s.get("elements") or [])]
        except Exception as e:
            emit(f"      not touching the registry: the edit would not parse ({e})")
            return False
        if name in still or len(checked.get("screens") or []) != len(
                data.get("screens") or []):
            emit("      not touching the registry: the edit removed more than "
                 "the one entry")
            return False

        from .atomic import write_text
        write_text(path, after)
        History(self.root).record(
            owner, path, before, after, actor="auto", action="decide",
            note=f"{owner} no longer photographs {name}: {why[:120]}")
        emit(f"      {owner} no longer photographs {name}")
        emit(f"        because {why[:100]}")
        return True

    def _picture_fits(self, section_id: str, name: str) -> bool:
        """Has this picture already been ruled not to be of this section?"""
        import json
        try:
            verdicts = json.loads(
                (self.root / MATCHES).read_text(encoding="utf-8"))
        except Exception:
            return True
        v = verdicts.get(f"{section_id}|{name}")
        if v is None or not _verdict_still_about(self.root, name, v):
            return True
        return bool(v.get("fits", True))

    def _picture_choices(self, proj) -> list[dict]:
        """Pictures already photographed, and what each screen is called.

        Offered so a wrong figure can be swapped for a right one rather than
        only removed. A section with the right picture is better documentation
        than a section with none, and the alternative was already on disk.
        """
        try:
            from .capture import load_screens
            _, screens = load_screens(self.root / "content" / "screens.yaml")
        except Exception:
            return []
        # Which pictures are already in the document, and where. Repointing to
        # one that another section already shows trades a wrong picture for a
        # duplicate, which is a worse finding than the one being fixed.
        taken: dict[str, str] = {}
        for sec in proj.sections.values():
            for shot in sec.screenshots():
                if shot:
                    taken.setdefault(shot, sec.id)
        out = []
        for s in screens:
            shot = getattr(s, "shot", "")
            if shot and proj.assets.exists(shot):
                owner = taken.get(shot)
                out.append({
                    "file": shot,
                    "shows": (getattr(s, "title", "") or s.id) + (
                        f"  [already shown in {owner}, do not repoint to this]"
                        if owner else "  [not used by any section]"),
                })
        return out[:40]

    def _settle_the_rest(self, emit) -> str:
        """Decide the findings no mechanical step could clear.

        Everything before this either applies a difference, adopts a picture or
        rewrites a sentence, and each of those is a change with an obviously
        right answer. What is left is the residue: two sections showing one
        picture, a photograph carrying a name that cannot be re-photographed.
        Those need an editor's judgement, which is why they were handed back.

        Handing them back is right when there is nobody to hand them to and
        wrong when there is. There is: the same model doing the writing can read
        both sections and say which one the picture is actually about. It gets a
        closed menu of actions rather than free rein, its reasoning is recorded
        beside the change, and the whole step is measured and put back if the
        rules got worse. A person who disagrees restores it from History.
        """
        from .console import assist
        from .history import History
        from .lint import lint

        proj = self._project()
        # Not just errors and warnings. A finding's level says how badly it
        # would hurt to publish, not whether anything can be done about it, and
        # reading it as the second thing made every INFO permanently invisible
        # to the one step whose whole job is settling what nothing else could.
        # They accumulated in front of a person who could only look at them.
        left = [f for f in lint(proj)
                if (f.level in ("error", "warning") or _worth_deciding(f))
                and not _is_a_persons_signature(f)]
        if not left:
            return ""

        ok, why = assist.available()
        if not ok:
            self._describe_blocked = why
            return ""

        def figures_of(sec):
            return [b.attrs.get("file", "") for b in sec.blocks
                    if b.kind == "screenshot" and b.attrs.get("file")]

        done = 0
        for f in left:
            # every section this finding touches, by id, from wherever it names them
            blob = f"{f.section} {f.detail or ''} {f.message}"
            involved = [s for sid, s in proj.sections.items() if sid in blob]
            if not involved:
                continue
            payload = [{
                "id": s.id, "title": s.title, "figures": figures_of(s),
                "body": " ".join(b.text for b in s.blocks if b.kind == "paragraph"),
            } for s in involved]

            res = assist.decide(
                {"rule": f.rule, "message": f.message, "detail": f.detail or ""},
                payload, edition=proj.profile.name,
                candidates=self._picture_choices(proj))
            if not res.ok:
                self._describe_blocked = (res.error or "")[:120]
                emit(f"      could not decide {f.rule}: {res.error}")
                break

            d = assist.read_decision(res.output)
            if d["action"] == "none":
                emit(f"      {f.rule}: left for a person. {d['why'][:90]}")
                self.for_you.append({
                    "what": f.message, "why": d["why"] or (f.detail or ""),
                    "do": "Open the section and decide."})
                continue

            if d["action"] == "stop_capturing":
                took = self._stop_capturing(d["file"], d["why"], emit)
                if took:
                    done += 1
                    proj = self._project()
                continue

            if d["action"] == "accept":
                name = d["file"]
                if proj.assets.exists(name):
                    entry = proj.assets.registry.setdefault(name, {})
                    entry["checked_by"] = {
                        "who": f"the model ({assist.DEFAULT_MODEL})",
                        "when": datetime.now().strftime("%Y-%m-%d"),
                        "note": d["why"][:200]}
                    proj.assets.save()
                    done += 1
                    emit(f"      kept {name}: {d['why'][:80]}")
                continue

            sec = proj.sections.get(d["section"])
            if sec is None or not d["file"]:
                continue
            # Each decision is judged by itself. Measuring the step as a whole
            # meant one bad call took the good ones down with it: a repoint that
            # created a duplicate reverted the whole step, including a correct
            # removal made beside it.
            errors_before = self._errors()
            snapshot = self._snapshot()
            before = sec.path.read_text(encoding="utf-8")
            if d["action"] == "repoint":
                if not d["to"] or not proj.assets.exists(d["to"]):
                    emit(f"      cannot repoint to {d['to']!r}: no such picture")
                    continue
                # Somebody has already looked at this picture and said it is of
                # a different part of the product. Pointing the section at it
                # would be undone by the step that looks, which would hand it
                # back here, which would point at it again. Two steps taking
                # turns is not a loop making progress, and the rule count never
                # moves, so nothing catches it.
                if not self._picture_fits(d["section"], d["to"]):
                    emit(f"      will not point {d['section']} at {d['to']}: "
                         f"it has been looked at and is of something else")
                    continue
                after = before.replace(d["file"], d["to"])
                if after != before:
                    sec.path.write_text(after, encoding="utf-8")
                    History(self.root).record(
                        sec.id, sec.path, before, after, actor="auto",
                        action="decide",
                        note=f"{sec.id} now shows {d['to']} instead of "
                             f"{d['file']}: {d['why'][:110]}")
                    if self._errors() > errors_before:
                        self._restore(snapshot)
                        emit(f"      put back: pointing {sec.id} at {d['to']} "
                             f"broke a rule")
                        proj = self._project()
                        continue
                    emit(f"      {sec.id} now shows {d['to']}")
                    emit(f"        because {d['why'][:100]}")
                    done += 1
                    proj = self._project()
                continue
            after = _drop_figure(before, d["file"])
            if after == before:
                continue
            sec.path.write_text(after, encoding="utf-8")
            if self._errors() > errors_before:
                self._restore(snapshot)
                emit(f"      put back: removing {d['file']} broke a rule")
                proj = self._project()
                continue
            # Retired on purpose, and recorded as such. Otherwise the next
            # lint run reports the picture as unreferenced and the section as
            # having a screen with no figure, and the loop hands back two new
            # findings for every one it settled. Work the system made for
            # itself is not work for a person.
            reg = proj.assets.registry.setdefault(d["file"], {})
            reg["retired"] = {"when": datetime.now().strftime("%Y-%m-%d"),
                              "from": sec.id, "why": d["why"][:200]}
            proj.assets.save()
            History(self.root).record(
                sec.id, sec.path, before, after, actor="auto", action="decide",
                note=f"took {d['file']} out of {sec.id}: {d['why'][:120]}")
            emit(f"      took {d['file']} out of {sec.id}")
            emit(f"        because {d['why'][:100]}")
            done += 1
            proj = self._project()

        return f"{done} decision(s) made" if done else ""

    def _look_at_pictures(self, emit) -> str:
        """Have the model look at every picture nobody has checked.

        The finding says nobody has checked this picture for real customer
        names. That was reported as a thing only a person could settle, and a
        person was then offered eighteen buttons to press one at a time. But
        looking at a picture and reading the names in it is exactly what a model
        that can see is for, and one is already configured for the writing.

        A clean verdict is recorded as the model's, not as proof of masking:
        it can be wrong, and conflating "a model looked and saw nothing" with
        "the masking rules ran on this" would be claiming something untrue about
        a control that exists to protect a customer.

        A name found is worth more than a verdict. It goes back as the exact
        string, so the next thing that happens is a masking rule rather than
        another round of looking.
        """
        from .console import assist
        from .lint import lint

        proj = self._project()
        want = []
        for f in lint(proj):
            if f.rule not in ("ASSET-10", "ASSET-11"):
                continue
            name = f.message.split(":", 1)[-1].strip()
            if proj.assets.exists(name):
                want.append(name)
        if not want:
            return ""

        ok, why = assist.available()
        if not ok:
            self._describe_blocked = why
            emit(f"    cannot look at pictures: {why}")
            return ""

        product = (proj.config.get("product") or {})
        clean, flagged = 0, []
        forbid = assist.forbidden_names(self.root)
        emit(f"    looking at {len(want)} picture(s), "
             f"against {len(forbid)} name(s) that must never appear")
        for name in want:
            res = assist.look(proj.asset_path(name),
                              product=str(product.get("name", "")),
                              vendor=str(product.get("vendor", "")),
                              forbid=forbid)
            if not res.ok:
                self._describe_blocked = (res.error or "")[:120]
                emit(f"      could not look at {name}: {res.error}")
                break
            is_clean, names = assist.read_verdict(res.output)
            if is_clean:
                entry = proj.assets.registry.setdefault(name, {})
                entry["checked_by"] = {
                    "who": f"the model ({assist.DEFAULT_MODEL})",
                    "when": datetime.now().strftime("%Y-%m-%d"),
                    "note": "looked and saw no real customer name",
                }
                proj.assets.save()
                clean += 1
            else:
                flagged.append((name, names))
                emit(f"      {name}: real name(s) visible: {', '.join(names) or 'unclear'}")

        for name, names in flagged:
            self.for_you.append({
                "what": f"{name} shows a real name: {', '.join(names)}",
                "why": "A picture that never went through masking, and the model "
                       "can read a real name in it.",
                "do": "Add that name under Names so it is replaced, then "
                      "photograph the screen again, or take the picture out."})

        bits = []
        if clean:
            bits.append(f"{clean} picture(s) checked and clean")
        if flagged:
            bits.append(f"{len(flagged)} showing a real name")
        return ", ".join(bits)

    def _replace_unchecked_pictures(self, emit) -> str:
        """Swap in a freshly masked photograph wherever one is available.

        A picture that never went through masking is reported by name, and the
        crawl that just ran almost certainly took a masked version of the very
        same screen. Waiting for the sweep to notice a difference was too
        indirect: it compares fingerprints and proposes a swap when a screen has
        visibly moved, which is not the question here. The question is whether
        anybody has checked this picture, and the answer is known.
        """
        from .capture import latest_capture
        from .console import actions
        from .history import History
        from .lint import lint

        run = latest_capture(self.root / "capture")
        if run is None:
            return ""
        wanted = [f.message.split(":", 1)[-1].strip()
                  for f in lint(self._project())
                  if f.rule == "ASSET-10" and ":" in f.message]
        if not wanted:
            return ""
        swapped = 0
        for name in wanted:
            src = run / "screenshots" / name
            if not src.exists():
                continue                       # this screen was not in the run
            p = self._project()
            before = p.asset_path(name).read_bytes() if p.assets.exists(name) else b""
            try:
                actions.apply_image(p, run, name)
            except Exception as e:
                emit(f"      could not replace {name}: {e}")
                continue
            after = p.asset_path(name).read_bytes()
            if after != before:
                History(self.root).record(
                    name, p.asset_path(name), "", "", actor="auto",
                    action="picture", note=f"replaced {name} with a masked capture")
                swapped += 1
                emit(f"      replaced {name} with a masked photograph")
        return f"{swapped} picture(s) replaced" if swapped else ""

    def _images(self, emit) -> str:
        from .decisions import Decisions
        from .knowledge import Knowledge
        from .sweep import Sweep
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
        from .capture import latest_capture
        from .drift import analyse
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
    APPLICABLE = ("renamed", "added", "removed", "image", "unmapped")

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
            "items": list(getattr(change, "items", []) or []),
            "applicable": change.change in self.APPLICABLE,
        }

    def _apply_change(self, c: dict, decisions) -> bool:
        """Make one drift change, and record both the edit and the decision."""
        from .capture import latest_capture
        from .console import actions
        from .history import History
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

        from .assets import refresh_derived
        from .history import History
        from .model import parse_section
        from .sweep import Sweep

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
            "for_you": _once(self.for_you),
        }
        budget = getattr(self, "budget", None)
        if budget is not None:
            out["model"] = {"calls": budget.calls, "limit": budget.limit,
                            "tokens": budget.tokens(),
                            "by_task": dict(sorted(budget.by_task.items()))}
            budget.record(self.root)
        path = self.root / "review" / "auto.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2, ensure_ascii=False),
                        encoding="utf-8")

        emit("")
        if budget is not None and budget.calls:
            emit(budget.summary())
            if budget.calls >= budget.limit:
                emit("  that is the ceiling. Raise it with VERBA_MODEL_CALLS if "
                     "the document is genuinely this big.")
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
            emit(f"{len(_once(self.for_you))} thing(s) still yours to decide")
        return out
