"""Project configuration, profile resolution and the assembled document tree."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined, TemplateError

from .assets import AssetStore
from .model import (
    Block,
    Node,
    Section,
    build_outline,
    flatten,
    load_all_sections,
    outline_ids,
    prune_outline,
)

CONTENT_DIR = "content"


class ProfileError(RuntimeError):
    pass


@dataclass
class Profile:
    """A rendering variant: vocabulary, branding and section visibility.

    Genericisation lives here. Section text refers to ``{{ operator.name }}``
    rather than to a customer, so one content tree renders both a neutral
    product manual and a customer-branded edition.
    """
    name: str
    vars: dict = field(default_factory=dict)
    title_suffix: str = ""
    audience: str = "operator"
    include: list | None = None
    exclude: list = field(default_factory=list)
    # An edition that names no customer. The rules hold it to that, using the
    # operator names the *other* editions declare, so the list of forbidden
    # words is derived rather than typed into the linter, which is where one
    # company's customer name used to live.
    neutral: bool = False

    @classmethod
    def load(cls, path: Path) -> "Profile":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        # What an edition carries is declared here rather than scattered across
        # section files, so "what is in the customer edition" is one list a
        # person can read, and changing it is one edit rather than thirty-eight.
        picks = data.get("sections") or {}
        chosen = picks.get("include")
        return cls(
            name=data.get("name", Path(path).stem),
            vars=data.get("vars", {}) or {},
            title_suffix=data.get("title_suffix", "") or "",
            audience=data.get("audience", "operator"),
            include=[str(s) for s in chosen] if chosen else None,
            exclude=[str(s) for s in (picks.get("exclude") or [])],
            neutral=bool(data.get("neutral",
                                  data.get("name", Path(path).stem)
                                  in ("generic", "default", "neutral"))),
        )

    def carries(self, section_id: str, declared: list | None = None) -> bool:
        """Is this section part of this edition, judged on its own?

        Ignores the outline, so it answers for a section in isolation. A parent
        kept only because a child survived is a question about the tree, and
        `prune_outline` is what answers that.
        """
        if section_id in self.exclude:
            return False
        if declared is not None and self.name not in declared:
            return False
        return self.include is None or section_id in self.include


@dataclass
class Project:
    root: Path
    config: dict
    sections: dict[str, Section]
    profile: Profile
    assets: AssetStore
    outline: list[Node] = field(default_factory=list)
    # Every id doc.yaml names, whether or not this edition carries it. Without
    # this, dropping a chapter from one edition makes its sections look like
    # files someone forgot to wire up, and the rules report a decision as a
    # mistake.
    listed: set = field(default_factory=set)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, root: Path | str = ".", profile: str | None = None) -> "Project":
        root = Path(root).resolve()
        content = root / CONTENT_DIR
        cfg_path = content / "doc.yaml"
        if not cfg_path.exists():
            raise FileNotFoundError(f"missing {cfg_path}")
        config = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        prof_name = profile or config.get("defaults", {}).get("profile", "generic")
        prof_path = content / "profiles" / f"{prof_name}.yaml"
        if not prof_path.exists():
            raise ProfileError(f"unknown profile {prof_name!r} ({prof_path} not found)")
        prof = Profile.load(prof_path)
        sections = load_all_sections(content / "sections")
        assets = AssetStore(content / "assets")
        proj = cls(root=root, config=config, sections=sections, profile=prof, assets=assets)
        proj.listed = set(outline_ids(config.get("outline", [])))
        kept = prune_outline(config.get("outline", []), sections, prof)
        proj.outline = build_outline(kept, sections)
        return proj

    # ------------------------------------------------------------------
    @property
    def nodes(self) -> list[Node]:
        return flatten(self.outline)

    @property
    def rendered_sections(self) -> list[Section]:
        return [n.section for n in self.nodes if n.section is not None]

    def tenant_terms(self) -> list[str]:
        """Names a neutral edition must not contain.

        Read off the other editions rather than listed here: whatever the
        customer edition calls its operator is exactly the word the neutral one
        must never print. Extra terms can be named under `lint.tenant_terms` in
        doc.yaml for anything the profiles do not cover, such as a product name.
        """
        terms: list[str] = []
        for path in sorted((self.root / CONTENT_DIR / "profiles").glob("*.yaml")):
            other = Profile.load(path)
            if other.neutral or other.name == self.profile.name:
                continue
            name = ((other.vars.get("operator") or {}).get("name") or "").strip()
            if name and len(name) > 2:
                terms.append(name)
        terms += [str(x) for x in
                  ((self.config.get("lint") or {}).get("tenant_terms") or [])]
        out, seen = [], set()
        for term in terms:
            for variant in (term, term.lower(), f"{term}'s"):
                if variant.lower() not in seen:
                    seen.add(variant.lower())
                    out.append(variant)
        return out

    def orphans(self) -> list[str]:
        """Section files the outline never names, in any edition."""
        return sorted(set(self.sections) - self.listed)

    def excluded(self) -> list[str]:
        """What this edition leaves out, in document order.

        A deliberate omission, so it is reported as a fact about the edition
        rather than as a finding against the document.
        """
        shipping = {n.id for n in self.nodes}
        return [sid for sid in outline_ids(self.config.get("outline", []))
                if sid not in shipping]

    def missing(self) -> list[str]:
        return sorted(n.id for n in self.nodes if n.section is None)

    # ------------------------------------------------------------------
    def context(self) -> dict:
        ctx: dict[str, Any] = {}
        ctx.update(self.config.get("vars", {}) or {})
        ctx.update(self.profile.vars)
        ctx.setdefault("product", self.config.get("product", {}))
        ctx.setdefault("document", self.config.get("document", {}))
        ctx["profile"] = self.profile.name
        ctx["today"] = date.today().isoformat()
        return ctx

    def substitute(self, text: str) -> str:
        """Resolve profile variables in one string.

        StrictUndefined turns a typo in a variable name into a build failure
        rather than a silently blank word in a shipped document.
        """
        if not text or "{" not in text:
            return text
        env = Environment(undefined=StrictUndefined, autoescape=False)
        try:
            return env.from_string(text).render(**self.context())
        except TemplateError as e:
            raise ProfileError(
                f"profile {self.profile.name!r} cannot resolve: {text[:80]!r} ({e})") from e

    def resolve_block(self, block: Block) -> Block:
        b = Block(block.kind, self.substitute(block.text), attrs=dict(block.attrs))
        items = []
        for it in block.items:
            if isinstance(it, dict):
                items.append({k: (self.substitute(v) if isinstance(v, str) else v)
                              for k, v in it.items()})
            else:
                items.append(self.substitute(str(it)))
        b.items = items
        for k in ("caption", "label"):
            if k in b.attrs and isinstance(b.attrs[k], str):
                b.attrs[k] = self.substitute(b.attrs[k])
        return b

    def resolved_blocks(self, section: Section) -> list[Block]:
        return [self.resolve_block(b) for b in section.blocks]

    # ------------------------------------------------------------------
    def title(self) -> str:
        doc = self.config.get("document", {})
        base = self.substitute(doc.get("title", "Technical Documentation"))
        return f"{base}{self.profile.title_suffix}"

    def asset_path(self, name: str) -> Path:
        return self.assets.path_for(name)
