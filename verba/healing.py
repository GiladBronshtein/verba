"""Self-healing selectors: the model looks at the live page and repairs the crawl.

When a step or an extraction stops resolving, the usual outcome is a failed
crawl and a person hand-editing `screens.yaml` against devtools. This does that
job instead: it takes a structured snapshot of what the page actually offers,
asks the model for a replacement selector, and then *verifies the answer in the
page before believing it*. Only a selector that resolves is ever proposed.

Nothing is written automatically. A repair is a proposal, reviewed like any
other change, because a selector that resolves is not necessarily the right one.

This is the same capability the Playwright MCP server gives an agent during a
conversation, except it lives inside the pipeline, so it works on a schedule and
in the Dock app with nobody watching.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# What the model is shown. Deliberately structured rather than raw HTML: a
# production page is far too large, and most of it is irrelevant to picking a
# selector.
SNAPSHOT_JS = r"""
() => {
  const vis = (e) => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const txt = (e) => (e.getAttribute('aria-label') || e.innerText || e.value ||
                      e.placeholder || '').replace(/\s+/g, ' ').trim().slice(0, 60);
  const describe = (e) => {
    const id = e.id && !/^[_:]?R[_a-z0-9]*$/i.test(e.id) ? '#' + e.id : '';
    const cls = [...e.classList].filter(c => !/^(Mui[A-Za-z]+-)?(root|colorPrimary)$/.test(c))
      .slice(0, 3).map(c => '.' + c).join('');
    const role = e.getAttribute('role') ? `[role=${e.getAttribute('role')}]` : '';
    const ph = e.getAttribute('placeholder') ? `[placeholder="${e.getAttribute('placeholder')}"]` : '';
    const ac = e.getAttribute('autocomplete') ? `[autocomplete="${e.getAttribute('autocomplete')}"]` : '';
    const type = e.getAttribute('type') ? `[type=${e.getAttribute('type')}]` : '';
    return { tag: e.tagName.toLowerCase(), id, cls, role, ph, ac, type, text: txt(e) };
  };
  const grab = (sel, cap) => [...document.querySelectorAll(sel)]
    .filter(vis).slice(0, cap).map(describe);

  return {
    url: location.href,
    title: document.title,
    headings: grab('h1,h2,h3,h4', 12).map(d => d.text).filter(Boolean),
    tabs: grab('[role=tab], .MuiTab-root', 14),
    buttons: grab('button, [role=button]', 26),
    links: grab('a[href]', 18),
    inputs: grab('input, textarea, select, [role=combobox], [role=switch]', 26),
    tableHeaders: grab('table thead th, [role=columnheader]', 16).map(d => d.text),
    landmarks: grab('nav, aside, main, header, [role=navigation]', 8),
  };
}
"""

SYSTEM = """You repair CSS selectors for a documentation crawler that drives a real
browser over a Material UI application.

Rules:
- Answer with JSON only. No prose, no code fence.
- Prefer stable hooks in this order: [role=...], [autocomplete=...],
  [placeholder="..."], :has-text("..."), semantic tags. Then MUI component
  classes. Never use an id that looks generated (Material UI regenerates them
  on every render), and never use a positional nth-child unless nothing else
  identifies the element.
- A selector must match what was asked for and nothing else. Matching more
  elements is not better.
- If the snapshot does not contain anything that plausibly satisfies the
  request, say so rather than inventing a selector.

Reply shape:
{"selector": "<css or playwright selector>", "confidence": 0.0-1.0,
 "reasoning": "<one short sentence>", "possible": true|false}
