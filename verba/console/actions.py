"""Actions the console can take on content: apply a drift item, edit a section.

These are the operations that would otherwise be hand edits. Each one is a
small, reversible change to a section file, so a mistake is a git revert rather
than a rewrite.
"""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from ..assets import refresh_derived
from ..model import LABEL_KEY, Block, load_section


def _find_block(section, kind: str) -> Block | None:
    for b in section.blocks:
        if b.kind == kind:
            return b
    return None


def apply_rename(section, kind: str, old: str, new: str) -> str:
    key = LABEL_KEY.get(kind)
    if not key:
        return f"cannot rename inside a {kind} block"
    hits = 0
    for b in section.blocks:
        if b.kind != kind:
            continue
        for it in b.items:
            if isinstance(it, dict) and str(it.get(key, "")).strip().lower() == old.strip().lower():
                it[key] = new
                hits += 1
    if not hits:
        return f"no {kind[:-1]} named {old!r} found"
    section.save(section.path)
    return f"renamed {hits} {kind[:-1]} entry to {new!r}"


def apply_add(section, kind: str, label: str) -> str:
    key = LABEL_KEY.get(kind)
    if not key:
        return f"cannot add to a {kind} block"
    block = _find_block(section, kind)
    if block is None:
        block = Block(kind, items=[])
        section.blocks.append(block)
    if any(isinstance(i, dict) and str(i.get(key, "")).lower() == label.lower()
           for i in block.items):
        return f"{label!r} is already documented"
    # description is left as a TODO on purpose: a capture proves a control
    # exists, it does not prove what the control does
    block.items.append({key: label, "description": "TODO: describe this."})
    section.save(section.path)
    return f"added {kind[:-1]} {label!r} with a TODO description"


def apply_remove(section, kind: str, label: str) -> str:
    key = LABEL_KEY.get(kind)
    if not key:
        return f"cannot remove from a {kind} block"
    removed = 0
    for b in section.blocks:
        if b.kind != kind:
            continue
        before = len(b.items)
        b.items = [i for i in b.items
                   if not (isinstance(i, dict)
                           and str(i.get(key, "")).strip().lower() == label.strip().lower())]
        removed += before - len(b.items)
    section.blocks = [b for b in section.blocks
                      if b.kind not in LABEL_KEY or b.items]
    if not removed:
        return f"no {kind[:-1]} named {label!r} found"
    section.save(section.path)
    return f"removed {removed} {kind[:-1]} entry"


def _run_was_masked(capture_dir: Path) -> bool:
    """Did the crawl that produced this run have masking on?

    Read from the run's own manifest rather than from the rules as they stand
    today, because the rules can be turned on after the fact and that would
    retroactively vouch for pictures nobody masked.
    """
    try:
        import json
        man = json.loads((Path(capture_dir) / "inventory.json").read_text(encoding="utf-8"))
        mask = man.get("masking") or {}
        return bool(mask.get("active", mask.get("known_values", 0) or
                             mask.get("new_values", 0)))
    except Exception:
        return False


def apply_image(project, capture_dir: Path, asset_name: str, log=None) -> str:
    src = Path(capture_dir) / "screenshots" / asset_name
    if not src.exists():
        # the capture may have stored it under the screen's own shot name
        candidates = list((Path(capture_dir) / "screenshots").glob("*.png"))
        return (f"capture has no {asset_name}; available: "
                f"{', '.join(c.name for c in candidates[:6]) or 'nothing'}")
    dest = project.asset_path(asset_name)
    shutil.copyfile(src, dest)
    entry = project.assets.registry.setdefault(asset_name, {})
    entry.update({"source": str(src), "replaced_on": date.today().isoformat()})
    # Record that this picture came through the masking rules, and whether they
    # were on. Provenance is the only thing that can be checked later: the rules
    # run in the browser milliseconds before the shutter, and nothing about the
    # resulting PNG says whether they did. Without this, a picture lifted out of
    # an old Word file and a picture taken under full masking are the same file
    # on disk with the same claim to be in the document.
    entry["masked"] = _run_was_masked(Path(capture_dir))
    entry.pop("legacy_name", None)
    project.assets.save()
    r = refresh_derived(project.assets, asset_name, capture_dir=capture_dir, log=log)
    bits = []
    if r["captured"]:
        bits.append(f"refreshed {len(r['captured'])} inline element(s)")
    if r["recut"]:
        bits.append(f"re-cut {len(r['recut'])} from stored rectangles, check those")
    tail = (", and " + ", and ".join(bits)) if bits else ""
    return f"replaced {asset_name} from the capture{tail}"


def apply_change(project, change: dict, capture_dir: Path | None) -> str:
    """Route one drift item to the edit that resolves it."""
    sid = change.get("section", "")
    section = project.sections.get(sid)
    if section is None:
        return f"unknown section {sid!r}"
    section = load_section(section.path)          # re-read: the file may have moved on
    kind = change.get("kind", "")
    kind_of = change.get("change", "")
    label = change.get("label", "")

    if kind_of == "renamed":
        return apply_rename(section, kind, label, change.get("became", ""))
    if kind_of == "added":
        return apply_add(section, kind, label)
    if kind_of == "removed":
        return apply_remove(section, kind, label)
    if kind_of == "unmapped":
        # The screen shows a set of controls and the section names none of them.
        # The crawl brought the labels, so write them; the descriptions are
        # filled from the evidence immediately afterwards, and the pair is
        # judged together rather than the write being judged on its own.
        labels = [str(x) for x in (change.get("items") or []) if str(x).strip()]
        if not labels:
            return "nothing was observed to write"
        written = 0
        for lab in labels:
            note = apply_add(section, kind, lab)
            section = load_section(section.path)
            if note.startswith("added"):
                written += 1
        return f"documented {written} {kind} the screen shows"
    if kind_of == "image":
        if capture_dir is None:
            return "no capture available to take the image from"
        return apply_image(project, capture_dir, label)
    return f"{kind_of!r} needs a judgement call, open the section instead"


def set_meta(section, updates: dict) -> str:
    for k, v in updates.items():
        if v in (None, ""):
            section.meta.pop(k, None)
        else:
            section.meta[k] = v
    section.save(section.path)
    return f"updated {', '.join(updates)}"


def verify(section, when: str | None = None, root=None, who: str = "") -> str:
    """Accept a section, and record what makes that an acceptance.

    A name and the crawl it was read against. Without both it is a date, and a
    date is what thirty-five sections of the first real document carried while
    nobody had read any of them.
    """
    from ..attest import attest, latest_capture, whoami
    who = (who or "").strip() or whoami()
    if not who:
        raise ValueError(
            "nobody is named. Set VERBA_WHO, or a name in git config, so the "
            "acceptance says who made it.")
    against = latest_capture(root or section.path.parents[2])
    if not against:
        raise ValueError(
            "nothing has been captured yet, so there is nothing to have "
            "checked this against.")
    section.meta = attest(section.meta, who, against,
                          when or date.today().isoformat())
    section.save(section.path)
    return (f"{who} accepted this on {section.meta['last_verified']}, "
            f"against capture {against}")
