# Verba

**Technical documentation built from the running system, not from memory.**

Every product manual starts accurate and then quietly stops being accurate. A
column gets renamed, a tab moves, a button loses its label, and nothing in the
document knows. The screenshots are the worst of it: they age silently, and a
reader trusts a picture more than a paragraph.

Verba points a browser at your product, photographs every screen you care about,
reads the actual labels off the page, and tells you exactly where the document
and the software have drifted apart. Then it builds a DOCX, a PDF and an HTML
preview from one content tree.

It never writes to the system it documents. That is enforced in the browser, not
by being careful.

```bash
pip install git+https://github.com/GiladBronshtein/verba.git
playwright install chromium

verba new my-docs        # six questions
cd my-docs
verba build --pdf        # you have a document
```

> Not on PyPI yet, so install from the repository. The package name is reserved
> as `verba-docs` for when it is.

---

## What makes it different

Most documentation tools help you write. This one helps you stay right.

**Drift is a queue, not a discovery.** After a crawl, the labels read off each
screen are compared against what your sections claim. Renames are detected as
renames rather than reported as an unrelated deletion plus an addition. High
confidence changes are marked `[!]`, judgement calls `[?]`, and the mechanical
ones apply with one click.

```
### 4.2.1 Publishers List
- [!] removed column `Last Modified`
- [!] added column `REVENUE SHARE`
- [?] renamed column `ID` -> `PUBLISHER ID`
```

**Numbering is derived.** Section files never contain a number. Insert a section
and everything below it renumbers, in the body and on the contents page
together, so the two can never disagree the way hand-numbered documents always
eventually do.

**A capture proves a control exists. It does not prove what the control means.**
So the writer is told to leave `TODO: describe this.` rather than invent a
plausible purpose from a button's name. Confident, fluent and wrong is the worst
failure mode a documentation tool has.

**Selectors get repaired instead of failing the run.** When a step stops
resolving, the crawler snapshots what the page actually offers, asks a model for
a replacement, and then *verifies that answer in the live page before believing
it*. A selector matching nothing is never proposed. Repairs are proposals, never
silent writes.

---

## Nothing is ever written to the system you document

This is the guarantee the rest of the tool rests on, and it is enforced in code.

As soon as sign-in finishes, a route handler in the browser aborts every request
whose method is not `GET`, `HEAD` or `OPTIONS`. A stray click on Save fires its
request and the request dies in the browser: the product never sees it. Sign-in
is the single permitted write, and every sign-in request is logged and reported
in the capture manifest, so the one exception stays auditable.

Two further layers sit on top. The step interpreter refuses `fill` outside
sign-in and refuses Enter presses, so no form can be completed. The screen
registry is linted before every crawl for steps that read like a commit.

Verified end to end against a mock server that records what it receives: a step
that deliberately clicked Save produced

```
blocked write: PUT http://127.0.0.1:8899/api/publishers/1
```

and the server's write log contained only the sign-in POST.

---

## Sixty seconds

`verba new` asks six questions, every one with a default you can take by
pressing Return, and writes a project that **builds immediately**. Not a
skeleton with gaps to fill: a real document with a real first section, a screen
registry and a theme, which renders to PDF before you have typed anything else.

```
What is the product called? [My Product]: Acme Console
Who makes it? [Acme Console]: Acme Inc
What does it do, in one sentence?: Where operators configure campaigns.
Where does it live? [https://example.com]: https://console.acme.test

How do you sign in?
  1. form (default) : a username and password typed into the product's own sign-in page
  2. sso            : single sign-on, where you sign in once in a real browser
  3. none           : no sign-in needed

Which look?
  1. slate (default) : The neutral default
  2. ink             : Editorial monochrome with one warm accent
  3. atlas           : Deep teal and cool grey
  4. ember           : Warm charcoal with a burnt amber accent
  5. forest          : Deep green, low saturation
```

Then open the console and work from there:

```bash
verba console
```

---

## Telling it what your product *is*

A crawler can prove a control exists. It cannot tell you what the control is
for, what your company calls it, or which of two plausible readings is right.
That knowledge has to come from a person, once.

So every project carries `content/system.md`: a plain page describing the
product, its vocabulary, and the rules that are true of it. It is handed to the
model with every writing task, ahead of the craft rules, and it wins where they
disagree. Nothing in it is generated and nothing is inferred.

```markdown
## Vocabulary

- **Publisher** : an account that supplies inventory. Never call it a "seller".
- **Connection** : one route to a demand partner. A partner may have several.

## Rules that are true of this system

- A connection inherits its floor price from the partner unless it sets its own.
- Blocklists combine by union, so the most restrictive setting always wins.

## Do not document

- Internal identifiers, API routes and developer-facing values.
```

---

## Design is a setting, not a fork

Five built-in themes, every one measured rather than eyeballed: body text at
7:1 and the accent at 4.5:1, checked against the ground each colour is actually
painted on, including its own tinted callout, which is where accents usually
fail.

```bash
verba themes                 # what is available, and what each is for
verba themes --use ink
verba themes --check         # measure whatever you have set
```

Override single tokens without forking a theme, because most companies have one
brand colour and no opinion about the other nineteen:

```yaml
use: slate
tokens:
  brand_blue: "0F766E"
```

Page setup is a setting too, and the PDF and the DOCX read the same one, so the
two outputs cannot be laid out differently:

```bash
verba layout --paper Letter --side 20 --align justify --figure-width 14
```

