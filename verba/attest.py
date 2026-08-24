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
                  "tidy", "heal",
                  # A note is a person asking for something. The edit that
                  # answers it is still a model's, and a signature given before
                  # that edit was given to different text.
                  "note"}

# Undoing is not authoring. Putting a section back the way it was returns its
# acceptance along with its text, because the person accepted that text and it
# is the text that is there again. Without this, one reverted step stripped the
# badge off eighteen sections whose content was fully restored, and nothing in
# the log said so: the count went down and it read as progress.
RESTORING = {"put back", "restore", "revert", "undo", "baseline",
             # Signing is not authoring. An attestation records a check that
             # was just made against the text as it stands, so demoting on it
             # would undo the thing being written in the same breath.
             "accept", "verify"}


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


# Who did the checking. Both are real checks and the difference is worth
# recording, so a reader can tell one from the other and a person can look for
# the sections no person has read. What was never acceptable was a document
# claiming a check that nobody and nothing had made.
PERSON, LOOP = "person", "loop"


def attest(meta: dict, who: str, capture: str, when: str,
           kind: str = PERSON) -> dict:
    meta = dict(meta)
    meta["status"] = "verified"
    meta["last_verified"] = when
    meta["verified_by"] = who
    meta["verified_against"] = capture
    meta["verified_kind"] = kind
    return meta


def signed_by_a_person(meta: dict) -> bool:
    """A person read this one, rather than the loop checking it."""
    return is_attested(meta) and str(
        meta.get("verified_kind", PERSON) or PERSON) == PERSON


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


def signature(root: Path | str, section_id: str, meta: dict) -> dict:
    """Whether this section carries a signature, and if not, what happened.

    "review" on its own tells nobody anything. A section sitting in review with
    a verification date beside it and no explanation is the reader's problem to
    solve with no information: they can see something is wrong and not what,
    and the only control on the page marks it verified, which is the one thing
    they cannot responsibly do without knowing what changed.

    So the reason is read back out of History: who signed it last, and every
    machine change since. That is exactly what needs reading before signing
    again, and it is already recorded.
    """
    import json
    root = Path(root)
    signed = bool(meta.get("status") == "verified" and is_attested(meta))
    out = {
        "signed": signed,
        "by": str(meta.get("verified_by", "") or ""),
        "against": str(meta.get("verified_against", "") or ""),
        "when": str(meta.get("last_verified", "") or ""),
        "since": [],
        "ever": False,
    }
    log = root / ".verba" / "history" / "log.jsonl"
    if not log.exists():
        return out
    rows = []
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("section") == section_id:
            rows.append(r)

    last_signed = None
    for i, r in enumerate(rows):
        if r.get("actor") not in MACHINE_ACTORS and r.get("action") in (
                "accept", "verify"):
            last_signed, out["ever"] = i, True
    if last_signed is None:
        return out
    for r in rows[last_signed + 1:]:
        if r.get("actor") in MACHINE_ACTORS and r.get("action") not in RESTORING:
            out["since"].append({
                "at": r.get("at", ""), "actor": r.get("actor", ""),
                "action": r.get("action", ""), "note": (r.get("note") or "")[:200],
                "id": r.get("id", ""),
            })
    return out
