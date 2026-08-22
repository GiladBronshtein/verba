"""Drift detection: compare a capture of the live system against the document.

Answers the question that governs every documentation update: which sections
are now wrong, and in what way. Output is a review queue, ordered so the
highest-confidence differences are handled first.
"""
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path


from .naming import is_not_a_control

from .capture import _norm
from .imaging import distance, fingerprint_file

# Which declared block type each captured element kind is compared against.
KIND_MAP = {
    "columns": "columns",
    "fields": "fields",
    "actions": "actions",
    "buttons": "actions",
    "tabs": "tabs",
    "labels": "fields",
}

RENAME_RATIO = 0.72
IMAGE_CHANGED = 0.35


@dataclass
class Change:
    section: str
    screen: str
    kind: str
    change: str          # added | removed | renamed | image | unmapped
    label: str = ""
    became: str = ""
    confidence: float = 1.0
    note: str = ""
    # What the live screen showed. An "the section documents none" item is only
    # actionable if it brings the labels along; without them it is a complaint.
    items: list = field(default_factory=list)

    def line(self) -> str:
        if self.change == "renamed":
            return f"renamed {self.kind[:-1]} `{self.label}` -> `{self.became}`"
        if self.change == "image":
            return f"screenshot no longer matches the live screen ({self.note})"
        if self.change == "unmapped":
            return self.note
        return f"{self.change} {self.kind[:-1]} `{self.label}`"


@dataclass
class Report:
    captured_at: str = ""
    changes: list[Change] = field(default_factory=list)
    unmapped_screens: list[str] = field(default_factory=list)
    suspect_screens: list = field(default_factory=list)
    stale_sections: list[str] = field(default_factory=list)
    capture_errors: list = field(default_factory=list)

    def by_section(self) -> dict[str, list[Change]]:
        out: dict[str, list[Change]] = {}
        for c in self.changes:
            out.setdefault(c.section, []).append(c)
        return out

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for c in self.changes:
            counts[c.change] = counts.get(c.change, 0) + 1
        return {"sections_affected": len(self.by_section()), **counts,
                "unmapped_screens": len(self.unmapped_screens),
                "suspect_screens": len(self.suspect_screens),
                "stale_sections": len(self.stale_sections)}


def _match_lists(declared: list[str], observed: list[str]):
    """Pair declared labels to observed ones, tolerating wording changes."""
    d_norm = {_norm(x): x for x in declared if x}
    o_norm = {_norm(x): x for x in observed if x}
    exact = set(d_norm) & set(o_norm)
    missing = [d_norm[k] for k in d_norm if k not in exact]
    extra = [o_norm[k] for k in o_norm if k not in exact]

    renames = []
    for m in list(missing):
        best, ratio = None, 0.0
        for e in extra:
            a, b = _norm(m), _norm(e)
            r = difflib.SequenceMatcher(None, a, b).ratio()
            # A qualified label ("ID" -> "Publisher ID") scores badly on edit
            # distance but is almost always the same column renamed.
            if _is_qualified(a, b):
                r = max(r, 0.80)
            if r > ratio:
                best, ratio = e, r
        if best and ratio >= RENAME_RATIO:
            renames.append((m, best, ratio))
            missing.remove(m)
            extra.remove(best)
    return missing, extra, renames


def _is_qualified(a: str, b: str) -> bool:
    """True when one label is the other plus qualifying words."""
    wa, wb = a.split(), b.split()
    if not wa or not wb or wa == wb:
        return False
    short, long_ = (wa, wb) if len(wa) < len(wb) else (wb, wa)
    return all(w in long_ for w in short)


def _carries_value(project, name: str) -> bool:
    """Does this name contain a value the crawler substituted for a real one?"""
    try:
        from .lint import _masked_values
        return any(v in (name or "") for v in _masked_values(project))
    except Exception:
        return False


def _plausible(expected_url: str, landed_url: str) -> bool:
    """Did the crawl finish on the page it was aiming for?"""
    from urllib.parse import urlparse
    a, b = urlparse(expected_url), urlparse(landed_url)
    pa = [x for x in a.path.split("/") if x]
    pb = [x for x in b.path.split("/") if x]
    if not pa:
        return True
    # the first path segment is the module: /supply is not /demand, and
    # /auth/login is certainly not /supply
    return bool(pb) and pa[0] == pb[0]


