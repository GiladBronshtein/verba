"""HTML renderer: a reviewable, linkable preview of the same content tree.

Used for review before a DOCX is cut. Section status, verification dates and
drift flags are shown inline so a reviewer sees not just the text but how much
to trust it.
"""
from __future__ import annotations

import base64
import html
import re
from pathlib import Path

from ..render.docx import ICON_MARKER
from ..glyphs import for_emoji, svg as glyph
from ..theme import Theme

CSS = """
:root{
  --navy:$NAVY; --blue:$BLUE; --lav:$LAV; --peri:$PERI;
  --grey:$GREYD; --grey-mid:$GREYM; --red:$RED; --green:$GREEN; --amber:$AMBER;
  --bg:#ffffff; --surface:$LAV; --border:$LAV; --text:$NAVY;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme=light]){
    --bg:#0E1222; --surface:#161B30; --border:#2A3152; --text:#E7EAF6;
    /* On a dark ground the accent has to lift, or a colour chosen to pass on
       white sits at three-to-one on near-black. The theme carries a lighter
       sibling for exactly this. */
    --navy:#E7EAF6; --lav:#1C2340; --grey:#9AA3C4; --grey-mid:#7A83A6;
    --blue:$PERI;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Calibri,sans-serif}
.wrap{display:grid;grid-template-columns:290px minmax(0,1fr);gap:0;min-height:100vh}
nav{position:sticky;top:0;height:100vh;overflow:auto;padding:24px 18px;
  background:var(--surface);border-right:1px solid var(--border);font-size:13px}
nav h2{font-size:12px;letter-spacing:.09em;text-transform:uppercase;color:var(--grey-mid);margin:0 0 14px}
nav a{display:block;padding:3px 0;color:var(--grey);text-decoration:none}
nav a:hover{color:var(--blue)}
nav a.l1{font-weight:700;color:var(--navy);margin-top:12px}
nav a.l3{padding-left:16px;font-size:12.5px}
main{padding:40px 48px;max-width:980px}
h1.doc{font-size:34px;margin:0 0 4px;color:var(--navy)}
.sub{color:var(--grey-mid);margin-bottom:28px}
section{scroll-margin-top:20px;padding-top:8px}
h1{font-size:27px;color:var(--navy);border-bottom:3px solid var(--blue);
  padding-bottom:8px;margin:48px 0 14px}
h2{font-size:19px;color:var(--blue);margin:34px 0 10px}
h3{font-size:16px;color:var(--navy);margin:26px 0 8px}
h4{font-size:13.5px;color:var(--blue);margin:20px 0 6px;text-transform:none}
p{margin:9px 0}
ul{margin:8px 0;padding-left:22px} li{margin:3px 0}
img.shot{max-width:100%;border:1px solid var(--border);border-radius:8px;display:block;margin:14px auto}
.detail{margin:10px 0}
img.crop{max-width:100%;height:auto;border:1px solid var(--border);border-radius:4px;display:block}
img.icon{height:1.5em;vertical-align:-.4em;border:1px solid var(--border);border-radius:4px;margin:0 3px}
figcaption{text-align:center;font-size:12.5px;color:var(--grey-mid);margin-bottom:18px}
figcaption b{color:var(--blue)}
.note{background:var(--lav);border-left:4px solid var(--blue);padding:11px 14px;
  border-radius:0 6px 6px 0;margin:14px 0;font-size:14px}
.note.important{border-left-color:var(--red)}
.note b{color:var(--blue)} .note.important b{color:var(--red)}
.deflist{margin:10px 0}
.deflist div{padding:4px 0}
.deflist .name{font-weight:700}
.deflist .col .name,.deflist .act .name{color:var(--blue)}
.deflist .type{color:var(--peri);font-size:13px}
.deflist .req{color:var(--red);font-weight:700}
.deflist .sep{color:var(--grey-mid)}
.meta{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 14px;font-size:11.5px}
.chip{border:1px solid var(--border);border-radius:999px;padding:2px 9px;color:var(--grey)}
.chip.verified{border-color:var(--green);color:var(--green)}
.chip.draft{border-color:var(--amber);color:var(--amber)}
.chip.stale{border-color:var(--red);color:var(--red)}
.chip.drift{border-color:var(--red);color:var(--red);font-weight:700}
.driftbox{border:1px solid var(--red);border-radius:8px;padding:10px 14px;margin:10px 0;
  font-size:13.5px;background:color-mix(in srgb,var(--red) 7%,transparent)}
.driftbox b{color:var(--red)}
table.status{border-collapse:collapse;width:100%;margin-top:18px;font-size:13.5px}
table.status th{text-align:left;padding:8px 10px;border-bottom:2px solid var(--blue);
  color:var(--navy);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
table.status td{padding:7px 10px;border-bottom:1px solid var(--border)}
table.status a{color:var(--text);text-decoration:none}
table.status a:hover{color:var(--blue)}
.driftnum{color:var(--red)}
nav a.active{color:var(--blue)}
nav a.home{margin:0 0 10px}
@media(max-width:860px){.wrap{grid-template-columns:1fr}nav{position:static;height:auto}main{padding:24px}}
"""


