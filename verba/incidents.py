"""Failures, recorded well enough to be fixed.

A stack trace in a terminal that has since scrolled away is not a bug report.
Every failure is written here instead, with the context that makes it
actionable: what was being attempted, the state at the time, the traceback, and
where the surrounding code lives.

Two consumers:

* a person, reading `verba incidents`;
* a coding agent, given `incidents export`, which produces a self-contained
  brief with the traceback, the relevant source, and what was already tried.

Deliberately not self-modifying. A pipeline that edits its own source
unsupervised is a pipeline nobody can review, and this one already refuses to
change a document without approval. Rewriting itself unasked would be a stranger
thing to permit than that.
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .atomic import write_json

STORE = "review/incidents.json"
MAX_KEEP = 400


def _signature(where: str, kind: str, message: str) -> str:
    """Group repeats of the same fault, ignoring the parts that always differ."""
    import re
    core = re.sub(r"0x[0-9a-f]+|\d{4,}|/[\w./-]+/", "", message)[:160]
    return hashlib.sha256(f"{where}|{kind}|{core}".encode()).hexdigest()[:12]


@dataclass
class Incident:
    id: str
    signature: str
    at: str
    where: str                    # the operation, e.g. "capture supply.publishers.list"
    kind: str                     # exception class, or a domain label
    message: str
    traceback: str = ""
    context: dict = field(default_factory=dict)
    seen: int = 1
    last_at: str = ""
    resolved: bool = False
    resolution: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Incidents:
    root: Path
    items: dict = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> "Incidents":
        root = Path(root).resolve()
        path = root / STORE
        items = {}
        if path.exists():
            try:
                for d in json.loads(path.read_text(encoding="utf-8")):
                    items[d["signature"]] = Incident(**d)
            except Exception:
                items = {}
        return cls(root=root, items=items)

    def save(self):
        path = self.root / STORE
        path.parent.mkdir(parents=True, exist_ok=True)
        keep = sorted(self.items.values(), key=lambda i: i.last_at or i.at,
                      reverse=True)[:MAX_KEEP]
        write_json(path, [i.to_dict() for i in keep])

    # ------------------------------------------------------------------
    def record(self, where: str, exc: BaseException | None = None,
               message: str = "", context: dict | None = None) -> Incident:
        kind = type(exc).__name__ if exc else "reported"
        msg = message or (str(exc) if exc else "")
        sig = _signature(where, kind, msg)
        now = datetime.now().isoformat(timespec="seconds")

        existing = self.items.get(sig)
        if existing and not existing.resolved:
            existing.seen += 1
            existing.last_at = now
            existing.context = {**existing.context, **(context or {})}
            self.save()
            return existing

        tb = ""
        if exc is not None:
            tb = "".join(traceback.format_exception(
                type(exc), exc, exc.__traceback__))[-4000:]
        inc = Incident(
            id=f"{now.replace(':', '').replace('-', '')}-{sig}",
            signature=sig, at=now, last_at=now, where=where, kind=kind,
            message=msg[:600], traceback=tb, context=context or {},
        )
        self.items[sig] = inc
        self.save()
        return inc

    def resolve(self, signature: str, note: str = "") -> bool:
        inc = self.items.get(signature)
        if not inc:
            return False
        inc.resolved = True
        inc.resolution = note
        self.save()
        return True

    def open_items(self) -> list[Incident]:
        return sorted([i for i in self.items.values() if not i.resolved],
                      key=lambda i: (-i.seen, i.last_at), reverse=False)

    def summary(self) -> dict:
        opened = self.open_items()
        return {"open": len(opened), "total": len(self.items),
                "repeats": sum(i.seen for i in opened),
                "worst": opened[0].where if opened else None}

    # ------------------------------------------------------------------
    def brief(self, signature: str | None = None) -> str:
        """A self-contained brief for whoever is going to fix this.

        Includes the traceback and the source of the frames inside this project,
        so the reader does not have to go hunting for context that was already
        known at the moment of failure.
        """
        items = ([self.items[signature]] if signature and signature in self.items
                 else self.open_items())
        if not items:
            return "No open incidents."

        out = [
            "# verba incident brief",
            "",
            f"Generated {datetime.now().isoformat(timespec='seconds')}",
            f"Python {sys.version.split()[0]} on {platform.system()} "
            f"{platform.release()}",
            f"Project {self.root}",
            "",
            "Each incident below is a real failure recorded at the moment it "
            "happened. Fix the cause in the source, do not paper over the "
            "symptom, and keep the project's own rules: no em dashes, comments "
            "explain why rather than what.",
            "",
        ]
        for inc in items[:6]:
            out += [
                f"## {inc.where}",
                "",
                f"- signature: `{inc.signature}`",
                f"- seen {inc.seen} time(s), first {inc.at}, last {inc.last_at}",
                f"- {inc.kind}: {inc.message}",
                "",
            ]
            if inc.context:
                out += ["Context at the time:", "```json",
                        json.dumps(inc.context, indent=2, default=str)[:1200],
                        "```", ""]
            if inc.traceback:
                out += ["Traceback:", "```", inc.traceback[-2200:], "```", ""]
            for path, lo, hi in self._frames(inc.traceback):
                try:
                    lines = Path(path).read_text(encoding="utf-8").splitlines()
                except Exception:
                    continue
                snippet = "\n".join(
                    f"{n:>5}  {lines[n - 1]}"
                    for n in range(max(1, lo), min(len(lines), hi) + 1))
                rel = Path(path)
                try:
                    rel = rel.relative_to(self.root)
                except ValueError:
                    pass
                out += [f"Source `{rel}` around the failure:", "```python",
                        snippet, "```", ""]
        out += ["## How to close one",
                "",
                "After fixing, record it so the brief stops carrying it:",
                "",
                "```bash",
                "python3 -m verba incidents --resolve <signature> "
                "--note 'what changed'",
                "python3 tools/selftest.py",
                "```", ""]
        return "\n".join(out)

    def _frames(self, tb: str, span: int = 6):
        """Project source locations named in a traceback, innermost first."""
        import re
        out = []
        for m in re.finditer(r'File "([^"]+)", line (\d+)', tb or ""):
            path, line = m.group(1), int(m.group(2))
            if str(self.root) not in path or "/tools/" in path:
                continue
            out.append((path, line - span, line + span))
        return list(reversed(out))[:3]


def guard(incidents: "Incidents", where: str, context: dict | None = None):
    """Context manager that records whatever goes wrong, then re-raises."""
    class _Guard:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            if exc is not None:
                incidents.record(where, exc, context=context)
            return False
    return _Guard()
