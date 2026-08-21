"""Replace real entity names in screenshots with neutral placeholders.

Publisher names, partner names, account identifiers and email addresses appear
all over the platform UI and should not be shipped in documentation that goes to
other customers. Masking rewrites them in the page's DOM immediately before the
screenshot is taken. Nothing is submitted, so the platform never sees the
substitution: it exists only in the pixels.

A mapping is kept on disk so a given real value always becomes the same
placeholder, both across screens in one crawl and across crawls months apart.
Screenshots therefore stay consistent between revisions.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Applied in the browser. Returns the mapping it used so the caller can persist
# it and reuse it next time.
MASK_JS = r"""
(cfg) => {
  const map = Object.assign({}, cfg.map || {});
  const counters = Object.assign({}, cfg.counters || {});
  const keep = new Set((cfg.keep || []).map(s => s.toLowerCase()));
  const applied = [];

  const nextFor = (rule) => {
    counters[rule] = (counters[rule] || 0) + 1;
    return counters[rule];
  };
  const fill = (tpl, n) => tpl.replace(/\{n(?::0(\d+)d)?\}/g, (_, w) =>
    w ? String(n).padStart(parseInt(w, 10), '0') : String(n));

  const assign = (rule, original, tpl) => {
    const key = rule + ' ' + original;
    if (map[key] === undefined) {
      map[key] = fill(tpl, nextFor(rule));
      applied.push({ rule: rule, from: original, to: map[key] });
    }
    return map[key];
  };

  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const literalRules = (cfg.literals || []).map((r) => ({
    re: new RegExp(esc(r.match), r.case_sensitive === false ? 'gi' : 'g'),
    to: r.with
  }));
  const patternRules = (cfg.patterns || []).map((r) => ({
    re: new RegExp(r.pattern, r.flags || 'g'),
    to: r.with,
    name: r.name || 'pattern'
  }));

  // Names learned from table columns are reused everywhere else on the page.
  // A publisher masked in a list must also be masked in the breadcrumb, the
  // detail heading and any prose that happens to name it. Longest first, so a
  // name that contains another name cannot be half replaced.
  const learned = () => Object.keys(map)
    .filter((k) => k.startsWith('column:'))
    .map((k) => ({ from: k.slice(k.indexOf(' ') + 1), to: map[k] }))
    .filter((x) => x.from && x.from.length > 2)
    .sort((a, b) => b.from.length - a.from.length);

  const rewrite = (text) => {
    if (!text || !text.trim()) return text;
    let out = text;
    for (const r of literalRules) out = out.replace(r.re, () => r.to);
    for (const l of learned()) out = out.split(l.from).join(l.to);
    for (const r of patternRules) {
      out = out.replace(r.re, (m) =>
        keep.has(m.toLowerCase()) ? m : assign(r.name, m, r.to));
    }
    return out;
  };

  // 1. column masking: values under a named table header
  (cfg.columns || []).forEach((rule) => {
    document.querySelectorAll('table').forEach((table) => {
      const heads = Array.from(table.querySelectorAll('thead th, thead td'));
      const idx = heads.findIndex((h) =>
        (h.innerText || '').trim().toLowerCase() === rule.header.toLowerCase());
      if (idx < 0) return;
      table.querySelectorAll('tbody tr').forEach((tr) => {
        const cell = tr.children[idx];
        if (!cell) return;
        const original = (cell.innerText || '').trim();
        if (!original || keep.has(original.toLowerCase())) return;
        const label = 'column:' + (rule.as || rule.header.toLowerCase());
        cell.innerText = assign(label, original, rule.with);
      });
    });
  });

  // 2. text nodes everywhere else
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => {
      const p = n.parentElement;
      if (!p) return NodeFilter.FILTER_REJECT;
      const tag = p.tagName;
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT')
        return NodeFilter.FILTER_REJECT;
      return n.nodeValue && n.nodeValue.trim()
        ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    }
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((n) => {
    const next = rewrite(n.nodeValue);
    if (next !== n.nodeValue) n.nodeValue = next;
  });

  // 3. attributes and field values that render as visible text.
  // DOM only: nothing here is ever submitted back to the platform.
  document.querySelectorAll('input,textarea,[title],[aria-label],[alt],[placeholder]')
    .forEach((e) => {
      ['value', 'placeholder', 'title', 'alt', 'aria-label'].forEach((a) => {
        const v = a === 'value' ? e.value : e.getAttribute(a);
        if (typeof v !== 'string' || !v.trim()) return;
        const next = rewrite(v);
        if (next === v) return;
        if (a === 'value') e.value = next; else e.setAttribute(a, next);
      });
    });

  return { map: map, counters: counters, applied: applied };
}
"""


def _for_screen(columns: list, screen_id: str) -> list:
    """The column rules that apply to this screen.

    A NAME column means something different in each module: on a supply screen
    it is a publisher, on a demand screen a partner, on a list screen a list.
    One rule for all of them is how a table of demand partners came out labelled
    "Test Publisher". A rule can name the screens it is for, and the first
    matching one wins; a rule with no screens is the fallback.
    """
    out, seen = [], set()
    scoped = [c for c in columns if c.get("screens")]
    generic = [c for c in columns if not c.get("screens")]

    for rule in scoped:
        if not screen_id:
            continue
        if any(_matches(pat, screen_id) for pat in rule["screens"]):
            key = rule["header"].lower()
            if key not in seen:
                seen.add(key)
                out.append(rule)
    for rule in generic:
        key = rule["header"].lower()
        if key not in seen:
            seen.add(key)
            out.append(rule)
    return out


def _matches(pattern: str, screen_id: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(screen_id, pattern)


@dataclass
class Masker:
    enabled: bool = True
    literals: list = field(default_factory=list)
    patterns: list = field(default_factory=list)
    columns: list = field(default_factory=list)
    keep: list = field(default_factory=list)
    map: dict = field(default_factory=dict)
    counters: dict = field(default_factory=dict)
    map_path: Path | None = None
    applied: list = field(default_factory=list)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, config_path: Path, map_path: Path | None = None) -> "Masker":
        cfg = {}
        if Path(config_path).exists():
            cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        m = cls(
            enabled=bool(cfg.get("enabled", True)),
            literals=cfg.get("literals", []) or [],
            patterns=cfg.get("patterns", []) or [],
            columns=cfg.get("columns", []) or [],
            keep=cfg.get("keep", []) or [],
            map_path=Path(map_path) if map_path else None,
        )
        if m.map_path and m.map_path.exists():
            saved = json.loads(m.map_path.read_text(encoding="utf-8"))
            m.map = saved.get("map", {})
            m.counters = saved.get("counters", {})
        return m

    def config(self, screen_id: str = "") -> dict:
        return {"literals": self.literals, "patterns": self.patterns,
                "columns": _for_screen(self.columns, screen_id),
                "keep": self.keep,
                "map": self.map, "counters": self.counters}

    def active(self) -> bool:
        return bool(self.enabled and (self.literals or self.patterns or self.columns))

    # ------------------------------------------------------------------
    def apply(self, page, log=None, screen_id: str = "") -> list[dict]:
        """Mask the live DOM. Returns what was replaced on this page."""
        if not self.active():
            return []
        try:
            result = page.evaluate(MASK_JS, self.config(screen_id))
        except Exception as e:
            if log:
                log(f"    masking skipped: {e}")
            return []
        self.map = result.get("map", self.map)
        self.counters = result.get("counters", self.counters)
        new = result.get("applied", [])
        self.applied.extend(new)
        if log and new:
            preview = ", ".join(f"{a['from']} to {a['to']}" for a in new[:4])
            log(f"    masked {len(new)} new value(s): {preview}"
                f"{' and more' if len(new) > 4 else ''}")
        return new

    def save(self):
        if not self.map_path:
            return
        self.map_path.parent.mkdir(parents=True, exist_ok=True)
        self.map_path.write_text(
            json.dumps({"map": self.map, "counters": self.counters},
                       indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8")

    def summary(self) -> dict:
        """What masking did. `new_values` is the count people misread as zero:
        a crawl that reuses an established mapping learns nothing new while
        still masking every name on every page."""
        by_rule: dict[str, int] = {}
        for a in self.applied:
            by_rule[a["rule"]] = by_rule.get(a["rule"], 0) + 1
        return {"new_values": len(self.applied), "by_rule": by_rule,
                "known_values": len(self.map),
                "total_replacements": len(self.applied),
                "active": self.active()}

    def table(self) -> list[dict]:
        """The mapping, for display: real value on the left, placeholder right."""
        rows = []
        for key, value in sorted(self.map.items()):
            rule, _, original = key.partition(" ")
            rows.append({"rule": rule, "from": original, "to": value})
        return rows

    def scrub_text(self, text: str) -> str:
        """Apply the same mapping to text read off the page.

        The extracted inventory feeds drift detection and can end up quoted in
        the review queue, so it must not carry real names either.
        """
        if not text:
            return text
        out = text
        for rule in self.literals:
            flags = 0 if rule.get("case_sensitive", True) else re.I
            out = re.sub(re.escape(rule["match"]), rule["with"], out, flags=flags)
        for key, value in self.map.items():
            _, _, original = key.partition(" ")
            if original and original in out:
                out = out.replace(original, value)
        return out
