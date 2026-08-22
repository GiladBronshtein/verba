"""What the product being documented actually is.

A crawler can prove that a control exists. It cannot tell you what the control
is *for*, what the company calls it, or which of two plausible readings is the
right one, and a writer who guesses at those produces confident, fluent, wrong
documentation. That knowledge has to come from a person, once, and then be
available to every later run.

So a project carries ``content/system.md``: a plain page describing the product,
its vocabulary and the rules that are true of it. It is handed to the model with
every writing task, alongside the evidence from the crawl. Nothing here is
generated and nothing here is inferred; it is the one part of the pipeline that
is purely what a person knows.

The engine used to have this hard-coded to one company's product, one sentence
deep, inside a prompt string. Which meant documenting a second product required
editing the source.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG = "content/system.md"

TEMPLATE = """---
product: {product}
vendor: {vendor}
audience: {audience}
---

## What this system is

{about}

## Who uses it

{audience_note}

## Vocabulary

The words this document uses, and the words it does not. The writer is held to
these: if the interface says one thing and the company says another, say which
wins here.

- **Term** : what it means, in one line.

## Rules that are true of this system

Things a screenshot cannot show. Inheritance, precedence, what happens when two
settings disagree, which fields are required and why.

- …

## Do not document

Anything here is deliberately out of scope, and the writer will leave it alone
rather than describing it from the evidence.

- Internal identifiers, API routes and developer-facing values.
"""


@dataclass
class System:
    """The project's description of the product it documents."""
    root: Path
    product: str = ""
    vendor: str = ""
    audience: str = "operator"
    body: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def exists(self) -> bool:
        return bool(self.body.strip())

    @property
    def words(self) -> int:
        return len(self.body.split())

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, root: Path | str = ".") -> "System":
        root = Path(root)
        path = root / CONFIG
        if not path.exists():
            return cls(root=root)
        raw = path.read_text(encoding="utf-8")
        meta, body = {}, raw
        m = re.match(r"^---\n(.*?)\n---\n?(.*)$", raw, re.S)
        if m:
            meta = yaml.safe_load(m.group(1)) or {}
            body = m.group(2)
        return cls(root=root, body=body.strip(), meta=meta,
                   product=str(meta.get("product", "") or ""),
                   vendor=str(meta.get("vendor", "") or ""),
                   audience=str(meta.get("audience", "operator") or "operator"))

    def write(self, product: str, vendor: str = "", audience: str = "operator",
              about: str = "", audience_note: str = "") -> Path:
        path = self.root / CONFIG
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TEMPLATE.format(
            product=product, vendor=vendor or product, audience=audience,
            about=about or f"{product} is the system this document describes. "
                           "Replace this paragraph with what it does and who it "
                           "does it for, in the terms the company itself uses.",
            audience_note=audience_note or
            f"Written for the {audience}: someone who operates the system rather "
            "than someone who builds it.",
        ), encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    def prompt_block(self) -> str:
        """What the model is told about this product, before any evidence.

        Deliberately verbatim. Summarising it here would be this module deciding
        which of a person's statements about their own product matter, which is
        exactly the judgement it is not in a position to make.
        """
        if not self.exists:
            return ("No description of this system has been written yet, so you "
                    "know nothing about it beyond the evidence below. Do not "
                    "infer purpose or meaning from a control's name: where the "
                    "evidence does not say what something is for, write "
                    "`TODO: describe this.` and move on.")
        head = f"You are writing the documentation for {self.product}."
        if self.vendor and self.vendor != self.product:
            head += f" It is made by {self.vendor}."
        return (f"{head}\n\nWhat follows is the product description its own team "
                f"wrote. It is authoritative: where it and your general knowledge "
                f"disagree, it wins.\n\n{self.body}")

    def summary(self) -> dict:
        return {"exists": self.exists, "product": self.product,
                "vendor": self.vendor, "audience": self.audience,
                "words": self.words, "path": CONFIG}
