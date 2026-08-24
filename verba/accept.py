"""Reading a section and saying so, one at a time.

Requiring a person's signature on every section is only honest if signing is
possible. Thirty-eight sections, each needing someone to open a file, read it
against a screenshot, and run a command, is a rule that will be satisfied by
a shell loop within a week, and then the signature means what the bulk date
meant before it.

So this walks them. For each section it shows what the section claims, what the
crawl saw on the screen behind it, what has changed since anybody last looked,
and then asks. Accepting takes one keystroke. Not accepting takes one keystroke.
Nothing is skipped silently and nothing is signed in a batch.

The one thing it will not do is accept on your behalf, including when you hold
down Return: an empty answer is a skip, never a yes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .attest import attest, is_attested, latest_capture, signed_by_a_person, whoami


@dataclass
class Card:
    """Everything a person needs in front of them to say yes or no."""
    id: str
    number: str
    title: str
    words: int
    figures: list = field(default_factory=list)
    claims: dict = field(default_factory=dict)
    seen: dict = field(default_factory=dict)
    changed_since: list = field(default_factory=list)
    status: str = ""
    last: str = ""
    checked_by_loop: bool = False

    def differences(self) -> list[str]:
        """Where the section and the crawl disagree, in words."""
        out = []
        for kind in sorted(set(self.claims) | set(self.seen)):
            said = [str(x) for x in self.claims.get(kind, [])]
            saw = [str(x) for x in self.seen.get(kind, [])]
            if not saw:
                continue
            missing = [x for x in saw if x not in said]
            extra = [x for x in said if x not in saw]
            if missing:
                out.append(f"on screen but not written: {', '.join(missing[:6])}")
            if extra:
                out.append(f"written but not on screen: {', '.join(extra[:6])}")
        return out


def _evidence(root: Path, screens: list[str]) -> dict:
    run = latest_capture(root)
    if not run:
        return {}
    path = Path(root) / "capture" / run / "inventory.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict = {}
    for sid in screens:
        for kind, values in ((data.get("screens", {}).get(sid) or {})
                             .get("elements", {}) or {}).items():
            out.setdefault(kind, []).extend(values)
    return out


def outstanding(project, root: Path | str) -> list[Card]:
    """Every section whose claim has no person behind it."""
    root = Path(root)
    cards = []
    for node in project.nodes:
        sec = node.section
        if sec is None or sec.path is None:
            continue
        # A section the loop has checked is not outstanding, but a person
        # reading it themselves still upgrades the signature, so it stays on
        # the list marked for what it is.
        if sec.status == "verified" and signed_by_a_person(sec.meta):
            continue
        try:
            text = sec.path.read_text(encoding="utf-8")
        except Exception:
            continue
        cards.append(Card(
            id=sec.id, number=node.number, title=sec.title,
            words=len(text.split()),
            figures=sec.screenshots(),
            claims=sec.declared_labels(),
            seen=_evidence(root, sec.screens),
            status=sec.status,
            last=sec.last_verified,
            checked_by_loop=is_attested(sec.meta),
        ))
    return cards


def sign(project, root: Path | str, section_id: str, who: str = "",
         when: str = "") -> str:
    """Record one acceptance. Raises rather than inventing a signature."""
    from datetime import date
    root = Path(root)
    who = (who or "").strip() or whoami()
    if not who:
        raise ValueError("nobody is named. Set VERBA_WHO or git config user.name.")
    against = latest_capture(root)
    if not against:
        raise ValueError("nothing has been captured, so there is nothing to "
                         "have checked this against.")
    sec = project.sections.get(section_id)
    if sec is None:
        raise ValueError(f"no section {section_id!r}")
    sec.meta = attest(sec.meta, who, against, when or date.today().isoformat())
    sec.save(sec.path)
    return f"{who} accepted {section_id} against {against}"
