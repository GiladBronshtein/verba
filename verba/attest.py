"""Who checked this, and against what.

`status: verified` was a string somebody typed. On the first real document
built with this engine, all thirty-eight sections carried it, thirty-five of
them stamped with the same July date, while History recorded that 2.8% of the
changes to that document had a human behind them. The rule meant to catch
exactly this, FRESH-01, stayed quiet, because a date was present and nothing
asked where the date came from.

So a claim now carries its evidence: who accepted it, and which capture they
accepted it against. A date on its own is not a check, it is a memory of one.

The other half is that the claim expires when the thing it describes changes.
Any change with a machine behind it drops the section back to `review`, because
a person verified the section they read, not the one a model rewrote after
them.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Actors whose changes are the machine's own. `human` and `note` are a person
# at the keyboard; everything else is the loop, the crawl or the model.
MACHINE_ACTORS = {"auto", "assist", "drift", "capture", "system", "sweep",
                  "tidy", "heal"}

# Undoing is not authoring. Putting a section back the way it was returns its
# acceptance along with its text, because the person accepted that text and it
# is the text that is there again. Without this, one reverted step stripped the
# badge off eighteen sections whose content was fully restored, and nothing in
# the log said so: the count went down and it read as progress.
RESTORING = {"put back", "restore", "revert", "undo"}


def whoami() -> str:
    """A name to put on an acceptance.

    Nothing here invents one. An acceptance signed "unknown" is worth exactly
    what `status: verified` was worth before, so the callers treat an empty
    answer as a reason to ask rather than a default to write.
    """
    for var in ("VERBA_WHO", "GIT_AUTHOR_NAME"):
        if os.environ.get(var, "").strip():
            return os.environ[var].strip()
    try:
        r = subprocess.run(["git", "config", "user.name"],
                           capture_output=True, text=True, timeout=4)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return os.environ.get("USER", "").strip()


def latest_capture(root: Path | str) -> str:
    """The run a person would have been looking at."""
    runs = sorted(p.name for p in (Path(root) / "capture").glob("*")
                  if (p / "inventory.json").exists())
    return runs[-1] if runs else ""


def is_attested(meta: dict) -> bool:
    """Does this section's claim carry its evidence?"""
    return bool(str(meta.get("verified_by", "") or "").strip()
                and str(meta.get("verified_against", "") or "").strip())


def attest(meta: dict, who: str, capture: str, when: str) -> dict:
    meta = dict(meta)
    meta["status"] = "verified"
    meta["last_verified"] = when
    meta["verified_by"] = who
    meta["verified_against"] = capture
    return meta


def demote(text: str, actor: str, action: str = "") -> str:
    """Drop a verified section back to review after a machine changed it.

    Text in, text out, and only the three lines that make the claim. Parsing
    the section and writing it back would reformat a file somebody is reading
    in a diff, over a change they did not make.
    """
    if actor not in MACHINE_ACTORS or action in RESTORING:
        return text
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    end = next((i for i, ln in enumerate(lines[1:], 1)
                if ln.strip() == "---"), None)
    if end is None:
        return text

    out, changed = [], False
    for i, line in enumerate(lines):
        if 0 < i < end:
            key = line.split(":", 1)[0].strip()
            if key == "status" and line.split(":", 1)[-1].strip() == "verified":
                out.append(line.split(":", 1)[0] + ": review\n")
                changed = True
                continue
            if key in ("verified_by", "verified_against"):
                changed = True
                continue        # the acceptance was of the previous text
        out.append(line)
    return "".join(out) if changed else text
