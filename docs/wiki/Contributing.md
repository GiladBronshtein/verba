# Contributing

The full text lives in
[CONTRIBUTING.md](https://github.com/GiladBronshtein/verba/blob/main/CONTRIBUTING.md).
This page is the orientation.

## Run the tests first

```bash
git clone https://github.com/GiladBronshtein/verba.git && cd verba
pip install -e ".[assist,dev]"
python -m playwright install chromium
python tools/selftest.py
```

The suite builds a project from scratch with the wizard and tests the engine
against **that**, rather than against a hand made fixture. An engine whose whole
claim is that it works on a product it has never seen should be tested that way.

## Two rules that are not style preferences

**Nothing may write to the system being documented.** The guard in
`verba/readonly.py` aborts every request that is not GET, HEAD or OPTIONS once
sign in finishes. There is a test that stands up a real server, drives a real
browser at it, clicks a button wired to a `PUT`, and asserts the server received
nothing. If you change anything on the capture path, that test is the one that
matters.

**Nothing decides what a person owns.** The loop applies mechanical changes,
measures the rules afterwards, and puts back anything that made the document
worse. What it cannot justify from evidence it hands back with the reason. A
change that makes the tool guess more confidently is the wrong direction.

## Where things go

| Change | Where |
|---|---|
| A new rule | `verba/lint.py`, with an entry in `REMEDIES` saying what clears it |
| A loop step | `verba/auto.py`, and it must be measured and revertible |
| A model task | `verba/console/assist.py` |
| A console page | `verba/console/static/`, and the page list in `app.js` |
| An output format | `verba/render/` |
| Anything project specific | Your own `content/`, never this package |

A finding without a remedy is a complaint. Every rule that reports to a person
carries what would clear it and whether the system or a person does it.

## Adding a loop step

The contract is small and non negotiable:

1. It must be applied and then measured. `lint` is counted before and after.
2. Anything that raises the count is reverted.
3. If it can rewrite a whole section, it must also pass `_keeps_every_figure`.
   Counting errors is not enough: a rewrite that quietly drops half the figures
   looks like an improvement to a counter, and that is how five sections lost
   fourteen figures in one run.
4. It must be recorded in History with its reasoning.

## The house style, for this repository's own prose

No em dashes. No URLs or route paths in body text. Bullets over prose for list
like content. Say what a thing is for before saying what it does.

The comments in this codebase explain **why**, especially where the obvious
approach was tried and abandoned. Several of them describe a bug that reached
production once. Keep that habit: a comment recording what went wrong is worth
more than one restating what the line does.

## Before you open a pull request

```bash
python3 tools/selftest.py         # the suite
python3 tools/rule_baseline.py    # what the rules say about the corpus
python3 tools/check_links.py      # every link in the README and the wiki
python3 -m ruff check verba tools
```

## Reporting a bug

Include `review/auto.json` from the run, the output of `verba status`, and the
version. If it is a capture problem, `verba incidents --export` writes a brief
that has most of what is needed already.
