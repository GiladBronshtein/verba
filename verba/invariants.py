"""What no step may do, whatever the rule count says.

The loop judges every step by counting rule findings before and after and
putting back anything that raised the count. That catches a step which breaks a
rule. It does not catch a step which damages the document in a way no rule
measures, and in one session three separate steps did exactly that:

* a rewrite took a section from thirteen figures to two, and the count did not
  move, because a missing figure is not an error;
* the decider and the sweep took turns adding and removing the same figure for
  four rounds, and the count was identical after every one;
* two rules disagreed about one picture and undid each other forever, again at
  a constant count.

Each was fixed with a guard against that specific pair. Three patches, one
hole, and no reason to think the fourth pair is not already in here. So this
states the properties generically instead: a step may improve a document, and
it may leave it alone, but there are things it may never do to it, and none of
them are visible to a counter.

Deliberately conservative. Everything here is something a person would call
damage on sight, so a step tripping one of these is a bug and not a judgement
call. Anything arguable belongs in the rules, where it can be discussed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

FIGURE = re.compile(r"^!\[[^\]]*\]\(([^)\s]+)", re.M)
FENCE = re.compile(r"^```([a-z]+)", re.M)

# A rewrite may tighten prose. It may not quietly delete half a section: below
# this share of the words it was given, something has gone wrong rather than
# well.
FLOOR = 0.5


@dataclass
class Shape:
    """The parts of a document a step is not allowed to lose."""
    sections: dict = field(default_factory=dict)

    @classmethod
    def of(cls, project) -> "Shape":
        out = {}
        for sid, sec in project.sections.items():
            try:
                text = sec.path.read_text(encoding="utf-8") if sec.path else ""
            except Exception:
                continue
            out[sid] = {
                "figures": set(FIGURE.findall(text)),
                "blocks": set(FENCE.findall(text)),
                "words": len(text.split()),
            }
        return cls(sections=out)


def faults(before: Shape, after: Shape) -> dict:
    """{section id: what was done to it}, for everything a step may not do.

    Attributed rather than pooled. A step that corrects five sections and
    damages one should lose the one, and pooling the answer into a flat list
    meant the whole step went back and four good corrections went with it.
    """
    out: dict[str, list[str]] = {}

    def note(sid, msg):
        out.setdefault(sid, []).append(msg)

    for sid in set(before.sections) - set(after.sections):
        note(sid, f"{sid} stopped existing")

    for sid, was in before.sections.items():
        now = after.sections.get(sid)
        if now is None:
            continue

        lost = was["figures"] - now["figures"]
        if lost:
            note(sid, f"{sid} lost {len(lost)} figure(s): "
                      f"{', '.join(sorted(lost)[:3])}")

        dropped = was["blocks"] - now["blocks"]
        if dropped:
            note(sid, f"{sid} lost every {', '.join(sorted(dropped))} block")

        if was["words"] and now["words"] < was["words"] * FLOOR:
            note(sid, f"{sid} went from {was['words']} words to {now['words']}")

    return out


def broken(before: Shape, after: Shape) -> list[str]:
    """The same thing, flattened, for callers that only want to know."""
    return [msg for msgs in faults(before, after).values() for msg in msgs]


def tug_of_war(rounds: list[dict]) -> list[str]:
    """Files that keep being changed back and forth by different steps.

    A step that writes a file another step wrote earlier in the same round is
    not necessarily wrong. A file written by two different steps in each of two
    consecutive rounds, with no net change to the rule count, is two steps
    taking turns, and no counter will ever notice because the count is what
    they are both preserving.
    """
    if len(rounds) < 2:
        return []
    out = []
    a, b = rounds[-2], rounds[-1]
    for path, steps in (a.get("writes") or {}).items():
        also = (b.get("writes") or {}).get(path) or []
        if len(set(steps)) > 1 and set(steps) == set(also):
            out.append(f"{path} was written by {' and '.join(sorted(set(steps)))} "
                       f"in two rounds running")
    return out
