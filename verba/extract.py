"""One-time migration: recover a legacy generated DOCX into the content tree.

The legacy documents were produced by throwaway generator scripts, several of
which no longer exist on disk. Their formatting is regular enough to be read
back: every block type has a distinct run/paragraph signature. This module
classifies each paragraph, matches embedded images back to files in
``screenshots/`` by perceptual hash, and writes one Markdown file per heading.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

from docx import Document
from docx.shared import RGBColor
from PIL import Image

from .assets import AssetStore, Library
from .imaging import crop_by_rect
from .model import Block, Section

BRAND_BLUE = "3137DB"
PERIWINKLE = "5E97FF"
GREY_MID = "A1A1A1"
RED_ERR = "E03939"

_NUM_RE = re.compile(r"^(?P<icon>[^\w\d]*)\s*(?P<num>\d+(?:\.\d+)*)\.?\s+(?P<title>.+)$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-")


# ------------------------------------------------------------ paragraph read


def _color(run) -> str | None:
    try:
        if run.font.color is not None and run.font.color.type is not None:
            rgb = run.font.color.rgb
            return str(rgb) if isinstance(rgb, RGBColor) else None
    except Exception:
        pass
    return None


def _size(run) -> float | None:
    return run.font.size.pt if run.font.size else None


EMU_PER_CM = 360000


def _crop_rect(xml: str):
    """Word stores crops as srcRect in thousandths of a percent inset per edge."""
    m = re.search(r"<a:srcRect([^/>]*)/>", xml)
    if not m:
        return None
    attrs = dict(re.findall(r'([ltrb])="(-?\d+)"', m.group(1)))
    rect = [round(int(attrs.get(k, 0)) / 1000.0, 3) for k in ("l", "t", "r", "b")]
    return rect if any(rect) else None


def _display_cm(xml: str):
    m = re.search(r'<wp:extent cx="(\d+)" cy="(\d+)"', xml)
    return round(int(m.group(1)) / EMU_PER_CM, 2) if m else None


def read_paragraph(p, doc_part) -> dict:
    xml = p._p.xml
    runs = [
        {
            "text": r.text,
            "bold": bool(r.font.bold),
            "italic": bool(r.font.italic),
            "size": _size(r),
            "color": _color(r),
        }
        for r in p.runs
    ]
    images = []
    for m in re.finditer(r'r:embed="(rId\d+)"', xml):
        rid = m.group(1)
        try:
            blob = doc_part.rels[rid].target_part.blob
        except Exception:
            continue
        images.append((rid, blob, _crop_rect(xml), _display_cm(xml)))
    return {
        "style": p.style.name,
        "text": p.text.strip(),
        "runs": runs,
        "images": images,
        "hanging": "w:hanging" in xml,
        "shaded": "w:shd" in xml,
        "centered": (p.alignment is not None and int(p.alignment) == 1),
        "max_size": max([r["size"] or 0 for r in runs] or [0]),
    }


# ------------------------------------------------------------ classification


def classify(rec: dict, context: str) -> str:
    style, runs = rec["style"], rec["runs"]
    if rec["images"] and not rec["text"]:
        return "image"
    if style == "List Bullet":
        return "bullet"
    if style.startswith("Heading"):
        return f"h{style[-1]}"
    if rec["shaded"]:
        return "note"
    if rec["max_size"] >= 20:
        return "h1"
    if rec["max_size"] >= 12.5 and runs and runs[0]["bold"]:
        return "h2"
    if rec["centered"] and runs and (runs[0]["size"] or 0) <= 9 and runs[0]["color"] == GREY_MID:
        return "caption"
    if rec["hanging"] and runs:
        first = runs[0]
        # required-marker run comes first on some field rows
        idx = 1 if (first["color"] == RED_ERR and first["text"].strip() == "*") else 0
        head = runs[idx] if idx < len(runs) else first
        if not head["bold"]:
            return "continuation"
        has_type = any(r["color"] == PERIWINKLE for r in runs)
        if head["color"] == BRAND_BLUE:
            return "action"
        if has_type:
            return "field"
        return "columns" if "column" in context.lower() else "field"
    if not rec["text"]:
        return "blank"
    return "body"


def split_label(rec: dict) -> tuple[str, str, str, bool]:
    """Return (label, type, description, required) from a hanging-indent row."""
    runs = rec["runs"]
    required = bool(runs and runs[0]["color"] == RED_ERR and runs[0]["text"].strip() == "*")
    parts = runs[1:] if required else runs
    label_bits, type_bits, desc_bits, seen_sep = [], [], [], False
    for r in parts:
        t = r["text"]
        if not t:
            continue
        if seen_sep:
            desc_bits.append(t)
        elif r["color"] == PERIWINKLE:
            type_bits.append(t)
        elif t.strip() == ":" or t.strip().startswith(":"):
            seen_sep = True
            rest = t.split(":", 1)[1]
            if rest.strip():
                desc_bits.append(rest)
        elif r["bold"]:
            label_bits.append(t)
        else:
            desc_bits.append(t)
    label = "".join(label_bits).strip().rstrip(":").strip()
    typ = "".join(type_bits).strip().rstrip(":").strip()
    desc = "".join(desc_bits).strip().lstrip(":").strip()
    return label, typ, desc, required


# ------------------------------------------------------------ main extraction


def extract(docx_path: Path, shots_dir: Path, out_root: Path, assets_dir: Path,
            doc_title: str = "") -> dict:
    doc = Document(str(docx_path))
    lib = Library.load(Path(shots_dir))
    store = AssetStore(Path(assets_dir))

    recs = [read_paragraph(p, doc.part) for p in doc.paragraphs]

    sections: list[Section] = []
    outline: list[dict] = []
    cur: Section | None = None
    chapter_slug = "front"
    chapter_entry: dict | None = None
    parent_entry: dict | None = None
    h4_context = ""
    pending: dict[str, list] = {}
    unmatched = 0
    seen_toc = False
    shot_counts: dict[str, int] = {}
    icon_counts: dict[str, int] = {}

    def flush_pending():
        nonlocal pending
        for kind in ("fields", "actions", "columns", "bullets", "steps"):
            if pending.get(kind):
                cur.blocks.append(Block(kind, items=pending[kind]))
                pending[kind] = []

    def start_section(sid: str, title: str, level: int, icon: str, number: str):
        nonlocal cur
        if cur is not None:
            flush_pending()
        cur = Section(id=sid, title=title, meta={
            "id": sid, "title": title, "icon": icon, "level": level,
            "status": "verified", "legacy_number": number,
        })
        sections.append(cur)

    for i, rec in enumerate(recs):
        kind = classify(rec, h4_context)
        text = rec["text"]

        if kind == "blank":
            continue

        if kind in ("h1", "h2", "h3"):
            m = _NUM_RE.match(text)
            icon, number, title = "", "", text
            if m:
                icon = m.group("icon").strip()
                number, title = m.group("num"), m.group("title").strip()
            else:
                # leading emoji without a number
                em = re.match(r"^([^\w\s]+)\s+(.*)$", text)
                if em:
                    icon, title = em.group(1), em.group(2)
            if title.lower().startswith("table of contents"):
                seen_toc = True
                cur = None
                continue
            if not seen_toc:
                continue  # skip cover / pre-TOC matter
            if not title.strip():
                continue  # stray empty heading left over from manual Word edits

            if kind == "h1":
                chapter_slug = slug(title)
                sid = chapter_slug
                start_section(sid, title, 1, icon, number)
                chapter_entry = {"id": sid, "children": []}
                outline.append(chapter_entry)
                parent_entry = chapter_entry
            elif kind == "h2":
                sid = f"{chapter_slug}.{slug(title)}"
                start_section(sid, title, 2, icon, number)
                parent_entry = {"id": sid, "children": []}
                (chapter_entry or {"children": outline})["children"].append(parent_entry)
            else:
                sid = f"{chapter_slug}.{slug(title)}"
                start_section(sid, title, 3, icon, number)
                target = parent_entry or chapter_entry
                target["children"].append({"id": sid})
            h4_context = ""
            continue

        if cur is None:
            continue

        if kind == "h4":
            flush_pending()
            h4_context = text
            cur.blocks.append(Block("heading", text, attrs={"level": 4, "icon": ""}))
            continue

        if kind == "image":
            rid, blob, rect, disp_cm = rec["images"][0]
            img = Image.open(io.BytesIO(blob))
            src_name, dist = lib.match(img)
            is_icon = rec["style"] == "List Bullet" and bool(pending.get("bullets"))
            base = cur.id.replace(".", "-")
            if is_icon:
                icon_counts[cur.id] = icon_counts.get(cur.id, 0) + 1
                name = f"icon-{base}-{icon_counts[cur.id]}.png"
            else:
                shot_counts[cur.id] = shot_counts.get(cur.id, 0) + 1
                name = f"{base}-{shot_counts[cur.id]}.png"
            meta = {"section": cur.id}
            if rect:
                meta["crop"] = rect
            if src_name:
                meta.update(legacy_name=src_name, match_distance=round(dist, 4))
                source = lib.root / src_name
            else:
                source = None
                unmatched += 1

            if rect:
                # materialise the crop so the file on disk is what the page shows,
                # keeping the rect in the registry so it can be re-cut after a recapture
                base_img = Image.open(source) if source else img
                cropped = crop_by_rect(base_img, rect)
                buf = io.BytesIO(); cropped.save(buf, "PNG")
                store.put_blob(name, buf.getvalue(), **meta)
            elif source:
                store.put_file(name, source, **meta)
            else:
                store.put_blob(name, blob, note="no library match", **meta)

            if is_icon:
                marker = f"[icon:{name}]"
                pending["bullets"][-1] += f" {marker}"
                continue
            flush_pending()
            attrs = {"file": name, "caption": ""}
            if disp_cm:
                attrs["width_cm"] = disp_cm
            cur.blocks.append(Block("screenshot", attrs=attrs))
            continue

        if kind == "caption":
            for b in reversed(cur.blocks):
                if b.kind == "screenshot":
                    b.attrs["caption"] = text
                    break
            continue

        if kind == "bullet":
            if not text:
                continue
            pending.setdefault("bullets", []).append(text)
            continue

        if kind == "note":
            flush_pending()
            label = "Note"
            body = text
            m = re.match(r"^\s*(?:[^\w\s]+\s*)?([A-Za-z][A-Za-z /]+):\s+(.*)$", text)
            if m:
                label, body = m.group(1).strip(), m.group(2).strip()
            cur.blocks.append(Block("note", body, attrs={"label": label}))
            continue

        if kind in ("field", "action", "columns"):
            label, typ, desc, required = split_label(rec)
            if kind == "field":
                item = {"field": label}
                if typ:
                    item["type"] = typ
                if required:
                    item["required"] = True
                item["description"] = desc
                pending.setdefault("fields", []).append(item)
            elif kind == "action":
                pending.setdefault("actions", []).append(
                    {"action": label, "description": desc})
            else:
                pending.setdefault("columns", []).append(
                    {"column": label, "description": desc})
            continue

        if kind == "continuation":
            for key in ("fields", "actions", "columns"):
                if pending.get(key):
                    last = pending[key][-1]
                    last["description"] = (last.get("description", "") + " " + text).strip()
                    break
            else:
                if pending.get("bullets"):
                    pending["bullets"][-1] += " " + text
                else:
                    cur.blocks.append(Block("paragraph", text))
            continue

        # body
        if text:
            flush_pending()
            if cur.blocks and cur.blocks[-1].kind == "paragraph" and not text[0].isupper():
                cur.blocks[-1].text += " " + text
            else:
                cur.blocks.append(Block("paragraph", text))

    if cur is not None:
        flush_pending()

    # write files
    written = []
    for sec in sections:
        chapter = sec.id.split(".")[0]
        n = len([s for s in sections if s.id.split(".")[0] == chapter and
                 sections.index(s) <= sections.index(sec)])
        fname = f"{n:03d}-{slug(sec.title)}.md"
        path = out_root / chapter / fname
        sec.meta.pop("level", None)
        sec.save(path)
        written.append(path)

    store.save()
    return {
        "library": lib.stats(),
        "assets": len(store.registry),
        "sections": len(sections),
        "files": written,
        "outline": outline,
        "unmatched_images": unmatched,
    }
