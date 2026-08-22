<div align="center">

<img src="docs/img/logo.svg" width="76" alt="">

# Verba

**Technical documentation that checks itself against the running product.**

Point it at your system. It signs in, photographs every screen, reads the real
labels off the page, reads what your document says about them, and tells you
exactly where the two have drifted apart. Then it fixes what it can and hands
back only what genuinely needs you.

It can never write to the system it documents. That is enforced in the browser,
not by being careful.

[![check](https://github.com/GiladBronshtein/verba/actions/workflows/check.yml/badge.svg)](https://github.com/GiladBronshtein/verba/actions/workflows/check.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-3137DB)](LICENSE)
[![Read only](https://img.shields.io/badge/writes%20to%20your%20system-never-1F9D55)](#it-can-never-write-to-your-system)

</div>

---

<img src="docs/img/console-changes.png" alt="The console: a six-step process down the left, and a review queue listing added and removed columns and tabs with Apply and Review on each">

<div align="center"><sub>
The product changed underneath the document. Every difference, with what to do about it.<br>
Everything in this README is reproducible from the demo that ships with the repo, in <a href="#try-it-in-two-minutes">two minutes</a>.
</sub></div>

---

## The problem

Every product manual starts accurate and quietly stops being accurate. A column
gets renamed, a tab disappears, a button loses its label, and nothing in the
document knows. The screenshots are the worst of it: they age silently, and a
reader trusts a picture more than a paragraph.

The usual answer is discipline, which fails, or a rewrite every quarter, which
is expensive and still wrong by the time it ships.

Verba treats the running system as the source of truth and the document as
something to be held against it, continuously, by a process that can do most of
the work without asking.

## Two minutes

```bash
pip install "git+https://github.com/GiladBronshtein/verba.git#egg=verba-docs[assist]"
playwright install chromium

verba new my-docs        # six questions, every one with a default
cd my-docs
verba build --pdf        # you already have a document
verba console            # and this is where you work
```

`verba new` writes a project that **builds immediately** — a real first section,
a screen registry, a theme — so the first thing you meet is a PDF rather than an
error about a rule you have not read.

---

## What it does

### The loop

```
connect  ->  capture  ->  review  ->  write  ->  check  ->  publish
```

That sequence is the interface. Each step carries its own state, the one with
work in it is marked, and every step stays clickable, because a person who wants
Publish on a Tuesday is working, not lost.

| | |
|---|---|
| **Crawl a live system** | Signs in, walks every screen, photographs it at a fixed viewport, and reads the labels off the page |
| **Detect drift** | Compares those labels with what your sections claim. Renames are detected as renames, not as a deletion plus an addition |
| **Fingerprint screenshots** | A changed screen is flagged even when no label moved |
| **Fix what can be fixed** | Applies mechanical changes, writes missing descriptions from evidence, rewrites what the rules object to, adopts fresh pictures |
| **Measure and revert** | Every step is applied, the rules are counted again, and anything that made the document worse is put straight back |
| **Hand back only decisions** | What it cannot justify from evidence comes back with the reason and the choice |

### What the model does

A model is configured for the writing. It is used for everything it is actually
good at, not just prose.

| | |
|---|---|
| **Writes missing descriptions** | From the crawl evidence, and leaves a marker rather than inventing a meaning the evidence does not support |
| **Rewrites to house style** | Triggered by the rule findings that name a rewrite as their fix |
| **Reads every section against the crawl** | Not label-to-label: does what this section *says* survive contact with the screen, and does it leave out what the screen is for |
| **Looks at every picture** | Checks each screenshot for real customer names, against the exact list of strings that must never appear |
| **Checks each picture is of the right thing** | A chapter called Dashboard Overview illustrated by the accounts list passes every other rule |
| **Decides the residue** | From a closed menu: repoint a figure at the right picture, drop one that cannot be published, or say plainly that this one is yours |

Every model action is measured like any other change, judged one at a time, and
recorded in History with its reasoning. Nothing is written that a person cannot
put back.

### Safety

| | |
|---|---|
| **Never writes to your system** | Enforced in the browser. Every non-GET request is aborted after sign-in |
| **Masks real names** | Rewrites customer names and identifiers in the DOM immediately before each screenshot |
| **Stable placeholders** | One real value always becomes the same placeholder, so figures never contradict each other |
| **Refuses unmasked production** | A connection marked as holding real data cannot be captured unmasked |
| **Locked, atomic writes** | Two consoles cannot lose each other's work |
| **Everything reversible** | Every change is in History, by whom, with a diff and a restore |

### The document

| | |
|---|---|
| **DOCX, PDF and HTML** | One content tree, three outputs |
| **Derived numbering** | Section files carry no number, so inserting one renumbers the body and the contents page together |
| **Editions** | One tree, several documents. An edition declares what it carries |
| **Themes** | Five, each contrast-measured rather than eyeballed |
| **Page setup** | Paper, margins, alignment, hyphenation, figure width, contents depth. The PDF and the Word file read the same numbers |
| **Versioned releases** | `release --version v2` refuses to overwrite an output |

---

## What it looks like

<table>
<tr>
<td width="50%"><img src="docs/img/console-capture.png" alt="Capture"><br>
<sub><b>Capture</b> — what the last crawl found, the read-only guarantees, and
screens photographed that no section shows.</sub></td>
<td width="50%"><img src="docs/img/console-screens.png" alt="Screens"><br>
<sub><b>Screens</b> — what gets photographed and what is read off each one. It
reports screens that read nothing and so can never detect a change.</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/img/console-names.png" alt="Names"><br>
<sub><b>Names</b> — which real names must never appear, every replacement made
so far, and any picture nobody has checked.</sub></td>
<td width="50%"><img src="docs/img/console-writer.png" alt="The writer"><br>
<sub><b>The writer</b> — paste a key, pick a model by what it is good at. The
gateway settings fold away for the people who have one.</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/img/console-sections.png" alt="Sections"><br>
<sub><b>Sections</b> — every section with its status, freshness, the screen it
is evidenced by, and what is flagged against it.</sub></td>
<td width="50%"><img src="docs/img/console-design.png" alt="Design"><br>
<sub><b>Design</b> — the palette, the typeface, the sheet and the margins. The
PDF and the Word file read the same numbers.</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/img/console-section.png" alt="A section open"><br>
<sub><b>A section</b> — the outline down the side, what is outstanding, the
source and its preview. Recapture just this screen from here.</sub></td>
<td width="50%"><img src="docs/img/console-documents.png" alt="Documents"><br>
<sub><b>Documents</b> — every system you document, in one console. Switch
between them, or start another.</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/img/console-editions.png" alt="Editions"><br>
<sub><b>Editions</b> — what each edition carries. Drop a chapter and the
numbering closes up behind it.</sub></td>
<td width="50%"><img src="docs/img/console-design.png" alt="Design"><br>
<sub><b>Design</b> — the palette, the typeface, the sheet and the margins. The
PDF and the Word file read the same numbers.</sub></td>
</tr>
</table>

Both themes are real, and both are measured: every text colour is checked
against the background it is actually painted on.

<details>
<summary>The same screen in light mode</summary>
<img src="docs/img/console-changes-light.png" alt="The review queue in light mode">
</details>

## What it produces

<table>
<tr>
<td width="50%"><img src="docs/img/doc-cover.png" alt="The generated cover page"></td>
<td width="50%"><img src="docs/img/doc-page.png" alt="A generated body page with a numbered figure"></td>
</tr>
</table>

---

## Drift is a queue, not a discovery

Each screen declares what to read off it. After a crawl, those labels are
compared with what your sections claim.

```
### 4.1 Accounts List
- [!] added column `HEALTH`
- [!] removed column `Plan`
- [!] added column `TIER`

### 4.2 Account Detail
- [!] added tab `Integrations`
```

`[!]` is high confidence, `[?]` needs judgement. Mechanical changes apply on
their own; anything needing a decision says so instead of offering a button.

## A capture proves a control exists. It does not prove what it means.

So the writer is told to leave `TODO: describe this.` rather than invent a
plausible purpose from a button's name, and the marker is refused at build time
so it can never ship. Confident, fluent and wrong is the worst failure a
documentation tool has.

What the product actually *is* comes from a person, once, in
`content/system.md`, and it is given to the model ahead of the writing rules.

```markdown
## Vocabulary
- **Publisher** : an account that supplies inventory. Never "seller".
- **Connection** : one route to a demand partner. A partner may have several.

## Rules that are true of this system
- A connection inherits its floor price from the partner unless it sets its own.
- Blocklists combine by union, so the most restrictive setting wins.
```

The writing rules themselves live in `content/house.md` when you want your own,
and fall back to a built-in set when you do not. A team that documents route
paths on purpose can say so.

---

## It can never write to your system

This is the guarantee everything else rests on, and it is enforced in code.

As soon as sign-in finishes, a route handler in the browser aborts every request
whose method is not `GET`, `HEAD` or `OPTIONS`. A stray click on Save fires its
request and the request dies in the browser: your product never sees it. Sign-in
is the single permitted write, and every sign-in request is logged and reported
in the capture manifest, so the one exception stays auditable.

Two further layers sit on top. The step interpreter refuses `fill` outside
sign-in and refuses Enter presses, so no form can be completed. The screen
registry is linted before every crawl for steps that read like a commit.

Verified end to end by a test that stands up a server which records what it
receives, drives a real browser at it with the guard armed, and clicks a button
wired to a `PUT`:

```
blocked write: PUT http://127.0.0.1:8899/api/accounts/1
```

The server's write log contained only the sign-in POST. The test fails if the
guard is removed, which was checked.

## Screenshots that do not leak your customers

A screenshot of a live account carries one customer's data into another
customer's documentation. Rules rewrite real values in the page's DOM
immediately before each screenshot is taken.

```yaml
columns:
  - header: NAME
    with: "Example Account {n}"
    as: account
patterns:
  - name: account-id
    pattern: "acc_[0-9a-f]{20}"
    with: "acc_{n:020d}"
```

Column rules catch every name in a list view without knowing the names in
advance, which matters because the data changes between crawls. A name learned
from a column is masked everywhere else on the page too, and the mapping is
stored, so one real value always becomes the same placeholder.

Masking protects what a crawl takes and says nothing about a picture that
arrived some other way. Those are found, reported, and looked at.

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
  exclude: [admin-tools]      # drops the branch; numbering closes up
vars:
  operator:
    name: AcmeCorp
```

Sections write `{{ operator.name }}` rather than naming a company. A neutral
edition is held to that automatically: the names it must not print are read off
your *other* editions.

## Design is a setting, not a fork

```bash
verba themes                 # what is available, and what each is for
verba themes --use ink
verba themes --check         # measure whatever you have set
verba layout --paper Letter --side 20 --align justify --figure-width 14
```

Every layout change is judged before any of it is written, against the page you
are choosing rather than the one on disk:

```
refused: a 15cm figure does not fit the 11.2cm column on A5 at 18mm margins
```

## When a selector breaks

```bash
verba capture --heal
verba heal --apply
```

On a failure the crawler snapshots what the page actually offers, asks a model
for a replacement, and **verifies that answer in the live page before believing
it**. A selector that matches nothing is never proposed. Repairs are proposals,
because a selector that resolves is not necessarily the right one.

---

## Try it in two minutes

Everything in this README came from a demo that ships with the repository: a
small fictional admin console called Meridian, and a document built from it.
Nothing points at anyone's real system.

```bash
git clone https://github.com/GiladBronshtein/verba.git && cd verba
pip install -e ".[assist]" && playwright install chromium

python3 examples/meridian/serve.py &            # the product being documented
export VERBA_USER=ops@meridian.test VERBA_PASSWORD=anything

verba --root examples/meridian-docs capture     # photograph it
verba --root examples/meridian-docs build --pdf
verba --root examples/meridian-docs console     # and look at it
```

To watch drift appear, change Meridian — rename a column in
`examples/meridian/serve.py`, restart it, and capture again.

## Commands

| Command | What it does |
|---|---|
| `verba new` | start a new document, without a blank page |
| `verba console` | the management interface, and the easiest way in |
| `verba status` | every section with status, freshness and open drift |
| `verba capture` | crawl the live system into a timestamped run |
| `verba drift` | compare the newest capture to the document |
| `verba fix` | settle everything the system can, and say what is left |
| `verba fix --full` | photograph every screen first, then do that |
| `verba auto` | the whole loop, stopping only where you are needed |
| `verba lint` | run the content rules |
| `verba build --pdf` | render DOCX, PDF and the HTML preview |
| `verba release --version v2` | cut a version, never overwriting an output |
| `verba themes` / `verba layout` | how the document looks, and how the page is set |
| `verba edition` | which sections this edition carries |
| `verba survey` | what the document is missing, before you crawl |
| `verba masking` | the real-to-placeholder mapping |
| `verba heal` | review the selector repairs a crawl proposed |

## Reaching a model

Three routes, tried in order, and the console names whichever it is using:

1. **Your organisation's AI service**, if one is configured, so usage stays
   metered centrally. Verba asks it what models it carries and offers you those,
   rather than guessing at a list.
2. **Your own Claude key**, pasted into the console and kept in the OS keychain,
   never in the project and never in a log.
3. **The Claude Code CLI**, which needs no key. It cannot be given an image, so
   the picture checks need one of the first two.

This speaks the Anthropic Messages API. Claude works directly, and a gateway can
translate for models that do not: on one real deployment the picker offered
twelve models including GPT variants, and they answer.

## Requirements

- Python 3.11 or newer
- Chromium, via `playwright install chromium`
- `pip install "verba-docs[assist]"` for the writing and the picture checks

Credentials never live in the repository. A form login keeps its password in the
OS keychain or in `VERBA_PASSWORD` for scheduled runs; single sign-on keeps a
saved browser session and no password at all.

## Tests

```bash
python tools/selftest.py
```

The suite builds a project from scratch with the wizard and tests the engine
against that, rather than against a hand-made fixture. An engine whose whole
claim is that it works on a product it has never seen should be tested that way.

It runs on every push, with a browser, against the demo document. The first
three things CI found were that the package did not build, that `numpy` was
imported and never declared, and that a duplicate dictionary key had been
silently discarding every section's own note.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Two rules there are not style
preferences: nothing may write to the system being documented, and nothing
decides what a person owns.

## License

MIT.
