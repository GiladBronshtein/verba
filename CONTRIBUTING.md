# Contributing

## Run the tests first

```bash
pip install -e ".[assist,dev]"
python -m playwright install chromium
python tools/selftest.py
```

The suite builds a project from scratch with the wizard and tests the engine
against that, rather than against a hand-made fixture. An engine whose whole
claim is that it works on a product it has never seen should be tested that way.

## Two rules that are not style preferences

**Nothing may write to the system being documented.** The guard in
`verba/readonly.py` aborts every request that is not GET, HEAD or OPTIONS once
sign-in finishes. There is a test that stands up a real server, drives a real
browser at it, clicks a button wired to a `PUT`, and asserts the server received
nothing. If you change anything on the capture path, that test is the one that
matters.

**Nothing decides what a person owns.** The loop applies mechanical changes,
measures the rules afterwards, and puts back anything that made the document
worse. What it cannot justify from evidence it hands back with the reason. A
change that makes the tool guess more confidently is the wrong direction.

## Where things go

- `verba/` is the engine. Nothing in here may know about any particular product.
- `content/` in a project is that project: its sections, screens, masking rules,
  theme and house style.
- `examples/meridian/` is a small fictional admin console so the whole loop can
  be demonstrated without pointing a crawler at a system you do not own.

If you find yourself adding a product's name, a company's palette or one team's
writing conventions to `verba/`, it belongs in `content/` instead. That
separation is the thing that turned this from one company's script into a tool.

## Comments

Explain why, not what. A comment that restates the line above it is noise; a
comment saying what went wrong last time is the reason the code looks like that.
Several in here are load-bearing.

## Before you open a pull request

- `python tools/selftest.py` passes
- `ruff check verba tools` is clean
- `python -m verba --root examples/meridian-docs lint` still passes
- If you fixed a bug, there is a test that fails without your fix. Check it
  actually fails: a regression test that passes both ways proves nothing.