def analyse(project, capture_dir: Path, staleness_days: int = 120,
            screens_cfg: dict | None = None) -> Report:
    if isinstance(capture_dir, dict):
        inv = capture_dir              # a pre-merged inventory
        capture_dir = Path(inv.get("_dir", "."))
    else:
        inv = json.loads(
            (Path(capture_dir) / "inventory.json").read_text(encoding="utf-8"))
    rep = Report(captured_at=inv.get("captured_at", ""),
                 capture_errors=inv.get("errors", []))
    screens = inv.get("screens", {})

    # section id -> screens it claims
    claims: dict[str, list[str]] = {}
    for node in project.nodes:
        sec = node.section
        if sec is None:
            continue
        for s in sec.screens:
            claims.setdefault(s, []).append(sec.id)

    for screen_id, record in screens.items():
        owners = claims.get(screen_id) or record.get("sections") or []
        if not owners:
            rep.unmapped_screens.append(screen_id)
            continue

        # If the crawl did not end up on the screen it was asked for, its labels
        # describe a different page and every difference derived from them is
        # noise. Better to report the screen as suspect than to fill the queue.
        expected = (screens_cfg or {}).get(screen_id)
        landed = record.get("url", "")
        if expected and landed and not _plausible(expected, landed):
            rep.suspect_screens.append(
                {"screen": screen_id, "expected": expected, "landed": landed})
            continue

        elements = record.get("elements", {})
        for owner in owners:
            sec = project.sections.get(owner)
            if sec is None:
                continue
            declared = sec.declared_labels()

            for cap_kind, observed in elements.items():
                target = KIND_MAP.get(cap_kind, cap_kind)
                if target is None or not observed:
                    continue
                dec = declared.get(target, [])
                if not dec:
                    rep.changes.append(Change(
                        owner, screen_id, target, "unmapped", confidence=0.5,
                        note=f"live screen exposes {len(observed)} {cap_kind} "
                             f"but the section documents none",
                        items=list(observed)))
                    continue
                missing, extra, renames = _match_lists(dec, observed)
                for m in missing:
                    rep.changes.append(Change(owner, screen_id, target, "removed", m))
                for e in extra:
                    # The crawler reads whatever the page shows, which includes
                    # avatar initials, bare numbers and layout spacers. Adding
                    # those to the document only for the sweep to take them out
                    # again is a loop the reviewer has to close by hand.
                    if is_not_a_control(e):
                        continue
                    # And whatever the row happened to be called. "Test Account
                    # 11-OW" is one partner's connection, not a control: adding
                    # it breaks the rule that says prose names the feature, so
                    # the next pass has to take it out again.
                    if _carries_value(project, e):
                        continue
                    rep.changes.append(Change(owner, screen_id, target, "added", e))
                for old, new, ratio in renames:
                    if _carries_value(project, new) and not _carries_value(project, old):
                        continue
                    # The screen shows a tooltip where the document has the
                    # control's real name, so the crawler reads the tooltip and
                    # proposes renaming the good name to the bad one. Applying
                    # that undoes the writing pass, and the next crawl proposes
                    # it again: the same loop as adding a name that is not a
                    # control, arriving through a different door.
                    if is_not_a_control(new) and not is_not_a_control(old):
                        continue
                    rep.changes.append(Change(owner, screen_id, target, "renamed",
                                              old, new, round(ratio, 2)))

            # screenshot comparison
            shot = record.get("shot")
            if shot:
                origin = (inv.get("_runs") or {}).get(screen_id)
                base = (Path(capture_dir).parent / origin) if origin else Path(capture_dir)
                new_path = base / "screenshots" / shot
                if not new_path.exists():
                    new_path = Path(capture_dir) / "screenshots" / shot
                for block in sec.blocks:
                    if block.kind != "screenshot":
                        continue
                    cur = project.asset_path(block.attrs.get("file", ""))
                    if not (cur.exists() and new_path.exists()):
                        continue
                    try:
                        d = distance(fingerprint_file(cur), fingerprint_file(new_path))
                    except Exception:
                        continue
                    if d > IMAGE_CHANGED:
                        rep.changes.append(Change(
                            owner, screen_id, "screenshot", "image",
                            label=block.attrs.get("file", ""),
                            confidence=min(1.0, d),
                            note=f"visual difference {d:.2f}"))
                    break

    # staleness relative to this capture
    cap_date = _parse_date(inv.get("captured_at", "")) or date.today()
    for node in project.nodes:
        sec = node.section
        if sec is None:
            continue
        lv = _parse_date(sec.last_verified)
        if lv is None or (cap_date - lv).days > staleness_days:
            rep.stale_sections.append(sec.id)

    rep.changes.sort(key=lambda c: (-c.confidence, c.section, c.kind, c.label))
    return rep


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:19]).date()
    except ValueError:
        return None


def to_markdown(rep: Report, project) -> str:
    numbers = {n.id: n.number for n in project.nodes}
    titles = {n.id: n.title for n in project.nodes}
    lines = [
        "# Documentation drift review",
        "",
        f"Capture: {rep.captured_at or 'unknown'}    Profile: {project.profile.name}",
        "",
        "## Summary",
        "",
    ]
    for k, v in rep.summary().items():
        lines.append(f"- {k.replace('_', ' ')}: {v}")
    lines += ["", "## Review queue", ""]

    by_sec = rep.by_section()
    if not by_sec:
        lines.append("No differences found between the capture and the document.")
    for sid, changes in sorted(by_sec.items(), key=lambda kv: numbers.get(kv[0], "zz")):
        num = numbers.get(sid, "?")
        lines += [f"### {num} {titles.get(sid, sid)}", f"`{sid}`", ""]
        for c in changes:
            flag = "!" if c.confidence >= 0.9 else "?"
            lines.append(f"- [{flag}] {c.line()}")
        lines.append("")

    if rep.stale_sections:
        lines += ["## Not re-verified in this capture", ""]
        for sid in sorted(rep.stale_sections, key=lambda s: numbers.get(s, "zz")):
            lines.append(f"- {numbers.get(sid,'?')} {titles.get(sid, sid)} (`{sid}`)")
        lines.append("")

    if rep.suspect_screens:
        lines += ["## Screens that did not load where they were sent", "",
                  "The crawl finished somewhere other than the screen it was asked "
                  "for, so its labels describe a different page. No differences are "
                  "reported from these, because they would all be noise.", ""]
        for sspec in rep.suspect_screens:
            lines.append(f"- `{sspec['screen']}` was sent to {sspec['expected']} "
                         f"but finished on {sspec['landed']}")
        lines.append("")

    if rep.unmapped_screens:
        lines += ["## Captured screens with no section", "",
                  "These screens exist in the product but nothing in the document "
                  "covers them. Each is a candidate new section.", ""]
        for s in rep.unmapped_screens:
            lines.append(f"- `{s}`")
        lines.append("")

    if rep.capture_errors:
        lines += ["## Capture problems", ""]
        for e in rep.capture_errors:
            lines.append(f"- `{e.get('screen','?')}`: {e.get('error','')}")
        lines.append("")

    return "\n".join(lines)
