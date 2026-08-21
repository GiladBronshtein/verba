"""Change history for content and assets.

Every edit is recorded: who or what made it, when, why, and the full text before
and after. That makes three things possible which a documentation set needs and
rarely has: seeing what changed between any two points, understanding why a
sentence says what it says, and putting a section back the way it was.

Storage is deliberately plain. Each revision is a complete copy of the small
Markdown file, and the log is one JSON object per line. No database, no git
dependency, and nothing that auto-commits to a repository.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

STORE = ".verba/history"
LOG = "log.jsonl"

# Where a change came from. Recorded so a later reader can tell a considered
# human edit from a bulk mechanical one.
ACTORS = {
    "human": "edited by hand",
    "assist": "accepted from the writing assistant",
    "drift": "applied from the drift queue",
    "capture": "replaced from a capture",
    "system": "changed by the pipeline",
}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


@dataclass
class Revision:
    id: str
    section: str
    at: str
    actor: str
    action: str
    note: str = ""
    before: str = ""
    after: str = ""
    path: str = ""
    kind: str = "section"          # section | asset

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d.pop("before", None)
        d.pop("after", None)
        return d


@dataclass
class History:
    root: Path
    _log: Path = field(init=False)

    def __post_init__(self):
        # resolve: a relative root makes relative_to() fail on the absolute paths
        # the project hands over, which silently loses the record of a change
        self.root = Path(self.root).resolve()
        self.dir = self.root / STORE
        self.dir.mkdir(parents=True, exist_ok=True)
        self._log = self.dir / LOG

    # ------------------------------------------------------------------ write
    def record(self, section_id: str, path: Path, before: str | None,
               after: str, actor: str = "human", action: str = "edit",
               note: str = "") -> Revision | None:
        """Store one change. Returns None when nothing actually differs."""
        if before is not None and before == after:
            return None
        now = datetime.now()
        rev = Revision(
            id=f"{now.strftime('%Y%m%dT%H%M%S')}-{digest(after)}",
            section=section_id,
            at=now.isoformat(timespec="seconds"),
            actor=actor, action=action, note=note,
            path=_rel(path, self.root),
        )
        folder = self.dir / section_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{rev.id}.md").write_text(after, encoding="utf-8")
        if before is not None and not list(folder.glob("*.base.md")):
            # keep the state this section was in before its first tracked edit,
            # so the very first change is revertable too
            (folder / f"{rev.id}.base.md").write_text(before, encoding="utf-8")
        with self._log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rev.to_dict(), ensure_ascii=False) + "\n")
        return rev

    def record_asset(self, name: str, source: str, actor: str = "capture",
                     note: str = "") -> Revision:
        now = datetime.now()
        rev = Revision(
            id=f"{now.strftime('%Y%m%dT%H%M%S')}-{digest(name + source)}",
            section=name, at=now.isoformat(timespec="seconds"),
            actor=actor, action="replace image", note=note or source,
            kind="asset", path=source,
        )
        with self._log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rev.to_dict(), ensure_ascii=False) + "\n")
        return rev

    # ------------------------------------------------------------------ read
    def entries(self, section_id: str | None = None, limit: int = 200) -> list[dict]:
        if not self._log.exists():
            return []
        out = []
        for line in self._log.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if section_id and e.get("section") != section_id:
                continue
            out.append(e)
        return list(reversed(out))[:limit]

    def content(self, section_id: str, revision_id: str) -> str | None:
        f = self.dir / section_id / f"{revision_id}.md"
        return f.read_text(encoding="utf-8") if f.exists() else None

    def baseline(self, section_id: str) -> str | None:
        found = sorted((self.dir / section_id).glob("*.base.md")) \
            if (self.dir / section_id).exists() else []
        return found[0].read_text(encoding="utf-8") if found else None

    def previous(self, section_id: str, revision_id: str) -> str | None:
        """The content immediately before the given revision."""
        revs = [e for e in reversed(self.entries(section_id))
                if e.get("kind", "section") == "section"]
        ids = [e["id"] for e in revs]
        if revision_id not in ids:
            return None
        i = ids.index(revision_id)
        if i == 0:
            return self.baseline(section_id)
        return self.content(section_id, ids[i - 1])

    def restore(self, section_id: str, revision_id: str, target: Path,
                actor: str = "human") -> Revision | None:
        """Put a section back to an earlier revision, recording the restore."""
        text = self.content(section_id, revision_id)
        if text is None:
            raise FileNotFoundError(f"no revision {revision_id} for {section_id}")
        before = Path(target).read_text(encoding="utf-8") if Path(target).exists() else ""
        Path(target).write_text(text, encoding="utf-8")
        return self.record(section_id, target, before, text, actor=actor,
                           action="restore", note=f"restored {revision_id}")

    def stats(self) -> dict:
        entries = self.entries(limit=100000)
        by_actor: dict[str, int] = {}
        for e in entries:
            by_actor[e.get("actor", "?")] = by_actor.get(e.get("actor", "?"), 0) + 1
        sections = {e["section"] for e in entries if e.get("kind", "section") == "section"}
        return {"changes": len(entries), "sections_touched": len(sections),
                "by_actor": by_actor,
                "first": entries[-1]["at"] if entries else None,
                "last": entries[0]["at"] if entries else None}

    def seed(self, sections: dict) -> int:
        """Record a baseline for every section that has no history yet.

        Without this the first edit after installing history has nothing to
        revert to.
        """
        n = 0
        for sid, sec in sections.items():
            folder = self.dir / sid
            if folder.exists() and any(folder.glob("*.md")):
                continue
            text = sec.to_markdown()
            self.record(sid, sec.path, None, text, actor="system",
                        action="baseline", note="state when history began")
            n += 1
        return n


def _rel(path, root: Path) -> str:
    """A path relative to the project when possible, absolute otherwise.

    Never let a path outside the project abort the record: losing the audit
    trail is worse than storing a longer string.
    """
    if not path:
        return ""
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)
