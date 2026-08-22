"""What the writer has learned, and how it gets recalled.

The aim is a documentation set that gets more accurate every run rather than
merely more current. Three kinds of knowledge accumulate:

* **Decisions.** What was declined and why. Already binding: a rejected proposal
  is never silently re-made.
* **House vocabulary.** How this document actually names things, harvested from
  the sections themselves rather than prescribed. If thirty sections say
  "Targeting Conditions", the thirty-first should not say "targeting rules".
* **Accepted phrasing.** Text a person approved, which is the only real evidence
  of what good looks like here.

On retrieval: this is deliberately not a vector store. The whole corpus is
thirty-eight short sections and a few hundred decisions, which fits in a prompt
many times over. Embeddings would add a service, a schema and an approximate
recall step to a problem that exact lookup solves completely. If the corpus ever
outgrows that, the seam is `bundle_for()`: swap what it retrieves, leave every
caller alone.
"""
from __future__ import annotations

from .atomic import write_json
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

STORE = "review/knowledge.json"

# Words that carry no house meaning, so they never count as vocabulary.
STOP = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is",
    "are", "be", "this", "that", "it", "as", "by", "from", "at", "you", "your",
    "can", "will", "not", "if", "when", "which", "each", "all", "any", "into",
    "click", "opens", "shows", "used", "use", "set", "sets", "page", "screen",
}

TERM_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b")


@dataclass
class Knowledge:
    root: Path
    terms: dict = field(default_factory=dict)          # term -> count, sections
    phrasing: list = field(default_factory=list)       # approved examples
    updated: str = ""

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, root: Path) -> "Knowledge":
        root = Path(root).resolve()
        path = root / STORE
        if not path.exists():
            return cls(root=root)
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return cls(root=root)
        return cls(root=root, terms=d.get("terms", {}),
                   phrasing=d.get("phrasing", []), updated=d.get("updated", ""))

    def save(self):
        path = self.root / STORE
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, {
            "updated": datetime.now().isoformat(timespec="seconds"),
            "terms": self.terms, "phrasing": self.phrasing[-200:],
        })

    # ------------------------------------------------------------------
    def learn_vocabulary(self, project) -> int:
        """Harvest how this document names things, from the document itself."""
        counts: dict[str, dict] = {}
        for node in project.nodes:
            sec = node.section
            if sec is None:
                continue
            blob = [sec.title]
            for b in sec.blocks:
                blob.append(b.text or "")
                for it in b.items:
                    if isinstance(it, dict):
                        blob.extend(str(v) for v in it.values())
                    else:
                        blob.append(str(it))
            text = " ".join(blob)
            for m in TERM_RE.finditer(text):
                term = m.group(1).strip()
                if term.lower() in STOP or len(term) < 4:
                    continue
                if all(w.lower() in STOP for w in term.split()):
                    continue
                e = counts.setdefault(term, {"count": 0, "sections": []})
                e["count"] += 1
                if sec.id not in e["sections"]:
                    e["sections"].append(sec.id)
        # a term used in one place only is a phrase, not house vocabulary
        self.terms = {t: v for t, v in counts.items()
                      if v["count"] >= 3 or len(v["sections"]) >= 2}
        self.save()
        return len(self.terms)

    def record_accepted(self, section_id: str, task: str, text: str):
        """Keep a sample of text a person approved: evidence of house style."""
        sample = "\n".join(
            [ln for ln in text.splitlines()
             if ln.strip() and not ln.startswith(("---", "!", "```", "#"))][:6])
        if not sample:
            return
        self.phrasing.append({
            "section": section_id, "task": task,
            "at": datetime.now().isoformat(timespec="seconds"),
            "sample": sample[:600],
        })
        self.save()

    # ------------------------------------------------------------------
    def vocabulary_note(self, section_id: str, limit: int = 24) -> str:
        """The terms this document uses, weighted toward the ones in play here."""
        if not self.terms:
            return ""
        here = [t for t, v in self.terms.items() if section_id in v["sections"]]
        common = [t for t, _ in sorted(self.terms.items(),
                                       key=lambda kv: -kv[1]["count"])]
        chosen, seen = [], set()
        for t in here + common:
            if t not in seen:
                seen.add(t)
                chosen.append(t)
            if len(chosen) >= limit:
                break
        return ("Vocabulary this document already uses. Match it exactly rather "
                "than introducing a synonym:\n  " + ", ".join(chosen))

    def phrasing_note(self, section_id: str, limit: int = 2) -> str:
        mine = [p for p in reversed(self.phrasing) if p["section"] == section_id]
        others = [p for p in reversed(self.phrasing) if p["section"] != section_id]
        picked = (mine + others)[:limit]
        if not picked:
            return ""
        out = ["Text approved here before, as a guide to tone and shape:"]
        for p in picked:
            out.append(f"  from {p['section']}:")
            out.extend(f"    {ln}" for ln in p["sample"].splitlines()[:4])
        return "\n".join(out)

    def bundle_for(self, section_id: str, decisions=None) -> str:
        """Everything learned that bears on writing this section."""
        parts = []
        if decisions is not None:
            note = decisions.notes_for(section_id)
            if note:
                parts.append(note)
        try:
            from .design import Design
            note = Design.load(self.root).note_for_writer()
            if note:
                parts.append(note)
        except Exception:
            pass
        v = self.vocabulary_note(section_id)
        if v:
            parts.append(v)
        p = self.phrasing_note(section_id)
        if p:
            parts.append(p)
        return "\n\n".join(parts)

    def summary(self) -> dict:
        top = sorted(self.terms.items(), key=lambda kv: -kv[1]["count"])[:12]
        return {"terms": len(self.terms), "phrasing_samples": len(self.phrasing),
                "updated": self.updated,
                "top_terms": [{"term": t, "count": v["count"],
                               "sections": len(v["sections"])} for t, v in top]}
