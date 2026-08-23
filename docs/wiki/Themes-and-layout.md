# Themes and layout

Design is a setting, not a fork. Nothing about how the document looks requires
editing a template or a renderer.

## Themes

Five, each contrast measured rather than eyeballed.

| Theme | Register |
|---|---|
| **Slate** | The neutral default. Indigo on near black, cool grey panels. Reads as a manual rather than a brochure, and gets out of the way of screenshots, which are the loudest thing on any page |
| **Atlas** | Deep teal and cool grey. Engineering document register: precise, quiet, a little clinical. Pairs well with dense field tables |
| **Ember** | Warm charcoal with burnt amber. Softer than the blues without being informal. Good for onboarding material read once |
| **Forest** | Deep green, low saturation. Calm and unbranded, for infrastructure and operations rather than a product someone is selling |
| **Ink** | Editorial monochrome with one warm accent. Almost no colour, so the accent means something. For documents printed and read end to end |

```bash
verba themes            # all five, with what each is for
verba themes --use ink
verba themes --show     # the resolved values
verba themes --check    # measure its contrast
```

`--check` measures every text colour against the background it is actually
painted on, not against white. A palette that passes on paper and fails in a
panel is the normal way this goes wrong.

## A palette of your own

A house palette belongs to the document, not to the engine: it is the one
design decision that cannot be general, and putting it in the engine means
every project carries every other project's brand.

```
my-docs/
  themes/
    house.yaml        # or content/themes/house.yaml
```

```yaml
label: House
about: The house palette. Brand blue on near-black text.
brand_blue: "#3137DB"
```

```bash
verba themes --use house
```

A project theme wins over a built-in of the same name, and `verba themes` lists
both.

**A theme that cannot be found never fails a build.** The document renders in
the default and the substitution is reported as `DESIGN-04`, because somebody
publishing a release is trying to ship a document and the thing that is wrong
is the colour of its headings. A traceback out of a release is the worst
possible way to learn that.

## Typefaces

```bash
verba fonts
```

Four faces ship: Inter, Source Sans 3, IBM Plex Sans, and the system default.
Each carries its own body size, line height and tracking, because setting them
all at one size is how a document ends up looking wrong in a way nobody can name.
Inter has a very large x height and is set smaller and tracked in; Source Sans
is small on the body and set larger.

Each also names a DOCX face and a fallback, so a machine without the font still
produces a sensible Word file rather than Times New Roman.

`verba fonts` reports what the outputs will actually be set in **on this
machine**, which settles most arguments about kerning before they start.

## The cover

Two parts, and nothing floats. A field carries the identity, and the sheet
below it carries the facts:

- the vendor as a small-caps eyebrow, the product as the only large thing on
  the page, the subtitle under it, and a rule closing the field
- a one-sentence lead from `document.lead` in `doc.yaml`, saying what the
  reader is holding
- the facts in two ruled columns, and the confidentiality line at the foot

It used to run the vendor at 64pt and the product under it at 32pt, which on a
document whose vendor and product share a word printed the same word twice, in
two sizes, under a third of a page of nothing.

## The page

```bash
verba layout
verba layout --paper Letter --side 20 --align justify --figure-width 14
```

| Setting | What it is |
|---|---|
| `--paper` | A4, A5, Letter or Legal. Sets the sheet for the PDF and the DOCX together, so the two cannot disagree |
| `--side` | Left and right margin, mm |
| `--edge` | Paper edge to header and footer text, mm |
| `--header-band` / `--footer-band` | Their heights, rule included, mm |
| `--gap` | Air under the header rule, mm |
| `--align` | `left` or `justify` |
| `--hyphens` | `on` or `off` |
| `--figure-width` | How wide a screenshot prints, cm |
| `--toc-depth` | Deepest level on the contents page, 1 to 4 |

## Changes are judged before they are written

Every layout change is checked against **the page you are choosing**, not the
one currently on disk:

```
refused: a 15cm figure does not fit the 11.2cm column on A5 at 18mm margins
```

Checking against the current page would let you switch to A5 and only find out
afterwards. All of it is judged as one decision, so a paper change and a margin
change in the same command are evaluated together.

## Why the decisions are recorded

```bash
verba design
```

Prints what was decided about how this looks, and why. Design decisions get
re litigated every time someone new looks at the document, and a recorded reason
is the difference between a discussion and a rerun of the same discussion.
