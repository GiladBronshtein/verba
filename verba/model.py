"""Content model: typed blocks, section files, outline tree.

A section is one Markdown file with YAML front matter. The body uses a small,
fixed set of conventions that map 1:1 onto renderable block types, so the same
source produces DOCX, HTML and a drift-checkable inventory.

Block syntax
------------
    #### Heading            -> heading (level from hash count, relative)
    plain paragraph         -> paragraph
    - item                  -> bullets
    1. item                 -> steps
    > [!Label] text         -> note (callout box)
    ![caption](file.png)    -> screenshot   (optional " =14cm" width suffix)
    ```fields  ... ```      -> fields   (YAML list: field/type/required/description)
    ```actions ... ```      -> actions  (YAML list: action/description)
    ```columns ... ```      -> columns  (YAML list: column/description)
    ```terms   ... ```      -> terms    (YAML list: term/definition)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Iterable

import yaml

BLOCK_LANGS = {"fields", "actions", "columns", "terms"}

# Key that carries the human label for each structured block type.
LABEL_KEY = {
    "fields": "field",
    "actions": "action",
    "columns": "column",
    "terms": "term",
}

STATUSES = ("draft", "review", "verified", "stale")


# ---------------------------------------------------------------- blocks


@dataclass
class Block:
    kind: str
    text: str = ""
    items: list = dc_field(default_factory=list)
    attrs: dict = dc_field(default_factory=dict)

    def labels(self) -> list[str]:
        """Human labels this block declares (used for drift comparison)."""
        key = LABEL_KEY.get(self.kind)
        if not key:
            return []
        out = []
        for it in self.items:
            if isinstance(it, dict) and it.get(key):
                out.append(str(it[key]))
        return out

    def to_markdown(self, base_level: int = 3) -> str:
        k = self.kind
        if k == "heading":
            lvl = int(self.attrs.get("level", base_level))
            icon = self.attrs.get("icon", "")
            title = f"{icon} {self.text}".strip()
            return f"{'#' * lvl} {title}"
        if k == "paragraph":
            return self.text
        if k == "bullets":
            return "\n".join(f"- {i}" for i in self.items)
        if k == "steps":
            return "\n".join(f"{n}. {i}" for n, i in enumerate(self.items, 1))
        if k == "note":
            label = self.attrs.get("label", "Note")
            body = self.text.replace("\n", " ")
            return f"> [!{label}] {body}"
        if k == "screenshot":
            cap = self.attrs.get("caption", "")
            width = self.attrs.get("width_cm")
            suffix = f" ={width}cm" if width else ""
            return f"![{cap}]({self.attrs.get('file','')}{suffix})"
        if k in BLOCK_LANGS:
            dumped = yaml.safe_dump(
                self.items, sort_keys=False, allow_unicode=True, width=100
            ).rstrip()
            return f"```{k}\n{dumped}\n```"
        raise ValueError(f"unknown block kind: {k}")


# ---------------------------------------------------------------- section


@dataclass
class Section:
    id: str
    title: str
    path: Path | None = None
    meta: dict = dc_field(default_factory=dict)
    blocks: list[Block] = dc_field(default_factory=list)
    # populated by the outline walker
    number: str = ""
    level: int = 1
    children: list["Section"] = dc_field(default_factory=list)

    # -- convenience accessors -------------------------------------------
    @property
    def icon(self) -> str:
        return self.meta.get("icon", "") or ""

    @property
    def status(self) -> str:
        return self.meta.get("status", "draft")

    @property
    def screens(self) -> list[str]:
        v = self.meta.get("screens") or []
        return [v] if isinstance(v, str) else list(v)

    @property
    def profiles(self) -> list[str] | None:
        v = self.meta.get("profiles")
        if v is None:
            return None
        return [v] if isinstance(v, str) else list(v)

    @property
    def last_verified(self) -> str:
        return str(self.meta.get("last_verified", "") or "")

    def screenshots(self) -> list[str]:
        return [b.attrs.get("file", "") for b in self.blocks if b.kind == "screenshot"]

    def declared_labels(self) -> dict[str, list[str]]:
        """{'columns': [...], 'fields': [...], 'actions': [...]} for drift checks."""
        out: dict[str, list[str]] = {}
        for b in self.blocks:
            if b.kind in LABEL_KEY:
                out.setdefault(b.kind, []).extend(b.labels())
        return out

    def word_count(self) -> int:
        n = 0
        for b in self.blocks:
            n += len(b.text.split())
            for it in b.items:
                n += len(str(it).split())
        return n

    # -- serialisation ----------------------------------------------------
    def to_markdown(self) -> str:
        meta = dict(self.meta)
        meta.setdefault("id", self.id)
        meta["title"] = self.title
        # stable key order keeps diffs readable
        order = [
            "id", "title", "icon", "level", "status", "last_verified",
            "screens", "profiles", "audience", "sources", "owner", "notes",
        ]
        ordered = {k: meta[k] for k in order if k in meta}
        ordered.update({k: v for k, v in meta.items() if k not in ordered})
        fm = yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, width=100).rstrip()
        parts = [f"---\n{fm}\n---", ""]
        for b in self.blocks:
            parts.append(b.to_markdown())
            parts.append("")
        return "\n".join(parts).rstrip() + "\n"

    def save(self, path: Path | None = None) -> Path:
        target = Path(path or self.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_markdown(), encoding="utf-8")
        self.path = target
        return target


# ---------------------------------------------------------------- parser

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_IMG_RE = re.compile(r"^!\[(?P<cap>[^\]]*)\]\((?P<file>[^)\s]+)(?:\s*=(?P<w>[\d.]+)cm)?\)\s*$")
_NOTE_RE = re.compile(r"^>\s*\[!(?P<label>[^\]]+)\]\s*(?P<text>.*)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_STEP_RE = re.compile(r"^\d+\.\s+(.*)$")
_ICON_RE = re.compile(r"^([\U0001F300-\U0001FAFF☀-➿️←-⇿]+)\s+(.*)$")


_BARE_COLON = re.compile(r'^(\s*(?:-\s+)?[A-Za-z_][\w-]*:)\s+(?![\'"|>&*!])(.*\S)\s*$')


def _load_block(text: str):
    """Parse a fenced YAML block, repairing the one mistake that keeps happening.

    A value containing a colon and a space must be quoted. Writers get this
    wrong, and so does a language model asked to emit `TODO: describe this.`
    Rejecting the whole proposal over a quoting slip is the wrong trade: repair
    it, then parse.
    """
    try:
        return yaml.safe_load(text) or []
    except yaml.YAMLError:
        pass

    repaired = []
    for line in text.splitlines():
        m = _BARE_COLON.match(line)
        if m and ": " in m.group(2):
            value = m.group(2).replace('\\', '\\\\').replace('"', '\\"')
            repaired.append(f'{m.group(1)} "{value}"')
        else:
            repaired.append(line)
    try:
        return yaml.safe_load("\n".join(repaired)) or []
    except yaml.YAMLError as e:
        raise ValueError(f"this block is not valid YAML: {e}") from e


def parse_section(text: str, path: Path | None = None) -> Section:
    meta: dict[str, Any] = {}
    m = _FM_RE.match(text)
    body = text
    if m:
        meta = yaml.safe_load(m.group(1)) or {}
        body = text[m.end():]

    blocks: list[Block] = []
    lines = body.splitlines()
    i, n = 0, len(lines)
    para: list[str] = []
    bullets: list[str] = []
    steps: list[str] = []

    def flush():
        nonlocal para, bullets, steps
        if para:
            blocks.append(Block("paragraph", " ".join(x.strip() for x in para).strip()))
            para = []
        if bullets:
            blocks.append(Block("bullets", items=bullets))
            bullets = []
        if steps:
            blocks.append(Block("steps", items=steps))
            steps = []

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush()
            i += 1
            continue

        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            j = i + 1
            buf = []
            while j < n and not lines[j].strip().startswith("```"):
                buf.append(lines[j])
                j += 1
            flush()
            if lang in BLOCK_LANGS:
                items = _load_block("\n".join(buf))
                blocks.append(Block(lang, items=items))
            else:  # unknown fence: keep as literal paragraph so nothing is lost
                blocks.append(Block("paragraph", "\n".join(buf)))
            i = j + 1
            continue

        hm = _HEADING_RE.match(stripped)
        if hm:
            flush()
            title = hm.group(2).strip()
            icon = ""
            im = _ICON_RE.match(title)
            if im:
                icon, title = im.group(1), im.group(2).strip()
            blocks.append(
                Block("heading", title, attrs={"level": len(hm.group(1)), "icon": icon})
            )
            i += 1
            continue

        img = _IMG_RE.match(stripped)
        if img:
            flush()
            attrs = {"file": img.group("file"), "caption": img.group("cap")}
            if img.group("w"):
                attrs["width_cm"] = float(img.group("w"))
            blocks.append(Block("screenshot", attrs=attrs))
            i += 1
            continue

        nm = _NOTE_RE.match(stripped)
        if nm:
            flush()
            parts = [nm.group("text").strip()]
            j = i + 1
            while j < n and lines[j].strip().startswith(">"):
                parts.append(lines[j].strip().lstrip(">").strip())
                j += 1
            blocks.append(
                Block("note", " ".join(p for p in parts if p).strip(),
                      attrs={"label": nm.group("label").strip()})
            )
            i = j
            continue

        bm = _BULLET_RE.match(stripped)
        if bm:
            if para:
                blocks.append(Block("paragraph", " ".join(x.strip() for x in para).strip()))
                para = []
            bullets.append(bm.group(1).strip())
            i += 1
            continue

        sm = _STEP_RE.match(stripped)
        if sm:
            if para:
                blocks.append(Block("paragraph", " ".join(x.strip() for x in para).strip()))
                para = []
            steps.append(sm.group(1).strip())
            i += 1
            continue

        para.append(stripped)
        i += 1

    flush()
    sec = Section(
        id=str(meta.get("id") or (path.stem if path else "unknown")),
        title=str(meta.get("title") or ""),
        path=path,
        meta=meta,
        blocks=blocks,
    )
    return sec


def load_section(path: Path) -> Section:
    return parse_section(Path(path).read_text(encoding="utf-8"), Path(path))


def load_all_sections(root: Path) -> dict[str, Section]:
    out: dict[str, Section] = {}
    for p in sorted(Path(root).rglob("*.md")):
        sec = load_section(p)
        if sec.id in out:
            raise ValueError(f"duplicate section id {sec.id!r}: {p} and {out[sec.id].path}")
        out[sec.id] = sec
    return out


# ---------------------------------------------------------------- outline


@dataclass
class Node:
    """One entry in the ordered outline tree (from doc.yaml)."""
    id: str
    number: str
    level: int
    section: Section | None
    children: list["Node"] = dc_field(default_factory=list)

    @property
    def title(self) -> str:
        return self.section.title if self.section else self.id

    @property
    def icon(self) -> str:
        return self.section.icon if self.section else ""

    def walk(self) -> Iterable["Node"]:
        yield self
        for c in self.children:
            yield from c.walk()


def _entry(entry) -> tuple[str, list]:
    """One outline entry as (id, children), however it was written."""
    if isinstance(entry, str):
        return entry, []
    return entry.get("id"), entry.get("children") or []


def outline_ids(outline: list) -> list[str]:
    """Every id the outline names, before any edition has had its say."""
    out: list[str] = []
    for entry in outline or []:
        sid, kids = _entry(entry)
        if sid:
            out.append(sid)
        out.extend(outline_ids(kids))
    return out


def prune_outline(outline: list, sections: dict[str, Section], edition) -> list:
    """Drop what this edition does not carry, before anything is numbered.

    Three things can take a section out of an edition, and they mean different
    things, so they behave differently:

    * ``exclude`` in the edition names something a person decided this edition
      does not carry. It takes the whole branch: excluding a chapter drops the
      sections under it, because that is what excluding a chapter means.
    * ``include`` in the edition is a list of what the edition *is*. An entry
      not on it is dropped only if nothing under it survives either, so naming
      one sub-section keeps the chapter it lives in and the reader keeps their
      bearings.
    * ``profiles:`` in a section's own front matter is the section declaring
      which editions it belongs to, which is still the right place for a
      section written for one customer and no one else.

    Pruning runs before numbering, so an edition that omits chapter 3 numbers
    what is left 1, 2, 3 rather than printing a hole where it used to be.
    """
    kept: list = []
    for entry in outline or []:
        sid, kids = _entry(entry)
        if edition is not None and sid in getattr(edition, "exclude", ()):
            continue
        sec = sections.get(sid)
        declared = sec.profiles if sec is not None else None
        if edition is not None and declared is not None \
                and edition.name not in declared:
            continue
        kids = prune_outline(kids, sections, edition)
        allow = getattr(edition, "include", None) if edition is not None else None
        if allow is not None and sid not in allow and not kids:
            continue
        kept.append({"id": sid, "children": kids} if kids else {"id": sid})
    return kept


def build_outline(outline: list, sections: dict[str, Section], prefix: str = "",
                  level: int = 1, profile: str | None = None) -> list[Node]:
    """Turn doc.yaml's nested list into numbered Nodes.

    Numbering is derived, never hand-written, so inserting a section renumbers
    everything below it automatically.
    """
    nodes: list[Node] = []
    counter = 0
    for entry in outline or []:
        if isinstance(entry, str):
            sid, kids = entry, []
        else:
            sid = entry.get("id")
            kids = entry.get("children") or []
        sec = sections.get(sid)
        if sec is not None and profile is not None:
            allowed = sec.profiles
            if allowed is not None and profile not in allowed:
                continue
        counter += 1
        number = f"{prefix}{counter}"
        node = Node(id=sid, number=number, level=level, section=sec)
        if sec is not None:
            sec.number, sec.level = number, level
        node.children = build_outline(kids, sections, prefix=f"{number}.",
                                      level=level + 1, profile=profile)
        nodes.append(node)
    return nodes


def flatten(nodes: list[Node]) -> list[Node]:
    out: list[Node] = []
    for nd in nodes:
        out.extend(nd.walk())
    return out
