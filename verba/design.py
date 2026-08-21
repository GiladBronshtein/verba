"""The design memory: what was decided, why, and what holds us to it.

The content side of this system already remembers. House vocabulary, accepted
phrasing and every approve or decline with its reason are fed back to the writer
on each task, so a judgement made once is not quietly undone.

Nothing did that for design. How the document and the console look and behave
lived as prose in TECHNICAL.md, and prose is not read by anything: the same
mistake can be made twice, and was. This is the same idea applied to the other
half of the work.

The distinction that matters is between a note and a memory. A note is written
and forgotten. Every entry here names what enforces it, and `check()` holds the
project against the ones that can be checked mechanically. An entry that nothing
reads belongs in TECHNICAL.md, not in `content/design.yaml`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

CONFIG = "content/design.yaml"

# Emoji ranges, for the rule that says marks are drawn rather than typed.
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF←-⇿]")


@dataclass
class Decision:
    id: str
    area: str
    decided: str
    because: str = ""
    rule: str = ""
    enforced_by: str = ""
    added: str = ""

    @property
    def held_by(self) -> str:
        if self.rule:
            return f"lint {self.rule}"
        if self.enforced_by:
            return self.enforced_by
        return "nothing yet"


@dataclass
class Design:
    root: Path
    tokens: dict = field(default_factory=dict)
    decisions: list = field(default_factory=list)
    traps: list = field(default_factory=list)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, root: Path | str = ".") -> "Design":
        root = Path(root)
        path = root / CONFIG
        raw = {}
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            root=root,
            tokens=raw.get("tokens") or {},
            decisions=[Decision(**d) for d in (raw.get("decisions") or [])],
            traps=raw.get("traps") or [],
        )

    def token(self, name: str, fallback=None):
        return self.tokens.get(name, fallback)

    def by_area(self) -> dict:
        out: dict[str, list] = {}
        for d in self.decisions:
            out.setdefault(d.area, []).append(d)
        return out

    def find(self, needle: str) -> list[Decision]:
        n = needle.lower()
        return [d for d in self.decisions
                if n in d.id.lower() or n in d.area.lower()
                or n in d.decided.lower() or n in d.because.lower()]

    # ------------------------------------------------------------------
    def add(self, area: str, decided: str, because: str,
            rule: str = "", enforced_by: str = "") -> Decision:
        """Record a decision, keeping the file's comments and ordering."""
        slug = re.sub(r"[^a-z0-9]+", "-", decided.lower())[:44].strip("-")
        d = Decision(id=slug, area=area, decided=decided.strip(),
                     because=because.strip(), rule=rule,
                     enforced_by=enforced_by, added=date.today().isoformat())
        path = self.root / CONFIG
        text = path.read_text(encoding="utf-8")
        entry = [f"\n  - id: {d.id}",
                 f"    area: {d.area}",
                 f"    decided: {_scalar(d.decided)}",
                 f"    because: {_scalar(d.because)}"]
        if rule:
            entry.append(f"    rule: {rule}")
        if enforced_by:
            entry.append(f"    enforced_by: {enforced_by}")
        entry.append(f"    added: {d.added}")

        marker = "\ntraps:"
        block = "\n".join(entry) + "\n"
        if marker in text:
            text = text.replace(marker, block + marker, 1)
        else:
            text += block
        path.write_text(text, encoding="utf-8")
        self.decisions.append(d)
        return d

    # ------------------------------------------------------------------
    def check(self, project) -> list[dict]:
        """Hold the project against the decisions that can be checked.

        Returns findings shaped like lint's, so `lint()` can fold them in and a
        design decision blocks a build exactly as a content rule does.
        """
        out: list[dict] = []
        out += self._check_marks(project)
        out += self._check_console_type()
        out += self._check_dialogs()
        return out

    # -- DESIGN-01: marks are drawn, not typed --------------------------
    def _check_marks(self, project) -> list[dict]:
        if not self._has("marks-are-drawn"):
            return []
        from .glyphs import for_emoji
        out = []
        for node in project.nodes:
            sec = node.section
            if sec is None or not sec.icon:
                continue
            if EMOJI.search(sec.icon) and not for_emoji(sec.icon):
                out.append({
                    "rule": "DESIGN-01", "level": "warning",
                    "section": f"{node.number} {sec.id}",
                    "message": f"no drawn mark for {sec.icon}, so it prints as an emoji",
                    "detail": "add it to EMOJI in verba/glyphs.py, or use a "
                              "mark that has one"})
        return out

    # -- DESIGN-02: the type floor in the console ------------------------
    def _check_console_type(self) -> list[dict]:
        floor = float(self.token("type_floor_px", 12))
        css = self.root / "verba" / "console" / "static" / "app.css"
        if not css.exists():
            return []
        out = []
        for i, line in enumerate(css.read_text(encoding="utf-8").splitlines(), 1):
            for m in re.finditer(r"font-size:\s*([\d.]+)px", line):
                if float(m.group(1)) < floor:
                    out.append({
                        "rule": "DESIGN-02", "level": "warning", "section": "",
                        "message": f"console text below the {floor:g}px floor: "
                                   f"{m.group(1)}px",
                        "detail": f"app.css:{i}"})
        return out

    # -- DESIGN-03: no browser dialogs -----------------------------------
    def _check_dialogs(self) -> list[dict]:
        if not self._has("no-browser-dialogs"):
            return []
        js = self.root / "verba" / "console" / "static" / "app.js"
        if not js.exists():
            return []
        out = []
        src = js.read_text(encoding="utf-8")
        # strip comments so the rule's own explanation does not trip it
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        src = re.sub(r"^\s*//.*$", "", src, flags=re.M)
        for call in ("confirm(", "alert(", "prompt("):
            for m in re.finditer(rf"(?<![.\w]){re.escape(call)}", src):
                line = src[:m.start()].count("\n") + 1
                out.append({
                    "rule": "DESIGN-03", "level": "error", "section": "",
                    "message": f"a browser dialog is used: {call})",
                    "detail": f"app.js:{line}. use modal() or ask()"})
        return out

    def _has(self, decision_id: str) -> bool:
        return any(d.id == decision_id for d in self.decisions)

    # ------------------------------------------------------------------
    def note_for_writer(self) -> str:
        """The decisions a person writing a section needs to obey."""
        relevant = [d for d in self.decisions if d.area in ("content", "typography")]
        if not relevant:
            return ""
        lines = ["Design decisions that apply to this document. These were made "
                 "deliberately and must be respected:"]
        for d in relevant:
            lines.append(f"  - {d.decided.strip()}")
        return "\n".join(lines)

    def summary(self) -> dict:
        return {"decisions": len(self.decisions),
                "areas": sorted({d.area for d in self.decisions}),
                "traps": len(self.traps),
                "unenforced": [d.id for d in self.decisions if d.held_by == "nothing yet"]}


def _scalar(value: str) -> str:
    """Quote a value that YAML would otherwise misread.

    A `#` inside an unquoted value starts a comment and silently truncates it,
    which is how a colour reference became half a sentence.
    """
    if any(c in value for c in "#:{}[]&*!|>'\"%@`") or value.strip() != value:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value
