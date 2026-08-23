"""PDF renderer.

Prints the document through headless Chromium, so the PDF comes from the same
content tree as the DOCX and needs neither Word nor LibreOffice installed.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from ..glyphs import CSS as GLYPH_CSS
from ..theme import Theme
from ..typography import Typography
from .html import HtmlRenderer, _esc


def _revision_label(stamp: str) -> str:
    """What goes under Revision on the cover.

    "draft 2026-08-23" sat directly above a Date row carrying the same day: the
    date printed twice, and neither of them reading as a revision. The running
    footer keeps the long form, where telling two proofs apart is the point.
    """
    s = str(stamp or "").strip()
    return "Draft" if s.lower().startswith("draft") else s


def _mm(value) -> str:
    return f"{float(value):g}"


def print_css(face, page=None, text=None, theme=None) -> str:
    """The print stylesheet, set in the chosen face.

    Type size is not a constant here. Faces differ by more than a name: Inter's
    x-height is far larger than Source Sans's, so the same nominal size reads a
    point bigger. Each face carries the size and leading it wants, and the
    tracking it needs, and this substitutes them in.
    """
    from ..theme import Theme
    th = theme if theme is not None else Theme()
    return (face.css_import()
            + GLYPH_CSS
            + PRINT_CSS
            .replace("$BODY", face.css_body())
            .replace("$MONO", face.css_mono())
            .replace("$PT", f"{face.body_pt}pt")
            .replace("$LINE", str(face.line))
            .replace("$TRACK", face.tracking())
            .replace("$SIDE", _mm(page.side if page else 18))
            .replace("$TOP", _mm(page.margin_top if page else 24))
            .replace("$BOT", _mm(page.margin_bottom if page else 20))
            .replace("$PAPER", page.paper_name if page else "A4")
            # The palette is the project's, not this file's. It used to be five
            # literal hex values here, which meant every document ever built by
            # this engine came out in one company's brand.
            .replace("$NAVY", f"#{th.navy_deep}")
            .replace("$BLUE", f"#{th.brand_blue}")
            .replace("$LAV", f"#{th.lavender}")
            .replace("$PERI", f"#{th.periwinkle}")
            .replace("$HERO", f"#{th.navy_hero}")
            .replace("$GREYM", f"#{th.grey_mid}")
            .replace("$GREYD", f"#{th.grey_dark}")
            .replace("$RED", f"#{th.red_err}")
            .replace("$GREEN", f"#{th.green_ok}")
            .replace("$AMBER", f"#{th.amber}")
            .replace("$ALIGN", text.css_align if text else "left")
            .replace("$HYPH", text.css_hyphens if text else "auto"))


PRINT_CSS = """
/* Chromium takes the @page margin over the one passed to page.pdf(), and the
   header and footer are drawn into that margin box. The two must agree: set
   the top here to 0 and the running header lands on the first line of text. */
@page { size: $PAPER; margin: $TOPmm $SIDEmm $BOTmm $SIDEmm; }
:root{
  --navy:$NAVY; --blue:$BLUE; --lav:$LAV; --peri:$PERI; --hero:$HERO;
  --grey:$GREYD; --grey-mid:$GREYM; --red:$RED; --border:$LAV;
  --bg:#fff; --text:$NAVY; --surface:$LAV; --green:$GREEN; --amber:$AMBER;
}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--text);
  font:$PT/$LINE $BODY;letter-spacing:$TRACK;
  -webkit-font-smoothing:antialiased;
  /* Digits in a technical document sit in tables and field lists, where a
     proportional 1 next to a proportional 8 will not line up. */
  font-variant-numeric:tabular-nums;
  -webkit-print-color-adjust:exact;print-color-adjust:exact}
code,kbd,.mono{font-family:$MONO;font-size:0.94em;letter-spacing:0}
main{max-width:none}
nav,.meta,.driftbox{display:none !important}

