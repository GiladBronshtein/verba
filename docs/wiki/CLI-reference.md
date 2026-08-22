# CLI reference

```
verba [--root PATH] [--profile EDITION] <command> [options]
```

| Global | Meaning |
|---|---|
| `--root` | The project directory. Defaults to the current one |
| `--profile` | Which edition to work on. Defaults to `defaults.profile` in `doc.yaml` |

`verba` and `python3 -m verba` are the same thing. The second is the safe one
when several Pythons are on the machine.

---

## Looking

### `verba status`
Every section with its status, freshness and open drift, plus what is flagged.
The first command to run, and usually the only one you need to know.

### `verba survey [--crawl] [--json]`
What the document is missing, **before** you crawl. `--crawl` then photographs
exactly the screens that would close a gap, which is the cheap way to fill a new
document.

### `verba drift [--capture RUN] [--print-report]`
Compare the newest capture with what the sections claim. `--capture` points at
an older run.

### `verba lint [--level all|error|warning|info] [--strict]`
Run the content rules. `--strict` exits non-zero on errors, for CI. See the
[Rule reference](Rule-reference).

### `verba knowledge` / `verba decisions` / `verba changelog`
What the crawl has learned, what has been decided, and the derived changelog.

### `verba routes` / `verba masking` / `verba forms` / `verba fonts`
The remembered address of every screen; the real to placeholder mapping; every
form, field and rule the crawl read; and what the outputs are actually set in on
this machine.

---

## Crawling

### `verba capture [options]`

| Option | Does |
|---|---|
| `--screens a,b,c` | Only these screen ids |
| `--section ID` | Only the screens that section uses |
| `--headed` | Show the browser. For working out why a selector fails |
| `--no-mask` | Skip masking. Refused when the connection sets `mask_required` |
| `--replay-steps` | Re-run the steps without re-photographing |
| `--heal` | Let the model propose replacements for selectors that broke |
| `--wait-for-signin` | Open a browser and wait for you to sign in, second factor and all, then carry on |
| `--no-sweep` | Do not offer to fill gaps afterwards |

### `verba env list|use|verify|signin|password [id]`
Connections, including the `handoff` mode for products that ask for a code. `verify` is what to run when a crawl fails: it separates the
network, the credentials and the selectors. See
[Connections and sign in](Connections-and-sign-in).

### `verba heal [--apply]`
Review the selector repairs a crawl proposed, and apply them. See
[Healing selectors](Healing-selectors).

### `verba incidents [--export] [--signature S] [--resolve ID] [--note TEXT]`
Crawls that failed, and how. `--export` writes a brief a coding agent can act on.

---

## Fixing

### `verba fix [--rounds N] [--no-crawl] [--full]`
Settle everything the system can, and say what is left. `--full` photographs
every screen in the registry first, which is what "run everything" has to mean.
See [The loop](The-loop).

### `verba auto [--rounds N] [--no-crawl]`
The same loop, deciding per round whether a crawl would help.

### `verba sweep [--section ID] [--images-only] [--apply-images]`
Review the crawl and propose the gaps filled.

### `verba tidy [--section IDS] [--apply]`
Fix the writing across the document, as one decision rather than section by
section.

### `verba note "..." [--section ID] [--figure F] [--reopen ID] [--drop ID]`
Write down something you noticed. The loop picks it up on its next run and does
what you asked for.

---

## Writing

### `verba section new|show|set|verify [id] [values...]`

```bash
verba section new accounts.exports --title "Exports" --screen accounts.exports
verba section show accounts.list
verba section set accounts.list status verified
verba section verify accounts.list --date 2026-08-22
```

---

## Design

### `verba themes [--use NAME] [--show] [--check]`
Five themes. `--check` measures every text colour against the background it is
actually painted on.

### `verba layout [--paper] [--side] [--edge] [--header-band] [--footer-band] [--gap] [--align] [--hyphens] [--figure-width] [--toc-depth]`
The sheet, the margins, how text is set. Judged against the page you are
choosing before any of it is written.

### `verba fonts [--document NAME] [--console NAME] [--verify]`
Which typefaces the outputs and the console are set in.

### `verba design [--check] [--find Q] [--add TEXT --because WHY]`
What was decided about how this looks, and why.

### `verba edition [show|add|drop|reset] [id]`
Which sections this edition carries. See [Editions](Editions).

---

## Publishing

### `verba build [--pdf] [--out DIR] [--label L] [--force] [--history]`
Render the DOCX, the HTML preview, and with `--pdf` the PDF.

### `verba release [--version vN] [--summary TEXT] [--force]`
Cut a version. Refuses to overwrite an output that already exists, which is why
`--force` exists and why you should think before using it.

### `verba history [id] [--limit N] [--restore ID]`
Every recorded change, and restore one.

> When restoring, read the stored content rather than trusting the timestamps.
> The newest revision of a damaged section is the damage. This is not
> theoretical: the first restore attempt during development picked already
> damaged revisions because they were the most recent.

---

## The rest

### `verba new [dir] [--product] [--vendor] [--about] [--url] [--auth] [--user] [--theme] [--audience] [-y]`
Start a new document, without a blank page. See
[Your first document](Your-first-document).

### `verba console [--port 8800] [--no-open]`
The management interface, and the easiest way in. See
[Console guide](Console-guide).

### `verba selftest [--live]`
Check this installation. `--live` also signs in and crawls one screen.