DETAIL_MAX_H = 200          # taller than this and it is a screen, not a crop


def _is_detail(project, name: str) -> bool:
    """Is this a cropped control rather than a picture of a screen?"""
    if not name:
        return False
    try:
        from PIL import Image
        path = project.asset_path(name)
        if not path.exists():
            return False
        with Image.open(path) as im:
            return im.size[1] < DETAIL_MAX_H
    except Exception:
        return False


def _esc(t: str) -> str:
    return html.escape(str(t))


def _b64(path: Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


def themed_css(theme, css: str = None) -> str:
    """The stylesheet with this project's palette substituted in.

    The colours were literals here, which is why every document this engine
    built came out in one company's brand no matter whose product it described.
    """
    out = CSS if css is None else css
    for token, value in (("$NAVY", theme.navy_deep), ("$BLUE", theme.brand_blue),
                         ("$LAV", theme.lavender), ("$PERI", theme.periwinkle),
                         ("$GREYD", theme.grey_dark), ("$GREYM", theme.grey_mid),
                         ("$RED", theme.red_err), ("$GREEN", theme.green_ok),
                         ("$AMBER", theme.amber), ("$HERO", theme.navy_hero)):
        out = out.replace(token, f"#{value}")
    return out


class HtmlRenderer:
    def __init__(self, project, drift_report=None, embed_images: bool = False,
                 lazy: bool = True):
        # `loading="lazy"` is right for the preview, where someone scrolls, and
        # fatal for print, where nobody does: an image below the first viewport
        # is never asked for, so the printed page gets the broken-image mark
        # instead of the figure. The renderer is shared, so the caller says
        # which it is building.
        self.lazy = lazy
        self.p = project
        # The project's own theme. There is no default product any more, so
        # there is no default palette either.
        self.theme = Theme.load(getattr(project, "root", "."))
        self.drift = drift_report.by_section() if drift_report else {}
        self.embed = embed_images
        self.asset_out: Path | None = None

    def _img(self, name: str, cls: str) -> str:
        path = self.p.asset_path(name)
        if not path.exists():
            return f'<em style="color:var(--red)">[missing asset: {_esc(name)}]</em>'
        if self.embed:
            src = f"data:image/png;base64,{_b64(path)}"
        else:
            # copy beside the page so the preview is a self-contained folder
            # that a static server can hand out without a multi-megabyte page
            dest = self.asset_out / name
            if not dest.exists() or dest.stat().st_mtime < path.stat().st_mtime:
                dest.write_bytes(path.read_bytes())
            src = f"assets/{name}"
        lazy = ' loading="lazy"' if getattr(self, "lazy", True) else ""
        return f'<img class="{cls}" src="{src}" alt="{_esc(name)}"{lazy}>'

    def _inline(self, text: str) -> str:
        out, pos = [], 0
        for m in ICON_MARKER.finditer(text):
            out.append(_esc(text[pos:m.start()].rstrip()))
            out.append(self._img(m.group(1), "icon"))
            pos = m.end()
        out.append(_esc(text[pos:]))
        return "".join(out)

    def _blocks(self, section, chapter, counter) -> str:
        parts = []
        for b in self.p.resolved_blocks(section):
            k = b.kind
            if k == "paragraph":
                parts.append(f"<p>{self._inline(b.text)}</p>")
            elif k == "bullets":
                items = "".join(f"<li>{self._inline(str(i))}</li>" for i in b.items)
                parts.append(f"<ul>{items}</ul>")
            elif k == "steps":
                items = "".join(f"<li>{self._inline(str(i))}</li>" for i in b.items)
                parts.append(f"<ol>{items}</ol>")
            elif k == "heading":
                parts.append(f"<h4>{_esc(b.text)}</h4>")
            elif k == "note":
                label = b.attrs.get("label", "Note")
                # The theme names a drawn mark. An emoji written directly into
                # a section still resolves, because content is allowed to be
                # typed the easy way; it is only ever printed as a mark.
                icon = glyph(self.theme.note_marks.get(label, "note")) \
                    or for_emoji(label)
                cls = "note important" if label in ("Important", "Warning") else "note"
                parts.append(f'<div class="{cls}"><b>{icon}{_esc(label)}:</b> '
                             f'{self._inline(b.text)}</div>')
            elif k == "screenshot":
                name = b.attrs.get("file", "")
                cap = b.attrs.get("caption", "")
                # A cropped control is not a figure. Numbering one and blowing
                # it up to the column width gives a blurry strip under a caption
                # reading "Figure 4.7", which is indistinguishable from an image
                # that failed to load. Shown at its own size instead, and left
                # out of the figure numbering, where it reads as what it is: a
                # detail of the screen the text is describing.
                if not cap and _is_detail(self.p, name):
                    parts.append(f'<div class="detail">'
                                 f'{self._img(name, "crop")}</div>')
                    continue
                counter[chapter] = counter.get(chapter, 0) + 1
                parts.append(
                    f'<figure>{self._img(name, "shot")}'
                    f'<figcaption><b>Figure {chapter}.{counter[chapter]}</b>'
                    f'{": " + _esc(cap) if cap else ""}</figcaption></figure>')
            elif k == "fields":
                rows = []
                for f in b.items:
                    req = '<span class="req">* </span>' if f.get("required") else ""
                    typ = f'<span class="type"> {_esc(f["type"])}</span>' if f.get("type") else ""
                    desc = f'<span class="sep">:  </span>{_esc(f.get("description",""))}' \
                        if f.get("description") else ""
                    rows.append(f'<div>{req}<span class="name">{_esc(f.get("field",""))}'
                                f'</span>{typ}{desc}</div>')
                parts.append(f'<div class="deflist">{"".join(rows)}</div>')
            elif k in ("actions", "columns", "tabs"):
                key = {"actions": "action", "columns": "column", "tabs": "tab"}[k]
                cls = {"actions": "act", "columns": "col", "tabs": "tab"}[k]
                rows = []
                for it in b.items:
                    desc = f'<span class="sep">:  </span>{_esc(it.get("description",""))}' \
                        if it.get("description") else ""
                    rows.append(f'<div><span class="name">{_esc(it.get(key,""))}</span>{desc}</div>')
                parts.append(f'<div class="deflist {cls}">{"".join(rows)}</div>')
            elif k == "terms":
                rows = [f'<div><span class="name">{_esc(it.get("term",""))}:  </span>'
                        f'{_esc(it.get("definition",""))}</div>' for it in b.items]
                parts.append(f'<div class="deflist">{"".join(rows)}</div>')
        return "\n".join(parts)

    # ---------------------------------------------------------------- pages
    def _chapters(self):
        """Group the outline into chapters, each rendered as its own page."""
        chapters, current = [], None
        for node in self.p.nodes:
            if node.section is None:
                continue
            if node.level == 1:
                current = {"node": node, "nodes": [node],
                           "file": f"ch-{node.number}-{_slug(node.section.title)}.html"}
                chapters.append(current)
            elif current is not None:
                current["nodes"].append(node)
        return chapters

    def _nav(self, chapters, active_file: str) -> str:
        out = ['<a class="l1 home" href="index.html">Overview</a>']
        for ch in chapters:
            for node in ch["nodes"]:
                if node.level > 3:
                    continue
                here = ch["file"] == active_file
                href = f'{ch["file"]}#{node.id.replace(".", "-")}' if here or node.level > 1 \
                    else ch["file"]
                cls = f'l{min(node.level, 3)}' + (" active" if here and node.level == 1 else "")
                out.append(f'<a class="{cls}" href="{href}">'
                           f'{node.number} {_esc(node.section.title)}</a>')
        return "".join(out)

    def _page(self, title: str, nav: str, main: str) -> str:
        return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{_esc(title)}</title><style>{themed_css(self.theme)}</style></head><body>'
                f'<div class="wrap"><nav><h2>Contents</h2>{nav}</nav>'
                f'<main>{main}</main></div></body></html>')

    def _section_html(self, node, counter) -> str:
        sec = node.section
        anchor = node.id.replace(".", "-")
        heading = {1: "h1", 2: "h2", 3: "h3"}.get(node.level, "h4")
        icon = (for_emoji(sec.icon) or (f"{sec.icon} " if sec.icon else "")) if sec.icon else ""
        chips = [f'<span class="chip {sec.status}">{sec.status}</span>']
        if sec.last_verified:
            chips.append(f'<span class="chip">verified {sec.last_verified}</span>')
        for sid in sec.screens:
            chips.append(f'<span class="chip">{_esc(sid)}</span>')
        drift = self.drift.get(sec.id, [])
        driftbox = ""
        if drift:
            chips.append(f'<span class="chip drift">{len(drift)} drift</span>')
            items = "".join(f"<li>{_esc(c.line())}</li>" for c in drift)
            driftbox = ('<div class="driftbox"><b>Needs review against the live system</b>'
                        f"<ul>{items}</ul></div>")
        chapter = node.number.split(".")[0]
        return (f'<section id="{anchor}">'
                f'<{heading}>{icon}{node.number} {_esc(sec.title)}</{heading}>'
                f'<div class="meta">{"".join(chips)}</div>{driftbox}'
                f'{self._blocks(sec, chapter, counter)}</section>')

    def render(self, out_path: Path) -> Path:
        """Write a paginated preview: one page per chapter plus an index.

        A single page for the whole manual runs past 30,000 pixels, which no
        reviewer scrolls and some renderers refuse to composite.
        """
        p = self.p
        out_path = Path(out_path)
        out_dir = out_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        self.asset_out = out_dir / "assets"
        self.asset_out.mkdir(parents=True, exist_ok=True)

        chapters = self._chapters()
        doc_title = f"{p.config['product']['name']} {p.title()}"

        for ch in chapters:
            counter: dict = {}
            body = "".join(self._section_html(n, counter) for n in ch["nodes"])
            page = self._page(f"{ch['node'].number}. {ch['node'].section.title} - {doc_title}",
                              self._nav(chapters, ch["file"]), body)
            (out_dir / ch["file"]).write_text(page, encoding="utf-8")

        # index: status overview across every section
        rows = []
        for ch in chapters:
            for node in ch["nodes"]:
                sec = node.section
                d = len(self.drift.get(sec.id, []))
                rows.append(
                    f'<tr><td><a href="{ch["file"]}#{node.id.replace(".", "-")}">'
                    f'{node.number} {_esc(sec.title)}</a></td>'
                    f'<td><span class="chip {sec.status}">{sec.status}</span></td>'
                    f'<td>{_esc(sec.last_verified or "-")}</td>'
                    f'<td>{_esc(", ".join(sec.screens) or "-")}</td>'
                    f'<td>{"<b class=driftnum>" + str(d) + "</b>" if d else "-"}</td></tr>')
        total_drift = sum(len(v) for v in self.drift.values())
        main = (f'<h1 class="doc">{_esc(doc_title)}</h1>'
                f'<div class="sub">Edition: {_esc(p.profile.name)} &middot; '
                f'{len(p.nodes)} sections &middot; {len(chapters)} chapters &middot; '
                f'{total_drift} open drift items</div>'
                f'<table class="status"><thead><tr><th>Section</th><th>Status</th>'
                f'<th>Verified</th><th>Screens</th><th>Drift</th></tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table>')
        index = out_dir / "index.html"
        index.write_text(self._page(doc_title, self._nav(chapters, ""), main),
                         encoding="utf-8")
        return index


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
