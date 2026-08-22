# Project layout

A Verba project is data. The engine is a package you upgrade; the project is
files you own and can read in a diff.

```
my-docs/
  content/
    doc.yaml              the outline, and therefore the numbering
    system.md             what this product is, in your words
    house.md              your writing rules (optional)
    screens.yaml          how to reach each screen, what to read off it
    masking.yaml          what must never appear in a screenshot
    masking-map.json      the real to placeholder mapping, kept stable
    environments.yaml     which system to talk to, and how to get in
    routes.yaml           the remembered address of every screen
    theme.yaml            which palette
    typography.yaml       sheet, margins, and how text is set
    sections/*.md         one file per section
    assets/               pictures, plus registry.json
    profiles/*.yaml       editions
  capture/<timestamp>/    one folder per crawl: live.json, inventory.json, shots
  review/                 the queue and what has been decided
  dist/                   what you publish
  .verba/                 history, browser sessions, locks
```

## content/

| File | What it decides |
|---|---|
| `doc.yaml` | Product and document metadata, the outline, build defaults, and any documented rule suppressions |
| `system.md` | What the product is, its vocabulary, and the domain rules the writer must not contradict. Given to the model ahead of every task |
| `house.md` | Your own writing rules. Falls back to a built in set when absent |
| `screens.yaml` | The registry. See [Screens registry](Screens-registry) |
| `masking.yaml` | Column, pattern and literal rules. See [Masking and names](Masking-and-names) |
| `masking-map.json` | Written by the crawl. One real value always becomes the same placeholder |
| `environments.yaml` | Connections. See [Connections and sign in](Connections-and-sign-in) |
| `theme.yaml` | Which of the five themes |
| `typography.yaml` | Paper, margins, alignment, hyphenation, figure width, contents depth |
| `sections/` | The writing. See [Sections](Sections) |
| `profiles/` | Editions. See [Editions](Editions) |

Nothing under `content/` is generated except `masking-map.json` and
`assets/registry.json`. Both are readable, and both are meant to be committed.

## capture/

One folder per crawl, named by timestamp. Inside:

| File | What it holds |
|---|---|
| `live.json` | Every label read off every screen, per screen |
| `inventory.json` | What was visited, what was skipped, and why |
| `*.png` | The photographs, already masked |
| `manifest` | The read only record: every request the browser was allowed to make |

Old captures are kept. Drift always compares against the newest, but History
can point at any of them.

## review/

| File | What it holds |
|---|---|
| `DRIFT.md` | The queue, human readable |
| `proposals.json` | What the system offers to change, and its confidence |
| `decisions.json` | What has been accepted, declined, and by whom |
| `knowledge.json` | What the crawl has learned about the product over time |
| `survey.json` | What the document is missing, before a crawl |
| `incidents.json` | Crawls that failed, and how |
| `auto.json` | The last loop run: every step, what it changed, what it reverted |
| `picture-match.json` | Whether each figure is of what its section describes |

## .verba/

| Path | What it holds |
|---|---|
| `history/log.jsonl` | Every change ever made, with a diff and a restore |
| `sessions/` | Saved browser sessions for single sign on. Never a password |
| `*.lock` | Advisory locks, so two consoles cannot lose each other's work |

## What to commit

Commit `content/`, and commit `review/decisions.json` so a teammate's
acceptances are not repeated. Commit `capture/` only if you want the evidence in
history; it is large. `dist/` is output. `.verba/sessions/` is a credential and
must never be committed, which is why the scaffold writes a `.gitignore` that
excludes it.
