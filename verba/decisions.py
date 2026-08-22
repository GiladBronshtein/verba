"""Decisions on proposed changes, and the reasons behind them.

A review queue that forgets is worse than no queue: the same rejected suggestion
comes back every crawl, and the reviewer learns to skim rather than read. So
every approve and every decline is recorded against a fingerprint of the change
itself, with the reason given at the time.

Two things then use that record:

* **drift** marks a change that was declined before, so it never again arrives
  looking like a fresh finding, and can be hidden entirely.
* **the writing assistant** is given the notes for a section, so a decision made
  once is not quietly undone by the next proposal.
"""
from __future__ import annotations

import hashlib
from .atomic import write_json
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

STORE = "review/decisions.json"

APPROVED = "approved"
DECLINED = "declined"


def fingerprint(change: dict) -> str:
    """Identify a change by what it proposes, not by when it was seen.

    Confidence and wording can shift between crawls; the section, the kind of
    change and the label it concerns do not. Keying on those means the same
    proposal is recognised on a later run.
    """
    parts = [
        str(change.get("section", "")),
        str(change.get("kind", "")),
        str(change.get("change", "")),
        str(change.get("label", "")).strip().lower(),
        str(change.get("became", "")).strip().lower(),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


# Reasons only the system ever gives itself. Used to read older records, which
# predate the field that says who decided.
AUTO_REASONS = {
    "applying this added a rule finding",
}


@dataclass
class Decision:
    id: str
    section: str
    verdict: str                 # approved | declined
    line: str = ""
    reason: str = ""
    at: str = ""
    change: dict = field(default_factory=dict)
    # Who decided. A person's decline is binding; the system's is a note to
    # itself, made under whatever it could do that day, and has to be
    # reconsidered when that changes. Conflating the two meant a change the
    # system declined because it could not yet describe an added control was
    # then quoted back to the writer as "reviewed by a person and must be
    # respected", and no later run would look at it again.
    by: str = "human"            # human | auto

    @property
    def binding(self) -> bool:
        return self.by != "auto"

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Decisions:
    root: Path
    items: dict = field(default_factory=dict)
    reversed_: list = field(default_factory=list)

    @classmethod
    def load(cls, root: Path) -> "Decisions":
        root = Path(root)
        path = root / STORE
        items, rev = {}, []
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                # the store used to be a bare list; keep reading those
                entries = raw.get("decisions", []) if isinstance(raw, dict) else raw
                rev = raw.get("reversed", []) if isinstance(raw, dict) else []
                for d in entries:
                    # Records written before `by` existed. The system's own
                    # retreats are identifiable by the reason it gives itself,
                    # and reading them as human rulings would keep them binding
                    # forever.
                    if "by" not in d:
                        d["by"] = ("auto" if d.get("reason", "") in AUTO_REASONS
                                   else "human")
                    items[d["id"]] = Decision(**{k: v for k, v in d.items()
                                                 if k in Decision.__annotations__})
            except Exception:
                items, rev = {}, []
        return cls(root=root, items=items, reversed_=rev)

    def save(self):
        path = self.root / STORE
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, {
            "decisions": [d.to_dict() for d in self.items.values()],
            "reversed": self.reversed_[-300:],
        })

    # ------------------------------------------------------------------
    def record(self, change: dict, verdict: str, reason: str = "",
               by: str = "human") -> Decision:
        if verdict == DECLINED and not reason.strip():
            raise ValueError("declining a change needs a reason: the next crawl "
                             "reads it, and so does the writing assistant")
        d = Decision(
            id=fingerprint(change),
            section=str(change.get("section", "")),
            verdict=verdict,
            line=str(change.get("line", "")),
            reason=reason.strip(),
            at=datetime.now().isoformat(timespec="seconds"),
            change={k: change.get(k) for k in
                    ("kind", "change", "label", "became", "screen")},
            by=by,
        )
        self.items[d.id] = d
        self.save()
        return d

    def reopen(self, change: dict, note: str = "") -> Decision | None:
        """Take a decision back, keeping the record that it was made.

        Deleting it outright would lose the fact that a judgement was reached
        and then reconsidered, which is exactly the sort of thing someone asks
        about six months later. The item becomes actionable again and the model
        stops being told about it, but the trail survives.
        """
        sig = fingerprint(change)
        old = self.items.pop(sig, None)
        if old is None:
            return None
        self.reversed_.append({
            **old.to_dict(),
            "reopened_at": datetime.now().isoformat(timespec="seconds"),
            "reopened_note": note.strip(),
        })
        self.save()
        return old

    def reversals_for(self, section_id: str) -> list[dict]:
        return [r for r in self.reversed_ if r.get("section") == section_id]

    def verdict_for(self, change: dict) -> Decision | None:
        return self.items.get(fingerprint(change))

    def declined_for(self, section_id: str, binding_only: bool = False) -> list[Decision]:
        return [d for d in self.items.values()
                if d.section == section_id and d.verdict == DECLINED
                and (d.binding or not binding_only)]

    def notes_for(self, section_id: str) -> str:
        """The standing instructions for a section, for the model to obey."""
        # Only what a person actually decided. Telling the model that the
        # system's own retreat was a human ruling makes it defend a gap.
        declined = self.declined_for(section_id, binding_only=True)
        if not declined:
            return ""
        lines = ["Decisions already made about this section. These were reviewed "
                 "by a person and must be respected, not re-proposed:"]
        for d in declined:
            lines.append(f"  - rejected: {d.line}")
            lines.append(f"    reason given: {d.reason}")
        return "\n".join(lines)

    def summary(self) -> dict:
        approved = [d for d in self.items.values() if d.verdict == APPROVED]
        declined = [d for d in self.items.values() if d.verdict == DECLINED]
        return {"total": len(self.items), "approved": len(approved),
                "declined": len(declined), "reopened": len(self.reversed_),
                "sections_with_notes": len({d.section for d in declined})}

    def annotate(self, changes: list[dict]) -> list[dict]:
        """Mark each change with any decision already taken on it."""
        out = []
        for c in changes:
            d = self.verdict_for(c)
            item = dict(c)
            if d:
                item["decided"] = d.verdict
                item["decided_at"] = d.at
                item["decided_reason"] = d.reason
            out.append(item)
        return out