/* The cover.

   It used to run the vendor name at 64pt, the product under it at 32pt and the
   subtitle under that, which on a document whose vendor and product share a
   word printed RISE and then Rise Hub: three competing titles and the same word
   twice. Above them sat a third of a page of nothing, because the block was
   pushed down by a fixed 70mm margin rather than placed.

   Now the page has two parts. A field carries the identity, and the sheet below
   it carries the facts. Nothing floats, and the title is the only large thing
   on the page. */
.cover{height:257mm;page-break-after:always;padding:0;
  display:flex;flex-direction:column}
.cover .band{height:132mm;background:var(--hero);padding:26mm $SIDEmm 20mm;
  position:relative;display:flex;flex-direction:column;justify-content:space-between}
.cover .band:after{content:"";position:absolute;left:0;right:0;bottom:0;
  height:2.2mm;background:var(--blue)}
.cover .vendor{font-size:9pt;letter-spacing:0.26em;text-transform:uppercase;
  color:var(--peri);font-weight:600}
.cover .titles{margin-bottom:2mm}
.cover .product{font-size:42pt;line-height:1.02;letter-spacing:-0.028em;
  font-weight:700;color:#fff;max-width:150mm;margin:0}
.cover .subtitle{color:var(--peri);font-size:13pt;margin:7mm 0 0;font-weight:400}
.cover .low{flex:1;padding:22mm $SIDEmm 20mm;display:flex;flex-direction:column}
.cover .lead{font-size:10.5pt;line-height:1.62;color:var(--grey);max-width:132mm;
  margin-bottom:14mm}
/* Two columns, because five or six facts in one column leaves a page half
   empty and reads as a form rather than a colophon. */
/* Under the band, not pinned to the foot. Pinned, the facts left ninety
   millimetres of white between themselves and the thing they belong to, which
   is the dead space this cover was redrawn to remove, moved down the page. */
.cover .facts{font-size:9.5pt;
  display:grid;grid-template-columns:1fr 1fr;column-gap:16mm}
.cover .facts div{display:flex;gap:6mm;padding:2.7mm 0;
  border-bottom:0.2mm solid rgba(0,0,0,0.14)}
.cover .facts div:nth-child(1),.cover .facts div:nth-child(2){
  border-top:0.2mm solid rgba(0,0,0,0.14)}
.cover .facts b{font-weight:600;font-size:7.6pt;letter-spacing:0.1em;
  text-transform:uppercase;color:var(--grey-mid);width:26mm;flex:none;
  padding-top:0.4mm}
.cover .facts span{color:var(--navy);font-weight:500}
.cover .conf{margin-top:auto;display:flex;justify-content:space-between;
  color:var(--grey-mid);font-size:8pt;letter-spacing:0.04em}

.toc{page-break-after:always}
.toc h1{margin-top:0;margin-bottom:4mm}
.toc a{text-decoration:none;color:inherit;display:flex;gap:3mm;align-items:baseline}
.toc .row{margin:0.45mm 0;font-size:9.8pt;line-height:1.35}
.toc .row.l1{font-weight:700;color:var(--navy);margin-top:2.2mm}
.toc .row.l2{padding-left:8mm;color:var(--grey)}
.toc .row.l3{padding-left:16mm;color:var(--grey);font-size:9.5pt}
.toc .num{color:var(--blue);min-width:16mm}
.toc .row.l2 .num,.toc .row.l3 .num{color:var(--grey-mid)}
.toc .dots{flex:1;border-bottom:0.3mm dotted var(--border);transform:translateY(-1mm)}

/* A 1.32 modular scale off the body size, so changing the face rescales the
   whole hierarchy with it rather than leaving headings stranded at fixed pt. */
h1,h2,h3,h4{letter-spacing:-0.012em;text-wrap:balance;font-weight:700}
h1{font-size:2.1em;color:var(--navy);margin:0 0 5mm;padding-bottom:3mm;
  border-bottom:1mm solid var(--blue);page-break-before:always;page-break-after:avoid}
h1.first{page-break-before:avoid}
/* Colour was carrying the hierarchy and could not: h2 at 1.27em and h3 at 1.1em
   are the same size to a reader, so the only thing separating a chapter from a
   sub-heading was blue against navy, and blue text at that weight reads as a
   link rather than as a heading. Size and weight separate them now, and the
   rule above an h2 does the work of the whitespace that used to be there. */
h2{font-size:1.62em;color:var(--hero);margin:11mm 0 3mm;padding-top:3.5mm;
  border-top:0.35mm solid rgba(0,0,0,0.16);letter-spacing:-0.02em;
  page-break-after:avoid}
h3{font-size:1.16em;color:var(--blue);font-weight:600;margin:7mm 0 1.6mm;
  page-break-after:avoid}
h4{font-size:0.97em;color:var(--blue);margin:4mm 0 1.5mm;page-break-after:avoid;
  letter-spacing:0.02em;text-transform:none}
/* A heading must never be the last thing on a page. */
h1+*,h2+*,h3+*,h4+*{page-break-before:avoid}
/* Ragged right, deliberately. Justified setting needs hyphenation to avoid
   rivers of white running down the column, and the Chromium that prints this
   ships without hyphenation dictionaries: `hyphens:auto` measurably changes
   nothing here. Given that choice, an even word space and an uneven right edge
   beats an even edge and stretched spaces. `text-wrap:pretty` then does the
   rest, keeping the rag shallow and refusing to leave a word alone on the
   last line. */
p{margin:2mm 0;text-align:$ALIGN;hyphens:$HYPH;-webkit-hyphens:$HYPH;
  text-wrap:pretty;orphans:2;widows:2;max-width:none}
li{text-wrap:pretty}
ul,ol{margin:2mm 0;padding-left:6mm} li{margin:0.8mm 0}
section{page-break-inside:auto}

figure{margin:4mm 0;page-break-inside:avoid;text-align:center}
img.shot{max-width:100%;max-height:110mm;object-fit:contain;
  border:0.3mm solid var(--border);border-radius:1.5mm}
img.icon{height:1.35em;vertical-align:-.35em;border:0.3mm solid var(--border);
  border-radius:1mm;margin:0 1mm}
figcaption{font-size:8.5pt;color:var(--grey-mid);margin-top:1.5mm;font-style:italic}

/* A cropped control, shown at the size it was captured. No upscaling: a
   500 pixel wide strip stretched to the column is a blur, and blur in a
   technical document reads as a mistake. */
.detail{margin:2.5mm 0;page-break-inside:avoid}
img.crop{max-width:100%;height:auto;border:0.3mm solid var(--border);
  border-radius:1mm;image-rendering:auto;display:block}
figcaption b{color:var(--blue);font-style:normal}

.note{background:var(--lav);border-left:1.2mm solid var(--blue);padding:2.5mm 3.5mm;
  margin:3mm 0;font-size:9.5pt;page-break-inside:avoid;border-radius:0 1.5mm 1.5mm 0}
.note.important{border-left-color:var(--red)}
.note b{color:var(--blue)} .note.important b{color:var(--red)}

.deflist{margin:2mm 0}
/* Flush left. The hanging indent was there to make the term stand out, but the
   term is already bold and coloured, so all the indent added was a ragged left
   edge on every entry that wrapped, which is most of them. */
.deflist div{padding:1.1mm 0;page-break-inside:avoid}
.deflist .name{font-weight:700;color:var(--navy)}
.deflist .col .name,.deflist .act .name{color:var(--blue)}
.deflist .type{color:var(--peri);font-size:9pt}
.deflist .req{color:var(--red);font-weight:700}
.deflist .sep{color:var(--grey-mid)}

.revisions table{border-collapse:collapse;width:100%;font-size:9.5pt}
.revisions th{text-align:left;padding:2mm;border-bottom:0.6mm solid var(--blue);
  color:var(--navy);font-size:8.5pt;text-transform:uppercase;letter-spacing:.05em}
.revisions td{padding:1.8mm 2mm;border-bottom:0.3mm solid var(--border);vertical-align:top}
.revisions .v{color:var(--blue);font-weight:700;white-space:nowrap}
"""


def _settle(page, timeout_ms: int = 90000):
    """Wait until every picture has actually decoded before printing.

    `wait_until="networkidle"` is meaningless here: the page is loaded over
    file://, where there is no network to go idle, so it returns at once and
    the PDF is printed from whatever has drawn so far. Small inline element
    shots win that race and full 1440x768 screenshots lose it, which is why the
    document came out with its little pictures present and most of its figures
    replaced by the browser's broken-image mark.

    `img.complete` alone is not enough either: it goes true for an image that
    failed, so the natural width is checked as well and a figure that genuinely
    cannot load is reported rather than silently dropped.
    """
    # Belt and braces: if anything upstream still emitted a lazy image, make it
    # eager here rather than waiting ninety seconds for a request that will
    # never be made.
    page.evaluate("""() => {
        document.querySelectorAll('img[loading="lazy"]').forEach(i => {
            i.loading = 'eager';
            const src = i.getAttribute('src');
            if (src) { i.setAttribute('src', src); }
        });
    }""")
    page.wait_for_function(
        "() => Array.from(document.images).every(i => i.complete)",
        timeout=timeout_ms)
    broken = page.evaluate(
        "() => Array.from(document.images)"
        ".filter(i => !i.naturalWidth).map(i => i.getAttribute('src'))")
    try:
        page.evaluate("() => document.fonts.ready")
    except Exception:
        pass
    if broken:
        raise RuntimeError(
            f"{len(broken)} image(s) could not be loaded for printing: "
            + ", ".join(str(b).split('/')[-1] for b in broken[:6]))


class PdfRenderer:
    """Builds a print HTML, then drives Chromium to print it."""

    def __init__(self, project, history=None):
        self.p = project
        self.history = history or []
        self.html = HtmlRenderer(project, drift_report=None, embed_images=False,
                                 lazy=False)
        _typo = Typography.load(getattr(project, "root", "."))
        self.theme = Theme.load(getattr(project, "root", "."))
        self.face = _typo.face("document")
        self.page = _typo.page
        self.text = _typo.text

    def _css(self) -> str:
        return print_css(self.face, self.page, self.text, self.theme)

    # ------------------------------------------------------------------
    def _cover(self) -> str:
        cfg, prod = self.p.config, self.p.config["product"]
        doc = cfg.get("document", {})
        rows = [
            ("Environment", doc.get("environment", "")),   # dropped below if empty
            ("Platform", prod.get("platform_version", "")),
            ("Edition", self.p.profile.name.title()),
            ("Revision", _revision_label(cfg.get("_release_label", "draft"))),
            ("Date", date.today().strftime("%d %B %Y")),
            ("Sections", str(sum(1 for n in self.p.nodes if n.section))),
        ]
        # A label with nothing beside it reads as a field that failed to fill,
        # not as a fact that does not apply, so an empty row is not printed.
        facts = "".join(f"<div><b>{_esc(k)}</b><span>{_esc(v)}</span></div>"
                        for k, v in rows if str(v).strip())
        # A company that has not named itself separately from its product is not
        # two lines of cover: printing the same word large and then again small
        # reads as a template that failed to fill rather than as a masthead.
        # The vendor is an eyebrow now, not a masthead, so the guard against
        # printing the same word twice only has to catch the case where one
        # contains the other: "Rise" over "Rise Hub" is a company above its
        # product and reads correctly, where "RISE" at 64pt over "Rise Hub" at
        # 32pt read as a template that had failed to fill.
        name, vendor = prod.get("name", ""), prod.get("vendor") or ""
        eyebrow = vendor.strip() if vendor.strip() and vendor.strip() != name.strip() else ""
        lead = _esc(doc.get("lead", "")) if doc.get("lead") else ""
        conf = _esc(doc.get("confidentiality", ""))
        return (f'<div class="cover">'
                f'<div class="band">'
                f'<div class="vendor">{_esc(eyebrow)}</div>'
                f'<div class="titles">'
                f'<div class="product">{_esc(name)}</div>'
                f'<div class="subtitle">{_esc(self.p.title())}</div>'
                f'</div></div>'
                f'<div class="low">'
                f'{f"<div class=lead>{lead}</div>" if lead else ""}'
                f'<div class="facts">{facts}</div>'
                f'<div class="conf"><span>{conf}</span>'
                f'<span>{_esc(eyebrow or name)}</span></div>'
                f'</div></div>')

    def _toc(self) -> str:
        depth = self.p.config.get("build", {}).get("toc_depth", 3)
        rows = []
        for node in self.p.nodes:
            if node.level > depth or node.section is None:
                continue
            anchor = node.id.replace(".", "-")
            rows.append(
                f'<div class="row l{node.level}"><a href="#{anchor}">'
                f'<span class="num">{node.number}</span>'
                f'<span>{_esc(node.section.title)}</span>'
                f'<span class="dots"></span></a></div>')
        return f'<div class="toc"><h1 class="first">Contents</h1>{"".join(rows)}</div>'

    def _revisions(self) -> str:
        if not self.history:
            return ""
        rows = "".join(
            f'<tr><td class="v">{_esc(r.get("version",""))}</td>'
            f'<td>{_esc(r.get("date",""))}</td>'
            f'<td>{_esc(r.get("summary",""))}</td></tr>'
            for r in self.history)
        return (f'<div class="revisions"><h1>Revision History</h1>'
                f'<table><thead><tr><th>Version</th><th>Date</th><th>Summary</th>'
                f'</tr></thead><tbody>{rows}</tbody></table></div>')

    def build_front_html(self, out_dir: Path) -> Path:
        """Cover plus contents: printed without running header and footer."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        title = f"{self.p.config['product']['name']} {self.p.title()}"
        page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                f'<title>{_esc(title)}</title><style>{self._css()}'
                # front matter prints at zero page margin so the cover bleeds
                # to the paper edge; padding moves inside the elements
                f'@page{{margin:0}}'
                # Full sheet, and the band bleeds to the paper edge because
                # the front matter prints at zero page margin.
                f'.cover{{height:297mm;padding:0;page-break-after:always}}'
                f'.toc,.revisions{{padding:15mm 18mm;page-break-after:auto}}'
                f'</style></head>'
                f'<body><main>{self._cover()}{self._toc()}{self._revisions()}'
                f'</main></body></html>')
        path = out_dir / "front.html"
        path.write_text(page, encoding="utf-8")
        return path

    def build_html(self, out_dir: Path, front: bool = True) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        self.html.asset_out = out_dir / "assets"
        self.html.asset_out.mkdir(parents=True, exist_ok=True)

        counter: dict = {}
        body = []
        front_html = f"{self._cover()}{self._toc()}{self._revisions()}" if front else ""
        for node in self.p.nodes:
            if node.section is None:
                continue
            html = self.html._section_html(node, counter)
            body.append(html)
        joined = "".join(body)
        # first chapter must not start with a forced page break, the TOC did that
        joined = joined.replace("<h1>", '<h1 class="first">', 1)

        title = f"{self.p.config['product']['name']} {self.p.title()}"
        page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                f'<title>{_esc(title)}</title><style>{self._css()}</style></head>'
                f'<body><main>{front_html}{joined}</main></body></html>')
        path = out_dir / "print.html"
        path.write_text(page, encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    def render(self, out_path: Path, work_dir: Path | None = None) -> Path:
        from playwright.sync_api import sync_playwright

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        work = Path(work_dir or out_path.parent / "_print")
        front_src = self.build_front_html(work)
        body_src = self.build_html(work, front=False)

        prod = self.p.config["product"]["name"]
        conf = self.p.config.get("document", {}).get("confidentiality", "")
        stamp = self.p.config.get("_release_label", "draft")
        face = Typography.load(getattr(self.p, "root", ".")).face("document")

        # Chromium renders header and footer templates in their own document,
        # not the page's. Two things bite there and both are silent:
        #
        #   * a size in `pt` is ignored and the text comes out microscopic, so
        #     the running header simply is not there and nobody notices until
        #     they look for a page number;
        #   * Chromium wraps the template in a #header / #footer div with its
        #     own padding, which pushes the content out of the margin box and
        #     clips it.
        #
        # Sizes in px, and the wrapper reset.
        # The band sits inside the page margin. Its own top padding is the
        # white space between the paper edge and the header text, and the rule
        # is pushed away from the text below it by the rest of the band. Both
        # come from content/typography.yaml so the spacing is yours to set.
        pg = Typography.load(getattr(self.p, "root", ".")).page
        reset = ("<style>#header,#footer{padding:0 !important;margin:0 !important;"
                 "font-size:9px !important;-webkit-print-color-adjust:exact;}</style>")
        chrome = (f"font-family:{face.css_body_attr()};font-size:9px;color:#A1A1A1;"
                  f"width:100%;padding:0 {pg.side}mm;box-sizing:border-box;"
                  "font-variant-numeric:tabular-nums;display:flex;"
                  "justify-content:space-between;align-items:center;")
        # The running header names the product being documented and the company
        # that makes it, and takes its rule from the theme. It used to print one
        # particular company's name, in that company's blue, on every page of
        # every document this engine produced.
        vendor = self.p.config.get("product", {}).get("vendor", "")
        mark = f"{vendor.upper()} | {prod}" if vendor and vendor.strip() != prod.strip() else prod
        accent = f"#{self.theme.brand_blue}"
        header = (f'{reset}<div style="{chrome}'
                  f'padding-top:{pg.edge}mm;'
                  f'border-bottom:0.5px solid {accent};padding-bottom:2.4mm;">'
                  f'<span style="color:{accent};font-weight:700">{_esc(mark)}</span>'
                  f'<span>Page <span class="pageNumber"></span> of '
                  f'<span class="totalPages"></span></span></div>')
        footer = (f'{reset}<div style="{chrome}'
                  f'padding-bottom:{pg.edge}mm;'
                  f'border-top:0.5px solid #D8DCEC;padding-top:2.4mm;">'
                  f'<span>{_esc(prod)}: {_esc(self.p.title())}</span>'
                  f'<span>{_esc(conf)} | {_esc(stamp)}</span></div>')

        front_pdf, body_pdf = work / "front.pdf", work / "body.pdf"
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_context().new_page()
            page.emulate_media(media="print")

            # Front matter carries no running header: a cover with a page
            # number across the top is the mark of a document nobody laid out.
            page.goto(front_src.resolve().as_uri(), wait_until="networkidle")
            _settle(page)
            page.pdf(path=str(front_pdf), format=pg.paper_name, print_background=True,
                     margin={"top": "0mm", "bottom": "0mm",
                             "left": "0mm", "right": "0mm"})

            page.goto(body_src.resolve().as_uri(), wait_until="networkidle")
            _settle(page)
            page.pdf(path=str(body_pdf), format=pg.paper_name, print_background=True,
                     display_header_footer=True,
                     header_template=header, footer_template=footer,
                     margin={"top": f"{pg.margin_top}mm",
                             "bottom": f"{pg.margin_bottom}mm",
                             "left": "0mm", "right": "0mm"})
            browser.close()

        _concat([front_pdf, body_pdf], out_path)
        return out_path


def _concat(parts, out_path: Path):
    """Join the front matter and body PDFs.

    Falls back to the body alone if pypdf is unavailable, so a missing optional
    dependency degrades the output rather than failing the build.
    """
    try:
        from pypdf import PdfWriter
    except ImportError:
        Path(out_path).write_bytes(Path(parts[-1]).read_bytes())
        return
    writer = PdfWriter()
    for part in parts:
        writer.append(str(part))
    with open(out_path, "wb") as fh:
        writer.write(fh)
