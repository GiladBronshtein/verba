#!/usr/bin/env python3
"""What the rules currently say about a known set of documents.

A rule's firing condition can be narrowed by one person in one commit, and the
list of findings gets shorter, and it looks like progress. It is the move
always available when a list will not empty, it always works, and doing it four
times leaves a rule engine that measures nothing.

It happened here. Three rules were narrowed in one afternoon and fourteen
findings disappeared. Each narrowing was argued from evidence and I still think
each was right, but nothing in the repository would have objected if they had
not been, and nothing recorded what stopped being reported.

So the corpus is checked in. Change a rule and this prints exactly which
findings stop and start, on every document it knows about, and refuses until
the baseline is updated in the same commit where a reviewer can see both halves
of the trade.

    python3 tools/rule_baseline.py            compare, exit 1 on drift
    python3 tools/rule_baseline.py --write    accept the new state
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASELINE = ROOT / "tools" / "rule-baseline.json"

# Documents the rules are held against. A project added here is a project whose
# findings cannot change by accident.
CORPUS = {"meridian": ROOT / "examples" / "meridian-docs"}


def counts(root: Path) -> dict:
    from verba.lint import lint
    from verba.project import Project
    return dict(Counter(f"{f.rule}:{f.level}" for f in lint(Project.load(root))))


def measure() -> dict:
    return {name: counts(path) for name, path in sorted(CORPUS.items())
            if (path / "content" / "doc.yaml").exists()}


def main() -> int:
    now = measure()
    if "--write" in sys.argv:
        BASELINE.write_text(json.dumps(now, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
        total = sum(sum(v.values()) for v in now.values())
        print(f"baseline written: {len(now)} document(s), {total} finding(s)")
        return 0

    if not BASELINE.exists():
        print("no baseline yet. Write one: python3 tools/rule_baseline.py --write")
        return 1

    was = json.loads(BASELINE.read_text(encoding="utf-8"))
    drift = []
    for doc in sorted(set(was) | set(now)):
        a, b = was.get(doc, {}), now.get(doc, {})
        for key in sorted(set(a) | set(b)):
            if a.get(key, 0) != b.get(key, 0):
                drift.append(f"  {doc:10} {key:18} {a.get(key, 0)} -> {b.get(key, 0)}")

    if not drift:
        total = sum(sum(v.values()) for v in now.values())
        print(f"rules unchanged against the corpus "
              f"({len(now)} document(s), {total} finding(s))")
        return 0

    print("the rules now say something different about the corpus:\n")
    print("\n".join(drift))
    print("\nIf that is the intended trade, record it in the same commit:")
    print("  python3 tools/rule_baseline.py --write")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
