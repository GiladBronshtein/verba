"""How much the loop is allowed to ask for, and what it asked for.

Every step in the loop that needs judgement calls a model, and there are
twenty-one such call sites. On a small document that is a handful of calls. On
a large one it is a call per section per round plus a vision call per picture,
and nothing in the engine had any idea how many that was or what it cost.
Somebody would find out from an invoice.

A run now has a ceiling and keeps a tally. The ceiling is deliberately generous
and deliberately present: its job is not to save money on a normal run, it is
to make a runaway stop and say so instead of continuing quietly until somebody
notices in a different system entirely.

Tokens are counted where the backend reports them and estimated where it does
not. An estimate that is roughly right and visible beats an exact number nobody
ever sees.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .atomic import write_json

LEDGER = "review/model-usage.json"

# Enough for a full pass over a large document, and far below the point where
# a loop stuck in a circle would run all night.
DEFAULT_CALLS = 400


class OverBudget(RuntimeError):
    pass


@dataclass
class Budget:
    """One run's allowance, and what it actually spent."""
    limit: int = DEFAULT_CALLS
    calls: int = 0
    prompt_chars: int = 0
    reply_chars: int = 0
    images: int = 0
    by_task: dict = field(default_factory=dict)
    started: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @classmethod
    def for_run(cls, limit: int | None = None) -> "Budget":
        given = limit if limit is not None else os.environ.get("VERBA_MODEL_CALLS")
        try:
            n = int(given) if given not in (None, "") else DEFAULT_CALLS
        except (TypeError, ValueError):
            n = DEFAULT_CALLS
        return cls(limit=max(1, n))

    def spend(self, task: str, prompt: str = "", reply: str = "",
              images: int = 0) -> None:
        self.calls += 1
        self.prompt_chars += len(prompt or "")
        self.reply_chars += len(reply or "")
        self.images += images
        self.by_task[task] = self.by_task.get(task, 0) + 1

    def check(self, task: str) -> None:
        if self.calls >= self.limit:
            raise OverBudget(
                f"this run has asked the model {self.calls} times, which is its "
                f"limit. Nothing is wrong with the document; something is wrong "
                f"with the loop, or the document is bigger than the default "
                f"allows. Raise it with VERBA_MODEL_CALLS if it is the second.")

    # -- reporting -------------------------------------------------------
    def tokens(self) -> int:
        """Roughly. Four characters to a token is close enough to be useful."""
        return (self.prompt_chars + self.reply_chars) // 4 + self.images * 1500

    def summary(self) -> str:
        if not self.calls:
            return "the model was not needed"
        worst = sorted(self.by_task.items(), key=lambda kv: -kv[1])[:3]
        where = ", ".join(f"{k} {v}" for k, v in worst)
        return (f"{self.calls} model call(s) of {self.limit} allowed, "
                f"about {self.tokens():,} tokens"
                + (f", {self.images} picture(s)" if self.images else "")
                + (f" ({where})" if where else ""))

    def record(self, root: Path | str) -> None:
        """Append this run to the ledger, so cost has a history."""
        path = Path(root) / LEDGER
        try:
            past = json.loads(path.read_text(encoding="utf-8")).get("runs", [])
        except Exception:
            past = []
        past.append({
            "at": self.started, "calls": self.calls, "limit": self.limit,
            "tokens": self.tokens(), "images": self.images,
            "by_task": dict(sorted(self.by_task.items())),
        })
        write_json(path, {"runs": past[-200:]})
