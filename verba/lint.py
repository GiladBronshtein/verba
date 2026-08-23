"""Rule engine.

Encodes the project's standing content rules so they are checked on every
build rather than remembered per session. Each rule returns Findings; the
build fails on any ERROR.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

from .attest import is_attested

ERROR, WARN, INFO = "error", "warning", "info"

# Which names must not appear in a neutral edition is a property of the
# project, not of this linter: see Project.tenant_terms().

URL_PATTERNS = [
    re.compile(r"https?://[^\s)]+"),
    re.compile(r"(?<![\w.])/(?:supply|demand|admin|dashboard|login|settings|users)\b"),
]

INTERNALS = [
    (re.compile(r"\b(?:HTTP\s*)?[45]\d{2}\s+(?:error|status|response)", re.I), "HTTP status code"),
    (re.compile(r"\bJWT\b|\bbearer token\b|\brefresh token\b", re.I), "token internals"),
    (re.compile(r"\bAPI endpoint\b|\bPOST /|\bGET /", re.I), "API internals"),
    (re.compile(r"\bnull\b|\bundefined\b|\bNaN\b"), "developer-facing value"),
]

EM_DASH = "—"
UNRESOLVED = re.compile(r"\{\{|\}\}")
ICON_NAME = re.compile(r"\b(bell|gear|pencil|trash|plus|magnifier|chevron)\s+icon\b", re.I)


@dataclass
class Finding:
    rule: str
    level: str
    section: str
    message: str
    detail: str = ""

    def __str__(self):
        loc = f"{self.section}" if self.section else "-"
        tail = f"  ({self.detail})" if self.detail else ""
        return f"[{self.level.upper():7}] {self.rule}  {loc}: {self.message}{tail}"


# A figure is a picture of a screen. Captures are taken at 1440x768 and cropped,
# so anything this far below that is a control, not a screen.
FIGURE_MIN_W = 320
FIGURE_MIN_H = 200

TODO_MARK = re.compile(r"TODO:\s*describe this", re.I)


def _unwritten(section) -> list[str]:
    """Every place a description was left for later, named so it can be found."""
    out = []
    for b in section.blocks:
        if TODO_MARK.search(b.text or ""):
            out.append(f"{b.kind}: {(b.text or '')[:40]}")
        for it in (b.items or []):
            if isinstance(it, dict):
                for key, value in it.items():
                    if isinstance(value, str) and TODO_MARK.search(value):
                        name = (it.get("field") or it.get("name")
                                or it.get("action") or it.get("column") or key)
                        out.append(str(name))
            elif TODO_MARK.search(str(it)):
                out.append(str(it)[:40])
    return out


def _image_size(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None


def _is_blank(path) -> bool:
    """A capture that came back as one flat colour."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            lo, hi = im.convert("L").getextrema()
            return (hi - lo) < 12
    except Exception:
        return False


@lru_cache(maxsize=4)
def _masked_values_for(root: str) -> tuple:
    """Every placeholder the crawler substitutes for a real entity name.

    These belong in screenshots, where a picture has to show something. In
    prose they mean the sentence is about one account rather than about the
    product.
    """
    path = Path(root) / "content" / "masking-map.json"
    if not path.exists():
        return ()
    try:
        mp = json.loads(path.read_text(encoding="utf-8")).get("map", {})
    except Exception:
        return ()
    seen = {v for v in mp.values() if isinstance(v, str) and len(v) > 3}
    # longest first, so the more specific name is reported
    return tuple(sorted(seen, key=len, reverse=True))


def _masked_values(project) -> tuple:
    return _masked_values_for(str(getattr(project, "root", ".")))