```
sheet          A4  (210 x 297 mm)
side margins   18 mm
top / bottom   29 / 25.3 mm  (edge 12 + band 8 + gap 9)
column         17.4 cm of text
body text      justify, hyphens on
figures        15 cm wide
contents       down to level 3
```

Every change is judged before any of it is written, against the page you are
choosing rather than the one on disk. Moving to A5 and narrowing the figures in
one edit is accepted as a single coherent change; asking for A5 while keeping
15cm figures is refused whole, with the reason:

```
refused: a 15cm figure does not fit the 11.2cm column on A5 at 18mm margins
```

---

## Editions

One content tree, several documents. An edition declares what it carries, so
"what is in the customer edition" is one list you can read rather than a
property scattered across every section file.

```yaml
# content/profiles/acmecorp.yaml
name: acmecorp
title_suffix: " (AcmeCorp Edition)"
sections:
  exclude: [admin-tools]      # drops the branch, and the numbering closes up
vars:
  operator:
    name: AcmeCorp
```

Sections write `{{ operator.name }}` rather than naming a company. A neutral
edition is then held to that automatically: the names it must not print are read
off your *other* editions, so nothing has to be listed twice.

```bash
verba edition                          # what this edition carries, and why not
verba edition drop admin-tools
verba --profile acmecorp build --pdf
```

---

## Screenshots that do not leak your customers

A screenshot of a live account carries one customer's data into another
customer's documentation. Rules in `content/masking.yaml` rewrite real values in
the page's DOM immediately before each screenshot is taken, and in the labels
read off the page afterwards.

```yaml
columns:
  - header: NAME
    with: "Example Account {n}"
patterns:
  - name: entity-id
    pattern: "\\b[0-9a-f]{24}\\b"
    with: "6a000000000000000000{n:04d}"
```

Column rules matter most: they catch every name in a list view without knowing
the names in advance, which is necessary because the data changes between
crawls. A name learned from a column is masked everywhere else on the page too,
including breadcrumbs and headings.

The substitution happens in the browser and nothing is submitted, so this stays
consistent with the guarantee above. The mapping is stored, so a given real
value always becomes the same placeholder, in this crawl and in crawls months
from now, and screenshots stay stable between revisions.

A connection can be marked as holding real data, and capturing it unmasked is
then refused outright.

---

## The loop

```
capture  ->  drift  ->  author  ->  lint  ->  build  ->  release
   |          |           |          |         |          |
 live UI   review     section     rules     DOCX +    versioned
 crawl     queue      edits      enforced   preview   output
```

Or hand the whole thing over:

```bash
verba auto
```

It crawls, fills the gaps the evidence can answer, fixes the writing, applies
the mechanical differences, adopts the fresh screenshots, and stops where a
person is genuinely needed. What makes it safe to leave alone is not confidence,
it is measurement: every step is applied, the rules are counted again, and a
step that made the document worse is put straight back.

Three things it will not do: write to your system, accept a figure from a screen
that landed somewhere else, or decide something a person owns.

---

## Commands

| Command | What it does |
|---|---|
| `verba new` | start a new document, without a blank page |
| `verba console` | the management interface, and the easiest way in |
| `verba status` | every section with status, freshness and open drift |
| `verba capture` | crawl the live system into a timestamped run |
| `verba drift` | compare the newest capture to the document |
| `verba lint` | run the content rules |
| `verba build --pdf` | render DOCX, PDF and the HTML preview |
| `verba release --version v2` | cut a version, never overwriting an output |
| `verba themes` | how the document looks |
| `verba layout` | the sheet, the margins, how text is set |
| `verba edition` | which sections this edition carries |
| `verba auto` | the whole loop, stopping only where you are needed |
| `verba survey` | what the document is missing, before you crawl |
| `verba masking` | the real-to-placeholder mapping |
| `verba routes` | the remembered address of every screen |
| `verba heal` | review the selector repairs a crawl proposed |

---

## The console

`verba console` opens a local web app at `127.0.0.1:8800`. Everything the CLI
does, it does, and nothing more: both drive the same project objects, so they
can never disagree about state.

The per-section page is the main working surface. Recapture one screen and adopt
the result. Edit the Markdown with a live preview beside it. See the differences
against the live system, each with Apply where the change is mechanical and a
plain explanation where it needs judgement. Read the raw labels the last capture
took off the page, so you can check the document against evidence rather than
against memory.

---

## Writing assistance

Five model-backed actions, each of which returns a **proposal**: a line diff you
accept, open in the editor, or discard. Nothing reaches a section file
otherwise, and a proposal that does not parse as a valid section, or that tries
to change a section id, is rejected before you ever see it.

The model is reached in this order, and the console names which it is using:

1. **A gateway**, if `VERBA_GATEWAY` is set. For teams that meter and bill
   model usage centrally.
2. **The Anthropic API**, if `ANTHROPIC_API_KEY` is set.
3. **The Claude Code CLI**, which needs no key at all.

If none is reachable the panel says so and the rest of the pipeline is
unaffected. `ANTHROPIC_BASE_URL` is deliberately not consulted: it is set per
shell and can point somewhere you did not choose for this pipeline.

---

## Requirements

- Python 3.11 or newer
- Chromium, via `playwright install chromium`, for capture and PDF

Credentials never live in the repository. A form login keeps its password in the
OS keychain (`verba env password <id>`); single sign-on keeps a saved browser
session and no password at all.

---

## Tests

```bash
python3 tools/selftest.py
```

The suite builds a project from scratch with the wizard and tests the engine
against that, rather than against a hand-made fixture. An engine whose claim is
that it works on a product it has never seen should be tested that way.

---

## License

MIT.