"""


@dataclass
class Repair:
    screen: str
    kind: str                 # step | extract | element
    key: str                  # which step/extraction this is
    old: str
    new: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    verified: bool = False
    matches: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Healer:
    """Proposes selector repairs, verified against the live page."""
    enabled: bool = True
    repairs: list = field(default_factory=list)
    attempts: int = 0
    max_attempts: int = 12

    def snapshot(self, page) -> dict:
        try:
            return page.evaluate(SNAPSHOT_JS)
        except Exception as e:
            return {"error": str(e)[:200]}

    # ------------------------------------------------------------------
    def _ask(self, want: str, old: str, snap: dict, log=None) -> dict:
        from .console.assist import run_model

        prompt = (
            f"The crawler needs to find: {want}\n"
            f"The selector that stopped working: {old!r}\n\n"
            f"This is what the page currently offers:\n"
            f"{json.dumps(snap, indent=1)[:6000]}\n\n"
            f"Give the replacement selector."
        )
        result = run_model(prompt, system=SYSTEM, timeout=90, log=None)
        if not result.ok:
            return {"possible": False, "reasoning": result.error}
        text = (result.output or "").strip()
        if text.startswith("```"):
            text = "\n".join(text.splitlines()[1:-1])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"possible": False, "reasoning": f"unparseable reply: {text[:120]}"}

    def _verify(self, page, selector: str, expect_one: bool) -> tuple[bool, int, str]:
        """Believe a selector only once the page agrees it resolves."""
        try:
            n = page.locator(selector).count()
        except Exception as e:
            return False, 0, f"invalid selector: {str(e)[:120]}"
        if n == 0:
            return False, 0, "matches nothing"
        if expect_one:
            try:
                page.locator(selector).first.wait_for(state="visible", timeout=3000)
            except Exception:
                return False, n, "matches but nothing visible"
        return True, n, ""

    # ------------------------------------------------------------------
    def heal(self, page, screen_id: str, kind: str, key: str, old: str,
             want: str, log=None) -> Repair | None:
        emit = log or (lambda *_: None)
        if not self.enabled or self.attempts >= self.max_attempts:
            return None
        self.attempts += 1

        rep = Repair(screen=screen_id, kind=kind, key=key, old=old)
        emit(f"    healing: looking for {want}")
        snap = self.snapshot(page)
        if snap.get("error"):
            rep.error = snap["error"]
            self.repairs.append(rep)
            return rep

        answer = self._ask(want, old, snap, log=emit)
        if not answer.get("possible", True) or not answer.get("selector"):
            rep.error = answer.get("reasoning", "no candidate offered")
            emit(f"    healing: no repair ({rep.error[:80]})")
            self.repairs.append(rep)
            return rep

        rep.new = str(answer["selector"])
        rep.confidence = float(answer.get("confidence", 0) or 0)
        rep.reasoning = str(answer.get("reasoning", ""))[:200]

        ok, n, why = self._verify(page, rep.new, expect_one=(kind != "extract"))
        rep.verified, rep.matches = ok, n
        if not ok:
            rep.error = why
            emit(f"    healing: proposed {rep.new!r} but it {why}")
        else:
            emit(f"    healing: {rep.new!r} resolves, {n} match(es), "
                 f"confidence {rep.confidence:.0%}")
        self.repairs.append(rep)
        return rep

    # ------------------------------------------------------------------
    def proposals(self) -> list[dict]:
        return [r.to_dict() for r in self.repairs if r.verified]

    def summary(self) -> dict:
        good = [r for r in self.repairs if r.verified]
        return {"attempted": len(self.repairs), "verified": len(good),
                "screens": sorted({r.screen for r in good})}

    def save(self, path: Path):
        if not self.repairs:
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps([r.to_dict() for r in self.repairs], indent=2), encoding="utf-8")


def apply_repairs(screens_path: Path, repairs: list[dict]) -> list[str]:
    """Write accepted repairs into the screen registry.

    Edits the YAML text rather than reserialising it, so the file's comments and
    ordering survive: the registry is meant to be read by people.
    """
    text = Path(screens_path).read_text(encoding="utf-8")
    applied = []
    for r in repairs:
        old, new = r.get("old", ""), r.get("new", "")
        if not old or not new or old not in text:
            continue
        for quoted in (f'"{old}"', f"'{old}'", old):
            if quoted in text:
                repl = f'"{new}"' if quoted.startswith('"') else (
                    f"'{new}'" if quoted.startswith("'") else new)
                text = text.replace(quoted, repl, 1)
                applied.append(f"{r.get('screen')}.{r.get('key')}: {old} -> {new}")
                break
    if applied:
        Path(screens_path).write_text(text, encoding="utf-8")
    return applied