def _texts(project, section):
    """Every user-visible string a section will render, with a locator."""
    out = [("title", section.title)]
    for i, b in enumerate(project.resolved_blocks(section)):
        if b.text:
            out.append((f"{b.kind}[{i}]", b.text))
        for j, it in enumerate(b.items):
            if isinstance(it, dict):
                for k, v in it.items():
                    if isinstance(v, str):
                        out.append((f"{b.kind}[{i}].{k}", v))
            else:
                out.append((f"{b.kind}[{i}][{j}]", str(it)))
        for k in ("caption", "label"):
            if b.attrs.get(k):
                out.append((f"{b.kind}[{i}].{k}", b.attrs[k]))
    return out


def _allowed(project, rule: str, section_id: str, detail: str) -> bool:
    """Documented, reviewable exceptions declared in doc.yaml under `lint.allow`.

    An exception must name the rule and either a section or a literal string,
    so every suppression is visible in one place instead of being argued again
    each time the document is rebuilt.
    """
    for entry in (project.config.get("lint", {}) or {}).get("allow", []) or []:
        if entry.get("rule") != rule:
            continue
        sec = entry.get("section")
        if sec and sec not in section_id:
            continue
        match = entry.get("match")
        if match and match not in detail:
            continue
        return True
    return False


# What clears each rule, and whether the system can do it or a person must.
# A finding without an entry here still reports; it just cannot offer a button.
REMEDIES = {
    "CONTENT-02": ("Ask the writer to fill these in",
                   "sweep", "It writes what the crawl can answer and offers to "
                            "remove anything that was never a control."),
    "ASSET-01":   ("Recapture this screen", "capture",
                   "The image the section refers to is not in the library."),
    "ASSET-05":   ("Show it in Images", "images",
                   "Nothing in the document uses this picture. Put it in a "
                   "section or delete it."),
    "ASSET-04":   ("Show it in Images", "images",
                   "The same picture is stored under two names. Usually one of "
                   "them belongs to a screen that redirected, so its capture is "
                   "a picture of somewhere else. Remove the one nothing uses."),
    "ASSET-07":   ("Adopt the captured version", "adopt",
                   "The screen captured under a name this section does not use."),
    "ASSET-08":   ("Edit the section", "open",
                   "Give it a caption only if it really is a picture of a screen; "
                   "otherwise leave it captionless and it renders as a detail."),
    # "open" rather than "none": nothing can decide this, but the person can,
    # and the place to do it is the section that ships the picture. A finding
    # with nothing to press is a complaint, which is a rule this project holds
    # itself to and I had just broken.
    "ASSET-12":   ("Open the section that shows it", "open",
                   "The picture is of a different part of the product from the "
                   "one this section describes. Either point the section at a "
                   "screen that shows what it is about, or take the figure out "
                   "and let the text stand."),
    "ASSET-11":   ("Open the section that shows it", "open",
                   "Nothing has checked this picture for real names, and no "
                   "screen in the registry produces it, so photographing the "
                   "system will never replace it. Someone added it by hand, or "
                   "it came out of an older document. Either register a screen "
                   "that captures this view, or take the picture out. Nothing "
                   "can decide that for you."),
    "ASSET-10":   ("Photograph this screen properly", "capture",
                   "This picture never went through masking, so nothing has "
                   "checked whether it shows a real customer's account. "
                   "Photographing the screen again puts it through the masking "
                   "rules and settles it."),
    "ASSET-09":   ("Recapture this screen", "capture",
                   "The capture came back blank."),
    "FRESH-01":   ("Mark verified", "verify", "Nobody has checked this against "
                                              "the live product."),
    "FRESH-04":   ("Mark verified", "verify",
                   "The section says it was verified, but does not say by whom "
                   "or against which crawl. Accepting it again records both, "
                   "and the badge is dropped automatically the next time "
                   "anything but a person changes the section."),
    "FRESH-02":   ("Recapture this screen", "capture", "The check is old."),
    "FRESH-03":   ("Recapture this screen", "capture", "The check is old."),
    "STYLE-01":   ("Rewrite to house style", "assist:polish",
                   "An em dash is not permitted."),
    "STYLE-02":   ("Rewrite to house style", "assist:polish",
                   "A route or address in prose."),
    "STYLE-03":   ("Rewrite to house style", "assist:polish",
                   "Protocol detail that is not visible in the interface."),
    "STYLE-04":   ("Rewrite to house style", "assist:polish",
                   "An icon is named in prose but not shown."),
    "STYLE-05":   ("Rewrite to house style", "assist:polish",
                   "Prose that should be bullets."),
    "STYLE-06":   ("Rewrite to house style", "assist:polish",
                   "The text names one account's value where it should name the "
                   "feature. The reader is looking at a different account."),
    "GENERIC-01": ("Edit the section", "open",
                   "A customer is named in the tenant-neutral edition."),
    "DESIGN-01":  ("Add a drawn mark", "open",
                   "The mark has no drawn equivalent, so it prints as an emoji."),
    "DESIGN-02":  ("Edit app.css", "none", "Console text below the type floor."),
    "DESIGN-03":  ("Replace with modal()", "none", "A browser dialog is used."),
    "STRUCT-01":  ("Create the section", "none", "The outline names a file that "
                                                 "does not exist."),
    "STRUCT-02":  ("Add it to the outline", "none", "The file exists but ships "
                                                    "nowhere."),
    "CONTENT-01": ("Draft from the crawl", "assist:draft", "The section is empty."),
    "CONTENT-03": ("Ask the writer to tidy these", "sweep",
                   "A placeholder or a tooltip is being documented as though it "
                   "were the name of a control. The writer offers to remove them."),
    "ASSET-06":   ("Capture this screen", "capture",
                   "The section maps to a screen and shows no picture of it."),
    "ASSET-02":   ("Capture this screen", "capture",
                   "The same image is used for two figures in a row."),
    "ASSET-03":   ("Capture this screen", "capture",
                   "Two sections show the same picture, so one of them is "
                   "illustrated by a screen it does not describe. Either give "
                   "the second section a screen of its own in "
                   "content/screens.yaml, or take its figure out and let the "
                   "text stand alone. Which of the two is a judgement about "
                   "the document, so nothing decides it for you."),
    "PROFILE-01": ("Edit the section", "open",
                   "A profile variable did not resolve."),
    "PROFILE-02": ("Edit the section", "open",
                   "A profile variable was left unresolved in the text."),
    "META-01":    ("Edit the section", "open", "The status is not one we use."),
}


def remedy(rule: str) -> dict:
    """What would clear this finding."""
    label, action, why = REMEDIES.get(
        rule, ("No automatic fix", "none",
               "This one needs a person to decide what is right."))
    return {"label": label, "action": action, "why": why}


def lint(project, strict_staleness_days: int = 120) -> list[Finding]:
    tenant_terms = project.tenant_terms()
    findings: list[Finding] = []

    # Design decisions are held to the same standard as content rules. A
    # decision that only lives in a document is a note; one that fails a build
    # is a decision.
    try:
        from .design import Design
        for d in Design.load(project.root).check(project):
            findings.append(Finding(d["rule"], d["level"], d["section"],
                                    d["message"], d.get("detail", "")))
    except Exception:
        pass                       # design memory is additive, never fatal

    def add(finding: Finding):
        if not _allowed(project, finding.rule, finding.section, finding.detail):
            findings.append(finding)

    # -- structure -------------------------------------------------------
    for sid in project.missing():
        add(Finding("STRUCT-01", ERROR, sid, "outline references a section that has no file"))
    for sid in project.orphans():
        add(Finding("STRUCT-02", WARN, sid,
                    "section file exists but is not in the outline, so it will not ship"))

    # -- per-section text rules -------------------------------------------
    for node in project.nodes:
        sec = node.section
        if sec is None:
            continue
        sid = f"{node.number} {sec.id}"

        try:
            texts = _texts(project, sec)
        except Exception as e:
            add(Finding("PROFILE-01", ERROR, sid, "profile variable did not resolve", str(e)))
            continue

        if not sec.blocks:
            add(Finding("CONTENT-01", WARN, sid, "section has no content"))

        # A marker the writer left because the evidence could not answer it is
        # honest while the document is being worked on and indefensible once it
        # ships: the reader sees "TODO: describe this." where a description
        # belongs. It blocks a build so it cannot leave the building by
        # accident.
        # A placeholder is instruction text inside an empty field, and a
        # tooltip is a sentence about a control. Documenting either as though
        # it were the control's name is what produces entries like
        # "Enter publisher name" and "Search by name or ID...".
        from .naming import is_not_a_control, why_not
        wrong = []
        for b in sec.blocks:
            for it in (b.items or []):
                if not isinstance(it, dict):
                    continue
                nm = str(it.get("field") or it.get("name") or it.get("action")
                         or it.get("column") or it.get("term") or "")
                if nm and is_not_a_control(nm):
                    wrong.append(f"{nm} ({why_not(nm)})")
        if wrong:
            add(Finding("CONTENT-03", ERROR, sid,
                        f"{len(wrong)} entry(ies) named by something that is not "
                        f"a control name",
                        "; ".join(wrong[:4])))

        # A specific value where the feature belongs. "Back to Test Publisher 11"
        # describes one row of one account; the reader has a different one. The
        # masking map knows every value the crawler substituted, so anything
        # from it appearing in prose is a value that should have been the name
        # of the thing instead.
        for where, text in texts:
            for value in _masked_values(project):
                if value in text:
                    add(Finding("STYLE-06", ERROR, sid,
                                f"the text names a specific value rather than the "
                                f"feature: {value}",
                                f"{where}: ...{_around(text, value)}..."))
                    break

        left = _unwritten(sec)
        if left:
            add(Finding("CONTENT-02", ERROR, sid,
                        f"{len(left)} description(s) never written",
                        "; ".join(left[:6])))

        for where, text in texts:
            if EM_DASH in text:
                add(Finding("STYLE-01", ERROR, sid,
                            "em dash is not permitted", f"{where}: ...{_around(text, EM_DASH)}..."))
            if UNRESOLVED.search(text):
                add(Finding("PROFILE-02", ERROR, sid,
                            "unresolved template braces reached the output", where))
            for pat in URL_PATTERNS:
                m = pat.search(text)
                if m:
                    add(Finding("STYLE-02", ERROR, sid,
                                "URL or route path in body text", f"{where}: {m.group(0)}"))
            for pat, what in INTERNALS:
                m = pat.search(text)
                if m:
                    add(Finding("STYLE-03", WARN, sid,
                                f"{what} is not user-visible content",
                                f"{where}: {m.group(0)}"))
            if ICON_NAME.search(text) and not re.search(r"[\U0001F300-\U0001FAFF⚙️🔔✏️🗑️➕✅🔍]|\[icon:", text):
                add(Finding("STYLE-04", WARN, sid,
                            "icon named in prose without showing the icon", where))

        if project.profile.neutral:
            for where, text in texts:
                for term in tenant_terms:
                    if re.search(rf"\b{re.escape(term)}\b", text):
                        add(Finding("GENERIC-01", ERROR, sid,
                                    f"customer name {term!r} in the tenant-neutral edition",
                                    where))
                        break

        # prose that should be bullets
        for where, text in texts:
            if where.startswith("paragraph") and text.count(", ") >= 4 and len(text) > 320:
                add(Finding("STYLE-05", INFO, sid,
                            "long list-like paragraph, consider bullets", where))

        # staleness
        lv = sec.last_verified
        # A claim without its evidence is not a check, it is a memory of one.
        # This rule existed to catch an unverified section and stayed quiet on
        # a document where all thirty-eight said verified, thirty-five of them
        # stamped on the same day, because a date was present and nothing asked
        # where the date came from.
        if sec.status == "verified" and not is_attested(sec.meta):
            add(Finding("FRESH-04", WARN, sid,
                        "says verified, but nobody is named and no capture is "
                        "cited",
                        "Marking it verified again records who accepted it and "
                        "which crawl they accepted it against."))
        if not lv:
            add(Finding("FRESH-01", WARN, sid, "no last_verified date"))
        else:
            try:
                d = datetime.fromisoformat(str(lv)).date()
                age = (date.today() - d).days
                if age > strict_staleness_days:
                    add(Finding("FRESH-02", WARN, sid,
                                f"not verified against the live system for {age} days"))
            except ValueError:
                add(Finding("FRESH-03", WARN, sid, f"unparseable last_verified: {lv!r}"))

        if sec.status not in ("draft", "review", "verified", "stale"):
            add(Finding("META-01", WARN, sid, f"unknown status {sec.status!r}"))

    # -- assets -----------------------------------------------------------
    used: dict[str, list[str]] = {}
    for node in project.nodes:
        sec = node.section
        if sec is None:
            continue
        sid = f"{node.number} {sec.id}"
        last = None
        for b in sec.blocks:
            names = []
            if b.kind == "screenshot":
                names.append(b.attrs.get("file", ""))
            for it in b.items:
                for m in re.finditer(r"\[icon:([^\]\s]+)", str(it)):
                    names.append(m.group(1))
            for name in names:
                if not name:
                    continue
                used.setdefault(name, []).append(sid)
                if not project.assets.exists(name):
                    add(Finding("ASSET-01", ERROR, sid, f"missing asset file: {name}"))
            if b.kind == "screenshot":
                # A figure is a picture of a screen. When the file behind one is
                # a cropped control a few dozen pixels tall, the page prints a
                # caption reading "Figure 4.7" over a thin strip, which looks
                # exactly like an image that failed to load.
                shot = b.attrs.get("file", "")
                # A captionless crop is rendered as a detail at its own size,
                # not as a numbered figure, so it is not a fault. One given a
                # caption is being presented as a figure and had better be one.
                if shot and b.attrs.get("caption") and project.assets.exists(shot):
                    size = _image_size(project.asset_path(shot))
                    if size:
                        w, h = size
                        if h < FIGURE_MIN_H or w < FIGURE_MIN_W:
                            add(Finding("ASSET-08", ERROR, sid,
                                        f"figure is too small to be a screen: {shot}",
                                        f"{w}x{h}, expected at least "
                                        f"{FIGURE_MIN_W}x{FIGURE_MIN_H}. "
                                        f"an inline element belongs beside the text, "
                                        f"not under a figure caption"))
                        elif _is_blank(project.asset_path(shot)):
                            add(Finding("ASSET-09", ERROR, sid,
                                        f"figure is blank: {shot}",
                                        "the capture came back empty, so recapture "
                                        "this screen"))
                cur = b.attrs.get("file", "")
                if cur and cur == last:
                    add(Finding("ASSET-02", ERROR, sid,
                                f"the same image is used for two figures in a row: {cur}"))
                last = cur
            elif b.kind == "heading":
                last = None

    for name, wheres in used.items():
        uniq = sorted(set(wheres))
        if len(uniq) > 1:
            add(Finding("ASSET-03", ERROR, "", f"image reused across sections: {name}",
                        " and ".join(uniq)))

    for group in project.assets.duplicate_groups().values():
        in_use = [g for g in group if g in used]
        if len(in_use) > 1:
            add(Finding("ASSET-04", ERROR, "",
                        "byte-identical images used under different names",
                        ", ".join(in_use)))

    # An image belonging to a section this edition leaves out is still doing its
    # job in the edition that carries it. Only an image no section anywhere
    # refers to is genuinely spare.
    held = set(used)
    shipping = {n.id for n in project.nodes}
    for sid in project.listed - shipping:
        sec = project.sections.get(sid)
        if sec is None:
            continue
        for b in sec.blocks:
            if b.kind in ("screenshot", "icon"):
                if b.attrs.get("file"):
                    held.add(b.attrs["file"])

    # Masking runs at capture time, in the browser, immediately before the
    # shutter. That protects everything a crawl takes and says nothing at all
    # about a picture that arrived some other way: lifted out of an older Word
    # file, dropped in by hand, or adopted before any masking rule existed.
    # Those are exactly the pictures most likely to carry a real customer's
    # account into somebody else's documentation, and until now nothing looked.
    #
    # This does not claim the image is wrong. It says nobody has checked, which
    # for a rule the project calls absolute is the thing worth reporting.
    registry = getattr(project.assets, "registry", {}) or {}
    # Whether a crawl could replace this picture at all. A picture the registry
    # produces can be settled by photographing that screen; one it does not is a
    # detail view somebody added by hand, and no amount of crawling will reach
    # it. Reporting both the same way sent people to press a button that could
    # never work.
    shots: set[str] = set()
    try:
        from .capture import load_screens
        _, _screens = load_screens(project.root / "content" / "screens.yaml")
        for s in _screens:
            if getattr(s, "shot", ""):
                shots.add(s.shot)
            for elem in (getattr(s, "elements", []) or []):
                if isinstance(elem, dict) and elem.get("name"):
                    shots.add(elem["name"])
    except Exception:
        pass

    # A picture of something other than what the section describes. Recorded by
    # the loop when it looked, so this costs nothing to check.
    try:
        import json
        matches = json.loads(
            (project.root / "review" / "picture-match.json").read_text(encoding="utf-8"))
    except Exception:
        matches = {}
    # {section id: {filename ruled not to be of that section}}
    misfits: dict[str, set] = {}
    for key, verdict in sorted(matches.items()):
        if verdict.get("fits", True):
            continue
        sid, _, fname = key.partition("|")
        # A verdict is about an image, not about a filename, and the filename
        # outlives the image every time a screen is photographed again. Two
        # rules read these, so one that never expired would silence a rule on
        # evidence about a picture that is no longer there.
        from .auto import _verdict_still_about
        if not _verdict_still_about(project.root, fname, verdict):
            continue
        misfits.setdefault(sid, set()).add(fname)
        sec = project.sections.get(sid)
        if sec is None or fname not in (sec.screenshots() or []):
            continue                       # the figure has since been changed
        add(Finding("ASSET-12", WARN, sid,
                    f"picture is not of what this section describes: {fname}",
                    verdict.get("what", "")))

    for name in sorted(used):
        rec = registry.get(name) or {}
        src = str(rec.get("source", ""))
        if "/capture/" in src or rec.get("masked") or rec.get("checked_by"):
            continue
        where = ("lifted from " + str(rec.get("legacy_name"))
                 if rec.get("legacy_name") else
                 "added outside a crawl" if src else "no record of where it came from")
        if name in shots:
            add(Finding("ASSET-10", WARN, "",
                        f"picture never went through masking: {name}",
                        f"{where}. A screen produces this one, so photographing "
                        f"it will settle it."))
        else:
            owner = (used.get(name) or [""])[0]
            add(Finding("ASSET-11", WARN, owner,
                        f"picture no crawl can reach: {name}",
                        f"{where}. No screen in content/screens.yaml produces "
                        f"this file, so no capture will ever replace it."))

    for name in project.assets.all_names():
        if name in held:
            continue
        # A picture the loop retired on purpose is not a loose end. It was
        # taken out for a reason, the reason is recorded beside it, and
        # reporting it back as unreferenced turns one settled finding into a
        # new one.
        if (registry.get(name) or {}).get("retired"):
            continue
        # A picture nothing shows and no screen produces is inventory, not a
        # finding. Nothing the loop can do reaches it: no crawl replaces it,
        # no step adopts it, and the only remaining move is a person deciding
        # to write a section around it. Reporting it anyway put eighteen
        # permanently unclearable items in front of somebody who had asked
        # five times why the list never emptied, and buried the two items that
        # were real. The Images page lists every unused picture, which is where
        # an inventory belongs.
        if name not in shots:
            continue
        add(Finding("ASSET-05", INFO, "",
                    f"asset is not referenced anywhere: {name}",
                    "A screen produces this file, so either a section should "
                    "show it or the screen should stop capturing it."))

    # A section whose screen captures under a different filename than the section
    # references will crawl happily and change nothing: the new image lands
    # beside the document rather than in it, with nothing to say so.
    try:
        from .capture import load_screens
        _, screens = load_screens(project.root / "content" / "screens.yaml")
        shot_of = {s.id: s.shot for s in screens if s.shot}
    except Exception:
        shot_of = {}
    for node in project.nodes:
        sec = node.section
        if sec is None or not sec.screens:
            continue
        used = set(sec.screenshots())
        for screen_id in sec.screens:
            shot = shot_of.get(screen_id)
            # A capture ruled not to be a picture of this section is a capture
            # this section is right not to use. The rule's premise is that a
            # recapture ought to reach the document; when somebody has looked
            # and said it shows a different part of the product, it ought not,
            # and reporting it asks for a change that would be reverted by the
            # rule below. Two steps then take turns undoing each other forever,
            # which is exactly what happened.
            if shot and shot in misfits.get(sec.id, ()):
                continue
            if shot and used and shot not in used:
                add(Finding("ASSET-07", WARN, f"{node.number} {sec.id}",
                            f"screen {screen_id} captures to {shot}, which this "
                            f"section does not use",
                            f"it shows {', '.join(sorted(used))}, so a recapture "
                            f"will not reach the document"))

    for node in project.nodes:
        sec = node.section
        if sec is None or node.level < 2:
            continue
        if sec.screens and not sec.screenshots():
            # Unless its figure was taken out on purpose. A section left without
            # a picture by a decision the loop recorded is in the state somebody
            # chose, and telling them about it is telling them about their own
            # decision.
            retired = any((rec or {}).get("retired", {}).get("from") == sec.id
                          for rec in (getattr(project.assets, "registry", {}) or {}).values())
            if retired:
                continue
            # Nor when every picture those screens produce is already shown by
            # another section. Capturing again changes nothing, and adopting
            # the picture would put the same figure in two sections, which is
            # an error. A rule whose only available fix is a worse finding is
            # not asking for work, it is asking to be ignored, and a person who
            # has been told five times that the list never empties is right.
            #
            # A sub-section documenting one panel of a screen its parent shows
            # is the ordinary case, not a defect. It wants a crop of its own,
            # which is a person defining a screen, or it wants no figure.
            produced = {shot_of.get(sid) for sid in sec.screens}
            produced.discard(None)
            if produced and all(
                    any(p in (o.screenshots() or []) for o in project.sections.values()
                        if o.id != sec.id)
                    for p in produced):
                continue
            add(Finding("ASSET-06", INFO, f"{node.number} {sec.id}",
                        "section maps to a screen but shows no screenshot"))

    order = {ERROR: 0, WARN: 1, INFO: 2}
    return sorted(findings, key=lambda x: (order[x.level], x.rule, x.section))


def _around(text: str, needle: str, pad: int = 30) -> str:
    i = text.find(needle)
    return text[max(0, i - pad): i + pad].replace("\n", " ")


def summarise(findings: list[Finding]) -> dict:
    return {
        "error": sum(1 for x in findings if x.level == ERROR),
        "warning": sum(1 for x in findings if x.level == WARN),
        "info": sum(1 for x in findings if x.level == INFO),
    }
